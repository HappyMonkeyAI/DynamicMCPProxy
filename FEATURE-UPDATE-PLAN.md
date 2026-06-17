# Feature Update Plan — Dynamic MCP Proxy

> **Based on analysis of 31 X bookmarks curated by Perplexity.**
> Each bookmark was traced to its source and evaluated against the existing codebase (proxy_server.py, config.py, matcher.py, guardrails.py, plugin_scanner.py, RESTLoader) before inclusion in this plan.

**Goal:** Integrate the highest-signal architectural ideas from the bookmark set into the Dynamic MCP Proxy's next development phase.

**Architecture:** The proxy is a FastMCP stdio server that lazily loads child MCP tool servers based on project context. Key subsystems: catalogue (public + user overlay), keyword matcher, deferred/active mounting with LRU eviction, response steering (pick/omit/template/token_budget), audit logging + rate limiting, hot-plug plugin scanner, REST bridge loader, and an optional HTTP sidecar.

---

## How Each Bookmark Was Scored

The bookmarks were evaluated on four criteria:
1. **Architectural alignment** — does the idea slot into the proxy's existing architecture?
2. **User-facing impact** — does it improve developer experience?
3. **Effort / Risk** — how much code changes, any runtime risks?
4. **Signal density** — how many lessons can be extracted from a single source?

---

## Tier 1 — High Impact, Architecturally Aligned (Build Next)

### F-01: Self-Evolving Catalogue (Runtime Mutation)

**Sources:**
- [Aish — Self-improving PM system with evolving memory](https://x.com/AishwaryaDevv/status/2052314745957741007)
- [Louis Gleeson — 724 office, tools that write tools](https://x.com/aigleeson/status/2037848861591703914)
- [AlphaSignalAI / WorldofAI — Hermes self-evolution](https://x.com/inthworldofai/status/2054430265368273330)

**What it does:**
The catalogue currently loads once at startup and never changes. This feature makes it self-improve:
- Track which servers are actually invoked vs. mounted-but-unused
- Boost ranking weights for frequently-used servers, decay for ignored ones
- When `_apply_steering` patterns (pick, omit) are set on a server and hit repeatedly, remember those preferences automatically
- When a server fails to load (mount fails, tool calls error), deprioritize it

**Files to modify:**
- `src/matcher.py` — add `usage_boost` field to RankedEntry, factor into scoring
- `src/proxy_server.py` — instrument `audited_call` to update usage counters, store in a new `_usage_stats` dict
- `src/config.py` — add `usage_stats: dict[str, dict]` to AppConfig for persistence
- `src/plugin_scanner.py` — if a plugin crashes repeatedly, auto-unmount and deprioritize

**Edge cases:**
- First-run bootstrap: no usage data yet, fall back to current keyword matching
- Reset button: `proxy_reset_usage()` tool to wipe stats
- Persistence vs. session-only: default to session-only; offer `persist=True` flag

**Risks:**
- Weight drift: a wrong preference could calcify bad rankings. Mitigated by reset tool and session-only default.
- Don't let feedback loop amplify bad mounts. Cap boost to 2x max.

**Verification:**
- Unit test: call handshake → activate server A → call A tools 5 times → handshake again → A ranks higher than B
- Unit test: server with 3 failed mounts gets -50% score penalty

---

### F-02: Structured Observability (Motus-Style Tracing)

**Source:** [Zhihao Jia — Motus Tracing](https://x.com/JiaZhihao/status/2055327218415341978)

**What it does:**
Replace the flat `audit()` log in guardrails.py with structured, traceable observability. Each user request gets a `trace_id` that follows it through:
1. `proxy_handshake()` → generates trace_id
2. `_register_pending()` / `_materialise()` → span for server mount
3. `audited_call()` → span per tool invocation
4. `_apply_steering()` → sub-span within tool call
5. LRU eviction → span

**Files to modify:**
- `src/guardrails.py` — add `TraceContext` class, `trace_span` context manager
- `src/proxy_server.py` — instrument each phase with trace spans
- `src/config.py` — add `tracing_enabled: bool = False`, `trace_export_path: str`

**New file:**
- `src/tracer.py` — structured trace writer (JSONL format, exportable to OpenTelemetry)

**Edge cases:**
- Async spans: spans from concurrent tool calls must nest correctly per-trace
- Memory: cap trace buffer at 1000 entries, oldest dropped
- Off-by-default: tracing must NOT be enabled unless explicitly configured (zero overhead when off)

**Verification:**
- Test: `tracing_enabled=True`, make handshake + 3 tool calls → verify trace JSONL has 5+ spans with correct parent-child
- Test: `tracing_enabled=False` → trace file not created
- Test: concurrent calls get different trace_ids

**Why not just use OpenTelemetry SDK?** Too heavy for stdio MCP. A JSONL file is trivially exportable to OTEL-collector later without the dependency weight.

---

### F-03: Env Var Hygiene & Credential Scanning

**Sources:**
- [0xSero — Harness security tools; env var hygiene](https://x.com/0xSero/status/2052104609372815691)
- [Guri Singh — Cybersecurity skills library for AI agents](https://x.com/heygurisingh/status/2046229645054640252)

**What it does:**
The proxy passes `env_vars` from child processes, but there's no validation:
1. **Pre-mount scan** — before spawning a child server, verify that all required `env_vars` are present AND look like real values (not placeholder strings like `"your-api-key-here"`)
2. **Audit redaction** — in the audit log, mask any env var values that accidentally leak into tool arguments or results
3. **Credential-free mode** — a flag `skip_unconfigured_servers: bool = True` that skips mounting any server with missing env vars instead of failing silently at runtime

**Files to modify:**
- `src/config.py` — add `skip_unconfigured_servers` to AppConfig
- `src/guardrails.py` — add `_redact_credentials(text: str)` function, call from `truncate_result`
- `src/proxy_server.py` — add pre-flight check in `_do_mount()` that validates env_vars

**Edge cases:**
- `env_vars` may contain vars that are intentionally empty (e.g., optional features). Add an `env_vars_required` field to CatalogueEntry to distinguish mandatory from optional.
- Redaction must not destroy valid data (false positives on words like `KEY`, `TOKEN`). Use a whitelist of known env var names that exist in the child's config.
- `.env` file itself — not currently scanned. Add a startup check that warns if `.env` contains commented-out keys that look like they should be uncommented.

**Verification:**
- Test: server with missing mandatory env var → mount skipped with clear error message
- Test: tool response containing `"token": "sk-..."` → audit log shows `"token": "[REDACTED]"`
- Test: optional env var missing → mount proceeds

---

### F-04: Difficulty-Aware Model Routing

**Source:** [0xCS — Model router for Hermes Agent](https://x.com/FT_IOxCS/status/2051323362647945375)

**What it does:**
Not all tool calls need the same model capability. Some are cheap lookups (read file, fetch URL, search). Others need reasoning (plan, analyze code). Add a routing layer that:
1. Tags each tool call with a `difficulty` hint (from the catalogue entry, or inferred from tool name/description)
2. Routes simple calls to a fast/cheap model, complex calls to a capable model
3. Works as a **plugin** registered via `./plugins/` — the proxy provides the routing infrastructure but the model choice is externalized to a config

**Files to modify:**
- `src/proxy_server.py` — add `difficulty` to tool call metadata before forwarding, add plugin hook for model routing
- `src/config.py` — add `model_routing: dict[str, str]` defaults
- `src/plugin_scanner.py` — extend scanner to look for executable plugins that export a `route_model(tool_name, difficulty)` interface

**New file:**
- `plugins/model-router` — reference implementation that routes via `difficulty` tag

**Edge cases:**
- No router plugin loaded → no-op (all calls go to the default model)
- Router plugin crashes → fall back to default, log error
- `difficulty` not set for a tool → treat as `default`

**Why a plugin rather than core?** Model routing is deployment-specific (local Ollama vs. cloud OpenAI vs. corporate gateway). The proxy should provide the hook, not the policy.

**Verification:**
- Test: router plugin loaded, `difficulty=simple` tool → router intercepts with correct tag
- Test: router plugin removed → all calls pass through unchanged
- Test: plugin crash → graceful fallback with stderr warning

---

### F-05: Plugin Ecosystem Deepening

**Sources:**
- [Louis Gleeson — 724 office self-writing tools](https://x.com/aigleeson/status/2037848861591703914)
- [Kappaemme — Complexity analysis for codebases](https://x.com/Kappaemme1926/status/2055343704467206506)
- [Sukh Sroay — Composable tool pipelines](https://x.com/sukh_saroy/status/2050843157919916344)

**What it does:**
The plugin scanner currently watches `./plugins/` for any executable and attempts to mount it as a stdio MCP server. This works but is **dumb**: it has no way to know what the plugin needs, offers, or wants.

Make plugins **self-describing**:
1. Plugin manifest (`plugin.toml` or YAML frontmatter in the script) with:
   - `name`, `description`, `version`
   - `requires_env` — env vars needed
   - `estimated_tools` count
   - `difficulty` hints per tool
   - `tags` for discovery matching
2. Plugin lifecycle hooks:
   - `on_mount` / `on_unmount` — clean up temp files, release ports
   - `on_error` — diagnostic report when the plugin crashes
3. Plugin health check — the scanner periodically pings each plugin's `ping` tool (or does a fast stdio handshake re-check) and unmounts unresponsive ones after N failures

**Files to modify:**
- `src/plugin_scanner.py` — rewrite to parse plugin manifests, add health-check loop, add lifecycle hooks
- `src/proxy_server.py` — wire `on_error` callback into `audited_call` exception handler
- `src/config.py` — add `plugin_health_check_interval: int = 30` (seconds)

**New file:**
- `plugins/example-plugin/plugin.toml` — reference manifest
- `plugins/README.md` — plugin authoring guide

**Edge cases:**
- Plugin without manifest → fall back to current behavior (name from filename, estimated_tools=10)
- Manifest parsing failure → log warning, still try to mount
- Health check for servers that DON'T support ping → check based on process alive + last-response-time instead
- Plugin dir becomes a subdirectory (was single files only)

**Verification:**
- Test: plugin with manifest → scanner reads tags, env_vars, estimated_tools correctly
- Test: plugin without manifest → legacy behaviour
- Test: plugin crashes mid-flight → `on_error` callback fires → after 3 crashes plugin auto-unmounted

---

## Tier 2 — Medium Impact, Good Additions (Build After Tier 1)

### F-06: Grep-Enhanced Matcher

**Source:** [elvis (omarsar0) — Grep beats vector DBs for coding tasks](https://x.com/omarsar0/status/2055317577031975269)

**What it does:**
The matcher currently uses Jaccard similarity on keyword tokens. This works but misses exact text matches between `task_description` and tool descriptions. Add ripgrep-based scoring as a parallel signal: if the user says "I need to query a PostgreSQL database" and a server's description contains "postgres" + "query" + "database" as adjacent/semi-adjacent substrings, that should score higher than a server that matches "database" via tech_stack but has nothing to do with querying.

**Files to modify:**
- `src/matcher.py` — add `_exact_text_match_score()` that does substring overlap analysis between task_description words and the entry's full description text

**Implementation details:**
- Not a full ripgrep invocation (no subprocess dependency). Just Python `re.search` with word-boundary patterns.
- Each word from task_description gets a regex `\bword\b` match against the description. Multiple matches on one word don't add extra score (it's about presence, not count).
- Combined with existing Jaccard score via weighted sum: `0.7 * tag_overlap + 0.3 * text_match`

**Verification:**
- Test: task_description="query postgres database" → postgres server text-match score > 0, filesystem server = 0
- Test: task_description="" → text_match score = 0 (no degradation)

---

### F-07: WorkGraph-Style Context Management

**Source:** [Utkarsh Sharma — WorkGraph for context loss](https://x.com/UsmanReads/status/2051337875908657259)

**What it does:**
Long tool call chains lose context because each response is truncated or summarised independently. WorkGraph tracks the graph of tool calls and their outputs, then provides a structured summary that preserves the causal chain:

```
User asked: "Deploy the latest build"
  → github_list_commits() → "Found commit abc123"
  → docker_build(commit=abc123) → "Build complete"
  → kubernetes_deploy(image=abc123) → "Deployed to staging"
```

Each step is a node. Instead of truncating each result independently, the graph summariser preserves the chain and only truncates leaf-level detail.

**Files to modify:**
- `src/proxy_server.py` — add `_activity_graph: dict[str, list[GraphNode]]` that tracks tool calls in the current session
- Add a `proxy_session_summary()` tool that returns the activity graph as a compact, readable graph

**New file:**
- `src/graph.py` — GraphNode dataclass, activity graph builder, summary formatter

**Edge cases:**
- Session with no tool calls → empty graph
- 100+ tool calls → graph capped at last 50 entries
- Concurrent tool calls: a graph can have sibling branches that merge later
- Memory: keep graph in-memory only, not persisted

**Verification:**
- Test: 3 sequential tool calls → graph shows chain with correct parent-child edges
- Test: concurrent calls → sibling nodes under same parent
- Test: `proxy_session_summary()` returns valid graph JSON

---

### F-08: Auto-Discovery of local MCP Servers

**Sources:**
- [Ian Lapham — Personal research engine](https://x.com/ianlapham/status/2052567929049272571)
- [Jack H. Ng — Beever Atlas with team-shared memory](https://x.com/nghoihin/status/2053531708478124321)

**What it does:**
Scan the local machine for running MCP servers and auto-register them. Two modes:
1. **Port scan** — check common MCP ports (8100-8200, 8765-8800) for SSE `/sse` endpoints
2. **Unix socket scan** — check `/tmp/*.sock` patterns for stdio-like MCP servers
3. **Launcher integration** — query the launcher registry (port 8765) for already-known services and add them as catalogue entries

**Files to modify:**
- `src/proxy_server.py` — add `proxy_discover_local_servers()` tool
- `src/config.py` — add `auto_discovery_ports: list[int]` default
- `src/plugin_scanner.py` — extend to re-scan on schedule (periodic discovery)

**New file:**
- `src/discovery.py` — port scanner, SSE handshake validator, launcher query

**Edge cases:**
- Port already in use by a non-MCP service → graceful handshake failure
- Duplicate discovery → skip if name/url already in catalogue or active
- Privileged ports (< 1024) → skip with warning
- Rate-limit scanning: max 10 ports per call, 1 call per 60 seconds

**Verification:**
- Test: launcher server running at localhost:8765 → discovery finds it and adds `launcher` entry
- Test: random port with no service → no false positive
- Test: duplicate discovery → returns already-known

---

### F-09: KV Cache-Inspired Eviction Strategy

**Source:** [Maor Elkarat — KV cache > 4-bit weights for VRAM](https://x.com/Maor_Elkarat/status/2050866949643477241)

**What it does:**
The proxy already has LRU eviction (`_evict_lru_if_needed`). But LRU is naive — it doesn't consider *cost of re-loading* a server. A better strategy: evict the server with the **lowest value/cost ratio**.

- **Value**: usage frequency + recency + number of tools
- **Cost**: startup time + memory footprint + network dependency
- **Evict** the server with lowest `value / cost`

This mirrors KV cache management: keep the entries with the best hit-rate per memory-unit.

**Files to modify:**
- `src/proxy_server.py` — add `_value_score(server_name)` and `_cost_score(server_name)` functions, replace simple `next(iter(_active_servers))` with scored eviction
- Track per-server metrics: `mount_count`, `tool_call_count`, `last_use`, `avg_response_time_ms`, `memory_mb`

**Edge cases:**
- Server with no usage data yet → value_score = 0.5 (neutral), cost_score = estimated
- Cost score unknown → default to 1.0
- Sudden spike in usage → value_score weighted heavily toward recency (last 60 seconds 3x multiplier)

**Verification:**
- Test: server A used 10 times, server B used 1 time → B evicted before A
- Test: server C is large (30 tools) but unused → evicted before frequently-used single-tool server
- Test: server with recent use (last 5 seconds) immune from eviction for 30 seconds grace period

---

## Tier 3 — Inspirational / Nice-to-Have (Future)

### F-10: Web Dashboard (Hermes HUD style)

**Source:** [Joey — Hermes HUD Web UI v0.8.0](https://x.com/aijoey/status/2051651808867565965)

Expose a rich dashboard at the HTTP sidecar (port 8765) showing:
- Active servers with real-time tool counts
- Budget usage history (sparkline)
- Per-server metrics (latency, error rate, call count)
- Live audit log viewer
- Mount/unmount controls from the UI

**Would extend:** `src/api.py` (the FastAPI sidecar) significantly.

### F-11: Beever Atlas Shared Memory

**Source:** [Jack H. Ng — 16-tool MCP server with Beever Atlas](https://x.com/nghoihin/status/2053531708478124321)

Add a catalogue entry for Beever Atlas or build a native memory persistence layer that shares context across IDE sessions (VS Code → Cursor → Windsurf). The proxy's `proxy_handshake()` could write to a shared memory store and read back the last session's server configuration.

### F-12: TrustClaw-Style Guardrail Hardening

**Source:** [sarahfim — TrustClaw: 1000+ app integrations](https://x.com/sarahfim/status/2053989393036145121)

TrustClaw's approach to production-grade personal agents has lessons for the proxy's security model:
- Per-tool OAuth scoping (not just allow/deny lists)
- Audit trail per-user (multiple IDE users behind one proxy)
- Approval workflows for privileged operations (write/deploy tools > readonly tools)

---

## Implementation Order

```
Phase 1 (current sprint):
  F-01: Self-Evolving Catalogue       ← highest architectural leverage
  F-03: Env Var Hygiene                ← security baseline
  F-05: Plugin Ecosystem Deepening     ← unlocks all plugin-dependent features

Phase 2 (next sprint):
  F-02: Structured Observability       ← needs F-01's usage stats as input signal
  F-04: Difficulty-Aware Routing       ← needs F-05's plugin system
  F-06: Grep-Enhanced Matcher          ← standalone, low risk

Phase 3 (following sprint):
  F-07: WorkGraph Context              ← needs F-02's tracing for session graph
  F-08: Auto-Discovery                 ← standalone, medium risk
  F-09: KV-Cache Eviction              ← needs F-01's usage stats for accurate scoring

Phase 4 (future):
  F-10: Web Dashboard
  F-11: Beever Atlas Shared Memory
  F-12: TrustClaw Guardrails
```

## Source-By-Source Triage Summary

For reference, every bookmark and why it landed where it did:

| Source | Topic | Tier | Rationale |
|--------|-------|------|-----------|
| Aish — Evolving memory | Self-improving PM | F-01 | Direct map to runtime mutation |
| Gleeson — 724 office | Tools writing tools | F-01, F-05 | Plugin + self-evolution |
| AlphaSignalAI — Hermes self-evolution | Prompt/code rewriting | F-01 | Confirms approach |
| Zhihao Jia — Motus Tracing | Observability | F-02 | Audit log is already there, just flat |
| 0xSero — Env var hygiene | Security scanning | F-03 | Directly addresses child process risk |
| Guri Singh — Cybersec library | Security skills | F-03 | Complements env scan |
| 0xCS — Model router | LLM routing | F-04 | Plugin hook pattern |
| Kappaemme — Complexity analysis | Codebase scan plugin | F-05 | Concrete plugin example |
| Sukh Saroy — Composable pipelines | Tool composition | F-05 | Plugin architecture |
| elvis/omarsar0 — Grep vs vector DBs | Text matching | F-06 | Validates + improves current matcher |
| Utkarsh Sharma — WorkGraph | Context loss | F-07 | Complements tracing |
| Ian Lapham — Research engine | Agent discovery | F-08 | Auto-discovery pattern |
| Jack H. Ng — Beever Atlas | Shared memory | F-08, F-11 | Discovery + future memory |
| Maor Elkarat — KV cache | Eviction strategy | F-09 | Validates + improves LRU |
| Joey — Hermes HUD | Web UI | F-10 | Nice dashboard |
| Sarah Drasner — Context windows | Background | Reference | Knowledge only |
| Nelly — MemPalace | Memory system | Reference | Interesting but orthogonal to proxy |
| Lilian Weng — Chain-of-thought | Test-time compute | Reference | Not proxy-level |
| Paul Iusztin — Claude Code + MCP | Usage note | Skip | Not actionable |
| Graeme — Hermes praise | Opinion | Skip | Not code |
| Jesse Genet — /goal command | Usage tip | Skip | Hermes feature, not proxy |
| Nous Research — Official post | Announcement | Skip | Not code |
| Winston Brown — Agentic stack | Architecture | Skip | Hermes-level, not proxy-level |
| Guri Singh — 10 repos / Agency | List of repos | Reference | Review links, no direct action |
| elvis/omarsar0 — LLM Wikis | Reference | Reference | Related research |
| Ronin — Autobrowse | Browser agent | Reference | Interesting but separate domain |
| thsottiaux — Chronicle | Memory building | F-01 | Supports self-evolution |

---

## Files Likely to Change (Master List)

| File | F-01 | F-02 | F-03 | F-04 | F-05 | F-06 | F-07 | F-08 | F-09 |
|------|------|------|------|------|------|------|------|------|------|
| `src/proxy_server.py` | M | M | M | M | M | - | M | M | M |
| `src/config.py` | M | M | M | - | M | - | - | M | - |
| `src/matcher.py` | M | - | - | - | - | M | - | - | - |
| `src/guardrails.py` | - | M | M | - | - | - | - | - | - |
| `src/plugin_scanner.py` | M | - | - | M | M | - | - | - | - |
| `src/loaders/rest.py` | - | - | - | - | - | - | - | - | - |
| `src/api.py` | - | - | - | - | - | - | - | M | - |
| `src/tracer.py` (new) | - | C | - | - | - | - | - | - | - |
| `src/graph.py` (new) | - | - | - | - | - | - | C | - | - |
| `src/discovery.py` (new) | - | - | - | - | - | - | - | C | - |
| `catalogue.json` | - | - | - | - | - | - | - | - | - |
| `proxy_config.json` | - | - | - | - | - | - | - | - | - |

M = Modify, C = Create, - = Unchanged

## Verification Strategy

Each feature gets:
1. **Unit tests** in `tests/` — at least 3 per feature covering happy path, edge cases, and failure modes
2. **Integration test** — fire up the proxy, make handshake calls, verify correct behaviour
3. **Existing regression** — all 59 existing tests must pass after each phase
4. **Stdout discipline check** — no feature should introduce new `print()` or any output to stdout that would break the MCP transport

---

## Research Round 2: Bookmarks CSV (June 2026) — Token Efficiency, Knowledge Servers & Smarter Selection

**Sources (from ai_bookmarks_master_june_template.xlsx - Master Bookmarks.csv analysis):**
- LAP (Lap-Platform/LAP): Lean agent-native API specs (5-40× compression, typed contracts, complementary to MCP). Registry + compiler.
- 9router: RTK auto-compression of tool_result content (20-40% savings).
- memtrace: Bi-temporal structural code KG exposed as 25+ MCP tools. Deterministic, fast, low-memory. Strong for "project understanding".
- Beever Atlas: Team chat → wiki + Neo4j graph with 28-tool MCP server (auth, rate limits, citations). (Already added to catalogue.json as starter.)
- SimpleMem: Lifelong semantic memory + compression for context bloat (MCP server available).
- Agentic Design Patterns (Antonio Gulli): 424-page code-backed book with dedicated Ch.10 MCP, Ch.18 Guardrails, Routing, Tool Use, Memory Management, Resource-Aware Optimization.
- Others (agent-sandbox for isolation ideas).

**Scoring criteria used:** Same as original plan (architectural fit, impact on budgets/context, effort, signal density). All ideas preserve stdio purity and build on existing subsystems (steering, matcher, REST loader, deferred mounting, catalogue merge).

**Goal for this round:** Directly attack the two biggest token consumers — *input tool schemas/specs* and *output tool results* — while making selection (matcher) and catalogue smarter.

---

### F-11: Advanced Output Compression (9router RTK + Steering Evolution)

**What it does:**
Current `_apply_steering` does pick/omit/template + crude token_budget truncation on JSON. Extend it with heuristic "RTK-style" compression for common noisy outputs (git diffs, logs, file listings, API responses, stack traces).

- Auto-detect output type (or use per-catalogue `compression_profile`).
- Apply smart rules: drop repeated lines, summarize diffs, truncate arrays intelligently, keep high-signal keys.
- Optional learned preferences (persist pick/omit from usage, building on F-01).

**Files to modify:**
- `src/proxy_server.py` — extend `_apply_steering` and `_get_nested`.
- `src/config.py` / ProxyEntry — add optional `compression_profile: str | None` and `auto_compress: bool`.
- `catalogue.json` — seed profiles for heavy servers (e.g. github, slack).
- `tests/test_steering_rest.py` — expand with new cases.

**New file (optional small):** `src/compression.py` — reusable heuristics (keep pure Python, no new deps).

**Cherry-picks:**
- 9router RTK techniques for tool_result.
- LAP "lean mode" philosophy (infer from names, drop redundancy).

**Risks / Edge cases:**
- Over-compression loses critical data → always keep `proxy_list_tools` + raw fallback via flag.
- Non-JSON text → apply length + line-deduplication only.

**Verification:**
- Unit: large git diff input → compressed keeps headers + changed hunks, drops noise.
- Integration: activate heavy server, call tool → verify token reduction vs baseline while preserving usability.
- No regression on existing pick/omit/template tests.

**Priority:** Tier 1 (directly multiplies value of every activated server).

---

### F-12: LAP Integration for Lean Input Specs (REST Bridges & Tool Schemas)

**What it does:**
`proxy_activate_from_spec` currently shells out to `40mcp generate` → verbose JSON configs. 

- Add optional `use_lap: bool` or auto-detect.
- Support ingesting `.lap` files (or call `lapsh compile` if available) to generate dramatically smaller configs.
- Apply LAP-style semantic compression (type directives, common fields) to our generated `configs/*.json` or even to steering output.
- Optionally expose LAP-compressed tool schemas when mounting (if we can hook schema generation).

**Files to modify:**
- `src/proxy_server.py` — update `proxy_activate_from_spec` (support lapsh or direct LAP parser).
- `src/loaders/rest.py` — add LAP config loader path (or post-process existing 40mcp output).
- `catalogue.json` — add optional `lap_compressed: true` examples; seed LAP-enhanced entries.

**Dependencies:** Optional (fall back gracefully if `lapsh` not installed). Document in README.

**Cherry-picks from LAP research:**
- 5-40× savings on verbose OpenAPI specs.
- Typed contracts (`enum(...)`, `str(uuid)`) reduce hallucination.
- Explicitly "LAP can compress MCP tool schemas."

**Risks:**
- External tool dependency → make fully optional, with pure-Python fallback for basic compression.
- Round-tripping: preserve ability to convert back.

**Verification:**
- Generate from a large OpenAPI (e.g. Stripe) → compare token count of generated config with/without LAP mode.
- End-to-end: activate REST server with LAP → tool calls succeed with fewer context tokens.

**Priority:** Tier 1 (improves every REST/custom API bridge and future tool schema exposure).

---

### F-13: Smarter Project Context & Matcher (memtrace + Self-Evolution)

**What it does:**
Current matcher is pure keyword/Jaccard + file ext + requirements (good but shallow).

- Enrich `ProjectContext` optionally with structural signals (imports, symbols from open files or a fast local indexer if present).
- Persist usage stats (which servers/tools succeed) across handshakes/sessions (builds directly on F-01).
- Boost scores for knowledge/memory servers (Beever Atlas style) when task_description mentions "history", "decisions", "team", "wiki", "previous".

**Files to modify:**
- `src/matcher.py` — add optional structural scorer (if `open_files` contain parseable code); integrate usage boost.
- `src/proxy_server.py` — capture usage in `audited_call`, pass richer context from handshake.
- `src/config.py` — persist `usage_stats` or `activation_history`.
- `catalogue.json` — tag knowledge servers appropriately (already started with beever-atlas).

**Cherry-picks:**
- memtrace: deterministic graph > pure LLM/vector for code; temporal + impact scoring.
- Beever Atlas + SimpleMem: distilled knowledge beats raw history.
- Existing F-01 + F-06: usage + grep/text signals.

**Edge cases:**
- No structural data available → graceful fallback to current scoring.
- Cold start → no usage data.

**Verification:**
- Test: task mentions "refactor auth" + Django files open → postgres + security servers rank higher.
- Test: repeated successful use of a server → its score increases on next handshake.
- Unit tests for new scoring components.

**Priority:** Tier 1-2 (core value prop of "right tools for context").

---

### F-14: Knowledge Server Catalogue Expansion + Docs Alignment

**What it does:**
- Add high-signal MCP knowledge servers (Beever Atlas already added; plan memtrace, SimpleMem-style when public/stable).
- Update docs to reference external pattern language (Gulli book Ch. 10 MCP, Ch. 18 Guardrails, Resource-Aware Optimization, Routing).
- Add a `proxy_get_research_hints()` or simply document in `CONTEXT.md` / README the key external references.

**Files to modify:**
- `catalogue.json`
- `docs/memories/patterns_and_lessons.md` (already started with S-18)
- `CONTEXT.md` and `README.md` (reference the patterns book and research/ folder).
- Optionally `research/LINKS.md` (already updated).

**Priority:** Low-code, high-documentation value.

---

## Updated Master Change Table (New Round)

| File                  | F-11 | F-12 | F-13 | F-14 |
|-----------------------|------|------|------|------|
| `src/proxy_server.py` | M    | M    | M    | -    |
| `src/config.py`       | M    | -    | M    | -    |
| `src/matcher.py`      | -    | -    | M    | -    |
| `src/loaders/rest.py` | -    | M    | -    | -    |
| `catalogue.json`      | M    | M    | M    | M    |
| `tests/test_steering*`| M    | M    | -    | -    |
| Docs (CONTEXT, patterns, README) | - | - | - | M |

## Recommended Slice Order (Small, Ratcheted)

1. F-11 Output Compression heuristics (quick win on existing steering).
2. F-12 LAP support (leverages existing `proxy_activate_from_spec`).
3. F-13 Matcher evolution (builds on F-01/F-06 already in plan).
4. F-14 Docs + more catalogue entries.

After each slice:
- `git add -A && git commit -m "feat: ..."`
- Run full test suite + manual MCP handshake test.
- Update patterns_and_lessons.md with any new lessons.

This round keeps the spirit of the original plan while directly incorporating the latest high-signal external references. All changes stay minimal, stdio-safe, and backwards compatible.
