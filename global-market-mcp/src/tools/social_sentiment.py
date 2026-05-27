"""MCP tool registrations for social sentiment data (StockTwits + Reddit).

Registers 2 tools:
- get_stocktwits_sentiment: Recent StockTwits messages and sentiment ratios.
- get_reddit_sentiment: Recent Reddit posts about a stock.

These tools use standalone data source functions (no YFinanceDataSource needed)
and degrade gracefully — they never crash the MCP server.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..data_sources.social_sentiment import (
    fetch_reddit_sentiment,
    fetch_stocktwits_sentiment,
)
from ..data_sources.validation import validate_ticker_lenient
from ..formatting.json_fmt import format_json
from ..formatting.markdown import format_reddit_sentiment, format_stocktwits_sentiment


def register_social_sentiment_tools(mcp: FastMCP) -> None:
    """Register social sentiment MCP tools on the given server instance.

    These tools do not require a YFinanceDataSource — they use independent
    public APIs (StockTwits and Reddit).

    Args:
        mcp: The FastMCP server to register tools on.
    """

    @mcp.tool()
    async def get_stocktwits_sentiment(
        ticker: str,
        limit: int = 15,
        format: str = "markdown",
    ) -> str:
        """Fetch recent StockTwits messages and sentiment for a stock.

        Returns:
        - Sentiment summary: bullish/bearish/neutral counts and ratios.
        - A visual sentiment bar showing the bull/bear balance.
        - Recent messages with their sentiment labels and authors.

        StockTwits is a social media platform for traders. Use this tool
        to gauge retail trader sentiment, identify momentum shifts, and
        understand the social narrative around a stock.

        Note: This data reflects retail sentiment and may be noisy.
        It is most useful as one signal among many, not a standalone
        trading indicator.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "TSLA").
            limit: Maximum number of messages to show (default 15, max 30).
            format: "markdown" (default) or "json".
        """
        try:
            ticker = await validate_ticker_lenient(ticker)
        except Exception:
            # Even if validation fails, try fetching — StockTwits may
            # have the ticker even if yfinance doesn't
            ticker = ticker.strip().upper()

        try:
            data = await fetch_stocktwits_sentiment(ticker, limit=limit)
            if format == "json":
                return format_json(data)
            return format_stocktwits_sentiment(data)
        except Exception as e:
            # Ultimate safety net — this tool must NEVER crash
            return f"StockTwits sentiment data is currently unavailable for {ticker}: {e}"

    @mcp.tool()
    async def get_reddit_sentiment(
        ticker: str,
        limit: int = 10,
        format: str = "markdown",
    ) -> str:
        """Fetch recent Reddit posts discussing a stock.

        Searches popular finance subreddits (r/stocks, r/wallstreetbets,
        r/investing, r/stockmarket) for recent posts mentioning the ticker.

        Returns:
        - Post count from the past week.
        - Numbered list of posts with title, subreddit, upvotes, comments,
          date, and link.

        Use this tool to understand what retail investors are discussing,
        identify emerging narratives, and gauge community interest level.
        High post volume with strong upvotes may indicate increased retail
        attention.

        Note: Reddit posts reflect community discussion, not financial
        advice. Posts from r/wallstreetbets in particular may be highly
        speculative.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "GME").
            limit: Maximum number of posts to show (default 10, max 25).
            format: "markdown" (default) or "json".
        """
        try:
            ticker = await validate_ticker_lenient(ticker)
        except Exception:
            # Even if validation fails, try fetching
            ticker = ticker.strip().upper()

        try:
            data = await fetch_reddit_sentiment(ticker, limit=limit)
            if format == "json":
                return format_json(data)
            return format_reddit_sentiment(data)
        except Exception as e:
            # Ultimate safety net — this tool must NEVER crash
            return f"Reddit sentiment data is currently unavailable for {ticker}: {e}"
