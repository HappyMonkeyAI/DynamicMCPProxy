# mcp-gateway (block-town) Comparison

**URL**: https://github.com/block-town/mcp-gateway  
**Captured**: 2026-06

## Approach
Replaces the entire tool surface with a small number of generic gateway tools (`gw(service, tool, args)` style). Dispatch happens inside the gateway at call time.

## Why we looked at it
Another attempt to solve tool count explosion and context bloat.

## Key differences / why we diverged
- **Full fidelity vs shim**: mcp-gateway loses the original tool schemas and descriptions. Our proxy preserves the real tool names, descriptions, and input schemas from the mounted servers (just-in-time).
- **Discovery**: Agents using the gateway must know service names and call the shim. Our `tools/list` after `proxy_handshake` contains the actual tools.
- **Client agnosticism**: Both are proxies, but ours works as a drop-in MCP server.
- **Budget control**: We enforce hard total tool count via LRU eviction. Gateway approach avoids the problem by hiding everything behind 3–4 tools.

## What we rejected
- Opaque shims that break agent understanding of available capabilities.
- Requirement to rewrite how agents discover and invoke tools.

## What was useful
- Confirmation that some form of indirection or late binding is necessary for long-running agents.
- Reinforced our decision to keep the real tool surface visible while controlling volume.

See also the comparison table in README.md "Related Work".
