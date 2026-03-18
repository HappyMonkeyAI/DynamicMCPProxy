"""Tests for the keyword matching engine."""
from __future__ import annotations

import pytest
from src.config import CatalogueEntry
from src.matcher import ProjectContext, rank_servers


def _make_entry(name: str, tags: list[str], tech_stack: list[str] = None,
                description: str = "") -> CatalogueEntry:
    return CatalogueEntry(
        name=name,
        description=description or f"{name} server",
        tags=tags,
        tech_stack=tech_stack or ["any"],
        runtime="stdio",
    )


CATALOGUE = [
    _make_entry("github", ["github", "git", "code", "version_control"],
                description="GitHub MCP server — issues, PRs, code"),
    _make_entry("postgres", ["postgres", "database", "sql"],
                tech_stack=["python", "node", "django", "fastapi"],
                description="PostgreSQL read-only SQL queries"),
    _make_entry("slack", ["slack", "messaging", "communication"],
                description="Slack messaging and channels"),
    _make_entry("docker", ["docker", "containers", "devops"],
                description="Docker container management"),
    _make_entry("brave-search", ["search", "web", "research"],
                description="Brave web search"),
]


def test_rank_by_tech_stack():
    ctx = ProjectContext(tech_stack=["python", "postgres", "fastapi"])
    results = rank_servers(ctx, CATALOGUE, top_k=5)
    names = [r.entry.name for r in results]
    assert "postgres" in names
    # postgres should rank above slack
    pg_rank = names.index("postgres")
    assert pg_rank < names.index("slack") if "slack" in names else True


def test_rank_by_task_description():
    ctx = ProjectContext(
        tech_stack=[],
        task_description="I need to search the web for research",
    )
    results = rank_servers(ctx, CATALOGUE, top_k=3)
    names = [r.entry.name for r in results]
    assert "brave-search" in names


def test_rank_returns_top_k():
    ctx = ProjectContext(tech_stack=["any", "github", "docker", "slack", "postgres", "search"])
    results = rank_servers(ctx, CATALOGUE, top_k=2)
    assert len(results) <= 2


def test_rank_excludes_zero_score():
    ctx = ProjectContext(tech_stack=["haskell"])  # matches nothing
    results = rank_servers(ctx, CATALOGUE, top_k=5)
    assert all(r.score > 0 for r in results)


def test_rank_by_open_files():
    ctx = ProjectContext(open_files=["main.py", "models.sql", "Dockerfile"])
    results = rank_servers(ctx, CATALOGUE, top_k=5)
    names = [r.entry.name for r in results]
    # .sql should trigger postgres, Dockerfile should trigger docker
    assert "postgres" in names or "docker" in names


def test_rank_by_requirements():
    ctx = ProjectContext(requirements=["psycopg2", "sqlalchemy", "fastapi"])
    results = rank_servers(ctx, CATALOGUE, top_k=3)
    names = [r.entry.name for r in results]
    assert "postgres" in names


def test_rank_scores_are_sorted_descending():
    ctx = ProjectContext(tech_stack=["github", "docker", "postgres"])
    results = rank_servers(ctx, CATALOGUE, top_k=5)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
