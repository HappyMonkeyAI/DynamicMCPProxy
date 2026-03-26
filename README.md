# Dynamic MCP Proxy

A smart MCP proxy server that lazily loads relevant MCP tool servers based on your project context, keeping AI tool counts within recommended limits (≤ 50 tools for Google Antigravity).

Part of the [Anti-Gravity Agents Prompt Protocol](https://github.com/SPhillips1337/AntigravityAgentsPromptProtocol) ecosystem.

> **This project is a working, client-agnostic solution to [anthropics/claude-code#7336 — *Feature Request: Lazy Loading for MCP Servers and Tools*](https://github.com/anthropics/claude-code/issues/7336).** See [Related Work](#related-work--problem-context) below.

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

## Related Work & Problem Context

[anthropics/claude-code#7336](https://github.com/anthropics/claude-code/issues/7336) documented a real problem: loading all MCP servers at session startup can consume **54 % of the available context window** (~108k of 200k tokens) before a single message is sent. Several approaches have been proposed or built:

| Project | Approach | Limitation |
|---|---|---|
| [machjesusmoto/claude-lazy-loading](https://github.com/machjesusmoto/claude-lazy-loading) | Offline registry generator — produces a lightweight token index from your MCP config | No runtime injection; explicitly lists *"Automatic lazy loading at runtime"* as needing Claude Code support |
| [block-town/mcp-gateway](https://github.com/block-town/mcp-gateway) | Replaces all tools with 3–4 generic `gw(service, tool, args)` shim tools; dispatches at call time | Hard-coded, requires fork-and-edit per stack; the AI loses full tool type-safety and discovery |
| **This project** | Smart proxy that activates only the servers relevant to the current project context via `proxy_handshake()`, enforces a tool budget via LRU eviction, and is fully dynamic at runtime | Works with *any* MCP client today — no IDE changes required |

### Why the MCP layer is the right place to solve this

1. **Client-agnostic** — the proxy handles lazy loading transparently for any MCP client (Claude Code, Windsurf, Antigravity, opencode, Claude Desktop…), not just one IDE.
2. **`proxy_handshake()` already delivers the "After" UX from the issue** — the feature request's ideal example shows `> Auto-loading: context7, magic [+3.5k tokens]` after detecting keywords in user input. That is exactly what `proxy_handshake({ tech_stack, task_description })` does today.
3. **No fork required** — add servers to `catalogue.json` or `user.catalogue.json`; the matcher and budget enforcement are automatic.

## Inspiration

- [FastMCP dynamic proxy pattern](https://dev.to/amartyadev/building-a-dynamic-mcp-proxy-server-in-python-16jf)
- [mcp-scan guardrail design](https://github.com/invariantlabs-ai/mcp-scan)
- [Anti-Gravity Agents Prompt Protocol](https://github.com/SPhillips1337/AntigravityAgentsPromptProtocol)
