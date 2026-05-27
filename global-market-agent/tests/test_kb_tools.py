"""Tests for KB Tool Set (kb_tools.py) and kb_api.py enhancements."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.knowledge_base.kb_api import KnowledgeBase
from src.knowledge_base.kb_tools import (
    KBToolSet,
    READ_ONLY_SECTIONS,
    SECTION_MAP,
    WRITABLE_SECTIONS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kb(tmp_path):
    """Return a KnowledgeBase rooted in a temp dir with structure + seed files."""
    firn_dir = tmp_path / "firn"
    firn_dir.mkdir()
    _kb = KnowledgeBase(kb_root=firn_dir)
    _kb.ensure_structure()
    # Seed core_mind
    cm = firn_dir / "notebook" / "core_mind.md"
    cm.write_text("# Core Mind\nMarket regime: cautious.", encoding="utf-8")
    # Seed a theme
    theme_dir = firn_dir / "notebook" / "themes"
    (theme_dir / "copper-cycle.md").write_text(
        "# Copper Cycle\nSupply deficit expected.", encoding="utf-8"
    )
    # Seed an inbox item
    inbox_dir = firn_dir / "library" / "unread"
    (inbox_dir / "news-20260514.md").write_text(
        "# Breaking News\nFed held rates at 5.25%.", encoding="utf-8"
    )
    # Seed user_views
    uv = firn_dir / "user_context" / "user_views.md"
    uv.write_text("# User Views\nBullish on NVDA.", encoding="utf-8")
    # Seed a sector
    sector_dir = firn_dir / "notebook" / "sectors"
    (sector_dir / "tech.md").write_text("# Technology\nOverweight.", encoding="utf-8")
    # Seed meta dir for logging
    meta_dir = _kb.data_root / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    return _kb


@pytest.fixture
def ts(kb):
    """Return a KBToolSet wrapping the temp KB."""
    return KBToolSet(kb=kb)


def _invoke(tool_obj, **kwargs):
    """Invoke a LangChain @tool by calling it directly."""
    return tool_obj.invoke(kwargs)


# ===========================================================================
# READ tools
# ===========================================================================


class TestKBList:
    def test_list_themes(self, ts):
        result = _invoke(ts._tools["kb_list"], section="themes")
        assert "copper-cycle" in result
        assert "1." in result

    def test_list_empty_section(self, ts):
        result = _invoke(ts._tools["kb_list"], section="events")
        assert "empty" in result.lower()

    def test_list_unknown_section(self, ts):
        result = _invoke(ts._tools["kb_list"], section="nonexistent")
        assert "Unknown section" in result

    def test_list_single_file_section(self, ts):
        result = _invoke(ts._tools["kb_list"], section="core_mind")
        assert "core_mind" in result


class TestKBRead:
    def test_read_existing_file(self, ts):
        result = _invoke(ts._tools["kb_read"], section="themes", slug="copper-cycle")
        assert "Copper Cycle" in result
        assert "themes/copper-cycle" in ts.read_tracker

    def test_read_nonexistent(self, ts):
        result = _invoke(ts._tools["kb_read"], section="themes", slug="nonexistent")
        assert "Not found" in result

    def test_read_truncates_long_content(self, ts, kb):
        # Write a file longer than _MAX_READ_CHARS (50000)
        big = "x" * 60000
        (kb.root / "notebook" / "themes" / "big.md").write_text(big, encoding="utf-8")
        result = _invoke(ts._tools["kb_read"], section="themes", slug="big")
        assert len(result) < 60000
        assert "[... truncated ...]" in result

    def test_read_unknown_section(self, ts):
        result = _invoke(ts._tools["kb_read"], section="bogus", slug="x")
        assert "Unknown section" in result


class TestKBReadCoreMind:
    def test_reads_core_mind(self, ts):
        result = _invoke(ts._tools["kb_read_core_mind"])
        assert "Core Mind" in result
        assert "core_mind/" in ts.read_tracker

    def test_reads_nonexistent_core_mind(self, tmp_path):
        _kb = KnowledgeBase(kb_root=tmp_path)
        _kb.ensure_structure()
        _ts = KBToolSet(kb=_kb)
        result = _invoke(_ts._tools["kb_read_core_mind"])
        assert "does not exist" in result


class TestDigestHistory:
    def test_read_digest_history(self, ts, kb):
        # Seed digest_sessions.md
        meta_dir = kb.data_root / "meta"
        meta_dir.mkdir(parents=True, exist_ok=True)
        (meta_dir / "digest_sessions.md").write_text(
            "## Digest Session 2026-05-15\n- Batches: 2\n- Key takeaway: tariff thesis confirmed",
            encoding="utf-8",
        )
        result = _invoke(ts._tools["kb_read"], section="digest_history", slug="")
        assert "Digest Session" in result
        assert "tariff thesis" in result

    def test_digest_history_not_found(self, ts):
        result = _invoke(ts._tools["kb_read"], section="digest_history", slug="")
        assert "Not found" in result

    def test_digest_history_is_read_only(self, ts):
        result = _invoke(ts._tools["kb_write"], section="digest_history", slug="", content="hack")
        assert "read-only" in result.lower()

    def test_list_digest_history(self, ts, kb):
        (kb.data_root / "meta").mkdir(parents=True, exist_ok=True)
        (kb.data_root / "meta" / "digest_sessions.md").write_text("# Sessions", encoding="utf-8")
        result = _invoke(ts._tools["kb_list"], section="digest_history")
        assert "digest_sessions" in result


class TestReadInboxItem:
    def test_reads_inbox_item(self, ts):
        result = _invoke(ts._tools["read_inbox_item"], item_id="news-20260514")
        assert "Fed held rates" in result

    def test_inbox_item_not_found(self, ts):
        result = _invoke(ts._tools["read_inbox_item"], item_id="nonexistent")
        assert "not found" in result.lower()


class TestKBSearch:
    def test_finds_matches(self, ts):
        result = _invoke(ts._tools["kb_search"], query="copper")
        assert "copper" in result.lower()
        assert ":" in result  # file:line format

    def test_no_matches(self, ts):
        result = _invoke(ts._tools["kb_search"], query="xyznonexistent123")
        assert "No matches" in result

    def test_search_limits_output(self, ts, kb):
        # Create many files with matching content
        themes_dir = kb.root / "notebook" / "themes"
        for i in range(15):
            (themes_dir / f"theme-{i:02d}.md").write_text(
                f"# Theme {i}\nmatching-keyword line 1\nmatching-keyword line 2",
                encoding="utf-8",
            )
        result = _invoke(ts._tools["kb_search"], query="matching-keyword")
        # Should be capped at MAX_SEARCH_RESULTS (10)
        lines = [l for l in result.strip().split("\n") if ":" in l and "matching-keyword" in l]
        assert len(lines) <= 10


# ===========================================================================
# WRITE tools
# ===========================================================================


class TestKBWrite:
    def test_creates_new_file(self, ts):
        result = _invoke(
            ts._tools["kb_write"],
            section="themes",
            slug="ai-boom",
            content="# AI Boom\nSemiconductor supercycle.",
        )
        assert "Written" in result
        assert (ts.kb.root / "notebook" / "themes" / "ai-boom.md").is_file()

    def test_overwrites_after_read(self, ts):
        # Read first
        _invoke(ts._tools["kb_read"], section="themes", slug="copper-cycle")
        # Then overwrite
        result = _invoke(
            ts._tools["kb_write"],
            section="themes",
            slug="copper-cycle",
            content="# Updated Copper Cycle",
        )
        assert "Written" in result

    def test_blocks_readonly_section(self, ts):
        result = _invoke(
            ts._tools["kb_write"],
            section="inbox",
            slug="test",
            content="should fail",
        )
        assert "read-only" in result.lower() or "Error" in result

    def test_blocks_without_prior_read(self, ts):
        # File exists but was not read
        result = _invoke(
            ts._tools["kb_write"],
            section="themes",
            slug="copper-cycle",
            content="# Overwrite without reading",
        )
        assert "must read" in result.lower() or "Error" in result


class TestKBWriteCoreMind:
    def test_write_after_read(self, ts):
        _invoke(ts._tools["kb_read_core_mind"])
        result = _invoke(
            ts._tools["kb_write_core_mind"],
            content="# Updated Core Mind\nNew regime.",
        )
        assert "Written" in result
        assert ts.kb.read_core_mind() == "# Updated Core Mind\nNew regime."

    def test_blocks_without_read(self, ts):
        result = _invoke(
            ts._tools["kb_write_core_mind"],
            content="# Should fail",
        )
        assert "must read" in result.lower() or "Error" in result


class TestKBArchive:
    def test_archives_file(self, ts):
        result = _invoke(ts._tools["kb_archive"], section="themes", slug="copper-cycle")
        assert "Archived" in result
        # Original should be gone
        assert not (ts.kb.root / "notebook" / "themes" / "copper-cycle.md").is_file()
        # Should exist in archive/
        archive_files = list((ts.kb.root / "archive").glob("*copper-cycle*"))
        assert len(archive_files) == 1

    def test_archive_creates_dir(self, ts, kb):
        # Remove archive dir to test auto-creation
        import shutil
        archive_dir = kb.root / "archive"
        if archive_dir.exists():
            shutil.rmtree(archive_dir)
        # Create a fresh file to archive
        (kb.root / "notebook" / "events" / "test-event.md").write_text(
            "content", encoding="utf-8"
        )
        result = _invoke(ts._tools["kb_archive"], section="events", slug="test-event")
        assert "Archived" in result
        assert (kb.root / "archive").is_dir()


# ===========================================================================
# EDIT tools
# ===========================================================================


class TestKBEdit:
    def test_replaces_text(self, ts):
        _invoke(ts._tools["kb_read"], section="themes", slug="copper-cycle")
        result = _invoke(
            ts._tools["kb_edit"],
            section="themes",
            slug="copper-cycle",
            old_text="Supply deficit expected.",
            new_text="Supply surplus now.",
        )
        assert "Edited" in result
        content = (ts.kb.root / "notebook" / "themes" / "copper-cycle.md").read_text(
            encoding="utf-8"
        )
        assert "Supply surplus now." in content
        assert "Supply deficit expected." not in content

    def test_blocks_readonly(self, ts):
        ts.read_tracker.add("inbox/news-20260514")
        result = _invoke(
            ts._tools["kb_edit"],
            section="inbox",
            slug="news-20260514",
            old_text="Fed",
            new_text="ECB",
        )
        assert "read-only" in result.lower() or "Error" in result

    def test_blocks_without_read(self, ts):
        result = _invoke(
            ts._tools["kb_edit"],
            section="themes",
            slug="copper-cycle",
            old_text="Supply deficit",
            new_text="Supply surplus",
        )
        assert "must read" in result.lower()

    def test_fails_on_non_unique_match(self, ts, kb):
        # Create a file with duplicate text
        (kb.root / "notebook" / "themes" / "dup.md").write_text(
            "AAA BBB AAA", encoding="utf-8"
        )
        ts.read_tracker.add("themes/dup")
        result = _invoke(
            ts._tools["kb_edit"],
            section="themes",
            slug="dup",
            old_text="AAA",
            new_text="CCC",
        )
        assert "2 times" in result or "not unique" in result.lower() or "appears" in result

    def test_fails_on_missing_text(self, ts):
        _invoke(ts._tools["kb_read"], section="themes", slug="copper-cycle")
        result = _invoke(
            ts._tools["kb_edit"],
            section="themes",
            slug="copper-cycle",
            old_text="This text does not exist",
            new_text="replacement",
        )
        assert "not found" in result.lower()

    def test_edit_theme_size_warning(self, ts, kb):
        """Editing a theme file past 4000 chars should trigger a size warning."""
        big_content = "# Big Theme\n" + "x" * 4500
        (kb.root / "notebook" / "themes" / "big-theme.md").write_text(
            big_content, encoding="utf-8"
        )
        ts.read_tracker.add("themes/big-theme")
        result = _invoke(
            ts._tools["kb_edit"],
            section="themes",
            slug="big-theme",
            old_text="# Big Theme",
            new_text="# Big Theme Updated",
        )
        assert "WARNING" in result
        assert "4000" in result

    def test_edit_core_mind_size_warning(self, ts, kb):
        """Editing core_mind past 4500 chars should trigger a size warning."""
        big_cm = "# Core Mind\n" + "y" * 5000
        (kb.root / "notebook" / "core_mind.md").write_text(
            big_cm, encoding="utf-8"
        )
        ts.read_tracker.add("core_mind/")
        result = _invoke(
            ts._tools["kb_edit"],
            section="core_mind",
            slug="",
            old_text="# Core Mind",
            new_text="# Core Mind Updated",
        )
        assert "WARNING" in result
        assert "4500" in result

    def test_edit_small_file_no_warning(self, ts):
        """Editing a small file should not trigger any warning."""
        _invoke(ts._tools["kb_read"], section="themes", slug="copper-cycle")
        result = _invoke(
            ts._tools["kb_edit"],
            section="themes",
            slug="copper-cycle",
            old_text="Supply deficit expected.",
            new_text="Supply surplus now.",
        )
        assert "WARNING" not in result
        assert "Edited" in result


# ===========================================================================
# Safety tests
# ===========================================================================


class TestSafety:
    def test_path_traversal_blocked(self, ts):
        # Need enough ../ to escape: themes/ is at root/notebook/themes/
        # so ../../../../etc/passwd escapes the KB root
        with pytest.raises(ValueError, match="traversal"):
            _invoke(ts._tools["kb_read"], section="themes", slug="../../../../etc/passwd")

    def test_path_sandbox_enforced(self, ts):
        """Directly test _check_sandbox with a path outside root."""
        from pathlib import Path

        with pytest.raises(ValueError):
            ts._check_sandbox(Path("/etc/passwd"))

    def test_sandbox_rejects_sibling_directory(self, ts, kb):
        """Sibling dirs whose names share a prefix with KB root must be rejected."""
        from pathlib import Path

        # Create a sibling directory: {parent}/{kb_dir_name}_evil/
        sibling = kb.root.parent / (kb.root.name + "_evil")
        sibling.mkdir(exist_ok=True)
        evil_file = sibling / "payload.md"
        evil_file.write_text("malicious", encoding="utf-8")
        with pytest.raises(ValueError, match="traversal"):
            ts._check_sandbox(evil_file)

    def test_write_operations_logged(self, ts, kb):
        log_path = kb.data_root / "meta" / "update_log.md"
        _invoke(
            ts._tools["kb_write"],
            section="events",
            slug="test-event",
            content="# Test Event",
        )
        assert log_path.is_file()
        log_text = log_path.read_text(encoding="utf-8")
        assert "kb_write" in log_text
        assert "events/test-event" in log_text

    def test_section_map_covers_all(self):
        """SECTION_MAP keys should equal WRITABLE + READ_ONLY."""
        all_sections = WRITABLE_SECTIONS | READ_ONLY_SECTIONS
        assert set(SECTION_MAP.keys()) == all_sections


# ===========================================================================
# get_tools / get_tools_by_names
# ===========================================================================


class TestToolRetrieval:
    def test_get_tools_returns_all(self, ts):
        tools = ts.get_tools()
        assert len(tools) == 10
        names = {t.name for t in tools}
        expected = {
            "kb_list", "kb_read", "kb_read_core_mind", "read_inbox_item",
            "kb_search", "kb_write", "kb_write_core_mind", "kb_archive",
            "kb_edit", "kb_log",
        }
        assert names == expected

    def test_get_tools_by_names_subset(self, ts):
        tools = ts.get_tools_by_names(["kb_read", "kb_list"])
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"kb_read", "kb_list"}

    def test_get_tools_by_names_unknown_ignored(self, ts):
        tools = ts.get_tools_by_names(["kb_read", "nonexistent"])
        assert len(tools) == 1
        assert tools[0].name == "kb_read"


# ===========================================================================
# kb_api enhancements
# ===========================================================================


class TestSaveReportWithRotation:
    def test_creates_new_report(self, kb):
        path_str = kb.save_report_with_rotation("AAPL", "# AAPL Report\nBuy.")
        assert "latest_report.md" in path_str
        latest = kb.root / "notebook" / "stocks" / "AAPL" / "latest_report.md"
        assert latest.is_file()
        assert "Buy." in latest.read_text(encoding="utf-8")

    def test_rotates_old_report(self, kb):
        # Write first report
        kb.save_report_with_rotation("TSLA", "# Old Report")
        # Write second report — old one should be moved to history
        kb.save_report_with_rotation("TSLA", "# New Report")

        latest = kb.root / "notebook" / "stocks" / "TSLA" / "latest_report.md"
        assert "New Report" in latest.read_text(encoding="utf-8")

        history_dir = kb.root / "notebook" / "stocks" / "TSLA" / "report_history"
        assert history_dir.is_dir()
        history_files = list(history_dir.glob("*.md"))
        assert len(history_files) == 1
        assert "Old Report" in history_files[0].read_text(encoding="utf-8")


class TestListSectors:
    def test_list_sectors(self, kb):
        sectors = kb.list_sectors()
        assert "tech" in sectors

    def test_list_sectors_empty(self, tmp_path):
        _kb = KnowledgeBase(kb_root=tmp_path)
        _kb.ensure_structure()
        assert _kb.list_sectors() == []


class TestArchiveFile:
    def test_archive_file_moves_with_date(self, kb):
        # Create a file to archive
        themes_dir = kb.root / "notebook" / "themes"
        (themes_dir / "old-theme.md").write_text("old content", encoding="utf-8")

        kb.archive_file("notebook/themes", "old-theme")

        assert not (themes_dir / "old-theme.md").is_file()
        archive_files = list((kb.root / "archive").glob("*old-theme*"))
        assert len(archive_files) == 1
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert date_str in archive_files[0].name

    def test_archive_file_not_found(self, kb):
        with pytest.raises(FileNotFoundError):
            kb.archive_file("notebook/themes", "nonexistent")
