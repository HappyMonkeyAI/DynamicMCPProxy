# Codebase Insight: Catalogue & Config

## catalogue.json
~60 (public + user overlay, with research additions like beever-atlas, memtrace placeholder). Each entry has: `name`, `description`, `command` (for stdio), `url` (for SSE/HTTP), `tags`, `tech_stack`, `runtime`, `env_vars`, and optional `estimated_tools`, steering fields.

## user.catalogue.json
Private, gitignored. Contains servers from the user's existing IDE setup (antigravity mcp_config.json). Loaded and merged at startup — user entries override catalogue entries of the same name. This is where personal/local servers live (neo4j, opencode, 21st-magic, scrapling, etc.).

## .env
Private, gitignored. Loaded via `python-dotenv` at import time in `config.py` with `override=False` (real env vars always win). Contains API keys for both catalogue servers (blanked template) and user servers (pre-filled from antigravity config).

## Plugin Scanner (hot-plug)
The `plugin_scanner.py` watches `plugins/` for `*.sh` executables and mounts them automatically as stdio MCP servers. Each `.sh` file points to a FastMCP bridge script. Example:
- `plugins/rep-security-scan.sh` → `projects/repo-security-scan/mcp_server.py` (native FastMCP)
- `plugins/repo-audit-scan.sh` → `projects/AuditScan/mcp_fastmcp_server.py` (custom MCPServer wrapped in FastMCP)

Plugin name is derived from the filename (minus `.sh`). No catalogue entry is needed for plugin scanner mounts, but adding one makes the server discoverable via `proxy_search_tools`.

## Merge Logic (load_catalogue)
1. Load `catalogue.json` (public)
2. Load `user.catalogue.json` (private, optional)
3. User entries overwrite by name, new entries appended
4. Result is the unified catalogue used by the matcher and proxy tools

## proxy_config.json
Runtime config — tool budget, auth settings, guardrails, persisted custom proxies. Also gitignored (contains potential secrets). Auto-generated with safe defaults on first run.
