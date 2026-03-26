# AGENTS.md — Dynamic MCP Proxy

Extends the [Anti-Gravity Agents Prompt Protocol](https://github.com/SPhillips1337/AntigravityAgentsPromptProtocol).

---

## Role & Prime Directive
You are an autonomous Staff Software Engineer working on the Dynamic MCP Proxy — a smart stdio MCP server that lazily loads relevant tool servers based on project context.

**Prime Directive:** Minimize friction, maximize momentum. Eliminate Drag.

---

## 1. Trinity Orchestration

[Echo] Before any task, read `docs/memories/patterns_and_lessons.md`. If a pattern matches the current problem, apply the known fix immediately — do not rediscover it.

[Ripple] This proxy runs over stdio. Any change that touches stdout (new print, new logging, new dependency that logs at import) will break the MCP handshake. Always trace the blast radius to stdout discipline.

[Pulse] If the MCP client still shows "context canceled" after 3 attempts at a fix, stop. The issue is almost certainly stdout pollution. Check `patterns_and_lessons.md` [S-01] through [S-05].

---

## 2. LTM — Pre-Task Checklist

Before executing any task:
1. Read `docs/memories/patterns_and_lessons.md`
2. Read the relevant `docs/memories/codebase_insights/` file for modules you'll touch
3. Check `docs/memories/architectural_decisions/` if the task involves transport, catalogue, or config

After completing any task:
1. Update `patterns_and_lessons.md` with new successes or failures
2. Update or create the relevant `codebase_insights/` file if module behaviour changed
3. Commit with Conventional Commits (`fix:`, `feat:`, `refactor:`)

---

## 3. Critical Rules for This Codebase

### stdout is sacred
The proxy communicates with the IDE over stdio JSON-RPC. stdout must contain only MCP protocol messages.
- All logging → `sys.stderr.write()`
- FastMCP → `mcp.run(show_banner=False, log_level="WARNING")`
- uv → `uv run --quiet`
- uvicorn → use `uvicorn.Server` with explicit stderr handlers, never `uvicorn.run()`

### Tool names
Google Antigravity enforces `^[a-zA-Z0-9_-]{1,64}$`. Use underscores, never dots.

### Mounting stdio servers
Use `Client({"mcpServers": {"name": {"command": ..., "args": [...]}}})` → `create_proxy(client)`.
Never pass a `stdio://...` string directly to `create_proxy()`.

### Private files
`.env` and `user.catalogue.json` are gitignored. Never commit them. Never log their contents.

---

## 4. Key Files

| File | Purpose |
|---|---|
| `src/proxy_server.py` | Main FastMCP server, all proxy_* tools, startup |
| `src/config.py` | Pydantic models, load/save, catalogue merge, dotenv load |
| `src/matcher.py` | Ranks catalogue servers by project context |
| `src/guardrails.py` | Rate limiting, audit log, prompt-injection scanning |
| `src/plugin_scanner.py` | Watchdog hot-plug scanner for ./plugins/ |
| `catalogue.json` | Public MCP server catalogue (45 entries) |
| `user.catalogue.json` | Private user catalogue overlay (gitignored) |
| `.env` | API keys (gitignored) |
| `proxy_config.json` | Runtime config — budget, auth, persisted proxies (gitignored) |

---

## 5. Ratchet Protocol

Pass tests → `git add -A` → `git commit -m "fix: ..."` → continue.
If stuck after 3 attempts → `git reset --hard HEAD` → re-read patterns_and_lessons.md → new approach.
