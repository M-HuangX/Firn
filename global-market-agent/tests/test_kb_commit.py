"""Tests for kb_commit.py — git commit helper."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.knowledge_base.kb_commit import commit_kb_changes, get_recent_digest_log


class TestCommitKBChanges:
    def test_commit_with_changes(self):
        with patch("src.knowledge_base.kb_commit.subprocess.run") as mock_run:
            # First call: git status (has changes)
            # Second call: git add
            # Third call: git commit
            # Fourth call: git rev-parse
            mock_run.side_effect = [
                MagicMock(stdout=" M firn/foo.md\n", returncode=0),
                MagicMock(stdout="", returncode=0),
                MagicMock(stdout="", returncode=0),
                MagicMock(stdout="abc1234\n", returncode=0),
            ]
            result = commit_kb_changes("[digest] 5 items in 1 batch")
            assert result == "abc1234"
            assert mock_run.call_count == 4

    def test_no_changes_returns_none(self):
        with patch("src.knowledge_base.kb_commit.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            result = commit_kb_changes("test message")
            assert result is None

    def test_git_error_returns_none(self):
        with patch("src.knowledge_base.kb_commit.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "git")
            result = commit_kb_changes("test message")
            assert result is None


class TestGetRecentDigestLog:
    def test_get_recent_digest_log(self, tmp_path):
        sessions_file = tmp_path / "meta" / "digest_sessions.md"
        sessions_file.parent.mkdir(parents=True, exist_ok=True)
        content = "## Session 3\nContent\n\n---\n\n## Session 2\nContent\n\n---\n\n## Session 1\nContent"
        sessions_file.write_text(content, encoding="utf-8")

        with patch("src.knowledge_base.kb_commit._DATA_DIR", tmp_path):
            result = get_recent_digest_log(n=2)
        assert "Session 3" in result
        assert "Session 2" in result
        assert "Session 1" not in result

    def test_get_recent_digest_log_no_file(self, tmp_path):
        with patch("src.knowledge_base.kb_commit._DATA_DIR", tmp_path):
            result = get_recent_digest_log()
        assert result == "(no digest history)"
