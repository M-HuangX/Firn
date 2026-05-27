"""Tests for the divergence tracker."""

import pytest
import yaml

from src.knowledge_base.kb_api import KnowledgeBase
from src.knowledge_base.divergence import (
    check_and_record_divergence,
    get_active_divergences,
    resolve_divergence,
)
from src.knowledge_base.user_input import update_user_view


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kb(tmp_path):
    """Return a KnowledgeBase rooted in a temporary directory with structure created."""
    _kb = KnowledgeBase(kb_root=tmp_path)
    _kb.ensure_structure()
    # Seed source registry (needed by user_input indirectly)
    (tmp_path / "source_registry.yaml").write_text(
        yaml.dump(
            {
                "sources": {
                    "user_opinion": {"tier": 5, "trust": "contextual", "bias": "personal"},
                }
            }
        ),
        encoding="utf-8",
    )
    return _kb


# ---------------------------------------------------------------------------
# check_and_record_divergence
# ---------------------------------------------------------------------------


class TestCheckAndRecordDivergence:
    def test_no_user_view_returns_none(self, kb):
        """No divergence possible when no user view exists."""
        result = check_and_record_divergence(
            ticker="AAPL",
            agent_rating="Buy",
            agent_thesis="Strong fundamentals",
            kb=kb,
        )
        assert result is None

    def test_aligned_views_returns_none(self, kb):
        """No divergence when agent and user agree."""
        update_user_view("NVDA", "Very bullish on AI", "bullish", kb=kb)

        result = check_and_record_divergence(
            ticker="NVDA",
            agent_rating="Buy",
            agent_thesis="AI demand cycle supports growth",
            kb=kb,
        )
        assert result is None

    def test_buy_agent_bearish_user_diverges(self, kb):
        """Divergence: agent says Buy, user is bearish."""
        update_user_view("TSLA", "Overvalued, avoid", "bearish", kb=kb)

        result = check_and_record_divergence(
            ticker="TSLA",
            agent_rating="Buy",
            agent_thesis="Strong growth trajectory",
            kb=kb,
        )
        assert result is not None
        assert result["ticker"] == "TSLA"
        assert result["agent_view"] == "Buy"
        assert result["agent_sentiment"] == "bullish"
        assert result["user_sentiment"] == "bearish"
        assert result["status"] == "Active"

        # Verify it was written to divergences.md
        divs = kb.read_divergences()
        assert "TSLA" in divs
        assert "**Status**: Active" in divs

    def test_sell_agent_bullish_user_diverges(self, kb):
        """Divergence: agent says Sell, user is bullish."""
        update_user_view("AAPL", "Very bullish", "bullish", kb=kb)

        result = check_and_record_divergence(
            ticker="AAPL",
            agent_rating="Sell",
            agent_thesis="Overvalued at current levels",
            kb=kb,
        )
        assert result is not None
        assert result["agent_sentiment"] == "bearish"
        assert result["user_sentiment"] == "bullish"

    def test_overweight_agent_bearish_user_diverges(self, kb):
        """Divergence: agent says Overweight, user is bearish."""
        update_user_view("MSFT", "Don't like the outlook", "bearish", kb=kb)

        result = check_and_record_divergence(
            ticker="MSFT",
            agent_rating="Overweight",
            agent_thesis="Cloud growth strong",
            kb=kb,
        )
        assert result is not None
        assert result["agent_sentiment"] == "bullish"

    def test_underweight_agent_bullish_user_diverges(self, kb):
        """Divergence: agent says Underweight, user is bullish."""
        update_user_view("GME", "Diamond hands!", "bullish", kb=kb)

        result = check_and_record_divergence(
            ticker="GME",
            agent_rating="Underweight",
            agent_thesis="No fundamental support",
            kb=kb,
        )
        assert result is not None
        assert result["agent_sentiment"] == "bearish"
        assert result["user_sentiment"] == "bullish"

    def test_hold_agent_strong_user_sentiment(self, kb):
        """Minor divergence: agent says Hold, user has strong bullish view."""
        update_user_view("AMZN", "Extremely bullish", "bullish", kb=kb)

        result = check_and_record_divergence(
            ticker="AMZN",
            agent_rating="Hold",
            agent_thesis="Fair value at current price",
            kb=kb,
        )
        assert result is not None
        assert result["agent_sentiment"] == "neutral"
        assert result["user_sentiment"] == "bullish"

    def test_hold_agent_neutral_user_no_divergence(self, kb):
        """No divergence when both are neutral."""
        update_user_view("META", "No strong opinion", "neutral", kb=kb)

        result = check_and_record_divergence(
            ticker="META",
            agent_rating="Hold",
            agent_thesis="Fair value",
            kb=kb,
        )
        assert result is None

    def test_multiple_divergences_incremental_numbers(self, kb):
        """Each divergence gets a sequential number."""
        update_user_view("AAPL", "Bearish", "bearish", kb=kb)
        update_user_view("NVDA", "Bearish", "bearish", kb=kb)

        r1 = check_and_record_divergence("AAPL", "Buy", "thesis1", kb=kb)
        r2 = check_and_record_divergence("NVDA", "Buy", "thesis2", kb=kb)

        assert r1["entry_num"] == 1
        assert r2["entry_num"] == 2

    def test_ticker_case_insensitive(self, kb):
        """Ticker lookup should be case-insensitive."""
        update_user_view("aapl", "Bearish", "bearish", kb=kb)

        result = check_and_record_divergence(
            ticker="aapl",
            agent_rating="Buy",
            agent_thesis="test",
            kb=kb,
        )
        assert result is not None
        assert result["ticker"] == "AAPL"


# ---------------------------------------------------------------------------
# resolve_divergence
# ---------------------------------------------------------------------------


class TestResolveDivergence:
    def test_updates_status(self, kb):
        update_user_view("TSLA", "Overvalued", "bearish", kb=kb)
        check_and_record_divergence("TSLA", "Buy", "Growth story", kb=kb)

        success = resolve_divergence(
            ticker="TSLA",
            resolution="Stock dropped 15%, agent was wrong",
            winner="user",
            kb=kb,
        )
        assert success is True

        divs = kb.read_divergences()
        assert "**Status**: Resolved" in divs
        assert "**Winner**: user" in divs
        assert "Stock dropped 15%" in divs

    def test_returns_false_when_no_divergence(self, kb):
        success = resolve_divergence(
            ticker="NVDA",
            resolution="N/A",
            winner="pending",
            kb=kb,
        )
        assert success is False

    def test_returns_false_when_no_divergences_file(self, tmp_path):
        _kb = KnowledgeBase(kb_root=tmp_path)
        _kb.ensure_structure()
        success = resolve_divergence("AAPL", "test", kb=_kb)
        assert success is False

    def test_resolves_only_matching_ticker(self, kb):
        update_user_view("AAPL", "Bearish", "bearish", kb=kb)
        update_user_view("NVDA", "Bearish", "bearish", kb=kb)

        check_and_record_divergence("AAPL", "Buy", "thesis1", kb=kb)
        check_and_record_divergence("NVDA", "Buy", "thesis2", kb=kb)

        resolve_divergence("AAPL", "Resolved for Apple", "agent", kb=kb)

        divs = kb.read_divergences()
        # AAPL should be resolved, NVDA should still be active
        # Check that we have both statuses
        assert "**Winner**: agent" in divs
        # NVDA should still have Active status
        active = get_active_divergences(kb=kb)
        assert len(active) == 1
        assert active[0]["ticker"] == "NVDA"


# ---------------------------------------------------------------------------
# get_active_divergences
# ---------------------------------------------------------------------------


class TestGetActiveDivergences:
    def test_returns_only_active(self, kb):
        update_user_view("AAPL", "Bearish", "bearish", kb=kb)
        update_user_view("NVDA", "Bearish", "bearish", kb=kb)

        check_and_record_divergence("AAPL", "Buy", "thesis1", kb=kb)
        check_and_record_divergence("NVDA", "Overweight", "thesis2", kb=kb)

        # Resolve one
        resolve_divergence("AAPL", "Resolved", "agent", kb=kb)

        active = get_active_divergences(kb=kb)
        assert len(active) == 1
        assert active[0]["ticker"] == "NVDA"
        assert active[0]["status"] == "Active"

    def test_empty_when_no_file(self, tmp_path):
        _kb = KnowledgeBase(kb_root=tmp_path)
        _kb.ensure_structure()
        active = get_active_divergences(kb=_kb)
        assert active == []

    def test_empty_when_all_resolved(self, kb):
        update_user_view("AAPL", "Bearish", "bearish", kb=kb)
        check_and_record_divergence("AAPL", "Buy", "thesis", kb=kb)
        resolve_divergence("AAPL", "Done", "user", kb=kb)

        active = get_active_divergences(kb=kb)
        assert active == []

    def test_returns_correct_fields(self, kb):
        update_user_view("TSLA", "Very bearish", "bearish", kb=kb)
        check_and_record_divergence("TSLA", "Buy", "Growth story", kb=kb)

        active = get_active_divergences(kb=kb)
        assert len(active) == 1
        d = active[0]
        assert d["ticker"] == "TSLA"
        assert d["agent_view"] == "Buy"
        assert d["user_view"] == "bearish"
        assert d["date"]  # should have a date
        assert d["status"] == "Active"
