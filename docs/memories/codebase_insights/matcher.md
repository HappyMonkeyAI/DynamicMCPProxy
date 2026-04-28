# Codebase Insight: Matcher Engine

## Purpose
The matcher engine (`src/matcher.py`) ranks MCP servers from the catalogue based on the current project context. It uses keyword-based scoring to suggest the most relevant tools for the AI's current task.

## Normalization (`_normalise`)
Crucial for consistent matching. It:
- Lowercases all tokens.
- Strips most punctuation but **preserves** `+`, `#`, `.`, and `-`. This ensures languages and frameworks like `C++`, `C#`, `Node.js`, and `react-router` are not conflated or corrupted.
- Removes tokens that become empty strings after punctuation removal (e.g., `!!!` is ignored).

## Scoring Components
- **Tag Overlap**: Jaccard-like similarity between context tokens and entry tags/tech-stack. Weighted 3x.
- **Description Match**: Overlap between task description keywords and the server's description/tags.
- **Requirements Match**: Bonus points if package names in `requirements.txt` (or similar) match entry tags. Weighted 2x.
- **File Inference**: Infers technology stack from open file extensions (e.g., `.py` → `python`, `.sql` → `postgres`) and matches against tags.

## Project Context
The `ProjectContext` dataclass captures:
- `tech_stack`: Explicitly known technologies.
- `task_description`: Free-text description of the work.
- `open_files`: Currently active files in the IDE.
- `requirements`: List of project dependencies.
