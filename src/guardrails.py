"""
Security layer — prompt-injection guardrails, rate limiting, audit logging.
Dual-layer auth (JWT + HMAC) is in auth.py.

All functions are synchronous so they can be called from FastMCP tool wrappers.
"""
from __future__ import annotations

import json
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

from .config import AppConfig

# ---------------------------------------------------------------------------
# Prompt injection detection
# ---------------------------------------------------------------------------

# Patterns that strongly suggest prompt-injection inside a tool description
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a|an)", re.IGNORECASE),
    re.compile(r"new\s+instructions?:", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"<\s*/?system\s*>", re.IGNORECASE),
    re.compile(r"\bdo\s+not\s+reveal\b", re.IGNORECASE),
    re.compile(r"\bforget\s+(everything|all|prior)\b", re.IGNORECASE),
    re.compile(r"\bact\s+as\s+(if\s+you\s+are|a\b)", re.IGNORECASE),
]

_MAX_TOOL_DESCRIPTION_BYTES = 4096   # truncate descriptions beyond this
_MAX_RESULT_BYTES = 32_768           # truncate tool results beyond this (~32 KB)


def scan_tool_description(name: str, description: str) -> list[str]:
    """
    Check a tool description for prompt-injection patterns.
    Returns a list of human-readable warnings (empty = clean).
    """
    warnings: list[str] = []
    if len(description.encode()) > _MAX_TOOL_DESCRIPTION_BYTES:
        warnings.append(
            f"Tool '{name}' description is suspiciously long "
            f"({len(description.encode())} bytes > {_MAX_TOOL_DESCRIPTION_BYTES})."
        )
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(description):
            warnings.append(
                f"Tool '{name}' description matched injection pattern: {pattern.pattern!r}"
            )
    return warnings


def truncate_result(result: str) -> str:
    """Cap tool results at _MAX_RESULT_BYTES to protect the AI context window."""
    encoded = result.encode("utf-8", errors="replace")
    if len(encoded) <= _MAX_RESULT_BYTES:
        return result
    truncated = encoded[:_MAX_RESULT_BYTES].decode("utf-8", errors="replace")
    return truncated + f"\n\n[... result truncated at {_MAX_RESULT_BYTES} bytes ...]"


# ---------------------------------------------------------------------------
# Tool allow / deny list
# ---------------------------------------------------------------------------

def is_tool_allowed(tool_name: str, config: AppConfig) -> bool:
    """
    Return False if the tool is on the denylist, or if an allowlist is defined
    and the tool is not on it.
    """
    if config.tool_denylist and tool_name in config.tool_denylist:
        return False
    if config.tool_allowlist and tool_name not in config.tool_allowlist:
        return False
    return True


# ---------------------------------------------------------------------------
# Rate limiter (in-process, per-caller token bucket)
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Simple sliding-window rate limiter keyed by caller identity."""

    def __init__(self, max_rpm: int) -> None:
        self._max_rpm = max_rpm
        self._window: dict[str, deque[float]] = {}
        self._lock = Lock()

    def is_allowed(self, caller: str) -> bool:
        now = time.monotonic()
        window_start = now - 60.0
        with self._lock:
            timestamps = self._window.setdefault(caller, deque())
            # Drop timestamps older than 1 minute
            while timestamps and timestamps[0] < window_start:
                timestamps.popleft()
            if len(timestamps) >= self._max_rpm:
                return False
            timestamps.append(now)
            return True


_rate_limiter: Optional[_RateLimiter] = None


def init_rate_limiter(config: AppConfig) -> None:
    global _rate_limiter
    _rate_limiter = _RateLimiter(config.rate_limit_rpm)


def check_rate_limit(caller: str = "anonymous") -> bool:
    """Return False if the caller has exceeded the rate limit."""
    if _rate_limiter is None:
        return True
    return _rate_limiter.is_allowed(caller)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

_audit_lock = Lock()
_audit_path: Optional[Path] = None


def init_audit_log(config: AppConfig) -> None:
    global _audit_path
    p = Path(config.audit_log_path)
    if not p.is_absolute():
        p = Path(__file__).parent.parent / p
    _audit_path = p


def audit(
    *,
    tool: str,
    caller: str = "anonymous",
    outcome: str = "ok",
    latency_ms: float = 0.0,
    extra: Optional[dict] = None,
) -> None:
    """Append a single structured log line to the audit log."""
    if _audit_path is None:
        return
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "caller": caller,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
    }
    if extra:
        record.update(extra)
    with _audit_lock:
        with open(_audit_path, "a") as f:
            f.write(json.dumps(record) + "\n")
