"""Config routes (admin only): watchlist, sources, refresh, market snapshot."""

from __future__ import annotations

import time
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException

from src.api import PROJECT_ROOT
from src.api.dependencies import get_current_user, get_kb, rate_limit, require_admin
from src.api.models import SubmitResponse
from src.api.services import submit_refresh
from src.knowledge_base.kb_api import KnowledgeBase

router = APIRouter(dependencies=[Depends(rate_limit)])

_WATCHLIST_PATH = PROJECT_ROOT / "config" / "digest_watchlist.yaml"


# --- Watchlist ---


@router.get("/watchlist")
async def get_watchlist(_: None = Depends(require_admin)):
    if not _WATCHLIST_PATH.exists():
        return {"categories": {}}
    content = yaml.safe_load(_WATCHLIST_PATH.read_text()) or {}
    # The YAML has a top-level "categories" key — unwrap it
    if "categories" in content and isinstance(content["categories"], dict):
        return {"categories": content["categories"]}
    return {"categories": content}


@router.put("/watchlist")
async def update_watchlist(body: dict, _: None = Depends(require_admin)):
    categories = body.get("categories")
    if categories is None:
        raise HTTPException(status_code=422, detail="Missing 'categories' field")
    _WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _WATCHLIST_PATH.write_text(yaml.dump(categories, allow_unicode=True, sort_keys=False))
    return {"status": "ok"}


# --- Sources ---


@router.get("/sources")
async def get_sources(
    kb: KnowledgeBase = Depends(get_kb),
    _: None = Depends(require_admin),
):
    last_updated = kb.get_last_updated()
    registry = kb.read_source_registry()
    # Registry has a top-level "sources" key wrapping the actual source entries
    source_entries = registry.get("sources", registry) if isinstance(registry, dict) else {}
    sources = []
    for name, info in source_entries.items():
        if not isinstance(info, dict):
            continue
        lu = last_updated.get(name, {})
        sources.append({
            "name": name,
            "tier": info.get("human_tier") or info.get("tier"),
            "bias": info.get("bias"),
            "last_updated": lu.get("last_checked") or lu.get("date") if isinstance(lu, dict) else lu,
            "new_count": lu.get("new_count", 0) if isinstance(lu, dict) else 0,
        })
    return {"sources": sources}


@router.post("/sources/refresh", response_model=SubmitResponse)
async def refresh_sources(_: None = Depends(require_admin)):
    exec_id = await submit_refresh()
    return SubmitResponse(exec_id=exec_id)


# --- Market Snapshot (visitor-accessible) ---

_snapshot_cache: dict = {"data": None, "ts": 0.0}
_CACHE_TTL = 300  # 5 minutes


@router.get("/market-snapshot")
async def market_snapshot(user=Depends(get_current_user)):
    import asyncio

    now = time.time()
    if _snapshot_cache["data"] is not None and (now - _snapshot_cache["ts"]) < _CACHE_TTL:
        return _snapshot_cache["data"]

    from src.sources.market.snapshot import fetch_snapshot, load_watchlist

    watchlist = load_watchlist()
    all_tickers = []
    for tickers in watchlist.values():
        all_tickers.extend(tickers)
    # De-duplicate
    all_tickers = list(dict.fromkeys(all_tickers))

    if not all_tickers:
        return {"tickers": {}, "categories": watchlist}

    # fetch_snapshot() is synchronous (yfinance HTTP) — run in thread to avoid blocking
    data = await asyncio.to_thread(fetch_snapshot, all_tickers)
    result = {"tickers": data, "categories": watchlist}
    _snapshot_cache["data"] = result
    _snapshot_cache["ts"] = now
    return result
