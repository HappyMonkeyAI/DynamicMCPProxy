"""
Config persistence layer — Pydantic models and load/save helpers.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Default config file location (can be overridden via env var)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_PATH = Path(
    os.environ.get("PROXY_CONFIG", Path(__file__).parent.parent / "proxy_config.json")
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ProxyEntry(BaseModel):
    """A registered child MCP server."""

    name: str
    url: str
    tags: list[str] = Field(default_factory=list)
    active: bool = False
    runtime: Literal["stdio", "sse", "http"] = "sse"
    # ISO timestamp of last use, used for LRU eviction
    last_used: Optional[str] = None


class AppConfig(BaseModel):
    """Top-level proxy configuration."""

    # How many total tools may be exposed at once across all mounted servers
    tool_budget: int = 50

    # Security — disabled by default for dev
    auth_enabled: bool = False
    jwt_public_key_path: Optional[str] = None
    hmac_api_key: Optional[str] = None

    # Guardrails
    guardrails_enabled: bool = True
    rate_limit_rpm: int = 120
    tool_allowlist: list[str] = Field(default_factory=list)
    tool_denylist: list[str] = Field(default_factory=list)

    # Paths
    catalogue_path: str = "catalogue.json"
    audit_log_path: str = "audit.log"

    # Registered proxies (persisted)
    proxies: list[ProxyEntry] = Field(default_factory=list)


class CatalogueEntry(BaseModel):
    """A single entry in the bundled MCP server catalogue."""

    name: str
    description: str
    # Command template for stdio servers, e.g. "npx -y @modelcontextprotocol/server-github"
    command: Optional[str] = None
    # SSE URL for remote servers
    url: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    runtime: Literal["stdio", "sse", "http"] = "stdio"
    # Optional env vars required by this server (keys only, values from caller)
    env_vars: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Load / Save helpers
# ---------------------------------------------------------------------------

def _resolve_path(path: Path | str | None = None) -> Path:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.is_absolute():
        p = Path(__file__).parent.parent / p
    return p


def load_config(path: Path | str | None = None) -> AppConfig:
    """Load AppConfig from JSON file, returning defaults if not found."""
    cfg_path = _resolve_path(path)
    if not cfg_path.exists():
        return AppConfig()
    try:
        with open(cfg_path) as f:
            data = json.load(f)
        return AppConfig.model_validate(data)
    except Exception as exc:
        print(f"[config] Warning: could not load config ({exc}), using defaults.")
        return AppConfig()


def save_config(config: AppConfig, path: Path | str | None = None) -> None:
    """Persist AppConfig to JSON file."""
    cfg_path = _resolve_path(path)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w") as f:
        json.dump(config.model_dump(), f, indent=2)


def save_proxy(entry: ProxyEntry, config: AppConfig, path: Path | str | None = None) -> None:
    """Upsert a proxy entry and save config."""
    for i, p in enumerate(config.proxies):
        if p.name == entry.name:
            config.proxies[i] = entry
            break
    else:
        config.proxies.append(entry)
    save_config(config, path)


def remove_proxy(name: str, config: AppConfig, path: Path | str | None = None) -> bool:
    """Remove a proxy entry by name. Returns True if removed."""
    before = len(config.proxies)
    config.proxies = [p for p in config.proxies if p.name != name]
    if len(config.proxies) < before:
        save_config(config, path)
        return True
    return False


def load_catalogue(config: AppConfig) -> list[CatalogueEntry]:
    """Load the bundled MCP server catalogue."""
    cat_path = Path(config.catalogue_path)
    if not cat_path.is_absolute():
        cat_path = Path(__file__).parent.parent / cat_path
    if not cat_path.exists():
        return []
    try:
        with open(cat_path) as f:
            data = json.load(f)
        return [CatalogueEntry.model_validate(e) for e in data]
    except Exception as exc:
        print(f"[config] Warning: could not load catalogue ({exc})")
        return []
