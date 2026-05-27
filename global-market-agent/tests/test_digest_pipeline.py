"""Tests for digest_pipeline.py — batch digest with CoreAgent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.knowledge_base.digest_pipeline import (
    BatchResult,
    DigestResult,
    _append_session_log,
    _build_batch_input,
    _build_session_summary,
    _format_batch_for_history,
    run_digest,
)
from src.knowledge_base.kb_api import KnowledgeBase
from src.knowledge_base.perception import InboxItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AGENT_OUTPUT = "### Session Notes\n- Items read: test\n- Key takeaway: done"

_INBOX_TEMPLATE = """\
---
source: test_src
tier: {tier}
content_type: news
title: {title}
---
{body}"""


def _make_item(
    slug: str, tier: int = 3, title: str = "Test", body: str = "Body text"
) -> InboxItem:
    return InboxItem(
        slug=slug,
        source="test_source",
        tier=tier,
        content_type="analysis",
        ticker=None,
        title=title,
        body=body,
    )


def _seed_inbox(kb: KnowledgeBase, count: int, tier: int = 2) -> list[str]:
    """Seed N inbox items and return their slugs."""
    slugs = []
    for i in range(count):
        slug = f"item-{i}"
        content = _INBOX_TEMPLATE.format(tier=tier, title=f"Title {i}", body=f"Body {i}")
        kb.add_unread(slug, content)
        slugs.append(slug)
    return slugs


@pytest.fixture
def kb(tmp_path):
    _kb = KnowledgeBase(kb_root=tmp_path)
    _kb.ensure_structure()
    return _kb


# ---------------------------------------------------------------------------
# autouse mock: never call real CoreAgent
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_core_agent():
    with patch("src.knowledge_base.digest_pipeline.CoreAgent") as mock_cls:
        instance = MagicMock()
        instance.run = AsyncMock(return_value=_AGENT_OUTPUT)
        mock_cls.return_value = instance
        yield mock_cls


@pytest.fixture(autouse=True)
def mock_market_snapshot():
    with patch("src.sources.market.snapshot.generate_market_snapshot_item",
               return_value={"status": "skipped"}):
        yield


@pytest.fixture
def mock_filter():
    with patch("src.knowledge_base.digest_pipeline.filter_items") as mock_f:
        yield mock_f


# ---------------------------------------------------------------------------
# run_digest tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_inbox_returns_early(kb):
    result = await run_digest(kb=kb)
    assert result.total_inbox == 0
    assert result.batches_completed == 0
    assert result.items_processed == 0
    assert result.session_summary == ""


@pytest.mark.asyncio
async def test_single_item_single_batch(kb, mock_core_agent):
    _seed_inbox(kb, 1)
    result = await run_digest(kb=kb, filter_low_trust=False)
    assert result.batches_completed == 1
    assert result.items_processed == 1
    mock_core_agent.return_value.run.assert_called_once()


@pytest.mark.asyncio
async def test_multi_batch_processing(kb, mock_core_agent):
    _seed_inbox(kb, 20)
    result = await run_digest(batch_size=10, kb=kb, filter_low_trust=False)
    assert result.batches_completed == 2
    assert result.items_processed == 20
    assert mock_core_agent.return_value.run.call_count == 2


@pytest.mark.asyncio
async def test_reading_history_accumulates(kb, mock_core_agent):
    _seed_inbox(kb, 20)
    calls_input = []
    mock_core_agent.return_value.run = AsyncMock(
        side_effect=lambda text, **kw: (calls_input.append(text), _AGENT_OUTPUT)[1]
    )
    await run_digest(batch_size=10, kb=kb, filter_low_trust=False)
    assert len(calls_input) == 2
    assert "Reading History" not in calls_input[0]
    assert "Reading History" in calls_input[1]


@pytest.mark.asyncio
async def test_dropped_items_marked_digested(kb, mock_filter):
    _seed_inbox(kb, 3, tier=3)

    from src.agents.filter_agent import FilterResult

    items = []
    for slug in kb.list_unread():
        from src.knowledge_base.perception import parse_inbox_item
        content = kb.read_unread(slug)
        items.append(parse_inbox_item(slug, content))

    mock_filter.return_value = FilterResult(
        kept=[items[0]],
        dropped=[items[1], items[2]],
        auto_passed=[],
        reasons="",
    )

    await run_digest(kb=kb)

    # Dropped items should be in digested
    digested = kb.list_read()
    assert items[1].slug in digested
    assert items[2].slug in digested


@pytest.mark.asyncio
async def test_unparseable_items_marked_digested(kb):
    # Add an item without frontmatter
    kb.add_unread("bad-item", "No frontmatter here, just plain text")
    result = await run_digest(kb=kb, filter_low_trust=False)
    assert result.total_inbox == 1
    assert result.items_processed == 0
    digested = kb.list_read()
    assert "bad-item" in digested


@pytest.mark.asyncio
async def test_filter_disabled(kb, mock_filter):
    _seed_inbox(kb, 3, tier=3)
    result = await run_digest(kb=kb, filter_low_trust=False)
    mock_filter.assert_not_called()
    assert result.items_processed == 3
    assert result.auto_passed == 0
    assert result.filter_kept == 3
    assert result.filter_dropped == 0


@pytest.mark.asyncio
async def test_custom_batch_size(kb, mock_core_agent):
    _seed_inbox(kb, 12)
    result = await run_digest(batch_size=5, kb=kb, filter_low_trust=False)
    assert result.batches_completed == 3
    assert mock_core_agent.return_value.run.call_count == 3


@pytest.mark.asyncio
async def test_all_filtered_out(kb, mock_filter, mock_core_agent):
    _seed_inbox(kb, 3, tier=3)

    from src.agents.filter_agent import FilterResult
    from src.knowledge_base.perception import parse_inbox_item

    items = []
    for slug in kb.list_unread():
        content = kb.read_unread(slug)
        items.append(parse_inbox_item(slug, content))

    mock_filter.return_value = FilterResult(
        kept=[],
        dropped=items,
        auto_passed=[],
        reasons="all irrelevant",
    )

    result = await run_digest(kb=kb)
    assert result.batches_completed == 0
    assert result.items_processed == 0
    mock_core_agent.return_value.run.assert_not_called()


@pytest.mark.asyncio
async def test_items_marked_by_output_handler(kb, mock_core_agent):
    _seed_inbox(kb, 2)

    # Simulate the output handler being called by CoreAgent
    async def fake_run(input_text, context=None):
        # Simulate what the real output_handler would do
        from src.agents.output_handlers import mark_library_read
        await mark_library_read(_AGENT_OUTPUT, context, kb)
        return _AGENT_OUTPUT

    mock_core_agent.return_value.run = AsyncMock(side_effect=fake_run)
    await run_digest(kb=kb, filter_low_trust=False)
    # Items should be moved to digested
    assert len(kb.list_unread()) == 0
    assert len(kb.list_read()) == 2


@pytest.mark.asyncio
async def test_batch_error_continues(kb, mock_core_agent):
    _seed_inbox(kb, 20)
    call_count = [0]

    async def failing_first_batch(input_text, context=None):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("LLM failed")
        return _AGENT_OUTPUT

    mock_core_agent.return_value.run = AsyncMock(side_effect=failing_first_batch)
    result = await run_digest(batch_size=10, kb=kb, filter_low_trust=False)
    assert result.batches_completed == 1  # only successful batches counted
    assert len(result.batch_results) == 2  # both batches recorded
    assert result.items_processed == 10  # only successful batch items
    assert "Error" in result.batch_results[0].agent_output


@pytest.mark.asyncio
async def test_failed_batch_marks_items_digested(kb, mock_core_agent):
    """Items in a failed batch should be marked as digested to prevent infinite retry."""
    slugs = _seed_inbox(kb, 3)

    mock_core_agent.return_value.run = AsyncMock(
        side_effect=RuntimeError("LLM crashed")
    )
    result = await run_digest(batch_size=8, kb=kb, filter_low_trust=False)
    assert result.batches_completed == 0  # no successful batches

    # All items should have been moved to digested despite the failure
    pending = kb.list_unread()
    digested = kb.list_read()
    assert len(pending) == 0
    for slug in slugs:
        assert slug in digested


@pytest.mark.asyncio
async def test_digest_result_fields_correct(kb):
    _seed_inbox(kb, 5)
    result = await run_digest(kb=kb, filter_low_trust=False)
    assert result.total_inbox == 5
    assert result.items_processed == 5
    assert result.batches_completed == 1
    assert len(result.batch_results) == 1
    assert result.session_summary != ""
    assert result.filter_kept == 5
    assert result.auto_passed == 0
    assert result.filter_dropped == 0


@pytest.mark.asyncio
async def test_session_log_written(kb):
    _seed_inbox(kb, 2)
    await run_digest(kb=kb, filter_low_trust=False)
    path = kb.root / "meta" / "digest_sessions.md"
    assert path.is_file()
    content = path.read_text(encoding="utf-8")
    assert "Digest Session" in content


@pytest.mark.asyncio
async def test_session_log_prepends(kb):
    _seed_inbox(kb, 2)
    await run_digest(kb=kb, filter_low_trust=False)
    # Seed more and run again
    _seed_inbox(kb, 2)
    await run_digest(kb=kb, filter_low_trust=False)
    path = kb.root / "meta" / "digest_sessions.md"
    content = path.read_text(encoding="utf-8")
    # Should have two sessions separated by ---
    assert content.count("Digest Session") == 2
    # The separator should be present
    assert "\n---\n" in content


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


def test_build_batch_input_format(kb):
    items = [_make_item("slug1", tier=1, title="Fed Report", body="Rate decision content")]
    result = _build_batch_input(items, 1, 1, [], kb)
    assert "Digest Batch 1/1" in result
    assert "Items to Digest" in result
    assert "slug1" in result
    assert "Fed Report" in result
    assert "Current KB State" in result
    assert 'read_inbox_item("slug")' in result


def test_build_batch_input_with_reading_history(kb):
    items = [_make_item("slug2", tier=2)]
    history = ["## Batch 1 Summary\nItems: #slug1 (Tier 1, \"Title\")"]
    result = _build_batch_input(items, 2, 2, history, kb)
    assert "Reading History" in result
    assert "Batch 1 Summary" in result


def test_build_batch_input_empty_kb(kb):
    items = [_make_item("slug1")]
    result = _build_batch_input(items, 1, 1, [], kb)
    assert "Themes: 0 files" in result
    assert "Events: 0 files" in result
    assert "not yet created" in result


def test_format_batch_for_history_with_session_notes():
    br = BatchResult(
        batch_num=1,
        item_slugs=["a", "b"],
        items_detail=[("a", "Title A", 2), ("b", "Title B", 3)],
        agent_output="Some analysis\n### Session Notes\n- Items read: a, b\n- Key takeaway: useful",
    )
    result = _format_batch_for_history(br)
    assert "Batch 1 Summary" in result
    assert "Items read: a, b" in result
    assert "Key takeaway: useful" in result


def test_format_batch_for_history_without_session_notes():
    br = BatchResult(
        batch_num=1,
        item_slugs=["a"],
        items_detail=[("a", "Title A", 2)],
        agent_output="Just some plain agent output without session notes section",
    )
    result = _format_batch_for_history(br)
    assert "Batch 1 Summary" in result
    assert "plain agent output" in result


def test_build_session_summary_format():
    br = BatchResult(
        batch_num=1,
        item_slugs=["s1", "s2"],
        items_detail=[("s1", "T1", 2), ("s2", "T2", 3)],
        agent_output="output text here",
    )
    result = _build_session_summary([br], auto_passed=1, filter_kept=2, filter_dropped=0)
    assert "Digest Session" in result
    assert "Auto-passed: 1" in result
    assert "Filter kept: 2 | dropped: 0" in result
    assert "Batches: 1" in result
    assert "Total processed: 2" in result
    assert "s1, s2" in result


def test_tier_grouping_in_catalog(kb):
    items = [
        _make_item("low", tier=3, title="Low Trust"),
        _make_item("high", tier=1, title="High Trust"),
    ]
    result = _build_batch_input(items, 1, 1, [], kb)
    # Tier 1 should appear before tier 3
    high_pos = result.index("high trust")
    low_pos = result.index("medium trust")
    assert high_pos < low_pos


def test_kb_state_in_batch_input(kb):
    # Seed some themes and events
    kb.write_theme("ai-capex", "# AI Capex\nContent")
    kb.write_event("fed-rate", "# Fed Rate\nContent")
    items = [_make_item("slug1")]
    result = _build_batch_input(items, 1, 1, [], kb)
    assert "Themes: 1 files" in result
    assert "Events: 1 files" in result


def test_append_session_log(kb):
    _append_session_log(kb, "## Session 1\nContent 1")
    path = kb.root / "meta" / "digest_sessions.md"
    assert "Session 1" in path.read_text(encoding="utf-8")

    _append_session_log(kb, "## Session 2\nContent 2")
    content = path.read_text(encoding="utf-8")
    # Newest first
    assert content.index("Session 2") < content.index("Session 1")
