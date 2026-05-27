"""MCP tool registrations for financial statement retrieval — income, balance sheet, cash flow.

Registers 4 tools:
- get_income_statement: Revenue, margins, net income across periods.
- get_balance_sheet: Assets, liabilities, equity, key ratios across periods.
- get_cash_flow: Operating, investing, financing flows + free cash flow.
- get_financial_metrics: Consolidated valuation, profitability, growth ratios.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..data_sources.exceptions import DataSourceError
from ..data_sources.validation import validate_ticker_lenient
from ..data_sources.yfinance_source import YFinanceDataSource
from ..formatting.json_fmt import format_json
from ..formatting.markdown import (
    format_balance_sheet,
    format_cash_flow,
    format_financial_metrics,
    format_income_statement,
)


def register_financial_statement_tools(
    mcp: FastMCP, data_source: YFinanceDataSource
) -> None:
    """Register all financial-statement MCP tools on the given server instance.

    Args:
        mcp: The FastMCP server to register tools on.
        data_source: The YFinanceDataSource instance for fetching data.
    """

    @mcp.tool()
    async def get_income_statement(
        ticker: str,
        period: str = "annual",
        limit: int = 5,
        format: str = "markdown",
    ) -> str:
        """Fetch income statement data for a stock.

        Returns key line items (Revenue, COGS, Gross Profit, R&D, SG&A,
        Operating Income, EBITDA, Net Income, EPS) as rows with fiscal periods
        as columns.  Includes computed margins (Gross/Operating/Net) and YoY
        growth rates.

        Use this tool when you need to analyze a company's revenue, expenses,
        profitability, and earnings trends over multiple periods.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "MSFT").
            period: "annual" for yearly data or "quarterly" for quarterly data.
            limit: Number of most-recent periods to include (1-5, default 5).
            format: "markdown" (default) or "json".
        """
        try:
            ticker = await validate_ticker_lenient(ticker)
            data = await data_source.get_income_statement(
                ticker, period=period, limit=limit
            )
            if format == "json":
                return format_json(data)
            return format_income_statement(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"

    @mcp.tool()
    async def get_balance_sheet(
        ticker: str,
        period: str = "annual",
        limit: int = 5,
        format: str = "markdown",
    ) -> str:
        """Fetch balance sheet data for a stock.

        Returns curated ~20 key items (Total Assets, Current Assets, Cash,
        Total Liabilities, Current Liabilities, Long-Term Debt, Stockholders'
        Equity, etc.) with computed ratios (Current Ratio, Quick Ratio, D/E,
        D/A).

        Use this tool when you need to assess a company's financial position,
        liquidity, leverage, and asset composition over time.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "MSFT").
            period: "annual" for yearly data or "quarterly" for quarterly data.
            limit: Number of most-recent periods to include (1-5, default 5).
            format: "markdown" (default) or "json".
        """
        try:
            ticker = await validate_ticker_lenient(ticker)
            data = await data_source.get_balance_sheet(
                ticker, period=period, limit=limit
            )
            if format == "json":
                return format_json(data)
            return format_balance_sheet(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"

    @mcp.tool()
    async def get_cash_flow(
        ticker: str,
        period: str = "annual",
        limit: int = 5,
        format: str = "markdown",
    ) -> str:
        """Fetch cash flow statement data for a stock.

        Returns three sections (Operating, Investing, Financing activities)
        plus computed values: Free Cash Flow, FCF Margin, and OCF-to-Net Income
        ratio.

        Use this tool when you need to analyze how a company generates and
        uses cash, evaluate capital expenditures, and assess free cash flow
        generation quality.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "MSFT").
            period: "annual" for yearly data or "quarterly" for quarterly data.
            limit: Number of most-recent periods to include (1-5, default 5).
            format: "markdown" (default) or "json".
        """
        try:
            ticker = await validate_ticker_lenient(ticker)
            data = await data_source.get_cash_flow(
                ticker, period=period, limit=limit
            )
            if format == "json":
                return format_json(data)
            return format_cash_flow(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"

    @mcp.tool()
    async def get_financial_metrics(
        ticker: str,
        format: str = "markdown",
    ) -> str:
        """Fetch consolidated financial ratios and metrics for a stock.

        Returns ~25 metrics organized by section:
        - Valuation: P/E, P/B, P/S, PEG, EV/EBITDA, EV/Revenue
        - Profitability: ROE, ROA, margins (gross/operating/net/EBITDA)
        - Growth: revenue growth, earnings growth (annual + quarterly)
        - Per Share: EPS (trailing/forward), book value, revenue per share
        - Financial Health: D/E, current ratio, quick ratio, interest coverage
        - Cash Flow: free cash flow, FCF yield, OCF/Net Income
        - Dividends: yield, payout ratio, 5-year average yield

        Use this tool for valuation comparisons, profitability analysis,
        and financial health assessment. Pair with get_stock_info for company
        identity/price context (zero field overlap by design).

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "MSFT").
            format: "markdown" (default) or "json".
        """
        try:
            ticker = await validate_ticker_lenient(ticker)
            data = await data_source.get_financial_metrics(ticker)
            if format == "json":
                return format_json(data)
            return format_financial_metrics(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"
