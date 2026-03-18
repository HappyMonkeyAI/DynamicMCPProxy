"""
Keyword-based matching engine.

Scores catalogue entries against a ProjectContext and returns a ranked list.
The interface is designed so a v2 implementation can swap in embedding-based
similarity scoring without changing callers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import CatalogueEntry


# ---------------------------------------------------------------------------
# Project context
# ---------------------------------------------------------------------------

@dataclass
class ProjectContext:
    """Snapshot of what an AI is currently working on."""

    # e.g. ["python", "fastapi", "postgres", "docker"]
    tech_stack: list[str] = field(default_factory=list)

    # Free-text description of the current task
    task_description: str = ""

    # File paths currently open in the IDE (optional; used for stack inference)
    open_files: list[str] = field(default_factory=list)

    # Package names from requirements.txt / package.json / pyproject.toml etc.
    requirements: list[str] = field(default_factory=list)


@dataclass
class RankedEntry:
    entry: CatalogueEntry
    score: float

    def __lt__(self, other: "RankedEntry") -> bool:
        return self.score < other.score


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _normalise(tokens: list[str]) -> set[str]:
    """Lowercase + strip punctuation for consistent comparison."""
    return {re.sub(r"[^a-z0-9]", "", t.lower()) for t in tokens if t}


def _tag_overlap_score(context_tokens: set[str], entry: CatalogueEntry) -> float:
    """Tag overlap between context and catalogue entry tags + tech_stack."""
    entry_tokens = _normalise(entry.tags + entry.tech_stack)
    if not entry_tokens:
        return 0.0
    overlap = context_tokens & entry_tokens
    # Jaccard-like: intersect / union — weighted 3x
    return 3.0 * len(overlap) / len(context_tokens | entry_tokens)


def _description_score(task_description: str, entry: CatalogueEntry) -> float:
    """Score based on keyword hits from task_description in entry description."""
    if not task_description:
        return 0.0
    task_words = _normalise(task_description.split())
    entry_words = _normalise((entry.description + " " + " ".join(entry.tags)).split())
    hits = task_words & entry_words
    return len(hits) / max(len(task_words), 1)


def _requirements_score(requirements: list[str], entry: CatalogueEntry) -> float:
    """Bonus score when package names match entry tags."""
    if not requirements:
        return 0.0
    req_tokens = _normalise(requirements)
    entry_tokens = _normalise(entry.tags + entry.tech_stack)
    overlap = req_tokens & entry_tokens
    return 2.0 * len(overlap) / max(len(req_tokens), 1)


def _open_files_score(open_files: list[str], entry: CatalogueEntry) -> float:
    """Infer stack from file extensions and match against entry tags."""
    ext_to_tags: dict[str, list[str]] = {
        ".py": ["python"],
        ".ts": ["typescript", "node"],
        ".tsx": ["typescript", "react", "nextjs"],
        ".js": ["javascript", "node"],
        ".jsx": ["javascript", "react"],
        ".go": ["go", "golang"],
        ".rs": ["rust"],
        ".tf": ["terraform", "iac"],
        ".sql": ["postgres", "mysql", "database", "sql"],
        ".yaml": ["kubernetes", "docker", "ci"],
        ".yml": ["kubernetes", "docker", "ci"],
        ".json": [],
        ".md": [],
    }
    inferred: list[str] = []
    for f in open_files:
        ext = "." + f.rsplit(".", 1)[-1].lower() if "." in f else ""
        inferred.extend(ext_to_tags.get(ext, []))

    if not inferred:
        return 0.0
    inf_tokens = _normalise(inferred)
    entry_tokens = _normalise(entry.tags + entry.tech_stack)
    overlap = inf_tokens & entry_tokens
    return len(overlap) / max(len(inf_tokens), 1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def rank_servers(
    context: ProjectContext,
    catalogue: list[CatalogueEntry],
    top_k: int = 5,
) -> list[RankedEntry]:
    """
    Score and rank catalogue entries against a ProjectContext.

    Returns up to top_k entries sorted by score descending.
    Entries with score == 0 are excluded.
    """
    context_tokens = _normalise(context.tech_stack + context.requirements)

    ranked: list[RankedEntry] = []
    for entry in catalogue:
        score = (
            _tag_overlap_score(context_tokens, entry)
            + _description_score(context.task_description, entry)
            + _requirements_score(context.requirements, entry)
            + _open_files_score(context.open_files, entry)
        )
        if score > 0:
            ranked.append(RankedEntry(entry=entry, score=round(score, 4)))

    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked[:top_k]
