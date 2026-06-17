# docs/adr/

This directory exists to match common documentation conventions (see `setup-prompt.txt`).

**The actual architecture decisions for this project live in:**

`docs/memories/architectural_decisions/`

## Current decisions
- `stdio_transport.md`
- `user_catalogue_and_env.md`

## Why we use memories/
- Part of the Anti-Gravity LTM system (see `AGENTS.md` and `docs/memories/patterns_and_lessons.md`)
- Decisions are versioned together with patterns, failure post-mortems, and codebase insights
- Keeps all durable project memory in one discoverable tree

## For external tools / contributors
If a tool expects `docs/adr/*.md`, point it at `../memories/architectural_decisions/`.

When making new architecture decisions:
1. Write (or update) the record in `docs/memories/architectural_decisions/`
2. Update `CONTEXT.md` if the decision affects rules or guidance
3. Record related lessons in `patterns_and_lessons.md`

Do not duplicate files between `adr/` and `memories/`.
