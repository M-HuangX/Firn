"""Tests for the market news fetcher pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.knowledge_base.kb_api import KnowledgeBase
from src.sources.market.news import (
    _article_uuid,
    _format_article_body,
    _get_news_list,
    fetch_market_news,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kb(tmp_path):
    """Return a KnowledgeBase rooted in a temp dir with structure + source registry."""
    _kb = KnowledgeBase(kb_root=tmp_path)
    _kb.ensure_structure()
    (tmp_path / "source_registry.yaml").write_text(
        yaml.dump(
            {
                "sources": {
                    "market_news_yfinance": {
                        "human_tier": 3,
                        "trust": "moderate",
                        "bias": "aggregated",
                    },
                    "stock_news_yfinance": {
                        "human_tier": 3,
                        "trust": "moderate",
                        "bias": "aggregated",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    return _kb


def _make_article(
    title: str = "Test Article",
    publisher: str = "Reuters",
    uuid: str = "abc-123",
    link: str = "https://example.com/article",
    pub_time: int = 1715788800,  # 2024-05-15 16:00 UTC
    related_tickers: list[str] | None = None,
) -> dict:
    """Create a synthetic yfinance news article dict."""
    art = {
        "title": title,
        "publisher": publisher,
        "uuid": uuid,
        "link": link,
        "providerPublishTime": pub_time,
    }
    if related_tickers is not None:
        art["relatedTickers"] = related_tickers
    return art


# ---------------------------------------------------------------------------
# _article_uuid
# ---------------------------------------------------------------------------


class TestArticleUuid:
    def test_uses_uuid_field(self):
        assert _article_uuid({"uuid": "abc-123", "title": "Test"}) == "abc-123"

    def test_uses_id_field(self):
        assert _article_uuid({"id": "def-456", "title": "Test"}) == "def-456"

    def test_falls_back_to_title_hash(self):
        uid = _article_uuid({"title": "Some Article"})
        assert len(uid) == 16  # sha256 hex prefix

    def test_empty_article(self):
        uid = _article_uuid({})
        assert isinstance(uid, str)
        assert len(uid) > 0


# ---------------------------------------------------------------------------
# _get_news_list
# ---------------------------------------------------------------------------


class TestGetNewsList:
    def test_list_return(self):
        ticker = MagicMock()
        ticker.news = [{"title": "A"}]
        assert _get_news_list(ticker) == [{"title": "A"}]

    def test_dict_with_news_key(self):
        ticker = MagicMock()
        ticker.news = {"news": [{"title": "B"}]}
        assert _get_news_list(ticker) == [{"title": "B"}]

    def test_none_return(self):
        ticker = MagicMock()
        ticker.news = None
        assert _get_news_list(ticker) == []

    def test_attribute_error(self):
        ticker = MagicMock(spec=[])  # no .news attribute
        assert _get_news_list(ticker) == []

    def test_empty_list(self):
        ticker = MagicMock()
        ticker.news = []
        assert _get_news_list(ticker) == []

    def test_dict_without_news_key(self):
        ticker = MagicMock()
        ticker.news = {"other": "data"}
        assert _get_news_list(ticker) == []


# ---------------------------------------------------------------------------
# _format_article_body
# ---------------------------------------------------------------------------


class TestFormatArticleBody:
    def test_full_article(self):
        article = _make_article(related_tickers=["AAPL", "MSFT"])
        body = _format_article_body(article)
        assert "**Test Article**" in body
        assert "Reuters" in body
        assert "https://example.com/article" in body
        assert "AAPL" in body
        assert "MSFT" in body

    def test_missing_fields(self):
        body = _format_article_body({})
        assert "(no title)" in body
        assert "Unknown" in body

    def test_string_date(self):
        article = {"title": "Test", "providerPublishTime": None, "publishedDate": "2026-05-15"}
        body = _format_article_body(article)
        assert "2026-05-15" in body


# ---------------------------------------------------------------------------
# fetch_market_news — happy path
# ---------------------------------------------------------------------------


class TestFetchMarketNews:
    @patch("yfinance.Ticker")
    def test_happy_path_spy_news(self, MockTicker, kb):
        """SPY news should create inbox items."""
        articles = [
            _make_article("Market Rally", "AP", "u1"),
            _make_article("Fed Minutes", "Reuters", "u2"),
        ]

        spy_ticker = MagicMock()
        spy_ticker.news = articles
        MockTicker.return_value = spy_ticker

        result = fetch_market_news(kb=kb, max_articles=10)

        assert result["status"] == "ok"
        assert result["total_created"] == 2
        assert result["market_count"] == 2

        pending = kb.list_unread()
        assert len(pending) == 2

        # Verify frontmatter
        content = kb.read_unread(pending[0])
        assert "source: market_news_yfinance" in content
        assert "tier: 3" in content
        assert "content_type: news" in content

    @patch("yfinance.Ticker")
    def test_watchlist_tickers_also_fetched(self, MockTicker, kb):
        """Stock-specific news should be fetched for watched tickers."""
        # Create a watched ticker directory
        (kb.root / "notebook" / "stocks" / "AAPL").mkdir(parents=True)

        spy_articles = [_make_article("Market Up", "AP", "spy1")]
        aapl_articles = [_make_article("AAPL Earnings", "CNBC", "aapl1")]

        def make_ticker(symbol):
            t = MagicMock()
            if symbol == "SPY":
                t.news = spy_articles
            elif symbol == "AAPL":
                t.news = aapl_articles
            else:
                t.news = []
            return t

        MockTicker.side_effect = make_ticker

        result = fetch_market_news(kb=kb)

        assert result["total_created"] == 2
        assert result["market_count"] == 1
        assert result["ticker_counts"] == {"AAPL": 1}

        # Check that stock-specific item has correct source
        pending = kb.list_unread()
        found_stock_source = False
        for slug in pending:
            content = kb.read_unread(slug)
            if "source: stock_news_yfinance" in content:
                found_stock_source = True
                assert "ticker: AAPL" in content
                assert "stock-news" in content
        assert found_stock_source

    @patch("yfinance.Ticker")
    def test_empty_news_list(self, MockTicker, kb):
        """Empty news list should not crash."""
        spy = MagicMock()
        spy.news = []
        MockTicker.return_value = spy

        result = fetch_market_news(kb=kb)

        assert result["total_created"] == 0
        assert kb.list_unread() == []

    @patch("yfinance.Ticker")
    def test_yfinance_error_handled(self, MockTicker, kb):
        """yfinance error should be caught gracefully."""
        MockTicker.side_effect = Exception("yfinance timeout")

        result = fetch_market_news(kb=kb)

        assert result["total_created"] == 0
        assert len(result["errors"]) > 0

    @patch("yfinance.Ticker")
    def test_dedup_same_articles(self, MockTicker, kb):
        """Same articles should not be re-added on second call."""
        articles = [_make_article("Same News", "AP", "same-uuid")]
        spy = MagicMock()
        spy.news = articles
        MockTicker.return_value = spy

        # First call
        result1 = fetch_market_news(kb=kb)
        assert result1["total_created"] == 1

        # Second call — same articles
        result2 = fetch_market_news(kb=kb)
        assert result2["total_created"] == 0

    @patch("yfinance.Ticker")
    def test_dedup_new_articles_pass(self, MockTicker, kb):
        """New articles with different UUIDs should be added."""
        spy = MagicMock()

        # First call
        spy.news = [_make_article("Old News", "AP", "old-uuid")]
        MockTicker.return_value = spy
        fetch_market_news(kb=kb)

        # Second call with new article
        spy.news = [
            _make_article("Old News", "AP", "old-uuid"),
            _make_article("New News", "Reuters", "new-uuid"),
        ]
        MockTicker.return_value = spy
        result = fetch_market_news(kb=kb)

        assert result["total_created"] == 1
        assert result["market_count"] == 1

    @patch("yfinance.Ticker")
    def test_max_articles_limit(self, MockTicker, kb):
        """Should respect max_articles limit."""
        articles = [_make_article(f"Article {i}", "AP", f"uuid-{i}") for i in range(20)]
        spy = MagicMock()
        spy.news = articles
        MockTicker.return_value = spy

        result = fetch_market_news(kb=kb, max_articles=5)

        assert result["total_created"] == 5
        assert result["market_count"] == 5

    @patch("yfinance.Ticker")
    def test_freshness_tracking(self, MockTicker, kb):
        """Should record freshness after fetch."""
        spy = MagicMock()
        spy.news = [_make_article("News", "AP", "u1")]
        MockTicker.return_value = spy

        fetch_market_news(kb=kb)

        lu = kb.get_last_updated()
        assert "market_news_yfinance" in lu
        entry = lu["market_news_yfinance"]
        assert entry["new_count"] == 1
        assert "1 articles" in entry["summary"]

    @patch("yfinance.Ticker")
    def test_none_news_return(self, MockTicker, kb):
        """ticker.news returning None should be handled."""
        spy = MagicMock()
        spy.news = None
        MockTicker.return_value = spy

        result = fetch_market_news(kb=kb)

        assert result["total_created"] == 0
        assert result["errors"] == []

    @patch("yfinance.Ticker")
    def test_dict_format_news(self, MockTicker, kb):
        """ticker.news returning dict with 'news' key should work."""
        spy = MagicMock()
        spy.news = {"news": [_make_article("Dict News", "AP", "dict-u1")]}
        MockTicker.return_value = spy

        result = fetch_market_news(kb=kb)

        assert result["total_created"] == 1

    @patch("yfinance.Ticker")
    def test_per_ticker_error_isolation(self, MockTicker, kb):
        """Error on one ticker should not block others."""
        (kb.root / "notebook" / "stocks" / "AAPL").mkdir(parents=True)
        (kb.root / "notebook" / "stocks" / "MSFT").mkdir(parents=True)

        call_count = [0]

        def make_ticker(symbol):
            call_count[0] += 1
            if symbol == "SPY":
                t = MagicMock()
                t.news = [_make_article("SPY News", "AP", "spy1")]
                return t
            elif symbol == "AAPL":
                raise Exception("AAPL fetch failed")
            elif symbol == "MSFT":
                t = MagicMock()
                t.news = [_make_article("MSFT News", "Reuters", "msft1")]
                return t
            t = MagicMock()
            t.news = []
            return t

        MockTicker.side_effect = make_ticker

        result = fetch_market_news(kb=kb)

        assert result["total_created"] == 2  # SPY + MSFT
        assert len(result["errors"]) == 1
        assert "AAPL" in result["errors"][0]

    @patch("yfinance.Ticker")
    def test_article_title_in_inbox(self, MockTicker, kb):
        """Article title should appear in the inbox item title."""
        spy = MagicMock()
        spy.news = [_make_article("Fed Raises Rates", "AP", "fed1")]
        MockTicker.return_value = spy

        fetch_market_news(kb=kb)

        pending = kb.list_unread()
        assert len(pending) == 1
        content = kb.read_unread(pending[0])
        assert "title: Fed Raises Rates" in content

    @patch("yfinance.Ticker")
    def test_no_watched_tickers(self, MockTicker, kb):
        """No watched tickers should still fetch SPY news."""
        spy = MagicMock()
        spy.news = [_make_article("Market News", "AP", "m1")]
        MockTicker.return_value = spy

        result = fetch_market_news(kb=kb)

        assert result["total_created"] == 1
        assert result["ticker_counts"] == {}

    @patch("yfinance.Ticker")
    def test_seen_uuids_persisted(self, MockTicker, kb):
        """Seen UUIDs should be persisted in last_updated."""
        spy = MagicMock()
        spy.news = [_make_article("News A", "AP", "persist-uuid")]
        MockTicker.return_value = spy

        fetch_market_news(kb=kb)

        lu = kb.get_last_updated()
        entry = lu["market_news_yfinance"]
        assert "seen_uuids" in entry
        assert "persist-uuid" in entry["seen_uuids"]


# ---------------------------------------------------------------------------
# Integration: refresh_pipeline calls news fetch
# ---------------------------------------------------------------------------


class TestRefreshPipelineNewsIntegration:
    @patch("yfinance.Ticker")
    @patch("src.sources.refresh_pipeline._run_macro_pulse")
    @patch("src.sources.refresh_pipeline._run_watchlist_check")
    @patch("src.sources.refresh_pipeline.WechatSourceManager")
    def test_refresh_calls_news_fetch(self, MockManager, mock_watchlist, mock_pulse, MockTicker, kb):
        """refresh_sources should call news fetch."""
        mock_instance = MockManager.return_value
        mock_instance.accounts = []
        mock_instance.refresh_all.return_value = {}
        mock_pulse.return_value = {"status": "skipped"}
        mock_watchlist.return_value = {"status": "ok", "total_events": 0}

        spy = MagicMock()
        spy.news = [_make_article("Test", "AP", "rf1")]
        MockTicker.return_value = spy

        with patch("src.sources.refresh_pipeline.KnowledgeBase", return_value=kb):
            from src.sources.refresh_pipeline import refresh_sources
            result = refresh_sources()

        assert "news_fetch" in result

    @patch("src.sources.refresh_pipeline._run_news_fetch")
    @patch("src.sources.refresh_pipeline._run_macro_pulse")
    @patch("src.sources.refresh_pipeline._run_watchlist_check")
    @patch("src.sources.refresh_pipeline.WechatSourceManager")
    def test_news_failure_does_not_block(self, MockManager, mock_watchlist, mock_pulse, mock_news, kb):
        """News fetch errors should not prevent other results from returning."""
        mock_instance = MockManager.return_value
        mock_instance.accounts = []
        mock_instance.refresh_all.return_value = {}
        mock_pulse.return_value = {"status": "skipped"}
        mock_news.return_value = {"status": "error", "reason": "boom"}
        mock_watchlist.return_value = {"status": "ok", "total_events": 0}

        with patch("src.sources.refresh_pipeline.KnowledgeBase", return_value=kb):
            from src.sources.refresh_pipeline import refresh_sources
            result = refresh_sources()

        assert result["news_fetch"]["status"] == "error"
        assert result["new_articles"] == 0
