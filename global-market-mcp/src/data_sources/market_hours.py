"""Market hours utility — determines if US markets are currently open.

Uses exchange_calendars directly to check NYSE (XNYS) session times.
No dependency on the tools layer, avoiding circular imports.
"""

from __future__ import annotations

import logging
from datetime import datetime

import exchange_calendars as xcals
import pytz

from src.config import CacheTTL

logger = logging.getLogger(__name__)

_NYSE_TZ = pytz.timezone("America/New_York")


def is_us_market_open() -> bool:
    """Check if the US stock market (NYSE) is currently in a regular trading session.

    Uses the exchange_calendars library to determine whether the current
    timestamp falls within NYSE regular trading hours. Accounts for weekends,
    US holidays, and early closes.

    Returns:
        True if NYSE is in regular trading hours, False otherwise
        (weekends, holidays, pre-market, after-hours). Returns False
        on any error (e.g., date outside calendar range).
    """
    try:
        nyse = xcals.get_calendar("XNYS")
        now_et = datetime.now(_NYSE_TZ)
        today = now_et.date()

        if not nyse.is_session(today):
            return False

        session_open = nyse.session_open(today)
        session_close = nyse.session_close(today)
        now_utc = datetime.now(pytz.utc)

        return session_open <= now_utc <= session_close

    except Exception as e:
        logger.debug("Failed to check market hours: %s", e)
        return False


def get_price_data_ttl() -> int:
    """Return appropriate cache TTL for price data based on market hours.

    During regular trading hours, price data changes frequently, so a shorter
    TTL is used. Outside trading hours, data is static until the next session,
    so a longer TTL is appropriate.

    Returns:
        TTL in seconds — PRICE_HISTORY_MARKET_OPEN (900s) if markets are open,
        PRICE_HISTORY_MARKET_CLOSED (86400s) otherwise.
    """
    if is_us_market_open():
        return CacheTTL.PRICE_HISTORY_MARKET_OPEN
    return CacheTTL.PRICE_HISTORY_MARKET_CLOSED
