"""Tests for src.api.services — API service layer.

Tests the ExecutionQueue-based task submission and status queries.
"""

import asyncio
import pytest
from unittest.mock import patch

from src.api.services import (
    ExecutionQueue,
    get_execution_status,
    get_active_executions,
    _active_tasks,
)


@pytest.fixture(autouse=True)
def clean_state():
    """Ensure clean state between tests."""
    _active_tasks.clear()
    yield
    _active_tasks.clear()


# ---------------------------------------------------------------------------
# Status queries (these don't need the queue running)
# ---------------------------------------------------------------------------

class TestGetExecutionStatus:
    def test_unknown_for_nonexistent(self):
        assert get_execution_status("nonexistent") == "unknown"

    @pytest.mark.asyncio
    async def test_running_for_active_task(self):
        event = asyncio.Event()
        task = asyncio.create_task(event.wait())
        _active_tasks["test-123"] = task
        assert get_execution_status("test-123") == "running"
        event.set()
        await task

    @pytest.mark.asyncio
    async def test_completed_for_done_task(self):
        task = asyncio.create_task(asyncio.sleep(0))
        _active_tasks["test-456"] = task
        await task
        assert get_execution_status("test-456") == "completed"


class TestGetActiveExecutions:
    @pytest.mark.asyncio
    async def test_lists_running_tasks(self):
        event = asyncio.Event()
        task1 = asyncio.create_task(event.wait())
        task2 = asyncio.create_task(event.wait())
        _active_tasks["exec-1"] = task1
        _active_tasks["exec-2"] = task2

        active = get_active_executions()
        assert "exec-1" in active
        assert "exec-2" in active

        event.set()
        await task1
        await task2

    @pytest.mark.asyncio
    async def test_excludes_done_tasks(self):
        done_task = asyncio.create_task(asyncio.sleep(0))
        await done_task
        _active_tasks["done-1"] = done_task

        event = asyncio.Event()
        running_task = asyncio.create_task(event.wait())
        _active_tasks["running-1"] = running_task

        active = get_active_executions()
        assert "running-1" in active
        assert "done-1" not in active

        event.set()
        await running_task


# ---------------------------------------------------------------------------
# ExecutionQueue unit tests (fresh queue per test avoids event loop issues)
# ---------------------------------------------------------------------------

class TestExecutionQueue:
    @pytest.mark.asyncio
    async def test_queue_executes_submitted_task(self):
        q = ExecutionQueue()
        q.start()
        result_holder = []

        async def work():
            result_holder.append("done")
            return 42

        future = await q.submit(work(), exec_id="t1", task_type="test")
        result = await asyncio.wait_for(future, timeout=2.0)
        assert result == 42
        assert result_holder == ["done"]
        await q.stop()

    @pytest.mark.asyncio
    async def test_queue_serializes_tasks(self):
        """Tasks run one at a time (D30.1 serial execution)."""
        q = ExecutionQueue()
        q.start()
        execution_order = []

        async def tracked(label):
            execution_order.append(f"start-{label}")
            await asyncio.sleep(0.02)
            execution_order.append(f"end-{label}")

        f1 = await q.submit(tracked("A"), exec_id="t1", task_type="test")
        f2 = await q.submit(tracked("B"), exec_id="t2", task_type="test")
        await asyncio.wait_for(asyncio.gather(f1, f2), timeout=2.0)

        assert execution_order == ["start-A", "end-A", "start-B", "end-B"]
        await q.stop()

    @pytest.mark.asyncio
    async def test_queue_status(self):
        q = ExecutionQueue()
        status = q.get_queue_status()
        assert status["running"] is None
        assert status["pending"] == []
        assert status["pending_count"] == 0
