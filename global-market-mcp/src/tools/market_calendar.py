"""MCP tool registrations for market calendar operations — trading days, market hours, sessions.

Registers four MVP tools:
- get_market_status: Current market state and session info for an exchange.
- is_trading_day: Check whether a date is a trading session.
- get_trading_calendar: Holidays, session counts, or market hours for an exchange.
- get_index_data: Market index data (S&P 500, NASDAQ, DOW, VIX) for benchmarking.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import exchange_calendars as xcals
import pandas as pd
import pytz
from mcp.server.fastmcp import FastMCP

from ..config import INDEX_SYMBOLS, SUPPORTED_EXCHANGES
from ..data_sources.exceptions import DataSourceError
from ..data_sources.yfinance_source import YFinanceDataSource
from ..formatting.json_fmt import format_json
from ..formatting.markdown import (
    format_index_data,
    format_market_status,
    format_trading_calendar,
    format_trading_day,
)

logger = logging.getLogger(__name__)


def _validate_exchange(exchange: str) -> str | None:
    """Validate exchange code against SUPPORTED_EXCHANGES.

    Returns None if valid, or an error message string if invalid.
    """
    if exchange not in SUPPORTED_EXCHANGES:
        valid = ", ".join(f"{k} ({v})" for k, v in SUPPORTED_EXCHANGES.items())
        return f"Error: Unknown exchange '{exchange}'. Supported exchanges: {valid}"
    return None


def _get_calendar(exchange: str) -> xcals.ExchangeCalendar:
    """Get an exchange calendar instance."""
    return xcals.get_calendar(exchange)


def register_market_calendar_tools(mcp: FastMCP, data_source: YFinanceDataSource) -> None:
    """Register market calendar tools with the MCP server.

    Args:
        mcp: The FastMCP server instance.
        data_source: The YFinanceDataSource instance for fetching market data.
    """

    @mcp.tool()
    async def get_market_status(
        exchange: str = "XNYS",
        format: str = "markdown",
    ) -> str:
        """Get current market status and session information for an exchange.

        Returns whether the market is currently open, pre-market, post-market,
        or closed. Includes current time in UTC and local exchange timezone,
        today's session open/close times, whether today is a trading day, and
        the next market holiday.

        Supported exchanges: XNYS (NYSE), XNAS (NASDAQ), XSWX (SIX Swiss),
        XLON (London Stock Exchange).

        Args:
            exchange: Exchange code — "XNYS", "XNAS", "XSWX", or "XLON".
                      Default "XNYS".
            format: Output format — "markdown" or "json". Default "markdown".

        Returns:
            Formatted string with market status, session times, and next holiday.
        """
        try:
            err = _validate_exchange(exchange)
            if err:
                return err

            cal = _get_calendar(exchange)
            now_utc = datetime.now(pytz.utc)

            # Determine exchange timezone
            exchange_tz = cal.tz
            now_local = now_utc.astimezone(exchange_tz)
            today = now_local.date()
            today_ts = pd.Timestamp(today)

            is_session = cal.is_session(today_ts)

            # Market state
            market_state = "CLOSED"
            session_open_str = None
            session_close_str = None

            if is_session:
                session_open = cal.session_open(today_ts)
                session_close = cal.session_close(today_ts)
                open_local = session_open.astimezone(exchange_tz)
                close_local = session_close.astimezone(exchange_tz)
                session_open_str = open_local.strftime("%H:%M %Z")
                session_close_str = close_local.strftime("%H:%M %Z")

                if now_utc < session_open:
                    market_state = "PRE"
                elif now_utc > session_close:
                    market_state = "POST"
                else:
                    market_state = "OPEN"
            else:
                # Not a trading day — check if weekend or holiday
                day_of_week = today.weekday()
                if day_of_week >= 5:
                    market_state = "CLOSED (Weekend)"
                else:
                    market_state = "CLOSED (Holiday)"

            # Find next holiday (= next weekday that is NOT a trading session)
            next_holiday_date = None
            try:
                # Look ahead up to 365 days for next holiday
                look_end = today_ts + pd.Timedelta(days=365)
                if look_end > cal.last_session:
                    look_end = cal.last_session
                sessions = cal.sessions_in_range(today_ts, look_end)
                sessions_set = set(sessions)
                all_business_days = pd.date_range(start=today_ts, end=look_end, freq="B")
                for bd in all_business_days:
                    if bd not in sessions_set and bd >= today_ts:
                        next_holiday_date = bd.strftime("%Y-%m-%d")
                        break
            except Exception:
                pass  # Holiday lookup is best-effort

            # Find next trading day
            next_trading_day = None
            try:
                # Get the next valid session after today
                if is_session:
                    next_session = cal.next_session(today_ts)
                else:
                    # If today is not a session, find the next one
                    next_session = cal.next_session(today_ts)
                next_trading_day = next_session.strftime("%Y-%m-%d")
            except Exception:
                pass

            # Build session_times dict for formatter
            session_times = None
            if is_session and session_open_str and session_close_str:
                session_times = {
                    "open": session_open_str,
                    "close": session_close_str,
                }

            # Build next_holiday dict for formatter
            next_holiday_info = None
            if next_holiday_date:
                next_holiday_info = {
                    "date": next_holiday_date,
                    "name": "Market Holiday",
                }

            result_data = {
                "exchange": f"{exchange} ({SUPPORTED_EXCHANGES.get(exchange, exchange)})",
                "market_state": market_state,
                "current_time_utc": now_utc.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "current_time_local": now_local.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "timezone": str(exchange_tz),
                "is_trading_day": is_session,
                "session_times": session_times,
                "next_trading_day": next_trading_day,
                "next_holiday": next_holiday_info,
            }

            if format == "json":
                return format_json(result_data)
            return format_market_status(result_data)

        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"

    @mcp.tool()
    async def is_trading_day(
        date: str,
        exchange: str = "XNYS",
        format: str = "markdown",
    ) -> str:
        """Check if a specific date is a trading session for an exchange.

        Returns whether the date is a trading day, and if not, explains why
        (weekend or holiday). Also provides the nearest previous and next
        trading days for context.

        Args:
            date: Date to check in "YYYY-MM-DD" format.
            exchange: Exchange code — "XNYS", "XNAS", "XSWX", or "XLON".
                      Default "XNYS".
            format: Output format — "markdown" or "json". Default "markdown".

        Returns:
            Formatted string with trading day status and nearest trading days.
        """
        try:
            err = _validate_exchange(exchange)
            if err:
                return err

            # Parse the date
            try:
                target_date = pd.Timestamp(date)
            except (ValueError, TypeError):
                return f"Error: Invalid date format '{date}'. Please use YYYY-MM-DD format."

            cal = _get_calendar(exchange)

            # Check if date is within calendar range
            if target_date < cal.first_session or target_date > cal.last_session:
                return (
                    f"Error: Date '{date}' is outside the calendar range "
                    f"({cal.first_session.strftime('%Y-%m-%d')} to "
                    f"{cal.last_session.strftime('%Y-%m-%d')})."
                )

            is_session = cal.is_session(target_date)

            # Determine reason if not a trading day
            reason = None
            if not is_session:
                day_of_week = target_date.weekday()
                if day_of_week >= 5:
                    reason = "Weekend"
                else:
                    reason = "Market holiday"

            # Find previous and next trading days
            prev_trading_day = None
            next_trading_day = None

            try:
                prev_session = cal.previous_session(target_date)
                prev_trading_day = prev_session.strftime("%Y-%m-%d")
            except Exception:
                pass

            try:
                next_session = cal.next_session(target_date)
                next_trading_day = next_session.strftime("%Y-%m-%d")
            except Exception:
                pass

            result_data = {
                "date": date,
                "exchange": exchange,
                "exchange_name": SUPPORTED_EXCHANGES.get(exchange, exchange),
                "is_trading_day": is_session,
                "reason": reason,
                "previous_trading_day": prev_trading_day,
                "next_trading_day": next_trading_day,
            }

            if format == "json":
                return format_json(result_data)
            return format_trading_day(result_data)

        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"

    @mcp.tool()
    async def get_trading_calendar(
        exchange: str = "XNYS",
        year: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        info_type: str = "holidays",
        format: str = "markdown",
    ) -> str:
        """Get trading calendar information: holidays, session count, or market hours.

        Use info_type to choose what to retrieve:
        - "holidays": List of market holidays for the specified year.
        - "sessions": Count of trading sessions in a date range.
        - "hours": Regular market hours for the exchange.

        Args:
            exchange: Exchange code — "XNYS", "XNAS", "XSWX", or "XLON".
                      Default "XNYS".
            year: Year for holiday listing. Default is the current year.
                  Only used when info_type is "holidays".
            start_date: Start date "YYYY-MM-DD" for session count query.
                        Only used when info_type is "sessions".
            end_date: End date "YYYY-MM-DD" for session count query.
                      Only used when info_type is "sessions".
            info_type: What to retrieve — "holidays", "sessions", or "hours".
                       Default "holidays".
            format: Output format — "markdown" or "json". Default "markdown".

        Returns:
            Formatted string with the requested calendar information.
        """
        try:
            err = _validate_exchange(exchange)
            if err:
                return err

            valid_info_types = ("holidays", "sessions", "hours")
            if info_type not in valid_info_types:
                return (
                    f"Error: Invalid info_type '{info_type}'. "
                    f"Valid types: {', '.join(valid_info_types)}"
                )

            cal = _get_calendar(exchange)

            result_data: dict[str, Any] = {
                "exchange": exchange,
                "exchange_name": SUPPORTED_EXCHANGES.get(exchange, exchange),
                "info_type": info_type,
            }

            if info_type == "holidays":
                target_year = year or datetime.now().year
                result_data["year"] = target_year

                year_start = pd.Timestamp(f"{target_year}-01-01")
                year_end = pd.Timestamp(f"{target_year}-12-31")

                # Clamp to calendar range
                if year_start < cal.first_session:
                    year_start = cal.first_session
                if year_end > cal.last_session:
                    year_end = cal.last_session

                # Holidays = business days (weekdays) that are NOT trading sessions
                sessions = cal.sessions_in_range(year_start, year_end)
                sessions_set = set(sessions)
                all_business_days = pd.date_range(start=year_start, end=year_end, freq="B")
                holiday_list = [
                    d.strftime("%Y-%m-%d")
                    for d in all_business_days
                    if d not in sessions_set
                ]

                result_data["holidays"] = holiday_list
                result_data["holiday_count"] = len(holiday_list)

            elif info_type == "sessions":
                if not start_date or not end_date:
                    return (
                        "Error: Both start_date and end_date are required "
                        "when info_type is 'sessions'."
                    )

                try:
                    start_ts = pd.Timestamp(start_date)
                    end_ts = pd.Timestamp(end_date)
                except (ValueError, TypeError):
                    return "Error: Invalid date format. Please use YYYY-MM-DD format."

                if start_ts > end_ts:
                    return "Error: start_date must be before end_date."

                # Clamp to calendar range
                if start_ts < cal.first_session:
                    start_ts = cal.first_session
                if end_ts > cal.last_session:
                    end_ts = cal.last_session

                sessions = cal.sessions_in_range(start_ts, end_ts)
                total_days = (end_ts - start_ts).days + 1

                result_data["start_date"] = start_date
                result_data["end_date"] = end_date
                result_data["session_count"] = len(sessions)
                result_data["calendar_days"] = total_days
                result_data["non_trading_days"] = total_days - len(sessions)

            elif info_type == "hours":
                # Get regular market hours — use a recent trading day as reference
                now = datetime.now()
                ref_date = pd.Timestamp(now.date())

                market_hours: dict[str, str] = {}
                # Find a valid session for reference
                try:
                    if cal.is_session(ref_date):
                        ref_session = ref_date
                    else:
                        ref_session = cal.previous_session(ref_date)

                    session_open = cal.session_open(ref_session)
                    session_close = cal.session_close(ref_session)

                    local_tz = cal.tz
                    open_local = session_open.astimezone(local_tz)
                    close_local = session_close.astimezone(local_tz)

                    market_hours["Timezone"] = str(local_tz)
                    market_hours["Regular Open (Local)"] = open_local.strftime("%H:%M")
                    market_hours["Regular Close (Local)"] = close_local.strftime("%H:%M")
                    market_hours["Regular Open (UTC)"] = session_open.strftime("%H:%M UTC")
                    market_hours["Regular Close (UTC)"] = session_close.strftime("%H:%M UTC")

                except Exception:
                    market_hours["Timezone"] = str(cal.tz)
                    market_hours["Regular Open (Local)"] = "N/A"
                    market_hours["Regular Close (Local)"] = "N/A"
                    market_hours["Regular Open (UTC)"] = "N/A"
                    market_hours["Regular Close (UTC)"] = "N/A"

                result_data["market_hours"] = market_hours

            if format == "json":
                return format_json(result_data)
            return format_trading_calendar(result_data)

        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"

    @mcp.tool()
    async def get_index_data(
        index: str = "SP500",
        period: str = "1y",
        info_type: str = "summary",
        format: str = "markdown",
    ) -> str:
        """Get market index data for benchmarking and market context.

        Returns current value, period change %, 52-week high/low, and position
        relative to the 200-day moving average. Use info_type="history" to also
        include historical OHLCV data.

        Available indices: SP500, NASDAQ, DOW, VIX, RUSSELL2000, or any
        yfinance index symbol (e.g., "^GSPC").

        Args:
            index: Index name — "SP500", "NASDAQ", "DOW", "VIX", "RUSSELL2000",
                   or a yfinance symbol. Default "SP500".
            period: Data period — "1mo", "3mo", "6mo", "1y", "2y", or "5y".
                    Default "1y".
            info_type: What to return — "summary" (overview only) or "history"
                       (overview + OHLCV table). Default "summary".
            format: Output format — "markdown" or "json". Default "markdown".

        Returns:
            Formatted string with index summary and optionally historical data.
        """
        try:
            valid_periods = ("1mo", "3mo", "6mo", "1y", "2y", "5y")
            if period not in valid_periods:
                return f"Error: Invalid period '{period}'. Valid periods: {', '.join(valid_periods)}"

            valid_info_types = ("summary", "history")
            if info_type not in valid_info_types:
                return (
                    f"Error: Invalid info_type '{info_type}'. "
                    f"Valid types: {', '.join(valid_info_types)}"
                )

            # Let data source resolve index names (e.g., "SP500" -> "^GSPC")
            data = await data_source.get_index_data(index, period)

            # Add info_type and friendly index name to result
            data["info_type"] = info_type
            data["index_name"] = index.upper() if index.upper() in INDEX_SYMBOLS else index

            # If history is requested, fetch historical prices
            if info_type == "history":
                try:
                    yf_symbol = INDEX_SYMBOLS.get(index.upper(), index)
                    tech_data = await data_source.get_technical_data(yf_symbol, period)
                    data["history"] = tech_data.get("ohlcv", [])
                except Exception as e:
                    logger.warning("Failed to fetch history for index '%s': %s", index, e)
                    data["history"] = []

            if format == "json":
                return format_json(data)
            return format_index_data(data)

        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"
