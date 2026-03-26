# Architectural Decision: stdio Transport for Catalogue Servers

**Date:** 2026-03-20
**Status:** Active

## Context
The catalogue contains ~45 servers that run as local subprocesses via `npx` or `uvx`. FastMCP's `create_proxy(url)` only accepts HTTP/SSE URLs. We needed a way to mount these as child servers without reimplementing subprocess management.

## Decision
Use FastMCP's `Client` with an MCPConfig dict (`{"mcpServers": {"name": {"command": ..., "args": [...]}}}`) and pass the connected client to `create_proxy()`. This delegates subprocess lifecycle, stdio pipe management, and session handling entirely to FastMCP's `MCPConfigTransport`.

## Tradeoffs
- Pro: Zero custom subprocess code, FastMCP handles restarts and cleanup
- Pro: Same pattern works for SSE/HTTP servers (just swap command for url)
- Con: Tool counts are estimated (not live-queried at mount time) to keep mounting fast
- Con: Unmounting is soft — tools remain in the namespace until process restart (FastMCP limitation)

## Alternatives Considered
- Custom asyncio subprocess + stdio pipe: Too much complexity, reinventing what FastMCP already does
- nodeenv in venv: Failed silently, unnecessary since node/uv already on system PATH
