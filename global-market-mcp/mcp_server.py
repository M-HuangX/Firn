"""FastMCP server entry point for the global market data server."""

import logging

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP("global-market-mcp")

# --- Register all MCP tools ---
from src.data_sources.fred_source import FREDDataSource
from src.data_sources.yfinance_source import YFinanceDataSource
from src.tools.analyst_ownership import register_analyst_ownership_tools
from src.tools.earnings import register_earnings_tools
from src.tools.financial_statements import register_financial_statement_tools
from src.tools.helpers import register_helper_tools
from src.tools.macroeconomic import register_macroeconomic_tools
from src.tools.market_calendar import register_market_calendar_tools
from src.tools.news_sentiment import register_news_sentiment_tools
from src.tools.stock_data import register_stock_data_tools
from src.tools.technical_analysis import register_technical_analysis_tools

data_source = YFinanceDataSource()
fred_source = FREDDataSource()

register_stock_data_tools(mcp, data_source)
register_financial_statement_tools(mcp, data_source)
register_technical_analysis_tools(mcp, data_source)
register_earnings_tools(mcp, data_source)
register_analyst_ownership_tools(mcp, data_source)
register_market_calendar_tools(mcp, data_source)
register_news_sentiment_tools(mcp, data_source)
register_macroeconomic_tools(mcp, fred_source, data_source)
register_helper_tools(mcp)


def main() -> None:
    """Start the MCP server."""
    logger.info("Starting global-market-mcp server...")
    mcp.run()


if __name__ == "__main__":
    main()
