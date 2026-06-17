# CONTEXT.md — Dynamic MCP Proxy

Concise operating manual. Source of truth for stack, rules, decisions, and contributor guidance. Read alongside `AGENTS.md` and `docs/memories/`.

## Stack and Runtime Assumptions
- **Language/Runtime**: Python >= 3.11
- **Core Framework**: FastMCP (FastAPI + MCP stdio/SSE/HTTP)
- **Primary Transport**: stdio JSON-RPC (the proxy itself is an MCP server)
- **Package/Run**: `uv sync` + `uv run --quiet python -m src.proxy_server`
- **Catalogue Servers**: Mostly stdio (`npx -y ...` or `uvx`/`uv run`), some SSE/HTTP, plus `runtime: "rest"` for 40mcp declarative bridges
- **Key Libraries**: fastmcp, pydantic (v2), httpx, watchdog, python-dotenv, PyJWT + cryptography, uvicorn (sidecar only)
- **Config Layers**:
  - `catalogue.json` (public, committed)
  - `user.catalogue.json` (private overlay, gitignored)
  - `.env` (keys, gitignored, loaded with `override=False`)
  - `proxy_config.json` (runtime budget/guardrails/proxies, gitignored)
- **Optional**: HTTP sidecar on `ENABLE_HTTP_SIDECAR=1`

## Non-Negotiable Rules
- **stdout is sacred**. The proxy speaks only MCP JSON-RPC over stdout. Any other output (print, logging, banners, uvicorn startup, uv build messages) before or during handshake causes "context canceled".
  - All logs → `sys.stderr`
  - `mcp.run(show_banner=False, log_level="WARNING")`
  - `uv run --quiet`
  - Use `uvicorn.Server` + stderr handlers (never bare `uvicorn.run()`)
- Tool names must match `^[a-zA-Z0-9_-]{1,64}$`. Never use dots.
- Mount stdio catalogue servers via `Client({"mcpServers": {name: {command, args}}})` then `create_proxy(client)`. Never hand a `stdio://...` string to `create_proxy()`.
- Never commit or log contents of `.env`, `user.catalogue.json`, or `proxy_config.json`.
- Follow the LTM pre-task checklist on every task (see AGENTS.md).
- Guardrails + rate limits are active by default in production configs.

## Workflow Protocols
- **Trinity Orchestration** (AGENTS.md):
  - Echo: read `docs/memories/patterns_and_lessons.md` first; apply known fixes.
  - Ripple: trace every change for stdout impact.
  - Pulse: after 3 "context canceled" failures, stop and audit stdout pollution.
- **LTM Pre/Post Checklist** (required):
  1. Read `patterns_and_lessons.md`
  2. Read relevant `codebase_insights/`
  3. Check `architectural_decisions/` for transport/catalogue/config topics
  - After: update patterns/insights, use Conventional Commits.
- **Ratchet Protocol**: Tests pass → `git add -A` → commit → continue. Stuck after 3 attempts → hard reset + re-read patterns.
- Small slices. Keep implementation and docs aligned.

## Resolved Architecture Decisions
See full records in `docs/memories/architectural_decisions/` and patterns.

- **stdio subprocess mounting** (S-02): Delegate entirely to FastMCP `MCPConfigTransport` via `Client` + `create_proxy()`.
- **Private data separation**: `user.catalogue.json` (overlay) + `.env` (override=False) keeps repo shareable.
- **Deferred mounting** (S-10): Use stub `{name}_load` tools + `_pending_servers` so expensive servers are materialised only on first use.
- **Tool budget + LRU**: `OrderedDict` + `estimated_tools` (with explicit overrides for heavy servers). Evict on `proxy_handshake` / activate when over budget.
- **Response Steering**: `pick`/`omit`/`template`/`token_budget` per catalogue entry applied in `audited_call`.
- **Unmounted providers**: Filter `mcp.providers` by `_transforms` Namespace `_prefix`.
- **REST bridges**: First-class via `runtime: "rest"` + 40mcp JSON configs (no Node dep for many APIs).
- **Plugins**: Watchdog observer hot-plugs executables from `./plugins/`.

## What Not To Do
- Write anything to stdout in the main proxy process or at import time.
- Use `create_proxy("stdio://...")` or raw command strings for mounting.
- Eagerly mount all matched servers at handshake (use deferred stubs).
- Assume npx/uvx are on PATH — explicitly pass full PATH in IDE MCP server `env`.
- Let `user.catalogue.json` bleed into unit tests (use `user_catalogue_path` override).
- Commit secrets or user-specific catalogue entries.
- Use `**kwargs` directly in FastMCP tool functions (use runtime `exec` wrappers for dynamic cases).
- Treat research/ or external links as the source of truth.

## Project-Specific Guidance
- **Matcher**: Keyword + weighted tag/tech_stack overlap (3x), requirements.txt, open file extension inference. Normaliser preserves `+`, `#`, `.`, `-`.
- **Tool namespacing**: Mounted servers are namespaced by their catalogue `name` (e.g. `atlassian-mcp-server_search`). Always call `proxy_list_tools(server_name=...)` to discover exact names.
- **Local uv projects**: In `user.catalogue.json` use `"command": "uv run --project /abs/path --quiet ..."` after `uv sync --project /abs/path --extra all`.
- **Steering is powerful**: Apply `pick` for high-signal fields on Slack/Jira/etc. to stay inside budget.
- **Custom proxies**: Only `sse`/`http` runtimes allowed via `proxy_add_custom_proxy` (stdio would be arbitrary code exec).
- **Tests**: Many use tmp_path isolation and monkeypatch detection. Run with `uv run pytest`.
- **Catalogue updates**: `uv run python scripts/sync_catalogue.py`.
- When adding features, also consider impact on `proxy_inspect_registry`, metrics, and guardrails.

Use the docs (CONTEXT + AGENTS + memories/) as the source of truth for future work. Update them in the same change when decisions shift.
