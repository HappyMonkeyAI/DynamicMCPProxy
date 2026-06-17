# LAP (Lean API Platform) — Agent-Native API Specs

**URL**: https://github.com/Lap-Platform/LAP  
**Website**: https://lap.sh / registry at lap.sh  
**Captured**: 2026-06-17 (from ai_bookmarks_master_june_template)  
**License**: Likely permissive (check repo; has CONTRIBUTING, used in IDE skills)

## What it is
A compiler + ecosystem that turns verbose API specs (OpenAPI, GraphQL, Postman, Protobuf, AsyncAPI, Smithy) into a lean, purpose-built "agent-native" format (.lap files). 5.2× median compression (up to 39x), with typed contracts to reduce hallucination. Explicitly designed as complementary to MCP.

## Why it matters to Dynamic MCP Proxy
Our proxy already has:
- `proxy_activate_from_spec(name, url)` for generating servers from OpenAPI/GraphQL
- `runtime: "rest"` + 40mcp declarative configs in catalogue
- Per-entry `pick`/`omit`/`template`/`token_budget` steering for response shaping and token control

LAP attacks the exact problem of bloated API/tool documentation that burns context and causes agents to guess endpoints/params. They even note "LAP can compress MCP tool schemas."

## Key technical ideas (cherry-pick candidates)
- **Semantic compression stages** (not simple minify):
  - Structural removal of YAML/JSON scaffolding
  - @directive grammar (flat single-line declarations)
  - Type compression: `type: string, format: uuid` → `str(uuid)`
  - Redundancy elimination via @common_fields / shared types
  - "Lean mode" that strips descriptions (LLMs infer from good names)
- Strong typed contracts: `enum(succeeded|pending|failed)` etc. dramatically cuts hallucination (accuracy from 0.399 → 0.860 in their tests).
- Round-trippable + diffable.
- Registry of 1500+ pre-compiled specs.
- Skill generation for agents.
- Explicit MCP complementarity: "MCP defines how... LAP compresses the documentation those tools expose."

## Benchmarks (from their data)
- 162 specs: 4.37M → 423K tokens overall
- Median OpenAPI 5.2× ; some 39×+
- Real agent tasks: same correct output, 24-91% fewer tokens in spec context
- 35% cheaper, 29% faster in their measurements

## What to avoid / differences
- Not a replacement for MCP (plumbing vs payload).
- Focused on *API documentation* compression for tool use, not full MCP server proxying/lazy activation/budget.
- Their primary UX is "install skills" into IDEs (Claude Code, Cursor, Codex) via lapsh CLI.

## Recommendations for this project
1. **High priority review**: Evaluate using LAP (or its grammar) when generating REST bridges or steering large external APIs. Could make our `configs/*.json` or generated tools dramatically leaner.
2. Add support for ingesting `.lap` files or calling out to `lapsh compile`.
3. Consider LAP-style type directives in our steering or catalogue metadata.
4. Potentially contribute our MCP proxy use-case or expose compressed tool schemas.
5. Add to catalogue? Or as an optional enhancer for `proxy_activate_from_spec`.

**Related internal**: See patterns for response steering [S-12], declarative REST [S-14], and proxy_activate_from_spec.

See also research/notes for related compression/memory work.
