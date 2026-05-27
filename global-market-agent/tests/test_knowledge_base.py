"""Tests for the Knowledge Base API."""

import json

import pytest
import yaml

from src.knowledge_base.kb_api import KnowledgeBase


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kb(tmp_path):
    """Return a KnowledgeBase rooted in a temporary directory with structure created."""
    firn_dir = tmp_path / "firn"
    firn_dir.mkdir()
    _kb = KnowledgeBase(kb_root=firn_dir)
    _kb.ensure_structure()
    # Seed the two config files that read_principles / read_source_registry expect
    (firn_dir / "agent_principles.md").write_text("# Principles\n## 1. Test\n", encoding="utf-8")
    (_kb.data_root / "sources").mkdir(parents=True, exist_ok=True)
    (_kb.data_root / "sources" / "source_registry.yaml").write_text(
        yaml.dump(
            {
                "sources": {
                    "sec_filings": {"tier": 1, "trust": "unconditional", "bias": "none"},
                    "social_media": {"tier": 4, "trust": "low", "bias": "varies"},
                }
            }
        ),
        encoding="utf-8",
    )
    return _kb


# ---------------------------------------------------------------------------
# ensure_structure
# ---------------------------------------------------------------------------


class TestEnsureStructure:
    def test_creates_all_directories(self, tmp_path):
        firn_dir = tmp_path / "firn"
        firn_dir.mkdir()
        kb = KnowledgeBase(kb_root=firn_dir)
        kb.ensure_structure()
        # Firn directories (under kb.root)
        for d in [
            "notebook",
            "notebook/themes",
            "notebook/events",
            "notebook/sectors",
            "notebook/stocks",
            "user_context",
            "user_context/forwarded",
            "library/unread",
            "library/read",
            "archive",
        ]:
            assert (firn_dir / d).is_dir(), f"Missing firn directory: {d}"
        # Data directories (under kb.data_root)
        for d in ["sources", "meta"]:
            assert (kb.data_root / d).is_dir(), f"Missing data directory: {d}"

    def test_idempotent(self, tmp_path):
        kb = KnowledgeBase(kb_root=tmp_path)
        kb.ensure_structure()
        kb.ensure_structure()  # should not raise


# ---------------------------------------------------------------------------
# Principles
# ---------------------------------------------------------------------------


class TestPrinciples:
    def test_read_principles(self, kb):
        text = kb.read_principles()
        assert "# Principles" in text

    def test_read_principles_missing(self, tmp_path):
        kb = KnowledgeBase(kb_root=tmp_path)
        with pytest.raises(FileNotFoundError):
            kb.read_principles()


# ---------------------------------------------------------------------------
# Source Registry
# ---------------------------------------------------------------------------


class TestSourceRegistry:
    def test_read_source_registry(self, kb):
        registry = kb.read_source_registry()
        assert "sources" in registry
        assert "sec_filings" in registry["sources"]

    def test_get_source_info(self, kb):
        info = kb.get_source_info("sec_filings")
        assert info is not None
        assert info["tier"] == 1

    def test_get_source_info_unknown(self, kb):
        assert kb.get_source_info("nonexistent") is None

    def test_get_source_tier(self, kb):
        assert kb.get_source_tier("sec_filings") == 1
        assert kb.get_source_tier("social_media") == 4

    def test_get_source_tier_unknown(self, kb):
        assert kb.get_source_tier("nonexistent") is None


# ---------------------------------------------------------------------------
# Core Mind
# ---------------------------------------------------------------------------


class TestCoreMind:
    def test_read_nonexistent(self, kb):
        assert kb.read_core_mind() is None

    def test_write_and_read(self, kb):
        kb.write_core_mind("# Core Mind\nBullish regime")
        text = kb.read_core_mind()
        assert text is not None
        assert "Bullish regime" in text


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------


class TestThemes:
    def test_list_empty(self, kb):
        assert kb.list_themes() == []

    def test_write_and_list(self, kb):
        kb.write_theme("ai-boom", "# AI Boom\nDetails here")
        kb.write_theme("rate-cuts", "# Rate Cuts\nDetails here")
        themes = kb.list_themes()
        assert themes == ["ai-boom", "rate-cuts"]

    def test_read_theme(self, kb):
        kb.write_theme("ai-boom", "# AI Boom")
        assert kb.read_theme("ai-boom") == "# AI Boom"

    def test_read_nonexistent_theme(self, kb):
        assert kb.read_theme("nope") is None

    def test_archive_theme(self, kb):
        kb.write_theme("old-theme", "content")
        kb.archive_theme("old-theme")
        assert kb.read_theme("old-theme") is None
        archived = kb.root / "archive" / "old-theme.md"
        assert archived.is_file()
        assert archived.read_text(encoding="utf-8") == "content"

    def test_archive_nonexistent_theme(self, kb):
        with pytest.raises(FileNotFoundError):
            kb.archive_theme("nonexistent")


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class TestEvents:
    def test_list_empty(self, kb):
        assert kb.list_events() == []

    def test_write_and_read(self, kb):
        kb.write_event("fed-meeting-2026-05", "# Fed Meeting\nHeld rates.")
        assert "Held rates" in kb.read_event("fed-meeting-2026-05")
        assert kb.list_events() == ["fed-meeting-2026-05"]

    def test_read_nonexistent(self, kb):
        assert kb.read_event("nope") is None


# ---------------------------------------------------------------------------
# Sectors
# ---------------------------------------------------------------------------


class TestSectors:
    def test_read_nonexistent(self, kb):
        assert kb.read_sector("tech") is None

    def test_write_and_read(self, kb):
        kb.write_sector("tech", "# Technology\nOverweight")
        assert "Overweight" in kb.read_sector("tech")


# ---------------------------------------------------------------------------
# Stocks
# ---------------------------------------------------------------------------


class TestStocks:
    def test_list_empty(self, kb):
        assert kb.list_stock_files("AAPL") == []

    def test_write_and_read(self, kb):
        kb.write_stock("AAPL", "thesis", "# AAPL Thesis\nGreat company but overpriced")
        kb.write_stock("AAPL", "expectations", "# AAPL Expectations\nEPS $7.50")
        assert "overpriced" in kb.read_stock("AAPL", "thesis")
        assert kb.list_stock_files("AAPL") == ["expectations", "thesis"]

    def test_ticker_case_normalized(self, kb):
        kb.write_stock("aapl", "thesis", "lowercase ticker")
        assert kb.read_stock("AAPL", "thesis") == "lowercase ticker"

    def test_read_nonexistent(self, kb):
        assert kb.read_stock("TSLA", "thesis") is None


# ---------------------------------------------------------------------------
# User Context
# ---------------------------------------------------------------------------


class TestUserContext:
    def test_user_views_roundtrip(self, kb):
        assert kb.read_user_views() is None
        kb.write_user_views("# Views\nBullish on NVDA")
        assert "Bullish on NVDA" in kb.read_user_views()

    def test_divergences_roundtrip(self, kb):
        assert kb.read_divergences() is None
        kb.write_divergences("# Divergences\nUser bullish, agent bearish on TSLA")
        assert "TSLA" in kb.read_divergences()

    def test_forwarded_roundtrip(self, kb):
        assert kb.list_forwarded() == []
        kb.write_forwarded("article-2026-05-14", "# Forwarded Article\nSeeking Alpha says...")
        assert kb.list_forwarded() == ["article-2026-05-14"]
        assert "Seeking Alpha" in kb.read_forwarded("article-2026-05-14")

    def test_read_nonexistent_forwarded(self, kb):
        assert kb.read_forwarded("nope") is None


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------


class TestInbox:
    def test_add_and_list_unread(self, kb):
        assert kb.list_unread() == []
        kb.add_unread("news-20260514", "# Breaking\nFed raises rates")
        assert kb.list_unread() == ["news-20260514"]
        assert "Fed raises" in kb.read_unread("news-20260514")

    def test_read_nonexistent_pending(self, kb):
        assert kb.read_unread("nope") is None

    def test_mark_read(self, kb):
        kb.add_unread("item-1", "content")
        kb.mark_read("item-1")
        assert kb.list_unread() == []
        read_file = kb.root / "library" / "read" / "item-1.md"
        assert read_file.is_file()
        assert read_file.read_text(encoding="utf-8") == "content"

    def test_mark_read_nonexistent(self, kb):
        with pytest.raises(FileNotFoundError):
            kb.mark_read("nope")


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


class TestMeta:
    def test_get_last_updated_empty(self, kb):
        assert kb.get_last_updated() == {}

    def test_set_last_updated_with_new_data(self, kb):
        kb.set_last_updated("wechat_test", new_count=3, summary="3 new articles")
        data = kb.get_last_updated()
        entry = data["wechat_test"]
        assert isinstance(entry, dict)
        assert entry["new_count"] == 3
        assert entry["summary"] == "3 new articles"
        assert "T" in entry["last_checked"]
        assert entry["last_new_data"] is not None
        assert "T" in entry["last_new_data"]

    def test_set_last_updated_no_new_data(self, kb):
        # First call with new data
        kb.set_last_updated("wechat_test", new_count=2, summary="2 new")
        first = kb.get_last_updated()["wechat_test"]
        first_new = first["last_new_data"]

        # Second call with no new data
        kb.set_last_updated("wechat_test", new_count=0, summary="no new articles")
        second = kb.get_last_updated()["wechat_test"]
        assert second["new_count"] == 0
        assert second["summary"] == "no new articles"
        # last_new_data should be preserved from first call
        assert second["last_new_data"] == first_new
        # last_checked should be updated
        assert second["last_checked"] >= first["last_checked"]

    def test_set_last_updated_no_prior_no_new(self, kb):
        """First check with zero results → last_new_data is None."""
        kb.set_last_updated("wechat_new", new_count=0, summary="no data")
        entry = kb.get_last_updated()["wechat_new"]
        assert entry["last_new_data"] is None

    def test_set_last_updated_preserves_other_sources(self, kb):
        kb.set_last_updated("source_a", new_count=1, summary="1 new")
        kb.set_last_updated("source_b", new_count=2, summary="2 new")
        data = kb.get_last_updated()
        assert "source_a" in data
        assert "source_b" in data
        assert data["source_a"]["new_count"] == 1
        assert data["source_b"]["new_count"] == 2

    def test_set_last_updated_legacy_migration(self, kb):
        """Old string-format entries are migrated when overwritten."""
        # Manually write legacy format
        import json
        path = kb.data_root / "meta" / "last_updated.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"old_source": "2026-01-01T00:00:00Z"}))

        # Overwrite with new API
        kb.set_last_updated("old_source", new_count=0, summary="checked")
        entry = kb.get_last_updated()["old_source"]
        assert isinstance(entry, dict)
        # Legacy timestamp should be preserved as last_new_data
        assert entry["last_new_data"] == "2026-01-01T00:00:00Z"

    def test_build_source_status_empty(self, kb):
        result = kb.build_source_status()
        assert "No source freshness data" in result

    def test_build_source_status_with_data(self, kb):
        kb.set_last_updated("wechat_test", new_count=2, summary="2 articles")
        kb.set_last_updated("wechat_other", new_count=0, summary="no new")
        result = kb.build_source_status()
        assert "Source Freshness:" in result
        assert "wechat_test" in result
        assert "2 new" in result
        assert "wechat_other" in result

    def test_build_source_status_legacy_format(self, kb):
        """Legacy string entries render gracefully."""
        import json
        path = kb.data_root / "meta" / "last_updated.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"legacy": "2026-01-01T00:00:00Z"}))

        result = kb.build_source_status()
        assert "legacy" in result
        assert "2026-01-01" in result

    def test_append_log(self, kb):
        # Create the initial log file
        log_path = kb.data_root / "meta" / "update_log.md"
        log_path.write_text("# Knowledge Base Update Log\n", encoding="utf-8")

        kb.append_log("Seeded KB with AAPL data")
        kb.append_log("Updated macro regime")

        text = log_path.read_text(encoding="utf-8")
        assert "Seeded KB with AAPL data" in text
        assert "Updated macro regime" in text
        # Each entry should be timestamped
        lines = [l for l in text.splitlines() if l.startswith("- [")]
        assert len(lines) == 2
        assert "UTC" in lines[0]

    def test_get_last_updated_missing_file(self, tmp_path):
        """When no last_updated.json exists, return empty dict."""
        kb = KnowledgeBase(kb_root=tmp_path)
        assert kb.get_last_updated() == {}


# ---------------------------------------------------------------------------
# Default KB root
# ---------------------------------------------------------------------------


class TestDefaultRoot:
    def test_default_root_points_to_firn(self):
        kb = KnowledgeBase()
        # Should resolve to global-market-agent/firn/
        assert kb.root.name == "firn"
        assert kb.root.parent.name == "global-market-agent"
        # data_root should be global-market-agent/data/
        assert kb.data_root.name == "data"
        assert kb.data_root.parent.name == "global-market-agent"
