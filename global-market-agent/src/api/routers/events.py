"""SSE streaming endpoint — replay + tail per-execution event logs."""

from __future__ import annotations

import asyncio
import json
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from src.api import LOGS_DIR
from src.api.dependencies import CurrentUser, get_current_user, rate_limit

router = APIRouter(dependencies=[Depends(rate_limit)])

# Events hidden from visitors (may contain API internals)
_VISITOR_HIDDEN_PREFIXES: tuple[str, ...] = ()

# Max SSE stream duration (30 minutes) — prevents leaked connections from crashed executions
_MAX_STREAM_SECONDS = 30 * 60

# After analysis.end, wait this long for audit.start before closing the stream
_AUDIT_GRACE_SECONDS = 15

_EXEC_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


@router.get("/events/{exec_id}")
async def stream_events(
    exec_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    """SSE stream: replay existing events then tail for new ones.

    The stream stays open through the audit phase (if auto-audit runs).
    Terminal conditions:
    - audit.complete or digest.session_end → definitive end
    - analysis.end with no audit.start after grace period → no audit coming
    """
    if not _EXEC_ID_RE.match(exec_id):
        raise HTTPException(status_code=400, detail="Invalid exec_id format")

    event_log_path = LOGS_DIR / exec_id / "events.jsonl"

    async def event_generator():
        position = 0
        start_time = time.monotonic()
        analysis_ended_at: float | None = None
        audit_started = False

        # Phase 1: Replay existing events
        if event_log_path.exists():
            for line in event_log_path.read_text().splitlines():
                if _should_send(line, user.role):
                    yield {"event": "pipeline", "data": line.strip()}
                # Track lifecycle markers
                if '"analysis.end"' in line:
                    analysis_ended_at = time.monotonic()
                if '"audit.start"' in line:
                    audit_started = True
                position += 1

        # Early exit: execution complete and all phases done
        if _execution_is_complete(exec_id) and event_log_path.exists():
            all_lines = event_log_path.read_text().splitlines()
            if _is_fully_complete(all_lines):
                yield {"event": "complete", "data": "{}"}
                return
            # analysis.end exists but no audit.start — no audit was triggered
            if _has_analysis_end_no_audit(all_lines):
                yield {"event": "complete", "data": "{}"}
                return

        # Phase 2: Tail for new events (poll every 500ms)
        while not await request.is_disconnected():
            # Timeout guard
            if time.monotonic() - start_time > _MAX_STREAM_SECONDS:
                yield {"event": "timeout", "data": "{}"}
                return

            if event_log_path.exists():
                lines = event_log_path.read_text().splitlines()
                for line in lines[position:]:
                    if _should_send(line, user.role):
                        yield {"event": "pipeline", "data": line.strip()}
                    # Track lifecycle markers
                    if '"analysis.end"' in line:
                        analysis_ended_at = time.monotonic()
                    if '"audit.start"' in line:
                        audit_started = True
                    position += 1

                # Hard terminal: audit.complete or digest.session_end
                if _is_fully_complete(lines):
                    yield {"event": "complete", "data": "{}"}
                    return

            # Grace period: analysis ended, wait for audit to start
            if analysis_ended_at and not audit_started:
                if time.monotonic() - analysis_ended_at > _AUDIT_GRACE_SECONDS:
                    yield {"event": "complete", "data": "{}"}
                    return

            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())


def _should_send(line: str, role: str) -> bool:
    """Filter events based on user role."""
    if role == "admin":
        return True
    try:
        evt = json.loads(line)
        event_name = evt.get("event", "")
        return not any(event_name.startswith(p) for p in _VISITOR_HIDDEN_PREFIXES)
    except (json.JSONDecodeError, KeyError):
        return True


def _execution_is_complete(exec_id: str) -> bool:
    """Check if this execution has already finished (has end_time)."""
    info_path = LOGS_DIR / exec_id / "execution_info.json"
    if not info_path.exists():
        return False
    try:
        data = json.loads(info_path.read_text())
        return bool(data.get("end_time"))
    except (json.JSONDecodeError, OSError):
        return False


def _is_fully_complete(lines: list[str]) -> bool:
    """Check if all phases (analysis + audit, or digest) are definitively done."""
    for line in lines:
        if '"audit.complete"' in line or '"digest.session_end"' in line:
            return True
    return False


def _has_analysis_end_no_audit(lines: list[str]) -> bool:
    """Check if analysis ended but no audit was triggered."""
    has_analysis_end = False
    has_audit_start = False
    for line in lines:
        if '"analysis.end"' in line:
            has_analysis_end = True
        if '"audit.start"' in line:
            has_audit_start = True
    return has_analysis_end and not has_audit_start
