"""Tests for the user input handler."""

import pytest
import yaml

from src.knowledge_base.kb_api import KnowledgeBase
from src.knowledge_base.user_input import (
    get_user_view_for_ticker,
    process_user_forward,
    update_user_view,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kb(tmp_path):
    """Return a KnowledgeBase rooted in a temporary directory with structure created."""
    _kb = KnowledgeBase(kb_root=tmp_path)
    _kb.ensure_structure()
    # Seed source registry for tier lookups
    (tmp_path / "source_registry.yaml").write_text(
        yaml.dump(
            {
                "sources": {
                    "sec_filings": {"tier": 1, "trust": "unconditional", "bias": "none"},
                    "seeking_alpha": {"tier": 3, "trust": "moderate", "bias": "retail_analytical"},
                    "social_media": {"tier": 4, "trust": "low", "bias": "varies"},
                    "user_forwarded": {"tier": 4, "trust": "low_to_moderate", "bias": "varies"},
                    "user_opinion": {"tier": 5, "trust": "contextual", "bias": "personal"},
                }
            }
        ),
        encoding="utf-8",
    )
    return _kb


# ---------------------------------------------------------------------------
# process_user_forward
# ---------------------------------------------------------------------------


class TestProcessUserForward:
    def test_stores_content_in_forwarded(self, kb):
        result = process_user_forward(
            content="NVDA is going to the moon because of AI demand!",
            kb=kb,
        )
        assert result["slug"]
        assert result["stored_at"]
        # Verify file was created
        stored_content = kb.read_forwarded(result["slug"])
        assert stored_content is not None
        assert "NVDA is going to the moon" in stored_content
        assert "# Forwarded Content" in stored_content

    def test_with_source_lookup(self, kb):
        result = process_user_forward(
            content="Seeking Alpha says AAPL is undervalued",
            source="seeking_alpha",
            kb=kb,
        )
        assert result["source"] == "seeking_alpha"
        assert result["tier"] == 3  # seeking_alpha is Tier 3

        stored = kb.read_forwarded(result["slug"])
        assert "Tier 3" in stored

    def test_with_ticker(self, kb):
        result = process_user_forward(
            content="Article about NVDA growth prospects",
            ticker="nvda",
            kb=kb,
        )
        assert result["ticker"] == "NVDA"

        # Check that user_views was updated with a note
        views = kb.read_user_views()
        assert views is not None
        assert "### NVDA" in views

    def test_default_tier_for_unknown_source(self, kb):
        result = process_user_forward(
            content="Some random content from unknown source",
            source="random_blog",
            kb=kb,
        )
        # Unknown source defaults to Tier 4
        assert result["tier"] == 4

    def test_default_source_is_user_forwarded(self, kb):
        result = process_user_forward(
            content="Content without explicit source",
            kb=kb,
        )
        assert result["source"] == "user_forwarded"
        assert result["tier"] == 4

    def test_slug_format(self, kb):
        result = process_user_forward(
            content="AAPL earnings beat expectations significantly",
            source="twitter",
            kb=kb,
        )
        slug = result["slug"]
        # Slug should start with date and contain source
        assert "twitter" in slug
        assert "aapl" in slug.lower()

    def test_agent_assessment_header(self, kb):
        result = process_user_forward(
            content="Test content",
            source="social_media",
            kb=kb,
        )
        stored = kb.read_forwarded(result["slug"])
        assert "**Agent Assessment**" in stored
        assert "Tier 4" in stored

    def test_no_registry_file(self, tmp_path):
        """Should work even without source_registry.yaml."""
        _kb = KnowledgeBase(kb_root=tmp_path)
        _kb.ensure_structure()
        # No source_registry.yaml seeded
        result = process_user_forward(
            content="Content without registry",
            kb=_kb,
        )
        assert result["tier"] == 4  # fallback default


# ---------------------------------------------------------------------------
# update_user_view
# ---------------------------------------------------------------------------


class TestUpdateUserView:
    def test_creates_new_section(self, kb):
        update_user_view("NVDA", "Very bullish due to AI demand", "bullish", kb=kb)

        views = kb.read_user_views()
        assert views is not None
        assert "### NVDA" in views
        assert "**Sentiment**: Bullish" in views
        assert "Very bullish due to AI demand" in views

    def test_updates_existing_section(self, kb):
        # Create initial view
        update_user_view("AAPL", "Neutral on Apple", "neutral", kb=kb)
        # Update it
        update_user_view("AAPL", "Now bearish after earnings miss", "bearish", kb=kb)

        views = kb.read_user_views()
        assert "### AAPL" in views
        assert "**Sentiment**: Bearish" in views
        assert "Now bearish after earnings miss" in views
        # Old view should be replaced
        assert "Neutral on Apple" not in views

    def test_preserves_other_tickers(self, kb):
        update_user_view("AAPL", "Bullish on Apple", "bullish", kb=kb)
        update_user_view("NVDA", "Bearish on NVDA", "bearish", kb=kb)
        # Update only AAPL
        update_user_view("AAPL", "Changed to neutral", "neutral", kb=kb)

        views = kb.read_user_views()
        assert "### AAPL" in views
        assert "### NVDA" in views
        assert "Changed to neutral" in views
        assert "Bearish on NVDA" in views

    def test_invalid_sentiment_defaults_to_neutral(self, kb):
        update_user_view("TSLA", "Some view", "invalid_sentiment", kb=kb)

        views = kb.read_user_views()
        assert "**Sentiment**: Neutral" in views

    def test_ticker_normalized_to_uppercase(self, kb):
        update_user_view("aapl", "Test view", "bullish", kb=kb)

        views = kb.read_user_views()
        assert "### AAPL" in views


# ---------------------------------------------------------------------------
# get_user_view_for_ticker
# ---------------------------------------------------------------------------


class TestGetUserViewForTicker:
    def test_returns_correct_view(self, kb):
        update_user_view("NVDA", "Very bullish on AI", "bullish", kb=kb)

        view = get_user_view_for_ticker("NVDA", kb=kb)
        assert view is not None
        assert view["ticker"] == "NVDA"
        assert view["sentiment"] == "bullish"
        assert view["view"] == "Very bullish on AI"
        assert view["updated_date"]  # should be a date string

    def test_returns_none_when_no_view(self, kb):
        view = get_user_view_for_ticker("MSFT", kb=kb)
        assert view is None

    def test_returns_none_when_no_views_file(self, tmp_path):
        _kb = KnowledgeBase(kb_root=tmp_path)
        _kb.ensure_structure()
        view = get_user_view_for_ticker("AAPL", kb=_kb)
        assert view is None

    def test_extracts_correct_ticker_from_multiple(self, kb):
        update_user_view("AAPL", "Neutral on Apple", "neutral", kb=kb)
        update_user_view("NVDA", "Bullish on NVDA", "bullish", kb=kb)
        update_user_view("TSLA", "Bearish on Tesla", "bearish", kb=kb)

        nvda = get_user_view_for_ticker("NVDA", kb=kb)
        assert nvda is not None
        assert nvda["sentiment"] == "bullish"
        assert nvda["view"] == "Bullish on NVDA"

        tsla = get_user_view_for_ticker("TSLA", kb=kb)
        assert tsla is not None
        assert tsla["sentiment"] == "bearish"

    def test_ticker_case_insensitive_lookup(self, kb):
        update_user_view("AAPL", "Test view", "bullish", kb=kb)

        view = get_user_view_for_ticker("aapl", kb=kb)
        assert view is not None
        assert view["ticker"] == "AAPL"
