"""
Dual-layer authentication middleware.

Layer 1: JWT (RS256) — primary auth for human/IDE callers.
Layer 2: HMAC (API key via X-API-Key header) — service-to-service.

Both layers are DISABLED by default (auth_enabled = false in proxy_config.json).
Enable in production by setting auth_enabled = true and providing keys.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional

from .config import AppConfig

# jwt is optional — only imported when auth is enabled
_jwt_available = False
try:
    import jwt as _jwt  # PyJWT
    _jwt_available = True
except ImportError:
    pass


class AuthError(Exception):
    """Raised when authentication fails."""


def _load_jwt_public_key(path: str) -> str:
    with open(path) as f:
        return f.read()


def verify_jwt(token: str, config: AppConfig) -> dict:
    """
    Decode and verify a JWT Bearer token using the configured RSA public key.
    Returns the decoded payload dict on success, raises AuthError on failure.
    """
    if not _jwt_available:
        raise AuthError("PyJWT is not installed. Run: uv add PyJWT")
    if not config.jwt_public_key_path:
        raise AuthError("jwt_public_key_path is not configured.")
    try:
        public_key = _load_jwt_public_key(config.jwt_public_key_path)
        payload = _jwt.decode(token, public_key, algorithms=["RS256"])
        return payload
    except _jwt.ExpiredSignatureError:
        raise AuthError("JWT token has expired.")
    except _jwt.InvalidTokenError as exc:
        raise AuthError(f"Invalid JWT token: {exc}")


def verify_hmac(api_key: str, config: AppConfig) -> bool:
    """
    Constant-time comparison of the provided API key against the configured HMAC key.
    Returns True on success, raises AuthError on failure.
    """
    if not config.hmac_api_key:
        raise AuthError("hmac_api_key is not configured.")
    expected = config.hmac_api_key.encode()
    provided = api_key.encode()
    if not hmac.compare_digest(
        hashlib.sha256(expected).digest(),
        hashlib.sha256(provided).digest(),
    ):
        raise AuthError("Invalid API key.")
    return True


def authenticate(
    *,
    bearer_token: Optional[str] = None,
    api_key: Optional[str] = None,
    config: AppConfig,
) -> dict:
    """
    Try JWT first, then HMAC. Returns identity dict on success.
    Raises AuthError if auth is enabled and neither credential is valid.

    If auth_enabled is False, returns a guest identity immediately.
    """
    if not config.auth_enabled:
        return {"sub": "anonymous", "auth": "disabled"}

    last_error: Optional[AuthError] = None

    if bearer_token:
        try:
            payload = verify_jwt(bearer_token, config)
            return {**payload, "auth": "jwt"}
        except AuthError as exc:
            last_error = exc

    if api_key:
        try:
            verify_hmac(api_key, config)
            return {"sub": "service", "auth": "hmac"}
        except AuthError as exc:
            last_error = exc

    raise last_error or AuthError("No credentials provided.")
