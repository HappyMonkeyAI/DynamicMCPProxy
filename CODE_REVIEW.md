# Dynamic MCP Proxy - Code Review

**🔴 Critical Issues**

1. **Broken Authentication (Placebo Auth)**
   - **Lines:** `src/proxy_server.py` (imports), `src/auth.py`
   - **Problem:** The `authenticate` function is implemented in `src/auth.py` and imported into `src/proxy_server.py`, but it is *never actually called* anywhere in the tool definitions or the HTTP sidecar. Setting `auth_enabled = True` in the configuration does nothing; all endpoints remain fully unprotected.
   - **Solution:** Wrap the FastMCP tools and the FastAPI `/handshake` endpoint with auth checks.
     ```python
     # Example for api.py
     @app.post("/handshake")
     async def handshake(body: HandshakeRequest, request: Request, api_key: str = Security(api_key_header)):
         authenticate(api_key=api_key, config=config)
         # ...
     ```
   - **Rationale:** Without invocation, the dual-layer authentication middleware is a false sense of security, exposing all tools to unauthorized callers.

2. **Inactive Guardrails (Rate Limiting, Injection Detection, Result Truncation)**
   - **Lines:** `src/proxy_server.py` (imports), `src/guardrails.py`
   - **Problem:** Functions like `check_rate_limit`, `scan_tool_description`, and `truncate_result` are defined and imported but never executed. The prompt injection guardrails and rate limiters are completely inactive.
   - **Solution:** Call `check_rate_limit()` at the start of every tool wrapper, and apply `truncate_result()` to the outputs before returning.
   - **Rationale:** Prevents context window exhaustion and prompt injection vulnerabilities, fulfilling the promise of `guardrails_enabled`.

3. **Arbitrary Command Execution via Custom Proxies**
   - **Lines:** `src/proxy_server.py:270` (`proxy_add_custom_proxy`)
   - **Problem:** `proxy_add_custom_proxy` accepts a `url` parameter that can be a `stdio://` command. Since this function executes the command as a subprocess via `Client(mcp_config)`, a compromised AI agent or prompt injection could run arbitrary terminal commands (e.g., `stdio://bash -c "rm -rf /"`).
   - **Solution:** Restrict custom proxies to `sse` or `http` runtimes, or implement a strict validation/allowlist for `stdio` custom commands.
     ```python
     if runtime == "stdio":
         return json.dumps({"ok": False, "error": "stdio runtime is restricted for custom proxies."})
     ```
   - **Rationale:** Running arbitrary shell commands provided dynamically through an AI tool is an immense security risk.

4. **Tools Not Truly Unmounted (Budget Cap Bypass)**
   - **Lines:** `src/proxy_server.py:116` (`_do_unmount`)
   - **Problem:** The code removes the server from `_active_servers` but explicitly notes that FastMCP lacks an `unmount()` API. As a result, the tools are never actually unmounted from FastMCP's internal registries. The client will eventually receive more than 50 tools, silently violating the budget cap and overloading the AI context.
   - **Solution:** Manually pop the tools, resources, and prompts from FastMCP's internal dictionaries for the matching namespace, or submit a feature request/PR to the FastMCP library.
   - **Rationale:** The core feature of the proxy (lazily loading servers to enforce a tool limit) is fundamentally broken if tools persist indefinitely.


**🟡 Suggestions**

1. **Command Parsing Bug for Paths with Spaces**
   - **Lines:** `src/proxy_server.py:145` (`_mcp_config_for_entry`)
   - **Problem:** Using `command_str.split()` will incorrectly break paths or arguments containing spaces (e.g., `stdio://python "my script.py"`).
   - **Solution:** Use Python's built-in `shlex` module.
     ```python
     import shlex
     parts = shlex.split(command_str)
     ```
   - **Rationale:** Ensures command-line arguments are parsed safely and correctly, matching standard shell semantics.

2. **LRU Cache Position Not Updated on Re-use**
   - **Lines:** `src/proxy_server.py:255` (`proxy_handshake`)
   - **Problem:** When `proxy_handshake` processes an already-active server, it skips mounting it but fails to move it to the end of the `_active_servers` OrderedDict. Frequently used servers will thus eventually be incorrectly evicted as "least recently used."
   - **Solution:** Update the LRU cache before continuing.
     ```python
     if r.entry.name in _active_servers:
         with _lock:
             _active_servers.move_to_end(r.entry.name)
         activated.append(r.entry.name)
         continue
     ```
   - **Rationale:** Fixes the LRU eviction logic to correctly represent recent usage.

3. **Loss of Distinct Tech Stacks in Normalization**
   - **Lines:** `src/matcher.py:41` (`_normalise`)
   - **Problem:** `re.sub(r"[^a-z0-9]", "", t.lower())` transforms "C++", "C#", and "C" all into simply `"c"`. This completely breaks stack matching for these languages.
   - **Solution:** Preserve meaningful punctuation characters.
     ```python
     return {re.sub(r"[^a-z0-9+#.-]", "", t.lower()) for t in tokens if t}
     ```
   - **Rationale:** Correctly differentiates between distinct tech stacks like "C++", "C#", and "Node.js".

4. **Information Leakage in HTTP Sidecar**
   - **Lines:** `src/api.py:59` (`handshake`)
   - **Problem:** The `except Exception as exc:` block blindly returns `str(exc)` in a 500 response. This can leak stack traces, internal paths, or API keys.
   - **Solution:** Log the error locally to `sys.stderr.write` and return a generic client error.
     ```python
     except Exception as exc:
         sys.stderr.write(f"[api] Handshake failed: {exc}\n")
         raise HTTPException(status_code=500, detail="Internal server error")
     ```
   - **Rationale:** Adheres to security best practices by sanitizing error responses.

5. **Hardcoded Estimated Tool Counts**
   - **Lines:** `src/proxy_server.py:84` (`_estimate_tool_count`)
   - **Problem:** Tool count estimates are hardcoded (`"atlassian": 72`, etc.) directly in `proxy_server.py`, which is inflexible.
   - **Solution:** Add an `estimated_tools: int = 10` field to the `CatalogueEntry` model in `src/config.py` and populate it through the JSON catalogue.
   - **Rationale:** Keeps the proxy server agnostic and moves domain-specific metadata into the configuration layer.


**✅ Good Practices**

- **Secure HMAC Comparison:** `verify_hmac` in `src/auth.py` correctly uses `hashlib.sha256` and `hmac.compare_digest` to prevent timing attacks when comparing API keys.
- **Graceful Thread Usage:** The HTTP sidecar (`src/proxy_server.py`) intelligently uses `asyncio.run()` within a dedicated `daemon=True` thread. This prevents the FastAPI event loop from blocking the main stdio FastMCP loop.
- **Robust Exception/Default Handling:** `load_config` and `load_catalogue` in `src/config.py` safely catch file read/JSON errors and fall back to safe defaults while writing cleanly to `stderr` (which prevents breaking the MCP stdout protocol).
- **Audit Logging Structure:** `src/guardrails.py` implements audit logging using JSON Lines (`json.dumps() + \n`), making logs easily machine-readable and highly scalable.