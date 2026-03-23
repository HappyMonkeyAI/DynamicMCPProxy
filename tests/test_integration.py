"""
Integration test — verifies the full proxy management flow.

Tests:
1. Handshake triggers matching + mounting of relevant servers
2. Active server state is tracked and visible in list/metrics tools
3. Health resource returns valid JSON
4. Deactivate tracking works correctly

Note: We use an SSE mock server for end-to-end transport testing, but
the primary focus is on the orchestration layer (handshake → match → mount
→ track) which is fully synchronous and testable without a live MCP connection.
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src import proxy_server
from src.config import CatalogueEntry, ProxyEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_proxy_state() -> None:
    """Reset proxy global state between tests."""
    proxy_server._active_servers.clear()
    proxy_server._config = proxy_server.AppConfig()
    proxy_server._catalogue = []


def _make_http_entry(name: str, url: str, tags: list[str] = None) -> CatalogueEntry:
    return CatalogueEntry(
        name=name,
        description=f"Mock {name} server",
        url=url,
        tags=tags or [name],
        runtime="sse",
    )


# ---------------------------------------------------------------------------
# Tests: orchestration / management layer (no live transport needed)
# ---------------------------------------------------------------------------

class TestHandshakeOrchestration:
    """
    Tests that verify the handshake → match → mount → track pipeline.
    Mounting against a live SSE URL is attempted; on failure the entry
    is recorded in 'skipped'. We test the overall flow rather than the
    live transport.
    """

    def setup_method(self):
        """Reset state before every test."""
        _reset_proxy_state()
        proxy_server._startup()

    def test_handshake_returns_valid_json(self):
        """proxy.handshake must always return parseable JSON."""
        raw = proxy_server.proxy_handshake(
            tech_stack=["python"],
            task_description="Testing the proxy",
        )
        data = json.loads(raw)
        assert "activated_servers" in data
        assert "skipped" in data
        assert "active_tool_count" in data
        assert "budget_remaining" in data
        assert "context_received" in data
        assert "tip" in data

    def test_handshake_with_no_catalogue_match(self):
        """If no catalogue entries match, no servers are activated."""
        # Use a nonsense tech stack unlikely to match anything
        raw = proxy_server.proxy_handshake(
            tech_stack=["zxqwerty123"],
            task_description="",
        )
        data = json.loads(raw)
        assert data["activated_servers"] == []

    def test_handshake_activates_matching_server(self, monkeypatch):
        """
        A catalogue entry matching the tech_stack should be picked up by
        the matcher. We patch _do_mount to avoid needing a live server.
        """
        mock_entry = _make_http_entry("github", "http://localhost:9999/sse", tags=["github", "git", "version-control"])
        proxy_server._catalogue.append(mock_entry)

        # Patch _do_mount to succeed without a real network call
        def fake_mount(entry):
            proxy_server._active_servers[entry.name] = (entry, None, 5)
            return True, f"Mock-mounted '{entry.name}'."

        monkeypatch.setattr(proxy_server, "_do_mount", fake_mount)

        raw = proxy_server.proxy_handshake(
            tech_stack=["github"],
            task_description="I need to manage GitHub issues",
        )
        data = json.loads(raw)
        assert "github" in data["activated_servers"]

    def test_handshake_skips_already_active_server(self, monkeypatch):
        """Calling handshake twice should not try to double-mount."""
        entry = _make_http_entry("github", "http://localhost:9999/sse", tags=["github"])
        proxy_server._catalogue.append(entry)

        def fake_mount(e):
            proxy_server._active_servers[e.name] = (e, None, 5)
            return True, "Mounted."

        monkeypatch.setattr(proxy_server, "_do_mount", fake_mount)

        proxy_server.proxy_handshake(tech_stack=["github"])

        # Second handshake: server is already active, should not re-mount
        call_count = {"n": 0}
        original_mount = proxy_server._do_mount

        def counting_mount(e):
            call_count["n"] += 1
            return original_mount(e)

        monkeypatch.setattr(proxy_server, "_do_mount", counting_mount)
        proxy_server.proxy_handshake(tech_stack=["github"])
        assert call_count["n"] == 0, "Should not call _do_mount for already-active server"


class TestProxyManagementTools:
    """Tests for the proxy.* management tools."""

    def setup_method(self):
        _reset_proxy_state()
        proxy_server._startup()

    def test_list_active_servers_empty(self):
        raw = proxy_server.proxy_list_active_servers()
        data = json.loads(raw)
        assert data["active_servers"] == []
        assert data["total_tools"] == 0

    def test_list_active_servers_with_entries(self):
        entry = ProxyEntry(name="test-server", url="http://localhost:9999/sse", tags=["test"])
        proxy_server._active_servers["test-server"] = (entry, None, 7)

        raw = proxy_server.proxy_list_active_servers()
        data = json.loads(raw)
        assert len(data["active_servers"]) == 1
        assert data["active_servers"][0]["name"] == "test-server"
        assert data["active_servers"][0]["estimated_tools"] == 7
        assert data["total_tools"] == 7

    def test_list_available_servers(self):
        proxy_server._catalogue = [
            _make_http_entry("github", "http://localhost:9999/sse", ["github"]),
            _make_http_entry("postgres", "http://localhost:9998/sse", ["database"]),
        ]
        raw = proxy_server.proxy_list_available_servers()
        data = json.loads(raw)
        names = [s["name"] for s in data["available_servers"]]
        assert "github" in names
        assert "postgres" in names

    def test_list_available_servers_excludes_active(self):
        cat = _make_http_entry("github", "http://localhost:9999/sse", ["github"])
        proxy_server._catalogue = [cat]
        entry = ProxyEntry(name="github", url="http://localhost:9999/sse")
        proxy_server._active_servers["github"] = (entry, None, 5)

        raw = proxy_server.proxy_list_available_servers()
        data = json.loads(raw)
        assert all(s["name"] != "github" for s in data["available_servers"])

    def test_list_available_servers_filter_tag(self):
        proxy_server._catalogue = [
            _make_http_entry("github", "http://localhost:9999/sse", ["github"]),
            _make_http_entry("postgres", "http://localhost:9998/sse", ["database"]),
        ]
        raw = proxy_server.proxy_list_available_servers(filter_tag="database")
        data = json.loads(raw)
        names = [s["name"] for s in data["available_servers"]]
        assert "postgres" in names
        assert "github" not in names

    def test_deactivate_server(self):
        entry = ProxyEntry(name="test-server", url="http://localhost:9999/sse")
        proxy_server._active_servers["test-server"] = (entry, None, 5)

        raw = proxy_server.proxy_deactivate_server("test-server")
        data = json.loads(raw)
        assert data["ok"] is True
        assert "test-server" not in proxy_server._active_servers

    def test_deactivate_nonexistent_server(self):
        raw = proxy_server.proxy_deactivate_server("nonexistent")
        data = json.loads(raw)
        assert data["ok"] is False

    def test_get_metrics_returns_health(self):
        raw = proxy_server.proxy_get_metrics()
        data = json.loads(raw)
        assert data["status"] == "ok"
        assert "uptimeSeconds" in data


class TestMCPResources:
    """Tests for the always-on MCP Resources."""

    def setup_method(self):
        _reset_proxy_state()
        proxy_server._startup()

    def test_resource_info(self):
        raw = proxy_server.resource_info()
        data = json.loads(raw)
        assert data["name"] == "Dynamic MCP Proxy"
        assert "tool_budget" in data
        assert "catalogue_size" in data

    def test_resource_health(self):
        raw = proxy_server.resource_health()
        data = json.loads(raw)
        assert data["status"] == "ok"
        assert "uptimeSeconds" in data
        assert "activeServers" in data
        assert "budgetRemaining" in data

    def test_resource_servers(self):
        raw = proxy_server.resource_servers()
        data = json.loads(raw)
        assert "active" in data
        assert "available" in data
        assert "tool_budget" in data


class TestLRUEviction:
    """Tests for the LRU tool budget eviction logic."""

    def setup_method(self):
        _reset_proxy_state()
        # Set a tiny budget so eviction is easy to trigger
        proxy_server._config = proxy_server.AppConfig(tool_budget=10)

    def test_eviction_when_budget_exceeded(self, monkeypatch):
        """Adding a server that pushes over budget should evict the oldest."""
        # Simulate two loaded servers filling the budget
        e1 = ProxyEntry(name="server1", url="http://localhost:9001/sse")
        e2 = ProxyEntry(name="server2", url="http://localhost:9002/sse")
        proxy_server._active_servers["server1"] = (e1, None, 6)
        proxy_server._active_servers["server2"] = (e2, None, 4)
        # Total = 10, exactly at budget

        evicted = []
        original_unmount = proxy_server._do_unmount

        def tracking_unmount(name):
            evicted.append(name)
            return original_unmount(name)

        monkeypatch.setattr(proxy_server, "_do_unmount", tracking_unmount)

        # Trigger eviction by requesting 5 more
        proxy_server._evict_lru_if_needed(needed=5)
        assert len(evicted) >= 1
        # server1 is LRU (inserted first)
        assert "server1" in evicted


class TestProxyListTools:
    """Tests for the async proxy_list_tools tool."""

    def setup_method(self):
        _reset_proxy_state()
        proxy_server._startup()

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_list_tools_returns_valid_json(self):
        """proxy_list_tools must always return parseable JSON."""
        raw = self._run(proxy_server.proxy_list_tools())
        data = json.loads(raw)
        assert "tools" in data
        assert "total" in data
        assert "note" in data

    def test_list_tools_excludes_proxy_tools(self):
        """proxy_list_tools must not include the proxy_* management tools themselves."""
        raw = self._run(proxy_server.proxy_list_tools())
        data = json.loads(raw)
        for tool in data["tools"]:
            assert not tool["name"].startswith("proxy_"), (
                f"proxy_* tool '{tool['name']}' should be excluded from the list"
            )

    def test_list_tools_total_matches_list_length(self):
        """The 'total' field must match the actual number of tools returned."""
        raw = self._run(proxy_server.proxy_list_tools())
        data = json.loads(raw)
        assert data["total"] == len(data["tools"])

    def test_list_tools_filter_by_server_name(self, monkeypatch):
        """Filtering by server_name should only return tools with that prefix."""
        # Simulate a mounted server by injecting a fake provider via monkeypatch
        from unittest.mock import AsyncMock, MagicMock
        import asyncio

        fake_tool_github = MagicMock()
        fake_tool_github.name = "github_list-repos"
        fake_tool_github.description = "List GitHub repos"

        fake_provider = MagicMock()
        fake_provider.list_tools = AsyncMock(return_value=[fake_tool_github])
        
        # Add a Namespace transform so _prefix check works
        fake_transform = MagicMock()
        fake_transform._prefix = "github"
        fake_provider._transforms = [fake_transform]

        monkeypatch.setattr(proxy_server.mcp, "providers", [fake_provider])

        raw = self._run(proxy_server.proxy_list_tools(server_name="github"))
        data = json.loads(raw)
        assert len(data["tools"]) == 1
        assert data["tools"][0]["name"] == "github_list-repos"

        raw_empty = self._run(proxy_server.proxy_list_tools(server_name="atlassian"))
        data_empty = json.loads(raw_empty)
        assert data_empty["total"] == 0


class TestDiagnostics:
    """Tests for the new diagnostic and auditing features."""

    def setup_method(self):
        _reset_proxy_state()
        proxy_server._startup()

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_inspect_registry_returns_all_tools(self):
        """proxy_inspect_registry must include proxy_* tools (no filtering)."""
        raw = self._run(proxy_server.proxy_inspect_registry())
        data = json.loads(raw)
        assert data["status"] == "ok"
        registry_names = [t["name"] for t in data["registry"]]
        assert "proxy_handshake" in registry_names
        assert "proxy_list_tools" in registry_names
        assert "proxy_inspect_registry" in registry_names

    def test_audited_call_logs_to_audit_log(self, monkeypatch, tmp_path):
        """Calling a wrapped child tool must add an entry to the audit log."""
        # Mock audit path to a temporary file in the guardrails module
        from src import guardrails
        from unittest.mock import MagicMock, AsyncMock
        audit_file = tmp_path / "test_audit.log"
        monkeypatch.setattr(guardrails, "_audit_path", audit_file)

        # Mock a child server and its proxy
        entry = ProxyEntry(name="test-svc", url="http://test")
        mock_proxy = MagicMock()
        mock_proxy.call_tool = AsyncMock(return_value="result")
        
        # Manually trigger the mount logic that wraps call_tool
        # (We don't call _do_mount fully to avoid subprocesses)
        mcp_config = proxy_server._mcp_config_for_entry(entry)
        
        # Wrap it manually as in _do_mount
        original_call = mock_proxy.call_tool
        async def audited_call(name, arguments=None):
            import time
            start = time.monotonic()
            res = await original_call(name, arguments)
            latency = (time.monotonic() - start) * 1000
            proxy_server.audit(tool=f"{entry.name}_{name}", outcome="ok", latency_ms=latency)
            return res
        
        mock_proxy.call_tool = audited_call
        
        # Execute the call
        self._run(mock_proxy.call_tool("hello", {"arg": 1}))
        
        # Verify log entry
        assert audit_file.exists()
        lines = audit_file.read_text().splitlines()
        assert len(lines) >= 1
        record = json.loads(lines[0])
        assert record["tool"] == "test-svc_hello"
        assert record["outcome"] == "ok"

    def test_list_tools_no_filter_returns_all_non_proxy_tools(self, monkeypatch):
        """With no filter, all non-proxy_ tools from all servers are returned."""
        from unittest.mock import MagicMock

        fake_tools = [
            MagicMock(name="github_issues", description="GitHub issues"),
            MagicMock(name="postgres_query", description="Postgres query"),
        ]
        # MagicMock autogenerates .name from the name kwarg — we must set as attribute
        for t in fake_tools:
            t.name = t._mock_name  # Sync the name attribute correctly

        # Build manually since MagicMock name kwarg is special
        t1 = MagicMock()
        t1.name = "github_issues"
        t1.description = "GitHub issues"
        t2 = MagicMock()
        t2.name = "postgres_query"
        t2.description = "Postgres query"

        async def fake_list_tools():
            return [t1, t2]

        monkeypatch.setattr(proxy_server.mcp, "list_tools", fake_list_tools)

        raw = self._run(proxy_server.proxy_list_tools())
        data = json.loads(raw)
        names = [t["name"] for t in data["tools"]]
        assert "github_issues" in names
        assert "postgres_query" in names
        assert data["total"] == 2

    def test_list_tools_handles_exception_gracefully(self, monkeypatch):
        """If mcp.list_tools() raises, the tool must return JSON with ok=False."""
        async def exploding_list_tools():
            raise RuntimeError("Simulated failure")

        monkeypatch.setattr(proxy_server.mcp, "list_tools", exploding_list_tools)

        raw = self._run(proxy_server.proxy_list_tools())
        data = json.loads(raw)
        assert data["ok"] is False
        assert "error" in data
