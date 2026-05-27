"""Tests for filter_agent.py — LLM-based relevance filter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.filter_agent import FilterResult, _parse_keep_ids, filter_items
from src.knowledge_base.perception import InboxItem


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


# ---------------------------------------------------------------------------
# filter_items tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_pass_tier_1_2():
    items = [_make_item("a", tier=1), _make_item("b", tier=2), _make_item("c", tier=3)]
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=MagicMock(content="KEEP: 1\nDROP: \nREASON: relevant")
    )
    with patch("src.agents.filter_agent.create_llm", return_value=mock_llm):
        result = await filter_items(items, "core mind summary")
    assert len(result.auto_passed) == 2
    assert result.auto_passed[0].slug == "a"
    assert result.auto_passed[1].slug == "b"


@pytest.mark.asyncio
async def test_all_high_trust():
    items = [_make_item("a", tier=1), _make_item("b", tier=2)]
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock()
    with patch("src.agents.filter_agent.create_llm", return_value=mock_llm):
        result = await filter_items(items, "core mind summary")
    assert len(result.auto_passed) == 2
    assert len(result.kept) == 0
    assert len(result.dropped) == 0
    mock_llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_filter_keeps_relevant():
    items = [_make_item("a", tier=3), _make_item("b", tier=3), _make_item("c", tier=3)]
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=MagicMock(content="KEEP: 1, 3\nDROP: 2\nREASON: #1 relevant; #3 interesting")
    )
    with patch("src.agents.filter_agent.create_llm", return_value=mock_llm):
        result = await filter_items(items, "core mind summary")
    assert len(result.kept) == 2
    assert result.kept[0].slug == "a"
    assert result.kept[1].slug == "c"
    assert len(result.dropped) == 1
    assert result.dropped[0].slug == "b"


@pytest.mark.asyncio
async def test_filter_drops_irrelevant():
    items = [_make_item("a", tier=3), _make_item("b", tier=3), _make_item("c", tier=3)]
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=MagicMock(content="KEEP: \nDROP: 1, 2, 3\nREASON: all irrelevant")
    )
    with patch("src.agents.filter_agent.create_llm", return_value=mock_llm):
        result = await filter_items(items, "core mind summary")
    # Empty KEEP line → safe fallback keeps all
    assert len(result.kept) == 3
    assert len(result.dropped) == 0


@pytest.mark.asyncio
async def test_filter_fallback_on_llm_error():
    items = [_make_item("a", tier=3), _make_item("b", tier=3)]
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("API down"))
    with patch("src.agents.filter_agent.create_llm", return_value=mock_llm):
        result = await filter_items(items, "core mind summary")
    assert len(result.kept) == 2
    assert len(result.dropped) == 0


@pytest.mark.asyncio
async def test_empty_items():
    result = await filter_items([], "core mind summary")
    assert len(result.kept) == 0
    assert len(result.dropped) == 0
    assert len(result.auto_passed) == 0


@pytest.mark.asyncio
async def test_filter_prompt_contains_catalog():
    items = [_make_item("x", tier=3, title="AI capex update", body="Big spending on AI")]
    captured_prompt = []
    mock_llm = MagicMock()

    async def capture_invoke(messages):
        captured_prompt.append(messages[0].content)
        return MagicMock(content="KEEP: 1\nDROP: \nREASON: relevant")

    mock_llm.ainvoke = capture_invoke
    with patch("src.agents.filter_agent.create_llm", return_value=mock_llm):
        await filter_items(items, "core mind summary")
    assert captured_prompt
    assert "AI capex update" in captured_prompt[0]
    assert "Big spending on AI" in captured_prompt[0]


@pytest.mark.asyncio
async def test_custom_auto_pass_tier():
    items = [_make_item("a", tier=1), _make_item("b", tier=3), _make_item("c", tier=4)]
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=MagicMock(content="KEEP: 1\nDROP: \nREASON: relevant")
    )
    with patch("src.agents.filter_agent.create_llm", return_value=mock_llm):
        result = await filter_items(items, "summary", auto_pass_tier=3)
    assert len(result.auto_passed) == 2  # tier 1 and 3 auto-passed
    assert result.auto_passed[0].slug == "a"
    assert result.auto_passed[1].slug == "b"


@pytest.mark.asyncio
async def test_reasons_extracted():
    items = [_make_item("a", tier=3)]
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=MagicMock(content="KEEP: 1\nDROP: \nREASON: #1 very relevant to AI theme")
    )
    with patch("src.agents.filter_agent.create_llm", return_value=mock_llm):
        result = await filter_items(items, "summary")
    assert "very relevant to AI theme" in result.reasons


# ---------------------------------------------------------------------------
# _parse_keep_ids tests
# ---------------------------------------------------------------------------


def test_parse_keep_ids_normal():
    assert _parse_keep_ids("KEEP: 1, 3, 5\nDROP: 2, 4", 5) == [1, 3, 5]


def test_parse_keep_ids_empty():
    result = _parse_keep_ids("KEEP: \nDROP: 1, 2, 3", 3)
    assert result == [1, 2, 3]  # safe fallback


def test_parse_keep_ids_malformed():
    result = _parse_keep_ids("some random text without KEEP", 4)
    assert result == [1, 2, 3, 4]  # safe fallback
