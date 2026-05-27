"""Integration tests for representative MCP tools — end-to-end through data source and formatter.

Tests cover:
- list_tool_constants (static data, no mocking)
- get_stock_info (mocked yfinance)
- is_trading_day (exchange_calendars, no external API)
- get_market_status (exchange_calendars, no external API)
- get_insider_transactions (mocked data source)
- get_upgrades_downgrades (mocked data source)
- get_earnings_dates (mocked data source)
- get_stock_news (mocked data source)
- get_stocktwits_sentiment (mocked urllib)
- get_reddit_sentiment (mocked urllib)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp.server.fastmcp import FastMCP

from src.data_sources.cache import get_cache
from src.data_sources.yfinance_source import YFinanceDataSource
from src.tools.helpers import register_helper_tools
from src.tools.market_calendar import register_market_calendar_tools
from src.tools.news_sentiment import register_news_extras_tools, register_news_sentiment_tools
from src.tools.social_sentiment import register_social_sentiment_tools
from src.tools.stock_data import register_stock_data_tools


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
    """Create a FastMCP instance with all tool groups registered."""
    mcp = FastMCP("test")
    ds = YFinanceDataSource()
    register_helper_tools(mcp)
    register_stock_data_tools(mcp, ds)
    register_market_calendar_tools(mcp, ds)
    register_news_sentiment_tools(mcp, ds)
    register_news_extras_tools(mcp, ds)
    register_social_sentiment_tools(mcp)
    return mcp


def _get_tool_fn(mcp: FastMCP, name: str):
    """Extract the raw async tool function from FastMCP internals."""
    return mcp._tool_manager._tools[name].fn


# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

MOCK_AAPL_INFO: dict = {
    "shortName": "Apple Inc.",
    "longName": "Apple Inc.",
    "symbol": "AAPL",
    "quoteType": "EQUITY",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "country": "United States",
    "website": "https://www.apple.com",
    "fullTimeEmployees": 164000,
    "currentPrice": 195.50,
    "previousClose": 194.27,
    "fiftyTwoWeekHigh": 199.62,
    "fiftyTwoWeekLow": 124.17,
    "fiftyDayAverage": 178.45,
    "twoHundredDayAverage": 168.93,
    "beta": 1.29,
    "volume": 54321000,
    "exchange": "NMS",
    "currency": "USD",
    "marketState": "REGULAR",
    "exchangeTimezoneName": "America/New_York",
}

MOCK_CORN_INFO: dict = {
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
    "longBusinessSummary": "The fund seeks to track the price of corn futures contracts.",
}


# ---------------------------------------------------------------------------
# 1-3. list_tool_constants tests (no mocking — static data)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tool_constants_all(mcp_app: FastMCP):
    """list_tool_constants with no arguments returns all constant categories."""
    fn = _get_tool_fn(mcp_app, "list_tool_constants")
    result = await fn()

    assert isinstance(result, str)
    # Should contain all five category headers
    for category in ("period", "interval", "exchange", "index", "indicator"):
        assert category in result


@pytest.mark.asyncio
async def test_list_tool_constants_period(mcp_app: FastMCP):
    """list_tool_constants with kind='period' returns only period values."""
    fn = _get_tool_fn(mcp_app, "list_tool_constants")
    result = await fn(kind="period")

    assert isinstance(result, str)
    assert "period" in result
    # Should contain known period values
    assert "1d" in result
    assert "1y" in result
    assert "max" in result
    # Should NOT contain other categories
    assert "## exchange" not in result
    assert "## index" not in result


@pytest.mark.asyncio
async def test_list_tool_constants_json(mcp_app: FastMCP):
    """list_tool_constants with format='json' returns valid JSON."""
    fn = _get_tool_fn(mcp_app, "list_tool_constants")
    result = await fn(format="json")

    assert isinstance(result, str)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)
    assert "period" in parsed
    assert isinstance(parsed["period"], list)
    assert "1d" in parsed["period"]


# ---------------------------------------------------------------------------
# 4-6. get_stock_info tests (mocked yfinance)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_stock_info_tool_markdown(mcp_app: FastMCP):
    """get_stock_info returns markdown containing the company name."""
    fn = _get_tool_fn(mcp_app, "get_stock_info")

    with patch("src.data_sources.validation.yf") as mock_yf, \
         patch("src.data_sources.yfinance_source.yf") as mock_yf_ds:
        # Mock validation: yf.Ticker("AAPL").info returns valid info
        mock_val_ticker = MagicMock()
        mock_val_ticker.info = MOCK_AAPL_INFO
        mock_yf.Ticker.return_value = mock_val_ticker

        # Mock data source: yf.Ticker("AAPL").info
        mock_ds_ticker = MagicMock()
        mock_ds_ticker.info = MOCK_AAPL_INFO
        mock_yf_ds.Ticker.return_value = mock_ds_ticker

        result = await fn(ticker="AAPL", format="markdown")

    assert isinstance(result, str)
    assert "Apple Inc." in result
    assert "# Stock Info" in result
    assert "$195.50" in result
    assert "Technology" in result


@pytest.mark.asyncio
async def test_get_stock_info_tool_json(mcp_app: FastMCP):
    """get_stock_info with format='json' returns a valid JSON string."""
    fn = _get_tool_fn(mcp_app, "get_stock_info")

    with patch("src.data_sources.validation.yf") as mock_yf, \
         patch("src.data_sources.yfinance_source.yf") as mock_yf_ds:
        mock_val_ticker = MagicMock()
        mock_val_ticker.info = MOCK_AAPL_INFO
        mock_yf.Ticker.return_value = mock_val_ticker

        mock_ds_ticker = MagicMock()
        mock_ds_ticker.info = MOCK_AAPL_INFO
        mock_yf_ds.Ticker.return_value = mock_ds_ticker

        result = await fn(ticker="AAPL", format="json")

    assert isinstance(result, str)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)
    assert parsed["_ticker"] == "AAPL"
    assert parsed["identity"]["shortName"] == "Apple Inc."
    assert parsed["price"]["currentPrice"] == 195.50


@pytest.mark.asyncio
async def test_get_stock_info_tool_invalid_ticker(mcp_app: FastMCP):
    """get_stock_info with an invalid ticker returns 'Error: ...' string, not an exception."""
    fn = _get_tool_fn(mcp_app, "get_stock_info")

    with patch("src.data_sources.validation.yf") as mock_yf:
        # Ticker that returns no shortName -> TickerNotFoundError
        mock_val_ticker = MagicMock()
        mock_val_ticker.info = {}  # No shortName = invalid
        mock_yf.Ticker.return_value = mock_val_ticker
        mock_yf.Search.return_value = MagicMock(quotes=[])

        result = await fn(ticker="ZZZZZ", format="markdown")

    assert isinstance(result, str)
    assert result.startswith("Error:")


@pytest.mark.asyncio
async def test_get_stock_info_etf_markdown(mcp_app: FastMCP):
    """get_stock_info for an ETF includes fund_info section in markdown."""
    fn = _get_tool_fn(mcp_app, "get_stock_info")

    with patch("src.data_sources.validation.yf") as mock_yf, \
         patch("src.data_sources.yfinance_source.yf") as mock_yf_ds:
        mock_val_ticker = MagicMock()
        mock_val_ticker.info = MOCK_CORN_INFO
        mock_yf.Ticker.return_value = mock_val_ticker

        mock_ds_ticker = MagicMock()
        mock_ds_ticker.info = MOCK_CORN_INFO
        mock_yf_ds.Ticker.return_value = mock_ds_ticker

        result = await fn(ticker="CORN", format="markdown")

    assert isinstance(result, str)
    assert "# ETF Info" in result
    assert "Teucrium Corn Fund" in result
    assert "## Fund Info" in result
    assert "Commodities Focused" in result
    assert "Teucrium" in result
    assert "$263.01M" in result  # totalAssets


@pytest.mark.asyncio
async def test_get_stock_info_etf_json(mcp_app: FastMCP):
    """get_stock_info for an ETF includes fund_info in JSON output."""
    fn = _get_tool_fn(mcp_app, "get_stock_info")

    with patch("src.data_sources.validation.yf") as mock_yf, \
         patch("src.data_sources.yfinance_source.yf") as mock_yf_ds:
        mock_val_ticker = MagicMock()
        mock_val_ticker.info = MOCK_CORN_INFO
        mock_yf.Ticker.return_value = mock_val_ticker

        mock_ds_ticker = MagicMock()
        mock_ds_ticker.info = MOCK_CORN_INFO
        mock_yf_ds.Ticker.return_value = mock_ds_ticker

        result = await fn(ticker="CORN", format="json")

    parsed = json.loads(result)
    assert parsed["identity"]["quoteType"] == "ETF"
    assert parsed["fund_info"]["category"] == "Commodities Focused"
    assert parsed["fund_info"]["totalAssets"] == 263009776.0
    assert parsed["fund_info"]["navPrice"] == 18.5351


# ---------------------------------------------------------------------------
# 7-8. is_trading_day tests (exchange_calendars — no external API)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_trading_day_weekday(mcp_app: FastMCP):
    """is_trading_day on a known NYSE trading day returns 'Yes'."""
    fn = _get_tool_fn(mcp_app, "is_trading_day")

    # 2025-01-02 is a Thursday, NYSE was open
    result = await fn(date="2025-01-02", exchange="XNYS")

    assert isinstance(result, str)
    assert "Yes" in result


@pytest.mark.asyncio
async def test_is_trading_day_weekend(mcp_app: FastMCP):
    """is_trading_day on a Saturday returns 'No'."""
    fn = _get_tool_fn(mcp_app, "is_trading_day")

    # 2025-01-04 is a Saturday
    result = await fn(date="2025-01-04", exchange="XNYS")

    assert isinstance(result, str)
    assert "No" in result
    assert "Weekend" in result


# ---------------------------------------------------------------------------
# 9. get_market_status test (exchange_calendars — no external API)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_market_status_returns_string(mcp_app: FastMCP):
    """get_market_status returns a non-empty string with market state info."""
    fn = _get_tool_fn(mcp_app, "get_market_status")

    result = await fn(exchange="XNYS")

    assert isinstance(result, str)
    assert len(result) > 0
    assert "# Market Status" in result
    assert "Market State" in result


# ---------------------------------------------------------------------------
# 10-12. get_insider_transactions tests (mocked data source)
# ---------------------------------------------------------------------------


MOCK_INSIDER_DATA = {
    "_ticker": "AAPL",
    "summary": {
        "totalTransactions": 3,
        "buyCount": 2,
        "sellCount": 1,
        "otherCount": 0,
        "totalBuyValue": 1800000.0,
        "totalSellValue": 750000.0,
    },
    "transactions": [
        {
            "insider": "John Doe",
            "type": "Buy",
            "text": "Purchase of shares",
            "shares": 10000,
            "value": 1500000.0,
            "date": "2025-03-15",
        },
        {
            "insider": "Jane Smith",
            "type": "Sell",
            "text": "Sale of shares",
            "shares": 5000,
            "value": 750000.0,
            "date": "2025-03-10",
        },
        {
            "insider": "Bob Lee",
            "type": "Buy",
            "text": "Purchase of shares",
            "shares": 2000,
            "value": 300000.0,
            "date": "2025-03-05",
        },
    ],
}


class TestGetInsiderTransactions:
    """Tests for the get_insider_transactions MCP tool."""

    @pytest.mark.asyncio
    async def test_insider_transactions_markdown(self, mcp_app: FastMCP):
        """get_insider_transactions returns markdown with insider data."""
        fn = _get_tool_fn(mcp_app, "get_insider_transactions")

        with patch("src.data_sources.validation.yf") as mock_yf, \
             patch.object(
                 YFinanceDataSource,
                 "get_insider_transactions",
                 new_callable=AsyncMock,
                 return_value=MOCK_INSIDER_DATA,
             ):
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = MOCK_AAPL_INFO
            mock_yf.Ticker.return_value = mock_val_ticker

            result = await fn(ticker="AAPL", format="markdown")

        assert isinstance(result, str)
        assert "# Insider Transactions" in result
        assert "John Doe" in result
        assert "Buy" in result
        assert "Sell" in result

    @pytest.mark.asyncio
    async def test_insider_transactions_json(self, mcp_app: FastMCP):
        """get_insider_transactions with format='json' returns valid JSON."""
        fn = _get_tool_fn(mcp_app, "get_insider_transactions")

        with patch("src.data_sources.validation.yf") as mock_yf, \
             patch.object(
                 YFinanceDataSource,
                 "get_insider_transactions",
                 new_callable=AsyncMock,
                 return_value=MOCK_INSIDER_DATA,
             ):
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = MOCK_AAPL_INFO
            mock_yf.Ticker.return_value = mock_val_ticker

            result = await fn(ticker="AAPL", format="json")

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["_ticker"] == "AAPL"
        assert parsed["summary"]["buyCount"] == 2

    @pytest.mark.asyncio
    async def test_insider_transactions_error(self, mcp_app: FastMCP):
        """get_insider_transactions with invalid ticker returns error string."""
        fn = _get_tool_fn(mcp_app, "get_insider_transactions")

        with patch("src.data_sources.validation.yf") as mock_yf:
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = {}
            mock_yf.Ticker.return_value = mock_val_ticker
            mock_yf.Search.return_value = MagicMock(quotes=[])

            result = await fn(ticker="ZZZZZ", format="markdown")

        assert isinstance(result, str)
        assert result.startswith("Error:")


# ---------------------------------------------------------------------------
# 13-15. get_upgrades_downgrades tests (mocked data source)
# ---------------------------------------------------------------------------


MOCK_UPGRADES_DATA = {
    "_ticker": "AAPL",
    "upgrades_downgrades": [
        {
            "date": "2025-04-15",
            "firm": "Goldman Sachs",
            "toGrade": "Buy",
            "fromGrade": "Neutral",
            "action": "upgrade",
        },
        {
            "date": "2025-04-10",
            "firm": "Morgan Stanley",
            "toGrade": "Overweight",
            "fromGrade": "Equal-Weight",
            "action": "init",
        },
    ],
}


class TestGetUpgradesDowngrades:
    """Tests for the get_upgrades_downgrades MCP tool."""

    @pytest.mark.asyncio
    async def test_upgrades_downgrades_markdown(self, mcp_app: FastMCP):
        """get_upgrades_downgrades returns markdown with rating changes."""
        fn = _get_tool_fn(mcp_app, "get_upgrades_downgrades")

        with patch("src.data_sources.validation.yf") as mock_yf, \
             patch.object(
                 YFinanceDataSource,
                 "get_upgrades_downgrades",
                 new_callable=AsyncMock,
                 return_value=MOCK_UPGRADES_DATA,
             ):
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = MOCK_AAPL_INFO
            mock_yf.Ticker.return_value = mock_val_ticker

            result = await fn(ticker="AAPL", format="markdown")

        assert isinstance(result, str)
        assert "# Upgrades/Downgrades" in result
        assert "Goldman Sachs" in result
        assert "upgrade" in result

    @pytest.mark.asyncio
    async def test_upgrades_downgrades_json(self, mcp_app: FastMCP):
        """get_upgrades_downgrades with format='json' returns valid JSON."""
        fn = _get_tool_fn(mcp_app, "get_upgrades_downgrades")

        with patch("src.data_sources.validation.yf") as mock_yf, \
             patch.object(
                 YFinanceDataSource,
                 "get_upgrades_downgrades",
                 new_callable=AsyncMock,
                 return_value=MOCK_UPGRADES_DATA,
             ):
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = MOCK_AAPL_INFO
            mock_yf.Ticker.return_value = mock_val_ticker

            result = await fn(ticker="AAPL", format="json")

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["_ticker"] == "AAPL"
        assert len(parsed["upgrades_downgrades"]) == 2

    @pytest.mark.asyncio
    async def test_upgrades_downgrades_error(self, mcp_app: FastMCP):
        """get_upgrades_downgrades with invalid ticker returns error string."""
        fn = _get_tool_fn(mcp_app, "get_upgrades_downgrades")

        with patch("src.data_sources.validation.yf") as mock_yf:
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = {}
            mock_yf.Ticker.return_value = mock_val_ticker
            mock_yf.Search.return_value = MagicMock(quotes=[])

            result = await fn(ticker="ZZZZZ", format="markdown")

        assert isinstance(result, str)
        assert result.startswith("Error:")


# ---------------------------------------------------------------------------
# 16-18. get_earnings_dates tests (mocked data source)
# ---------------------------------------------------------------------------


MOCK_EARNINGS_DATES_DATA = {
    "_ticker": "AAPL",
    "earnings_dates": [
        {
            "date": "2025-07-31",
            "epsEstimate": 2.35,
            "reportedEps": None,
            "surprisePct": None,
            "isUpcoming": True,
        },
        {
            "date": "2025-01-30",
            "epsEstimate": 2.10,
            "reportedEps": 2.18,
            "surprisePct": 3.81,
            "isUpcoming": False,
        },
    ],
}


class TestGetEarningsDates:
    """Tests for the get_earnings_dates MCP tool."""

    @pytest.mark.asyncio
    async def test_earnings_dates_markdown(self, mcp_app: FastMCP):
        """get_earnings_dates returns markdown with upcoming and past sections."""
        fn = _get_tool_fn(mcp_app, "get_earnings_dates")

        with patch("src.data_sources.validation.yf") as mock_yf, \
             patch.object(
                 YFinanceDataSource,
                 "get_earnings_dates",
                 new_callable=AsyncMock,
                 return_value=MOCK_EARNINGS_DATES_DATA,
             ):
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = MOCK_AAPL_INFO
            mock_yf.Ticker.return_value = mock_val_ticker

            result = await fn(ticker="AAPL", format="markdown")

        assert isinstance(result, str)
        assert "# Earnings Dates" in result
        assert "Upcoming" in result
        assert "Past" in result

    @pytest.mark.asyncio
    async def test_earnings_dates_json(self, mcp_app: FastMCP):
        """get_earnings_dates with format='json' returns valid JSON."""
        fn = _get_tool_fn(mcp_app, "get_earnings_dates")

        with patch("src.data_sources.validation.yf") as mock_yf, \
             patch.object(
                 YFinanceDataSource,
                 "get_earnings_dates",
                 new_callable=AsyncMock,
                 return_value=MOCK_EARNINGS_DATES_DATA,
             ):
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = MOCK_AAPL_INFO
            mock_yf.Ticker.return_value = mock_val_ticker

            result = await fn(ticker="AAPL", format="json")

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["_ticker"] == "AAPL"
        assert len(parsed["earnings_dates"]) == 2
        assert parsed["earnings_dates"][0]["isUpcoming"] is True

    @pytest.mark.asyncio
    async def test_earnings_dates_error(self, mcp_app: FastMCP):
        """get_earnings_dates with invalid ticker returns error string."""
        fn = _get_tool_fn(mcp_app, "get_earnings_dates")

        with patch("src.data_sources.validation.yf") as mock_yf:
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = {}
            mock_yf.Ticker.return_value = mock_val_ticker
            mock_yf.Search.return_value = MagicMock(quotes=[])

            result = await fn(ticker="ZZZZZ", format="markdown")

        assert isinstance(result, str)
        assert result.startswith("Error:")


# ---------------------------------------------------------------------------
# 19-21. get_stock_news tests (mocked data source)
# ---------------------------------------------------------------------------


MOCK_NEWS_DATA = {
    "_ticker": "AAPL",
    "news": [
        {
            "title": "Apple Earnings Beat Expectations",
            "publisher": "Reuters",
            "date": "2025-05-14 10:30",
            "link": "https://example.com/apple-news",
            "relatedTickers": ["AAPL", "MSFT"],
        },
        {
            "title": "Apple Launches New Product",
            "publisher": "Bloomberg",
            "date": "2025-05-13 08:15",
            "link": "https://example.com/apple-product",
            "relatedTickers": ["AAPL"],
        },
    ],
}


class TestGetStockNews:
    """Tests for the get_stock_news MCP tool."""

    @pytest.mark.asyncio
    async def test_stock_news_markdown(self, mcp_app: FastMCP):
        """get_stock_news returns markdown with news articles."""
        fn = _get_tool_fn(mcp_app, "get_stock_news")

        with patch("src.data_sources.validation.yf") as mock_yf, \
             patch.object(
                 YFinanceDataSource,
                 "get_stock_news",
                 new_callable=AsyncMock,
                 return_value=MOCK_NEWS_DATA,
             ):
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = MOCK_AAPL_INFO
            mock_yf.Ticker.return_value = mock_val_ticker

            result = await fn(ticker="AAPL", format="markdown")

        assert isinstance(result, str)
        assert "# Stock News" in result
        assert "Apple Earnings Beat Expectations" in result
        assert "Reuters" in result

    @pytest.mark.asyncio
    async def test_stock_news_json(self, mcp_app: FastMCP):
        """get_stock_news with format='json' returns valid JSON."""
        fn = _get_tool_fn(mcp_app, "get_stock_news")

        with patch("src.data_sources.validation.yf") as mock_yf, \
             patch.object(
                 YFinanceDataSource,
                 "get_stock_news",
                 new_callable=AsyncMock,
                 return_value=MOCK_NEWS_DATA,
             ):
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = MOCK_AAPL_INFO
            mock_yf.Ticker.return_value = mock_val_ticker

            result = await fn(ticker="AAPL", format="json")

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["_ticker"] == "AAPL"
        assert len(parsed["news"]) == 2

    @pytest.mark.asyncio
    async def test_stock_news_error(self, mcp_app: FastMCP):
        """get_stock_news with invalid ticker returns error string."""
        fn = _get_tool_fn(mcp_app, "get_stock_news")

        with patch("src.data_sources.validation.yf") as mock_yf:
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = {}
            mock_yf.Ticker.return_value = mock_val_ticker
            mock_yf.Search.return_value = MagicMock(quotes=[])

            result = await fn(ticker="ZZZZZ", format="markdown")

        assert isinstance(result, str)
        assert result.startswith("Error:")


# ---------------------------------------------------------------------------
# 22-25. get_stocktwits_sentiment tests (mocked urllib)
# ---------------------------------------------------------------------------


MOCK_STOCKTWITS_API_RESPONSE = json.dumps({
    "messages": [
        {
            "body": "AAPL is looking bullish!",
            "created_at": "2025-05-14T12:00:00Z",
            "entities": {"sentiment": {"basic": "Bullish"}},
            "user": {"username": "trader1"},
        },
        {
            "body": "Bearish on AAPL right now",
            "created_at": "2025-05-14T11:00:00Z",
            "entities": {"sentiment": {"basic": "Bearish"}},
            "user": {"username": "trader2"},
        },
        {
            "body": "Watching AAPL closely",
            "created_at": "2025-05-14T10:00:00Z",
            "entities": {"sentiment": None},
            "user": {"username": "trader3"},
        },
    ]
}).encode("utf-8")


class TestGetStockTwitsSentiment:
    """Tests for the get_stocktwits_sentiment MCP tool."""

    @pytest.mark.asyncio
    async def test_stocktwits_sentiment_markdown(self, mcp_app: FastMCP):
        """get_stocktwits_sentiment returns markdown with sentiment data."""
        fn = _get_tool_fn(mcp_app, "get_stocktwits_sentiment")

        with patch("src.data_sources.validation.yf") as mock_yf, \
             patch("src.data_sources.social_sentiment.urllib.request.urlopen") as mock_urlopen:
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = MOCK_AAPL_INFO
            mock_yf.Ticker.return_value = mock_val_ticker

            mock_resp = MagicMock()
            mock_resp.read.return_value = MOCK_STOCKTWITS_API_RESPONSE
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = await fn(ticker="AAPL", format="markdown")

        assert isinstance(result, str)
        assert "StockTwits Sentiment" in result
        assert "Bullish" in result
        assert "Bearish" in result

    @pytest.mark.asyncio
    async def test_stocktwits_sentiment_json(self, mcp_app: FastMCP):
        """get_stocktwits_sentiment with format='json' returns valid JSON."""
        fn = _get_tool_fn(mcp_app, "get_stocktwits_sentiment")

        with patch("src.data_sources.validation.yf") as mock_yf, \
             patch("src.data_sources.social_sentiment.urllib.request.urlopen") as mock_urlopen:
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = MOCK_AAPL_INFO
            mock_yf.Ticker.return_value = mock_val_ticker

            mock_resp = MagicMock()
            mock_resp.read.return_value = MOCK_STOCKTWITS_API_RESPONSE
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = await fn(ticker="AAPL", format="json")

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["ticker"] == "AAPL"
        assert parsed["sentiment_summary"]["bullish_count"] == 1
        assert parsed["sentiment_summary"]["bearish_count"] == 1
        assert parsed["sentiment_summary"]["neutral_count"] == 1

    @pytest.mark.asyncio
    async def test_stocktwits_sentiment_network_error(self, mcp_app: FastMCP):
        """get_stocktwits_sentiment gracefully degrades on network errors."""
        fn = _get_tool_fn(mcp_app, "get_stocktwits_sentiment")

        with patch("src.data_sources.validation.yf") as mock_yf, \
             patch("src.data_sources.social_sentiment.urllib.request.urlopen") as mock_urlopen:
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = MOCK_AAPL_INFO
            mock_yf.Ticker.return_value = mock_val_ticker

            import urllib.error
            mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

            result = await fn(ticker="AAPL", format="markdown")

        assert isinstance(result, str)
        # Should get the unavailable message, not crash
        assert "unavailable" in result.lower() or "AAPL" in result

    @pytest.mark.asyncio
    async def test_stocktwits_sentiment_unavailable_formatting(self, mcp_app: FastMCP):
        """get_stocktwits_sentiment formats 'unavailable' result properly."""
        fn = _get_tool_fn(mcp_app, "get_stocktwits_sentiment")

        with patch("src.data_sources.validation.yf") as mock_yf, \
             patch("src.data_sources.social_sentiment.urllib.request.urlopen") as mock_urlopen:
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = MOCK_AAPL_INFO
            mock_yf.Ticker.return_value = mock_val_ticker

            import urllib.error
            mock_urlopen.side_effect = urllib.error.HTTPError(
                url="", code=429, msg="Too Many Requests", hdrs={}, fp=None
            )

            result = await fn(ticker="AAPL", format="markdown")

        assert isinstance(result, str)
        # Should contain the ticker and rate limit info
        assert "AAPL" in result
        assert "unavailable" in result.lower() or "Rate limit" in result


# ---------------------------------------------------------------------------
# 26-29. get_reddit_sentiment tests (mocked urllib)
# ---------------------------------------------------------------------------


MOCK_REDDIT_API_RESPONSE = json.dumps({
    "data": {
        "children": [
            {
                "data": {
                    "title": "AAPL is undervalued right now",
                    "score": 150,
                    "num_comments": 42,
                    "subreddit": "stocks",
                    "permalink": "/r/stocks/comments/abc123/aapl_undervalued/",
                    "created_utc": 1715700000.0,
                }
            },
            {
                "data": {
                    "title": "Apple earnings discussion thread",
                    "score": 500,
                    "num_comments": 200,
                    "subreddit": "wallstreetbets",
                    "permalink": "/r/wallstreetbets/comments/def456/apple_earnings/",
                    "created_utc": 1715600000.0,
                }
            },
        ]
    }
}).encode("utf-8")


class TestGetRedditSentiment:
    """Tests for the get_reddit_sentiment MCP tool."""

    @pytest.mark.asyncio
    async def test_reddit_sentiment_markdown(self, mcp_app: FastMCP):
        """get_reddit_sentiment returns markdown with Reddit posts."""
        fn = _get_tool_fn(mcp_app, "get_reddit_sentiment")

        with patch("src.data_sources.validation.yf") as mock_yf, \
             patch("src.data_sources.social_sentiment.urllib.request.urlopen") as mock_urlopen:
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = MOCK_AAPL_INFO
            mock_yf.Ticker.return_value = mock_val_ticker

            mock_resp = MagicMock()
            mock_resp.read.return_value = MOCK_REDDIT_API_RESPONSE
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = await fn(ticker="AAPL", format="markdown")

        assert isinstance(result, str)
        assert "Reddit Discussion" in result
        assert "AAPL is undervalued right now" in result
        assert "r/stocks" in result or "stocks" in result

    @pytest.mark.asyncio
    async def test_reddit_sentiment_json(self, mcp_app: FastMCP):
        """get_reddit_sentiment with format='json' returns valid JSON."""
        fn = _get_tool_fn(mcp_app, "get_reddit_sentiment")

        with patch("src.data_sources.validation.yf") as mock_yf, \
             patch("src.data_sources.social_sentiment.urllib.request.urlopen") as mock_urlopen:
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = MOCK_AAPL_INFO
            mock_yf.Ticker.return_value = mock_val_ticker

            mock_resp = MagicMock()
            mock_resp.read.return_value = MOCK_REDDIT_API_RESPONSE
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = await fn(ticker="AAPL", format="json")

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["ticker"] == "AAPL"
        assert parsed["post_count"] == 2
        assert len(parsed["posts"]) == 2

    @pytest.mark.asyncio
    async def test_reddit_sentiment_network_error(self, mcp_app: FastMCP):
        """get_reddit_sentiment gracefully degrades on network errors."""
        fn = _get_tool_fn(mcp_app, "get_reddit_sentiment")

        with patch("src.data_sources.validation.yf") as mock_yf, \
             patch("src.data_sources.social_sentiment.urllib.request.urlopen") as mock_urlopen:
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = MOCK_AAPL_INFO
            mock_yf.Ticker.return_value = mock_val_ticker

            import urllib.error
            mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

            result = await fn(ticker="AAPL", format="markdown")

        assert isinstance(result, str)
        # Should get the unavailable message, not crash
        assert "unavailable" in result.lower() or "AAPL" in result

    @pytest.mark.asyncio
    async def test_reddit_sentiment_empty_results(self, mcp_app: FastMCP):
        """get_reddit_sentiment with no posts returns properly formatted result."""
        fn = _get_tool_fn(mcp_app, "get_reddit_sentiment")

        empty_response = json.dumps({
            "data": {"children": []}
        }).encode("utf-8")

        with patch("src.data_sources.validation.yf") as mock_yf, \
             patch("src.data_sources.social_sentiment.urllib.request.urlopen") as mock_urlopen:
            mock_val_ticker = MagicMock()
            mock_val_ticker.info = MOCK_AAPL_INFO
            mock_yf.Ticker.return_value = mock_val_ticker

            mock_resp = MagicMock()
            mock_resp.read.return_value = empty_response
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = await fn(ticker="AAPL", format="markdown")

        assert isinstance(result, str)
        assert "Reddit Discussion" in result
        assert "No recent posts" in result or "0" in result
