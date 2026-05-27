"""Tests for macroeconomic MCP tools — treasury yields, economic indicators, yield curve, market regime.

Tests cover:
- get_treasury_yields (mocked fredapi)
- get_economic_indicators (mocked fredapi)
- get_yield_curve (mocked fredapi)
- get_market_regime (mocked yfinance)
- Error handling (missing API key, API errors)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from mcp.server.fastmcp import FastMCP

from src.data_sources.cache import get_cache
from src.data_sources.fred_source import FREDDataSource
from src.data_sources.yfinance_source import YFinanceDataSource
from src.tools.macroeconomic import register_macroeconomic_tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the TTL cache before and after each test."""
    get_cache().clear()
    yield
    get_cache().clear()


@pytest.fixture()
def mcp_app():
    """Create a FastMCP instance with macroeconomic tools registered."""
    mcp = FastMCP("test")
    fred_src = FREDDataSource()
    yf_src = YFinanceDataSource()
    register_macroeconomic_tools(mcp, fred_src, yf_src)
    return mcp


def _get_tool_fn(mcp: FastMCP, name: str):
    """Extract the raw async tool function from FastMCP internals."""
    return mcp._tool_manager._tools[name].fn


# ---------------------------------------------------------------------------
# Mock data helpers
# ---------------------------------------------------------------------------


def _mock_fred_series(values: list[float], start_date: str = "2025-01-01") -> pd.Series:
    """Create a mock pandas Series resembling FRED data output."""
    dates = pd.date_range(start=start_date, periods=len(values), freq="MS")
    return pd.Series(values, index=dates)


MOCK_GS2 = _mock_fred_series([4.10, 4.15, 4.20, 4.18, 4.25, 4.30])
MOCK_GS10 = _mock_fred_series([4.50, 4.55, 4.60, 4.58, 4.65, 4.70])
MOCK_GS30 = _mock_fred_series([4.80, 4.85, 4.90, 4.88, 4.95, 5.00])

MOCK_CPI = _mock_fred_series([310.5, 311.2, 312.0, 312.8, 313.5, 314.2])
MOCK_UNRATE = _mock_fred_series([3.7, 3.8, 3.9, 3.8, 3.7, 3.6])
MOCK_GDP = _mock_fred_series([2.1, 2.3, 2.5, 2.2])
MOCK_FEDFUNDS = _mock_fred_series([5.25, 5.25, 5.25, 5.00, 4.75, 4.50])

MOCK_YIELD_SPREAD = _mock_fred_series([0.30, 0.25, 0.20, 0.15, 0.10, 0.05])
MOCK_YIELD_SPREAD_INVERTED = _mock_fred_series([0.10, 0.05, 0.00, -0.05, -0.10, -0.20])


def _mock_sp500_df() -> pd.DataFrame:
    """Create a mock S&P 500 price DataFrame with 250 daily entries."""
    # Use a fixed Friday to avoid weekend truncation making date count < periods
    dates = pd.date_range(end="2026-05-15", periods=250, freq="B")
    # Prices trend upward from 4800 to 5500
    prices = np.linspace(4800, 5500, 250) + np.random.RandomState(42).randn(250) * 20
    return pd.DataFrame(
        {
            "Open": prices - 10,
            "High": prices + 15,
            "Low": prices - 15,
            "Close": prices,
            "Volume": np.random.RandomState(42).randint(2_000_000_000, 4_000_000_000, 250),
        },
        index=dates,
    )


def _mock_vix_df(level: float = 18.5) -> pd.DataFrame:
    """Create a mock VIX DataFrame with 60 daily entries around a given level."""
    dates = pd.date_range(end="2026-05-15", periods=60, freq="B")
    prices = np.full(60, level) + np.random.RandomState(42).randn(60) * 2
    return pd.DataFrame(
        {
            "Open": prices - 0.5,
            "High": prices + 1.0,
            "Low": prices - 1.0,
            "Close": prices,
            "Volume": np.random.RandomState(42).randint(100_000, 500_000, 60),
        },
        index=dates,
    )


# ---------------------------------------------------------------------------
# 1-3. get_treasury_yields tests
# ---------------------------------------------------------------------------


class TestGetTreasuryYields:
    """Tests for the get_treasury_yields MCP tool."""

    @pytest.mark.asyncio
    async def test_treasury_yields_markdown(self, mcp_app: FastMCP):
        """get_treasury_yields returns markdown with yield data."""
        fn = _get_tool_fn(mcp_app, "get_treasury_yields")

        with patch.object(
            FREDDataSource,
            "get_treasury_yields",
            new_callable=AsyncMock,
            return_value={
                "current": {"2Y": 4.30, "10Y": 4.70, "30Y": 5.00},
                "history": {
                    "2Y": [{"date": "2025-06-01", "yield_pct": 4.30}],
                    "10Y": [{"date": "2025-06-01", "yield_pct": 4.70}],
                    "30Y": [{"date": "2025-06-01", "yield_pct": 5.00}],
                },
                "as_of": "2025-06-01",
            },
        ):
            result = await fn(format="markdown")

        assert isinstance(result, str)
        assert "# Treasury Yields" in result
        assert "2-Year" in result
        assert "10-Year" in result
        assert "30-Year" in result
        assert "4.30%" in result
        assert "4.70%" in result

    @pytest.mark.asyncio
    async def test_treasury_yields_json(self, mcp_app: FastMCP):
        """get_treasury_yields with format='json' returns valid JSON."""
        fn = _get_tool_fn(mcp_app, "get_treasury_yields")

        with patch.object(
            FREDDataSource,
            "get_treasury_yields",
            new_callable=AsyncMock,
            return_value={
                "current": {"2Y": 4.30, "10Y": 4.70, "30Y": 5.00},
                "history": {"2Y": [], "10Y": [], "30Y": []},
                "as_of": "2025-06-01",
            },
        ):
            result = await fn(format="json")

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["current"]["10Y"] == 4.70
        assert parsed["as_of"] == "2025-06-01"

    @pytest.mark.asyncio
    async def test_treasury_yields_error_missing_key(self, mcp_app: FastMCP):
        """get_treasury_yields returns error string when API key is missing."""
        fn = _get_tool_fn(mcp_app, "get_treasury_yields")

        with patch.object(
            FREDDataSource,
            "get_treasury_yields",
            new_callable=AsyncMock,
            side_effect=Exception("FRED_API_KEY is not configured"),
        ):
            result = await fn(format="markdown")

        assert isinstance(result, str)
        assert result.startswith("Error:")


# ---------------------------------------------------------------------------
# 4-7. get_economic_indicators tests
# ---------------------------------------------------------------------------


class TestGetEconomicIndicators:
    """Tests for the get_economic_indicators MCP tool."""

    @pytest.mark.asyncio
    async def test_economic_indicators_all_markdown(self, mcp_app: FastMCP):
        """get_economic_indicators with 'all' returns markdown with all indicators."""
        fn = _get_tool_fn(mcp_app, "get_economic_indicators")

        with patch.object(
            FREDDataSource,
            "get_economic_indicators",
            new_callable=AsyncMock,
            return_value={
                "indicators": {
                    "cpi": {
                        "name": "CPI (Consumer Price Index)",
                        "current": 314.2,
                        "previous": 313.5,
                        "change": 0.7,
                        "as_of": "2025-05-01",
                        "history": [{"date": "2025-05-01", "index_value": 314.2}],
                    },
                    "unemployment": {
                        "name": "Unemployment Rate",
                        "current": 3.6,
                        "previous": 3.7,
                        "change": -0.1,
                        "as_of": "2025-05-01",
                        "history": [{"date": "2025-05-01", "rate_pct": 3.6}],
                    },
                }
            },
        ):
            result = await fn(indicator="all", format="markdown")

        assert isinstance(result, str)
        assert "# Economic Indicators" in result
        assert "CPI" in result
        assert "Unemployment" in result
        assert "314.20" in result

    @pytest.mark.asyncio
    async def test_economic_indicators_single_markdown(self, mcp_app: FastMCP):
        """get_economic_indicators with specific indicator returns relevant data."""
        fn = _get_tool_fn(mcp_app, "get_economic_indicators")

        with patch.object(
            FREDDataSource,
            "get_economic_indicators",
            new_callable=AsyncMock,
            return_value={
                "indicators": {
                    "unemployment": {
                        "name": "Unemployment Rate",
                        "current": 3.6,
                        "previous": 3.7,
                        "change": -0.1,
                        "as_of": "2025-05-01",
                        "history": [{"date": "2025-05-01", "rate_pct": 3.6}],
                    },
                }
            },
        ):
            result = await fn(indicator="unemployment", format="markdown")

        assert isinstance(result, str)
        assert "Unemployment" in result
        assert "3.60" in result

    @pytest.mark.asyncio
    async def test_economic_indicators_json(self, mcp_app: FastMCP):
        """get_economic_indicators with format='json' returns valid JSON."""
        fn = _get_tool_fn(mcp_app, "get_economic_indicators")

        with patch.object(
            FREDDataSource,
            "get_economic_indicators",
            new_callable=AsyncMock,
            return_value={
                "indicators": {
                    "fed_funds": {
                        "name": "Federal Funds Rate",
                        "current": 4.50,
                        "previous": 4.75,
                        "change": -0.25,
                        "as_of": "2025-05-01",
                        "history": [],
                    },
                }
            },
        ):
            result = await fn(indicator="fed_funds", format="json")

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert "indicators" in parsed
        assert parsed["indicators"]["fed_funds"]["current"] == 4.50

    @pytest.mark.asyncio
    async def test_economic_indicators_error(self, mcp_app: FastMCP):
        """get_economic_indicators with bad indicator returns error string."""
        fn = _get_tool_fn(mcp_app, "get_economic_indicators")

        with patch.object(
            FREDDataSource,
            "get_economic_indicators",
            new_callable=AsyncMock,
            side_effect=Exception("API error"),
        ):
            result = await fn(indicator="invalid_thing", format="markdown")

        assert isinstance(result, str)
        assert result.startswith("Error:")


# ---------------------------------------------------------------------------
# 8-11. get_yield_curve tests
# ---------------------------------------------------------------------------


class TestGetYieldCurve:
    """Tests for the get_yield_curve MCP tool."""

    @pytest.mark.asyncio
    async def test_yield_curve_normal_markdown(self, mcp_app: FastMCP):
        """get_yield_curve returns markdown with positive spread."""
        fn = _get_tool_fn(mcp_app, "get_yield_curve")

        with patch.object(
            FREDDataSource,
            "get_yield_curve",
            new_callable=AsyncMock,
            return_value={
                "current_spread": 0.40,
                "is_inverted": False,
                "interpretation": "Flat — often a transitional signal.",
                "trend_3m_change": -0.10,
                "history": [{"date": "2025-06-01", "spread_pct": 0.40}],
                "as_of": "2025-06-01",
            },
        ):
            result = await fn(format="markdown")

        assert isinstance(result, str)
        assert "# Yield Curve" in result
        assert "Normal" in result
        assert "0.40%" in result

    @pytest.mark.asyncio
    async def test_yield_curve_inverted_markdown(self, mcp_app: FastMCP):
        """get_yield_curve correctly shows inversion status."""
        fn = _get_tool_fn(mcp_app, "get_yield_curve")

        with patch.object(
            FREDDataSource,
            "get_yield_curve",
            new_callable=AsyncMock,
            return_value={
                "current_spread": -0.20,
                "is_inverted": True,
                "interpretation": "Inverted — recession warning signal.",
                "trend_3m_change": -0.30,
                "history": [{"date": "2025-06-01", "spread_pct": -0.20}],
                "as_of": "2025-06-01",
            },
        ):
            result = await fn(format="markdown")

        assert isinstance(result, str)
        assert "INVERTED" in result

    @pytest.mark.asyncio
    async def test_yield_curve_json(self, mcp_app: FastMCP):
        """get_yield_curve with format='json' returns valid JSON."""
        fn = _get_tool_fn(mcp_app, "get_yield_curve")

        with patch.object(
            FREDDataSource,
            "get_yield_curve",
            new_callable=AsyncMock,
            return_value={
                "current_spread": 0.40,
                "is_inverted": False,
                "interpretation": "Flat.",
                "trend_3m_change": -0.10,
                "history": [],
                "as_of": "2025-06-01",
            },
        ):
            result = await fn(format="json")

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["current_spread"] == 0.40
        assert parsed["is_inverted"] is False

    @pytest.mark.asyncio
    async def test_yield_curve_error(self, mcp_app: FastMCP):
        """get_yield_curve returns error string on API failure."""
        fn = _get_tool_fn(mcp_app, "get_yield_curve")

        with patch.object(
            FREDDataSource,
            "get_yield_curve",
            new_callable=AsyncMock,
            side_effect=Exception("FRED API timeout"),
        ):
            result = await fn(format="markdown")

        assert isinstance(result, str)
        assert result.startswith("Error:")


# ---------------------------------------------------------------------------
# 12-16. get_market_regime tests
# ---------------------------------------------------------------------------


class TestGetMarketRegime:
    """Tests for the get_market_regime MCP tool."""

    @pytest.mark.asyncio
    async def test_market_regime_risk_on_markdown(self, mcp_app: FastMCP):
        """get_market_regime returns RISK-ON when S&P above 200MA and VIX low."""
        fn = _get_tool_fn(mcp_app, "get_market_regime")

        # S&P 500: trending up, well above 200MA
        sp500_df = _mock_sp500_df()
        # VIX: low (around 14)
        vix_df = _mock_vix_df(level=14.0)

        with patch("src.tools.macroeconomic.yf") as mock_yf:
            mock_sp500 = MagicMock()
            mock_sp500.history.return_value = sp500_df
            mock_vix = MagicMock()
            mock_vix.history.return_value = vix_df

            def ticker_factory(symbol):
                if symbol == "^GSPC":
                    return mock_sp500
                elif symbol == "^VIX":
                    return mock_vix
                return MagicMock()

            mock_yf.Ticker.side_effect = ticker_factory

            result = await fn(format="markdown")

        assert isinstance(result, str)
        assert "# Market Regime" in result
        assert "RISK-ON" in result
        assert "S&P 500" in result
        assert "VIX" in result

    @pytest.mark.asyncio
    async def test_market_regime_risk_off_markdown(self, mcp_app: FastMCP):
        """get_market_regime returns RISK-OFF when S&P below 200MA and VIX high."""
        fn = _get_tool_fn(mcp_app, "get_market_regime")

        # S&P 500: trending down, below 200MA
        dates = pd.date_range(end="2026-05-15", periods=250, freq="B")
        prices = np.linspace(5500, 4600, 250) + np.random.RandomState(42).randn(250) * 20
        sp500_df = pd.DataFrame(
            {"Open": prices, "High": prices + 15, "Low": prices - 15, "Close": prices, "Volume": [3_000_000_000] * 250},
            index=dates,
        )
        # VIX: elevated (around 30)
        vix_df = _mock_vix_df(level=30.0)

        with patch("src.tools.macroeconomic.yf") as mock_yf:
            mock_sp500 = MagicMock()
            mock_sp500.history.return_value = sp500_df
            mock_vix = MagicMock()
            mock_vix.history.return_value = vix_df

            def ticker_factory(symbol):
                if symbol == "^GSPC":
                    return mock_sp500
                elif symbol == "^VIX":
                    return mock_vix
                return MagicMock()

            mock_yf.Ticker.side_effect = ticker_factory

            result = await fn(format="markdown")

        assert isinstance(result, str)
        assert "RISK-OFF" in result

    @pytest.mark.asyncio
    async def test_market_regime_cautious_markdown(self, mcp_app: FastMCP):
        """get_market_regime returns CAUTIOUS for mixed signals."""
        fn = _get_tool_fn(mcp_app, "get_market_regime")

        # S&P 500: above 200MA
        sp500_df = _mock_sp500_df()
        # VIX: elevated (around 28) -- mixed signal
        vix_df = _mock_vix_df(level=28.0)

        with patch("src.tools.macroeconomic.yf") as mock_yf:
            mock_sp500 = MagicMock()
            mock_sp500.history.return_value = sp500_df
            mock_vix = MagicMock()
            mock_vix.history.return_value = vix_df

            def ticker_factory(symbol):
                if symbol == "^GSPC":
                    return mock_sp500
                elif symbol == "^VIX":
                    return mock_vix
                return MagicMock()

            mock_yf.Ticker.side_effect = ticker_factory

            result = await fn(format="markdown")

        assert isinstance(result, str)
        assert "CAUTIOUS" in result

    @pytest.mark.asyncio
    async def test_market_regime_json(self, mcp_app: FastMCP):
        """get_market_regime with format='json' returns valid JSON."""
        fn = _get_tool_fn(mcp_app, "get_market_regime")

        sp500_df = _mock_sp500_df()
        vix_df = _mock_vix_df(level=18.0)

        with patch("src.tools.macroeconomic.yf") as mock_yf:
            mock_sp500 = MagicMock()
            mock_sp500.history.return_value = sp500_df
            mock_vix = MagicMock()
            mock_vix.history.return_value = vix_df

            def ticker_factory(symbol):
                if symbol == "^GSPC":
                    return mock_sp500
                elif symbol == "^VIX":
                    return mock_vix
                return MagicMock()

            mock_yf.Ticker.side_effect = ticker_factory

            result = await fn(format="json")

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert "regime" in parsed
        assert "sp500" in parsed
        assert "vix" in parsed
        assert parsed["sp500"]["current"] is not None
        assert parsed["vix"]["current"] is not None

    @pytest.mark.asyncio
    async def test_market_regime_error(self, mcp_app: FastMCP):
        """get_market_regime returns error string on failure."""
        fn = _get_tool_fn(mcp_app, "get_market_regime")

        with patch("src.tools.macroeconomic.yf") as mock_yf:
            mock_yf.Ticker.side_effect = Exception("Network error")

            result = await fn(format="markdown")

        assert isinstance(result, str)
        assert result.startswith("Error:")


# ---------------------------------------------------------------------------
# 17-19. FREDDataSource unit tests
# ---------------------------------------------------------------------------


class TestFREDDataSource:
    """Unit tests for the FREDDataSource class."""

    @pytest.mark.asyncio
    async def test_missing_api_key(self):
        """FREDDataSource raises informative error when API key is missing."""
        source = FREDDataSource()
        source._api_key = None

        with pytest.raises(Exception) as exc_info:
            await source.get_treasury_yields()
        assert "FRED_API_KEY" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_treasury_yields_data(self):
        """FREDDataSource.get_treasury_yields returns correct structure."""
        source = FREDDataSource()
        source._api_key = "test_key"

        with patch("src.data_sources.fred_source.FREDDataSource._fetch_series") as mock_fetch:
            mock_fetch.side_effect = [MOCK_GS2, MOCK_GS10, MOCK_GS30]
            result = await source.get_treasury_yields()

        assert "current" in result
        assert result["current"]["2Y"] == 4.30
        assert result["current"]["10Y"] == 4.70
        assert result["current"]["30Y"] == 5.00
        assert "history" in result
        assert "as_of" in result

    @pytest.mark.asyncio
    async def test_get_economic_indicators_all(self):
        """FREDDataSource.get_economic_indicators returns all indicators."""
        source = FREDDataSource()
        source._api_key = "test_key"

        with patch("src.data_sources.fred_source.FREDDataSource._fetch_series") as mock_fetch:
            mock_fetch.side_effect = [MOCK_CPI, MOCK_UNRATE, MOCK_GDP, MOCK_FEDFUNDS]
            result = await source.get_economic_indicators(indicator="all")

        assert "indicators" in result
        assert "cpi" in result["indicators"]
        assert "unemployment" in result["indicators"]
        assert "gdp" in result["indicators"]
        assert "fed_funds" in result["indicators"]
        assert result["indicators"]["cpi"]["current"] == 314.2

    @pytest.mark.asyncio
    async def test_get_yield_curve_normal(self):
        """FREDDataSource.get_yield_curve detects normal (positive) spread."""
        source = FREDDataSource()
        source._api_key = "test_key"

        with patch("src.data_sources.fred_source.FREDDataSource._fetch_series") as mock_fetch:
            mock_fetch.return_value = MOCK_YIELD_SPREAD
            result = await source.get_yield_curve()

        assert result["current_spread"] == 0.05
        assert result["is_inverted"] is False
        assert "history" in result

    @pytest.mark.asyncio
    async def test_get_yield_curve_inverted(self):
        """FREDDataSource.get_yield_curve detects inverted spread."""
        source = FREDDataSource()
        source._api_key = "test_key"

        with patch("src.data_sources.fred_source.FREDDataSource._fetch_series") as mock_fetch:
            mock_fetch.return_value = MOCK_YIELD_SPREAD_INVERTED
            result = await source.get_yield_curve()

        assert result["current_spread"] == -0.20
        assert result["is_inverted"] is True
        assert "Inverted" in result["interpretation"]
