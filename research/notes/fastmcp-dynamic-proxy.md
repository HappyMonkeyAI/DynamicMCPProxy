# FastMCP Dynamic Proxy Pattern

**URL**: https://dev.to/amartyadev/building-a-dynamic-mcp-proxy-server-in-python-16jf  
**Related**: https://github.com/jlowin/fastmcp  
**Captured**: 2026-06

## What it is
An early exploration of using FastMCP to build a dynamic proxy that can mount other MCP servers at runtime.

## Why it matters
FastMCP's `create_proxy()` + mounting APIs are the foundation of this entire project. The blog post demonstrated the basic "proxy + mount" capability we extended heavily.

## Key observations
- FastMCP makes mounting remote (SSE) servers trivial.
- Stdio / subprocess servers require the `Client(mcp_config_dict)` path (this became [S-02]).
- Tool namespacing via `mount(..., namespace=...)` is automatic (and the source of the "exact names" problem solved by `proxy_list_tools`).

## What we adopted
- The `create_proxy` + `mcp.mount` core loop.
- Reliance on FastMCP to manage client lifecycles.

## What we had to go beyond
- Deferred (stub) loading instead of eager mount at handshake.
- Unmount by directly editing `mcp.providers` (no public unmount API).
- Full stdio discipline, budget/LRU, guardrails, REST loader, plugin scanner, response steering.
- Robust catalogue + matching system on top.

**License / status**: FastMCP is actively maintained (as of 2026).
