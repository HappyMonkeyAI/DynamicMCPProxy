"""Tests for the config persistence layer."""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from src.config import (
    AppConfig, ProxyEntry, CatalogueEntry,
    load_config, save_config, save_proxy, remove_proxy, load_catalogue,
)


def test_load_config_defaults(tmp_path: Path):
    cfg = load_config(tmp_path / "nonexistent.json")
    assert cfg.tool_budget == 100
    assert cfg.auth_enabled is False
    assert cfg.guardrails_enabled is True
    assert cfg.proxies == []


def test_save_and_load_config_roundtrip(tmp_path: Path):
    cfg = AppConfig(tool_budget=30, auth_enabled=True)
    cfg_path = tmp_path / "proxy_config.json"
    save_config(cfg, cfg_path)
    reloaded = load_config(cfg_path)
    assert reloaded.tool_budget == 30
    assert reloaded.auth_enabled is True


def test_save_proxy_upsert(tmp_path: Path):
    cfg = AppConfig()
    cfg_path = tmp_path / "proxy_config.json"
    entry = ProxyEntry(name="test", url="http://localhost:8100/sse", tags=["test"])
    save_proxy(entry, cfg, cfg_path)

    reloaded = load_config(cfg_path)
    assert len(reloaded.proxies) == 1
    assert reloaded.proxies[0].name == "test"

    # Upsert — update URL
    updated = ProxyEntry(name="test", url="http://localhost:9000/sse", tags=["test"])
    save_proxy(updated, reloaded, cfg_path)
    reloaded2 = load_config(cfg_path)
    assert len(reloaded2.proxies) == 1
    assert reloaded2.proxies[0].url == "http://localhost:9000/sse"


def test_remove_proxy(tmp_path: Path):
    cfg = AppConfig(proxies=[
        ProxyEntry(name="a", url="http://a", tags=[]),
        ProxyEntry(name="b", url="http://b", tags=[]),
    ])
    cfg_path = tmp_path / "proxy_config.json"
    save_config(cfg, cfg_path)

    removed = remove_proxy("a", cfg, cfg_path)
    assert removed is True

    reloaded = load_config(cfg_path)
    assert len(reloaded.proxies) == 1
    assert reloaded.proxies[0].name == "b"

    # Removing non-existent returns False
    assert remove_proxy("xyz", reloaded, cfg_path) is False


def test_load_catalogue(tmp_path: Path):
    cat_data = [
        {
            "name": "github",
            "description": "GitHub MCP server",
            "command": "npx -y @modelcontextprotocol/server-github",
            "tags": ["github", "git"],
            "tech_stack": ["any"],
            "runtime": "stdio",
            "env_vars": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
        }
    ]
    cat_path = tmp_path / "catalogue.json"
    cat_path.write_text(json.dumps(cat_data))

    cfg = AppConfig(catalogue_path=str(cat_path))
    # Pass a nonexistent user catalogue path to isolate from the real one
    entries = load_catalogue(cfg, user_catalogue_path=tmp_path / "user.catalogue.json")
    assert len(entries) == 1
    assert entries[0].name == "github"
    assert "github" in entries[0].tags


def test_load_catalogue_missing(tmp_path: Path):
    cfg = AppConfig(catalogue_path=str(tmp_path / "missing.json"))
    entries = load_catalogue(cfg, user_catalogue_path=tmp_path / "user.catalogue.json")
    assert entries == []
