"""Digest routes: submit, list, detail."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

_EXEC_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

from src.api import LOGS_DIR
from src.api.dependencies import CurrentUser, get_current_user, rate_limit, require_admin
from src.api.models import SubmitResponse
from src.api.services import submit_digest

router = APIRouter(dependencies=[Depends(rate_limit)])


# --- Response models ---

class DigestSummary(BaseModel):
    exec_id: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    articles_processed: int = 0
    # --- KB mutation stats (Phase E) ---
    batches_total: int | None = None
    themes_added: int = 0
    themes_updated: int = 0
    stocks_added: int = 0
    stocks_updated: int = 0
    events_added: int = 0
    core_mind_updated: bool = False
    total_kb_chars_written: int = 0
    duration_s: float | None = None


class DigestDetail(BaseModel):
    exec_id: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    articles_processed: int = 0
    batches_total: int | None = None
    batches_complete: int = 0
    kb_mutations: list[dict] = []
    # --- KB mutation stats (Phase E) ---
    themes_added: int = 0
    themes_updated: int = 0
    stocks_added: int = 0
    stocks_updated: int = 0
    events_added: int = 0
    core_mind_updated: bool = False
    total_kb_chars_written: int = 0
    duration_s: float | None = None


# --- Endpoints ---

@router.post("/digest", response_model=SubmitResponse)
async def submit(user: CurrentUser = Depends(require_admin)):
    exec_id = await submit_digest(batch_size=25)
    return SubmitResponse(exec_id=exec_id)


@router.get("/digest", response_model=list[DigestSummary])
async def list_digests(
    limit: int = 20,
    user: CurrentUser = Depends(get_current_user),
):
    results = []
    if not LOGS_DIR.exists():
        return results

    dirs = sorted(
        (d for d in LOGS_DIR.iterdir() if d.is_dir()),
        key=lambda d: d.name,
        reverse=True,
    )

    for exec_dir in dirs:
        if not _is_digest(exec_dir):
            continue
        info = _read_exec_info(exec_dir)
        if info is None:
            continue
        kb_stats = _compute_kb_stats(exec_dir)
        results.append(
            DigestSummary(
                exec_id=exec_dir.name,
                status=_derive_status(exec_dir.name, info),
                started_at=info.get("start_time"),
                completed_at=info.get("end_time"),
                articles_processed=_count_articles(exec_dir),
                **kb_stats,
            )
        )
        if len(results) >= limit:
            break

    return results


@router.get("/digest/{exec_id}", response_model=DigestDetail)
async def get_digest(exec_id: str, user: CurrentUser = Depends(get_current_user)):
    if not _EXEC_ID_RE.match(exec_id):
        raise HTTPException(status_code=400, detail="Invalid exec_id format")
    exec_dir = LOGS_DIR / exec_id
    if not exec_dir.exists():
        raise HTTPException(status_code=404, detail="Execution not found")

    info = _read_exec_info(exec_dir) or {}
    events = _read_digest_events(exec_dir)
    batch_starts = [e for e in events if e.get("event") == "digest.batch_start"]
    batch_completes = [e for e in events if e.get("event") == "digest.batch_complete"]
    kb_events = [e for e in events if e.get("event", "").startswith("kb.")]

    kb_stats = _compute_kb_stats(exec_dir)
    # Remove batches_total from kb_stats — DigestDetail computes it from batch_starts
    kb_stats.pop("batches_total", None)

    return DigestDetail(
        exec_id=exec_id,
        status=_derive_status(exec_id, info),
        started_at=info.get("start_time"),
        completed_at=info.get("end_time"),
        articles_processed=_count_articles(exec_dir),
        batches_total=len(batch_starts) if batch_starts else None,
        batches_complete=len(batch_completes),
        kb_mutations=[
            {
                "type": _kb_event_type(e.get("event", "")),
                "path": e.get("data", {}).get("path", ""),
            }
            for e in kb_events
        ],
        **kb_stats,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_kb_stats(exec_dir: Path) -> dict:
    """Scan events.jsonl for KB mutation statistics."""
    events_file = exec_dir / "events.jsonl"
    if not events_file.exists():
        return {}

    stats: dict = {
        "themes_added": 0, "themes_updated": 0,
        "stocks_added": 0, "stocks_updated": 0,
        "events_added": 0, "core_mind_updated": False,
        "total_kb_chars_written": 0, "duration_s": None,
        "batches_total": None,
    }

    try:
        lines = events_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}

    for line in lines:
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = ev.get("event", "")
        data = ev.get("data", {})

        if event_type == "kb.write":
            section = data.get("section", "")
            is_new = data.get("is_new", False)
            size = data.get("size", 0)
            if section == "themes":
                if is_new:
                    stats["themes_added"] += 1
                else:
                    stats["themes_updated"] += 1
            elif section in ("stocks", "stock_theses"):
                if is_new:
                    stats["stocks_added"] += 1
                else:
                    stats["stocks_updated"] += 1
            elif section == "events":
                stats["events_added"] += 1
            stats["total_kb_chars_written"] += size

        elif event_type == "kb.edit":
            section = data.get("section", "")
            delta = data.get("new_len", 0) - data.get("old_len", 0)
            if section == "themes":
                stats["themes_updated"] += 1
            elif section in ("stocks", "stock_theses"):
                stats["stocks_updated"] += 1
            if delta > 0:
                stats["total_kb_chars_written"] += delta

        elif event_type == "kb.core_mind_updated":
            stats["core_mind_updated"] = True
            stats["total_kb_chars_written"] += data.get("size", 0)

        elif event_type == "digest.session_end":
            stats["duration_s"] = data.get("elapsed_s")
            stats["batches_total"] = data.get("batches")

    return stats


def _is_digest(exec_dir: Path) -> bool:
    return (exec_dir / "agents" / "core_digest.json").exists()


def _read_exec_info(exec_dir: Path) -> dict | None:
    info_path = exec_dir / "execution_info.json"
    if not info_path.exists():
        return None
    try:
        return json.loads(info_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _derive_status(exec_id: str, info: dict) -> str:
    from src.api.services import get_execution_status as mem_status

    # 1. Check in-memory status (API-triggered tasks)
    mem = mem_status(exec_id)
    if mem == "running":
        return "running"

    # 2. Finished tasks have end_time set
    if info.get("end_time"):
        return "complete" if info.get("success", True) else "failed"

    # 3. CLI-triggered tasks (retrain, --digest): no in-memory record,
    #    no end_time yet. Check if events.jsonl was recently modified
    #    (within 5 minutes) — indicates active writing.
    events_path = LOGS_DIR / exec_id / "events.jsonl"
    if events_path.exists():
        age = time.time() - events_path.stat().st_mtime
        if age < 300:  # 5 minutes
            return "running"

    return "unknown"


def _count_articles(exec_dir: Path) -> int:
    """Count processed articles from events."""
    events = _read_digest_events(exec_dir)
    # Check session_end first (most accurate total)
    for e in events:
        if e.get("event") == "digest.session_end":
            return e.get("data", {}).get("items_processed", 0)
    # Fallback: sum item_count from batch_start events
    total = 0
    for e in events:
        if e.get("event") == "digest.batch_start":
            total += e.get("data", {}).get("item_count", 0)
    return total


def _read_digest_events(exec_dir: Path) -> list[dict]:
    events_path = exec_dir / "events.jsonl"
    if not events_path.exists():
        return []
    events = []
    for line in events_path.read_text().splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


def _kb_event_type(event_name: str) -> str:
    if "write" in event_name or "create" in event_name:
        return "create"
    if "edit" in event_name or "update" in event_name:
        return "update"
    if "archive" in event_name or "delete" in event_name:
        return "delete"
    return "update"
