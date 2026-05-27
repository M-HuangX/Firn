"""Tests for Market Snapshot module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.sources.market.snapshot import (
    _fmt_pct,
    _format_row,
    build_market_snapshot,
    fetch_snapshot,
    load_watchlist,
)


class TestLoadWatchlist:
    def test_loads_from_config(self):
        """Real config file should load successfully."""
        result = load_watchlist()
        assert len(result) > 0
        assert "US Indices" in result
        assert "SPY" in result["US Indices"]

    def test_returns_all_categories(self):
        result = load_watchlist()
        assert "Magnificent 7" in result
        assert "Commodities" in result
        assert "Agriculture" in result
        assert "Semiconductors" in result

    def test_missing_file(self, monkeypatch):
        monkeypatch.setattr(
            "src.sources.market.snapshot._WATCHLIST_PATH",
            Path("/nonexistent/path.yaml"),
        )
        result = load_watchlist()
        assert result == {}


class TestFmtPct:
    def test_positive(self):
        assert _fmt_pct(0.025) == "+2.5%"

    def test_negative(self):
        assert _fmt_pct(-0.031) == "-3.1%"

    def test_zero(self):
        assert _fmt_pct(0.0) == "+0.0%"

    def test_none(self):
        assert _fmt_pct(None) == "—"


class TestFormatRow:
    def test_basic_row(self):
        d = {
            "price": 542.30,
            "currency": "USD",
            "change_1d": 0.003,
            "change_1w": -0.012,
            "change_1m": 0.028,
            "week52_pos": 0.78,
        }
        row = _format_row("US Index", "SPY", d)
        assert "US Index" in row
        assert "SPY" in row
        assert "$542.30" in row
        assert "+0.3%" in row
        assert "-1.2%" in row
        assert "+2.8%" in row
        assert "+78.0%" in row

    def test_non_usd_currency(self):
        d = {
            "price": 72500.0,
            "currency": "KRW",
            "change_1d": 0.01,
            "change_1w": None,
            "change_1m": None,
            "week52_pos": 0.5,
        }
        row = _format_row("Semis", "005930.KS", d)
        assert "KRW" in row

    def test_missing_changes(self):
        d = {
            "price": 100.0,
            "currency": "USD",
            "change_1d": None,
            "change_1w": None,
            "change_1m": None,
            "week52_pos": None,
        }
        row = _format_row("Test", "TST", d)
        assert "—" in row


class TestFetchSnapshot:
    @patch("src.sources.market.snapshot._fetch_single")
    def test_returns_data_for_valid_tickers(self, mock_fetch):
        mock_fetch.return_value = {
            "price": 100.0,
            "currency": "USD",
            "change_1d": 0.01,
            "change_1w": 0.02,
            "change_1m": 0.05,
            "week52_pos": 0.7,
            "short_name": "Test",
        }
        result = fetch_snapshot(["AAPL", "MSFT"])
        assert len(result) == 2
        assert result["AAPL"]["price"] == 100.0

    @patch("src.sources.market.snapshot._fetch_single")
    def test_skips_failed_tickers(self, mock_fetch):
        mock_fetch.side_effect = [
            {"price": 100.0, "currency": "USD", "change_1d": 0.01,
             "change_1w": None, "change_1m": None, "week52_pos": None,
             "short_name": "A"},
            None,  # Second ticker fails
        ]
        result = fetch_snapshot(["AAPL", "BAD"])
        assert len(result) == 1
        assert "AAPL" in result

    @patch("src.sources.market.snapshot._fetch_single")
    def test_handles_exception(self, mock_fetch):
        mock_fetch.side_effect = Exception("network error")
        result = fetch_snapshot(["AAPL"])
        assert result == {}


class TestBuildMarketSnapshot:
    @patch("src.sources.market.snapshot.fetch_snapshot")
    def test_builds_markdown_table(self, mock_fetch):
        mock_fetch.return_value = {
            "SPY": {"price": 542.30, "currency": "USD", "change_1d": 0.003,
                    "change_1w": -0.012, "change_1m": 0.028, "week52_pos": 0.78,
                    "short_name": "SPDR S&P 500"},
            "GLD": {"price": 238.50, "currency": "USD", "change_1d": 0.001,
                    "change_1w": 0.021, "change_1m": 0.053, "week52_pos": 0.95,
                    "short_name": "SPDR Gold"},
        }
        result = build_market_snapshot()
        assert "Market Snapshot" in result
        assert "SPY" in result
        assert "GLD" in result
        assert "$542.30" in result

    @patch("src.sources.market.snapshot.fetch_snapshot")
    def test_deduplicates_tracked_tickers(self, mock_fetch):
        """Tracked tickers already in watchlist should not appear in portfolio section."""
        mock_fetch.return_value = {
            "SPY": {"price": 542.0, "currency": "USD", "change_1d": 0.01,
                    "change_1w": None, "change_1m": None, "week52_pos": 0.8,
                    "short_name": "SPY"},
        }
        # SPY is in watchlist AND tracked — should only appear once
        result = build_market_snapshot(tracked_tickers=["SPY"])
        assert result.count("SPY") == 1  # Only in benchmark table

    @patch("src.sources.market.snapshot.fetch_snapshot")
    def test_portfolio_section_for_new_tickers(self, mock_fetch):
        mock_fetch.return_value = {
            "SPY": {"price": 542.0, "currency": "USD", "change_1d": 0.01,
                    "change_1w": None, "change_1m": None, "week52_pos": 0.8,
                    "short_name": "SPY"},
            "CUSTOM": {"price": 50.0, "currency": "USD", "change_1d": -0.02,
                       "change_1w": None, "change_1m": None, "week52_pos": 0.4,
                       "short_name": "Custom Stock"},
        }
        result = build_market_snapshot(tracked_tickers=["CUSTOM"])
        assert "Tracked portfolio" in result
        assert "CUSTOM" in result

    @patch("src.sources.market.snapshot.fetch_snapshot")
    def test_empty_when_no_data(self, mock_fetch):
        mock_fetch.return_value = {}
        result = build_market_snapshot()
        assert result == ""

    @patch("src.sources.market.snapshot.load_watchlist")
    @patch("src.sources.market.snapshot.fetch_snapshot")
    def test_empty_watchlist(self, mock_fetch, mock_watchlist):
        mock_watchlist.return_value = {}
        mock_fetch.return_value = {}
        result = build_market_snapshot()
        assert result == ""
