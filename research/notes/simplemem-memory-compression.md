# SimpleMem — Efficient Lifelong Memory for LLM Agents (with MCP support)

**URL**: https://github.com/aiming-lab/SimpleMem  
**Captured**: 2026-06-17  
**Key features**: Semantic compression, lifelong/cross-session memory, multimodal (text/image/audio/video), self-evolving variants (EvolveMem), MCP server

## What it is
A memory system for agents that stores, compresses, and retrieves long-term memories using semantic (lossless?) techniques. Reduces context bloat in long-running agent sessions. Has first-class MCP server support (including hosted option) so any MCP client can use it as a tool server.

## Relevance to Dynamic MCP Proxy
We fight context bloat on the *tool surface* via:
- Lazy/deferred mounting (S-10)
- Tool budget + LRU eviction
- Response steering (pick/omit/template/token_budget) [S-12]

SimpleMem fights it on the *conversation / state* side — exactly the other half of the token problem for long-lived agents. Agents using our proxy will still accumulate history; better memory backends help overall.

It is itself an MCP server, so:
- Good candidate for `user.catalogue.json` or public catalogue (memory tools are commonly needed).
- Demonstrates clean MCP server packaging (Docker, skill, PyPI).

## Cherry-pick opportunities
- **Compression techniques**: Study their semantic compression approach. Could inspire better defaults or learned steering rules in our `audited_call` / steering layer.
- **Cross-session / lifelong**: Our proxy currently has no persistence of "which servers were useful for what contexts" across restarts. A lightweight memory of past handshakes + outcomes could improve the matcher over time (meta-learning for tool selection).
- **Self-evolving memory**: EvolveMem uses LLM-driven diagnosis to improve its own retrieval. Interesting pattern for making the proxy's matcher/catalogue "learn".
- MCP server best practices: How they package and expose memory ops as clean MCP tools.

## Benchmarks / claims
- Strong SOTA improvements on LoCoMo, MemBench, etc. (esp. with multimodal and EvolveMem).
- Explicitly targets "reduces context bloat in long agentic sessions".

## What to cherry-pick vs avoid
- Great for *agent memory layer*. Not a direct substitute for our tool proxy concerns.
- Multimodal may be overkill unless we want to steer image/audio tool responses.
- Use as an optional "memory server" in catalogue rather than integrating deeply unless we decide to add proxy-level memory.

Related patterns in our docs: [S-12] Response Steering, long-term LTM in AGENTS.md / docs/memories/.
