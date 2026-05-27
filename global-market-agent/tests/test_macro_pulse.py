"""Tests for the macro pulse pipeline (daily macro snapshot generator)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import yaml

from src.knowledge_base.kb_api import KnowledgeBase
from src.sources.market.macro_pulse import (
    _fetch_fred_data,
    _fetch_market_data,
    compute_market_regime,
    format_macro_pulse,
    generate_macro_pulse,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kb(tmp_path):
    """Return a KnowledgeBase rooted in a temp dir with structure + source registry."""
    firn_dir = tmp_path / "firn"
    firn_dir.mkdir()
    _kb = KnowledgeBase(kb_root=firn_dir)
    _kb.ensure_structure()
    (_kb.data_root / "sources").mkdir(parents=True, exist_ok=True)
    (_kb.data_root / "sources" / "source_registry.yaml").write_text(
        yaml.dump(
            {
                "sources": {
                    "macro_pulse": {
                        "human_tier": 1,
                        "trust": "unconditional",
                        "bias": "none",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    return _kb


def _make_sp500_history(current_price: float = 5500.0, days: int = 250) -> pd.DataFrame:
    """Create a synthetic S&P 500 history DataFrame."""
    # Use a fixed Friday to avoid weekend truncation making date count < days
    dates = pd.date_range(end="2026-05-15", periods=days, freq="B")
    # Linearly increasing prices ending at current_price
    start_price = current_price * 0.85
    prices = [start_price + (current_price - start_price) * (i / (days - 1)) for i in range(days)]
    return pd.DataFrame(
        {"Open": prices, "High": prices, "Low": prices, "Close": prices, "Volume": [1e6] * days},
        index=dates,
    )


def _make_vix_history(level: float = 18.0, days: int = 5) -> pd.DataFrame:
    """Create a synthetic VIX history DataFrame."""
    dates = pd.date_range(end="2026-05-15", periods=days, freq="B")
    prices = [level] * days
    return pd.DataFrame(
        {"Open": prices, "High": prices, "Low": prices, "Close": prices, "Volume": [1e6] * days},
        index=dates,
    )


def _make_nasdaq_history(current_price: float = 17500.0, days: int = 5) -> pd.DataFrame:
    """Create a synthetic NASDAQ history DataFrame."""
    dates = pd.date_range(end="2026-05-15", periods=days, freq="B")
    prev = current_price * 0.99
    prices = [prev] * (days - 1) + [current_price]
    return pd.DataFrame(
        {"Open": prices, "High": prices, "Low": prices, "Close": prices, "Volume": [1e6] * days},
        index=dates,
    )


def _make_fred_series(value: float, date_str: str = "2026-05-01") -> pd.Series:
    """Create a simple pandas Series mimicking FRED data."""
    idx = pd.DatetimeIndex([date_str])
    return pd.Series([value], index=idx)


# ---------------------------------------------------------------------------
# compute_market_regime
# ---------------------------------------------------------------------------


class TestComputeMarketRegime:
    def test_risk_on_above_200ma_by_more_than_2pct(self):
        regime, desc = compute_market_regime(sp500_price=5500, sp500_200ma=5000, vix_level=18)
        assert regime == "RISK-ON"
        assert "above 200MA" in desc

    def test_risk_off_below_200ma_by_more_than_2pct(self):
        regime, desc = compute_market_regime(sp500_price=4800, sp500_200ma=5000, vix_level=18)
        assert regime == "RISK-OFF"
        assert "below 200MA" in desc

    def test_cautious_within_2pct_of_200ma(self):
        regime, desc = compute_market_regime(sp500_price=5050, sp500_200ma=5000, vix_level=18)
        assert regime == "CAUTIOUS"
        assert "near 200MA" in desc

    def test_cautious_at_negative_edge(self):
        # -1% is within +-2%
        regime, _ = compute_market_regime(sp500_price=4950, sp500_200ma=5000, vix_level=15)
        assert regime == "CAUTIOUS"

    def test_vix_override_risk_on_to_cautious(self):
        """VIX > 25 should downgrade RISK-ON to CAUTIOUS."""
        regime, desc = compute_market_regime(sp500_price=5500, sp500_200ma=5000, vix_level=28)
        assert regime == "CAUTIOUS"
        assert "downgrading" in desc.lower() or "VIX elevated" in desc

    def test_vix_extreme_override_to_risk_off(self):
        """VIX > 35 should override any regime to RISK-OFF."""
        regime, desc = compute_market_regime(sp500_price=5500, sp500_200ma=5000, vix_level=40)
        assert regime == "RISK-OFF"
        assert "RISK-OFF" in desc

    def test_vix_25_does_not_downgrade_cautious(self):
        """VIX > 25 only overrides RISK-ON, not already-CAUTIOUS."""
        regime, _ = compute_market_regime(sp500_price=5050, sp500_200ma=5000, vix_level=28)
        assert regime == "CAUTIOUS"  # stays CAUTIOUS, not downgraded further

    def test_vix_extreme_overrides_risk_off_already(self):
        """VIX > 35 keeps RISK-OFF when already RISK-OFF."""
        regime, _ = compute_market_regime(sp500_price=4800, sp500_200ma=5000, vix_level=40)
        assert regime == "RISK-OFF"

    def test_unknown_when_no_price_data(self):
        regime, _ = compute_market_regime(sp500_price=None, sp500_200ma=None, vix_level=18)
        assert regime == "UNKNOWN"

    def test_unknown_when_no_200ma(self):
        regime, _ = compute_market_regime(sp500_price=5500, sp500_200ma=None, vix_level=18)
        assert regime == "UNKNOWN"

    def test_vix_only_extreme_no_price_data(self):
        """VIX > 35 with no price data should give RISK-OFF."""
        regime, _ = compute_market_regime(sp500_price=None, sp500_200ma=None, vix_level=40)
        assert regime == "RISK-OFF"

    def test_vix_only_elevated_no_price_data(self):
        """VIX > 25 with no price data should give CAUTIOUS."""
        regime, _ = compute_market_regime(sp500_price=None, sp500_200ma=None, vix_level=28)
        assert regime == "CAUTIOUS"

    def test_none_vix_still_uses_price(self):
        regime, _ = compute_market_regime(sp500_price=5500, sp500_200ma=5000, vix_level=None)
        assert regime == "RISK-ON"

    def test_all_none(self):
        regime, _ = compute_market_regime(sp500_price=None, sp500_200ma=None, vix_level=None)
        assert regime == "UNKNOWN"


# ---------------------------------------------------------------------------
# _fetch_market_data (mocked yfinance)
# ---------------------------------------------------------------------------


class TestFetchMarketData:
    @patch("yfinance.Ticker")
    def test_happy_path(self, MockTicker):
        sp500_hist = _make_sp500_history(5500.0)
        nasdaq_hist = _make_nasdaq_history(17500.0)
        vix_hist = _make_vix_history(18.0)

        def make_ticker(symbol):
            t = MagicMock()
            if symbol == "^GSPC":
                t.history.return_value = sp500_hist
            elif symbol == "^IXIC":
                t.history.return_value = nasdaq_hist
            elif symbol == "^VIX":
                t.history.return_value = vix_hist
            return t

        MockTicker.side_effect = make_ticker

        result = _fetch_market_data()

        assert result["sp500"]["price"] == 5500.0
        assert result["sp500"]["ma200"] is not None
        assert result["nasdaq"]["price"] == 17500.0
        assert result["vix"]["level"] == 18.0
        assert result["regime"] in ("RISK-ON", "CAUTIOUS", "RISK-OFF", "UNKNOWN")
        assert result["errors"] == []

    @patch("yfinance.Ticker")
    def test_sp500_failure_others_ok(self, MockTicker):
        nasdaq_hist = _make_nasdaq_history()
        vix_hist = _make_vix_history()

        def make_ticker(symbol):
            t = MagicMock()
            if symbol == "^GSPC":
                t.history.side_effect = Exception("yfinance timeout")
            elif symbol == "^IXIC":
                t.history.return_value = nasdaq_hist
            elif symbol == "^VIX":
                t.history.return_value = vix_hist
            return t

        MockTicker.side_effect = make_ticker

        result = _fetch_market_data()

        assert result["sp500"] == {}
        assert result["nasdaq"]["price"] is not None
        assert result["vix"]["level"] is not None
        assert any("S&P 500" in e for e in result["errors"])

    @patch("yfinance.Ticker")
    def test_all_indices_fail(self, MockTicker):
        def make_ticker(symbol):
            t = MagicMock()
            t.history.side_effect = Exception("network error")
            return t

        MockTicker.side_effect = make_ticker

        result = _fetch_market_data()

        assert result["sp500"] == {}
        assert result["nasdaq"] == {}
        assert result["vix"] == {}
        assert len(result["errors"]) == 3

    @patch("yfinance.Ticker")
    def test_empty_dataframe(self, MockTicker):
        empty_df = pd.DataFrame()

        def make_ticker(symbol):
            t = MagicMock()
            t.history.return_value = empty_df
            return t

        MockTicker.side_effect = make_ticker

        result = _fetch_market_data()

        assert result["sp500"] == {}
        assert len(result["errors"]) >= 1

    @patch("yfinance.Ticker")
    def test_vix_interpretation_levels(self, MockTicker):
        """Test all VIX interpretation thresholds."""
        for vix_level, expected_fragment in [
            (12.0, "Low fear"),
            (17.0, "Below average"),
            (22.0, "Normal volatility"),
            (30.0, "Elevated fear"),
            (40.0, "Extreme fear"),
        ]:
            vix_hist = _make_vix_history(vix_level)

            def make_ticker(symbol, vh=vix_hist):
                t = MagicMock()
                if symbol == "^VIX":
                    t.history.return_value = vh
                else:
                    t.history.return_value = pd.DataFrame()
                return t

            MockTicker.side_effect = make_ticker

            result = _fetch_market_data()
            if result["vix"]:
                assert expected_fragment in result["vix"]["interpretation"], (
                    f"VIX {vix_level}: expected '{expected_fragment}' in '{result['vix']['interpretation']}'"
                )


# ---------------------------------------------------------------------------
# _fetch_fred_data (mocked fredapi)
# ---------------------------------------------------------------------------


class TestFetchFredData:
    @pytest.fixture(autouse=True)
    def no_fred_cache(self):
        with patch("src.sources.market.macro_pulse._load_fred_cache", return_value=None), \
             patch("src.sources.market.macro_pulse._save_fred_cache"):
            yield

    @patch.dict(os.environ, {"FRED_API_KEY": "test-key-123"})
    @patch("fredapi.Fred")
    def test_happy_path(self, MockFred):
        fred_instance = MockFred.return_value

        def get_series(series_id):
            data_map = {
                "GS10": _make_fred_series(4.25),
                "GS2": _make_fred_series(4.50),
                "GS30": _make_fred_series(4.60),
                "T10Y2Y": _make_fred_series(-0.25),
                "FEDFUNDS": _make_fred_series(5.25),
                "CPIAUCSL": _make_fred_series(3.2),
                "UNRATE": _make_fred_series(4.1),
                "A191RL1Q225SBEA": _make_fred_series(2.5),
            }
            return data_map.get(series_id, pd.Series(dtype=float))

        fred_instance.get_series.side_effect = get_series

        result = _fetch_fred_data()

        assert result is not None
        assert result["yields"]["10Y"] == 4.25
        assert result["yields"]["2Y"] == 4.50
        assert result["yields"]["30Y"] == 4.60
        assert result["spread"]["value_pct"] == -0.25
        assert result["spread"]["status"] == "inverted"
        assert result["indicators"]["fed_funds"]["value"] == 5.25
        assert result["indicators"]["cpi"]["value"] == 3.2
        assert result["indicators"]["unemployment"]["value"] == 4.1
        assert result["indicators"]["gdp"]["value"] == 2.5
        assert result["errors"] == []

    @patch.dict(os.environ, {}, clear=True)
    def test_no_api_key_returns_none(self):
        # Ensure FRED_API_KEY is not set
        os.environ.pop("FRED_API_KEY", None)
        result = _fetch_fred_data()
        assert result is None

    @patch.dict(os.environ, {"FRED_API_KEY": "test-key-123"})
    @patch("fredapi.Fred")
    def test_partial_failure(self, MockFred):
        """Some series succeed, some fail — should still return partial data."""
        fred_instance = MockFred.return_value

        call_count = 0

        def get_series(series_id):
            nonlocal call_count
            call_count += 1
            if series_id == "GS10":
                return _make_fred_series(4.25)
            if series_id == "T10Y2Y":
                return _make_fred_series(0.50)
            raise Exception("FRED rate limit")

        fred_instance.get_series.side_effect = get_series

        result = _fetch_fred_data()

        assert result is not None
        assert result["yields"]["10Y"] == 4.25
        assert "2Y" not in result["yields"]
        assert result["spread"]["status"] == "normal"
        assert len(result["errors"]) > 0

    @patch.dict(os.environ, {"FRED_API_KEY": "test-key-123"})
    @patch("fredapi.Fred")
    def test_yield_spread_statuses(self, MockFred):
        """Test inverted, normal, and flat spread classification."""
        fred_instance = MockFred.return_value

        for spread_val, expected_status in [
            (-0.5, "inverted"),
            (1.5, "normal"),
            (0.05, "flat"),
            (-0.05, "flat"),
        ]:
            fred_instance.get_series.return_value = _make_fred_series(spread_val)

            result = _fetch_fred_data()
            assert result["spread"]["status"] == expected_status, (
                f"Spread {spread_val}: expected '{expected_status}', got '{result['spread']['status']}'"
            )


# ---------------------------------------------------------------------------
# format_macro_pulse
# ---------------------------------------------------------------------------


class TestFormatMacroPulse:
    def test_full_output_with_fred(self):
        market = {
            "sp500": {"price": 5500.0, "change_pct": 0.75, "ma200": 5200.0, "pct_from_200ma": 5.77},
            "nasdaq": {"price": 17500.0, "change_pct": 1.2},
            "vix": {"level": 18.5, "interpretation": "Below average -- calm conditions"},
            "regime": "RISK-ON",
            "regime_description": "Bullish trend",
            "errors": [],
        }
        fred = {
            "yields": {"10Y": 4.25, "2Y": 4.50, "30Y": 4.60},
            "spread": {"value_bp": -25.0, "status": "inverted"},
            "indicators": {
                "fed_funds": {"value": 5.25, "as_of": "2026-05-01", "label": "Fed Funds Rate"},
                "cpi": {"value": 3.2, "as_of": "2026-04-15", "label": "CPI"},
                "unemployment": {"value": 4.1, "as_of": "2026-04-01", "label": "Unemployment Rate"},
                "gdp": {"value": 2.5, "as_of": "2026-03-28", "label": "GDP Growth"},
            },
            "errors": [],
        }

        body = format_macro_pulse("2026-05-15", market, fred)

        assert "# Macro Pulse -- 2026-05-15" in body
        assert "## Market Regime: RISK-ON" in body
        assert "S&P 500: 5500.0" in body
        assert "5.8% above 200MA" in body
        assert "NASDAQ: 17500.0" in body
        assert "VIX: 18.5" in body
        assert "## Interest Rates" in body
        assert "10Y Treasury: 4.25%" in body
        assert "2Y Treasury: 4.5%" in body
        assert "-25.0bp" in body
        assert "inverted" in body
        assert "Fed Funds: 5.25%" in body
        assert "## Economic Indicators" in body
        assert "CPI: 3.2% YoY" in body
        assert "Unemployment Rate: 4.1%" in body
        assert "GDP Growth: 2.5%" in body

    def test_output_without_fred(self):
        market = {
            "sp500": {"price": 5500.0, "change_pct": 0.5, "ma200": 5200.0, "pct_from_200ma": 5.77},
            "nasdaq": {"price": 17500.0, "change_pct": 1.0},
            "vix": {"level": 18.0, "interpretation": "Below average"},
            "regime": "RISK-ON",
            "regime_description": "Bullish",
            "errors": [],
        }

        body = format_macro_pulse("2026-05-15", market, None)

        assert "# Macro Pulse" in body
        assert "## Market Regime: RISK-ON" in body
        assert "FRED data unavailable" in body
        # Should NOT have economic indicators section
        assert "## Economic Indicators" not in body

    def test_output_with_market_errors(self):
        market = {
            "sp500": {},
            "nasdaq": {},
            "vix": {},
            "regime": "UNKNOWN",
            "regime_description": "",
            "errors": ["S&P 500: timeout", "NASDAQ: timeout"],
        }

        body = format_macro_pulse("2026-05-15", market, None)

        assert "data unavailable" in body
        assert "## Market Data Gaps" in body
        assert "S&P 500: timeout" in body

    def test_sp500_below_200ma_shows_below(self):
        market = {
            "sp500": {"price": 4800.0, "change_pct": -1.5, "ma200": 5000.0, "pct_from_200ma": -4.0},
            "nasdaq": {"price": 16000.0, "change_pct": -2.0},
            "vix": {"level": 30.0, "interpretation": "Elevated fear"},
            "regime": "RISK-OFF",
            "regime_description": "Bearish",
            "errors": [],
        }

        body = format_macro_pulse("2026-05-15", market, None)

        assert "below 200MA" in body


# ---------------------------------------------------------------------------
# generate_macro_pulse (integration, mocked external calls)
# ---------------------------------------------------------------------------


class TestGenerateMacroPulse:
    @patch("src.sources.market.macro_pulse._fetch_fred_data")
    @patch("src.sources.market.macro_pulse._fetch_market_data")
    def test_happy_path_creates_inbox_item(self, mock_market, mock_fred, kb):
        mock_market.return_value = {
            "sp500": {"price": 5500.0, "change_pct": 0.5, "ma200": 5200.0, "pct_from_200ma": 5.77},
            "nasdaq": {"price": 17500.0, "change_pct": 1.0},
            "vix": {"level": 18.0, "interpretation": "Below average"},
            "regime": "RISK-ON",
            "regime_description": "Bullish",
            "errors": [],
        }
        mock_fred.return_value = {
            "yields": {"10Y": 4.25, "2Y": 4.50},
            "spread": {"value_pct": -0.25, "value_bp": -25.0, "status": "inverted"},
            "indicators": {
                "cpi": {"value": 3.2, "as_of": "2026-04-15", "label": "CPI"},
            },
            "errors": [],
        }

        with patch.dict(os.environ, {"FRED_API_KEY": "test"}):
            result = generate_macro_pulse(kb=kb)

        assert result["status"] == "ok"
        assert result["regime"] == "RISK-ON"
        assert result["market_ok"] is True
        assert result["fred_ok"] is True
        assert "slug" in result

        # Verify inbox item exists
        pending = kb.list_unread()
        assert len(pending) == 1
        content = kb.read_unread(pending[0])
        assert "source: macro_pulse" in content
        assert "tier: 1" in content
        assert "content_type: market_data" in content
        assert "Macro Pulse" in content

    @patch("src.sources.market.macro_pulse._fetch_fred_data")
    @patch("src.sources.market.macro_pulse._fetch_market_data")
    def test_no_fred_key_still_creates_item(self, mock_market, mock_fred, kb):
        """When FRED_API_KEY is not set, should still create inbox item with market data."""
        mock_market.return_value = {
            "sp500": {"price": 5500.0, "change_pct": 0.5, "ma200": 5200.0, "pct_from_200ma": 5.77},
            "nasdaq": {"price": 17500.0, "change_pct": 1.0},
            "vix": {"level": 18.0, "interpretation": "Below average"},
            "regime": "RISK-ON",
            "regime_description": "Bullish",
            "errors": [],
        }
        mock_fred.return_value = None  # simulates no FRED_API_KEY

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("FRED_API_KEY", None)
            result = generate_macro_pulse(kb=kb)

        assert result["status"] == "ok"
        assert result["market_ok"] is True
        assert result["fred_ok"] is False

        pending = kb.list_unread()
        assert len(pending) == 1
        content = kb.read_unread(pending[0])
        assert "FRED data unavailable" in content

    @patch("src.sources.market.macro_pulse._fetch_fred_data")
    @patch("src.sources.market.macro_pulse._fetch_market_data")
    def test_yfinance_failure_with_fred_ok(self, mock_market, mock_fred, kb):
        """When yfinance fails but FRED works, should still create inbox item."""
        mock_market.return_value = {
            "sp500": {},
            "nasdaq": {},
            "vix": {},
            "regime": "UNKNOWN",
            "regime_description": "",
            "errors": ["all failed"],
        }
        mock_fred.return_value = {
            "yields": {"10Y": 4.25},
            "spread": {},
            "indicators": {"cpi": {"value": 3.2, "as_of": "2026-04-15", "label": "CPI"}},
            "errors": [],
        }

        with patch.dict(os.environ, {"FRED_API_KEY": "test"}):
            result = generate_macro_pulse(kb=kb)

        assert result["status"] == "ok"
        assert result["market_ok"] is False
        assert result["fred_ok"] is True

    @patch("src.sources.market.macro_pulse._fetch_fred_data")
    @patch("src.sources.market.macro_pulse._fetch_market_data")
    def test_both_fail_no_inbox_item(self, mock_market, mock_fred, kb):
        """When both yfinance and FRED fail, no inbox item should be created."""
        mock_market.return_value = {
            "sp500": {},
            "nasdaq": {},
            "vix": {},
            "regime": "UNKNOWN",
            "regime_description": "",
            "errors": ["network error"],
        }
        mock_fred.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("FRED_API_KEY", None)
            result = generate_macro_pulse(kb=kb)

        assert result["status"] == "error"
        assert result["reason"] == "no_data_available"

        # No inbox items
        pending = kb.list_unread()
        assert len(pending) == 0

    @patch("src.sources.market.macro_pulse._fetch_fred_data")
    @patch("src.sources.market.macro_pulse._fetch_market_data")
    def test_deduplication_skips_second_call(self, mock_market, mock_fred, kb):
        """Calling generate_macro_pulse twice on the same day should skip the second."""
        mock_market.return_value = {
            "sp500": {"price": 5500.0, "change_pct": 0.5, "ma200": 5200.0, "pct_from_200ma": 5.77},
            "nasdaq": {"price": 17500.0, "change_pct": 1.0},
            "vix": {"level": 18.0, "interpretation": "Below average"},
            "regime": "RISK-ON",
            "regime_description": "Bullish",
            "errors": [],
        }
        mock_fred.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("FRED_API_KEY", None)

            # First call
            result1 = generate_macro_pulse(kb=kb)
            assert result1["status"] == "ok"

            # Second call — should be skipped
            result2 = generate_macro_pulse(kb=kb)
            assert result2["status"] == "skipped"
            assert result2["reason"] == "already_generated_today"

        # Only one inbox item
        assert len(kb.list_unread()) == 1

    @patch("src.sources.market.macro_pulse._fetch_fred_data")
    @patch("src.sources.market.macro_pulse._fetch_market_data")
    def test_freshness_recorded(self, mock_market, mock_fred, kb):
        """set_last_updated should be called after successful generation."""
        mock_market.return_value = {
            "sp500": {"price": 5500.0, "change_pct": 0.5, "ma200": 5200.0, "pct_from_200ma": 5.77},
            "nasdaq": {"price": 17500.0, "change_pct": 1.0},
            "vix": {"level": 18.0, "interpretation": "Below average"},
            "regime": "RISK-ON",
            "regime_description": "Bullish",
            "errors": [],
        }
        mock_fred.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("FRED_API_KEY", None)
            generate_macro_pulse(kb=kb)

        last_updated = kb.get_last_updated()
        assert "macro_pulse" in last_updated
        entry = last_updated["macro_pulse"]
        assert entry["new_count"] == 1
        assert "daily snapshot" in entry["summary"]

    @patch("src.sources.market.macro_pulse._fetch_fred_data")
    @patch("src.sources.market.macro_pulse._fetch_market_data")
    def test_market_exception_handled(self, mock_market, mock_fred, kb):
        """If _fetch_market_data raises, generate_macro_pulse should not crash."""
        mock_market.side_effect = Exception("yfinance import error")
        mock_fred.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("FRED_API_KEY", None)
            result = generate_macro_pulse(kb=kb)

        assert result["status"] == "error"

    @patch("src.sources.market.macro_pulse._fetch_fred_data")
    @patch("src.sources.market.macro_pulse._fetch_market_data")
    def test_fred_exception_handled(self, mock_market, mock_fred, kb):
        """If _fetch_fred_data raises, should still use market data."""
        mock_market.return_value = {
            "sp500": {"price": 5500.0, "change_pct": 0.5, "ma200": 5200.0, "pct_from_200ma": 5.77},
            "nasdaq": {"price": 17500.0, "change_pct": 1.0},
            "vix": {"level": 18.0, "interpretation": "Below average"},
            "regime": "RISK-ON",
            "regime_description": "Bullish",
            "errors": [],
        }
        mock_fred.side_effect = Exception("fredapi import error")

        with patch.dict(os.environ, {"FRED_API_KEY": "test"}):
            result = generate_macro_pulse(kb=kb)

        assert result["status"] == "ok"
        assert result["market_ok"] is True
        assert result["fred_ok"] is False

    @patch("src.sources.market.macro_pulse._fetch_fred_data")
    @patch("src.sources.market.macro_pulse._fetch_market_data")
    def test_inbox_item_frontmatter(self, mock_market, mock_fred, kb):
        """Verify the inbox item has correct frontmatter fields."""
        mock_market.return_value = {
            "sp500": {"price": 5500.0, "change_pct": 0.5, "ma200": 5200.0, "pct_from_200ma": 5.77},
            "nasdaq": {"price": 17500.0, "change_pct": 1.0},
            "vix": {"level": 18.0, "interpretation": "Below average"},
            "regime": "RISK-ON",
            "regime_description": "Bullish",
            "errors": [],
        }
        mock_fred.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("FRED_API_KEY", None)
            result = generate_macro_pulse(kb=kb)

        slug = result["slug"]
        content = kb.read_unread(slug)

        assert content.startswith("---")
        assert "source: macro_pulse" in content
        assert "tier: 1" in content
        assert "content_type: market_data" in content
        assert "title: Macro Pulse" in content
        assert "tags: macro, daily" in content

    @patch("src.sources.market.macro_pulse._fetch_fred_data")
    @patch("src.sources.market.macro_pulse._fetch_market_data")
    def test_output_contains_expected_sections(self, mock_market, mock_fred, kb):
        """Verify the markdown body contains the expected sections."""
        mock_market.return_value = {
            "sp500": {"price": 5500.0, "change_pct": 0.5, "ma200": 5200.0, "pct_from_200ma": 5.77},
            "nasdaq": {"price": 17500.0, "change_pct": 1.0},
            "vix": {"level": 18.0, "interpretation": "Below average"},
            "regime": "RISK-ON",
            "regime_description": "Bullish",
            "errors": [],
        }
        mock_fred.return_value = {
            "yields": {"10Y": 4.25, "2Y": 4.50},
            "spread": {"value_pct": -0.25, "value_bp": -25.0, "status": "inverted"},
            "indicators": {
                "cpi": {"value": 3.2, "as_of": "2026-04-15", "label": "CPI"},
                "unemployment": {"value": 4.1, "as_of": "2026-04-01", "label": "Unemployment Rate"},
                "fed_funds": {"value": 5.25, "as_of": "2026-05-01", "label": "Fed Funds Rate"},
            },
            "errors": [],
        }

        with patch.dict(os.environ, {"FRED_API_KEY": "test"}):
            result = generate_macro_pulse(kb=kb)

        slug = result["slug"]
        content = kb.read_unread(slug)

        # Check markdown sections are present in the body
        assert "# Macro Pulse" in content
        assert "## Market Regime:" in content
        assert "## Interest Rates" in content
        assert "## Economic Indicators" in content


# ---------------------------------------------------------------------------
# Integration: refresh_pipeline calls macro pulse
# ---------------------------------------------------------------------------


class TestRefreshPipelineIntegration:
    @patch("src.sources.market.macro_pulse._fetch_fred_data")
    @patch("src.sources.market.macro_pulse._fetch_market_data")
    @patch("src.sources.refresh_pipeline.WechatSourceManager")
    def test_refresh_calls_macro_pulse(self, MockManager, mock_market, mock_fred, kb):
        """refresh_sources should call macro pulse after WeChat refresh."""
        # Mock WeChat manager
        mock_instance = MockManager.return_value
        mock_instance.accounts = []
        mock_instance.refresh_all.return_value = {}

        mock_market.return_value = {
            "sp500": {"price": 5500.0, "change_pct": 0.5, "ma200": 5200.0, "pct_from_200ma": 5.77},
            "nasdaq": {"price": 17500.0, "change_pct": 1.0},
            "vix": {"level": 18.0, "interpretation": "Below average"},
            "regime": "RISK-ON",
            "regime_description": "Bullish",
            "errors": [],
        }
        mock_fred.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("FRED_API_KEY", None)
            with patch("src.sources.refresh_pipeline.KnowledgeBase", return_value=kb):
                from src.sources.refresh_pipeline import refresh_sources
                result = refresh_sources()

        assert "macro_pulse" in result
        assert result["macro_pulse"]["status"] in ("ok", "skipped")

    @patch("src.sources.refresh_pipeline._run_macro_pulse")
    @patch("src.sources.refresh_pipeline.WechatSourceManager")
    def test_macro_failure_does_not_block_wechat(self, MockManager, mock_pulse, kb):
        """Macro pulse errors should not prevent WeChat results from returning."""
        mock_instance = MockManager.return_value
        mock_instance.accounts = []
        mock_instance.refresh_all.return_value = {}

        mock_pulse.return_value = {"status": "error", "reason": "something broke"}

        with patch("src.sources.refresh_pipeline.KnowledgeBase", return_value=kb):
            from src.sources.refresh_pipeline import refresh_sources
            result = refresh_sources()

        # Should still return successfully
        assert result["new_articles"] == 0
        assert result["macro_pulse"]["status"] == "error"
