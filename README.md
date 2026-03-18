# Dynamic MCP Proxy

A smart MCP proxy server that **lazily loads relevant MCP tool servers based on your project context**, keeping AI tool counts within recommended limits (≤ 50 tools for Google Antigravity).

## Quick Start

### Install

```bash
cd dynamic-mcp-proxy-server
uv sync
```

### Add to your IDE (Antigravity / opencode / Claude Desktop)

```json
{
  "mcpServers": {
    "dynamic-proxy": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/home/stephen/dynamic-mcp-proxy-server",
        "python", "-m", "src.proxy_server"
      ]
    }
  }
}
```

Once published to PyPI, it simplifies to:
```json
{
  "mcpServers": {
    "dynamic-proxy": {
      "command": "uvx",
      "args": ["dynamic-mcp-proxy"]
    }
  }
}
```

## How It Works

```
IDE connects → proxy exposes proxy.* tools + MCP Resources + Prompts
AI calls proxy.handshake({ tech_stack, task_description })
  → Matcher scores 27 catalogue entries
  → Top-5 servers activated (lazily mounted)
  → tools/list now includes those servers' tools
  → Budget cap (50 tools) enforced via LRU eviction
```

## MCP Discovery Surface (Spec-Compliant)

| MCP Method | What the AI Sees |
|---|---|
| `tools/list` | Minimal `proxy.*` management tools |
| `resources/list` + `resources/read` | Live health, proxy info, server inventory |
| `prompts/list` | `suggest_tools_for_context` guided workflow |

## proxy.* Tools

| Tool | Description |
|---|---|
| `proxy.handshake(tech_stack, task_description, ...)` | Context handshake — activates relevant servers |
| `proxy.list_active_servers()` | Currently mounted servers + tool counts |
| `proxy.list_available_servers(filter_tag?)` | Browse catalogue |
| `proxy.activate_server(name)` | Explicitly mount a server |
| `proxy.deactivate_server(name)` | Free up tool budget |
| `proxy.add_custom_proxy(name, url, tags, runtime)` | Add an ad-hoc server |
| `proxy.get_metrics()` | Live memory/CPU/uptime metrics |

## MCP Resources

| URI | Description |
|---|---|
| `mcp://proxy/info` | Static metadata (version, capabilities) |
| `mcp://proxy/health` | Live health (uptime, memory, active tools) |
| `mcp://proxy/servers` | Full server inventory (active + available) |

## Configuration

Copy `proxy_config.json` (auto-generated with safe defaults on first run):

```json
{
  "tool_budget": 50,
  "auth_enabled": false,
  "guardrails_enabled": true,
  "rate_limit_rpm": 120,
  "catalogue_path": "catalogue.json",
  "audit_log_path": "audit.log",
  "jwt_public_key_path": null,
  "hmac_api_key": null,
  "tool_allowlist": [],
  "tool_denylist": [],
  "proxies": []
}
```

**Key settings:**
- `tool_budget` — max tools exposed at once (default 50, matches Antigravity recommendation)
- `auth_enabled` — set `true` in production; uses JWT RS256 + HMAC API key
- `guardrails_enabled` — prompt-injection scanning + result size caps

## Security

When `auth_enabled = true`:
- **JWT (RS256)** — primary auth; set `jwt_public_key_path` to your RSA public key PEM file
- **HMAC API key** — service-to-service; set `hmac_api_key` (passed via `X-API-Key` header)
- **Guardrails** — 8 prompt-injection pattern checks on all tool descriptions
- **Audit log** — every tool call logged to `audit.log` (JSON lines)
- **Rate limiting** — configurable RPM per caller

## Hot-Plug Plugins

Drop any executable MCP provider script into `./plugins/`. The proxy detects it via `watchdog`, attempts a handshake, and registers it live — no restart needed.

## Update the Catalogue

```bash
uv run python scripts/sync_catalogue.py
```

Fetches the latest server list from [github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) and merges with your existing `catalogue.json`.

## Run Tests

```bash
uv run pytest tests/ -v
```

## Optional HTTP Endpoint

The proxy also starts a minimal FastAPI sidecar on `:8765`:

```bash
curl -X POST http://localhost:8765/handshake \
  -H "Content-Type: application/json" \
  -d '{"tech_stack": ["python", "fastapi"], "task_description": "Building a REST API"}'
```

This pre-warms the proxy before the MCP connection opens. Disable with `DISABLE_HTTP_SIDECAR=1`.

## Inspiration

- [FastMCP dynamic proxy pattern](https://dev.to/amartyadev/building-a-dynamic-mcp-proxy-server-in-python-16jf)  
- [mcp-scan guardrail design](https://github.com/invariantlabs-ai/mcp-scan)