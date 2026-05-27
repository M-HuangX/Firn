"""Tests for ingest_cached_articles — one-time bulk import of cached WeChat articles."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from contextlib import ExitStack
from dataclasses import dataclass, field

from src.sources.refresh_pipeline import ingest_cached_articles


@dataclass
class FakeAccount:
    name: str
    effective_tier: int = 2
    tags: list = field(default_factory=list)


@pytest.fixture
def kb_root(tmp_path):
    """Create a minimal KB directory structure."""
    for d in ("library/unread", "library/read", "meta", "notebook/themes",
              "notebook/stocks", "sources"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "meta" / "last_updated.json").write_text("{}")
    return tmp_path


@pytest.fixture
def kb(kb_root):
    from src.knowledge_base.kb_api import KnowledgeBase
    return KnowledgeBase(kb_root=kb_root)


@pytest.fixture
def mock_manager():
    """Mock WechatSourceManager with 2 accounts and cached articles."""
    mgr = MagicMock()
    mgr.accounts = [
        FakeAccount(name="TestAccount1", effective_tier=2, tags=["macro"]),
        FakeAccount(name="TestAccount2", effective_tier=3, tags=[]),
    ]
    mgr.get_account.side_effect = lambda n: next(
        (a for a in mgr.accounts if a.name == n), None
    )
    mgr.get_recent_articles.side_effect = lambda name, **kw: {
        "TestAccount1": [
            {"title": "Article A", "account": "TestAccount1", "timestamp": 1715700000,
             "summary": "Summary A", "content": "Full content A", "sogou_link": "",
             "wechat_url": "https://mp.weixin.qq.com/a"},
            {"title": "Article B", "account": "TestAccount1", "timestamp": 1715600000,
             "summary": "Summary B", "content": "Full content B", "sogou_link": "",
             "wechat_url": ""},
        ],
        "TestAccount2": [
            {"title": "Article C", "account": "TestAccount2", "timestamp": 1715500000,
             "summary": "Summary C", "content": "Full content C", "sogou_link": "",
             "wechat_url": ""},
        ],
    }.get(name, [])
    return mgr


def _run_with_patches(mock_manager, kb):
    """Run ingest_cached_articles with all necessary patches."""
    with ExitStack() as stack:
        stack.enter_context(patch("src.sources.refresh_pipeline.WechatSourceManager", return_value=mock_manager))
        stack.enter_context(patch("src.sources.refresh_pipeline.KnowledgeBase", return_value=kb))
        stack.enter_context(patch("src.knowledge_base.perception.KnowledgeBase", return_value=kb))
        stack.enter_context(patch("src.sources.refresh_pipeline._ingest_bilibili_cached", return_value=0))
        return ingest_cached_articles()


class TestIngestCached:
    def test_imports_all_cached_articles(self, kb_root, kb, mock_manager):
        result = _run_with_patches(mock_manager, kb)

        assert result["total_created"] == 3
        assert result["per_account"]["TestAccount1"] == 2
        assert result["per_account"]["TestAccount2"] == 1

        pending = list((kb_root / "library" / "unread").glob("*.md"))
        assert len(pending) == 3

    def test_dedup_against_existing_pending(self, kb_root, kb, mock_manager):
        """Articles already in library/unread should be skipped."""
        item = "---\ntitle: [TestAccount1] Article A\n---\nexisting"
        (kb_root / "library" / "unread" / "old-item.md").write_text(item)

        result = _run_with_patches(mock_manager, kb)
        assert result["total_created"] == 2

    def test_dedup_against_existing_digested(self, kb_root, kb, mock_manager):
        """Articles already in library/read should be skipped."""
        item = "---\ntitle: [TestAccount1] Article A\n---\nalready digested"
        (kb_root / "library" / "read" / "old-item.md").write_text(item)

        result = _run_with_patches(mock_manager, kb)
        assert result["total_created"] == 2

    def test_no_cached_articles(self, kb, mock_manager):
        """Empty cache → 0 imports."""
        mgr = MagicMock()
        mgr.accounts = [FakeAccount(name="Empty")]
        mgr.get_recent_articles.return_value = []

        result = _run_with_patches(mgr, kb)
        assert result["total_created"] == 0

    def test_idempotent(self, kb, mock_manager):
        """Running twice produces 0 new items on second run."""
        r1 = _run_with_patches(mock_manager, kb)
        assert r1["total_created"] == 3

        r2 = _run_with_patches(mock_manager, kb)
        assert r2["total_created"] == 0

    def test_event_log_emitted(self, kb, mock_manager, monkeypatch):
        """Verify event log is called for start and end."""
        events = []
        monkeypatch.setattr(
            "src.sources.refresh_pipeline.log_event",
            lambda event, **kw: events.append(event),
        )

        _run_with_patches(mock_manager, kb)

        assert "source.ingest_cached_start" in events
        assert "source.ingest_cached_end" in events
