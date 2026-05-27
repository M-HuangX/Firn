"""Tests for YFinanceDataSource — mocked yfinance calls, no network access."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.data_sources.cache import get_cache
from src.data_sources.exceptions import (
    ExternalAPIError,
    NoDataAvailableError,
    TickerNotFoundError,
)
from src.data_sources.yfinance_source import (
    YFinanceDataSource,
    _safe_float,
    _safe_int,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ds() -> YFinanceDataSource:
    """Return a fresh YFinanceDataSource instance."""
    return YFinanceDataSource()


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the TTLCache singleton before and after each test."""
    get_cache().clear()
    yield
    get_cache().clear()


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

_SAMPLE_INFO: dict[str, Any] = {
    "shortName": "Apple Inc.",
    "longName": "Apple Inc.",
    "symbol": "AAPL",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "country": "United States",
    "website": "https://www.apple.com",
    "fullTimeEmployees": 164000,
    "currentPrice": 150.0,
    "previousClose": 148.5,
    "fiftyTwoWeekHigh": 180.0,
    "fiftyTwoWeekLow": 120.0,
    "fiftyDayAverage": 155.0,
    "twoHundredDayAverage": 145.0,
    "beta": 1.2,
    "volume": 50000000,
    "exchange": "NMS",
    "currency": "USD",
    "marketState": "REGULAR",
    "exchangeTimezoneName": "America/New_York",
    # Metrics-related fields
    "trailingPE": 25.0,
    "forwardPE": 22.0,
    "priceToBook": 40.0,
    "priceToSalesTrailing12Months": 7.0,
    "pegRatio": 1.5,
    "enterpriseToEbitda": 20.0,
    "enterpriseToRevenue": 6.5,
    "returnOnEquity": 0.45,
    "returnOnAssets": 0.20,
    "grossMargins": 0.43,
    "operatingMargins": 0.30,
    "profitMargins": 0.25,
    "ebitdaMargins": 0.33,
    "revenueGrowth": 0.08,
    "earningsGrowth": 0.10,
    "earningsQuarterlyGrowth": 0.05,
    "trailingEps": 6.0,
    "forwardEps": 6.8,
    "bookValue": 3.75,
    "revenuePerShare": 24.0,
    "debtToEquity": 150.0,
    "currentRatio": 1.0,
    "quickRatio": 0.8,
    "interestCoverage": None,
    "freeCashflow": 100_000_000_000,
    "operatingCashflow": 120_000_000_000,
    "marketCap": 2_500_000_000_000,
    "netIncomeToCommon": 95_000_000_000,
    "dividendYield": 0.006,
    "dividendRate": 0.92,
    "payoutRatio": 0.15,
    "fiveYearAvgDividendYield": 0.8,
    "exDividendDate": 1700000000,
    "trailingAnnualDividendRate": 0.92,
    "trailingAnnualDividendYield": 0.006,
    "quoteType": "EQUITY",
}

_SAMPLE_ETF_INFO: dict[str, Any] = {
    "shortName": "Teucrium Corn Fund ETV",
    "longName": "Teucrium Corn Fund",
    "symbol": "CORN",
    "quoteType": "ETF",
    "currentPrice": 18.14,
    "previousClose": 18.53,
    "fiftyTwoWeekHigh": 19.13,
    "fiftyTwoWeekLow": 16.61,
    "fiftyDayAverage": 18.42,
    "twoHundredDayAverage": 17.79,
    "beta": 0.34,
    "volume": 663307,
    "exchange": "PCX",
    "currency": "USD",
    "marketState": "REGULAR",
    "exchangeTimezoneName": "America/New_York",
    "category": "Commodities Focused",
    "fundFamily": "Teucrium",
    "totalAssets": 263009776,
    "navPrice": 18.5351,
    "netExpenseRatio": 1.0,
    "ytdReturn": 0.0538239,
    "threeYearAverageReturn": -0.0659682,
    "fiveYearAverageReturn": -0.0143625,
    "longBusinessSummary": "The fund seeks to track the price of corn futures.",
}


def _sample_ohlcv_df(days: int = 30, tz: str = "UTC") -> pd.DataFrame:
    """Create a deterministic OHLCV DataFrame similar to yfinance output."""
    # Use a fixed Friday to avoid weekend truncation making date count < days
    dates = pd.date_range(end="2026-05-15", periods=days, freq="B", tz=tz)
    np.random.seed(42)
    close = np.linspace(140, 160, days)
    return pd.DataFrame(
        {
            "Open": close - 1,
            "High": close + 5,
            "Low": close - 5,
            "Close": close,
            "Volume": np.full(days, 3_000_000, dtype=int),
        },
        index=dates,
    )


def _make_mock_ticker(
    info: dict[str, Any] | None = None,
    history_df: pd.DataFrame | None = None,
    dividends: pd.Series | None = None,
) -> MagicMock:
    """Create a mock yf.Ticker with controlled attributes.

    Because the source code uses ``getattr(yf_ticker, "info")`` via _run_sync,
    the mock must expose these as plain attributes (not methods).
    For ``.history()``, which is called as a method, it must be a callable mock.
    """
    mock = MagicMock()
    mock.info = info if info is not None else {}

    if history_df is not None:
        mock.history = MagicMock(return_value=history_df)
    else:
        mock.history = MagicMock(return_value=pd.DataFrame())

    if dividends is not None:
        mock.dividends = dividends
    else:
        mock.dividends = pd.Series(dtype=float)

    return mock


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestSafeFloat:
    """Tests for the _safe_float helper."""

    def test_safe_float_normal(self):
        assert _safe_float(42.5) == 42.5

    def test_safe_float_nan(self):
        assert _safe_float(float("nan")) is None

    def test_safe_float_inf(self):
        assert _safe_float(float("inf")) is None

    def test_safe_float_none(self):
        assert _safe_float(None) is None

    def test_safe_float_int_input(self):
        assert _safe_float(42) == 42.0

    def test_safe_float_string_fails(self):
        assert _safe_float("not_a_number") is None


class TestSafeInt:
    """Tests for the _safe_int helper."""

    def test_safe_int_normal(self):
        assert _safe_int(42) == 42

    def test_safe_int_nan(self):
        assert _safe_int(float("nan")) is None

    def test_safe_int_none(self):
        assert _safe_int(None) is None

    def test_safe_int_float_input(self):
        assert _safe_int(42.9) == 42


# ---------------------------------------------------------------------------
# get_stock_info tests
# ---------------------------------------------------------------------------


class TestGetStockInfo:
    """Tests for YFinanceDataSource.get_stock_info."""

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_stock_info_success(self, mock_ticker_cls, ds):
        """Valid info dict returns correct structure with identity/price/market sections."""
        mock_ticker = _make_mock_ticker(info=_SAMPLE_INFO)
        mock_ticker_cls.return_value = mock_ticker

        result = await ds.get_stock_info("AAPL")

        assert result["_ticker"] == "AAPL"
        assert result["identity"]["shortName"] == "Apple Inc."
        assert result["identity"]["sector"] == "Technology"
        assert result["identity"]["fullTimeEmployees"] == 164000
        assert result["price"]["currentPrice"] == 150.0
        assert result["price"]["beta"] == 1.2
        assert result["market"]["exchange"] == "NMS"
        assert result["market"]["currency"] == "USD"

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_stock_info_invalid_ticker(self, mock_ticker_cls, ds):
        """Empty info dict (no shortName) raises TickerNotFoundError."""
        mock_ticker = _make_mock_ticker(info={})
        mock_ticker_cls.return_value = mock_ticker

        with pytest.raises(TickerNotFoundError):
            await ds.get_stock_info("INVALID")

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_stock_info_api_error(self, mock_ticker_cls, ds):
        """Unexpected exception is wrapped in ExternalAPIError."""
        mock_ticker_cls.side_effect = RuntimeError("network failure")

        with pytest.raises(ExternalAPIError, match="get_stock_info failed"):
            await ds.get_stock_info("AAPL")

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_stock_info_equity_has_quote_type(self, mock_ticker_cls, ds):
        """Equity ticker includes quoteType in identity."""
        mock_ticker = _make_mock_ticker(info=_SAMPLE_INFO)
        mock_ticker_cls.return_value = mock_ticker

        result = await ds.get_stock_info("AAPL")
        assert result["identity"]["quoteType"] == "EQUITY"
        assert "fund_info" not in result

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_stock_info_etf_has_fund_info(self, mock_ticker_cls, ds):
        """ETF ticker includes fund_info section with category, AUM, NAV, etc."""
        mock_ticker = _make_mock_ticker(info=_SAMPLE_ETF_INFO)
        mock_ticker_cls.return_value = mock_ticker

        result = await ds.get_stock_info("CORN")

        assert result["identity"]["quoteType"] == "ETF"
        assert "fund_info" in result
        fi = result["fund_info"]
        assert fi["category"] == "Commodities Focused"
        assert fi["fundFamily"] == "Teucrium"
        assert fi["totalAssets"] == 263009776.0
        assert fi["navPrice"] == 18.5351
        assert fi["expenseRatio"] == 1.0
        assert fi["ytdReturn"] == 0.0538239
        assert fi["longBusinessSummary"] is not None


# ---------------------------------------------------------------------------
# get_historical_prices tests
# ---------------------------------------------------------------------------


class TestGetHistoricalPrices:
    """Tests for YFinanceDataSource.get_historical_prices."""

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_historical_prices_success(self, mock_ticker_cls, ds):
        """Valid history DataFrame returns summary + prices list."""
        df = _sample_ohlcv_df(days=30)
        mock_ticker = _make_mock_ticker(history_df=df)
        mock_ticker_cls.return_value = mock_ticker

        result = await ds.get_historical_prices("AAPL", period="1mo")

        assert result["_ticker"] == "AAPL"
        assert result["period"] == "1mo"
        assert result["interval"] == "1d"
        assert result["summary"]["total_rows"] == 30
        assert result["summary"]["price_change_pct"] is not None
        assert len(result["prices"]) == 30
        # Each price record has Date, Open, High, Low, Close, Volume
        first = result["prices"][0]
        assert "Date" in first
        assert "Close" in first

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_historical_prices_with_start_date(self, mock_ticker_cls, ds):
        """start_date overrides period and passes start/end to yf.Ticker.history."""
        df = _sample_ohlcv_df(days=10)
        mock_ticker = _make_mock_ticker(history_df=df)
        mock_ticker_cls.return_value = mock_ticker

        result = await ds.get_historical_prices(
            "AAPL", start_date="2024-01-01", end_date="2024-06-01"
        )

        assert "2024-01-01" in result["period"]
        assert "2024-06-01" in result["period"]
        # Verify history was called with start/end, not period
        mock_ticker.history.assert_called_once_with(
            start="2024-01-01", interval="1d", end="2024-06-01"
        )

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_historical_prices_empty(self, mock_ticker_cls, ds):
        """Empty DataFrame raises NoDataAvailableError."""
        mock_ticker = _make_mock_ticker(history_df=pd.DataFrame())
        mock_ticker_cls.return_value = mock_ticker

        with pytest.raises(NoDataAvailableError):
            await ds.get_historical_prices("AAPL")


# ---------------------------------------------------------------------------
# get_financial_metrics tests
# ---------------------------------------------------------------------------


class TestGetFinancialMetrics:
    """Tests for YFinanceDataSource.get_financial_metrics."""

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_financial_metrics_success(self, mock_ticker_cls, ds):
        """Returns all 7 metric sections."""
        mock_ticker = _make_mock_ticker(info=_SAMPLE_INFO)
        mock_ticker_cls.return_value = mock_ticker

        result = await ds.get_financial_metrics("AAPL")

        assert result["_ticker"] == "AAPL"
        expected_sections = [
            "valuation",
            "profitability",
            "growth",
            "per_share",
            "financial_health",
            "cash_flow",
            "dividends",
        ]
        for section in expected_sections:
            assert section in result, f"Missing section: {section}"

        # Spot-check some values
        assert result["valuation"]["trailingPE"] == 25.0
        assert result["profitability"]["grossMargins"] == 0.43
        assert result["growth"]["revenueGrowth"] == 0.08
        assert result["per_share"]["trailingEps"] == 6.0

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_financial_metrics_computed_fields(self, mock_ticker_cls, ds):
        """fcfYield and ocfToNetIncome are correctly computed from raw fields."""
        mock_ticker = _make_mock_ticker(info=_SAMPLE_INFO)
        mock_ticker_cls.return_value = mock_ticker

        result = await ds.get_financial_metrics("AAPL")

        # fcfYield = freeCashflow / marketCap = 100B / 2500B = 0.04
        expected_fcf_yield = round(100_000_000_000 / 2_500_000_000_000, 6)
        assert result["cash_flow"]["fcfYield"] == expected_fcf_yield

        # ocfToNetIncome = operatingCashflow / netIncomeToCommon = 120B / 95B
        expected_ocf_to_ni = round(120_000_000_000 / 95_000_000_000, 4)
        assert result["cash_flow"]["ocfToNetIncome"] == expected_ocf_to_ni


# ---------------------------------------------------------------------------
# get_dividends tests
# ---------------------------------------------------------------------------


class TestGetDividends:
    """Tests for YFinanceDataSource.get_dividends."""

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_dividends_success(self, mock_ticker_cls, ds):
        """Returns summary + history when dividends exist."""
        dates = pd.DatetimeIndex(
            [
                pd.Timestamp("2024-02-09", tz="UTC"),
                pd.Timestamp("2024-05-10", tz="UTC"),
                pd.Timestamp("2024-08-12", tz="UTC"),
                pd.Timestamp("2024-11-08", tz="UTC"),
            ]
        )
        dividends = pd.Series([0.23, 0.23, 0.24, 0.24], index=dates)

        mock_ticker = _make_mock_ticker(info=_SAMPLE_INFO, dividends=dividends)
        mock_ticker_cls.return_value = mock_ticker

        result = await ds.get_dividends("AAPL", years=5)

        assert result["_ticker"] == "AAPL"
        assert "summary" in result
        assert "history" in result
        assert result["summary"]["dividendYield"] == 0.006
        assert result["summary"]["dividendRate"] == 0.92
        assert result["summary"]["totalPaymentsInPeriod"] == 4
        assert len(result["history"]) == 4
        # Each history entry has date and amount
        assert result["history"][0]["date"] == "2024-02-09"
        assert result["history"][0]["amount"] == 0.23

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_dividends_no_dividends(self, mock_ticker_cls, ds):
        """Empty dividends Series returns empty history (not an error)."""
        mock_ticker = _make_mock_ticker(
            info=_SAMPLE_INFO, dividends=pd.Series(dtype=float)
        )
        mock_ticker_cls.return_value = mock_ticker

        result = await ds.get_dividends("AAPL")

        assert result["_ticker"] == "AAPL"
        assert result["history"] == []
        assert result["summary"]["totalPaymentsInPeriod"] == 0


# ---------------------------------------------------------------------------
# search_stocks tests
# ---------------------------------------------------------------------------


class TestSearchStocks:
    """Tests for YFinanceDataSource.search_stocks."""

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Search")
    async def test_search_stocks_success(self, mock_search_cls, ds):
        """Returns list of result dicts from Search.quotes."""
        mock_search = MagicMock()
        mock_search.quotes = [
            {
                "symbol": "AAPL",
                "shortname": "Apple Inc.",
                "exchange": "NMS",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "quoteType": "EQUITY",
            },
            {
                "symbol": "AAPLX",
                "shortname": "Some Fund",
                "exchange": "NAS",
                "sector": None,
                "industry": None,
                "quoteType": "MUTUALFUND",
            },
        ]
        mock_search_cls.return_value = mock_search

        result = await ds.search_stocks("Apple", limit=10)

        assert len(result) == 2
        assert result[0]["symbol"] == "AAPL"
        assert result[0]["name"] == "Apple Inc."
        assert result[0]["exchange"] == "NMS"
        assert result[0]["quoteType"] == "EQUITY"

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Search")
    async def test_search_stocks_no_results(self, mock_search_cls, ds):
        """Empty quotes list raises NoDataAvailableError."""
        mock_search = MagicMock()
        mock_search.quotes = []
        mock_search_cls.return_value = mock_search

        with pytest.raises(NoDataAvailableError, match="No search results"):
            await ds.search_stocks("xyznonexistent123")


# ---------------------------------------------------------------------------
# get_index_data tests
# ---------------------------------------------------------------------------


class TestGetIndexData:
    """Tests for YFinanceDataSource.get_index_data."""

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_index_data_resolves_friendly_name(self, mock_ticker_cls, ds):
        """'SP500' resolves to '^GSPC' before calling yf.Ticker."""
        df = _sample_ohlcv_df(days=250)
        mock_ticker = _make_mock_ticker(info={"shortName": "S&P 500"}, history_df=df)
        mock_ticker_cls.return_value = mock_ticker

        result = await ds.get_index_data("SP500", period="1y")

        # Verify the Ticker was created with the resolved symbol
        mock_ticker_cls.assert_called_with("^GSPC")
        assert result["_ticker"] == "^GSPC"

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_index_data_success(self, mock_ticker_cls, ds):
        """Returns summary with currentValue, periodChangePct."""
        df = _sample_ohlcv_df(days=250)
        mock_ticker = _make_mock_ticker(info={"shortName": "S&P 500"}, history_df=df)
        mock_ticker_cls.return_value = mock_ticker

        result = await ds.get_index_data("^GSPC", period="1y")

        assert result["_ticker"] == "^GSPC"
        assert result["name"] == "S&P 500"
        assert "summary" in result
        summary = result["summary"]
        assert summary["currentValue"] is not None
        assert summary["periodChangePct"] is not None
        assert summary["periodHigh"] is not None
        assert summary["periodLow"] is not None


# ---------------------------------------------------------------------------
# _format_financial_statement tests
# ---------------------------------------------------------------------------


class TestFormatFinancialStatement:
    """Tests for the static _format_financial_statement helper."""

    def test_format_financial_statement(self):
        """Converts a DataFrame with date columns and line-item rows to clean dict."""
        dates = [pd.Timestamp("2024-09-30"), pd.Timestamp("2023-09-30")]
        df = pd.DataFrame(
            {
                dates[0]: [100_000_000, 50_000_000, float("nan")],
                dates[1]: [90_000_000, 45_000_000, 10_000_000],
            },
            index=["TotalRevenue", "GrossProfit", "SpecialItem"],
        )

        result = YFinanceDataSource._format_financial_statement(
            df, ticker="AAPL", period_type="annual", limit=5
        )

        assert result["_ticker"] == "AAPL"
        assert result["period_type"] == "annual"
        assert result["periods"] == ["2024-09-30", "2023-09-30"]
        assert result["data"]["TotalRevenue"] == [100_000_000, 90_000_000]
        assert result["data"]["GrossProfit"] == [50_000_000, 45_000_000]
        # NaN should be converted to None
        assert result["data"]["SpecialItem"][0] is None
        assert result["data"]["SpecialItem"][1] == 10_000_000


# ---------------------------------------------------------------------------
# _get_period_slice tests
# ---------------------------------------------------------------------------


class TestGetPeriodSlice:
    """Tests for the static _get_period_slice helper."""

    def test_get_period_slice_6mo(self):
        """Slices DataFrame to approximately 180 days of data."""
        # Create 1 year of data
        df = _sample_ohlcv_df(days=252)

        sliced = YFinanceDataSource._get_period_slice(df, "6mo")

        # 6mo = 180 days; the sliced df should have fewer rows than the original
        assert len(sliced) < len(df)
        # The sliced data should span roughly 180 days (business days ~= 126)
        # Just verify it's a reasonable subset
        assert len(sliced) > 0
        # Verify the last date is the same as the original
        assert sliced.index[-1] == df.index[-1]

    def test_get_period_slice_unknown_defaults_to_180(self):
        """Unknown period string defaults to 180 days."""
        df = _sample_ohlcv_df(days=252)

        sliced_unknown = YFinanceDataSource._get_period_slice(df, "unknown")
        sliced_6mo = YFinanceDataSource._get_period_slice(df, "6mo")

        assert len(sliced_unknown) == len(sliced_6mo)

    def test_get_period_slice_returns_full_if_empty_slice(self):
        """If the slice would be empty (e.g., all data is older), return full df."""
        # Create data that is all in the distant past
        old_dates = pd.date_range(end="2020-01-01", periods=10, freq="B", tz="UTC")
        df = pd.DataFrame(
            {
                "Close": range(10),
                "High": range(10, 20),
                "Low": range(10),
                "Volume": [1000] * 10,
            },
            index=old_dates,
        )

        sliced = YFinanceDataSource._get_period_slice(df, "1mo")

        # Since all data is old, the slice would be empty, so full df is returned
        assert len(sliced) == len(df)


# ---------------------------------------------------------------------------
# get_insider_transactions tests
# ---------------------------------------------------------------------------


class TestGetInsiderTransactions:
    """Tests for YFinanceDataSource.get_insider_transactions."""

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_insider_transactions_success(self, mock_ticker_cls, ds):
        """Valid insider transaction DataFrame returns correct structure with summary."""
        mock_ticker = MagicMock()
        mock_ticker.info = _SAMPLE_INFO

        insider_df = pd.DataFrame({
            "Insider": ["John Doe", "Jane Smith", "Bob Lee"],
            "Text": [
                "Purchase of shares",
                "Sale of shares",
                "Purchase of shares",
            ],
            "Shares": [10000, 5000, 2000],
            "Value": [1500000.0, 750000.0, 300000.0],
            "Start Date": [
                pd.Timestamp("2025-03-15"),
                pd.Timestamp("2025-03-10"),
                pd.Timestamp("2025-03-05"),
            ],
        })

        mock_ticker.insider_transactions = insider_df
        mock_ticker_cls.return_value = mock_ticker

        result = await ds.get_insider_transactions("AAPL")

        assert result["_ticker"] == "AAPL"
        assert result["summary"]["totalTransactions"] == 3
        assert result["summary"]["buyCount"] == 2
        assert result["summary"]["sellCount"] == 1
        assert result["summary"]["totalBuyValue"] == 1800000.0
        assert result["summary"]["totalSellValue"] == 750000.0
        assert len(result["transactions"]) == 3
        assert result["transactions"][0]["insider"] == "John Doe"
        assert result["transactions"][0]["type"] == "Buy"
        assert result["transactions"][0]["date"] == "2025-03-15"

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_insider_transactions_empty(self, mock_ticker_cls, ds):
        """Empty DataFrame raises NoDataAvailableError."""
        mock_ticker = MagicMock()
        mock_ticker.info = _SAMPLE_INFO
        mock_ticker.insider_transactions = pd.DataFrame()
        mock_ticker_cls.return_value = mock_ticker

        with pytest.raises(NoDataAvailableError, match="No insider transaction"):
            await ds.get_insider_transactions("AAPL")

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_insider_transactions_invalid_ticker(self, mock_ticker_cls, ds):
        """Invalid ticker (empty info) raises TickerNotFoundError."""
        mock_ticker = MagicMock()
        mock_ticker.info = {}
        mock_ticker_cls.return_value = mock_ticker

        with pytest.raises(TickerNotFoundError):
            await ds.get_insider_transactions("INVALID")

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_insider_transactions_api_error(self, mock_ticker_cls, ds):
        """Unexpected exception is wrapped in ExternalAPIError."""
        mock_ticker_cls.side_effect = RuntimeError("network failure")

        with pytest.raises(ExternalAPIError, match="get_insider_transactions failed"):
            await ds.get_insider_transactions("AAPL")


# ---------------------------------------------------------------------------
# get_upgrades_downgrades tests
# ---------------------------------------------------------------------------


class TestGetUpgradesDowngrades:
    """Tests for YFinanceDataSource.get_upgrades_downgrades."""

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_upgrades_downgrades_success(self, mock_ticker_cls, ds):
        """Valid DataFrame returns correct structure with rating entries."""
        mock_ticker = MagicMock()
        mock_ticker.info = _SAMPLE_INFO

        upgrades_df = pd.DataFrame(
            {
                "Firm": ["Goldman Sachs", "Morgan Stanley", "JP Morgan"],
                "ToGrade": ["Buy", "Overweight", "Neutral"],
                "FromGrade": ["Neutral", "Equal-Weight", "Overweight"],
                "Action": ["upgrade", "init", "downgrade"],
            },
            index=pd.DatetimeIndex([
                pd.Timestamp("2025-04-15"),
                pd.Timestamp("2025-04-10"),
                pd.Timestamp("2025-04-05"),
            ]),
        )

        mock_ticker.upgrades_downgrades = upgrades_df
        mock_ticker_cls.return_value = mock_ticker

        result = await ds.get_upgrades_downgrades("AAPL")

        assert result["_ticker"] == "AAPL"
        assert len(result["upgrades_downgrades"]) == 3
        first = result["upgrades_downgrades"][0]
        assert first["firm"] == "Goldman Sachs"
        assert first["toGrade"] == "Buy"
        assert first["fromGrade"] == "Neutral"
        assert first["action"] == "upgrade"
        assert first["date"] == "2025-04-15"

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_upgrades_downgrades_empty(self, mock_ticker_cls, ds):
        """Empty DataFrame raises NoDataAvailableError."""
        mock_ticker = MagicMock()
        mock_ticker.info = _SAMPLE_INFO
        mock_ticker.upgrades_downgrades = pd.DataFrame()
        mock_ticker_cls.return_value = mock_ticker

        with pytest.raises(NoDataAvailableError, match="No upgrades/downgrades"):
            await ds.get_upgrades_downgrades("AAPL")

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_upgrades_downgrades_api_error(self, mock_ticker_cls, ds):
        """Unexpected exception is wrapped in ExternalAPIError."""
        mock_ticker_cls.side_effect = RuntimeError("network failure")

        with pytest.raises(ExternalAPIError, match="get_upgrades_downgrades failed"):
            await ds.get_upgrades_downgrades("AAPL")


# ---------------------------------------------------------------------------
# get_earnings_dates tests
# ---------------------------------------------------------------------------


class TestGetEarningsDates:
    """Tests for YFinanceDataSource.get_earnings_dates."""

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_earnings_dates_success(self, mock_ticker_cls, ds):
        """Valid earnings dates DataFrame returns correct structure."""
        mock_ticker = MagicMock()
        mock_ticker.info = _SAMPLE_INFO

        # One future date, two past dates
        future_date = pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=30)
        past_date1 = pd.Timestamp("2025-01-30", tz="UTC")
        past_date2 = pd.Timestamp("2024-10-31", tz="UTC")

        earnings_df = pd.DataFrame(
            {
                "EPS Estimate": [2.35, 2.10, 1.95],
                "Reported EPS": [None, 2.18, 2.01],
                "Surprise(%)": [None, 3.81, 3.08],
            },
            index=pd.DatetimeIndex([future_date, past_date1, past_date2]),
        )

        mock_ticker.earnings_dates = earnings_df
        mock_ticker_cls.return_value = mock_ticker

        result = await ds.get_earnings_dates("AAPL")

        assert result["_ticker"] == "AAPL"
        assert len(result["earnings_dates"]) == 3

        # First entry is upcoming
        assert result["earnings_dates"][0]["isUpcoming"] is True
        assert result["earnings_dates"][0]["epsEstimate"] == 2.35
        assert result["earnings_dates"][0]["reportedEps"] is None

        # Second entry is past
        assert result["earnings_dates"][1]["isUpcoming"] is False
        assert result["earnings_dates"][1]["reportedEps"] == 2.18
        assert result["earnings_dates"][1]["surprisePct"] == 3.81

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_earnings_dates_empty(self, mock_ticker_cls, ds):
        """Empty DataFrame raises NoDataAvailableError."""
        mock_ticker = MagicMock()
        mock_ticker.info = _SAMPLE_INFO
        mock_ticker.earnings_dates = pd.DataFrame()
        mock_ticker_cls.return_value = mock_ticker

        with pytest.raises(NoDataAvailableError, match="No earnings date"):
            await ds.get_earnings_dates("AAPL")

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_earnings_dates_api_error(self, mock_ticker_cls, ds):
        """Unexpected exception is wrapped in ExternalAPIError."""
        mock_ticker_cls.side_effect = RuntimeError("network failure")

        with pytest.raises(ExternalAPIError, match="get_earnings_dates failed"):
            await ds.get_earnings_dates("AAPL")


# ---------------------------------------------------------------------------
# get_stock_news tests
# ---------------------------------------------------------------------------


class TestGetStockNews:
    """Tests for YFinanceDataSource.get_stock_news."""

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_stock_news_old_format(self, mock_ticker_cls, ds):
        """Old yfinance news format (flat dicts) returns correct structure."""
        mock_ticker = MagicMock()
        mock_ticker.info = _SAMPLE_INFO
        mock_ticker.news = [
            {
                "title": "Apple Earnings Beat Expectations",
                "publisher": "Reuters",
                "providerPublishTime": 1700000000,
                "link": "https://example.com/apple-news",
                "relatedTickers": ["AAPL", "MSFT"],
            },
            {
                "title": "Apple Launches New Product",
                "publisher": "Bloomberg",
                "providerPublishTime": 1699900000,
                "link": "https://example.com/apple-product",
                "relatedTickers": ["AAPL"],
            },
        ]
        mock_ticker_cls.return_value = mock_ticker

        result = await ds.get_stock_news("AAPL")

        assert result["_ticker"] == "AAPL"
        assert len(result["news"]) == 2
        assert result["news"][0]["title"] == "Apple Earnings Beat Expectations"
        assert result["news"][0]["publisher"] == "Reuters"
        assert result["news"][0]["link"] == "https://example.com/apple-news"
        assert result["news"][0]["relatedTickers"] == ["AAPL", "MSFT"]
        assert result["news"][0]["date"] is not None

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_stock_news_new_format(self, mock_ticker_cls, ds):
        """New yfinance news format (nested under 'content') returns correct structure."""
        mock_ticker = MagicMock()
        mock_ticker.info = _SAMPLE_INFO
        mock_ticker.news = [
            {
                "content": {
                    "title": "Apple Q2 Results",
                    "provider": {"displayName": "CNBC"},
                    "pubDate": "2026-05-14T14:16:00Z",
                    "canonicalUrl": {"url": "https://cnbc.com/apple-q2"},
                },
                "relatedTickers": ["AAPL"],
            },
        ]
        mock_ticker_cls.return_value = mock_ticker

        result = await ds.get_stock_news("AAPL")

        assert result["_ticker"] == "AAPL"
        assert len(result["news"]) == 1
        assert result["news"][0]["title"] == "Apple Q2 Results"
        assert result["news"][0]["publisher"] == "CNBC"
        assert result["news"][0]["link"] == "https://cnbc.com/apple-q2"
        assert "2026-05-14" in result["news"][0]["date"]

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_stock_news_empty(self, mock_ticker_cls, ds):
        """Empty news list raises NoDataAvailableError."""
        mock_ticker = MagicMock()
        mock_ticker.info = _SAMPLE_INFO
        mock_ticker.news = []
        mock_ticker_cls.return_value = mock_ticker

        with pytest.raises(NoDataAvailableError, match="No news"):
            await ds.get_stock_news("AAPL")

    @pytest.mark.asyncio
    @patch("src.data_sources.yfinance_source.yf.Ticker")
    async def test_get_stock_news_api_error(self, mock_ticker_cls, ds):
        """Unexpected exception is wrapped in ExternalAPIError."""
        mock_ticker_cls.side_effect = RuntimeError("network failure")

        with pytest.raises(ExternalAPIError, match="get_stock_news failed"):
            await ds.get_stock_news("AAPL")
