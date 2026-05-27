"""Tests for KB context injection into the analysis pipeline."""

import pytest
import yaml

from src.knowledge_base.kb_api import KnowledgeBase
from src.knowledge_base.context_injection import (
    load_kb_context,
    format_kb_context_for_summary,
    format_kb_context_for_value,
    _extract_regime_line,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_kb(tmp_path):
    """Return a KnowledgeBase with structure created but no data files."""
    kb = KnowledgeBase(kb_root=tmp_path)
    kb.ensure_structure()
    return kb


@pytest.fixture
def populated_kb(tmp_path):
    """Return a KnowledgeBase populated with sample data."""
    kb = KnowledgeBase(kb_root=tmp_path)
    kb.ensure_structure()

    # Core mind
    kb.write_core_mind(
        "# Core Mind\n"
        "## Market Regime: CAUTIOUS (elevated uncertainty)\n"
        "- Fed holding rates, inflation sticky\n"
        "- Tech sector rotation underway\n"
        "## Active Themes\n"
        "- AI capex cycle\n"
        "- Treasury volatility\n"
    )

    # Themes
    kb.write_theme("ai-capex", "# AI Capex Cycle\nMassive spending on AI infra.")
    kb.write_theme("treasury-vol", "# Treasury Volatility\n10Y yield swinging.")

    # Stock files
    kb.write_stock("AAPL", "thesis", "# AAPL Thesis\nQuality company, fully valued at $190.")
    kb.write_stock("AAPL", "expectations", "# AAPL Expectations\nMarket implies 18% EPS growth.")
    kb.write_stock("AAPL", "predictions", "# AAPL Predictions\n- 2026-04: predicted fair value $175 — actual $192 (missed)")

    # User context
    kb.write_user_views("# User Views\nBullish on NVDA for AI tailwinds.")
    kb.write_divergences("# Divergences\n- TSLA: user bullish, agent neutral (valuation concern)")

    return kb


# ---------------------------------------------------------------------------
# load_kb_context
# ---------------------------------------------------------------------------


class TestLoadKBContext:
    def test_empty_kb_returns_available_true(self, empty_kb):
        """An empty but existing KB should return available=True with None values."""
        ctx = load_kb_context("AAPL", kb=empty_kb)
        assert ctx["available"] is True
        assert ctx["core_mind"] is None
        assert ctx["stock_thesis"] is None
        assert ctx["stock_expectations"] is None
        assert ctx["stock_predictions"] is None
        assert ctx["user_views"] is None
        assert ctx["divergences"] is None
        assert ctx["theme_list"] == []
        assert ctx["principles_summary"]  # should have the default reminder

    def test_populated_kb_returns_filled_values(self, populated_kb):
        """A populated KB should return all expected data."""
        ctx = load_kb_context("AAPL", kb=populated_kb)
        assert ctx["available"] is True
        assert "Core Mind" in ctx["core_mind"]
        assert "AAPL Thesis" in ctx["stock_thesis"]
        assert "18% EPS growth" in ctx["stock_expectations"]
        assert "predicted fair value" in ctx["stock_predictions"]
        assert "NVDA" in ctx["user_views"]
        assert "TSLA" in ctx["divergences"]
        assert sorted(ctx["theme_list"]) == ["ai-capex", "treasury-vol"]
        assert "Epistemic humility" in ctx["principles_summary"]

    def test_nonexistent_kb_path_returns_available_false(self, tmp_path):
        """A KB with a non-existent root should return available=False gracefully."""
        fake_root = tmp_path / "this_does_not_exist"
        kb = KnowledgeBase(kb_root=fake_root)
        ctx = load_kb_context("AAPL", kb=kb)
        assert ctx["available"] is False
        assert ctx["core_mind"] is None

    def test_ticker_case_insensitive(self, populated_kb):
        """Lowercase ticker should work and match uppercase stock files."""
        ctx = load_kb_context("aapl", kb=populated_kb)
        assert ctx["available"] is True
        assert "AAPL Thesis" in ctx["stock_thesis"]

    def test_missing_stock_returns_none(self, populated_kb):
        """A ticker with no KB files should return None for stock fields."""
        ctx = load_kb_context("MSFT", kb=populated_kb)
        assert ctx["available"] is True
        assert ctx["stock_thesis"] is None
        assert ctx["stock_expectations"] is None
        assert ctx["stock_predictions"] is None
        # But core_mind and user context should still be present
        assert ctx["core_mind"] is not None
        assert ctx["user_views"] is not None

    def test_default_kb_no_crash(self):
        """Calling load_kb_context without a KB instance should not crash."""
        # This uses the default KB path, which may or may not exist
        ctx = load_kb_context("AAPL")
        # Should return a valid dict either way
        assert isinstance(ctx, dict)
        assert "available" in ctx
        assert "principles_summary" in ctx


# ---------------------------------------------------------------------------
# format_kb_context_for_summary
# ---------------------------------------------------------------------------


class TestFormatKBContextForSummary:
    def test_full_context_produces_all_sections(self, populated_kb):
        ctx = load_kb_context("AAPL", kb=populated_kb)
        result = format_kb_context_for_summary(ctx, "AAPL")

        assert "## KNOWLEDGE BASE CONTEXT" in result
        assert "### Agent's Current World View (Core Mind)" in result
        assert "### Previous Analysis of AAPL" in result
        assert "### Previous Implied Expectations for AAPL" in result
        assert "### Past Predictions for AAPL" in result
        assert "### User's Investment Views" in result
        assert "### Agent-User Divergences" in result
        assert "### Agent Principles Reminder" in result

    def test_empty_context_returns_empty_string(self, empty_kb):
        ctx = load_kb_context("AAPL", kb=empty_kb)
        result = format_kb_context_for_summary(ctx, "AAPL")
        # Only principles_summary is set, so it should still produce output
        assert "### Agent Principles Reminder" in result

    def test_unavailable_returns_empty_string(self):
        ctx = {"available": False}
        result = format_kb_context_for_summary(ctx, "AAPL")
        assert result == ""

    def test_partial_context_only_includes_present_sections(self, empty_kb):
        """If only core_mind exists, only that section should appear."""
        empty_kb.write_core_mind("# Core\nRISK-ON regime")
        ctx = load_kb_context("AAPL", kb=empty_kb)
        result = format_kb_context_for_summary(ctx, "AAPL")
        assert "### Agent's Current World View" in result
        assert "### Previous Analysis of AAPL" not in result
        assert "### User's Investment Views" not in result


# ---------------------------------------------------------------------------
# format_kb_context_for_value
# ---------------------------------------------------------------------------


class TestFormatKBContextForValue:
    def test_with_expectations_includes_them(self, populated_kb):
        ctx = load_kb_context("AAPL", kb=populated_kb)
        result = format_kb_context_for_value(ctx, "AAPL")
        assert "## KNOWLEDGE BASE CONTEXT" in result
        assert "### Previous Implied Expectations for AAPL" in result
        assert "18% EPS growth" in result

    def test_with_regime_includes_it(self, populated_kb):
        ctx = load_kb_context("AAPL", kb=populated_kb)
        result = format_kb_context_for_value(ctx, "AAPL")
        assert "### Current Market Regime" in result
        assert "CAUTIOUS" in result

    def test_without_expectations_returns_empty(self, empty_kb):
        """No expectations and no core_mind regime -> empty string."""
        ctx = load_kb_context("MSFT", kb=empty_kb)
        result = format_kb_context_for_value(ctx, "MSFT")
        assert result == ""

    def test_unavailable_returns_empty(self):
        ctx = {"available": False}
        result = format_kb_context_for_value(ctx, "AAPL")
        assert result == ""

    def test_does_not_include_user_views(self, populated_kb):
        """Value formatter should NOT include user views or divergences."""
        ctx = load_kb_context("AAPL", kb=populated_kb)
        result = format_kb_context_for_value(ctx, "AAPL")
        assert "User's Investment Views" not in result
        assert "Divergences" not in result
        assert "Principles" not in result


# ---------------------------------------------------------------------------
# _extract_regime_line
# ---------------------------------------------------------------------------


class TestExtractRegimeLine:
    def test_finds_regime_line(self):
        text = "# Core Mind\n## Market Regime: RISK-ON\n- Some detail\n"
        result = _extract_regime_line(text)
        assert result == "Market Regime: RISK-ON"

    def test_case_insensitive(self):
        text = "Current regime is cautious\n"
        result = _extract_regime_line(text)
        assert "cautious" in result

    def test_no_regime_returns_none(self):
        text = "# Core Mind\n- Just some bullets\n- Nothing about market mode\n"
        result = _extract_regime_line(text)
        assert result is None

    def test_empty_string(self):
        assert _extract_regime_line("") is None
