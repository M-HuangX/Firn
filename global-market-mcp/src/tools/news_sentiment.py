"""MCP tool registrations for news, insider transactions, upgrades/downgrades, and earnings dates.

Tools are split into two registration functions:
- register_news_sentiment_tools: insider_transactions + upgrades_downgrades (active)
- register_news_extras_tools: earnings_dates + stock_news (reserved, not registered by default)
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..data_sources.exceptions import DataSourceError
from ..data_sources.validation import validate_ticker_lenient
from ..data_sources.yfinance_source import YFinanceDataSource
from ..formatting.json_fmt import format_json
from ..formatting.markdown import (
    format_earnings_dates,
    format_insider_transactions,
    format_stock_news,
    format_upgrades_downgrades,
)


def register_news_sentiment_tools(
    mcp: FastMCP, data_source: YFinanceDataSource
) -> None:
    """Register insider transactions and upgrades/downgrades tools.

    Args:
        mcp: The FastMCP server to register tools on.
        data_source: The YFinanceDataSource instance for fetching data.
    """

    @mcp.tool()
    async def get_insider_transactions(
        ticker: str,
        limit: int = 20,
        format: str = "markdown",
    ) -> str:
        """Fetch recent insider transactions (buys and sells) for a stock.

        Returns:
        - Summary: total transaction count, buy/sell breakdown, and total values.
        - Transaction table: date, insider name, transaction type, shares, and value.

        Use this tool to assess insider sentiment — heavy insider buying can
        signal management confidence, while concentrated selling may indicate
        concerns or routine diversification.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "MSFT").
            limit: Maximum number of transactions to show (default 20).
            format: "markdown" (default) or "json".
        """
        try:
            ticker = await validate_ticker_lenient(ticker)
            data = await data_source.get_insider_transactions(ticker, limit=limit)
            if format == "json":
                return format_json(data)
            return format_insider_transactions(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"

    @mcp.tool()
    async def get_upgrades_downgrades(
        ticker: str,
        limit: int = 20,
        format: str = "markdown",
    ) -> str:
        """Fetch recent analyst upgrades and downgrades for a stock.

        Returns:
        - Table of rating changes: date, analyst firm, action (e.g., upgrade,
          downgrade, initiated, reiterated), previous grade, and new grade.

        Use this tool to track Wall Street analyst sentiment shifts, identify
        consensus changes, and spot catalysts from major firm rating changes.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "MSFT").
            limit: Maximum number of entries to show (default 20).
            format: "markdown" (default) or "json".
        """
        try:
            ticker = await validate_ticker_lenient(ticker)
            data = await data_source.get_upgrades_downgrades(ticker, limit=limit)
            if format == "json":
                return format_json(data)
            return format_upgrades_downgrades(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"



def register_news_extras_tools(
    mcp: FastMCP, data_source: YFinanceDataSource
) -> None:
    """Register earnings_dates and stock_news tools (reserved, not active by default).

    These tools are available but not registered in mcp_server.py until
    their value is validated in production reports.

    Args:
        mcp: The FastMCP server to register tools on.
        data_source: The YFinanceDataSource instance for fetching data.
    """

    @mcp.tool()
    async def get_earnings_dates(
        ticker: str,
        limit: int = 8,
        format: str = "markdown",
    ) -> str:
        """Fetch upcoming and past earnings dates for a stock.

        Returns:
        - Upcoming earnings: date and EPS estimate (if available).
        - Past earnings: date, EPS estimate, reported EPS, and surprise %.

        Use this tool to check when the next earnings report is due, plan
        around earnings catalysts, or review recent earnings date history.
        For detailed beat/miss analysis, use get_earnings_data instead.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "MSFT").
            limit: Maximum number of dates to show (default 8).
            format: "markdown" (default) or "json".
        """
        try:
            ticker = await validate_ticker_lenient(ticker)
            data = await data_source.get_earnings_dates(ticker, limit=limit)
            if format == "json":
                return format_json(data)
            return format_earnings_dates(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"

    @mcp.tool()
    async def get_stock_news(
        ticker: str,
        limit: int = 10,
        format: str = "markdown",
    ) -> str:
        """Fetch recent news articles for a stock.

        Returns:
        - Numbered list of news articles with title, publisher, publication
          date, link, and related tickers.

        Use this tool to stay informed about recent developments, identify
        news-driven catalysts, or understand current market narratives
        around a stock.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "MSFT").
            limit: Maximum number of articles to show (default 10).
            format: "markdown" (default) or "json".
        """
        try:
            ticker = await validate_ticker_lenient(ticker)
            data = await data_source.get_stock_news(ticker, limit=limit)
            if format == "json":
                return format_json(data)
            return format_stock_news(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"
