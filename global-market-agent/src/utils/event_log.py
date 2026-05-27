"""Unified pipeline event log — append-only JSONL for dashboard observability.

All pipeline stages (source refresh, inbox, filter, digest, KB mutations,
analysis) write events here. Each event is one JSON line in
``data/meta/pipeline_events.jsonl``.

Usage::

    from src.utils.event_log import log_event, new_session_id

    sid = new_session_id("refresh")
    log_event("source.refresh_start", stage="source", sid=sid, sources=["wechat", "macro"])
    log_event("source.fetch_complete", stage="source", sid=sid, source="wechat_ExampleAnalyst", new_count=3)
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent  # global-market-agent/
_LOG_PATH = _PROJECT_DIR / "data" / "meta" / "pipeline_events.jsonl"


def _iso_now() -> str:
    """ISO 8601 timestamp with millisecond precision (``2026-05-19T10:24:14.123Z``)."""
    t = time.time()
    ms = int((t % 1) * 1000)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{ms:03d}Z"


def log_event(event: str, *, stage: str = "", sid: str = "", **data) -> None:
    """Append one event to the pipeline event log.

    Args:
        event: Dot-notation event type (e.g. "source.refresh_start").
        stage: Pipeline stage (source/inbox/filter/digest/kb/analysis).
        sid: Session ID linking related events (from :func:`new_session_id`).
        **data: Arbitrary event-specific payload fields.
    """
    entry: dict = {
        "ts": _iso_now(),
        "event": event,
    }
    if stage:
        entry["stage"] = stage
    if sid:
        entry["sid"] = sid
    if data:
        entry["data"] = data

    line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"

    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        # Logging must never crash the pipeline
        logger.debug("Failed to write event: %s", event, exc_info=True)

    execution_id = data.get("execution_id") if data else None
    if execution_id:
        try:
            per_exec_path = _PROJECT_DIR / "logs" / execution_id / "events.jsonl"
            per_exec_path.parent.mkdir(parents=True, exist_ok=True)
            with open(per_exec_path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            logger.debug("Failed to write per-exec event: %s (exec=%s)", event, execution_id, exc_info=True)


def new_session_id(prefix: str = "") -> str:
    """Generate a unique session ID for grouping related events.

    Format: ``{prefix}-{YYYYMMDD-HHMMSS}-{6hex}`` or ``{YYYYMMDD-HHMMSS}-{6hex}``.
    """
    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    short = uuid.uuid4().hex[:6]
    return f"{prefix}-{ts}-{short}" if prefix else f"{ts}-{short}"


def read_events(
    *,
    last_n: int = 0,
    stage: str = "",
    event_prefix: str = "",
    sid: str = "",
) -> list[dict]:
    """Read events from the log with optional filters.

    Intended for dashboard queries. Returns newest-first when *last_n* is set.

    Args:
        last_n: Return only the last N events (0 = all).
        stage: Filter by stage (e.g. "digest").
        event_prefix: Filter by event prefix (e.g. "kb." matches kb.write, kb.edit).
        sid: Filter by session ID.
    """
    if not _LOG_PATH.is_file():
        return []

    events = []
    with open(_LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if stage and entry.get("stage") != stage:
                continue
            if event_prefix and not entry.get("event", "").startswith(event_prefix):
                continue
            if sid and entry.get("sid") != sid:
                continue
            events.append(entry)

    if last_n:
        events = events[-last_n:]
    return events
