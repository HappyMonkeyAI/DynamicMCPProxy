# Memtrace — Structural + Bi-temporal Code Knowledge Graph (MCP-native)

**URL**: https://github.com/syncable-dev/memtrace-public  
**Site**: memtrace.io (private beta access)  
**Captured**: 2026-06-17 (from ai_bookmarks_master)  
**Stack**: Rust + Tree-sitter, exposes 25+ MCP tools

## What it is
A fast, local, zero-LLM-call indexer that turns a codebase into a rich bi-temporal structural knowledge graph (symbols as nodes, CALLS/IMPORTS/etc as edges, plus full version history). Exposes a large set of specialized MCP tools (find_symbol, get_impact, get_evolution, analyze_relationships, community detection, API topology across repos, etc.). Also ships agent "skills" that auto-activate.

## Why it matters
- **MCP-native server**: Directly relevant as a candidate for our `catalogue.json`. An extremely powerful "code intelligence" MCP server with 25+ tools.
- **Context efficiency**: Claims very low latency (0.07ms queries), tiny RSS (26MB), and "LeanCTX Native" compressed reads + token savings. Aligns perfectly with our tool budget + steering goals.
- **Better project understanding for matching**: Our current `matcher.py` is keyword + tag + file-extension + requirements based. A structural graph of the *actual open project* could enable dramatically smarter `proxy_handshake` decisions (e.g., "this task touches Django ORM and migrations → prioritize postgres + specific servers").
- Temporal features (impact, evolution, changes) are unique and powerful for agents doing real work over time.

## Strong numbers (from their benchmarks)
- Index 1500 files: 1.5s $0 (vs Mem0: 31min + cost)
- Much better recall on callers, impact, etc. vs GitNexus/CodeGrapher.
- 25+ MCP tools + 17 skills.

## Cherry-pick / adopt ideas
1. **Catalogue addition**: Strongly consider adding memtrace (or similar) as a high-value public entry once public. Tag it for "codebase", "python", "refactor", etc.
2. **Matcher evolution**: Use (or run) a lightweight code graph at handshake time (or cache it) to enrich `ProjectContext` with real symbols/imports instead of just keywords and extensions. This would be a major upgrade to relevance ranking.
3. **Response steering inspiration**: Their "LeanCTX" and structural significance budgeting (surface minimum set covering 80% significance) is analogous to our pick/omit + token_budget.
4. **Plugin / hot-plug precedent**: They use skills/plugins that teach agents how to use the tools.
5. Cross-repo API topology could inspire better "integration" servers in catalogue.

## Differences / avoid
- Primarily for *code intelligence inside the agent's working repo*, not general tool server proxying.
- Currently private beta (npm install requires access).
- Heavy focus on coding agents (Cursor, Claude Code, etc.).

## Status
Watch for public release. Even without full integration, the design of deterministic local graph + rich MCP surface + temporal scoring is gold for any context-aware tool system.

Related: GitNexus (another KG indexer, they claim better numbers), codebase-memory-mcp mentions in social.
