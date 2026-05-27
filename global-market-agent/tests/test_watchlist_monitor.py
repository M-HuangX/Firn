"""Tests for the watchlist event monitor pipeline."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import yaml

from src.knowledge_base.kb_api import KnowledgeBase
from src.sources.market.watchlist import (
    _check_analyst_actions,
    _check_earnings_date,
    _check_insider_transactions,
    check_watchlist_events,
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
                    "watchlist_monitor": {
                        "human_tier": 2,
                        "trust": "high",
                        "bias": "none",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    return _kb


@pytest.fixture
def kb_with_ticker(kb):
    """KB with one watched ticker (AAPL)."""
    (kb.root / "notebook" / "stocks" / "AAPL").mkdir(parents=True)
    return kb


@pytest.fixture
def now():
    return datetime.now(timezone.utc)


def _make_insider_df(
    text: str = "Purchase",
    value: float = 100_000,
    insider: str = "Tim Cook",
    date_offset_days: int = 5,
) -> pd.DataFrame:
    """Create a synthetic insider transactions DataFrame."""
    date = (datetime.now(timezone.utc) - timedelta(days=date_offset_days)).strftime("%Y-%m-%d")
    return pd.DataFrame([{
        "Insider": insider,
        "Text": text,
        "Value": value,
        "Shares": 1000,
        "Start Date": date,
    }])


def _make_analyst_df(
    action: str = "upgrade",
    firm: str = "Goldman Sachs",
    from_grade: str = "Hold",
    to_grade: str = "Buy",
    date_offset_days: int = 3,
) -> pd.DataFrame:
    """Create a synthetic upgrades/downgrades DataFrame."""
    date = datetime.now(timezone.utc) - timedelta(days=date_offset_days)
    return pd.DataFrame(
        [{
            "Firm": firm,
            "Action": action,
            "FromGrade": from_grade,
            "ToGrade": to_grade,
        }],
        index=pd.DatetimeIndex([date], tz="UTC"),
    )


# ---------------------------------------------------------------------------
# _check_insider_transactions
# ---------------------------------------------------------------------------


class TestCheckInsiderTransactions:
    def test_significant_purchase_creates_event(self, kb, now):
        ticker = MagicMock()
        ticker.insider_transactions = _make_insider_df(
            text="Purchase", value=200_000, insider="Jane Doe"
        )

        events = _check_insider_transactions("AAPL", ticker, kb, now)

        assert len(events) == 1
        assert events[0]["type"] == "insider_purchase"
        assert "AAPL" in events[0]["title"]
        assert "Jane Doe" in events[0]["body"]
        assert "$200,000" in events[0]["body"]

    def test_small_purchase_skipped(self, kb, now):
        """Purchases under $50k should be skipped."""
        ticker = MagicMock()
        ticker.insider_transactions = _make_insider_df(
            text="Purchase", value=10_000
        )

        events = _check_insider_transactions("AAPL", ticker, kb, now)

        assert len(events) == 0

    def test_insider_sale_skipped(self, kb, now):
        """Routine insider sales should be skipped."""
        ticker = MagicMock()
        ticker.insider_transactions = _make_insider_df(
            text="Sale", value=500_000
        )

        events = _check_insider_transactions("AAPL", ticker, kb, now)

        assert len(events) == 0

    def test_old_purchase_skipped(self, kb, now):
        """Purchases older than 30 days should be skipped."""
        ticker = MagicMock()
        ticker.insider_transactions = _make_insider_df(
            text="Purchase", value=200_000, date_offset_days=45
        )

        events = _check_insider_transactions("AAPL", ticker, kb, now)

        assert len(events) == 0

    def test_none_insider_data(self, kb, now):
        """None insider_transactions should return empty."""
        ticker = MagicMock()
        ticker.insider_transactions = None

        events = _check_insider_transactions("AAPL", ticker, kb, now)

        assert events == []

    def test_empty_dataframe(self, kb, now):
        """Empty DataFrame should return empty."""
        ticker = MagicMock()
        ticker.insider_transactions = pd.DataFrame()

        events = _check_insider_transactions("AAPL", ticker, kb, now)

        assert events == []

    def test_attribute_error_handled(self, kb, now):
        """AttributeError on insider_transactions should not crash."""
        ticker = MagicMock(spec=[])  # no insider_transactions attribute

        events = _check_insider_transactions("AAPL", ticker, kb, now)

        assert events == []

    def test_tier_is_1(self, kb, now):
        """Insider events should be tier 1 (SEC filings)."""
        ticker = MagicMock()
        ticker.insider_transactions = _make_insider_df(value=100_000)

        events = _check_insider_transactions("AAPL", ticker, kb, now)

        assert len(events) == 1
        assert events[0]["tier"] == 1


# ---------------------------------------------------------------------------
# _check_analyst_actions
# ---------------------------------------------------------------------------


class TestCheckAnalystActions:
    def test_upgrade_creates_event(self, kb, now):
        ticker = MagicMock()
        ticker.upgrades_downgrades = _make_analyst_df(
            action="upgrade", firm="JPMorgan", from_grade="Hold", to_grade="Buy"
        )

        events = _check_analyst_actions("AAPL", ticker, kb, now)

        assert len(events) == 1
        assert events[0]["type"] == "analyst_action"
        assert "AAPL" in events[0]["title"]
        assert "JPMorgan" in events[0]["body"]
        assert "Hold" in events[0]["body"]
        assert "Buy" in events[0]["body"]

    def test_downgrade_creates_event(self, kb, now):
        ticker = MagicMock()
        ticker.upgrades_downgrades = _make_analyst_df(
            action="downgrade", firm="Morgan Stanley", from_grade="Buy", to_grade="Sell"
        )

        events = _check_analyst_actions("AAPL", ticker, kb, now)

        assert len(events) == 1
        assert "downgrade" in events[0]["title"].lower() or "downgrade" in events[0]["body"].lower()

    def test_reiteration_skipped(self, kb, now):
        """Reiterations (same grade, no action keyword) should be skipped."""
        date = datetime.now(timezone.utc) - timedelta(days=2)
        df = pd.DataFrame(
            [{
                "Firm": "Citi",
                "Action": "main",  # reiteration-like action
                "FromGrade": "Buy",
                "ToGrade": "Buy",  # same grade
            }],
            index=pd.DatetimeIndex([date], tz="UTC"),
        )
        ticker = MagicMock()
        ticker.upgrades_downgrades = df

        events = _check_analyst_actions("AAPL", ticker, kb, now)

        assert len(events) == 0

    def test_old_action_skipped(self, kb, now):
        """Actions older than 7 days should be skipped."""
        ticker = MagicMock()
        ticker.upgrades_downgrades = _make_analyst_df(date_offset_days=10)

        events = _check_analyst_actions("AAPL", ticker, kb, now)

        assert len(events) == 0

    def test_none_data(self, kb, now):
        ticker = MagicMock()
        ticker.upgrades_downgrades = None

        events = _check_analyst_actions("AAPL", ticker, kb, now)

        assert events == []

    def test_empty_dataframe(self, kb, now):
        ticker = MagicMock()
        ticker.upgrades_downgrades = pd.DataFrame()

        events = _check_analyst_actions("AAPL", ticker, kb, now)

        assert events == []

    def test_tier_is_2(self, kb, now):
        """Analyst events should be tier 2."""
        ticker = MagicMock()
        ticker.upgrades_downgrades = _make_analyst_df()

        events = _check_analyst_actions("AAPL", ticker, kb, now)

        assert len(events) == 1
        assert events[0]["tier"] == 2

    def test_initiated_action(self, kb, now):
        """Initiated coverage should be treated as significant."""
        ticker = MagicMock()
        ticker.upgrades_downgrades = _make_analyst_df(
            action="initiated", from_grade="", to_grade="Buy"
        )

        events = _check_analyst_actions("AAPL", ticker, kb, now)

        assert len(events) == 1


# ---------------------------------------------------------------------------
# _check_earnings_date
# ---------------------------------------------------------------------------


class TestCheckEarningsDate:
    def test_upcoming_earnings_creates_event(self, kb, now):
        """Earnings within 14 days should create an event."""
        earnings_date = now + timedelta(days=7)
        ticker = MagicMock()
        ticker.calendar = {"Earnings Date": [earnings_date.isoformat()]}

        events = _check_earnings_date("AAPL", ticker, kb, now)

        assert len(events) == 1
        assert events[0]["type"] == "earnings_upcoming"
        assert "AAPL" in events[0]["title"]
        assert "7 days" in events[0]["title"]

    def test_far_earnings_skipped(self, kb, now):
        """Earnings more than 14 days out should be skipped."""
        earnings_date = now + timedelta(days=30)
        ticker = MagicMock()
        ticker.calendar = {"Earnings Date": [earnings_date.isoformat()]}

        events = _check_earnings_date("AAPL", ticker, kb, now)

        assert len(events) == 0

    def test_past_earnings_skipped(self, kb, now):
        """Past earnings dates should be skipped."""
        earnings_date = now - timedelta(days=5)
        ticker = MagicMock()
        ticker.calendar = {"Earnings Date": [earnings_date.isoformat()]}

        events = _check_earnings_date("AAPL", ticker, kb, now)

        assert len(events) == 0

    def test_none_calendar(self, kb, now):
        ticker = MagicMock()
        ticker.calendar = None

        events = _check_earnings_date("AAPL", ticker, kb, now)

        assert events == []

    def test_empty_dict_calendar(self, kb, now):
        ticker = MagicMock()
        ticker.calendar = {}

        events = _check_earnings_date("AAPL", ticker, kb, now)

        assert events == []

    def test_tier_is_2(self, kb, now):
        """Earnings events should be tier 2."""
        earnings_date = now + timedelta(days=5)
        ticker = MagicMock()
        ticker.calendar = {"Earnings Date": [earnings_date.isoformat()]}

        events = _check_earnings_date("AAPL", ticker, kb, now)

        assert len(events) == 1
        assert events[0]["tier"] == 2

    def test_attribute_error_handled(self, kb, now):
        """AttributeError on .calendar should not crash."""
        ticker = MagicMock(spec=[])

        events = _check_earnings_date("AAPL", ticker, kb, now)

        assert events == []


# ---------------------------------------------------------------------------
# check_watchlist_events (integration)
# ---------------------------------------------------------------------------


class TestCheckWatchlistEvents:
    def test_empty_watchlist(self, kb):
        """No watched tickers should return immediately."""
        # No yfinance mock needed — should return before using it
        result = check_watchlist_events(kb=kb)

        assert result["total_events"] == 0
        assert result["tickers_checked"] == 0

    @patch("yfinance.Ticker")
    def test_insider_purchase_creates_inbox_item(self, MockTicker, kb_with_ticker):
        """Significant insider purchase should create an inbox item."""
        ticker = MagicMock()
        ticker.insider_transactions = _make_insider_df(value=200_000)
        ticker.upgrades_downgrades = None
        ticker.calendar = None
        MockTicker.return_value = ticker

        result = check_watchlist_events(kb=kb_with_ticker)

        assert result["total_events"] >= 1
        assert "AAPL" in result["events_by_ticker"]

        pending = kb_with_ticker.list_unread()
        assert len(pending) >= 1
        content = kb_with_ticker.read_unread(pending[0])
        assert "source: watchlist_monitor" in content
        assert "content_type: event" in content

    @patch("yfinance.Ticker")
    def test_no_events_no_inbox(self, MockTicker, kb_with_ticker):
        """No significant events should create no inbox items."""
        ticker = MagicMock()
        ticker.insider_transactions = None
        ticker.upgrades_downgrades = None
        ticker.calendar = None
        MockTicker.return_value = ticker

        result = check_watchlist_events(kb=kb_with_ticker)

        assert result["total_events"] == 0
        assert kb_with_ticker.list_unread() == []

    @patch("yfinance.Ticker")
    def test_error_per_ticker_isolation(self, MockTicker, kb):
        """Error on one ticker should not block others."""
        (kb.root / "notebook" / "stocks" / "AAPL").mkdir(parents=True)
        (kb.root / "notebook" / "stocks" / "MSFT").mkdir(parents=True)

        def make_ticker(symbol):
            if symbol == "AAPL":
                raise Exception("AAPL lookup failed")
            t = MagicMock()
            t.insider_transactions = _make_insider_df(value=200_000)
            t.upgrades_downgrades = None
            t.calendar = None
            return t

        MockTicker.side_effect = make_ticker

        result = check_watchlist_events(kb=kb)

        # MSFT events should still be captured
        assert result["tickers_checked"] == 2
        assert len(result["errors"]) == 1
        assert "AAPL" in result["errors"][0]

    @patch("yfinance.Ticker")
    def test_freshness_tracking(self, MockTicker, kb_with_ticker):
        """Should record freshness after check."""
        ticker = MagicMock()
        ticker.insider_transactions = None
        ticker.upgrades_downgrades = None
        ticker.calendar = None
        MockTicker.return_value = ticker

        check_watchlist_events(kb=kb_with_ticker)

        lu = kb_with_ticker.get_last_updated()
        assert "watchlist_monitor" in lu
        entry = lu["watchlist_monitor"]
        assert "checked 1 tickers" in entry["summary"]

    @patch("yfinance.Ticker")
    def test_multiple_event_types_per_ticker(self, MockTicker, kb_with_ticker):
        """A ticker with both insider and analyst events should create multiple items."""
        now = datetime.now(timezone.utc)
        earnings_date = now + timedelta(days=5)

        ticker = MagicMock()
        ticker.insider_transactions = _make_insider_df(value=200_000)
        ticker.upgrades_downgrades = _make_analyst_df()
        ticker.calendar = {"Earnings Date": [earnings_date.isoformat()]}
        MockTicker.return_value = ticker

        result = check_watchlist_events(kb=kb_with_ticker)

        assert result["total_events"] >= 2
        events = result["events_by_ticker"].get("AAPL", [])
        assert len(events) >= 2

    @patch("yfinance.Ticker")
    def test_analyst_upgrade_inbox_item(self, MockTicker, kb_with_ticker):
        """Analyst upgrade should create inbox item with correct metadata."""
        ticker = MagicMock()
        ticker.insider_transactions = None
        ticker.upgrades_downgrades = _make_analyst_df(
            action="upgrade", firm="UBS", from_grade="Hold", to_grade="Buy"
        )
        ticker.calendar = None
        MockTicker.return_value = ticker

        check_watchlist_events(kb=kb_with_ticker)

        pending = kb_with_ticker.list_unread()
        assert len(pending) == 1
        content = kb_with_ticker.read_unread(pending[0])
        assert "source: watchlist_monitor" in content
        assert "ticker: AAPL" in content
        assert "UBS" in content

    @patch("yfinance.Ticker")
    def test_earnings_inbox_item(self, MockTicker, kb_with_ticker):
        """Upcoming earnings should create inbox item."""
        now = datetime.now(timezone.utc)
        earnings_date = now + timedelta(days=10)

        ticker = MagicMock()
        ticker.insider_transactions = None
        ticker.upgrades_downgrades = None
        ticker.calendar = {"Earnings Date": [earnings_date.isoformat()]}
        MockTicker.return_value = ticker

        check_watchlist_events(kb=kb_with_ticker)

        pending = kb_with_ticker.list_unread()
        assert len(pending) == 1
        content = kb_with_ticker.read_unread(pending[0])
        assert "Earnings" in content
        assert "AAPL" in content


# ---------------------------------------------------------------------------
# Integration: refresh_pipeline calls watchlist check
# ---------------------------------------------------------------------------


class TestRefreshPipelineWatchlistIntegration:
    @patch("src.sources.refresh_pipeline._run_news_fetch")
    @patch("src.sources.refresh_pipeline._run_market_snapshot")
    @patch("src.sources.refresh_pipeline._run_macro_pulse")
    @patch("src.sources.refresh_pipeline._run_watchlist_check")
    @patch("src.sources.refresh_pipeline.WechatSourceManager")
    def test_refresh_calls_watchlist(self, MockManager, mock_watchlist, mock_pulse, mock_snapshot, mock_news, kb):
        """refresh_sources should include watchlist check result."""
        mock_instance = MockManager.return_value
        mock_instance.accounts = []
        mock_instance.refresh_all.return_value = {}
        mock_pulse.return_value = {"status": "skipped"}
        mock_snapshot.return_value = {"status": "skipped"}
        mock_news.return_value = {"status": "ok", "total_created": 0}
        mock_watchlist.return_value = {"status": "ok", "total_events": 2, "tickers_checked": 1}

        with patch("src.sources.refresh_pipeline.KnowledgeBase", return_value=kb):
            from src.sources.refresh_pipeline import refresh_sources
            result = refresh_sources()

        assert "watchlist_check" in result
        assert result["watchlist_check"]["total_events"] == 2
        assert result["inbox_items"] == 2  # watchlist events

    @patch("src.sources.refresh_pipeline._run_news_fetch")
    @patch("src.sources.refresh_pipeline._run_market_snapshot")
    @patch("src.sources.refresh_pipeline._run_macro_pulse")
    @patch("src.sources.refresh_pipeline._run_watchlist_check")
    @patch("src.sources.refresh_pipeline.WechatSourceManager")
    def test_watchlist_failure_does_not_block(self, MockManager, mock_watchlist, mock_pulse, mock_snapshot, mock_news, kb):
        """Watchlist check errors should not prevent other results from returning."""
        mock_instance = MockManager.return_value
        mock_instance.accounts = []
        mock_instance.refresh_all.return_value = {}
        mock_pulse.return_value = {"status": "skipped"}
        mock_snapshot.return_value = {"status": "skipped"}
        mock_news.return_value = {"status": "ok", "total_created": 0}
        mock_watchlist.return_value = {"status": "error", "reason": "crash"}

        with patch("src.sources.refresh_pipeline.KnowledgeBase", return_value=kb):
            from src.sources.refresh_pipeline import refresh_sources
            result = refresh_sources()

        assert result["watchlist_check"]["status"] == "error"
        assert result["new_articles"] == 0
