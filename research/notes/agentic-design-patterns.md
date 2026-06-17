# Agentic Design Patterns — Hands-On Guide by Antonio Gulli (Google)

**Author**: Antonio Gulli (Senior Engineering Director at Google)  
**URL / Access**: Free pre-print PDF available (search the title or check linked cdn links in social posts); also on Amazon (royalties to Save the Children). One mirror example: https://irp.cdn-website.com/ca79032a/files/uploaded/Agentic-Design-Patterns.pdf  
**Captured**: 2026-06-17 (from ai_bookmarks_master_june_template.csv social shares)  
**Length**: ~424 pages, code-backed chapters

## What it is
A comprehensive, practical "design patterns" book for building reliable agentic AI systems. Structured like the classic GoF book but for agents. Every major pattern has code examples (often using Google ADK, LangGraph, etc.). It explicitly covers the modern frontier including MCP.

## Table of Contents highlights (most relevant chapters)
**Part One – Foundational**
- Ch 2: Routing
- Ch 5: Tool Use
- Ch 7: Multi-Agent

**Part Two**
- Ch 8: Memory Management
- Ch 10: **Model Context Protocol (MCP)** (16 pages, code)

**Part Four**
- Ch 16: Resource-Aware Optimization
- Ch 18: **Guardrails / Safety Patterns** (19 pages, code)
- Ch 19: Evaluation and Monitoring
- Ch 20: Prioritization

Plus appendices on advanced prompting, frameworks, coding agents, etc.

## Why it matters to Dynamic MCP Proxy
This book directly addresses the exact problems our project solves:
- **MCP chapter (Ch 10)**: Standardized interfaces for tools/agents. Validates our approach of being a smart proxy layer on top of MCP.
- **Guardrails/Safety (Ch 18)**: Our `guardrails.py` (prompt injection scanning, rate limiting, audit) maps directly here.
- **Routing (Ch 2)**: Our `matcher.py` + `proxy_handshake` is a sophisticated form of dynamic routing / tool selection.
- **Tool Use (Ch 5)** + Resource-Aware Optimization (Ch 16): Tool budget, LRU eviction, deferred loading, response steering — all examples of resource-aware and tool-use patterns.
- **Memory Management (Ch 8)**: Complements our steering and lazy activation; relevant to long-running agent sessions using the proxy.
- Multi-agent coordination and inter-agent patterns are useful context since many agents will use our proxy to get their tools.

The book treats MCP as a first-class standardized "USB for agents" for tools.

## Cherry-pick / validation opportunities
1. **Validate & extend our patterns**:
   - Compare our guardrail implementation against the book's recommended safety patterns.
   - Use the routing patterns to improve or document the matcher more formally.
   - Resource-aware optimization ideas to enhance tool budget / eviction logic.

2. **MCP-specific insights**: The dedicated chapter likely discusses best practices for tool servers, discovery, and integration — read for gaps in our `proxy_*` surface or catalogue design.

3. **Documentation & education**: The patterns provide a shared vocabulary. We could reference specific patterns in `CONTEXT.md`, `AGENTS.md`, or ADRs (e.g., "This implements a variant of the Resource-Aware Optimization + Guardrails patterns from Gulli").

4. **Feature ideas**: Reflection, planning, exception handling/recovery, human-in-the-loop, prioritization — some could inspire new `proxy_*` tools or catalogue metadata.

## What to cherry-pick vs avoid
- **Strongly cherry-pick**: The structured pattern language + concrete code for guardrails, routing, resource management, and the MCP treatment.
- The book is broad (full agent systems). Our scope is narrower and focused (stdio MCP proxy for lazy tool loading + budget + steering), so treat it as reference architecture rather than direct code to copy.
- Heavy on Google ADK/LangGraph examples — adapt, don't adopt wholesale.

## Recommended action
- Obtain the free PDF and read at minimum:
  - Chapter 10 (MCP)
  - Chapter 18 (Guardrails/Safety)
  - Chapter 2 (Routing)
  - Chapter 16 (Resource-Aware Optimization)
  - Chapter 5 (Tool Use) and Chapter 8 (Memory)
- Create or update an ADR or section in `patterns_and_lessons.md` / `CONTEXT.md` mapping our design decisions to these patterns.
- Consider adding the book to `research/LINKS.md` and `research/notes/`.

This is high-signal external reference material that aligns closely with the goals of the Dynamic MCP Proxy.
