"""MCP tool registrations for earnings data — history, estimates, surprises.

Registers 1 MVP tool:
- get_earnings_data: Earnings dates, EPS estimates vs actuals, and surprise history.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..data_sources.exceptions import DataSourceError
from ..data_sources.validation import validate_ticker_lenient
from ..data_sources.yfinance_source import YFinanceDataSource
from ..formatting.json_fmt import format_json
from ..formatting.markdown import format_earnings_data


def register_earnings_tools(
    mcp: FastMCP, data_source: YFinanceDataSource
) -> None:
    """Register all earnings-related MCP tools on the given server instance.

    Args:
        mcp: The FastMCP server to register tools on.
        data_source: The YFinanceDataSource instance for fetching data.
    """

    @mcp.tool()
    async def get_earnings_data(
        ticker: str,
        quarters: int = 8,
        format: str = "markdown",
    ) -> str:
        """Fetch earnings data for a stock — dates, EPS, and surprise history.

        Returns:
        - Next earnings: upcoming earnings date and estimated EPS (if available).
        - Earnings history: table with quarter end date, EPS estimate, EPS actual,
          and surprise percentage for the requested number of quarters.
        - Beat/miss trend: summary showing how many of the last N quarters beat
          or missed analyst EPS estimates.

        Use this tool when you need to evaluate earnings quality, identify
        beat/miss patterns, assess estimate reliability, or check when the
        next earnings report is due (catalyst identification).

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "MSFT").
            quarters: Number of historical quarters to include (default 8).
            format: "markdown" (default) or "json".
        """
        try:
            ticker = await validate_ticker_lenient(ticker)
            data = await data_source.get_earnings_data(ticker, quarters=quarters)
            if format == "json":
                return format_json(data)
            return format_earnings_data(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"
