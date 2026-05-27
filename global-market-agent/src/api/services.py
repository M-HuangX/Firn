"""API service layer — orchestrates pipeline executions for the web API.

Provides async task submission (returns exec_id immediately) and status queries.
Uses a priority-based serial execution queue (D30.1): only one pipeline runs at
a time, and admin tasks (priority=0) jump ahead of visitor tasks (priority=1).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from src.utils.execution_logger import ExecutionLogger

logger = logging.getLogger(__name__)

# In-memory task registry: exec_id → asyncio.Task
_active_tasks: dict[str, asyncio.Task] = {}


# ---------------------------------------------------------------------------
# Priority Queue
# ---------------------------------------------------------------------------

@dataclass(order=True)
class _QueueEntry:
    """A pending or running task in the execution queue."""

    # Fields used for sorting (priority first, then submission time)
    priority: int = field(compare=True)
    submitted_at: float = field(compare=True)
    # Non-comparison fields
    exec_id: str = field(compare=False)
    task_type: str = field(compare=False)  # "analysis", "digest", "audit", "refresh"
    coro: Any = field(compare=False, repr=False)  # the coroutine to run
    future: asyncio.Future = field(compare=False, repr=False)


class ExecutionQueue:
    """Priority-based serial execution queue.

    Tasks are executed one at a time, strictly serially.
    Admin tasks (priority=0) jump ahead of visitor tasks (priority=1) in the
    pending queue. Running tasks cannot be preempted.
    """

    def __init__(self) -> None:
        self._pending: list[_QueueEntry] = []  # sorted by (priority, submitted_at)
        self._running: _QueueEntry | None = None
        self._lock = asyncio.Lock()  # protects queue state
        self._worker_event = asyncio.Event()  # signals new work available
        self._worker_task: asyncio.Task | None = None

    def start(self) -> None:
        """Start the background worker. Call at app startup."""
        self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        """Stop the background worker. Call at app shutdown."""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def submit(
        self,
        coro: Any,
        *,
        exec_id: str,
        task_type: str,
        priority: int = 1,
    ) -> asyncio.Future:
        """Submit a coroutine for execution. Returns a Future for the result."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        entry = _QueueEntry(
            priority=priority,
            submitted_at=time.time(),
            exec_id=exec_id,
            task_type=task_type,
            coro=coro,
            future=future,
        )
        async with self._lock:
            self._pending.append(entry)
            self._pending.sort()
        self._worker_event.set()
        return future

    async def _worker(self) -> None:
        """Background loop: pick highest-priority pending task, run it, repeat."""
        while True:
            await self._worker_event.wait()

            # Pick next task
            async with self._lock:
                if not self._pending:
                    self._worker_event.clear()
                    continue
                entry = self._pending.pop(0)
                self._running = entry

            # Execute the coroutine
            try:
                result = await entry.coro
                if not entry.future.done():
                    entry.future.set_result(result)
            except Exception as exc:
                if not entry.future.done():
                    entry.future.set_exception(exc)
            finally:
                async with self._lock:
                    self._running = None
                    if not self._pending:
                        self._worker_event.clear()

    def get_queue_status(self) -> dict:
        """Return current queue state for API consumers."""
        running = None
        if self._running:
            running = {
                "exec_id": self._running.exec_id,
                "task_type": self._running.task_type,
                "priority": self._running.priority,
            }
        pending = [
            {
                "exec_id": e.exec_id,
                "task_type": e.task_type,
                "priority": e.priority,
            }
            for e in self._pending
        ]
        return {
            "running": running,
            "pending": pending,
            "pending_count": len(pending),
        }


# Module-level queue instance
_queue = ExecutionQueue()

# Backward-compatible alias — old code/tests may reference this.
# The queue now handles serialization; this lock is unused but kept for import compat.
_execution_lock = asyncio.Lock()


def start_execution_queue() -> None:
    """Start the execution queue worker. Call from app lifespan startup."""
    _queue.start()


async def stop_execution_queue() -> None:
    """Stop the execution queue worker. Call from app lifespan shutdown."""
    await _queue.stop()


def get_queue_status() -> dict:
    """Return current queue state for API consumers."""
    return _queue.get_queue_status()


# ---------------------------------------------------------------------------
# Submit functions
# ---------------------------------------------------------------------------

async def submit_analysis(ticker: str, query: str | None = None, *, priority: int = 1) -> str:
    """Submit an analysis for background execution. Returns exec_id immediately.

    The caller can use the exec_id to:
    - Establish SSE connection to tail events from logs/{exec_id}/events.jsonl
    - Query status via get_execution_status(exec_id)
    """
    el = ExecutionLogger()
    exec_id = el.execution_id
    # Save ticker in execution_info for later retrieval
    el.save_extra_info({"ticker": ticker})

    async def _run() -> dict:
        return await _run_analysis_background(ticker, query, el)

    future = await _queue.submit(_run(), exec_id=exec_id, task_type="analysis", priority=priority)
    task = asyncio.ensure_future(future)
    _active_tasks[exec_id] = task
    task.add_done_callback(lambda t: _active_tasks.pop(exec_id, None))
    return exec_id


async def submit_digest(batch_size: int = 25, *, priority: int = 1) -> str:
    """Submit a digest run for background execution. Returns exec_id immediately."""
    el = ExecutionLogger()
    exec_id = el.execution_id

    async def _run() -> Any:
        return await _run_digest_background(batch_size, el)

    future = await _queue.submit(_run(), exec_id=exec_id, task_type="digest", priority=priority)
    task = asyncio.ensure_future(future)
    _active_tasks[exec_id] = task
    task.add_done_callback(lambda t: _active_tasks.pop(exec_id, None))
    return exec_id


async def submit_audit(target_exec_id: str, mode: str | None = None, *, priority: int = 1) -> str:
    """Submit an audit for background execution. Returns exec_id immediately."""
    el = ExecutionLogger()
    exec_id = el.execution_id

    async def _run() -> Any:
        return await _run_audit_background(target_exec_id, mode, el)

    future = await _queue.submit(_run(), exec_id=exec_id, task_type="audit", priority=priority)
    task = asyncio.ensure_future(future)
    _active_tasks[exec_id] = task
    task.add_done_callback(lambda t: _active_tasks.pop(exec_id, None))
    return exec_id


async def submit_refresh(*, priority: int = 1) -> str:
    """Submit a source refresh for background execution. Returns exec_id immediately.

    Note: refresh_sources() is synchronous, so we wrap it with asyncio.to_thread.
    """
    el = ExecutionLogger()
    exec_id = el.execution_id

    async def _run() -> Any:
        return await _run_refresh_background(el)

    future = await _queue.submit(_run(), exec_id=exec_id, task_type="refresh", priority=priority)
    task = asyncio.ensure_future(future)
    _active_tasks[exec_id] = task
    task.add_done_callback(lambda t: _active_tasks.pop(exec_id, None))
    return exec_id


# ---------------------------------------------------------------------------
# Status queries (backward-compatible)
# ---------------------------------------------------------------------------

def get_execution_status(exec_id: str) -> str:
    """Check if an execution is still running.

    Returns: "running", "completed", or "unknown"
    """
    task = _active_tasks.get(exec_id)
    if task is None:
        return "unknown"
    if task.done():
        return "completed"
    return "running"


def get_active_executions() -> list[str]:
    """List all currently running execution IDs."""
    return [eid for eid, task in _active_tasks.items() if not task.done()]


# ---------------------------------------------------------------------------
# Background runners (run pipeline, handle errors — no lock needed, queue serializes)
# ---------------------------------------------------------------------------

async def _run_analysis_background(ticker: str, query: str | None, el: ExecutionLogger) -> dict:
    """Run analysis in background with error handling. Auto-triggers audit on success."""
    try:
        from src.main import run_analysis
        result = await run_analysis(ticker, query, execution_logger=el)
        el.finalize(success=True)
        # Auto-trigger audit after successful analysis
        analysis_exec_id = el.execution_id
        try:
            await submit_audit(analysis_exec_id)
            logger.info("Auto-triggered audit for %s", analysis_exec_id)
        except Exception as audit_err:
            logger.warning("Auto-audit submission failed for %s: %s", analysis_exec_id, audit_err)
        return result
    except Exception as e:
        logger.exception("Background analysis failed: %s", e)
        el.finalize(success=False, error=str(e))
        raise


async def _run_digest_background(batch_size: int, el: ExecutionLogger) -> Any:
    """Run digest in background with error handling."""
    try:
        from src.knowledge_base.digest_pipeline import run_digest
        result = await run_digest(batch_size=batch_size, execution_logger=el)
        el.finalize(success=True)
        return result
    except Exception as e:
        logger.exception("Background digest failed: %s", e)
        el.finalize(success=False, error=str(e))
        raise


async def _run_audit_background(target_exec_id: str, mode: str | None, el: ExecutionLogger) -> Any:
    """Run audit in background with error handling."""
    try:
        from src.audit.pipeline import run_audit
        result = await run_audit(target_exec_id, mode=mode, execution_logger=el)
        el.finalize(success=True)
        return result
    except Exception as e:
        logger.exception("Background audit failed: %s", e)
        el.finalize(success=False, error=str(e))
        raise


async def _run_refresh_background(el: ExecutionLogger) -> Any:
    """Run source refresh in background. Uses to_thread since refresh is sync."""
    try:
        from src.sources.refresh_pipeline import refresh_sources
        result = await asyncio.to_thread(refresh_sources)
        el.finalize(success=True)
        return result
    except Exception as e:
        logger.exception("Background refresh failed: %s", e)
        el.finalize(success=False, error=str(e))
        raise
