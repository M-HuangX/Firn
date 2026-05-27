"""Tests for src.utils.event_log — unified pipeline event log."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from src.utils.event_log import log_event, new_session_id, read_events, _LOG_PATH


@pytest.fixture
def tmp_log(tmp_path, monkeypatch):
    """Redirect event log to a temp file."""
    log_path = tmp_path / "pipeline_events.jsonl"
    monkeypatch.setattr("src.utils.event_log._LOG_PATH", log_path)
    return log_path


class TestLogEvent:
    def test_creates_file_and_writes_json(self, tmp_log):
        log_event("test.event", stage="test", foo="bar")
        assert tmp_log.is_file()
        lines = tmp_log.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event"] == "test.event"
        assert entry["stage"] == "test"
        assert entry["data"]["foo"] == "bar"
        assert "ts" in entry

    def test_appends_multiple_events(self, tmp_log):
        log_event("a.first", stage="a")
        log_event("b.second", stage="b")
        lines = tmp_log.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_session_id_included(self, tmp_log):
        log_event("test.sid", sid="my-session-123")
        entry = json.loads(tmp_log.read_text().strip())
        assert entry["sid"] == "my-session-123"

    def test_omits_empty_optional_fields(self, tmp_log):
        log_event("test.minimal")
        entry = json.loads(tmp_log.read_text().strip())
        assert "stage" not in entry
        assert "sid" not in entry
        assert "data" not in entry

    def test_handles_non_serializable_data(self, tmp_log):
        """default=str should handle Path objects etc."""
        log_event("test.path", stage="test", path=Path("/some/path"))
        entry = json.loads(tmp_log.read_text().strip())
        assert "/some/path" in entry["data"]["path"]

    def test_never_raises_on_write_failure(self, tmp_log, monkeypatch):
        """Logging errors must not crash the pipeline."""
        monkeypatch.setattr("src.utils.event_log._LOG_PATH", Path("/nonexistent/dir/log.jsonl"))
        # Should not raise
        log_event("test.fail", stage="test")

    def test_unicode_support(self, tmp_log):
        log_event("test.unicode", stage="test", title="Macro Analysis: Copper Inflection")
        entry = json.loads(tmp_log.read_text().strip())
        assert "Copper" in entry["data"]["title"]


class TestNewSessionId:
    def test_with_prefix(self):
        sid = new_session_id("refresh")
        assert sid.startswith("refresh-")
        parts = sid.split("-")
        assert len(parts) >= 3  # prefix-YYYYMMDD-HHMMSS-hex

    def test_without_prefix(self):
        sid = new_session_id()
        # Should be YYYYMMDD-HHMMSS-hex
        assert len(sid) > 10

    def test_unique(self):
        ids = {new_session_id("test") for _ in range(10)}
        assert len(ids) == 10  # All unique


class TestReadEvents:
    def test_empty_log(self, tmp_log):
        assert read_events() == []

    def test_reads_all(self, tmp_log):
        log_event("a.one", stage="a")
        log_event("b.two", stage="b")
        events = read_events()
        assert len(events) == 2

    def test_filter_by_stage(self, tmp_log):
        log_event("a.one", stage="source")
        log_event("b.two", stage="digest")
        log_event("c.three", stage="source")
        events = read_events(stage="source")
        assert len(events) == 2

    def test_filter_by_event_prefix(self, tmp_log):
        log_event("kb.write", stage="kb")
        log_event("kb.edit", stage="kb")
        log_event("analysis.start", stage="analysis")
        events = read_events(event_prefix="kb.")
        assert len(events) == 2

    def test_filter_by_sid(self, tmp_log):
        log_event("a.one", sid="session-1")
        log_event("b.two", sid="session-2")
        log_event("c.three", sid="session-1")
        events = read_events(sid="session-1")
        assert len(events) == 2

    def test_last_n(self, tmp_log):
        for i in range(10):
            log_event(f"test.{i}", stage="test", num=i)
        events = read_events(last_n=3)
        assert len(events) == 3
        assert events[0]["data"]["num"] == 7  # newest-last, so index 0 = 8th event

    def test_combined_filters(self, tmp_log):
        log_event("kb.write", stage="kb", sid="s1")
        log_event("kb.write", stage="kb", sid="s2")
        log_event("analysis.start", stage="analysis", sid="s1")
        events = read_events(stage="kb", sid="s1")
        assert len(events) == 1


@pytest.fixture
def tmp_project_dir(tmp_path, monkeypatch):
    """Redirect _PROJECT_DIR to a temp directory for per-exec path tests."""
    monkeypatch.setattr("src.utils.event_log._PROJECT_DIR", tmp_path)
    return tmp_path


class TestDualWrite:
    def test_dual_write_when_execution_id_present(self, tmp_log, tmp_project_dir):
        log_event("analysis.start", stage="analysis", execution_id="test_exec_123", ticker="AAPL")

        # Global file must have the event
        assert tmp_log.is_file()
        global_lines = tmp_log.read_text().strip().split("\n")
        assert len(global_lines) == 1
        global_entry = json.loads(global_lines[0])
        assert global_entry["event"] == "analysis.start"
        assert global_entry["data"]["execution_id"] == "test_exec_123"

        # Per-exec file must exist and contain the identical line
        per_exec_path = tmp_project_dir / "logs" / "test_exec_123" / "events.jsonl"
        assert per_exec_path.is_file()
        per_exec_lines = per_exec_path.read_text().strip().split("\n")
        assert len(per_exec_lines) == 1
        assert per_exec_lines[0] == global_lines[0]

    def test_no_per_exec_write_without_execution_id(self, tmp_log, tmp_project_dir):
        log_event("analysis.start", stage="analysis", ticker="AAPL")

        # Global file must have the event
        assert tmp_log.is_file()

        # No logs/ directory should be created
        logs_dir = tmp_project_dir / "logs"
        assert not logs_dir.exists()

    def test_dual_write_failure_does_not_crash(self, tmp_log, monkeypatch):
        # Point _PROJECT_DIR at a path that cannot be created (file in the way)
        monkeypatch.setattr("src.utils.event_log._PROJECT_DIR", Path("/nonexistent/unwritable"))

        # Must not raise, and global write must still succeed
        log_event("analysis.start", stage="analysis", execution_id="test_exec_456")
        assert tmp_log.is_file()
        entry = json.loads(tmp_log.read_text().strip())
        assert entry["event"] == "analysis.start"
