"""
Dynamic MCP Proxy Server — main entry point.

Exposes:
  • proxy.* tools    — the minimal always-on management surface
  • MCP Resources    — mcp://proxy/info, mcp://proxy/health, mcp://proxy/servers
  • MCP Prompts      — suggest_tools_for_context

Connect via stdio (standard MCP JSON config) or SSE.

Example MCP config entry:
    {
      "mcpServers": {
        "dynamic-proxy": {
          "command": "uv",
          "args": ["run", "--project", "/path/to/dynamic-mcp-proxy-server",
                   "python", "-m", "src.proxy_server"]
        }
      }
    }
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import logging
logging.basicConfig(stream=sys.stderr)

from fastmcp import FastMCP, Client
from fastmcp.server.server import create_proxy

from .auth import authenticate, AuthError
from .config import (
    AppConfig,
    CatalogueEntry,
    ProxyEntry,
    load_catalogue,
    load_config,
    remove_proxy,
    save_config,
    save_proxy,
)
from .guardrails import (
    audit,
    check_rate_limit,
    init_audit_log,
    init_rate_limiter,
    scan_tool_description,
)
from .matcher import ProjectContext, rank_servers
from .plugin_scanner import PluginScanner

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

_start_time = time.monotonic()
_config: AppConfig = AppConfig()
_catalogue: list[CatalogueEntry] = []

# OrderedDict preserves insertion order and lets us do LRU eviction
# key = server name, value = (ProxyEntry, FastMCP (proxy), tool_count)
_active_servers: OrderedDict[str, tuple[ProxyEntry, Any, int]] = OrderedDict()
_lock = threading.Lock()

# FastMCP main server
mcp = FastMCP(
    name="Dynamic MCP Proxy",
    instructions=(
        "This is a smart proxy that dynamically loads MCP tool servers relevant to "
        "your current project. Start by calling proxy.handshake() with your project "
        "context, or explore mcp://proxy/servers to see what's available."
    ),
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _tool_count() -> int:
    with _lock:
        return sum(tc for _, _, tc in _active_servers.values())


def _evict_lru_if_needed(needed: int = 0) -> None:
    """Unmount the least-recently-used server if budget would be exceeded."""
    while _active_servers:
        current = _tool_count()
        if current + needed <= _config.tool_budget:
            break
        # LRU is the first item in the OrderedDict
        with _lock:
            if not _active_servers:
                break
            name, (entry, proxy, _) = next(iter(_active_servers.items()))
        _do_unmount(name)
        sys.stderr.write(f"[proxy] LRU evicted: {name}\n")


def _estimate_tool_count(entry: ProxyEntry) -> int:
    """
    Best-effort estimate of tools a server will expose.
    Uses catalogue data if available, otherwise assumes 10.
    """
    for cat in _catalogue:
        if cat.name == entry.name:
            # Known heavy hitters
            known = {"atlassian": 72, "hubspot": 30, "zendesk": 25}
            return known.get(cat.name, 10)
    return 10


def _do_mount(entry: ProxyEntry) -> tuple[bool, str]:
    """
    Mount a single ProxyEntry as a child server.
    Returns (success, message).
    """
    if entry.name in _active_servers:
        return False, f"'{entry.name}' is already mounted."

    estimated = _estimate_tool_count(entry)
    _evict_lru_if_needed(needed=estimated)

    try:
        mcp_config = _mcp_config_for_entry(entry)
        client = Client(mcp_config)
        proxy = create_proxy(client)
        mcp.mount(proxy, namespace=entry.name)

        with _lock:
            _active_servers[entry.name] = (entry, proxy, estimated)
            _active_servers.move_to_end(entry.name)

        return True, f"Mounted '{entry.name}' ({estimated} tools estimated)."
    except Exception as exc:
        return False, f"Failed to mount '{entry.name}': {exc}"


def _do_unmount(name: str) -> tuple[bool, str]:
    """Unmount a child server by name. Returns (success, message)."""
    with _lock:
        if name not in _active_servers:
            return False, f"'{name}' is not mounted."
        _active_servers.pop(name)

    # FastMCP does not expose an unmount() API in the current version;
    # we track deactivation in _active_servers and the server will stop
    # being treated as active. Tools previously mounted remain until
    # the proxy process restarts — best-effort for now.
    return True, f"Deregistered '{name}' from active tracking (takes full effect on restart)."


def _resolve_catalogue_entry(name: str) -> Optional[CatalogueEntry]:
    for cat in _catalogue:
        if cat.name == name:
            return cat
    return None


def _catalogue_entry_to_proxy(cat: CatalogueEntry) -> Optional[ProxyEntry]:
    """Convert a CatalogueEntry to a ProxyEntry for mounting."""
    if cat.url:
        return ProxyEntry(name=cat.name, url=cat.url, tags=cat.tags, runtime=cat.runtime)
    if cat.command:
        return ProxyEntry(
            name=cat.name,
            url=f"stdio://{cat.command}",
            tags=cat.tags,
            runtime="stdio",
        )
    return None


def _mcp_config_for_entry(entry: ProxyEntry) -> dict:
    """Build an MCPConfig dict for a ProxyEntry."""
    if entry.runtime in ("sse", "http"):
        return {"mcpServers": {entry.name: {"url": entry.url, "transport": entry.runtime}}}
    # stdio — strip the "stdio://" prefix and split into command + args
    command_str = entry.url.removeprefix("stdio://")
    parts = command_str.split()
    return {"mcpServers": {entry.name: {"command": parts[0], "args": parts[1:]}}}


def _uptime_seconds() -> float:
    return float(round(time.monotonic() - _start_time, 2))


def _memory_mb() -> float:
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return float(round(usage.ru_maxrss / 1024, 2))
    except Exception:
        return 0.0



# ---------------------------------------------------------------------------
# MCP Resources (spec-compliant — always available via resources/list)
# ---------------------------------------------------------------------------

@mcp.resource("mcp://proxy/info")
def resource_info() -> str:
    """Static proxy metadata: name, version, protocol, capabilities."""
    return json.dumps({
        "name": "Dynamic MCP Proxy",
        "version": "0.1.0",
        "protocol": "2024-11-05",
        "transport": "stdio/sse",
        "capabilities": ["tools", "resources", "prompts"],
        "tool_budget": _config.tool_budget,
        "auth_enabled": _config.auth_enabled,
        "guardrails_enabled": _config.guardrails_enabled,
        "catalogue_size": len(_catalogue),
    }, indent=2)


@mcp.resource("mcp://proxy/health")
def resource_health() -> str:
    """Live process health: uptime, memory, CPU time, thread count."""
    return json.dumps({
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptimeSeconds": _uptime_seconds(),
        "memoryUsageMB": _memory_mb(),
        "activeServers": len(_active_servers),
        "activeToolCount": _tool_count(),
        "budgetRemaining": _config.tool_budget - _tool_count(),
        "threads": threading.active_count(),
    }, indent=2)


@mcp.resource("mcp://proxy/servers")
def resource_servers() -> str:
    """Aggregated child server inventory with tool counts and status."""
    with _lock:
        active = [
            {
                "name": name,
                "url": entry.url,
                "tags": entry.tags,
                "runtime": entry.runtime,
                "estimated_tools": tc,
                "status": "active",
            }
            for name, (entry, _, tc) in _active_servers.items()
        ]

    available = [
        {
            "name": cat.name,
            "description": cat.description,
            "tags": cat.tags,
            "tech_stack": cat.tech_stack,
            "runtime": cat.runtime,
            "status": "available",
        }
        for cat in _catalogue
        if cat.name not in _active_servers
    ]

    return json.dumps({
        "active": active,
        "available": available,
        "tool_budget": _config.tool_budget,
        "tools_used": _tool_count(),
    }, indent=2)


# ---------------------------------------------------------------------------
# MCP Prompts (spec-compliant — available via prompts/list)
# ---------------------------------------------------------------------------

@mcp.prompt()
def suggest_tools_for_context() -> str:
    """
    Guided workflow: describe your project context and let the proxy suggest
    and activate the most relevant MCP tool servers.
    """
    return (
        "You are connected to the Dynamic MCP Proxy. Here is how to get the best "
        "tool set for your current work:\n\n"
        "**Step 1**: Call `proxy.handshake` with your project context:\n"
        "```\n"
        "proxy.handshake({\n"
        '  "tech_stack": ["python", "fastapi", "postgres"],\n'
        '  "task_description": "Building a REST API with database access",\n'
        '  "requirements": ["fastapi", "sqlalchemy", "psycopg2"]\n'
        "})\n"
        "```\n\n"
        "**Step 2**: The proxy will respond with a list of activated servers and "
        "their tools. You can now use those tools directly.\n\n"
        "**Step 3**: If you need additional tools, call `proxy.list_available_servers` "
        "to browse the catalogue, then `proxy.activate_server(name=...)` to load more.\n\n"
        "**Step 4**: Check `mcp://proxy/health` (via resources/read) to see your "
        "remaining tool budget at any time."
    )


# ---------------------------------------------------------------------------
# proxy.* tools (always exposed — the minimal management surface)
# ---------------------------------------------------------------------------

@mcp.tool(name="proxy_handshake")
def proxy_handshake(
    tech_stack: list[str],
    task_description: str = "",
    open_files: Optional[list[str]] = None,
    requirements: Optional[list[str]] = None,
) -> str:

    """
    Send your project context to the proxy. It will activate the most relevant
    MCP servers from the catalogue and return a summary of available tools.

    Args:
        tech_stack: Languages and frameworks in use, e.g. ["python", "fastapi", "postgres"]
        task_description: Free-text description of what you are working on
        open_files: File paths currently open in the IDE (optional, helps infer stack)
        requirements: Package names from requirements.txt / package.json (optional)
    """
    t0 = time.monotonic()
    context = ProjectContext(
        tech_stack=tech_stack or [],
        task_description=task_description,
        open_files=open_files or [],
        requirements=requirements or [],
    )

    ranked = rank_servers(context, _catalogue, top_k=5)
    activated: list[str] = []
    skipped: list[str] = []

    for r in ranked:
        entry = _catalogue_entry_to_proxy(r.entry)
        if entry is None:
            continue
        # Skip already-active servers
        if r.entry.name in _active_servers:
            activated.append(r.entry.name)
            continue
        ok, msg = _do_mount(entry)
        if ok:
            activated.append(r.entry.name)
        else:
            skipped.append(f"{r.entry.name}: {msg}")

    latency = float(round((time.monotonic() - t0) * 1000, 1))

    audit(tool="proxy_handshake", outcome="ok", latency_ms=latency,
          extra={"activated": activated})

    result = {
        "activated_servers": activated,
        "skipped": skipped,
        "active_tool_count": _tool_count(),
        "budget_remaining": _config.tool_budget - _tool_count(),
        "context_received": {
            "tech_stack": tech_stack,
            "task_description": task_description[:120] if task_description else "",
        },

        "tip": (
            "Use proxy_list_available_servers() to browse more, "
            "or proxy_activate_server(name) to load specific ones."
        ),
    }
    return json.dumps(result, indent=2)


@mcp.tool(name="proxy_list_active_servers")
def proxy_list_active_servers() -> str:
    """List all currently mounted MCP servers and their estimated tool counts."""
    if not _active_servers:
        return json.dumps({"active_servers": [], "total_tools": 0})

    with _lock:
        servers = [
            {"name": name, "url": entry.url, "tags": entry.tags, "estimated_tools": tc}
            for name, (entry, _, tc) in _active_servers.items()
        ]
    return json.dumps({
        "active_servers": servers,
        "total_tools": _tool_count(),
        "budget": _config.tool_budget,
        "budget_remaining": _config.tool_budget - _tool_count(),
    }, indent=2)


@mcp.tool(name="proxy_list_available_servers")
def proxy_list_available_servers(filter_tag: str = "") -> str:
    """
    List MCP servers in the catalogue that are not yet mounted.

    Args:
        filter_tag: Optional tag to filter by (e.g. "database", "search")
    """
    available = [
        cat for cat in _catalogue
        if cat.name not in _active_servers
        and (not filter_tag or filter_tag.lower() in [t.lower() for t in cat.tags])
    ]
    return json.dumps({
        "available_servers": [
            {
                "name": c.name,
                "description": c.description,
                "tags": c.tags,
                "tech_stack": c.tech_stack,
                "runtime": c.runtime,
                "env_vars_needed": c.env_vars,
            }
            for c in available
        ],
        "count": len(available),
    }, indent=2)


@mcp.tool(name="proxy_activate_server")
def proxy_activate_server(name: str) -> str:
    """
    Activate (mount) a server from the catalogue by name.

    Args:
        name: Server name as shown in proxy.list_available_servers()
    """
    t0 = time.monotonic()
    cat = _resolve_catalogue_entry(name)
    if cat is None:
        # Try persisted custom proxies
        entry = next((p for p in _config.proxies if p.name == name), None)
        if entry is None:
            return json.dumps({"ok": False, "error": f"No server named '{name}' found."})
    else:
        entry = _catalogue_entry_to_proxy(cat)

    ok, msg = _do_mount(entry)
    audit(tool="proxy_activate_server", outcome="ok" if ok else "error",
          latency_ms=float(round((time.monotonic() - t0) * 1000, 1)),
          extra={"server": name})

    return json.dumps({"ok": ok, "message": msg, "active_tool_count": _tool_count()})


@mcp.tool(name="proxy_deactivate_server")
def proxy_deactivate_server(name: str) -> str:
    """
    Deactivate (unmount) a currently loaded server to free up tool budget.

    Args:
        name: Server name as shown in proxy.list_active_servers()
    """
    t0 = time.monotonic()
    ok, msg = _do_unmount(name)
    audit(tool="proxy_deactivate_server", outcome="ok" if ok else "error",
          latency_ms=float(round((time.monotonic() - t0) * 1000, 1)),
          extra={"server": name})

    return json.dumps({"ok": ok, "message": msg, "active_tool_count": _tool_count()})


@mcp.tool(name="proxy_add_custom_proxy")
def proxy_add_custom_proxy(
    name: str,
    url: str,
    tags: Optional[list[str]] = None,
    runtime: str = "sse",
    activate_now: bool = True,
) -> str:

    """
    Register a custom (non-catalogue) MCP server and optionally activate it.

    Args:
        name: A unique identifier for this server
        url: SSE URL (e.g. http://localhost:8100/sse) or stdio:// command
        tags: Tag list for future discovery matching
        runtime: "sse", "http", or "stdio"
        activate_now: If True, mount the server immediately
    """
    entry = ProxyEntry(
        name=name, url=url, tags=tags or [], runtime=runtime, active=activate_now
    )
    save_proxy(entry, _config)

    if activate_now:
        ok, msg = _do_mount(entry)
        return json.dumps({"ok": ok, "message": msg, "persisted": True})

    return json.dumps({"ok": True, "message": f"Registered '{name}' (not yet activated).", "persisted": True})


@mcp.tool(name="proxy_get_metrics")
def proxy_get_metrics() -> str:
    """
    Return live process metrics for the proxy itself.
    Mirrors the mcp://proxy/health resource as a callable tool.
    """
    return resource_health()


# ---------------------------------------------------------------------------
# Startup: mount persisted proxies + scan plugins
# ---------------------------------------------------------------------------

def _on_plugin_register(name: str, command: str) -> None:
    entry = ProxyEntry(name=name, url=f"stdio://{command}", tags=[], runtime="stdio")
    ok, msg = _do_mount(entry)
    sys.stderr.write(f"[plugin_scanner] {msg}\n")


def _on_plugin_deregister(name: str) -> None:
    ok, msg = _do_unmount(name)
    sys.stderr.write(f"[plugin_scanner] {msg}\n")


def _startup() -> None:
    global _config, _catalogue

    _config = load_config()
    _catalogue = load_catalogue(_config)

    init_audit_log(_config)
    init_rate_limiter(_config)

    sys.stderr.write(f"[proxy] Loaded catalogue: {len(_catalogue)} servers.\n")
    sys.stderr.write(f"[proxy] Tool budget: {_config.tool_budget}.\n")

    # Mount persisted active proxies
    for entry in _config.proxies:
        if entry.active:
            ok, msg = _do_mount(entry)
            sys.stderr.write(f"[proxy] Startup mount — {msg}\n")

    # Hot-plug scanner
    plugins_dir = Path(__file__).parent.parent / "plugins"
    scanner = PluginScanner(plugins_dir, _on_plugin_register, _on_plugin_deregister)
    scanner.start()

    sys.stderr.write(f"[proxy] Ready. Active tools: {_tool_count()} / {_config.tool_budget}.\n")


# ---------------------------------------------------------------------------
# Optional HTTP sidecar (POST /handshake only)
# ---------------------------------------------------------------------------

def _start_http_sidecar(port: int = 8765) -> None:
    """Start the optional FastAPI HTTP sidecar in a background thread."""
    try:
        from .api import create_app
        import uvicorn
        import logging as _logging

        # Ensure uvicorn never writes to stdout
        for _name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
            _log = _logging.getLogger(_name)
            if not _log.handlers:
                _h = _logging.StreamHandler(sys.stderr)
                _log.addHandler(_h)
            else:
                for _h in _log.handlers:
                    _h.stream = sys.stderr

        app = create_app(
            config=_config,
            catalogue=_catalogue,
            handshake_fn=proxy_handshake,
        )

        cfg = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning",
                             access_log=False)
        server = uvicorn.Server(cfg)

        def _run():
            import asyncio
            asyncio.run(server.serve())

        t = threading.Thread(target=_run, daemon=True, name="http-sidecar")
        t.start()
        sys.stderr.write(f"[proxy] HTTP sidecar started on http://0.0.0.0:{port}/handshake\n")
    except Exception as exc:
        sys.stderr.write(f"[proxy] HTTP sidecar failed to start: {exc}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    _startup()

    # Start HTTP sidecar only if explicitly enabled
    if os.environ.get("ENABLE_HTTP_SIDECAR", "").lower() in ("1", "true", "yes"):
        http_port = int(os.environ.get("HTTP_PORT", "8765"))
        _start_http_sidecar(http_port)

    mcp.run(show_banner=False, log_level="WARNING")


if __name__ == "__main__":
    main()
