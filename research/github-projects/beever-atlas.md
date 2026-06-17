# Beever Atlas — LLM-Wiki Knowledge Base with Native MCP Server

**URL**: https://github.com/Beever-AI/beever-atlas  
**Docs**: https://docs.beever.ai/atlas  
**Captured**: 2026-06-17 (from ai_bookmarks_master_june_template.csv)  
**License**: Apache 2.0

## What it is
Beever Atlas turns team conversations (Slack, Discord, Microsoft Teams, Mattermost) into a self-maintaining, LLM-powered wiki + knowledge graph. It extracts atomic facts, deduplicates, builds entity graphs (Neo4j), and provides cited answers. Critically, it ships a **native MCP server** (28 tools) so external agents (Claude Code, Cursor, etc.) can directly query the team knowledge base.

## Why it matters to Dynamic MCP Proxy
- **Prime catalogue candidate**: A real-world, production-grade MCP server focused on "organizational memory / knowledge retrieval". Perfect addition to `catalogue.json` under tags like `knowledge`, `wiki`, `team`, `slack`, `memory`, `graph`.
- Demonstrates a **curated, high-value MCP surface** (not dumping every internal API). 28 tools across Discovery, Retrieval, Graph, Session, Orchestration.
- Strong security/auth model for MCP: per-principal (per-agent) API keys, rate limiting, channel-level access control, audit.
- Dual-memory architecture (semantic 3-tier + graph) with smart router — echoes our own response steering + selection logic.
- Has a clean **stdio introspection mode** (zero dependencies) useful for testing and MCP registries.

## Key technical details
- **MCP exposure**:
  - HTTP mount at `/mcp` (with TLS required in prod).
  - Stdio mode: `python -m beever_atlas.api.mcp_server` or `beever-atlas-mcp` (great for local/inspection).
  - Auth via `Authorization: Bearer <key>` from `BEEVER_MCP_API_KEYS`.
- Tool families include `ask_channel` (flagship QA with deep reasoning), fact search, wiki page reading (legacy + new slug-based), graph traversal, activity, media search, etc.
- Ingestion pipeline: 6-stage ADK that distils chat into structured wiki + graph.
- Inspired by Karpathy's observation that LLMs reason better over curated wikis than raw chat logs.

## Cherry-pick opportunities
1. **Catalogue entry**: Add a public entry for Beever Atlas (or similar self-hosted knowledge servers). Include `env_vars` for the necessary keys and example `user.catalogue.json` snippet.
2. **MCP server design patterns**:
   - Curated tool surface instead of full exposure.
   - Principal-scoped access + rate limits per agent (aligns with our guardrails + `proxy_get_metrics`).
   - Stdio "light" mode for discovery/introspection.
3. **Knowledge distillation idea**: Our proxy could eventually benefit from (or expose) similar "distilled wiki" views of tool outputs or project context instead of raw results.
4. **Graph + semantic hybrid**: Inspiration for richer project context in the matcher (beyond current keyword + file ext + requirements).
5. Auth/rate-limit implementation details for multi-tenant or team proxy use.

## What to avoid / differences
- Primarily solves *team chat → structured knowledge* for RAG/QA, not general tool server proxying or lazy activation.
- Heavy stack (Weaviate + Neo4j + Mongo + Redis + FastAPI + ADK). Our proxy deliberately stays lightweight.
- The value is in the *content* it provides via MCP, so listing the server in our catalogue lets agents discover and activate it contextually.

## Practical next step for this project
Add an entry to `catalogue.json` (or document in research) so that when a project context mentions "team knowledge", "slack history", "decisions", "wiki", the matcher can surface Beever Atlas (or equivalent).

See also: memtrace (another rich MCP knowledge server), SimpleMem (memory compression), and the guardrails + MCP chapter in the Agentic Design Patterns book.
