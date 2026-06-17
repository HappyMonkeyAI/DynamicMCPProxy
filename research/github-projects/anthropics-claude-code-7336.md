# anthropics/claude-code#7336 — Lazy Loading for MCP Servers and Tools

**URL**: https://github.com/anthropics/claude-code/issues/7336  
**Captured**: 2026-06  
**Type**: GitHub issue (Anthropic Claude Code)

## What it is
Feature request describing how loading every MCP server at startup can consume >50% of the context window (example: 108k tokens out of 200k) before any user message is processed.

## Why it matters
This is the root problem statement that Dynamic MCP Proxy was built to solve in a **client-agnostic** way. The proxy delivers the desired UX (`proxy_handshake` + selective activation + budget) without requiring IDE changes or forks.

## Observations from the issue & discussion
- Users want "just-in-time" activation based on context.
- The ideal shown in the issue is very close to what `proxy_handshake({tech_stack, task_description})` + matcher does.
- Several proposals were client-side only or required forking the host.

## What we did differently (cherry-pick / avoid)
- **Cherry-pick**: The goal of dramatically reducing initial tool token load.
- **Avoid**: Waiting for host changes. We implemented a transparent stdio proxy layer that works today with any MCP client.
- We added strong budget enforcement (LRU), deferred loading, and steering — none of which were specified in the original request.

## Related internal artifacts
- See `README.md` "Related Work" section and "Why the MCP layer..."
- Primary solution pattern: [S-10] Deferred tool-definition loading and the matcher.
