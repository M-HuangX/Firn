"""Tests for the perception agent (inbox processing pipeline)."""

from __future__ import annotations

import yaml
import pytest

from src.knowledge_base.kb_api import KnowledgeBase
from src.knowledge_base.perception import (
    InboxItem,
    _has_cjk,
    add_to_inbox,
    parse_inbox_item,
    process_inbox,
    route_item,
    _slugify,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kb(tmp_path):
    """Return a KnowledgeBase rooted in a temp dir with structure + source registry."""
    _kb = KnowledgeBase(kb_root=tmp_path)
    _kb.ensure_structure()
    # Seed source registry for tier auto-resolution
    (tmp_path / "source_registry.yaml").write_text(
        yaml.dump(
            {
                "sources": {
                    "sec_filings": {"tier": 1, "trust": "unconditional", "bias": "none"},
                    "fred_api": {"tier": 1, "trust": "unconditional", "bias": "none"},
                    "analyst_ratings": {"tier": 2, "trust": "moderate_high", "bias": "sell_side"},
                    "finnhub_news": {"tier": 3, "trust": "moderate", "bias": "aggregated"},
                    "social_media": {"tier": 4, "trust": "low", "bias": "varies"},
                    "user_forwarded": {"tier": 4, "trust": "low_to_moderate", "bias": "varies"},
                    "user_opinion": {"tier": 5, "trust": "contextual", "bias": "personal"},
                }
            }
        ),
        encoding="utf-8",
    )
    return _kb


def _make_inbox_content(
    source: str = "finnhub_news",
    tier: int = 3,
    content_type: str = "news",
    ticker: str | None = None,
    title: str = "Test headline",
    tags: str = "",
    body: str = "This is the body content.",
) -> str:
    """Helper to build a frontmatter-formatted inbox item."""
    lines = ["---", f"source: {source}", f"tier: {tier}", f"content_type: {content_type}"]
    if ticker:
        lines.append(f"ticker: {ticker}")
    lines.append(f"title: {title}")
    if tags:
        lines.append(f"tags: {tags}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# parse_inbox_item
# ---------------------------------------------------------------------------


class TestParseInboxItem:
    def test_valid_frontmatter(self):
        content = _make_inbox_content(
            source="fred_api",
            tier=1,
            content_type="market_data",
            ticker="SPY",
            title="Treasury yields rise",
            tags="macro, rates",
            body="10Y yield hit 4.5%.",
        )
        item = parse_inbox_item("test-slug", content)
        assert item is not None
        assert item.slug == "test-slug"
        assert item.source == "fred_api"
        assert item.tier == 1
        assert item.content_type == "market_data"
        assert item.ticker == "SPY"
        assert item.title == "Treasury yields rise"
        assert item.tags == ["macro", "rates"]
        assert item.body == "10Y yield hit 4.5%."
        assert item.raw == content

    def test_missing_optional_fields_use_defaults(self):
        content = "---\nsource: unknown_src\n---\nSome body text."
        item = parse_inbox_item("minimal", content)
        assert item is not None
        assert item.source == "unknown_src"
        assert item.tier == 3  # default
        assert item.content_type == "news"  # default
        assert item.ticker is None
        assert item.title == "minimal"  # falls back to slug
        assert item.tags == []
        assert item.body == "Some body text."

    def test_no_frontmatter_returns_none(self):
        content = "No frontmatter here.\nJust plain text."
        assert parse_inbox_item("nope", content) is None

    def test_no_closing_frontmatter_returns_none(self):
        content = "---\nsource: test\nNo closing marker"
        assert parse_inbox_item("nope", content) is None

    def test_invalid_tier_uses_default(self):
        content = "---\nsource: test\ntier: abc\n---\nBody."
        item = parse_inbox_item("bad-tier", content)
        assert item is not None
        assert item.tier == 3

    def test_invalid_content_type_uses_default(self):
        content = "---\nsource: test\ncontent_type: garbage\n---\nBody."
        item = parse_inbox_item("bad-type", content)
        assert item is not None
        assert item.content_type == "news"

    def test_ticker_uppercased(self):
        content = "---\nsource: test\nticker: aapl\n---\nBody."
        item = parse_inbox_item("ticker-case", content)
        assert item is not None
        assert item.ticker == "AAPL"

    def test_title_en_parsed_from_frontmatter(self):
        content = (
            "---\n"
            "source: bilibili\n"
            "title: \u59dc\u6c41\u6c7d\u6c34\n"
            "title_en: Ginger Soda\n"
            "---\n"
            "Body."
        )
        item = parse_inbox_item("cn-item", content)
        assert item is not None
        assert item.title_en == "Ginger Soda"

    def test_title_en_defaults_empty_when_absent(self):
        content = "---\nsource: test\ntitle: Hello\n---\nBody."
        item = parse_inbox_item("no-en", content)
        assert item is not None
        assert item.title_en == ""

    def test_empty_frontmatter_still_parses(self):
        content = "---\n---\nBody only."
        item = parse_inbox_item("empty-front", content)
        assert item is not None
        assert item.source == "unknown"
        assert item.body == "Body only."


# ---------------------------------------------------------------------------
# route_item
# ---------------------------------------------------------------------------


class TestRouteItem:
    def test_tier1_event_routes_to_events(self, kb):
        item = InboxItem(
            slug="fed-rate-2026-05",
            source="fred_api",
            tier=1,
            content_type="event",
            ticker=None,
            title="Fed holds rates",
            body="Fed kept rates at 5.25%.",
            tags=["macro"],
            raw="",
        )
        result = route_item(item, kb)
        assert result["action"] == "stored_as_event"
        assert "events/" in result["location"]
        # Verify file was written
        assert kb.read_event("fed-rate-2026-05") is not None
        stored = kb.read_event("fed-rate-2026-05")
        assert "Source**: fred_api (Tier 1)" in stored
        assert "Fed kept rates" in stored

    def test_tier1_market_data_routes_to_events(self, kb):
        item = InboxItem(
            slug="spy-close-2026-05",
            source="market_prices",
            tier=1,
            content_type="market_data",
            ticker="SPY",
            title="SPY closes at 530",
            body="SPY closed at $530.",
            tags=[],
            raw="",
        )
        result = route_item(item, kb)
        assert result["action"] == "stored_as_event"
        assert "events/" in result["location"]

    def test_tier2_analysis_routes_to_themes(self, kb):
        item = InboxItem(
            slug="ai-capex-analysis",
            source="analyst_ratings",
            tier=2,
            content_type="analysis",
            ticker=None,
            title="AI capex trends Q2 2026",
            body="Analysis of hyperscaler capex spending.",
            tags=["ai", "capex"],
            raw="",
        )
        result = route_item(item, kb)
        assert result["action"] == "stored_as_theme"
        assert "themes/" in result["location"]
        assert kb.read_theme("ai-capex-analysis") is not None

    def test_tier3_news_routes_to_events(self, kb):
        item = InboxItem(
            slug="nvda-earnings",
            source="finnhub_news",
            tier=3,
            content_type="news",
            ticker="NVDA",
            title="NVDA beats earnings",
            body="NVDA reported EPS $6.12.",
            tags=["earnings"],
            raw="",
        )
        result = route_item(item, kb)
        assert result["action"] == "stored_as_event"
        assert "events/" in result["location"]
        stored = kb.read_event("nvda-earnings")
        assert "Ticker**: NVDA" in stored

    def test_tier4_content_routes_to_forwarded(self, kb):
        item = InboxItem(
            slug="reddit-tsla-post",
            source="social_media",
            tier=4,
            content_type="news",
            ticker="TSLA",
            title="Reddit says TSLA to the moon",
            body="Everyone on WSB is bullish.",
            tags=["social"],
            raw="",
        )
        result = route_item(item, kb)
        assert result["action"] == "stored_as_forwarded"
        assert "forwarded/" in result["location"]
        assert kb.read_forwarded("reddit-tsla-post") is not None

    def test_tier5_user_opinion_routes_to_forwarded(self, kb):
        item = InboxItem(
            slug="user-aapl-view",
            source="user_opinion",
            tier=5,
            content_type="user_content",
            ticker="AAPL",
            title="I think AAPL is undervalued",
            body="Based on my gut feeling.",
            tags=[],
            raw="",
        )
        result = route_item(item, kb)
        assert result["action"] == "stored_as_forwarded"
        assert "forwarded/" in result["location"]

    def test_user_content_type_always_routes_to_forwarded(self, kb):
        """Even if tier is 1, user_content goes to forwarded."""
        item = InboxItem(
            slug="user-note",
            source="test",
            tier=1,
            content_type="user_content",
            ticker=None,
            title="User note",
            body="A personal note.",
            tags=[],
            raw="",
        )
        result = route_item(item, kb)
        assert result["action"] == "stored_as_forwarded"

    def test_formatted_body_has_source_attribution(self, kb):
        item = InboxItem(
            slug="test-attribution",
            source="reuters_bloomberg",
            tier=2,
            content_type="news",
            ticker="MSFT",
            title="MSFT AI revenue",
            body="Microsoft AI revenue grew 50%.",
            tags=["ai", "revenue"],
            raw="",
        )
        route_item(item, kb)
        stored = kb.read_event("test-attribution")
        assert "# MSFT AI revenue" in stored
        assert "**Source**: reuters_bloomberg (Tier 2)" in stored
        assert "**Ticker**: MSFT" in stored
        assert "**Tags**: ai, revenue" in stored
        assert "Microsoft AI revenue grew 50%." in stored


# ---------------------------------------------------------------------------
# process_inbox
# ---------------------------------------------------------------------------


class TestProcessInbox:
    def test_empty_inbox_returns_empty(self, kb):
        results = process_inbox(kb)
        assert results == []

    def test_processes_all_items(self, kb):
        # Add two items
        kb.add_unread(
            "item-1",
            _make_inbox_content(
                source="fred_api", tier=1, content_type="event",
                title="GDP release", body="GDP grew 2.5%."
            ),
        )
        kb.add_unread(
            "item-2",
            _make_inbox_content(
                source="finnhub_news", tier=3, content_type="news",
                ticker="AAPL", title="AAPL launch event", body="Apple announced new product."
            ),
        )

        results = process_inbox(kb)
        assert len(results) == 2
        slugs = {r["slug"] for r in results}
        assert slugs == {"item-1", "item-2"}

        # Both should have been moved to processed
        assert kb.list_unread() == []
        digested_dir = kb.root / "library" / "read"
        digested_files = sorted(p.stem for p in digested_dir.iterdir() if p.suffix == ".md")
        assert "item-1" in digested_files
        assert "item-2" in digested_files

    def test_parse_error_still_moves_to_processed(self, kb):
        # Item with no frontmatter
        kb.add_unread("bad-item", "No frontmatter here, just text.")

        results = process_inbox(kb)
        assert len(results) == 1
        assert results[0]["action"] == "parse_error"
        assert results[0]["location"] is None

        # Should still be moved to processed
        assert kb.list_unread() == []

    def test_logs_summary(self, kb):
        kb.add_unread(
            "log-test",
            _make_inbox_content(source="fred_api", tier=1, content_type="event", body="Data."),
        )
        process_inbox(kb)

        log_path = kb.root / "meta" / "update_log.md"
        assert log_path.is_file()
        log_text = log_path.read_text(encoding="utf-8")
        assert "Perception: processed 1 items" in log_text

    def test_mixed_routing(self, kb):
        """Test that different item types are routed to different locations."""
        kb.add_unread(
            "event-item",
            _make_inbox_content(source="fred_api", tier=1, content_type="event", body="Event."),
        )
        kb.add_unread(
            "analysis-item",
            _make_inbox_content(source="analyst_ratings", tier=2, content_type="analysis", body="Analysis."),
        )
        kb.add_unread(
            "social-item",
            _make_inbox_content(source="social_media", tier=4, content_type="news", body="Tweet."),
        )

        results = process_inbox(kb)
        assert len(results) == 3

        actions = {r["slug"]: r["action"] for r in results}
        assert actions["event-item"] == "stored_as_event"
        assert actions["analysis-item"] == "stored_as_theme"
        assert actions["social-item"] == "stored_as_forwarded"


# ---------------------------------------------------------------------------
# add_to_inbox
# ---------------------------------------------------------------------------


class TestAddToInbox:
    def test_creates_properly_formatted_file(self, kb):
        slug = add_to_inbox(
            content="NVDA beat expectations.",
            source="finnhub_news",
            tier=3,
            content_type="news",
            ticker="NVDA",
            title="NVDA earnings beat",
            tags=["earnings", "technology"],
            kb=kb,
        )

        assert slug is not None
        assert "nvda-earnings-beat" in slug
        # Should be in pending
        assert slug in kb.list_unread()

        # Read and verify content
        content = kb.read_unread(slug)
        assert "source: finnhub_news" in content
        assert "tier: 3" in content
        assert "content_type: news" in content
        assert "ticker: NVDA" in content
        assert "title: NVDA earnings beat" in content
        assert "tags: earnings, technology" in content
        assert "NVDA beat expectations." in content

    def test_auto_resolves_tier_from_registry(self, kb):
        slug = add_to_inbox(
            content="Insider sold 50k shares.",
            source="social_media",  # tier 4 in registry
            content_type="news",
            title="Insider activity",
            kb=kb,
        )

        content = kb.read_unread(slug)
        assert "tier: 4" in content

    def test_unknown_source_defaults_tier_3(self, kb):
        slug = add_to_inbox(
            content="Something.",
            source="unknown_new_source",
            title="Unknown source item",
            kb=kb,
        )

        content = kb.read_unread(slug)
        assert "tier: 3" in content

    def test_explicit_tier_overrides_registry(self, kb):
        slug = add_to_inbox(
            content="Manual tier override.",
            source="social_media",  # registry says tier 4
            tier=2,  # explicit override
            title="Override test",
            kb=kb,
        )

        content = kb.read_unread(slug)
        assert "tier: 2" in content

    def test_slug_has_date_prefix(self, kb):
        slug = add_to_inbox(
            content="Test.",
            source="test",
            title="Date test",
            kb=kb,
        )

        # Should start with YYYY-MM-DD_
        import re
        assert re.match(r"^\d{4}-\d{2}-\d{2}_", slug)

    def test_no_title_uses_source_for_slug(self, kb):
        slug = add_to_inbox(
            content="No title.",
            source="fred_api",
            kb=kb,
        )
        assert "fred-api" in slug or "fred_api" in slug

    def test_invalid_content_type_defaults(self, kb):
        slug = add_to_inbox(
            content="Bad type.",
            source="test",
            content_type="invalid_type",
            title="Bad type test",
            kb=kb,
        )
        content = kb.read_unread(slug)
        assert "content_type: news" in content

    def test_ticker_uppercased(self, kb):
        slug = add_to_inbox(
            content="Lower case ticker.",
            source="test",
            ticker="aapl",
            title="Ticker case test",
            kb=kb,
        )
        content = kb.read_unread(slug)
        assert "ticker: AAPL" in content

    def test_explicit_title_en_written_to_frontmatter(self, kb):
        slug = add_to_inbox(
            content="Body.",
            source="bilibili",
            title="\u59dc\u6c41\u6c7d\u6c34",
            title_en="Ginger Soda",
            kb=kb,
        )
        content = kb.read_unread(slug)
        assert "title_en: Ginger Soda" in content

    def test_explicit_empty_title_en_skips_frontmatter_line(self, kb):
        slug = add_to_inbox(
            content="Body.",
            source="test",
            title="English title",
            title_en="",
            kb=kb,
        )
        content = kb.read_unread(slug)
        assert "title_en" not in content

    def test_english_title_gets_empty_title_en(self, kb):
        """Non-CJK title should not trigger translation; title_en stays empty."""
        slug = add_to_inbox(
            content="Body.",
            source="test",
            title="Pure English Title",
            kb=kb,
        )
        content = kb.read_unread(slug)
        # title_en should not appear (it's empty so omitted from frontmatter)
        assert "title_en" not in content


# ---------------------------------------------------------------------------
# _has_cjk
# ---------------------------------------------------------------------------


class TestHasCjk:
    def test_chinese_text(self):
        assert _has_cjk("\u59dc\u6c41\u6c7d\u6c34") is True

    def test_english_text(self):
        assert _has_cjk("Hello world") is False

    def test_mixed_text(self):
        assert _has_cjk("NVDA \u82f1\u4f1f\u8fbe") is True

    def test_empty_string(self):
        assert _has_cjk("") is False


# ---------------------------------------------------------------------------
# title_en auto-translation + roundtrip
# ---------------------------------------------------------------------------


class TestTitleEnAutoTranslation:
    def test_cjk_title_triggers_translation(self, kb, monkeypatch):
        """CJK title with no explicit title_en should call _translate_single_title."""
        monkeypatch.setattr(
            "src.knowledge_base.perception._translate_single_title",
            lambda title: "Mocked Translation",
        )
        slug = add_to_inbox(
            content="Body.",
            source="wechat_test",
            title="[test] \u52a8\u6001 2026-01-01",
            kb=kb,
        )
        content = kb.read_unread(slug)
        assert "title_en: Mocked Translation" in content
        item = parse_inbox_item(slug, content)
        assert item is not None
        assert item.title_en == "Mocked Translation"

    def test_title_en_with_colon_roundtrips(self, kb):
        """title_en containing colons should survive write→parse roundtrip."""
        slug = add_to_inbox(
            content="Body.",
            source="test",
            title="Test title",
            title_en="Gold: A Deep Dive",
            kb=kb,
        )
        content = kb.read_unread(slug)
        assert "title_en: Gold: A Deep Dive" in content
        item = parse_inbox_item(slug, content)
        assert item is not None
        assert item.title_en == "Gold: A Deep Dive"

    def test_title_en_with_quotes_roundtrips(self, kb):
        """title_en containing quotes should survive write→parse roundtrip."""
        slug = add_to_inbox(
            content="Body.",
            source="test",
            title="Test",
            title_en='The "New Normal" of Markets',
            kb=kb,
        )
        content = kb.read_unread(slug)
        item = parse_inbox_item(slug, content)
        assert item is not None
        assert item.title_en == 'The "New Normal" of Markets'


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_basic(self):
        assert _slugify("NVDA Earnings Beat") == "nvda-earnings-beat"

    def test_special_characters(self):
        assert _slugify("AAPL: 10% Revenue Growth!") == "aapl-10-revenue-growth"

    def test_extra_whitespace(self):
        assert _slugify("  too   many   spaces  ") == "too-many-spaces"

    def test_long_string_truncated(self):
        long_str = "a" * 200
        result = _slugify(long_str)
        assert len(result) <= 80


# ---------------------------------------------------------------------------
# End-to-end: add_to_inbox -> process_inbox
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_add_then_process(self, kb):
        """Full cycle: add to inbox, process, verify routing."""
        slug = add_to_inbox(
            content="Fed raised rates by 25bps.",
            source="fred_api",
            tier=1,
            content_type="event",
            title="Fed rate hike",
            tags=["macro", "rates"],
            kb=kb,
        )

        # Should be pending
        assert slug in kb.list_unread()

        # Process
        results = process_inbox(kb)
        assert len(results) == 1
        assert results[0]["action"] == "stored_as_event"

        # Should no longer be pending
        assert slug not in kb.list_unread()

        # Should be in events
        event = kb.read_event(slug)
        assert event is not None
        assert "Fed raised rates by 25bps." in event
        assert "Source**: fred_api (Tier 1)" in event

    def test_add_user_content_then_process(self, kb):
        """User content should end up in forwarded, not notebook."""
        slug = add_to_inbox(
            content="I think TSLA is going to $500.",
            source="user_opinion",
            tier=5,
            content_type="user_content",
            ticker="TSLA",
            title="User TSLA prediction",
            kb=kb,
        )

        results = process_inbox(kb)
        assert len(results) == 1
        assert results[0]["action"] == "stored_as_forwarded"

        # Should be in forwarded
        forwarded = kb.read_forwarded(slug)
        assert forwarded is not None
        assert "TSLA is going to $500" in forwarded

        # Should NOT be in events or themes
        assert kb.read_event(slug) is None
        assert kb.read_theme(slug) is None
