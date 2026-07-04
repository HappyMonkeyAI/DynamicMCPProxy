"""
Security layer — prompt-injection guardrails, rate limiting, audit logging.
Dual-layer auth (JWT + HMAC) is in auth.py.

All functions are synchronous so they can be called from FastMCP tool wrappers.
"""
from __future__ import annotations

import json
import re
import hashlib
import uuid
import time
import contextvars
from contextlib import contextmanager
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
    encoded = result.encode("utf-8")
    if len(encoded) <= _MAX_RESULT_BYTES:
        return result
    # Truncate to max bytes, then decode with 'ignore' to drop any partial multibyte character at the end.
    truncated = encoded[:_MAX_RESULT_BYTES].decode("utf-8", errors="ignore")
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
_receipt_caller: contextvars.ContextVar[str] = contextvars.ContextVar("receipt_caller", default="anonymous")
_receipt_run_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("receipt_run_id", default=None)
_SENSITIVE_KEY_RE = re.compile(
    r"(api[_-]?key|token|secret|password|passwd|authorization|auth|cookie|session|private[_-]?key)",
    re.IGNORECASE,
)


def new_run_id() -> str:
    """Generate an opaque run id for correlating one receipt tree."""
    return f"run_{uuid.uuid4().hex}"


def new_span_id() -> str:
    """Generate a short opaque span id for a single receipt event."""
    return uuid.uuid4().hex[:16]


def current_caller() -> str:
    """Return the receipt caller bound to the current request context."""
    return _receipt_caller.get()


def current_run_id() -> Optional[str]:
    """Return the receipt run id bound to the current request context, if any."""
    return _receipt_run_id.get()


@contextmanager
def receipt_context(caller: str, run_id: Optional[str] = None):
    """Bind caller/run id for internal receipt creation without public tool args."""
    caller_token = _receipt_caller.set(caller)
    run_token = _receipt_run_id.set(run_id)
    try:
        yield
    finally:
        _receipt_caller.reset(caller_token)
        _receipt_run_id.reset(run_token)


def _hash_value(value: object) -> str:
    """Stable short fingerprint for values without storing the raw payload."""
    raw = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _summarize_value(key: str, value: object) -> object:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        summary = {
            "type": "str",
            "length": len(value),
            "sha256": _hash_value(value),
        }
        if _SENSITIVE_KEY_RE.search(key):
            summary["redacted"] = True
        return summary
    if isinstance(value, list):
        return {
            "type": "list",
            "length": len(value),
            "sha256": _hash_value(value),
        }
    if isinstance(value, dict):
        return {
            "type": "dict",
            "keys": sorted(str(k) for k in value.keys())[:50],
            "sha256": _hash_value(value),
        }
    return {
        "type": type(value).__name__,
        "sha256": _hash_value(value),
    }


def summarize_arguments(arguments: Optional[dict]) -> dict:
    """
    Return privacy-safe argument summaries for receipts.

    Raw strings and nested payloads are never logged; strings/lists/dicts get
    type/size/fingerprint metadata so calls can be compared without leaking
    customer data or credentials. Numbers/bools are kept because they are often
    operationally useful and low-risk.
    """
    if not arguments:
        return {}
    return {str(k): _summarize_value(str(k), v) for k, v in arguments.items()}


def init_audit_log(config: AppConfig) -> None:
    global _audit_path
    if not config.receipts_enabled:
        _audit_path = None
        return
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
    event_type: str = "tool.call",
    run_id: Optional[str] = None,
    span_id: Optional[str] = None,
    parent_span_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    """Append a single structured log line to the audit log."""
    if _audit_path is None:
        return
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "run_id": run_id or new_run_id(),
        "span_id": span_id or new_span_id(),
        "tool": tool,
        "caller": caller,
        "outcome": outcome,
        "latency_ms": round(latency_ms, 2),
    }
    if parent_span_id:
        record["parent_span_id"] = parent_span_id
    if extra:
        record.update(extra)
    with _audit_lock:
        with open(_audit_path, "a") as f:
            f.write(json.dumps(record) + "\n")
