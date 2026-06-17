# agent-sandbox (kubernetes-sigs) — Isolated Stateful Workloads for AI Agents

**URL**: https://github.com/kubernetes-sigs/agent-sandbox  
**Captured**: 2026-06-17  
**Stack**: Kubernetes CRDs + controller (Sandbox, SandboxClaim, etc.). Supports strong isolation runtimes (gVisor, Kata).

## What it is
A standardized way on Kubernetes to run isolated, stateful, singleton "sandbox" pods. Explicitly motivated by AI agent runtimes that need to execute untrusted/LLM-generated code safely, with stable identity, persistent storage, hibernation, etc.

## Relevance
Our proxy frequently spawns child processes for MCP servers (`npx`, `uvx`, `uv run`, custom stdio). These are untrusted in the sense that:
- Catalogue entries come from the community
- `proxy_add_custom_proxy` allows users/agents to add more (we currently block stdio for this reason)
- Guardrails exist (description scanning, rate limits, audit), but no OS-level sandboxing, resource caps, or filesystem/network isolation for the children.

## Cherry-pick / lessons
- Threat model: Treating tool servers / code execution as needing strong isolation.
- Features worth considering (even outside k8s):
  - Resource limits and cgroups-style controls on spawned subprocesses.
  - Namespaced / chroot / landlock / bubblewrap isolation for local stdio children (Linux).
  - Stable "identity" for long-lived tool servers.
  - Hibernation / pause-resume of expensive servers.
- The "Sandbox" abstraction itself could inspire a future mode where certain heavy or custom servers run in containers.
- See also the companion "awesome-ai-sandboxes" list in the bookmarks.

## Limitations for us
- Primarily a k8s deployment concern. Our primary use is local stdio via IDE MCP config.
- Adding containerization would increase complexity (Docker dependency, startup time for tools).
- Good for future "production / multi-tenant proxy" mode rather than v1 local use.

**Our mitigations today**: Rejection of arbitrary stdio in `proxy_add_custom_proxy`, guardrails.py, explicit PATH and env control, audit.log.

Worth monitoring as agent security matures.
