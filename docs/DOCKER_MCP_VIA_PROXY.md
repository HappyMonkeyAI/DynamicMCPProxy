# Docker MCP Toolkit via Dynamic MCP Proxy

## Problem

Cursor’s `MCP_DOCKER` client talks to `docker mcp gateway` with the **default** profile (~40 catalog servers, including `node-code-sandbox`). Gateway workers leave containers running; over a day they pile up (~70 MB–2 GB reservation each) and starve the desktop.

`docker mcp gateway run` flags that make this worse:

- `--long-lived` — keep containers until gateway exit
- `--static` — pre-start servers
- default `--memory 2Gb` per server

## Approach

1. **Do not** keep the fat Docker MCP gateway always mounted in Cursor.
2. Add **on-demand** entries in `user.catalogue.json` (`docker-mcp-lean`, `docker-mcp-fetch`, …, `docker-mcp-node-sandbox`).
3. Agents call `proxy_activate_server("docker-mcp-lean")` (or a single-server entry), use tools, then `proxy_deactivate_server(...)` so the gateway stdio child exits and containers can be removed.
4. Never pass `--long-lived` / `--static` in catalogue commands.
5. Cap memory (`512Mb` lean / `1Gb` sandbox).
6. Run `scripts/Cleanup-DockerMcp.ps1` when the desktop is already bloated.

## Catalogue entries added

| Name | Role |
| --- | --- |
| `docker-mcp-lean` | `--profile hermes-lean` |
| `docker-mcp-fetch` | `--servers fetch` |
| `docker-mcp-sequentialthinking` | `--servers sequentialthinking` |
| `docker-mcp-duckduckgo` | `--servers duckduckgo` |
| `docker-mcp-time` | `--servers time` |
| `docker-mcp-memory` | `--servers memory` (state lost on deactivate) |
| `docker-mcp-node-sandbox` | `--servers node-code-sandbox` — heavy; activate only when needed |

Public `catalogue.json` already has a non-Toolkit `docker` entry (`npx @modelcontextprotocol/server-docker`) for container management — keep that separate from Toolkit catalog servers.

## Cursor config (`~/.cursor/mcp.json`)

Applied 2026-11-09:

- `MCP_DOCKER` uses `--profile hermes-lean --memory 512Mb --cpus 1` (was `default`).
- `dynamic-mcp-proxy` stdio server added for on-demand `docker-mcp-*` catalogue activation.
- Backup: `mcp.json.bak-20261109-lean`

Do **not** switch `MCP_DOCKER` back to `default` while also activating Toolkit servers through the proxy (duplicate gateways / sticky sandboxes).

## Immediate cleanup

```powershell
pwsh -File C:\Users\steph\happymonkey\DynamicMCPProxy\scripts\Cleanup-DockerMcp.ps1
# optional WP-CLI leftovers:
pwsh -File ...\Cleanup-DockerMcp.ps1 -IncludeWpCli
```

## Related

- DynamicMCPProxy LRU / deactivate: `docs/memories/codebase_insights/proxy_server.md`
- DevHost offload when desktop RAM is critical: MonkeySwarm DevHost allowlist
