"""Tests for data freshness system (4.33).

Covers: _format_age helper, build_source_status, refresh pipeline wiring,
digest pipeline source status injection, CLI --status.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.knowledge_base.kb_api import KnowledgeBase, _format_age


# ---------------------------------------------------------------------------
# _format_age
# ---------------------------------------------------------------------------


class TestFormatAge:
    def _now(self):
        return datetime.now(timezone.utc)

    def test_just_now(self):
        now = self._now()
        ts = now.isoformat()
        assert _format_age(ts, now) == "just now"

    def test_minutes(self):
        now = self._now()
        ts = (now - timedelta(minutes=25)).isoformat()
        assert _format_age(ts, now) == "25m ago"

    def test_hours(self):
        now = self._now()
        ts = (now - timedelta(hours=4)).isoformat()
        assert _format_age(ts, now) == "4h ago"

    def test_days(self):
        now = self._now()
        ts = (now - timedelta(days=3)).isoformat()
        assert _format_age(ts, now) == "3d ago"

    def test_none_input(self):
        assert _format_age(None, self._now()) == "unknown"

    def test_invalid_timestamp(self):
        assert _format_age("not-a-date", self._now()) == "unknown"

    def test_naive_timestamp_treated_as_utc(self):
        now = datetime.now(timezone.utc)
        naive = (now - timedelta(hours=2)).replace(tzinfo=None).isoformat()
        assert _format_age(naive, now) == "2h ago"


# ---------------------------------------------------------------------------
# build_source_status
# ---------------------------------------------------------------------------


class TestBuildSourceStatus:
    @pytest.fixture
    def kb(self, tmp_path):
        firn_dir = tmp_path / "firn"
        firn_dir.mkdir()
        kb = KnowledgeBase(kb_root=firn_dir)
        (kb.data_root / "meta").mkdir(parents=True, exist_ok=True)
        return kb

    def test_empty(self, kb):
        assert "No source freshness data" in kb.build_source_status()

    def test_with_new_data(self, kb):
        kb.set_last_updated("wechat_test", new_count=3, summary="3 articles")
        result = kb.build_source_status()
        assert "Source Freshness:" in result
        assert "wechat_test" in result
        assert "3 new" in result
        assert "3 articles" in result

    def test_no_new_data_shows_last_new(self, kb):
        kb.set_last_updated("src_a", new_count=1, summary="1 new")
        kb.set_last_updated("src_a", new_count=0, summary="nothing")
        result = kb.build_source_status()
        assert "no new data" in result
        assert "last new" in result

    def test_never_had_new_data(self, kb):
        kb.set_last_updated("src_b", new_count=0, summary="empty")
        result = kb.build_source_status()
        assert "no data yet" in result

    def test_legacy_string_format(self, kb):
        path = kb.data_root / "meta" / "last_updated.json"
        path.write_text(json.dumps({"old_src": "2026-01-15T08:00:00Z"}))
        result = kb.build_source_status()
        assert "old_src" in result
        assert "2026-01-15" in result

    def test_multiple_sources_sorted(self, kb):
        kb.set_last_updated("zz_last", new_count=1, summary="1")
        kb.set_last_updated("aa_first", new_count=2, summary="2")
        result = kb.build_source_status()
        lines = result.strip().split("\n")
        # First data line should be aa_first (sorted)
        assert "aa_first" in lines[1]
        assert "zz_last" in lines[2]


# ---------------------------------------------------------------------------
# Refresh pipeline freshness recording
# ---------------------------------------------------------------------------


class TestRefreshPipelineFreshness:
    @pytest.fixture
    def kb(self, tmp_path):
        firn_dir = tmp_path / "firn"
        firn_dir.mkdir()
        kb = KnowledgeBase(kb_root=firn_dir)
        (kb.data_root / "meta").mkdir(parents=True, exist_ok=True)
        (firn_dir / "library" / "unread").mkdir(parents=True, exist_ok=True)
        return kb

    @patch("src.sources.refresh_pipeline.WechatSourceManager")
    @patch("src.sources.refresh_pipeline.KnowledgeBase")
    @patch("src.sources.refresh_pipeline.add_to_inbox")
    def test_records_freshness_on_refresh(self, mock_inbox, mock_kb_cls, mock_mgr_cls, kb):
        """refresh_sources() should call set_last_updated per account."""
        from src.sources.refresh_pipeline import refresh_sources

        # Setup mock manager
        mock_account = MagicMock()
        mock_account.name = "TestAccount"
        mock_account.effective_tier = 2
        mock_account.tags = ["macro"]

        mock_mgr = MagicMock()
        mock_mgr.accounts = [mock_account]
        mock_mgr.refresh_all.return_value = {"TestAccount": []}
        mock_mgr_cls.return_value = mock_mgr

        mock_kb_cls.return_value = kb

        result = refresh_sources()

        # Should have recorded freshness
        data = kb.get_last_updated()
        assert "wechat_TestAccount" in data
        entry = data["wechat_TestAccount"]
        assert entry["new_count"] == 0
        assert "no new" in entry["summary"]

    @patch("src.sources.refresh_pipeline.WechatSourceManager")
    @patch("src.sources.refresh_pipeline.KnowledgeBase")
    @patch("src.sources.refresh_pipeline.add_to_inbox")
    def test_records_new_count(self, mock_inbox, mock_kb_cls, mock_mgr_cls, kb):
        """When articles are found, new_count reflects actual count."""
        from src.sources.refresh_pipeline import refresh_sources

        mock_article = MagicMock()
        mock_article.account = "Acc"
        mock_article.title = "Title"
        mock_article.content = "Content"
        mock_article.summary = "Sum"
        mock_article.wechat_url = None
        mock_article.timestamp = 1700000000

        mock_account = MagicMock()
        mock_account.name = "Acc"
        mock_account.effective_tier = 2
        mock_account.tags = []

        mock_mgr = MagicMock()
        mock_mgr.accounts = [mock_account]
        mock_mgr.refresh_all.return_value = {"Acc": [mock_article]}
        mock_mgr.get_account.return_value = mock_account
        mock_mgr_cls.return_value = mock_mgr

        mock_kb_cls.return_value = kb

        result = refresh_sources()

        data = kb.get_last_updated()
        entry = data["wechat_Acc"]
        assert entry["new_count"] == 1
        assert "1 new" in entry["summary"]


# ---------------------------------------------------------------------------
# Digest pipeline source status injection
# ---------------------------------------------------------------------------


class TestDigestSourceStatusInjection:
    @pytest.fixture
    def kb(self, tmp_path):
        firn_dir = tmp_path / "firn"
        firn_dir.mkdir()
        kb = KnowledgeBase(kb_root=firn_dir)
        (kb.data_root / "meta").mkdir(parents=True, exist_ok=True)
        for d in [
            "library/unread", "library/read",
            "notebook/themes", "notebook/events",
            "notebook/sectors",
        ]:
            (firn_dir / d).mkdir(parents=True, exist_ok=True)
        return kb

    def test_batch_input_includes_source_status(self, kb):
        from src.knowledge_base.digest_pipeline import _build_batch_input
        from src.knowledge_base.perception import InboxItem

        kb.set_last_updated("wechat_test", new_count=2, summary="2 articles")

        item = InboxItem(
            slug="test-item",
            source="wechat_test",
            tier=2,
            content_type="analysis",
            ticker=None,
            title="Test",
            body="Body",
        )

        result = _build_batch_input([item], 1, 1, [], kb)
        assert "Source Freshness:" in result
        assert "wechat_test" in result

    def test_batch_input_no_status_when_empty(self, kb):
        from src.knowledge_base.digest_pipeline import _build_batch_input
        from src.knowledge_base.perception import InboxItem

        item = InboxItem(
            slug="test-item",
            source="test",
            tier=2,
            content_type="analysis",
            ticker=None,
            title="Test",
            body="Body",
        )

        result = _build_batch_input([item], 1, 1, [], kb)
        # Should NOT include source freshness header when no data
        assert "Source Freshness:" not in result
        # But should still have KB state
        assert "Current KB State" in result
