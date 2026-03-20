# Dynamic MCP Proxy

A smart MCP proxy server that lazily loads relevant MCP tool servers based on your project context, keeping AI tool counts within recommended limits (≤ 50 tools for Google Antigravity).

Part of the [Anti-Gravity Agents Prompt Protocol](https://github.com/SPhillips1337/AntigravityAgentsPromptProtocol) ecosystem.

## How It Works

```
IDE connects → proxy exposes proxy_* tools + MCP Resources + Prompts
AI calls proxy_handshake({ tech_stack, task_description })
  → Matcher scores catalogue entries
  → Top-5 servers activated (lazily mounted as stdio subprocesses or SSE)
  → tools/list now includes those servers' tools
  → Budget cap (50 tools) enforced via LRU eviction
```

## Quick Start

### Prerequisites

Catalogue servers run via `npx` (Node.js) and `uvx` (uv). These must be on the PATH your IDE uses when spawning the proxy. Add them explicitly in the MCP config `env` block (see below). Find your paths with `type npx` and `type uvx`.

### Install

```bash
uv sync
```

### Configure

Copy the example config:

```bash
cp proxy_config.json.example proxy_config.json
```

Set up your environment and private catalogue:

```bash
cp .env.example .env          # fill in your API keys
# user.catalogue.json is auto-created or copy from your IDE's mcp_config.json
```

### Add to your IDE (Antigravity / opencode / Claude Desktop)

```json
{
  "mcpServers": {
    "dynamic-proxy": {
      "command": "uv",
      "args": [
        "run",
        "--quiet",
        "--project",
        "/path/to/dynamic-mcp-proxy-server",
        "python", "-m", "src.proxy_server"
      ],
      "env": {
        "PATH": "/home/user/.nvm/versions/node/v20.18.1/bin:/home/user/.local/bin:/usr/local/bin:/usr/bin:/bin"
      }
    }
  }
}
```

Adjust `PATH` to match your system (`type npx` and `type uvx` show the right directories).

## proxy_* Tools

| Tool | Description |
|---|---|
| `proxy_handshake(tech_stack, task_description, ...)` | Context handshake — activates relevant servers |
| `proxy_list_active_servers()` | Currently mounted servers + tool counts |
| `proxy_list_available_servers(filter_tag?)` | Browse catalogue |
| `proxy_activate_server(name)` | Explicitly mount a server |
| `proxy_deactivate_server(name)` | Free up tool budget |
| `proxy_add_custom_proxy(name, url, tags, runtime)` | Add an ad-hoc server |
| `proxy_get_metrics()` | Live memory/CPU/uptime metrics |

## MCP Resources

| URI | Description |
|---|---|
| `mcp://proxy/info` | Static metadata (version, capabilities) |
| `mcp://proxy/health` | Live health (uptime, memory, active tools) |
| `mcp://proxy/servers` | Full server inventory (active + available) |

## MCP Discovery Surface

| MCP Method | What the AI Sees |
|---|---|
| `tools/list` | Minimal `proxy_*` management tools |
| `resources/list` + `resources/read` | Live health, proxy info, server inventory |
| `prompts/list` | `suggest_tools_for_context` guided workflow |

## Catalogue

`catalogue.json` — 45 public MCP servers (GitHub, Docker, Postgres, Slack, Stripe, etc.).

`user.catalogue.json` — your private overlay (gitignored). Add personal servers here — local paths, private APIs, custom tools. Entries with the same name override the public catalogue.

```json
[
  {
    "name": "my-server",
    "description": "My private MCP server",
    "command": "python /path/to/server.py",
    "tags": ["custom"],
    "tech_stack": ["any"],
    "runtime": "stdio",
    "env_vars": ["MY_API_KEY"]
  }
]
```

## Environment Variables

`.env` (gitignored) is loaded automatically at startup. Copy `.env.example` to get started:

```bash
cp .env.example .env
```

Keys follow the `env_vars` field in each catalogue entry. Values in real environment variables always take precedence over the `.env` file.

## Configuration

`proxy_config.json` (gitignored, auto-generated with safe defaults):

```json
{
  "tool_budget": 50,
  "auth_enabled": false,
  "guardrails_enabled": true,
  "rate_limit_rpm": 120,
  "catalogue_path": "catalogue.json",
  "audit_log_path": "audit.log"
}
```

Key settings:
- `tool_budget` — max tools exposed at once (default 50, matches Antigravity limit)
- `auth_enabled` — JWT RS256 + HMAC API key auth for production use
- `guardrails_enabled` — prompt-injection scanning + result size caps

## Security

When `auth_enabled = true`:
- JWT (RS256) — set `jwt_public_key_path` to your RSA public key PEM
- HMAC API key — set `hmac_api_key` (passed via `X-API-Key` header)
- Guardrails — 8 prompt-injection pattern checks on all tool descriptions
- Audit log — every tool call logged to `audit.log` (JSON lines)
- Rate limiting — configurable RPM per caller

## Hot-Plug Plugins

Drop any executable MCP server script into `./plugins/`. The proxy detects it via watchdog and registers it live — no restart needed.

## Update the Public Catalogue

```bash
uv run python scripts/sync_catalogue.py
```

## Run Tests

```bash
uv run pytest tests/ -v
```

## Optional HTTP Endpoint

Disabled by default. Enable with `ENABLE_HTTP_SIDECAR=1`:

```bash
curl -X POST http://localhost:8765/handshake \
  -H "Content-Type: application/json" \
  -d '{"tech_stack": ["python", "fastapi"], "task_description": "Building a REST API"}'
```

## Long-Term Memory

This project uses the Anti-Gravity LTM protocol. Agent context lives in `.antigravity/memories/` (gitignored — local to each developer):

- `patterns_and_lessons.md` — solved problems, failure post-mortems
- `codebase_insights/` — module-level hidden knowledge
- `architectural_decisions/` — design tradeoffs and rationale

Bootstrap your local LTM by following [BOOTSTRAP.md](https://github.com/SPhillips1337/AntigravityAgentsPromptProtocol/blob/main/BOOTSTRAP.md) from the protocol repo. See `AGENTS.md` for the full agent protocol.

## Inspiration

- [FastMCP dynamic proxy pattern](https://dev.to/amartyadev/building-a-dynamic-mcp-proxy-server-in-python-16jf)
- [mcp-scan guardrail design](https://github.com/invariantlabs-ai/mcp-scan)
- [Anti-Gravity Agents Prompt Protocol](https://github.com/SPhillips1337/AntigravityAgentsPromptProtocol)
