"""MCP server entry point for Global Market Financial Data.

Creates a FastMCP server, registers all tool modules, sets up periodic cache
cleanup via lifespan, and runs the server over stdio transport.

Usage::

    uv run python src/mcp_server.py
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from src.data_sources.cache import get_cache
from src.data_sources.fred_source import FREDDataSource
from src.data_sources.yfinance_source import YFinanceDataSource
from src.tools.analyst_ownership import register_analyst_ownership_tools
from src.tools.earnings import register_earnings_tools
from src.tools.financial_statements import register_financial_statement_tools
from src.tools.helpers import register_helper_tools
from src.tools.macroeconomic import register_macroeconomic_tools
from src.tools.market_calendar import register_market_calendar_tools
from src.tools.stock_data import register_stock_data_tools
from src.tools.news_sentiment import register_news_sentiment_tools
from src.tools.social_sentiment import register_social_sentiment_tools
from src.tools.technical_analysis import register_technical_analysis_tools

# ---------------------------------------------------------------------------
# Environment & logging
# ---------------------------------------------------------------------------

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache cleanup background task
# ---------------------------------------------------------------------------

_CACHE_CLEANUP_INTERVAL_SECONDS = 300  # 5 minutes


async def _periodic_cache_cleanup() -> None:
    """Periodically remove expired cache entries and orphaned locks."""
    while True:
        await asyncio.sleep(_CACHE_CLEANUP_INTERVAL_SECONDS)
        try:
            removed = get_cache().cleanup_expired()
            if removed:
                logger.debug("Cache cleanup: removed %d expired entries", removed)
        except Exception:
            logger.exception("Error during periodic cache cleanup")


# ---------------------------------------------------------------------------
# Server lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def server_lifespan(app: FastMCP) -> AsyncIterator[None]:
    """Manage server lifecycle — start and stop background tasks."""
    cleanup_task = asyncio.create_task(_periodic_cache_cleanup())
    logger.info("Started periodic cache cleanup (every %ds)", _CACHE_CLEANUP_INTERVAL_SECONDS)
    try:
        yield None
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        logger.info("Stopped periodic cache cleanup")


# ---------------------------------------------------------------------------
# Server & tool registration
# ---------------------------------------------------------------------------

mcp = FastMCP("Global Market Financial Data", lifespan=server_lifespan)
data_source = YFinanceDataSource()
fred_source = FREDDataSource()

register_stock_data_tools(mcp, data_source)
register_financial_statement_tools(mcp, data_source)
register_technical_analysis_tools(mcp, data_source)
register_analyst_ownership_tools(mcp, data_source)
register_earnings_tools(mcp, data_source)
register_market_calendar_tools(mcp, data_source)
register_helper_tools(mcp)
register_news_sentiment_tools(mcp, data_source)
register_social_sentiment_tools(mcp)
register_macroeconomic_tools(mcp, fred_source, data_source)

logger.info("Registered all MCP tools")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
