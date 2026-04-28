"""Tests for internal helper functions in matcher.py."""
from __future__ import annotations

import pytest
from src.matcher import _normalise


@pytest.mark.parametrize(
    "tokens,expected",
    [
        # Empty list
        ([], set()),
        # Empty/whitespace strings
        (["", "  "], set()),
        # Only removed punctuation
        (["!!!", "???"], set()),
        # Mixed casing
        (["Python", "GoLang"], {"python", "golang"}),
        # Preserved punctuation
        (
            ["C++", "C#", "Node.js", "react-router"],
            {"c++", "c#", "node.js", "react-router"},
        ),
        # Leading/trailing whitespace
        (["  python  "], {"python"}),
        # Combined cases
        (["  Next.js!  ", "C++?"], {"next.js", "c++"}),
        # Numbers
        (["python3", "v1.2.3"], {"python3", "v1.2.3"}),
    ],
)
def test_normalise(tokens: list[str], expected: set[str]):
    assert _normalise(tokens) == expected
