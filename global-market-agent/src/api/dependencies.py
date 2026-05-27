"""FastAPI dependencies: auth, rate limiting, shared resources."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import Cookie, Depends, HTTPException, Request, Response

from src.api.auth import (
    COOKIE_NAME,
    create_visitor_token,
    verify_token,
)
from src.knowledge_base.kb_api import KnowledgeBase


# ---------------------------------------------------------------------------
# User context
# ---------------------------------------------------------------------------

@dataclass
class CurrentUser:
    role: str  # "admin" or "visitor"
    token_payload: dict


async def get_current_user(
    request: Request,
    response: Response,
    access_token: str | None = Cookie(None, alias=COOKIE_NAME),
) -> CurrentUser:
    """Extract and verify JWT from cookie. Auto-issues visitor token if none."""
    if access_token:
        payload = verify_token(access_token)
        if payload:
            return CurrentUser(role=payload["role"], token_payload=payload)

    # No valid token — auto-issue visitor JWT
    token = create_visitor_token()
    payload = verify_token(token)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=3600,
        path="/",
    )
    return CurrentUser(role="visitor", token_payload=payload)  # type: ignore[arg-type]


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Dependency that rejects non-admin users with 404 (not 403, to hide endpoint existence)."""
    if user.role != "admin":
        raise HTTPException(status_code=404)
    return user


# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------

def get_kb() -> KnowledgeBase:
    """Return a KnowledgeBase instance. Stateless — safe to create per request."""
    return KnowledgeBase()


# ---------------------------------------------------------------------------
# Rate limiter (in-memory, per-role)
# ---------------------------------------------------------------------------

_RATE_LIMITS = {
    "admin": 1000,   # requests per minute
    "visitor": 100,
}


@dataclass
class _RateBucket:
    count: int = 0
    window_start: float = 0.0


_buckets: dict[str, _RateBucket] = defaultdict(lambda: _RateBucket())


async def rate_limit(request: Request, user: CurrentUser = Depends(get_current_user)) -> None:
    """Simple per-role in-memory rate limiter (sliding window per minute)."""
    key = f"{user.role}:{request.client.host if request.client else 'unknown'}"
    limit = _RATE_LIMITS.get(user.role, 100)
    now = time.time()
    bucket = _buckets[key]

    if now - bucket.window_start > 60:
        bucket.count = 0
        bucket.window_start = now

    bucket.count += 1
    if bucket.count > limit:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Try again later.",
        )


# ---------------------------------------------------------------------------
# Visitor analysis budget
# ---------------------------------------------------------------------------

_VISITOR_ANALYSIS_LIMIT_PER_DAY = 1  # per visitor (cookie+IP)


@dataclass
class _VisitorBudget:
    """Track visitor analysis usage per day."""
    daily_counts: dict[str, int] = field(default_factory=dict)  # "YYYY-MM-DD:key" -> count
    global_daily: dict[str, int] = field(default_factory=dict)  # "YYYY-MM-DD" -> count


_visitor_budget = _VisitorBudget()


def check_visitor_analysis_budget(request: Request, user: CurrentUser) -> None:
    """Check if a visitor can submit an analysis. Raises 429 if over budget."""
    if user.role == "admin":
        return

    import os
    from datetime import date

    today = date.today().isoformat()
    ip = request.client.host if request.client else "unknown"
    visitor_key = f"{today}:{ip}"

    # Per-visitor daily limit
    if _visitor_budget.daily_counts.get(visitor_key, 0) >= _VISITOR_ANALYSIS_LIMIT_PER_DAY:
        raise HTTPException(status_code=429, detail="Visitor analysis limit reached (1/day).")

    # Global daily budget
    global_budget = int(os.environ.get("VISITOR_DAILY_BUDGET", "10"))
    if _visitor_budget.global_daily.get(today, 0) >= global_budget:
        raise HTTPException(status_code=429, detail="Global visitor analysis budget exhausted.")

    # Consume budget
    _visitor_budget.daily_counts[visitor_key] = _visitor_budget.daily_counts.get(visitor_key, 0) + 1
    _visitor_budget.global_daily[today] = _visitor_budget.global_daily.get(today, 0) + 1
