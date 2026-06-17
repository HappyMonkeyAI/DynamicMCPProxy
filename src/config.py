"""
Config persistence layer — Pydantic models and load/save helpers.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env from project root (no-op if file doesn't exist)
load_dotenv(Path(__file__).parent.parent / ".env", override=False)

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

    name: str = Field(description="Name must be [a-zA-Z0-9_-]{1,64}")
    url: str = Field(description="SSE URL or stdout command string")
    tags: list[str] = Field(default_factory=list)
    active: bool = False
    runtime: str = Field(default="stdio", description="sse, http, or stdio")
    # ISO timestamp of last use, used for LRU eviction
    last_used: Optional[str] = None
    env_vars: list[str] = Field(default_factory=list, description="Environment variables to pass to the tool server")
    # Steering / Response Shaping
    pick: list[str] = Field(default_factory=list, description="Fields to pick from the tool response")
    omit: list[str] = Field(default_factory=list, description="Fields to omit from the tool response")
    template: Optional[str] = Field(None, description="Formatting template for the response")
    token_budget: Optional[int] = Field(None, description="Max tokens (approx) for the tool response")
    # Compression profile for advanced tool result compression (e.g. "git", "log", "auto")
    compression_profile: Optional[str] = Field(None, description="Profile for smart output compression (rtk-style)")
    auto_compress: bool = Field(False, description="Enable automatic heuristic compression")


class AppConfig(BaseModel):
    """Top-level proxy configuration."""

    # How many total tools may be exposed at once across all mounted servers
    tool_budget: int = 100

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

    # Usage stats for self-evolving (F-13, persisted optionally)
    usage_stats: dict[str, int] = Field(default_factory=dict)


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
    runtime: Literal["stdio", "sse", "http", "rest"] = "stdio"
    # Optional env vars required by this server (keys only, values from caller)
    env_vars: list[str] = Field(default_factory=list)
    # Best-effort estimate of how many tools this server exposes (used for budget tracking)
    estimated_tools: int = 10
    # Steering / Response Shaping
    pick: list[str] = Field(default_factory=list)
    omit: list[str] = Field(default_factory=list)
    template: Optional[str] = None
    token_budget: Optional[int] = None
    # Compression profile for advanced tool result compression (e.g. "git", "log", "auto")
    compression_profile: Optional[str] = None
    auto_compress: bool = False
    # Path to a 40mcp-style REST bridge JSON config (for runtime="rest")
    config_path: Optional[str] = None


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
        import sys
        sys.stderr.write(f"[config] Warning: could not load config ({exc}), using defaults.\n")
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


def load_catalogue(config: AppConfig, user_catalogue_path: Path | str | None = None) -> list[CatalogueEntry]:
    """Load the bundled MCP server catalogue, merged with user.catalogue.json if present.

    Args:
        config: AppConfig with catalogue_path set.
        user_catalogue_path: Override path for user catalogue (useful in tests).
    """
    def _load_file(path: Path) -> list[CatalogueEntry]:
        if not path.exists():
            return []
        try:
            with open(path) as f:
                data = json.load(f)
            return [CatalogueEntry.model_validate(e) for e in data]
        except Exception as exc:
            import sys
            sys.stderr.write(f"[config] Warning: could not load catalogue {path} ({exc})\n")
            return []

    cat_path = Path(config.catalogue_path)
    if not cat_path.is_absolute():
        cat_path = Path(__file__).parent.parent / cat_path

    entries = _load_file(cat_path)

    # Merge user catalogue — user entries take precedence (overwrite by name)
    if user_catalogue_path is not None:
        user_cat_path = Path(user_catalogue_path)
    else:
        user_cat_path = Path(__file__).parent.parent / "user.catalogue.json"

    user_entries = _load_file(user_cat_path)
    if user_entries:
        existing = {e.name: i for i, e in enumerate(entries)}
        for ue in user_entries:
            if ue.name in existing:
                entries[existing[ue.name]] = ue
            else:
                entries.append(ue)

    return entries
