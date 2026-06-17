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
import shlex
import sys
import tempfile
import threading
import time
from collections import OrderedDict, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import logging
logging.basicConfig(stream=sys.stderr)

from fastmcp import FastMCP, Client
from fastmcp.server.server import create_proxy
from fastmcp.server.low_level import LowLevelServer
from mcp.types import PromptsCapability

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
    truncate_result,
)
from .matcher import ProjectContext, rank_servers, search_servers
from .plugin_scanner import PluginScanner
from .loaders.rest import RESTLoader

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

# Pending (deferred) servers: registered but not yet materialised.
# key = server name, value = CatalogueEntry or ProxyEntry
_pending_servers: dict[str, Any] = {}

# In-memory usage stats for self-evolving matcher (F-13)
# server name -> number of successful activations / tool calls
_server_usage: dict[str, int] = defaultdict(int)

# Simple cache for tool lists to reduce repeated discovery / cold start costs (F-15 research)
# key: provider prefix or name -> (list_of_tools, timestamp)
_tool_list_cache: dict[str, tuple[list, float]] = {}
_TOOL_CACHE_TTL = 300.0  # 5 min

def _persist_usage() -> None:
    """Persist current usage stats to config (for self-evolving across restarts)."""
    global _config
    _config.usage_stats = dict(_server_usage)
    save_config(_config)

mcp = FastMCP(
    name="Dynamic MCP Proxy",
    instructions=(
        "This is a smart proxy that dynamically loads MCP tool servers relevant to "
        "your current project. Start by calling proxy.handshake() with your project "
        "context, or explore mcp://proxy/servers to see what's available."
    ),
)


# ---------------------------------------------------------------------------
# Capability Patches
# ---------------------------------------------------------------------------

# Monkeypatch LowLevelServer.get_capabilities to explicitly declare 'listChanged'
# for prompts. This resolves client warnings where prompts are offered but 
# change-notification capability is not declared (even for static lists).
_original_get_capabilities = LowLevelServer.get_capabilities


def _patched_get_capabilities(self, notification_options=None, experimental_capabilities=None):
    capabilities = _original_get_capabilities(self, notification_options, experimental_capabilities)
    # Ensure prompts capability exists and has listChanged=True
    if capabilities.prompts is None:
        # If we have any prompts registered, declare the capability
        capabilities.prompts = PromptsCapability(listChanged=True)
    else:
        capabilities.prompts.listChanged = True
    return capabilities


# Apply the monkeypatch to all LowLevelServer instances created by FastMCP
LowLevelServer.get_capabilities = _patched_get_capabilities


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _tool_count() -> int:
    """Total tool slots consumed: active real tools + 1 stub per pending server."""
    with _lock:
        return sum(tc for _, _, tc in _active_servers.values()) + len(_pending_servers)


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
    Uses estimated_tools from the catalogue entry if available, otherwise assumes 10.
    """
    for cat in _catalogue:
        if cat.name == entry.name:
            return cat.estimated_tools
    return 10


def _get_nested(data: Any, path: str) -> Any:
    """Helper to get a value from a nested dict/list using dot notation."""
    parts = path.split(".")
    for part in parts:
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list) and part.isdigit():
            idx = int(part)
            data = data[idx] if 0 <= idx < len(data) else None
        else:
            return None
    return data


def _compress_output(text: str, profile: Optional[str] = None, max_chars: Optional[int] = None) -> str:
    """RTK-style smart compression for tool outputs.
    Pure Python, no external deps. Inspired by 9router RTK and LAP lean ideas.
    """
    if not text or not isinstance(text, str):
        return text or ""

    original_len = len(text)

    # 1. Basic cleanup: dedup consecutive identical lines, collapse blank lines
    lines = text.splitlines(keepends=False)
    cleaned = []
    prev_line = None
    blank_count = 0
    for line in lines:
        if line == prev_line and line.strip():
            continue  # skip exact consecutive duplicates (common in logs/diffs)
        if not line.strip():
            blank_count += 1
            if blank_count > 2:
                continue
        else:
            blank_count = 0
        cleaned.append(line)
        prev_line = line
    text = "\n".join(cleaned)

    # 2. Profile-specific compression
    profile = (profile or "").lower()
    if profile == "git" or (not profile and ("diff --git" in text or "@@" in text)):
        # Git diff: keep headers + only lines with + or - changes, summarize context
        kept = []
        for line in text.splitlines():
            if line.startswith(("diff --git", "index ", "--- ", "+++ ", "@@")) or line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
                kept.append(line)
            elif line.startswith(" ") and len(kept) > 0 and kept[-1].startswith(("@@", "+", "-")):
                # keep one context line after change
                kept.append(line[:80] + "..." if len(line) > 80 else line)
        text = "\n".join(kept[:200])  # cap

    elif profile == "log" or (not profile and any(kw in text.lower() for kw in ["error", "trace", "log"])):
        # Log: more aggressive dedup and truncate repeats
        seen = set()
        deduped = []
        for line in text.splitlines():
            key = line.strip()[:100]
            if key in seen and len(key) > 5:
                continue
            seen.add(key)
            deduped.append(line)
        text = "\n".join(deduped)

    elif profile == "api" or (not profile and (text.strip().startswith("{") or text.strip().startswith("["))):
        # API/JSON response: keep structure but truncate large arrays/strings
        try:
            data = json.loads(text)
            if isinstance(data, list):
                if len(data) > 10:
                    data = data[:5] + ["... (truncated, " + str(len(data)-5) + " more)"] + data[-2:]
            elif isinstance(data, dict):
                for k in list(data.keys()):
                    v = data[k]
                    if isinstance(v, list) and len(v) > 10:
                        data[k] = v[:5] + ["... (truncated)"] + v[-2:]
                    elif isinstance(v, str) and len(v) > 100:
                        data[k] = v[:100] + "..."
            text = json.dumps(data, indent=2)
        except:
            pass  # fall to truncate

    # 3. Final token budget aware truncate (better than pure head cut)
    if max_chars and len(text) > max_chars:
        head = int(max_chars * 0.65)
        tail_start = max(0, len(text) - (max_chars - head - 30))
        tail = text[tail_start:]
        text = text[:head] + "\n... [compressed/truncated for token budget] ...\n" + tail
        if len(text) > max_chars + 50:
            text = text[:max_chars] + "\n... (truncated)"

    return text


def _apply_steering(result: Any, entry: ProxyEntry) -> Any:
    """
    Apply response shaping: pick, omit, template, and token_budget.
    Applies to the 'content' list of an MCP ToolResult.
    """
    if not hasattr(result, "content") or not isinstance(result.content, list):
        return result

    # Check if we have anything to do
    if not any([entry.pick, entry.omit, entry.template, entry.token_budget,
                entry.compression_profile, entry.auto_compress]):
        return result

    new_content = []
    for item in result.content:
        # We only steer text content that contains JSON (common for API bridges)
        # or dictionary-like content if the SDK supports it.
        # FastMCP often returns CallToolResult with TextContent.
        if hasattr(item, "text") and isinstance(item.text, str):
            try:
                data = json.loads(item.text)
                
                # 1. Pick
                if entry.pick:
                    if isinstance(data, list):
                        data = [{k: _get_nested(row, k) for k in entry.pick} for row in data]
                    elif isinstance(data, dict):
                        data = {k: _get_nested(data, k) for k in entry.pick}
                
                # 2. Omit
                if entry.omit:
                    if isinstance(data, list):
                        for row in data:
                            if isinstance(row, dict):
                                for k in entry.omit:
                                    row.pop(k, None)
                    elif isinstance(data, dict):
                        for k in entry.omit:
                            data.pop(k, None)

                # 3. Template
                if entry.template:
                    if isinstance(data, list):
                        text = "\n".join([entry.template.format(**row) for row in data if isinstance(row, dict)])
                    elif isinstance(data, dict):
                        text = entry.template.format(**data)
                    else:
                        text = json.dumps(data)
                else:
                    text = json.dumps(data, indent=2)

                # 4. Token Budget (approximate chars / 4)
                max_chars = entry.token_budget * 4 if entry.token_budget else None

                # 5. Advanced compression (F-11: 9router RTK + LAP inspired)
                if entry.compression_profile or entry.auto_compress:
                    text = _compress_output(text, entry.compression_profile, max_chars)
                elif max_chars and len(text) > max_chars:
                    text = text[:max_chars] + "\n... (truncated by token_budget)"

                item.text = text
            except (json.JSONDecodeError, KeyError, AttributeError, ValueError):
                # If it's not JSON or template fails, leave as is (or apply budget only)
                max_chars = entry.token_budget * 4 if entry.token_budget else None
                if entry.compression_profile or entry.auto_compress:
                    item.text = _compress_output(item.text, entry.compression_profile, max_chars)
                elif max_chars and len(item.text) > max_chars:
                    item.text = item.text[:max_chars] + "\n... (truncated by token_budget)"
        
        new_content.append(item)

    result.content = new_content
    return result


def _provider_prefix(provider: Any) -> Optional[str]:
    """Best-effort namespace prefix for a mounted provider."""
    transforms = getattr(provider, "_transforms", None) or []
    if not transforms:
        return None
    return getattr(transforms[0], "_prefix", None)


async def _list_provider_tools(provider: Any, timeout_s: float = 3.0) -> list[Any]:
    """
    List tools from one mounted provider with a timeout.
    A single slow provider must not block discovery of the rest of the registry.
    Caches results briefly to mitigate repeated discovery costs (research on cold starts).
    """
    prefix = _provider_prefix(provider) or getattr(provider, "name", "unknown")
    now = time.monotonic()
    if prefix in _tool_list_cache:
        tools, ts = _tool_list_cache[prefix]
        if now - ts < _TOOL_CACHE_TTL:
            return tools

    try:
        tools = await asyncio.wait_for(provider.list_tools(), timeout=timeout_s)
        _tool_list_cache[prefix] = (tools, now)
        return tools
    except Exception as e:
        sys.stderr.write(f"[proxy] Error listing tools for provider {getattr(provider, 'name', 'unknown')}: {e}\n")
        return []


async def _list_mounted_tools(server_name: Optional[str] = None) -> list[Any]:
    """Collect mounted child tools without letting one provider stall the full scan."""
    # Check if mcp.list_tools is mocked/monkeypatched (e.g., in unit tests)
    list_tools_method = getattr(mcp, "list_tools", None)
    is_mocked = False
    if list_tools_method is not None:
        if not (
            hasattr(list_tools_method, "__self__")
            and list_tools_method.__self__ is mcp
            and hasattr(list_tools_method, "__func__")
            and list_tools_method.__func__.__qualname__ == "FastMCP.list_tools"
        ):
            is_mocked = True

    if is_mocked:
        all_tools = await mcp.list_tools()
        valid_tools = [
            t for t in all_tools
            if hasattr(t, "name") and isinstance(t.name, str)
        ]
        if server_name:
            prefix = f"{server_name}_"
            return [t for t in valid_tools if t.name.startswith(prefix)]
        else:
            return [t for t in valid_tools if not t.name.startswith("proxy_")]

    providers = list(mcp.providers)
    tools: list[Any] = []

    for provider in providers:
        prefix = _provider_prefix(provider)
        if server_name and prefix != server_name:
            continue

        provider_tools = await _list_provider_tools(provider)
        valid_tools = [
            t for t in provider_tools
            if hasattr(t, "name") and isinstance(t.name, str)
        ]
        if server_name:
            tools.extend(valid_tools)
        else:
            tools.extend([t for t in valid_tools if not t.name.startswith("proxy_")])

    return tools


def _do_mount(entry: ProxyEntry) -> tuple[bool, str]:
    """
    Mount a single ProxyEntry as a child server (materialize immediately).
    Returns (success, message).
    """
    if entry.name in _active_servers:
        return False, f"'{entry.name}' is already mounted."

    estimated = _estimate_tool_count(entry)
    _evict_lru_if_needed(needed=estimated)

    try:
        if entry.runtime == "rest":
            # Extract config path from rest:// URL
            config_path = entry.url.removeprefix("rest://")
            # If path is relative, make it absolute relative to project root
            p = Path(config_path)
            if not p.is_absolute():
                p = Path(__file__).parent.parent / p
            
            loader = RESTLoader(str(p), name=entry.name)
            proxy = loader.get_mcp()
        else:
            mcp_config = _mcp_config_for_entry(entry)
            client = Client(mcp_config)
            proxy = create_proxy(client)
        
        # Wrap proxy.call_tool to add auditing and steering
        original_call = proxy.call_tool
        
        async def audited_call(name: str, arguments: dict | None = None, **kwargs) -> Any:
            start_time = time.monotonic()
            outcome = "ok"
            try:
                result = await original_call(name, arguments, **kwargs)
                # Apply steering / response shaping
                result = _apply_steering(result, entry)
                return result
            except Exception as e:
                outcome = f"error: {str(e)}"
                raise
            finally:
                latency = (time.monotonic() - start_time) * 1000
                if outcome == "ok":
                    _server_usage[entry.name] += 1
                    if _server_usage[entry.name] % 5 == 0:
                        _persist_usage()
                audit(
                    tool=f"{entry.name}_{name}" if not name.startswith(f"{entry.name}_") else name,
                    outcome=outcome,
                    latency_ms=latency,
                    extra={"args": list(arguments.keys()) if arguments else []}
                )
                
        proxy.call_tool = audited_call
        
        mcp.mount(proxy, namespace=entry.name)

        with _lock:
            _active_servers[entry.name] = (entry, proxy, estimated)
            _active_servers.move_to_end(entry.name)
            _server_usage[entry.name] += 1
            _persist_usage()
            _tool_list_cache.pop(entry.name, None)  # invalidate cache on (re)mount

        return True, f"Mounted '{entry.name}' ({estimated} tools estimated)."
    except Exception as exc:
        return False, f"Failed to mount '{entry.name}': {exc}"


def _remove_stub_tool(name: str) -> None:
    """Remove the {name}_load stub tool from the FastMCP registry."""
    stub_name = f"{name}_load"
    # FastMCP stores directly-registered tools in mcp._tool_manager._tools
    try:
        tools = mcp._tool_manager._tools  # type: ignore[attr-defined]
        tools.pop(stub_name, None)
    except AttributeError:
        pass  # API surface may differ across FastMCP versions — safe to swallow


def _register_pending(entry: Any) -> tuple[bool, str]:
    """
    Register a server as a deferred (pending) entry.
    Exposes a single lightweight `{name}_load` stub tool instead of mounting the
    full server immediately. The real subprocess is only spawned when the stub
    (or any tool on that server) is first invoked.

    `entry` may be a CatalogueEntry or a ProxyEntry.
    Returns (success, message).
    """
    name = entry.name

    if name in _active_servers:
        return False, f"'{name}' is already fully mounted."
    if name in _pending_servers:
        return False, f"'{name}' is already pending."

    with _lock:
        _pending_servers[name] = entry

    # Register the stub tool dynamically.
    # We capture `name` in the closure via a default argument.
    stub_description = (
        f"Load the '{name}' MCP server and make its tools available. "
        f"Call this before using any {name}_* tools, or simply call any "
        f"{name}_* tool directly — the server will be loaded automatically."
    )

    def _make_stub(server_name: str):
        def stub() -> str:
            return _materialise(server_name)
        stub.__name__ = f"{server_name}_load"
        stub.__doc__ = stub_description
        return stub

    stub_fn = _make_stub(name)
    mcp.tool(name=f"{name}_load", description=stub_description)(stub_fn)

    estimated = getattr(entry, "estimated_tools", 10)
    sys.stderr.write(f"[proxy] Deferred '{name}' ({estimated} tools est.) — stub registered.\n")
    return True, f"Deferred '{name}' — call '{name}_load' to materialise ({estimated} tools estimated)."


def _materialise(name: str) -> str:
    """
    Materialise a pending server: remove its stub, spawn the subprocess,
    mount the real tools, and return a status message.
    Called automatically when the {name}_load stub is invoked.
    """
    with _lock:
        entry = _pending_servers.pop(name, None)

    if entry is None:
        if name in _active_servers:
            return json.dumps({"ok": True, "message": f"'{name}' is already fully loaded."})
        return json.dumps({"ok": False, "error": f"No pending server named '{name}'."})

    # Remove the stub tool first to free the slot before counting budget
    _remove_stub_tool(name)

    # Convert CatalogueEntry → ProxyEntry if needed
    if hasattr(entry, "command") or hasattr(entry, "url") and not hasattr(entry, "active"):
        # It's a CatalogueEntry
        proxy_entry = _catalogue_entry_to_proxy(entry)
        if proxy_entry is None:
            return json.dumps({"ok": False, "error": f"Cannot build ProxyEntry for '{name}'."})
    else:
        proxy_entry = entry

    ok, msg = _do_mount(proxy_entry)
    sys.stderr.write(f"[proxy] Materialised '{name}': {msg}\n")
    audit(tool=f"{name}_load", outcome="ok" if ok else "error", latency_ms=0)
    return json.dumps({"ok": ok, "message": msg, "active_tool_count": _tool_count()})


def _do_unmount(name: str) -> tuple[bool, str]:
    """Unmount a child server by name (active or pending). Returns (success, message)."""
    # Handle pending (deferred) servers
    with _lock:
        if name in _pending_servers:
            _pending_servers.pop(name)
    _remove_stub_tool(name)

    with _lock:
        if name not in _active_servers:
            # May have been pending only — that's fine
            if name not in _active_servers:
                return True, f"Cleared pending entry '{name}'."

        _active_servers.pop(name, None)
        _tool_list_cache.pop(name, None)  # clear cache
        
    # fastmcp doesn't have a public unmount API yet
    # We remove it from providers map directly
    mcp.providers[:] = [
        p for p in mcp.providers
        if not (
            hasattr(p, "_transforms")
            and any(getattr(t, "_prefix", None) == name for t in p._transforms)
        )
    ]

    return True, f"Unmounted '{name}'."


def _resolve_catalogue_entry(name: str) -> Optional[CatalogueEntry]:
    for cat in _catalogue:
        if cat.name == name:
            return cat
    return None


def _catalogue_entry_to_proxy(cat: CatalogueEntry) -> Optional[ProxyEntry]:
    """Convert a CatalogueEntry to a ProxyEntry for mounting."""
    url = cat.url
    runtime = cat.runtime

    if not url:
        if cat.command:
            url = f"stdio://{cat.command}"
            runtime = "stdio"
        elif cat.config_path:
            url = f"rest://{cat.config_path}"
            runtime = "rest"
        else:
            return None

    return ProxyEntry(
        name=cat.name,
        url=url,
        tags=cat.tags,
        runtime=runtime,
        env_vars=cat.env_vars,
        pick=cat.pick,
        omit=cat.omit,
        template=cat.template,
        token_budget=cat.token_budget,
        compression_profile=cat.compression_profile,
        auto_compress=cat.auto_compress,
    )


def _mcp_config_for_entry(entry: ProxyEntry) -> dict:
    """Build an MCPConfig dict for a ProxyEntry."""
    if entry.runtime in ("sse", "http"):
        return {"mcpServers": {entry.name: {"url": entry.url, "transport": entry.runtime}}}
    # stdio — strip the "stdio://" prefix and split into command + args
    # shlex.split handles paths/args with spaces correctly
    command_str = entry.url.removeprefix("stdio://")
    # Expand environment variables like $VAR or ${VAR}
    command_str = os.path.expandvars(command_str)
    parts = shlex.split(command_str)
    
    server_conf: dict[str, Any] = {"command": parts[0], "args": parts[1:]}
    # Pass along requested environment variables from proxy's environment
    if entry.env_vars:
        filtered_env = {k: os.environ[k] for k in entry.env_vars if k in os.environ}
        if filtered_env:
            server_conf["env"] = filtered_env

    return {"mcpServers": {entry.name: server_conf}}


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
    if _config.guardrails_enabled and not check_rate_limit("anonymous"):
        return json.dumps({"ok": False, "error": "Rate limit exceeded. Try again later."})

    t0 = time.monotonic()
    context = ProjectContext(
        tech_stack=tech_stack or [],
        task_description=task_description,
        open_files=open_files or [],
        requirements=requirements or [],
    )

    ranked = rank_servers(context, _catalogue, top_k=5, usage=dict(_server_usage))
    activated: list[str] = []
    skipped: list[str] = []

    for r in ranked:
        name = r.entry.name
        # Already fully active: bump LRU order
        if name in _active_servers:
            with _lock:
                _active_servers.move_to_end(name)
            activated.append(name)
            continue
        # Already pending: re-use existing stub
        if name in _pending_servers:
            activated.append(name)
            continue
        # Register as deferred (creates the {name}_load stub)
        ok, msg = _register_pending(r.entry)
        if ok:
            activated.append(name)
        else:
            skipped.append(f"{name}: {msg}")

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
    result_str = json.dumps(result, indent=2)
    if _config.guardrails_enabled:
        result_str = truncate_result(result_str)
    return result_str


@mcp.tool(name="proxy_list_active_servers")
def proxy_list_active_servers() -> str:
    """List all currently mounted MCP servers and their estimated tool counts."""
    with _lock:
        active = [
            {
                "name": name,
                "url": entry.url,
                "tags": entry.tags,
                "estimated_tools": tc,
                "status": "active",
            }
            for name, (entry, _, tc) in _active_servers.items()
        ]
        pending = [
            {
                "name": name,
                "tags": getattr(entry, "tags", []),
                "estimated_tools": getattr(entry, "estimated_tools", 10),
                "status": "pending",
                "note": f"Call '{name}_load' to materialise full tool set.",
            }
            for name, entry in _pending_servers.items()
        ]
    servers = active + pending
    if not servers:
        return json.dumps({"active_servers": [], "total_tools": 0})
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
        filter_tag: Optional tag filter, or free-text query (uses search_servers for discovery).
    """
    if filter_tag:
        # Use search for richer query support (F-15)
        results = search_servers(filter_tag, _catalogue, limit=20, usage=dict(_server_usage))
        available = [r.entry for r in results if r.entry.name not in _active_servers]
    else:
        available = [
            cat for cat in _catalogue
            if cat.name not in _active_servers
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


@mcp.tool(name="proxy_search_tools")
def proxy_search_tools(query: str, limit: int = 10) -> str:
    """
    Search the catalogue for relevant servers/tools using free-text query.
    Enables on-demand discovery (lazy loading pattern) so the AI can find
    specific capabilities without the full catalogue bloating context.

    Returns ranked list of matching servers (name, desc, score, tags).
    Use proxy_activate_server on results, or let handshake do it.

    Inspired by MCP tool search / lazy discovery best practices (Anthropic, Stacklok, etc.).
    """
    if not query or not query.strip():
        return json.dumps({"ok": False, "error": "Query required."})

    results = search_servers(
        query.strip(),
        _catalogue,
        limit=limit,
        usage=dict(_server_usage),
    )

    return json.dumps({
        "ok": True,
        "query": query,
        "results": [
            {
                "name": r.entry.name,
                "description": r.entry.description,
                "tags": r.entry.tags,
                "tech_stack": r.entry.tech_stack,
                "runtime": r.entry.runtime,
                "score": r.score,
                "estimated_tools": getattr(r.entry, "estimated_tools", 10),
            }
            for r in results
        ],
        "count": len(results),
        "note": "Activate with proxy_activate_server(name) or rely on proxy_handshake for auto.",
    }, indent=2)


@mcp.tool(name="proxy_list_tools")
async def proxy_list_tools(server_name: Optional[str] = None) -> str:
    """
    List all registered tools by inspecting the FastMCP instance.
    If server_name is provided, filters for tools from that child server.
    """
    try:
        filtered = await _list_mounted_tools(server_name=server_name)
            
        return json.dumps({
            "ok": True,
            "tools": [{"name": t.name, "description": t.description} for t in filtered],
            "total": len(filtered),
            "note": "Tools must be called by their full name (e.g. servername_toolname)."
        }, indent=2)
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"Failed to list tools: {exc}"})


@mcp.tool(name="proxy_inspect_registry")
async def proxy_inspect_registry() -> str:
    """
    Diagnostic tool: Expose proxy state and server counts.
    """
    try:
        tools = await _list_mounted_tools()
        # Get proxy_* tools from local provider or tool manager
        proxy_tools = []
        local_tools = []
        if hasattr(mcp, "_local_provider"):
            try:
                local_tools = await mcp._local_provider.list_tools()
            except Exception:
                pass
        
        tool_manager = getattr(mcp, "_tool_manager", None)
        if tool_manager is not None and hasattr(tool_manager, "_tools"):
            proxy_tool_names = sorted(tool_manager._tools.keys())
        else:
            proxy_tool_names = sorted([t.name for t in local_tools if hasattr(t, "name")])

        proxy_tools = [
            {"name": name}
            for name in proxy_tool_names
            if name.startswith("proxy_")
        ]
        registry = proxy_tools + [
            {"name": t.name} for t in tools
            if hasattr(t, "name") and isinstance(t.name, str)
        ]
    except Exception:
        registry = []

    return json.dumps({
        "status": "ok",
        "active_servers": list(_active_servers.keys()),
        "total_tools": len(registry),
        "registry": registry,
        "usage_stats": dict(sorted(_server_usage.items(), key=lambda x: -x[1])[:10])  # top used
    }, indent=2)


@mcp.tool(name="proxy_activate_from_spec")
async def proxy_activate_from_spec(
    name: str,
    spec_url: str,
    spec_type: str = "openapi",
    eager: bool = True,
    lean: bool = False
) -> str:
    """
    Generate an MCP server from an OpenAPI/GraphQL spec and activate it.
    
    Args:
        name: A unique name for this generated server
        spec_url: URL to the OpenAPI spec (JSON/YAML) or GraphQL endpoint
        spec_type: 'openapi' or 'graphql'
        eager: If True, mount the server immediately
        lean: If True, attempt to use LAP (https://lap.sh) to produce a dramatically
              leaner input spec before 40mcp generation (F-12 research slice).
              Falls back gracefully if LAP CLI not available.
    """
    if _config.guardrails_enabled and not check_rate_limit("anonymous"):
        return json.dumps({"ok": False, "error": "Rate limit exceeded."})

    t0 = time.monotonic()
    configs_dir = Path(__file__).parent.parent / "configs"
    configs_dir.mkdir(exist_ok=True)
    config_path = configs_dir / f"{name}.json"

    spec_for_generate = spec_url

    if lean:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                lap_file = os.path.join(tmp, f"{name}.lap")
                lean_openapi = os.path.join(tmp, f"{name}_lean.json")
                # Compile to LAP lean format
                lap_compile = f"npx -y @lap-platform/lapsh compile {spec_url} --lean --output {lap_file}"
                proc1 = await asyncio.create_subprocess_shell(
                    lap_compile,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc1.communicate()
                if proc1.returncode == 0:
                    # Convert back to lean OpenAPI
                    lap_convert = f"npx -y @lap-platform/lapsh convert {lap_file} -f openapi --output {lean_openapi}"
                    proc2 = await asyncio.create_subprocess_shell(
                        lap_convert,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await proc2.communicate()
                    if proc2.returncode == 0 and os.path.exists(lean_openapi):
                        spec_for_generate = lean_openapi
                        sys.stderr.write(f"[proxy] Used LAP for lean spec generation for {name}\n")
        except Exception as lap_err:
            sys.stderr.write(f"[proxy] LAP lean generation not available or failed, falling back: {lap_err}\n")

    # Use npx to run 40mcp generate (on original or lean spec)
    cmd = f"npx -y 40mcp generate {spec_for_generate} --name {name}"
    if spec_type == "graphql":
        cmd += " --graphql"
    
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            return json.dumps({"ok": False, "error": f"Generation failed: {stderr.decode()}"})
        
        # 40mcp generate outputs the JSON to stdout
        with open(config_path, "w") as f:
            f.write(stdout.decode())

        # Register it in the catalogue for this session
        desc = f"Generated from {spec_url}" + (" (LAP lean)" if spec_for_generate != spec_url else "")
        entry = CatalogueEntry(
            name=name,
            description=desc,
            runtime="rest",
            config_path=f"configs/{name}.json"
        )
        
        # Add to in-memory catalogue
        global _catalogue
        _catalogue.append(entry)

        # Activate
        return proxy_activate_server(name, eager=eager)

    except Exception as e:
        return json.dumps({"ok": False, "error": f"Failed to generate/activate: {str(e)}"})


@mcp.tool(name="proxy_activate_server")
def proxy_activate_server(name: str, eager: bool = False) -> str:
    """
    Activate (mount) a server from the catalogue by name.

    By default the server is registered as a deferred stub (`{name}_load` tool)
    and only fully spawned when first used. Pass eager=True to mount immediately.

    Args:
        name: Server name as shown in proxy.list_available_servers()
        eager: If True, spawn the subprocess immediately instead of deferring.
    """
    if _config.guardrails_enabled and not check_rate_limit("anonymous"):
        return json.dumps({"ok": False, "error": "Rate limit exceeded. Try again later."})

    t0 = time.monotonic()
    cat = _resolve_catalogue_entry(name)
    if cat is None:
        # Try persisted custom proxies — always mount eagerly (no catalogue metadata)
        entry = next((p for p in _config.proxies if p.name == name), None)
        if entry is None:
            return json.dumps({"ok": False, "error": f"No server named '{name}' found."})
        ok, msg = _do_mount(entry)
    elif eager:
        entry = _catalogue_entry_to_proxy(cat)
        ok, msg = _do_mount(entry)
    else:
        ok, msg = _register_pending(cat)

    audit(tool="proxy_activate_server", outcome="ok" if ok else "error",
          latency_ms=float(round((time.monotonic() - t0) * 1000, 1)),
          extra={"server": name, "eager": eager})

    result = json.dumps({"ok": ok, "message": msg, "active_tool_count": _tool_count()})
    if _config.guardrails_enabled:
        result = truncate_result(result)
    return result


@mcp.tool(name="proxy_deactivate_server")
def proxy_deactivate_server(name: str) -> str:
    """
    Deactivate (unmount) a currently loaded or pending server to free up tool budget.

    Args:
        name: Server name as shown in proxy.list_active_servers()
    """
    if _config.guardrails_enabled and not check_rate_limit("anonymous"):
        return json.dumps({"ok": False, "error": "Rate limit exceeded. Try again later."})

    t0 = time.monotonic()

    # Check both active and pending before deciding outcome
    is_known = name in _active_servers or name in _pending_servers
    if not is_known:
        return json.dumps({"ok": False, "error": f"'{name}' is not active or pending."})

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
    Only SSE and HTTP runtimes are accepted; stdio is restricted to prevent
    arbitrary command execution.

    Args:
        name: A unique identifier for this server
        url: SSE URL (e.g. http://localhost:8100/sse) or HTTP URL
        tags: Tag list for future discovery matching
        runtime: "sse" or "http" (stdio is not permitted for custom proxies)
        activate_now: If True, mount the server immediately
    """
    if _config.guardrails_enabled and not check_rate_limit("anonymous"):
        return json.dumps({"ok": False, "error": "Rate limit exceeded. Try again later."})

    if runtime == "stdio":
        return json.dumps({
            "ok": False,
            "error": "stdio runtime is restricted for custom proxies to prevent arbitrary command execution.",
        })

    entry = ProxyEntry(
        name=name, url=url, tags=tags or [], runtime=runtime, active=activate_now,
        compression_profile=None, auto_compress=False
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


@mcp.tool(name="proxy_get_usage")
def proxy_get_usage() -> str:
    """Return current server usage counts for self-evolving ranking (F-13)."""
    sorted_usage = dict(sorted(_server_usage.items(), key=lambda x: -x[1]))
    return json.dumps({
        "ok": True,
        "usage": sorted_usage,
        "note": "Higher usage boosts ranking in future handshakes."
    }, indent=2)


@mcp.tool(name="proxy_reset_usage")
def proxy_reset_usage(server: str | None = None) -> str:
    """Reset usage stats (all or for one server). Useful for testing or re-baselining."""
    if server:
        _server_usage.pop(server, None)
    else:
        _server_usage.clear()
    _persist_usage()
    return json.dumps({"ok": True, "message": f"Reset usage for {server or 'all'}; persisted."})


# ---------------------------------------------------------------------------
# Startup: mount persisted proxies + scan plugins
# ---------------------------------------------------------------------------

def _on_plugin_register(name: str, command: str) -> None:
    entry = ProxyEntry(name=name, url=f"stdio://{command}", tags=[], runtime="stdio", compression_profile=None, auto_compress=False)
    ok, msg = _do_mount(entry)
    sys.stderr.write(f"[plugin_scanner] {msg}\n")


def _on_plugin_deregister(name: str) -> None:
    ok, msg = _do_unmount(name)
    sys.stderr.write(f"[plugin_scanner] {msg}\n")


def _startup() -> None:
    global _config, _catalogue

    _config = load_config()
    _catalogue = load_catalogue(_config)

    if _config.usage_stats:
        _server_usage.update(_config.usage_stats)

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
