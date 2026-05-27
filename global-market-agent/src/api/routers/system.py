"""System routes: health, status, auth (login + /me)."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Response

from src.api.auth import (
    COOKIE_NAME,
    create_admin_token,
    verify_admin_password,
)
from src.api.dependencies import CurrentUser, get_current_user, get_kb, rate_limit
from src.api.models import HealthResponse, LoginRequest, SystemStatus, TokenInfo
from src.api.services import get_active_executions
from src.knowledge_base.kb_api import KnowledgeBase

router = APIRouter(dependencies=[Depends(rate_limit)])


# --- Health & Status ---


@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(active_executions=len(get_active_executions()))


@router.get("/status", response_model=SystemStatus)
async def status(kb: KnowledgeBase = Depends(get_kb)):
    themes = kb.list_themes()
    stocks = kb.list_stocks()
    events = kb.list_events()
    pending = kb.list_unread()
    digested = kb.list_read()
    core_mind = kb.read_core_mind()
    last_updated = kb.get_last_updated()

    # Day N: days since first pipeline event
    first_date = _get_first_event_date(kb)
    if first_date:
        from datetime import date

        day_n = (date.today() - first_date).days + 1
    else:
        day_n = _compute_day_n(kb)  # fallback to old method

    return SystemStatus(
        day_n=day_n,
        total_articles=len(pending) + len(digested),
        total_themes=len(themes),
        total_stocks=len(stocks),
        total_events=len(events),
        core_mind_chars=len(core_mind) if core_mind else 0,
        library_unread=len(pending),
        library_read=len(digested),
        last_digest=_get_last_digest_time(),
        last_analysis=_get_last_analysis_time(),
        llm_provider=os.environ.get("LLM_PROVIDER", "unknown"),
    )


def _get_first_event_date(kb: KnowledgeBase):
    """Read first line of pipeline_events.jsonl, parse ts -> date."""
    import json
    from datetime import date

    events_path = kb.data_root / "meta" / "pipeline_events.jsonl"
    if not events_path.is_file():
        return None
    try:
        with open(events_path, encoding="utf-8") as f:
            first_line = f.readline().strip()
        if not first_line:
            return None
        evt = json.loads(first_line)
        ts = evt.get("ts", "")
        date_str = ts[:10]
        return date.fromisoformat(date_str)
    except (json.JSONDecodeError, ValueError, OSError):
        return None


def _get_last_analysis_time() -> str | None:
    """Find the most recent completed analysis start_time from logs."""
    import json
    from src.api import LOGS_DIR
    if not LOGS_DIR.exists():
        return None
    for d in sorted(LOGS_DIR.iterdir(), key=lambda x: x.name, reverse=True):
        if not d.is_dir():
            continue
        info_path = d / "execution_info.json"
        if not info_path.is_file():
            continue
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
            # Analysis has ticker field; digest does not
            if info.get("ticker") and info.get("start_time"):
                return info["start_time"]
        except (json.JSONDecodeError, OSError):
            continue
    return None


def _get_last_digest_time() -> str | None:
    """Find the most recent digest start_time from logs."""
    import json
    from src.api import LOGS_DIR
    if not LOGS_DIR.exists():
        return None
    for d in sorted(LOGS_DIR.iterdir(), key=lambda x: x.name, reverse=True):
        if not d.is_dir():
            continue
        info_path = d / "execution_info.json"
        if not info_path.is_file():
            continue
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
            # Digest has no ticker field (analysis does)
            if not info.get("ticker") and info.get("start_time"):
                return info["start_time"]
        except (json.JSONDecodeError, OSError):
            continue
    return None


def _compute_day_n(kb: KnowledgeBase) -> int:
    """Compute Day N = days since the first digested article appeared (fallback)."""
    from datetime import date

    digested_dir = kb.root / "library" / "read"
    if not digested_dir.exists():
        return 0
    files = sorted(digested_dir.iterdir())
    if not files:
        return 0
    # Parse date from oldest filename (YYYY-MM-DD prefix in slug)
    oldest_name = files[0].stem
    try:
        date_str = oldest_name[:10]  # "2026-05-10"
        first_date = date.fromisoformat(date_str)
        return (date.today() - first_date).days + 1
    except (ValueError, IndexError):
        return 0


# --- Auth ---


@router.post("/auth/login")
async def login(body: LoginRequest, response: Response):
    if not verify_admin_password(body.password):
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Invalid password")
    token = create_admin_token()
    secure = os.environ.get("ENVIRONMENT", "production") != "development"
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=24 * 3600,
        path="/",
    )
    return {"status": "ok", "role": "admin"}


@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"status": "ok"}


@router.get("/auth/me", response_model=TokenInfo)
async def me(user: CurrentUser = Depends(get_current_user)):
    return TokenInfo(
        role=user.role,
        exp=user.token_payload.get("exp", 0),
        iat=user.token_payload.get("iat", 0),
    )
