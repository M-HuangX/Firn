"""JWT authentication: token creation, verification, login handler.

Tokens are stored in httpOnly cookies (not Authorization header).
Two roles: admin (password login, 24h) and visitor (auto-issued, 1h).
"""

from __future__ import annotations

import os
import time
import uuid

from jose import JWTError, jwt

# --- Config (from env) ---

_JWT_SECRET: str | None = None
_ADMIN_PASSWORD: str | None = None
_JWT_ALGORITHM = "HS256"
ADMIN_EXPIRY_SECONDS = 24 * 3600  # 24 hours
VISITOR_EXPIRY_SECONDS = 3600  # 1 hour
COOKIE_NAME = "access_token"


_PLACEHOLDER_VALUES = frozenset({
    "change-me-to-a-random-64-char-string",
    "change-me-to-a-strong-password",
})


def _get_jwt_secret() -> str:
    global _JWT_SECRET
    if _JWT_SECRET is None:
        _JWT_SECRET = os.environ.get("JWT_SECRET", "")
        if not _JWT_SECRET or _JWT_SECRET in _PLACEHOLDER_VALUES:
            raise RuntimeError("JWT_SECRET must be set to a secure random value")
    return _JWT_SECRET


def _get_admin_password() -> str:
    global _ADMIN_PASSWORD
    if _ADMIN_PASSWORD is None:
        _ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
        if not _ADMIN_PASSWORD or _ADMIN_PASSWORD in _PLACEHOLDER_VALUES:
            raise RuntimeError("ADMIN_PASSWORD must be set to a secure value")
    return _ADMIN_PASSWORD


# --- Token creation ---

def create_token(role: str, expiry_seconds: int | None = None) -> str:
    """Create a JWT token for the given role."""
    if expiry_seconds is None:
        expiry_seconds = (
            ADMIN_EXPIRY_SECONDS if role == "admin" else VISITOR_EXPIRY_SECONDS
        )
    now = int(time.time())
    payload = {
        "sub": role,
        "role": role,
        "iat": now,
        "exp": now + expiry_seconds,
        "jti": uuid.uuid4().hex[:16],
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=_JWT_ALGORITHM)


def create_admin_token() -> str:
    return create_token("admin")


def create_visitor_token() -> str:
    return create_token("visitor")


# --- Token verification ---

def verify_token(token: str) -> dict | None:
    """Verify and decode a JWT token. Returns payload dict or None if invalid."""
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[_JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


# --- Password check ---

def verify_admin_password(password: str) -> bool:
    """Check if the provided password matches the admin password (timing-safe)."""
    import hmac

    return hmac.compare_digest(password.encode(), _get_admin_password().encode())
