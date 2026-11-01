# MCP.md — Intent → server routing

**Purpose:** Route work by **intent**, then confirm/activate via live catalogue. Listed ≠ mounted (ADR-0003).

**Rules:**
1. On grounding: read this file + optional `MCP.local.md`.
2. Prefer listed MCP over shell improvisation for matching work.
3. If tools missing: Hermes MCP config **or** `dynamic_mcp_proxy` / `dynamic_proxy` → search → activate → (for vault) `*_load` before search tools. One live check before “unavailable.”
4. No secrets, tokens, or raw connection strings here.
5. Keep this table short. Full catalogue: Dynamic MCP Proxy / MonkeySwarm.

**Related:** [AgentsProtocol](https://github.com/HappyMonkeyAI/AgentsProtocol) `MCP.md` · ADR-0003 · ADR-0005 · skill `mcp-intent-routing`

---

## Core plane (usually always-on on operator host)

| Intent | Server (typical name) | Use when | Notes |
|--------|----------------------|----------|-------|
| Lazy tool belt / activate on-demand | `dynamic_mcp_proxy` / `dynamic_proxy` | Need a server not in session | Search → activate → handshake |
| Host CPU/RAM admission | `resource_sentinel` | Full tests, builds, containers, parallel agents | Snapshot → lease → heartbeat → release |
| Project paths, ports, stack | `launcher_registry` | Port conflicts, locate checkout | Prefer before binding ports |
| Project warm-start / session end | `spine` | Session start Sanity; before stop; Truth Audit | ADR-0005 — `session_brief` / `checkpoint` / `audit`; CLI `spine brief` |
| UI design memory / drift | `spine-design` | UI vs DESIGN.md | `design_brief` → `ensure_capture` → `check_design` |
| Operator prefs / subagent bootstrap | `user_context` | Spawning delegates | Local context root |
| Cross-agent tasks / readiness | `agent_communication` | Delegation, provider readiness | LAN coordination |
| Multi-agent file board | `agent_coordination` | File claims / task board | Does not replace locks |
| Live browser QA (V3) | `browseros` / `browseros_neo` / Playwright | ADR-0001 live exploratory | Real URL + state readback |

---

## On-demand / specialty (activate when intent matches)

| Intent | Server / component | Activate / find via | Protocol hook |
|--------|--------------------|---------------------|---------------|
| **Security / vulnerability audit** | `auditscan` / AuditScan | Hermes or `proxy_activate_server("auditscan")` | Trident **input**, not Owner V2/V3 substitute |
| **Article / tutorial research** | `article_research` | Hermes or proxy activate | Planning / Deep Mode RECON |
| **Structured choice / decision** | `kev` / `kev_157` / `kev-decision-mcp` | Hermes always-on when configured; else proxy | `kev_evaluate` / `kev_permute` / `kev_separate` — not free-form text |
| **Library / API pattern RAG** | `neo4j_semantic_search` / `neo4j-semantic-search` | Hermes direct **or** proxy activate then `*_load` | Codex vault graph; backend often 192.168.5.232 Neo4j+Ollama |
| GitHub issues/PRs | `github` | Hermes or proxy | Prefer over raw `gh` when mounted |
| Browser E2E | `playwright` | Hermes or proxy | Complements browseros |
| Durable wiki notes | project `kb-vault` / basic-memory | path `~/projects/kb-vault` on .215 | Desktop canonical may still be .229 |

---

## Discovery checklist

```text
[ ] Read MCP.md (+ MCP.local.md if present)
[ ] spine: session_brief or `spine brief` (ADR-0005)
[ ] dynamic_mcp_proxy: list/search when tools missing
[ ] resource_sentinel before heavy parallel/build
[ ] launcher_registry: project registered? ports free?
[ ] Domain extras: auditscan / article_research / kev / vault semantic search
[ ] Do not treat empty session tool list as empty fleet
```

## Project notes

- Project slug for Spine/launcher: `dynamic-mcp-proxy`
- Absolute path: `/home/stephen/dynamic-mcp-proxy-server`
- Prefer absolute path if named resolution fails.
