# 9router — LLM Router + RTK Tool Result Token Saver

**URL**: https://github.com/decolua/9router  
**Captured**: 2026-06-17 (from bookmarks CSV)  
**Type**: Model / provider router with aggressive tool output compression

## What it is
A proxy/router that sits in front of Claude Code / Cursor / Codex / Antigravity etc. It provides a single OpenAI-compatible endpoint, does automatic fallback across 40+ providers (subscription → cheap → free), quota tracking, and — most relevantly — "RTK Token Saver" that auto-compresses `tool_result` content to save 20-40% tokens per request.

## Direct relevance
- **Our domain overlap**: We are a *tool server router* (lazy activation of MCP servers). 9router is a *model/provider router* with heavy focus on tool call results.
- Their RTK feature is solving almost exactly the same sub-problem as our **response steering** (`pick`, `omit`, `template`, `token_budget` per catalogue entry).
- Works with Antigravity (mentioned explicitly), so ecosystem overlap.
- Token reduction on *tool outputs* is one of the biggest wins for keeping within budgets.

## Cherry-pick ideas
- **RTK compression techniques**: Investigate exactly how they compress tool_result (diffs, git output, grep, ls, etc.). We can improve or auto-apply more aggressive steering for common tool categories (e.g. always compress large file listings, test output, API responses).
- Fallback + budget logic: Ideas for smarter activation when "budget" (tool count or token estimate) is tight.
- Universal client support: They support many IDEs via a single endpoint — validation that proxy patterns work broadly.
- Dashboard / observability for routing decisions (we have `proxy_inspect_registry`, `proxy_get_metrics`).

## Specific wins they claim
- 20-40% token savings on tool_result content via RTK.
- Never hit limits by falling back.

## Integration thoughts
- Could run 9router in front of (or alongside) our proxy for model-side savings.
- Or learn from their compression heuristics and bake similar rules into our steering layer or per-server `pick` defaults in catalogue.json.
- Possible future: make our proxy also act as a smarter tool-result post-processor with learned or rule-based compression.

**Our existing related work**: [S-12] Response Steering for Context Efficiency. This project gives a real-world production implementation of similar ideas focused on tool outputs.

See also LAP for spec-side compression.
