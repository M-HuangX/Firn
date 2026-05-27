"""MCP tool registrations for stock data retrieval — quotes, price history, dividends, search.

Registers 4 MVP tools with a FastMCP server instance:

- ``get_stock_info``: Company identity, current price, and market information.
- ``get_historical_prices``: Historical OHLCV price data with summary statistics.
- ``get_dividends``: Dividend history, yield, and payout analysis.
- ``search_stocks``: Search for stocks by name, ticker, or keyword.
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from ..data_sources.exceptions import DataSourceError
from ..data_sources.validation import validate_ticker_lenient
from ..data_sources.yfinance_source import YFinanceDataSource
from ..formatting.json_fmt import format_json
from ..formatting.markdown import (
    format_dividends,
    format_historical_prices,
    format_search_results,
    format_stock_info,
)

logger = logging.getLogger(__name__)


def register_stock_data_tools(mcp: FastMCP, data_source: YFinanceDataSource) -> None:
    """Register all stock-data MCP tools on the given FastMCP server.

    Args:
        mcp: The FastMCP server instance to register tools on.
        data_source: The YFinanceDataSource instance used for data fetching.
    """

    @mcp.tool()
    async def get_stock_info(ticker: str, format: str = "markdown") -> str:
        """Get company identity, current price, and market information for a stock.

        Returns ~20 fields including: company name, sector, industry, current price,
        52-week range, moving averages, beta, volume, exchange, and currency.
        Does NOT include financial ratios (use get_financial_metrics for that).

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "MSFT", "NESN.SW")
            format: Output format - "markdown" (default) or "json"
        """
        try:
            ticker = await validate_ticker_lenient(ticker)
            data = await data_source.get_stock_info(ticker)
            if format == "json":
                return format_json(data)
            return format_stock_info(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"

    @mcp.tool()
    async def get_historical_prices(
        ticker: str,
        period: str = "6mo",
        interval: str = "1d",
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 250,
        format: str = "markdown",
    ) -> str:
        """Get historical OHLCV price data for a stock.

        Returns summary statistics (date range, price change %, period high/low,
        average volume) followed by an OHLCV table. Use this for trend analysis,
        charting, or computing custom indicators.

        When start_date is provided, it overrides the period parameter.
        All prices are split-adjusted by default.

        Intraday interval limits: 1m=7d max, 5m/15m/30m=60d max, 60m/1h=730d max.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "MSFT", "NESN.SW")
            period: Data period - "1d","5d","1mo","3mo","6mo","1y","2y","5y","10y","ytd","max"
            interval: Candle interval - "1m","2m","5m","15m","30m","60m","90m","1h","1d","5d","1wk","1mo","3mo"
            start_date: Start date "YYYY-MM-DD" (overrides period if provided)
            end_date: End date "YYYY-MM-DD" (defaults to today)
            limit: Maximum number of price rows to return (default 250)
            format: Output format - "markdown" (default) or "json"
        """
        try:
            ticker = await validate_ticker_lenient(ticker)
            data = await data_source.get_historical_prices(
                ticker,
                period=period,
                interval=interval,
                start_date=start_date,
                end_date=end_date,
            )
            # Trim prices to the requested limit (tool-layer concern)
            if data.get("prices") and len(data["prices"]) > limit:
                data["prices"] = data["prices"][-limit:]
                data["summary"]["note_trimmed"] = (
                    f"Showing last {limit} of {data['summary']['total_rows']} "
                    f"total data points."
                )
            if format == "json":
                return format_json(data)
            return format_historical_prices(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"

    @mcp.tool()
    async def get_dividends(
        ticker: str,
        years: int = 10,
        format: str = "markdown",
    ) -> str:
        """Get dividend payment history and yield analysis for a stock.

        Returns current dividend yield, annual rate, payout ratio, ex-dividend date,
        5-year average yield, consecutive years of payments, and a full dividend
        history table. Default 10 years of history to support dividend growth analysis.

        Use this to assess dividend sustainability, growth trends, and income potential.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "JNJ", "KO")
            years: Number of years of dividend history to include (default 10)
            format: Output format - "markdown" (default) or "json"
        """
        try:
            ticker = await validate_ticker_lenient(ticker)
            data = await data_source.get_dividends(ticker, years=years)
            if format == "json":
                return format_json(data)
            return format_dividends(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"

    @mcp.tool()
    async def search_stocks(
        query: str,
        limit: int = 10,
        format: str = "markdown",
    ) -> str:
        """Search for stocks by company name, ticker symbol, or keyword.

        Returns a table of matching securities with: Symbol, Name, Exchange,
        Sector, Industry, and Quote Type (equity, etf, index, etc.).

        Use this when you need to find the correct ticker symbol for a company,
        discover related stocks, or look up securities by name.

        Args:
            query: Search query (e.g., "Apple", "semiconductor", "TSLA")
            limit: Maximum number of results to return (default 10)
            format: Output format - "markdown" (default) or "json"
        """
        try:
            data = await data_source.search_stocks(query, limit=limit)
            if format == "json":
                return format_json(data)
            return format_search_results(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"
