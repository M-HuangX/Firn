"""MCP tool registrations for analyst recommendations and institutional ownership data.

Registers 2 MVP tools:
- get_analyst_data: Analyst recommendations, price targets, and consensus.
- get_institutional_holders: Institutional/insider ownership overview and top holders.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..data_sources.exceptions import DataSourceError
from ..data_sources.validation import validate_ticker_lenient
from ..data_sources.yfinance_source import YFinanceDataSource
from ..formatting.json_fmt import format_json
from ..formatting.markdown import format_analyst_data, format_institutional_holders


def register_analyst_ownership_tools(
    mcp: FastMCP, data_source: YFinanceDataSource
) -> None:
    """Register all analyst and ownership MCP tools on the given server instance.

    Args:
        mcp: The FastMCP server to register tools on.
        data_source: The YFinanceDataSource instance for fetching data.
    """

    @mcp.tool()
    async def get_analyst_data(
        ticker: str,
        format: str = "markdown",
    ) -> str:
        """Fetch analyst recommendations and price targets for a stock.

        Returns:
        - Price targets: current price, mean/median/high/low analyst targets,
          and upside/downside percentage from current price.
        - Consensus recommendation: overall rating (e.g., Buy/Hold/Sell) and
          distribution across Strong Buy, Buy, Hold, Sell, Strong Sell.
        - Recent trend: recommendation changes over the last 3-4 months.

        Use this tool when you need Wall Street analyst sentiment, price
        target ranges for valuation context, or to identify consensus shifts.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "MSFT").
            format: "markdown" (default) or "json".
        """
        try:
            ticker = await validate_ticker_lenient(ticker)
            data = await data_source.get_analyst_data(ticker)
            if format == "json":
                return format_json(data)
            return format_analyst_data(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"

    @mcp.tool()
    async def get_institutional_holders(
        ticker: str,
        limit: int = 10,
        format: str = "markdown",
    ) -> str:
        """Fetch institutional and insider ownership data for a stock.

        Returns:
        - Ownership overview: insider ownership %, institutional ownership %,
          number of institutional holders.
        - Top holders table: institution name, shares held, percentage of
          outstanding, value, and date reported.
        - Short interest data when available.

        Use this tool to understand who owns the stock, assess institutional
        conviction, and identify potential concentration risks.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "MSFT").
            limit: Maximum number of institutional holders to show (default 10).
            format: "markdown" (default) or "json".
        """
        try:
            ticker = await validate_ticker_lenient(ticker)
            data = await data_source.get_institutional_holders(ticker, limit=limit)
            if format == "json":
                return format_json(data)
            return format_institutional_holders(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"
