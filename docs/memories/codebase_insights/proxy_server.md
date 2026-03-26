# Codebase Insight: proxy_server.py

## Purpose
Main entry point. Owns the FastMCP instance, all `proxy_*` tools, MCP Resources, and the startup lifecycle.

## Key Design Decisions

### Tool Budget + LRU Eviction
`_active_servers` is an `OrderedDict` used as an LRU cache. When a new server would push the total tool count over `tool_budget` (default 50), the least-recently-used server is evicted first. Tool counts come from `CatalogueEntry.estimated_tools` (default 10; heavy hitters like atlassian=72 set explicitly in catalogue.json).

### Mounting Flow
1. `_catalogue_entry_to_proxy()` converts a `CatalogueEntry` to a `ProxyEntry` (stores command as `stdio://...`)
2. `_mcp_config_for_entry()` converts the ProxyEntry to a FastMCP-compatible MCPConfig dict — uses `shlex.split()` for correct handling of paths with spaces
3. `Client(mcp_config)` creates a client using `MCPConfigTransport` which handles subprocess stdio
4. `create_proxy(client)` wraps it as a mountable FastMCP server
5. `mcp.mount(proxy, namespace=entry.name)` exposes its tools prefixed by server name

### Unmounting Flow
FastMCP has no `unmount()` API. Mounted servers appear as `_WrappedProvider` in `mcp.providers`. Each has `_transforms` containing a `Namespace` whose `._prefix` equals the namespace. Unmount by filtering: `mcp.providers[:] = [p for p in mcp.providers if not (hasattr(p, "_transforms") and any(getattr(t, "_prefix", None) == name for t in p._transforms))]`

### Guardrails Integration
All `proxy_*` tools check `check_rate_limit()` at entry when `guardrails_enabled=True`. Result-returning tools apply `truncate_result()` to cap output at 32KB. `scan_tool_description()` is available for scanning mounted tool descriptions.

### Auth Integration
`authenticate()` is called in `api.py`'s `/handshake` endpoint (JWT Bearer or X-API-Key HMAC). When `auth_enabled=False` it returns a guest identity immediately — no-op for dev.

### Custom Proxy Security
`proxy_add_custom_proxy` rejects `runtime="stdio"` to prevent arbitrary command execution via AI-controlled tool calls. Only `sse` and `http` runtimes are accepted for custom proxies.

### LRU Re-use Fix
When `proxy_handshake` finds an already-active server, it calls `_active_servers.move_to_end(name)` before continuing, so frequently used servers aren't incorrectly evicted.

### stdout Discipline
The proxy runs over stdio transport. Nothing may write to stdout except the MCP JSON-RPC layer. All `print()` calls have been replaced with `sys.stderr.write()`. FastMCP banner is suppressed via `show_banner=False`. Log level is WARNING.

## Non-Obvious Dependencies
- `_on_plugin_register` / `_on_plugin_deregister` are callbacks passed to `PluginScanner` — they run in the watchdog observer thread, not the main thread. The `_lock` in `_do_mount`/`_do_unmount` protects `_active_servers`.
- `proxy_handshake` is also called by the optional HTTP sidecar (`api.py`) — it's a plain sync function, safe to call from both contexts.

- **Tool Mounting & Namespacing**: Child servers are mounted using `mcp.mount(proxy, namespace=entry.name)`. FastMCP automatically prefixes all tools from that server with `[namespace]_`.
- **Tool Discovery**: Since FastMCP aggregates all tools, the `await mcp.list_tools()` function returns all tools across all mounted servers, including their proper namespaced prefixes.
- **proxy_list_tools**: This internal proxy tool was added to expose the runtime results of `mcp.list_tools()` because users and LLM agents struggle to guess the exact namespace prefixes (especially if the `name` contains hyphens like `atlassian-mcp-server_`).
