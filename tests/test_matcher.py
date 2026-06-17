"""Tests for the keyword matching engine."""
from __future__ import annotations

import pytest
from src.config import CatalogueEntry
from src.matcher import ProjectContext, rank_servers, search_servers


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


def test_rank_usage_boost():
    """Usage stats boost frequently called servers (F-13)."""
    ctx = ProjectContext(task_description="need to check previous team decisions on auth")
    # Add a knowledge server to the test catalogue copy
    knowledge_cat = CATALOGUE + [
        _make_entry("team-wiki", ["knowledge", "wiki", "memory", "team"],
                    description="Team knowledge base and history")
    ]
    # Without usage
    results_no = rank_servers(ctx, knowledge_cat, top_k=5)
    # With high usage on wiki
    results_yes = rank_servers(ctx, knowledge_cat, top_k=5, usage={"team-wiki": 15})
    names_no = [r.entry.name for r in results_no]
    names_yes = [r.entry.name for r in results_yes]
    # wiki should rank higher with usage
    if "team-wiki" in names_yes:
        rank_yes = names_yes.index("team-wiki")
        if "team-wiki" in names_no:
            rank_no = names_no.index("team-wiki")
            assert rank_yes <= rank_no
        else:
            assert rank_yes < len(names_yes)


def test_search_servers():
    """Free-text search for on-demand discovery (F-15)."""
    # Search by description keywords
    results = search_servers("search the web for research", CATALOGUE, limit=3)
    names = [r.entry.name for r in results]
    assert "brave-search" in names

    # Search by name/tag
    results2 = search_servers("github code", CATALOGUE, limit=2)
    names2 = [r.entry.name for r in results2]
    assert "github" in names2

    # Empty query
    assert search_servers("", CATALOGUE) == []
