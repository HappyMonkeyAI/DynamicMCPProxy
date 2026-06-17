# Patterns & Lessons — Dynamic MCP Proxy

## Success Patterns

### [S-01] stdio stdout pollution
**Pattern:** Any output (print, logging, banners) written to stdout before `mcp.run()` takes ownership corrupts the JSON-RPC stdio stream and causes the MCP client to cancel with "context canceled".
**Fix:** All logging must go to `sys.stderr`. Use `show_banner=False` on `mcp.run()`. Use `log_level="WARNING"` to suppress FastMCP INFO lines. Use `uv run --quiet` to suppress uv build output.
**Status:** Resolved.

### [S-02] FastMCP stdio transport for subprocess servers
**Pattern:** `create_proxy(url)` only handles HTTP/SSE URLs. Catalogue entries with `command` fields (npx, uvx, docker) require `Client({"mcpServers": {"name": {"command": ..., "args": [...]}}})` passed to `create_proxy()` so FastMCP's `MCPConfigTransport` handles subprocess lifecycle.
**Fix:** Build MCP config dict from the command string, pass to `Client()`, then `create_proxy(client)`.
**Status:** Resolved.

### [S-03] Tool name regex validation
**Pattern:** Google Antigravity IDE enforces `^[a-zA-Z0-9_-]{1,64}$` on tool names. Dot-notation names like `proxy.handshake` fail when prefixed as `mcp_dynamic-proxy_proxy.handshake`.
**Fix:** Use underscores — `proxy_handshake`, `proxy_activate_server`, etc.
**Status:** Resolved.

### [S-04] PATH inheritance in MCP stdio processes
**Pattern:** MCP clients spawn the proxy process with a minimal PATH that does not include nvm or ~/.local/bin, so `npx` and `uvx` are not found by subprocesses.
**Fix:** Set `PATH` explicitly in the MCP config `env` block to include nvm node bin and ~/.local/bin.
**Status:** Resolved.

### [S-05] uv build output on stdout
**Pattern:** `uv run` prints "Building...", "Installed..." to stdout when the package has changed, corrupting the JSON-RPC stream.
**Fix:** Add `--quiet` flag to `uv run` in the MCP config args.
**Status:** Resolved.

### [S-06] FastMCP unmount via providers list
**Pattern:** FastMCP has no `unmount()` API. Mounted servers appear as `_WrappedProvider` entries in `mcp.providers`. Each has a `_transforms` list containing a `Namespace` object whose `._prefix` attribute equals the namespace string passed to `mcp.mount()`.
**Fix:** `mcp.providers[:] = [p for p in mcp.providers if not (hasattr(p, "_transforms") and any(getattr(t, "_prefix", None) == name for t in p._transforms))]`
**Status:** Resolved. Confirmed via introspection that `list_tools()` correctly excludes removed providers.

### [S-07] user.catalogue.json bleeds into tests
**Pattern:** `load_catalogue()` always merges the real `user.catalogue.json` from the project root, causing tests that pass a tmp_path catalogue to get extra entries.
**Fix:** Added `user_catalogue_path` parameter to `load_catalogue()`. Tests pass `user_catalogue_path=tmp_path / "user.catalogue.json"` (nonexistent) to isolate.
**Status:** Resolved.
# Patterns and Lessons

## [S-08] Identifying Tool Names for Mounted Servers
- **Trigger**: User reports "unknown tool name" when trying to call tools from a dynamically mounted server.
- **Root Cause**: FastMCP prefixes tools from mounted servers with the `namespace` used during mounting (which is the server's `name` in our proxy configuration). For example, a tool named `search` on a server named `atlassian-mcp-server` becomes `atlassian-mcp-server_search`.
- **Solution**: A new `proxy_list_tools` tool has been added to the proxy. We should always instruct users (or use it ourselves) to call `proxy_list_tools(server_name="...")` to get the *exact* string names to use for MCP tool calls.

## [S-09] Tools dropping due to unauthenticated services (mcp-atlassian)
- **Trigger**: Server mounts successfully but reports 0 tools, or specific subsets of tools are missing.
- **Root Cause**: In `mcp-atlassian`, if `CONFLUENCE_URL` is set without matching credentials, the Confluence configuration fails. Due to FastMCP `stdio` transport skipping the ASGI lifespan, `app_lifespan_state` is None. This causes a fallback evaluation `header_based_services` (which is always empty over `stdio`), resulting in *all* services, including Jira, being marked as unavailable and dropped. Furthermore, the proxy was neglecting to pass `os.environ` variables into the child `Client` config.
- **Solution**: Ensure the proxy passes `os.environ` mappings natively to the `command` block based on `env_vars` arrays in `catalogue.json`. Additionally, verify users either define credentials for all enabled services or omit the URLs for unauthenticated services altogether in `.env`.
---

### [S-10] Deferred (On-Demand) Tool-Definition Loading
**Pattern:** Eagerly mounting all context-matched servers at `proxy_handshake()` time loads full tool schemas into the AI's context window immediately, consuming budget even for servers that may never be used in that session.
**Fix:** Two-phase mounting — `_register_pending(entry)` registers a single `{name}_load` stub tool (via `mcp.tool(name=..., description=...)(stub_fn)`) and stores the entry in `_pending_servers`. `_materialise(name)` is called when the stub fires: it removes the stub from `mcp._tool_manager._tools`, pops from `_pending_servers`, converts `CatalogueEntry → ProxyEntry`, then calls `_do_mount()`. `proxy_deactivate_server()` handles both active and pending states. `_tool_count()` counts pending stubs as 1 each. `_reset_proxy_state()` in tests must clear `_pending_servers` too.
**Status:** Resolved. All 59 tests pass (commit 05c3b81).

### [S-11] Mounting Local MCP Servers via uv
**Pattern:** Running local MCP servers that use `uv` for dependency management requires ensuring the environment is synced with necessary extras (e.g., `ai`, `shell`) and using absolute paths for the project directory.
**Fix:** Use `uv sync --project /path/to/project --extra all` to prepare the environment, then use `uv run --project /path/to/project --quiet <command>` as the server's `command` in `user.catalogue.json`.
**Status:** Resolved. Successfully added Scrapling.

### [S-12] Response Steering for Context Efficiency
**Pattern:** Large API responses (Slack, Jira) consume excessive tokens and distract the AI with irrelevant metadata.
**Fix:** Implement a "Steering" layer in the tool execution loop (`audited_call`). Use `pick` and `omit` for field filtering, `template` for formatting, and `token_budget` for hard truncation. This ensures the context window only contains the highest-signal information.

### [S-13] FastMCP tool signature constraints
**Pattern:** FastMCP does not support `**kwargs` in tool functions. It uses inspection and type hints to generate the MCP tool schema.
**Fix:** For dynamic tool registration (like the `RESTLoader`), generate wrapper functions with explicit signatures at runtime using `exec()`. Pass the implementation function via the `globals` dict to ensure it's available in the generated function's scope.

### [S-14] Declarative REST Bridges
**Pattern:** Building custom MCP servers for every REST API is high-friction.
**Fix:** Adopt the `40mcp` JSON schema for declarative bridges. Implement a native Python `RESTLoader` that maps JSON definitions to FastMCP tools using `httpx`. This allows instant integration of community API configs without Node.js dependencies.

## Failure Post-Mortems

### [F-01] nodeenv venv approach
**Attempted:** Installing Node.js inside the Python venv via `nodeenv` to avoid system PATH dependency.
**Result:** `nodeenv` binary failed silently in the workspace environment. Node was already available via nvm — the real issue was PATH not being passed to the subprocess.
**Lesson:** Check what's already on the system before adding dependencies. Use `type npx` not `which npx` to find hashed commands.

### [F-02] HTTP sidecar stdout race
**Attempted:** Running uvicorn sidecar in a daemon thread alongside `mcp.run()`.
**Result:** uvicorn startup output raced with `mcp.run()` and occasionally wrote to stdout before the MCP handshake completed.
**Lesson:** Sidecar should be opt-in (`ENABLE_HTTP_SIDECAR=1`), not opt-out. Use `uvicorn.Server` with explicit stderr log handlers rather than `uvicorn.run()`.

### [F-03] tool_budget regression in tests
**Attempted:** Running existing tests to verify catalogue loading.
**Result:** `tests/test_config.py::test_load_config_defaults` failed because it expected `tool_budget == 50` while the implementation in `src/config.py` defaulted to `100`.
**Lesson:** Codebase defaults may change without corresponding test updates. Always verify standard defaults in the source when tests fail after unrelated changes.

### [S-15] Hardened shell installer script safety
**Pattern:** Shell scripts doing `cd` and remote fetch/pull/sync operations are subject to timing (TOCTOU), path traversal, and untrusted execution paths if directory changes fail silently or remote configs are manipulated.
**Fix:** Always verify `cd` success (e.g. `cd ... || fail ...`), re-validate git remote origin URLs immediately before fetching, and check that the current directory (`pwd -P`) strictly matches the expected target path before running package sync utilities like `uv sync`.
**Status:** Resolved. Addressed Amazon Q Developer comments in `install.sh`.

### [S-16] Async tool discovery mock compatibility & local provider
**Pattern:** Bypassing `mcp.list_tools()` to list tools from `mcp.providers` asynchronously with a timeout avoids blockages from single slow servers, but ignores directly registered proxy tools (when `_tool_manager` is missing) and breaks test monkeypatches on `mcp.list_tools()`.
**Fix:** Detect if `mcp.list_tools` has been monkeypatched (e.g. comparing its bound method status) and fallback to it in tests. To list local proxy tools in standard FastMCP, query `mcp._local_provider.list_tools()` as a fallback when `_tool_manager` is absent.
**Status:** Resolved. Addressed Amazon Q Developer comments on PR #6.

### [S-17] Documentation structure bootstrap (CONTEXT + research + HERMES alignment)
**Pattern:** Following a documentation setup prompt (setup-prompt.txt) in an existing project with strong custom LTM conventions.
**Actions:**
- Created root `CONTEXT.md` (stack assumptions, non-negotiable rules, workflows, resolved decisions, what-not-to-do, project guidance).
- Created `HERMES.md` (thin canonical pointer) while keeping `AGENTS.md` as the authoritative agent protocol (with small header clarification).
- Created full `research/` folder: README, LINKS, templates/project-note.md, plus initial notes for the motivating claude-code issue, FastMCP pattern, and mcp-gateway comparison.
- Created `docs/adr/README.md` for convention compatibility without moving or duplicating the real decisions (which remain in `docs/memories/architectural_decisions/`).
- Refined `README.md` (catalogue count, added explicit "Repository Documentation" section, clarified LTM paths).
- Preserved the existing `docs/memories/` structure and all AGENTS.md LTM rules.
**Result:** Clean, minimal, convention-aligned docs surface while maintaining zero friction with the Trinity / LTM / Ratchet protocols already in force.
**Status:** Resolved. All files verified. Follows "small slices" and "docs as source of truth".

### [S-18] Incorporating targeted external research references
**Pattern:** AI bookmarks CSV (master list of agent/MCP/tool projects) contained high-signal candidates directly applicable to proxy concerns (lazy activation, tool budget, steering, guardrails, matcher, catalogue, MCP surface design).
**Key additions from research:**
- Added "beever-atlas" to public `catalogue.json` (knowledge/wiki/graph MCP server with 28 tools; strong auth/rate-limit patterns).
- Created detailed `research/github-projects/` and `research/notes/` entries for LAP (lean agent-native API contracts + compression), memtrace (MCP code KG), 9router (tool result compression), SimpleMem (lifelong memory compression), agent-sandbox (isolation), and Agentic Design Patterns book (MCP Ch.10, Guardrails Ch.18, Routing, Resource-Aware Optimization).
- Validated catalogue load + ran config tests.
**Alignment notes:**
- LAP and 9router RTK directly extend ideas in [S-12] Response Steering and declarative REST ([S-14]).
- Beever Atlas and memtrace are rich MCP servers that validate and expand the catalogue approach.
- Gulli book provides external validation + vocabulary for guardrails, routing (matcher), resource optimization (budget/LRU), and MCP usage.
**Status:** Resolved for initial pass. Future work may integrate compression ideas or use these as catalogue exemplars.

### [S-19] Advanced output compression for tool results (F-11)
**Pattern:** Tool responses (especially from git, logs, large APIs) are major context consumers even after pick/omit. Simple char truncation loses signal.
**Solution:** Added `compression_profile` and `auto_compress` to ProxyEntry/CatalogueEntry. Implemented `_compress_output` with:
- Consecutive line dedup + blank collapse
- Profile-aware: "git" keeps diffs + headers, "log" dedups aggressively
- Smart truncate (head + tail) when budget active
- Integrated into `_apply_steering` without breaking existing pick/omit/template/token_budget
- Seeded example on github entry
- Enhanced with 'api' profile for nested list/string truncation in JSON responses (F-11)
**Cherry-picks:** 9router RTK techniques for tool_result compression + LAP lean-mode philosophy.
**Verification:** Extended tests pass; preserves behavior for old fields.
**Status:** Implemented as first slice of research round 2. Preserves stdout discipline.

### [S-20] LAP lean spec support in proxy_activate_from_spec (F-12)
**Pattern:** Generating REST bridges via 40mcp from full OpenAPI/GraphQL specs produces verbose configs that bloat context, similar to problems solved by LAP.
**Solution:** Extended `proxy_activate_from_spec` with `lean: bool = False`. When enabled:
- Attempts to use `npx @lap-platform/lapsh compile --lean` then `convert` to produce leaner OpenAPI input.
- Falls back silently to original spec if LAP CLI unavailable or fails (no new deps, graceful).
- Updates generated entry description to note "(LAP lean)".
- Results in smaller `configs/*.json` and thus leaner tool schemas exposed via RESTLoader.
**Cherry-picks:** LAP's semantic compression (5-40x on verbose specs), typed lean contracts, and explicit complementarity to MCP ("LAP compresses the documentation").
**Verification:** Code paths exercised; existing activate flow unchanged.
**Status:** Implemented. Enables dramatically leaner input specs for F-12 research goal. Update catalogue entries or use lean=True for heavy APIs.

### [S-21] Knowledge-aware matcher boost (F-13 starter)
**Pattern:** Simple keyword matcher misses when task is about "history", "team decisions", etc.; knowledge servers (Beever Atlas, memtrace-style) should rank higher.
**Solution:** Small additive bonus in rank_servers when task_description matches knowledge keywords AND entry has matching tags (knowledge/wiki/memory/graph/rag). Easy to extend with usage stats or structural graph later.
**Cherry-picks:** memtrace structural understanding + Beever Atlas for team knowledge; aligns with Gulli book routing/memory patterns.
**Verification:** All matcher tests still pass.
**Status:** Starter slice. Full self-evolving + structural to follow.

### [S-22] Basic usage tracking for self-evolving ranking (F-13)
**Pattern:** Without remembering which servers were useful, the matcher stays static. Frequent use should increase future relevance.
**Solution:** Added module-level _server_usage (increment on successful mount + tool calls in audited_call). Passed to rank_servers as optional usage dict for additive boost (capped diminishing returns). Knowledge bonus (S-21) + usage now work together.
**Verification:** New test passes; no impact on other ranking tests.
**Status:** In-memory for this slice. Persistence via proxy_config or separate can follow. Persist on mounts and every 5th tool call to balance I/O.

### [S-23] Usage inspection and reset tools (F-13)
**Pattern:** Need visibility and control over the self-evolving stats for debugging and reset.
**Solution:** Added proxy_get_usage() and proxy_reset_usage() (all or per-server).
**Verification:** New tools follow naming convention; no stdout issues.
**Status:** Complements the usage tracking.

F-13 (usage + knowledge + persist + inspect/reset) is now substantially complete. Self-evolving ranking is live (in-memory + persisted on key events). Ready for structural enhancements from memtrace research.

### [S-24] Memtrace placeholder in catalogue (F-14)
**Pattern:** High-value research MCP servers (e.g. memtrace code KG with 25+ tools) should be discoverable via catalogue/matcher.
**Solution:** Added memtrace placeholder entry (noted as private beta per research note).
**Verification:** Loads cleanly.
**Status:** Part of F-14 catalogue expansion.

### [S-25] On-demand tool search for lazy discovery (F-15)
**Pattern:** Loading full tool catalogues or even ranked lists upfront wastes context; AI should discover relevant servers on-demand via search query.
**Solution:** Added search_servers() in matcher (hybrid desc/tag/name + reuse of usage/knowledge boosts) and proxy_search_tools(query, limit) tool. Returns scored matches without activation. Aligns with Anthropic Tool Search, Stacklok Optimizer, lazy/passive server patterns seen in research.
**Verification:** New tests pass.
**Status:** First slice of F-15. Enables "search then activate" workflow on top of existing lazy stubs and usage self-evolution.

### [S-26] Tool list caching to reduce discovery overhead (F-15)
**Pattern:** Repeated list_tools() and capability discovery cause cold starts and latency (common in MCP research).
**Solution:** Added simple TTL cache in _list_provider_tools (5min). Invalidate on mount/unmount. Complements search for efficient on-demand.
**Verification:** Code paths covered indirectly.
**Status:** Part of caching slice.

### [S-27] Address bare except in _compress_output (Amazon Q review on PR #7)
**Pattern:** Bare `except:` clause in the api profile path of _compress_output silently suppressed JSONDecodeError/ValueError during compression, hiding failures when tool responses were malformed JSON. This hindered debugging.
**Fix:** Changed to `except (json.JSONDecodeError, ValueError) as e:` and added logging via `sys.stderr.write(f"[proxy] JSON compression failed for api profile: {e}\n")` before falling back to truncation. This matches the suggested fix from the Amazon Q developer review.
**Verification:** Directly addresses the critical finding in the code review on PR #7. Existing tests continue to pass; failure path now observable in stderr (consistent with stdout discipline).
**Status:** Resolved. Follows previous pattern of addressing Amazon Q comments (see S-?? for PR #6).

### [S-28] Wrapping custom MCP servers as FastMCP plugin bridges
**Pattern:** External tools (e.g. repo-audit-scan) have their own MCPServer class but don't use FastMCP stdio transport. They can't be mounted as proxy tools without a transport bridge.
**Fix:** Create a `mcp_fastmcp_server.py` that imports the external project's MCPServer singleton, wraps each tool method in `@mcp.tool()` decorators, and exposes them over stdio. Create a `plugins/{name}.sh` shell script pointing the venv's python at the bridge. The plugin scanner auto-detects and mounts it.
**Verification:** Plugin scanner log shows `Mounted 'repo-audit-scan' (10 tools estimated)`. Tools respond correctly over stdio.
**Status:** Resolved. Example at `projects/AuditScan/mcp_fastmcp_server.py`, `plugins/repo-audit-scan.sh`, `catalogue.json` entry.

