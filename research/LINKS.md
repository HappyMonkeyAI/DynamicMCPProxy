# LINKS.md — Curated External References

High-signal links only. See individual notes in `github-projects/` and `notes/` for details and analysis.

## Core Problem & Related Work
- https://github.com/anthropics/claude-code/issues/7336 — Original "Lazy Loading for MCP Servers and Tools" feature request (the problem this proxy solves client-agnostically)
- https://github.com/machjesusmoto/claude-lazy-loading — Offline registry / token index approach
- https://github.com/block-town/mcp-gateway — Gateway shim approach (3–4 generic tools)

## Key Technologies & Inspiration
- https://github.com/jlowin/fastmcp — FastMCP (the foundation for dynamic mounting)
- https://dev.to/amartyadev/building-a-dynamic-mcp-proxy-server-in-python-16jf — FastMCP dynamic proxy pattern article
- https://github.com/invariantlabs-ai/mcp-scan — Prompt injection / guardrail ideas

## Token Efficiency, Lean Contracts & Routing
- https://github.com/Lap-Platform/LAP — LAP: compiles OpenAPI/GraphQL etc into 5-40× leaner agent-native specs (complementary to MCP)
- https://github.com/decolua/9router — 9router: model router with RTK auto-compression of tool_result outputs (20-40% savings)
- https://github.com/aiming-lab/SimpleMem — SimpleMem: lifelong semantic memory + compression for agent context bloat (has MCP server)

## Code Intelligence & Structural Memory (MCP)
- https://github.com/syncable-dev/memtrace-public — Memtrace: bi-temporal structural knowledge graph of codebases exposed as 25+ MCP tools (very fast local indexing)
- https://github.com/gitnexus/gitnexus — GitNexus: codebase → knowledge graph for agents (comparator in memtrace benchmarks)

## Isolation & Security for Agents
- https://github.com/kubernetes-sigs/agent-sandbox — Kubernetes CRD/controller for isolated stateful AI agent runtimes (strong isolation via gVisor/Kata)
- https://github.com/tizkovatereza/awesome-ai-sandboxes — Curated list of AI/agent sandbox providers and techniques

## Knowledge Bases & MCP Servers
- https://github.com/Beever-AI/beever-atlas — Turns team chats (Slack/Discord/Teams) into LLM wiki + graph with native MCP server (28 tools). Strong auth/rate-limiting model.

## Foundational References
- Agentic Design Patterns (Antonio Gulli, Google) — Free ~424-page hands-on book with chapters on MCP (Ch. 10), Guardrails (Ch. 18), Routing, Tool Use, Memory, Resource-Aware Optimization, Multi-Agent. Code examples throughout. Highly aligned with this project's concerns.

## Protocol & Ecosystem
- https://github.com/SPhillips1337/AntigravityAgentsPromptProtocol — Anti-Gravity Agents Prompt Protocol (LTM, agent contracts)
- https://github.com/SPhillips1337/AntigravityAgentsPromptProtocol/blob/main/BOOTSTRAP.md — LTM bootstrap instructions

## MCP Specification & Clients
- MCP spec and SDKs (official)
- Google Antigravity / Claude Code / Windsurf / opencode MCP support notes (as they evolve)

Add only links that have produced durable observations for this project.
