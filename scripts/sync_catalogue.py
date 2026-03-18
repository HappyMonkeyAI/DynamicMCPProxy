#!/usr/bin/env python3
"""
Catalogue sync script — fetches the official MCP servers list from GitHub
and updates catalogue.json.

Usage:
    uv run python scripts/sync_catalogue.py [--output catalogue.json]

The script parses the README table from:
    https://github.com/modelcontextprotocol/servers
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:
    sys.exit("httpx is required. Run: uv add httpx")

GITHUB_README_URL = (
    "https://raw.githubusercontent.com/modelcontextprotocol/servers/main/README.md"
)

DEFAULT_OUTPUT = Path(__file__).parent.parent / "catalogue.json"


def _parse_readme_table(readme: str) -> list[dict]:
    """
    Extract server entries from the README. The official repo uses a markdown
    table with columns: Name | Description | Link
    We parse what we can and supplement with heuristic tag generation.
    """
    entries: list[dict] = []

    # Match rows in markdown tables: | cell | cell | cell |
    table_row = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|")

    for line in readme.splitlines():
        m = table_row.match(line.strip())
        if not m:
            continue
        name_cell, desc_cell, link_cell = m.group(1), m.group(2), m.group(3)

        # Skip header/divider rows
        if re.match(r"^[-: ]+$", name_cell.replace("|", "")):
            continue
        if name_cell.lower() in ("name", "server"):
            continue

        # Strip markdown links from name
        name = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", name_cell).strip().lower()
        name = re.sub(r"[^a-z0-9\-_]", "-", name).strip("-")
        description = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", desc_cell).strip()

        if not name or not description or len(name) < 2:
            continue

        # Heuristic tag generation from name + description
        tags = _generate_tags(name, description)

        entries.append({
            "name": name,
            "description": description,
            "command": None,       # Not available from README — fill manually
            "url": None,
            "tags": tags,
            "tech_stack": ["any"],
            "runtime": "stdio",
            "env_vars": [],
        })

    return entries


def _generate_tags(name: str, description: str) -> list[str]:
    """Heuristic: extract meaningful tokens from name and description as tags."""
    combined = (name + " " + description).lower()
    # Known keyword → tag mapping
    keyword_tags = {
        "github": "github", "gitlab": "gitlab", "bitbucket": "bitbucket",
        "git": "git", "postgres": "postgres", "postgresql": "postgres",
        "mysql": "mysql", "sqlite": "sqlite", "redis": "redis", "mongo": "mongodb",
        "neo4j": "neo4j", "graph": "graph",
        "slack": "slack", "notion": "notion", "jira": "jira",
        "confluence": "confluence", "atlassian": "atlassian",
        "aws": "aws", "gcp": "gcp", "azure": "azure",
        "docker": "docker", "kubernetes": "kubernetes", "k8s": "kubernetes",
        "terraform": "terraform", "search": "search", "brave": "brave",
        "google": "google", "maps": "maps", "drive": "drive",
        "file": "filesystem", "director": "filesystem",
        "browser": "browser", "puppeteer": "puppeteer", "playwright": "playwright",
        "stripe": "stripe", "payment": "payments", "hubspot": "hubspot",
        "zendesk": "zendesk", "sentry": "sentry", "linear": "linear",
        "memory": "memory", "fetch": "http", "web": "web",
    }
    tags: list[str] = []
    for kw, tag in keyword_tags.items():
        if kw in combined and tag not in tags:
            tags.append(tag)
    if not tags:
        tags.append(name)
    return tags


def sync(output_path: Path) -> None:
    print(f"Fetching README from {GITHUB_README_URL} ...")
    resp = httpx.get(GITHUB_README_URL, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    readme = resp.text
    print(f"Fetched {len(readme)} bytes.")

    entries = _parse_readme_table(readme)
    print(f"Parsed {len(entries)} server entries from README.")

    # Load existing catalogue to merge/preserve manual command fields
    existing: dict[str, dict] = {}
    if output_path.exists():
        with open(output_path) as f:
            for e in json.load(f):
                existing[e["name"]] = e

    merged: list[dict] = []
    for entry in entries:
        if entry["name"] in existing:
            # Preserve manually set fields from existing catalogue
            old = existing[entry["name"]]
            entry["command"] = old.get("command") or entry["command"]
            entry["url"] = old.get("url") or entry["url"]
            entry["env_vars"] = old.get("env_vars") or entry["env_vars"]
            entry["runtime"] = old.get("runtime", "stdio")
        merged.append(entry)

    # Append existing entries not found in README (custom/manual entries)
    synced_names = {e["name"] for e in merged}
    for name, e in existing.items():
        if name not in synced_names:
            merged.append(e)

    with open(output_path, "w") as f:
        json.dump(merged, f, indent=2)
    print(f"Wrote {len(merged)} entries to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync MCP server catalogue from GitHub.")
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Output catalogue.json path (default: {DEFAULT_OUTPUT})"
    )
    args = parser.parse_args()
    sync(args.output)


if __name__ == "__main__":
    main()
