"""YFinanceDataSource — primary data source wrapping the yfinance library for US stock data.

Provides 14 MVP methods covering company info, historical prices, financial
statements, metrics, technical data, analyst/institutional data, earnings,
and market index data.  One Phase 2 stub (``get_batch_quotes``) raises
``NotImplementedError``.

All synchronous yfinance calls are dispatched via ``_run_sync`` (which uses
``asyncio.to_thread``) so the async event loop is never blocked.  Every public
method is decorated with ``@cached`` for transparent TTL-based caching.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Never, TypeVar

import numpy as np
import pandas as pd
import yfinance as yf

from ..config import CacheTTL, INDEX_SYMBOLS
from .cache import cached
from .exceptions import (
    ExternalAPIError,
    NoDataAvailableError,
    TickerNotFoundError,
)
from .market_hours import get_price_data_ttl

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _safe_float(value: Any) -> float | None:
    """Convert a value to float, returning None for NaN/Inf/missing."""
    if value is None:
        return None
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _safe_int(value: Any) -> int | None:
    """Convert a value to int, returning None for NaN/missing."""
    if value is None:
        return None
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return int(f)
    except (ValueError, TypeError):
        return None


def _clean_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Replace NaN/Inf float values with None in a flat dict."""
    cleaned: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            cleaned[k] = None
        elif isinstance(v, dict):
            cleaned[k] = _clean_dict(v)
        else:
            cleaned[k] = v
    return cleaned


def _df_to_records(df: pd.DataFrame, date_col: str = "Date") -> list[dict[str, Any]]:
    """Convert a DataFrame with a DatetimeIndex to a list of dicts with ISO date strings.

    NaN values are replaced with None.
    """
    if df.empty:
        return []

    records: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        record: dict[str, Any] = {}
        # Handle DatetimeIndex
        if isinstance(idx, pd.Timestamp):
            record[date_col] = idx.strftime("%Y-%m-%d")
        else:
            record[date_col] = str(idx)

        for col in df.columns:
            val = row[col]
            if pd.isna(val):
                record[col] = None
            elif isinstance(val, (np.integer,)):
                record[col] = int(val)
            elif isinstance(val, (np.floating,)):
                record[col] = float(val)
            else:
                record[col] = val
        records.append(record)
    return records


class YFinanceDataSource:
    """Primary data source for US stock market data backed by the yfinance library.

    All methods are async.  Synchronous yfinance I/O is dispatched to a thread
    via ``_run_sync`` so the event loop is never blocked.  Public methods are
    decorated with ``@cached`` for transparent TTL-based caching with
    concurrent-request deduplication.

    Usage::

        ds = YFinanceDataSource()
        info = await ds.get_stock_info("AAPL")
    """

    def __init__(self) -> None:
        """Initialize the data source (no-op — stateless aside from caching)."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    _YFINANCE_TIMEOUT: float = 30.0  # seconds per individual yfinance call
    _MAX_RETRIES: int = 3
    _RETRY_BASE_DELAY: float = 2.0  # seconds; actual delay = base * attempt

    @staticmethod
    async def _run_sync(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run a synchronous function in a thread with timeout and retry.

        All yfinance calls go through this method.  yfinance uses *requests*
        internally and ``Ticker`` objects do not share mutable state, making
        them safe for concurrent thread execution.

        Each attempt is wrapped with a 30-second timeout.  Transient failures
        (timeouts, network errors) are retried up to 3 times with exponential
        backoff (2s, 4s, 6s).

        Args:
            func: The synchronous callable to execute.
            *args: Positional arguments forwarded to *func*.
            **kwargs: Keyword arguments forwarded to *func*.

        Returns:
            The return value of ``func(*args, **kwargs)``.

        Raises:
            The last exception if all retries are exhausted.
        """
        last_err: Exception | None = None
        for attempt in range(1, YFinanceDataSource._MAX_RETRIES + 1):
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(func, *args, **kwargs),
                    timeout=YFinanceDataSource._YFINANCE_TIMEOUT,
                )
            except (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError) as e:
                last_err = e
                if attempt < YFinanceDataSource._MAX_RETRIES:
                    delay = YFinanceDataSource._RETRY_BASE_DELAY * attempt
                    logger.warning(
                        "yfinance _run_sync attempt %d/%d failed (%s), retrying in %.0fs",
                        attempt, YFinanceDataSource._MAX_RETRIES, type(e).__name__, delay,
                    )
                    await asyncio.sleep(delay)
        raise last_err  # type: ignore[misc]

    def _handle_error(self, error: Exception, ticker: str, method: str) -> Never:
        """Translate unexpected exceptions into ``ExternalAPIError``.

        Known data-source exceptions (``TickerNotFoundError``,
        ``NoDataAvailableError``) are re-raised without wrapping.

        Args:
            error: The caught exception.
            ticker: The ticker symbol involved.
            method: The name of the calling method (for logging).

        Raises:
            TickerNotFoundError: Re-raised unchanged.
            NoDataAvailableError: Re-raised unchanged.
            ExternalAPIError: For all other exception types.
        """
        if isinstance(error, (TickerNotFoundError, NoDataAvailableError)):
            raise error
        if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
            logger.warning("Timeout in %s for '%s' after %.0fs", method, ticker,
                           YFinanceDataSource._YFINANCE_TIMEOUT)
            raise ExternalAPIError(
                message=f"{method} timed out after {YFinanceDataSource._YFINANCE_TIMEOUT:.0f}s",
                source="yfinance",
                ticker=ticker,
            ) from error
        logger.warning("Error in %s for '%s': %s", method, ticker, error)
        raise ExternalAPIError(
            message=f"{method} failed: {error}",
            source="yfinance",
            ticker=ticker,
        ) from error

    # ------------------------------------------------------------------
    # 1. get_stock_info
    # ------------------------------------------------------------------

    @cached(ttl_seconds=CacheTTL.STOCK_INFO)
    async def get_stock_info(self, ticker: str) -> dict[str, Any]:
        """Fetch company identity, current price, and market information.

        Returns ~20 curated fields organized into identity, price, and market
        sections.  Financial ratios are deliberately excluded (use
        ``get_financial_metrics`` instead).

        Args:
            ticker: Stock ticker symbol (e.g. ``"AAPL"``).

        Returns:
            Dict with keys ``_ticker``, ``identity``, ``price``, ``market``.

        Raises:
            TickerNotFoundError: If the ticker is invalid or returns no data.
            ExternalAPIError: On unexpected yfinance errors.
        """
        try:
            yf_ticker = yf.Ticker(ticker)
            info: dict[str, Any] = await self._run_sync(getattr, yf_ticker, "info")

            if not info or not info.get("shortName"):
                raise TickerNotFoundError(ticker=ticker)

            quote_type = info.get("quoteType", "EQUITY")

            result = {
                "_ticker": ticker,
                "identity": {
                    "shortName": info.get("shortName"),
                    "longName": info.get("longName"),
                    "symbol": info.get("symbol", ticker),
                    "quoteType": quote_type,
                    "sector": info.get("sector"),
                    "industry": info.get("industry"),
                    "country": info.get("country"),
                    "website": info.get("website"),
                    "fullTimeEmployees": _safe_int(info.get("fullTimeEmployees")),
                },
                "price": {
                    "currentPrice": _safe_float(info.get("currentPrice")),
                    "previousClose": _safe_float(info.get("previousClose")),
                    "fiftyTwoWeekHigh": _safe_float(info.get("fiftyTwoWeekHigh")),
                    "fiftyTwoWeekLow": _safe_float(info.get("fiftyTwoWeekLow")),
                    "fiftyDayAverage": _safe_float(info.get("fiftyDayAverage")),
                    "twoHundredDayAverage": _safe_float(
                        info.get("twoHundredDayAverage")
                    ),
                    "beta": _safe_float(info.get("beta")),
                    "volume": _safe_int(info.get("volume")),
                },
                "market": {
                    "exchange": info.get("exchange"),
                    "currency": info.get("currency"),
                    "marketState": info.get("marketState"),
                    "exchangeTimezoneName": info.get(
                        "exchangeTimezoneName",
                        info.get("timeZoneFullName"),
                    ),
                },
            }

            # ETF / Fund-specific fields
            if quote_type == "ETF":
                result["fund_info"] = {
                    "category": info.get("category"),
                    "fundFamily": info.get("fundFamily"),
                    "totalAssets": _safe_float(info.get("totalAssets")),
                    "navPrice": _safe_float(info.get("navPrice")),
                    "expenseRatio": _safe_float(info.get("netExpenseRatio")),
                    "ytdReturn": _safe_float(info.get("ytdReturn")),
                    "threeYearReturn": _safe_float(
                        info.get("threeYearAverageReturn")
                    ),
                    "fiveYearReturn": _safe_float(
                        info.get("fiveYearAverageReturn")
                    ),
                    "longBusinessSummary": info.get("longBusinessSummary"),
                }

            return _clean_dict(result)

        except TickerNotFoundError:
            raise
        except Exception as e:
            self._handle_error(e, ticker, "get_stock_info")

    # ------------------------------------------------------------------
    # 2. get_historical_prices
    # ------------------------------------------------------------------

    @cached(ttl_func=get_price_data_ttl)
    async def get_historical_prices(
        self,
        ticker: str,
        period: str = "6mo",
        interval: str = "1d",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Fetch historical OHLCV price data.

        When ``start_date`` is provided it overrides ``period`` and the
        ``start``/``end`` form of ``Ticker.history()`` is used instead.

        Args:
            ticker: Stock ticker symbol.
            period: yfinance period string (ignored when *start_date* is set).
            interval: Candle interval (e.g. ``"1d"``, ``"1h"``).
            start_date: Optional start in ``"YYYY-MM-DD"`` format.
            end_date: Optional end in ``"YYYY-MM-DD"`` format (defaults to today).

        Returns:
            Dict with ``_ticker``, ``period``, ``interval``, ``summary``,
            and ``prices`` (list of OHLCV dicts).

        Raises:
            TickerNotFoundError: If the ticker is invalid.
            NoDataAvailableError: If yfinance returns no rows.
            ExternalAPIError: On unexpected errors.
        """
        try:
            yf_ticker = yf.Ticker(ticker)

            if start_date:
                hist_kwargs: dict[str, Any] = {
                    "start": start_date,
                    "interval": interval,
                }
                if end_date:
                    hist_kwargs["end"] = end_date
                df: pd.DataFrame = await self._run_sync(
                    yf_ticker.history, **hist_kwargs
                )
                effective_period = f"{start_date} to {end_date or 'now'}"
            else:
                df = await self._run_sync(
                    yf_ticker.history, period=period, interval=interval
                )
                effective_period = period

            if df is None or df.empty:
                raise NoDataAvailableError(
                    message=f"No historical price data for '{ticker}' "
                    f"(period={effective_period}, interval={interval}).",
                    source="yfinance",
                    ticker=ticker,
                )

            # Build summary statistics
            first_close = _safe_float(df["Close"].iloc[0])
            last_close = _safe_float(df["Close"].iloc[-1])
            price_change_pct: float | None = None
            if first_close and last_close and first_close != 0:
                price_change_pct = round(
                    ((last_close - first_close) / first_close) * 100, 2
                )

            summary = {
                "start_date": df.index[0].strftime("%Y-%m-%d"),
                "end_date": df.index[-1].strftime("%Y-%m-%d"),
                "total_rows": len(df),
                "price_change_pct": price_change_pct,
                "period_high": _safe_float(df["High"].max()),
                "period_low": _safe_float(df["Low"].min()),
                "avg_volume": _safe_int(df["Volume"].mean()),
            }

            prices = _df_to_records(df[["Open", "High", "Low", "Close", "Volume"]])

            return {
                "_ticker": ticker,
                "period": effective_period,
                "interval": interval,
                "summary": summary,
                "prices": prices,
            }

        except (TickerNotFoundError, NoDataAvailableError):
            raise
        except Exception as e:
            self._handle_error(e, ticker, "get_historical_prices")

    # ------------------------------------------------------------------
    # 3. get_dividends
    # ------------------------------------------------------------------

    @cached(ttl_seconds=CacheTTL.DIVIDENDS)
    async def get_dividends(
        self, ticker: str, years: int = 10
    ) -> dict[str, Any]:
        """Fetch dividend history and compute yield information.

        Args:
            ticker: Stock ticker symbol.
            years: Number of years of history to include.

        Returns:
            Dict with ``_ticker``, ``summary`` (yield, rate, payout ratio),
            and ``history`` (list of date/amount dicts).

        Raises:
            TickerNotFoundError: If the ticker is invalid.
            NoDataAvailableError: If no dividend data is available.
            ExternalAPIError: On unexpected errors.
        """
        try:
            yf_ticker = yf.Ticker(ticker)
            info: dict[str, Any] = await self._run_sync(getattr, yf_ticker, "info")

            if not info or not info.get("shortName"):
                raise TickerNotFoundError(ticker=ticker)

            dividends: pd.Series = await self._run_sync(
                getattr, yf_ticker, "dividends"
            )

            # Filter to requested year range (use tz-aware cutoff to match yfinance's tz-aware index)
            cutoff = pd.Timestamp.now(tz="UTC") - timedelta(days=years * 365)
            if dividends is not None and not dividends.empty:
                try:
                    dividends = dividends[dividends.index >= cutoff]
                except TypeError:
                    # Fallback for timezone-naive index
                    cutoff_naive = pd.Timestamp.now() - timedelta(days=years * 365)
                    dividends = dividends[dividends.index >= cutoff_naive]

            history: list[dict[str, Any]] = []
            if dividends is not None and not dividends.empty:
                for date_idx, amount in dividends.items():
                    history.append(
                        {
                            "date": pd.Timestamp(date_idx).strftime("%Y-%m-%d"),
                            "amount": _safe_float(amount),
                        }
                    )

            # Compute annual totals per calendar year for growth analysis
            annual_totals: dict[int, float] = {}
            for entry in history:
                yr = int(entry["date"][:4])
                annual_totals[yr] = annual_totals.get(yr, 0.0) + (entry["amount"] or 0.0)

            # Count consecutive years with dividends (from most recent going backward)
            consecutive_years = 0
            current_year = datetime.now().year
            for yr in range(current_year, current_year - years - 1, -1):
                if yr in annual_totals and annual_totals[yr] > 0:
                    consecutive_years += 1
                else:
                    break

            summary = {
                "dividendYield": _safe_float(info.get("dividendYield")),
                "dividendRate": _safe_float(info.get("dividendRate")),
                "payoutRatio": _safe_float(info.get("payoutRatio")),
                "exDividendDate": (
                    datetime.fromtimestamp(info["exDividendDate"]).strftime("%Y-%m-%d")
                    if info.get("exDividendDate")
                    else None
                ),
                "fiveYearAvgDividendYield": _safe_float(
                    info.get("fiveYearAvgDividendYield")
                ),
                "trailingAnnualDividendRate": _safe_float(
                    info.get("trailingAnnualDividendRate")
                ),
                "trailingAnnualDividendYield": _safe_float(
                    info.get("trailingAnnualDividendYield")
                ),
                "consecutiveYearsWithDividends": consecutive_years,
                "totalPaymentsInPeriod": len(history),
            }

            return {
                "_ticker": ticker,
                "summary": summary,
                "annual_totals": annual_totals,
                "history": history,
            }

        except (TickerNotFoundError, NoDataAvailableError):
            raise
        except Exception as e:
            self._handle_error(e, ticker, "get_dividends")

    # ------------------------------------------------------------------
    # 4. search_stocks
    # ------------------------------------------------------------------

    @cached(ttl_seconds=CacheTTL.SEARCH_RESULTS)
    async def search_stocks(
        self, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Search for stocks by company name, ticker, or keyword.

        Args:
            query: Free-text search query.
            limit: Maximum number of results to return.

        Returns:
            List of dicts with ``symbol``, ``name``, ``exchange``,
            ``sector``, ``industry``, ``quoteType``.

        Raises:
            NoDataAvailableError: If the search returns no results.
            ExternalAPIError: On unexpected errors.
        """
        try:
            search = await self._run_sync(yf.Search, query)
            quotes: list[dict[str, Any]] = search.quotes

            if not quotes:
                raise NoDataAvailableError(
                    message=f"No search results for query '{query}'.",
                    source="yfinance",
                )

            results: list[dict[str, Any]] = []
            for quote in quotes[:limit]:
                results.append(
                    {
                        "symbol": quote.get("symbol"),
                        "name": quote.get("shortname") or quote.get("longname"),
                        "exchange": quote.get("exchange"),
                        "sector": quote.get("sector"),
                        "industry": quote.get("industry"),
                        "quoteType": quote.get("quoteType"),
                    }
                )

            return results

        except NoDataAvailableError:
            raise
        except Exception as e:
            logger.warning("Error in search_stocks for query '%s': %s", query, e)
            raise ExternalAPIError(
                message=f"search_stocks failed: {e}",
                source="yfinance",
            ) from e

    # ------------------------------------------------------------------
    # 5. get_income_statement
    # ------------------------------------------------------------------

    @cached(ttl_seconds=CacheTTL.FINANCIAL_STATEMENTS)
    async def get_income_statement(
        self,
        ticker: str,
        period: str = "annual",
        limit: int = 5,
    ) -> dict[str, Any]:
        """Fetch income statement data.

        Args:
            ticker: Stock ticker symbol.
            period: ``"annual"`` or ``"quarterly"``.
            limit: Number of most-recent periods to include (max 5).

        Returns:
            Dict with ``_ticker``, ``period_type``, ``periods`` (list of
            ISO date strings), and ``data`` mapping line-item names to lists
            of values aligned with ``periods``.

        Raises:
            TickerNotFoundError: If the ticker is invalid.
            NoDataAvailableError: If no income statement data is available.
            ExternalAPIError: On unexpected errors.
        """
        try:
            yf_ticker = yf.Ticker(ticker)

            if period == "quarterly":
                df: pd.DataFrame = await self._run_sync(
                    getattr, yf_ticker, "quarterly_income_stmt"
                )
            else:
                df = await self._run_sync(getattr, yf_ticker, "income_stmt")

            if df is None or df.empty:
                raise NoDataAvailableError(
                    message=f"No income statement data for '{ticker}' ({period}).",
                    source="yfinance",
                    ticker=ticker,
                )

            return self._format_financial_statement(df, ticker, period, limit)

        except (TickerNotFoundError, NoDataAvailableError):
            raise
        except Exception as e:
            self._handle_error(e, ticker, "get_income_statement")

    # ------------------------------------------------------------------
    # 6. get_balance_sheet
    # ------------------------------------------------------------------

    @cached(ttl_seconds=CacheTTL.FINANCIAL_STATEMENTS)
    async def get_balance_sheet(
        self,
        ticker: str,
        period: str = "annual",
        limit: int = 5,
    ) -> dict[str, Any]:
        """Fetch balance sheet data.

        Args:
            ticker: Stock ticker symbol.
            period: ``"annual"`` or ``"quarterly"``.
            limit: Number of most-recent periods to include (max 5).

        Returns:
            Dict with ``_ticker``, ``period_type``, ``periods``, and ``data``.

        Raises:
            TickerNotFoundError: If the ticker is invalid.
            NoDataAvailableError: If no balance sheet data is available.
            ExternalAPIError: On unexpected errors.
        """
        try:
            yf_ticker = yf.Ticker(ticker)

            if period == "quarterly":
                df: pd.DataFrame = await self._run_sync(
                    getattr, yf_ticker, "quarterly_balance_sheet"
                )
            else:
                df = await self._run_sync(getattr, yf_ticker, "balance_sheet")

            if df is None or df.empty:
                raise NoDataAvailableError(
                    message=f"No balance sheet data for '{ticker}' ({period}).",
                    source="yfinance",
                    ticker=ticker,
                )

            return self._format_financial_statement(df, ticker, period, limit)

        except (TickerNotFoundError, NoDataAvailableError):
            raise
        except Exception as e:
            self._handle_error(e, ticker, "get_balance_sheet")

    # ------------------------------------------------------------------
    # 7. get_cash_flow
    # ------------------------------------------------------------------

    @cached(ttl_seconds=CacheTTL.FINANCIAL_STATEMENTS)
    async def get_cash_flow(
        self,
        ticker: str,
        period: str = "annual",
        limit: int = 5,
    ) -> dict[str, Any]:
        """Fetch cash flow statement data.

        Args:
            ticker: Stock ticker symbol.
            period: ``"annual"`` or ``"quarterly"``.
            limit: Number of most-recent periods to include (max 5).

        Returns:
            Dict with ``_ticker``, ``period_type``, ``periods``, and ``data``.

        Raises:
            TickerNotFoundError: If the ticker is invalid.
            NoDataAvailableError: If no cash flow data is available.
            ExternalAPIError: On unexpected errors.
        """
        try:
            yf_ticker = yf.Ticker(ticker)

            if period == "quarterly":
                df: pd.DataFrame = await self._run_sync(
                    getattr, yf_ticker, "quarterly_cashflow"
                )
            else:
                df = await self._run_sync(getattr, yf_ticker, "cashflow")

            if df is None or df.empty:
                raise NoDataAvailableError(
                    message=f"No cash flow data for '{ticker}' ({period}).",
                    source="yfinance",
                    ticker=ticker,
                )

            return self._format_financial_statement(df, ticker, period, limit)

        except (TickerNotFoundError, NoDataAvailableError):
            raise
        except Exception as e:
            self._handle_error(e, ticker, "get_cash_flow")

    # ------------------------------------------------------------------
    # Financial statement helper
    # ------------------------------------------------------------------

    @staticmethod
    def _format_financial_statement(
        df: pd.DataFrame,
        ticker: str,
        period_type: str,
        limit: int,
    ) -> dict[str, Any]:
        """Convert a yfinance financial-statement DataFrame to a clean dict.

        yfinance returns statements with line-item names as the index and
        period dates as columns.  This helper limits to the *limit* most
        recent columns and converts everything to JSON-safe Python types.

        Args:
            df: The raw yfinance DataFrame (index=line items, columns=dates).
            ticker: The ticker symbol (for inclusion in the result).
            period_type: ``"annual"`` or ``"quarterly"``.
            limit: Maximum number of period columns to include.

        Returns:
            Dict with ``_ticker``, ``period_type``, ``periods``, ``data``.
        """
        # Columns are dates; take most recent *limit*
        df = df.iloc[:, :limit]

        # Build period labels as ISO date strings
        periods: list[str] = []
        for col in df.columns:
            if isinstance(col, pd.Timestamp):
                periods.append(col.strftime("%Y-%m-%d"))
            else:
                periods.append(str(col))

        # Build data dict: line_item -> list of values per period
        data: dict[str, list[Any]] = {}
        for line_item in df.index:
            values: list[Any] = []
            for val in df.loc[line_item]:
                if pd.isna(val):
                    values.append(None)
                elif isinstance(val, (np.integer,)):
                    values.append(int(val))
                elif isinstance(val, (np.floating,)):
                    f = float(val)
                    values.append(None if (math.isnan(f) or math.isinf(f)) else f)
                else:
                    values.append(val)
            data[str(line_item)] = values

        return {
            "_ticker": ticker,
            "period_type": period_type,
            "periods": periods,
            "data": data,
        }

    # ------------------------------------------------------------------
    # 8. get_financial_metrics
    # ------------------------------------------------------------------

    @cached(ttl_seconds=CacheTTL.FINANCIAL_METRICS)
    async def get_financial_metrics(self, ticker: str) -> dict[str, Any]:
        """Fetch ~25 financial ratios and metrics organized by section.

        Consolidates valuation, profitability, growth, per-share, financial
        health, cash-flow, and dividend metrics into a single response.
        Includes computed fields: ``fcfYield``, ``ocfToNetIncome``.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Dict with ``_ticker`` and seven section sub-dicts.

        Raises:
            TickerNotFoundError: If the ticker is invalid.
            ExternalAPIError: On unexpected errors.
        """
        try:
            yf_ticker = yf.Ticker(ticker)
            info: dict[str, Any] = await self._run_sync(getattr, yf_ticker, "info")

            if not info or not info.get("shortName"):
                raise TickerNotFoundError(ticker=ticker)

            # Computed metrics
            fcf = info.get("freeCashflow")
            market_cap = info.get("marketCap")
            fcf_yield: float | None = None
            if fcf and market_cap and market_cap != 0:
                fcf_yield = round(fcf / market_cap, 6)

            ocf = info.get("operatingCashflow")
            net_income = info.get("netIncomeToCommon")
            ocf_to_ni: float | None = None
            if ocf and net_income and net_income != 0:
                ocf_to_ni = round(ocf / net_income, 4)

            result = {
                "_ticker": ticker,
                "valuation": {
                    "trailingPE": _safe_float(info.get("trailingPE")),
                    "forwardPE": _safe_float(info.get("forwardPE")),
                    "priceToBook": _safe_float(info.get("priceToBook")),
                    "priceToSales": _safe_float(
                        info.get("priceToSalesTrailing12Months")
                    ),
                    "pegRatio": _safe_float(info.get("pegRatio")),
                    "enterpriseToEbitda": _safe_float(
                        info.get("enterpriseToEbitda")
                    ),
                    "enterpriseToRevenue": _safe_float(
                        info.get("enterpriseToRevenue")
                    ),
                },
                "profitability": {
                    "returnOnEquity": _safe_float(info.get("returnOnEquity")),
                    "returnOnAssets": _safe_float(info.get("returnOnAssets")),
                    "grossMargins": _safe_float(info.get("grossMargins")),
                    "operatingMargins": _safe_float(info.get("operatingMargins")),
                    "profitMargins": _safe_float(info.get("profitMargins")),
                    "ebitdaMargins": _safe_float(info.get("ebitdaMargins")),
                },
                "growth": {
                    "revenueGrowth": _safe_float(info.get("revenueGrowth")),
                    "earningsGrowth": _safe_float(info.get("earningsGrowth")),
                    "earningsQuarterlyGrowth": _safe_float(
                        info.get("earningsQuarterlyGrowth")
                    ),
                },
                "per_share": {
                    "trailingEps": _safe_float(info.get("trailingEps")),
                    "forwardEps": _safe_float(info.get("forwardEps")),
                    "bookValue": _safe_float(info.get("bookValue")),
                    "revenuePerShare": _safe_float(info.get("revenuePerShare")),
                },
                "financial_health": {
                    "debtToEquity": _safe_float(info.get("debtToEquity")),
                    "currentRatio": _safe_float(info.get("currentRatio")),
                    "quickRatio": _safe_float(info.get("quickRatio")),
                    "interestCoverage": _safe_float(info.get("interestCoverage")),
                },
                "cash_flow": {
                    "freeCashflow": _safe_float(fcf),
                    "operatingCashflow": _safe_float(ocf),
                    "fcfYield": _safe_float(fcf_yield),
                    "ocfToNetIncome": _safe_float(ocf_to_ni),
                },
                "dividends": {
                    "dividendYield": _safe_float(info.get("dividendYield")),
                    "payoutRatio": _safe_float(info.get("payoutRatio")),
                    "fiveYearAvgDividendYield": _safe_float(
                        info.get("fiveYearAvgDividendYield")
                    ),
                },
            }

            return result

        except TickerNotFoundError:
            raise
        except Exception as e:
            self._handle_error(e, ticker, "get_financial_metrics")

    # ------------------------------------------------------------------
    # 9. get_technical_data
    # ------------------------------------------------------------------

    @cached(ttl_func=get_price_data_ttl)
    async def get_technical_data(
        self, ticker: str, period: str = "1y"
    ) -> dict[str, Any]:
        """Fetch raw OHLCV data for technical analysis computation.

        The tools layer uses the ``ta`` library to compute indicators from
        this data.  This method returns the raw price series only.

        Args:
            ticker: Stock ticker symbol.
            period: yfinance period string.

        Returns:
            Dict with ``_ticker``, ``period``, and ``ohlcv`` (list of
            OHLCV dicts with ISO date strings).

        Raises:
            TickerNotFoundError: If the ticker is invalid.
            NoDataAvailableError: If yfinance returns no data.
            ExternalAPIError: On unexpected errors.
        """
        try:
            yf_ticker = yf.Ticker(ticker)
            df: pd.DataFrame = await self._run_sync(
                yf_ticker.history, period=period
            )

            if df is None or df.empty:
                raise NoDataAvailableError(
                    message=f"No price data for '{ticker}' (period={period}).",
                    source="yfinance",
                    ticker=ticker,
                )

            ohlcv = _df_to_records(df[["Open", "High", "Low", "Close", "Volume"]])

            return {
                "_ticker": ticker,
                "period": period,
                "ohlcv": ohlcv,
            }

        except (TickerNotFoundError, NoDataAvailableError):
            raise
        except Exception as e:
            self._handle_error(e, ticker, "get_technical_data")

    # ------------------------------------------------------------------
    # 10. get_price_analysis
    # ------------------------------------------------------------------

    @cached(ttl_func=get_price_data_ttl)
    async def get_price_analysis(
        self, ticker: str, period: str = "6mo"
    ) -> dict[str, Any]:
        """Compute price statistics, moving-average analysis, and trend direction.

        Args:
            ticker: Stock ticker symbol.
            period: yfinance period string (e.g. ``"6mo"``, ``"1y"``).

        Returns:
            Dict with ``_ticker``, ``price_stats``, ``moving_averages``,
            and ``trend``.

        Raises:
            TickerNotFoundError: If the ticker is invalid.
            NoDataAvailableError: If yfinance returns no data.
            ExternalAPIError: On unexpected errors.
        """
        try:
            yf_ticker = yf.Ticker(ticker)
            # Fetch enough data for SMA 200
            df: pd.DataFrame = await self._run_sync(
                yf_ticker.history, period="2y"
            )

            if df is None or df.empty:
                raise NoDataAvailableError(
                    message=f"No price data for '{ticker}' (period={period}).",
                    source="yfinance",
                    ticker=ticker,
                )

            close = df["Close"]
            current_price = _safe_float(close.iloc[-1])

            # ---- Price statistics ----
            # Trim to requested period for stats
            period_df = self._get_period_slice(df, period)
            period_close = period_df["Close"]

            first_close = _safe_float(period_close.iloc[0])
            price_change_pct: float | None = None
            if first_close and current_price and first_close != 0:
                price_change_pct = round(
                    ((current_price - first_close) / first_close) * 100, 2
                )

            avg_volume = _safe_int(period_df["Volume"].mean())
            avg_daily_range: float | None = None
            if not period_df.empty:
                daily_range = period_df["High"] - period_df["Low"]
                avg_daily_range = _safe_float(daily_range.mean())

            price_stats = {
                "currentPrice": current_price,
                "periodHigh": _safe_float(period_close.max()),
                "periodLow": _safe_float(period_close.min()),
                "priceChangePct": price_change_pct,
                "avgDailyRange": avg_daily_range,
                "avgVolume": avg_volume,
            }

            # ---- Moving average analysis ----
            sma_20 = _safe_float(close.rolling(window=20).mean().iloc[-1])
            sma_50 = _safe_float(close.rolling(window=50).mean().iloc[-1])
            sma_200 = _safe_float(close.rolling(window=200).mean().iloc[-1])

            def _price_vs_ma(ma_val: float | None) -> dict[str, Any]:
                if ma_val is None or current_price is None or ma_val == 0:
                    return {"value": ma_val, "position": None, "distance_pct": None}
                dist = round(((current_price - ma_val) / ma_val) * 100, 2)
                position = "above" if current_price > ma_val else "below"
                return {"value": round(ma_val, 2), "position": position, "distance_pct": dist}

            # MA alignment: bullish = price > SMA20 > SMA50 > SMA200
            ma_alignment = "neutral"
            if sma_20 and sma_50 and sma_200:
                if sma_20 > sma_50 > sma_200:
                    ma_alignment = "bullish"
                elif sma_20 < sma_50 < sma_200:
                    ma_alignment = "bearish"

            # Golden/death cross detection (SMA50 vs SMA200)
            cross_status = None
            if len(close) >= 200:
                sma50_series = close.rolling(window=50).mean()
                sma200_series = close.rolling(window=200).mean()
                valid = sma50_series.dropna()
                valid200 = sma200_series.dropna()
                if len(valid) >= 2 and len(valid200) >= 2:
                    prev_50 = _safe_float(sma50_series.iloc[-2])
                    prev_200 = _safe_float(sma200_series.iloc[-2])
                    curr_50 = _safe_float(sma50_series.iloc[-1])
                    curr_200 = _safe_float(sma200_series.iloc[-1])
                    if prev_50 and prev_200 and curr_50 and curr_200:
                        if prev_50 <= prev_200 and curr_50 > curr_200:
                            cross_status = "golden_cross"
                        elif prev_50 >= prev_200 and curr_50 < curr_200:
                            cross_status = "death_cross"

            moving_averages = {
                "SMA20": _price_vs_ma(sma_20),
                "SMA50": _price_vs_ma(sma_50),
                "SMA200": _price_vs_ma(sma_200),
                "alignment": ma_alignment,
                "crossStatus": cross_status,
            }

            # ---- Trend assessment ----
            short_term = "neutral"
            medium_term = "neutral"
            long_term = "neutral"

            if sma_20 and current_price:
                if current_price > sma_20:
                    short_term = "bullish"
                else:
                    short_term = "bearish"

            if sma_50 and current_price:
                if current_price > sma_50:
                    medium_term = "bullish"
                else:
                    medium_term = "bearish"

            if sma_200 and current_price:
                if current_price > sma_200:
                    long_term = "bullish"
                else:
                    long_term = "bearish"

            trend = {
                "shortTerm": short_term,
                "mediumTerm": medium_term,
                "longTerm": long_term,
            }

            return {
                "_ticker": ticker,
                "period": period,
                "price_stats": price_stats,
                "moving_averages": moving_averages,
                "trend": trend,
            }

        except (TickerNotFoundError, NoDataAvailableError):
            raise
        except Exception as e:
            self._handle_error(e, ticker, "get_price_analysis")

    @staticmethod
    def _get_period_slice(df: pd.DataFrame, period: str) -> pd.DataFrame:
        """Slice a DataFrame to the most recent rows matching a yfinance period string.

        Args:
            df: DataFrame with a DatetimeIndex.
            period: Period like ``"1mo"``, ``"3mo"``, ``"6mo"``, ``"1y"``, ``"2y"``.

        Returns:
            Sliced DataFrame.
        """
        period_map: dict[str, int] = {
            "1mo": 30,
            "3mo": 90,
            "6mo": 180,
            "1y": 365,
            "2y": 730,
            "5y": 1825,
            "ytd": (datetime.now() - datetime(datetime.now().year, 1, 1)).days,
        }
        days = period_map.get(period, 180)
        cutoff_utc = pd.Timestamp.now(tz="UTC") - timedelta(days=days)
        try:
            mask = df.index >= cutoff_utc
        except TypeError:
            # Fallback for timezone-naive index
            cutoff_naive = pd.Timestamp.now() - timedelta(days=days)
            mask = df.index >= cutoff_naive
        sliced = df[mask]
        return sliced if not sliced.empty else df

    # ------------------------------------------------------------------
    # 11. get_analyst_data
    # ------------------------------------------------------------------

    @cached(ttl_seconds=CacheTTL.ANALYST_DATA)
    async def get_analyst_data(self, ticker: str) -> dict[str, Any]:
        """Fetch analyst recommendations and price targets.

        Args:
            ticker: Stock ticker symbol.

        Returns:
            Dict with ``_ticker``, ``price_targets``, ``consensus``,
            and ``recent_trend``.

        Raises:
            TickerNotFoundError: If the ticker is invalid.
            NoDataAvailableError: If no analyst data is available.
            ExternalAPIError: On unexpected errors.
        """
        try:
            yf_ticker = yf.Ticker(ticker)
            info: dict[str, Any] = await self._run_sync(getattr, yf_ticker, "info")

            if not info or not info.get("shortName"):
                raise TickerNotFoundError(ticker=ticker)

            current_price = _safe_float(info.get("currentPrice"))

            # Price targets
            try:
                targets = await self._run_sync(
                    getattr, yf_ticker, "analyst_price_targets"
                )
            except Exception:
                targets = None

            price_targets: dict[str, Any] = {}
            if targets is not None and isinstance(targets, dict):
                mean_target = _safe_float(targets.get("mean"))
                upside_pct: float | None = None
                if mean_target and current_price and current_price != 0:
                    upside_pct = round(
                        ((mean_target - current_price) / current_price) * 100, 2
                    )
                price_targets = {
                    "current": _safe_float(targets.get("current")),
                    "mean": mean_target,
                    "median": _safe_float(targets.get("median")),
                    "high": _safe_float(targets.get("high")),
                    "low": _safe_float(targets.get("low")),
                    "numberOfAnalysts": _safe_int(targets.get("numberOfAnalysts")),
                    "upsidePct": upside_pct,
                }

            # Recommendations
            try:
                recs: pd.DataFrame = await self._run_sync(
                    getattr, yf_ticker, "recommendations"
                )
            except Exception:
                recs = None

            consensus: dict[str, Any] = {}
            recent_trend: list[dict[str, Any]] = []

            if recs is not None and not recs.empty:
                # yfinance recommendations may have columns like
                # period, strongBuy, buy, hold, sell, strongSell
                if "strongBuy" in recs.columns:
                    # Summary-format recommendations
                    latest = recs.iloc[0] if not recs.empty else None
                    if latest is not None:
                        total = sum(
                            _safe_int(latest.get(col)) or 0
                            for col in [
                                "strongBuy",
                                "buy",
                                "hold",
                                "sell",
                                "strongSell",
                            ]
                        )
                        consensus = {
                            "strongBuy": _safe_int(latest.get("strongBuy")),
                            "buy": _safe_int(latest.get("buy")),
                            "hold": _safe_int(latest.get("hold")),
                            "sell": _safe_int(latest.get("sell")),
                            "strongSell": _safe_int(latest.get("strongSell")),
                            "totalAnalysts": total,
                        }

                    # Recent trend: last 4 rows
                    for idx, row in recs.head(4).iterrows():
                        period_label = (
                            idx.strftime("%Y-%m-%d")
                            if isinstance(idx, pd.Timestamp)
                            else str(row.get("period", idx))
                        )
                        recent_trend.append(
                            {
                                "period": period_label,
                                "strongBuy": _safe_int(row.get("strongBuy")),
                                "buy": _safe_int(row.get("buy")),
                                "hold": _safe_int(row.get("hold")),
                                "sell": _safe_int(row.get("sell")),
                                "strongSell": _safe_int(row.get("strongSell")),
                            }
                        )

            # Recommendation key from info
            rec_key = info.get("recommendationKey")
            rec_mean = _safe_float(info.get("recommendationMean"))

            if not price_targets and not consensus:
                raise NoDataAvailableError(
                    message=f"No analyst data available for '{ticker}'.",
                    source="yfinance",
                    ticker=ticker,
                )

            return {
                "_ticker": ticker,
                "currentPrice": current_price,
                "recommendationKey": rec_key,
                "recommendationMean": rec_mean,
                "price_targets": price_targets,
                "consensus": consensus,
                "recent_trend": recent_trend,
            }

        except (TickerNotFoundError, NoDataAvailableError):
            raise
        except Exception as e:
            self._handle_error(e, ticker, "get_analyst_data")

    # ------------------------------------------------------------------
    # 12. get_institutional_holders
    # ------------------------------------------------------------------

    @cached(ttl_seconds=CacheTTL.INSTITUTIONAL_HOLDERS)
    async def get_institutional_holders(
        self, ticker: str, limit: int = 10
    ) -> dict[str, Any]:
        """Fetch institutional ownership overview and top holders.

        Args:
            ticker: Stock ticker symbol.
            limit: Maximum number of institutional holders to return.

        Returns:
            Dict with ``_ticker``, ``overview`` (ownership percentages),
            and ``top_holders`` (list of holder dicts).

        Raises:
            TickerNotFoundError: If the ticker is invalid.
            NoDataAvailableError: If no holder data is available.
            ExternalAPIError: On unexpected errors.
        """
        try:
            yf_ticker = yf.Ticker(ticker)
            info: dict[str, Any] = await self._run_sync(getattr, yf_ticker, "info")

            if not info or not info.get("shortName"):
                raise TickerNotFoundError(ticker=ticker)

            # Major holders (ownership percentages)
            try:
                major: pd.DataFrame = await self._run_sync(
                    getattr, yf_ticker, "major_holders"
                )
            except Exception:
                major = None

            overview: dict[str, Any] = {}
            if major is not None and not major.empty:
                # major_holders is a 2-column DataFrame with values and labels
                for _, row in major.iterrows():
                    val = row.iloc[0] if len(row) > 0 else None
                    label = row.iloc[1] if len(row) > 1 else None
                    if label and val is not None:
                        label_str = str(label).strip()
                        overview[label_str] = str(val)

            # Institutional holders
            try:
                inst: pd.DataFrame = await self._run_sync(
                    getattr, yf_ticker, "institutional_holders"
                )
            except Exception:
                inst = None

            top_holders: list[dict[str, Any]] = []
            if inst is not None and not inst.empty:
                for _, row in inst.head(limit).iterrows():
                    holder: dict[str, Any] = {}
                    for col in inst.columns:
                        val = row[col]
                        if pd.isna(val):
                            holder[col] = None
                        elif isinstance(val, pd.Timestamp):
                            holder[col] = val.strftime("%Y-%m-%d")
                        elif isinstance(val, (np.integer,)):
                            holder[col] = int(val)
                        elif isinstance(val, (np.floating,)):
                            f = float(val)
                            holder[col] = None if (math.isnan(f) or math.isinf(f)) else f
                        else:
                            holder[col] = val
                    top_holders.append(holder)

            if not overview and not top_holders:
                raise NoDataAvailableError(
                    message=f"No institutional holder data for '{ticker}'.",
                    source="yfinance",
                    ticker=ticker,
                )

            # Short interest from info
            short_data = {
                "shortRatio": _safe_float(info.get("shortRatio")),
                "shortPercentOfFloat": _safe_float(info.get("shortPercentOfFloat")),
                "sharesShort": _safe_int(info.get("sharesShort")),
                "sharesShortPriorMonth": _safe_int(info.get("sharesShortPriorMonth")),
            }

            return {
                "_ticker": ticker,
                "overview": overview,
                "top_holders": top_holders,
                "short_interest": short_data,
            }

        except (TickerNotFoundError, NoDataAvailableError):
            raise
        except Exception as e:
            self._handle_error(e, ticker, "get_institutional_holders")

    # ------------------------------------------------------------------
    # 13. get_earnings_data
    # ------------------------------------------------------------------

    @cached(ttl_seconds=CacheTTL.EARNINGS_DATA)
    async def get_earnings_data(
        self, ticker: str, quarters: int = 8
    ) -> dict[str, Any]:
        """Fetch earnings dates, EPS estimates/actuals, and surprise history.

        Args:
            ticker: Stock ticker symbol.
            quarters: Number of historical quarters to include.

        Returns:
            Dict with ``_ticker``, ``next_earnings``, ``history`` (list of
            quarter dicts), and ``beat_miss_summary``.

        Raises:
            TickerNotFoundError: If the ticker is invalid.
            NoDataAvailableError: If no earnings data is available.
            ExternalAPIError: On unexpected errors.
        """
        try:
            yf_ticker = yf.Ticker(ticker)
            info: dict[str, Any] = await self._run_sync(getattr, yf_ticker, "info")

            if not info or not info.get("shortName"):
                raise TickerNotFoundError(ticker=ticker)

            # Earnings dates
            try:
                earnings_dates: pd.DataFrame = await self._run_sync(
                    getattr, yf_ticker, "earnings_dates"
                )
            except Exception:
                earnings_dates = None

            if earnings_dates is None or earnings_dates.empty:
                raise NoDataAvailableError(
                    message=f"No earnings data available for '{ticker}'.",
                    source="yfinance",
                    ticker=ticker,
                )

            now = pd.Timestamp.now(tz="UTC")
            # Try timezone-aware comparison; fall back to naive
            try:
                future_mask = earnings_dates.index > now
            except TypeError:
                now_naive = pd.Timestamp.now()
                future_mask = earnings_dates.index > now_naive

            future_dates = earnings_dates[future_mask]
            past_dates = earnings_dates[~future_mask]

            # Next earnings
            next_earnings: dict[str, Any] = {}
            if not future_dates.empty:
                next_date = future_dates.index[-1]  # earliest future date (index is sorted desc)
                # Actually pick the closest future date
                if isinstance(next_date, pd.Timestamp):
                    # Get the minimum future date
                    closest_future = future_dates.index.min()
                    next_earnings = {
                        "date": closest_future.strftime("%Y-%m-%d"),
                        "epsEstimate": _safe_float(
                            future_dates.loc[closest_future].get("EPS Estimate")
                            if "EPS Estimate" in future_dates.columns
                            else None
                        ),
                    }

            # Historical earnings
            history: list[dict[str, Any]] = []
            if not past_dates.empty:
                # Limit to requested quarters, most recent first
                recent_past = past_dates.head(quarters)
                for date_idx, row in recent_past.iterrows():
                    eps_estimate = _safe_float(
                        row.get("EPS Estimate") if "EPS Estimate" in recent_past.columns else None
                    )
                    eps_actual = _safe_float(
                        row.get("Reported EPS") if "Reported EPS" in recent_past.columns else None
                    )
                    surprise_pct = _safe_float(
                        row.get("Surprise(%)") if "Surprise(%)" in recent_past.columns else None
                    )

                    entry: dict[str, Any] = {
                        "date": (
                            date_idx.strftime("%Y-%m-%d")
                            if isinstance(date_idx, pd.Timestamp)
                            else str(date_idx)
                        ),
                        "epsEstimate": eps_estimate,
                        "epsActual": eps_actual,
                        "surprisePct": surprise_pct,
                    }
                    history.append(entry)

            # Beat/miss summary
            beats = 0
            misses = 0
            meets = 0
            total_with_data = 0
            for h in history:
                if h["epsEstimate"] is not None and h["epsActual"] is not None:
                    total_with_data += 1
                    if h["epsActual"] > h["epsEstimate"]:
                        beats += 1
                    elif h["epsActual"] < h["epsEstimate"]:
                        misses += 1
                    else:
                        meets += 1

            beat_miss_summary = {
                "beats": beats,
                "misses": misses,
                "meets": meets,
                "totalWithData": total_with_data,
                "beatRate": round(beats / total_with_data, 2) if total_with_data > 0 else None,
            }

            return {
                "_ticker": ticker,
                "next_earnings": next_earnings,
                "history": history,
                "beat_miss_summary": beat_miss_summary,
            }

        except (TickerNotFoundError, NoDataAvailableError):
            raise
        except Exception as e:
            self._handle_error(e, ticker, "get_earnings_data")

    # ------------------------------------------------------------------
    # 14. get_index_data
    # ------------------------------------------------------------------

    @cached(ttl_func=get_price_data_ttl)
    async def get_index_data(
        self, index_symbol: str, period: str = "1y"
    ) -> dict[str, Any]:
        """Fetch market index data for benchmarking.

        Accepts either a friendly name (e.g. ``"SP500"``) or a raw yfinance
        symbol (e.g. ``"^GSPC"``).

        Args:
            index_symbol: Index name from ``INDEX_SYMBOLS`` or a yfinance ticker.
            period: yfinance period string.

        Returns:
            Dict with ``_ticker``, ``name``, ``summary`` (current value,
            change %, 52-week range), and ``history``.

        Raises:
            NoDataAvailableError: If no data is available for the index.
            ExternalAPIError: On unexpected errors.
        """
        try:
            # Resolve friendly name to yfinance symbol
            yf_symbol = INDEX_SYMBOLS.get(index_symbol.upper(), index_symbol)

            yf_ticker = yf.Ticker(yf_symbol)
            df: pd.DataFrame = await self._run_sync(
                yf_ticker.history, period=period
            )

            if df is None or df.empty:
                raise NoDataAvailableError(
                    message=f"No data for index '{index_symbol}' ({yf_symbol}).",
                    source="yfinance",
                    ticker=yf_symbol,
                )

            close = df["Close"]
            current_value = _safe_float(close.iloc[-1])
            first_value = _safe_float(close.iloc[0])

            period_change_pct: float | None = None
            if first_value and current_value and first_value != 0:
                period_change_pct = round(
                    ((current_value - first_value) / first_value) * 100, 2
                )

            # 52-week range from the data (use all available rows)
            high_52w = _safe_float(close.max())
            low_52w = _safe_float(close.min())

            # SMA200
            sma_200 = _safe_float(close.rolling(window=200).mean().iloc[-1])
            vs_sma200: float | None = None
            if sma_200 and current_value and sma_200 != 0:
                vs_sma200 = round(
                    ((current_value - sma_200) / sma_200) * 100, 2
                )

            # Attempt to get index name from info
            try:
                info: dict[str, Any] = await self._run_sync(getattr, yf_ticker, "info")
                index_name = info.get("shortName", index_symbol)
            except Exception:
                index_name = index_symbol

            summary = {
                "currentValue": current_value,
                "periodChangePct": period_change_pct,
                "periodHigh": _safe_float(df["High"].max()),
                "periodLow": _safe_float(df["Low"].min()),
                "fiftyTwoWeekHigh": high_52w,
                "fiftyTwoWeekLow": low_52w,
                "vsSMA200Pct": vs_sma200,
            }

            return {
                "_ticker": yf_symbol,
                "name": index_name,
                "period": period,
                "summary": summary,
            }

        except NoDataAvailableError:
            raise
        except Exception as e:
            logger.warning(
                "Error in get_index_data for '%s': %s", index_symbol, e
            )
            raise ExternalAPIError(
                message=f"get_index_data failed: {e}",
                source="yfinance",
                ticker=index_symbol,
            ) from e

    # ------------------------------------------------------------------
    # 15. get_insider_transactions
    # ------------------------------------------------------------------

    @cached(ttl_seconds=CacheTTL.INSIDER_TRANSACTIONS)
    async def get_insider_transactions(
        self, ticker: str, limit: int = 20
    ) -> dict[str, Any]:
        """Fetch recent insider transactions (buys/sells) for a stock.

        Args:
            ticker: Stock ticker symbol.
            limit: Maximum number of transactions to return.

        Returns:
            Dict with ``_ticker``, ``summary`` (buy/sell counts and totals),
            and ``transactions`` (list of transaction dicts).

        Raises:
            TickerNotFoundError: If the ticker is invalid.
            NoDataAvailableError: If no insider transaction data is available.
            ExternalAPIError: On unexpected errors.
        """
        try:
            yf_ticker = yf.Ticker(ticker)
            info: dict[str, Any] = await self._run_sync(getattr, yf_ticker, "info")

            if not info or not info.get("shortName"):
                raise TickerNotFoundError(ticker=ticker)

            try:
                df: pd.DataFrame = await self._run_sync(
                    getattr, yf_ticker, "insider_transactions"
                )
            except Exception:
                df = None

            if df is None or df.empty:
                raise NoDataAvailableError(
                    message=f"No insider transaction data available for '{ticker}'.",
                    source="yfinance",
                    ticker=ticker,
                )

            transactions: list[dict[str, Any]] = []
            buy_count = 0
            sell_count = 0
            buy_value = 0.0
            sell_value = 0.0

            for _, row in df.head(limit).iterrows():
                text = str(row.get("Text", "")) if row.get("Text") is not None else ""
                shares = _safe_int(row.get("Shares"))
                value = _safe_float(row.get("Value"))
                start_date = row.get("Start Date")

                # Determine if buy or sell from the Text field
                text_lower = text.lower()
                if "purchase" in text_lower or "buy" in text_lower:
                    tx_type = "Buy"
                    buy_count += 1
                    if value is not None:
                        buy_value += value
                elif "sale" in text_lower or "sell" in text_lower:
                    tx_type = "Sell"
                    sell_count += 1
                    if value is not None:
                        sell_value += value
                else:
                    tx_type = "Other"

                date_str = (
                    start_date.strftime("%Y-%m-%d")
                    if isinstance(start_date, pd.Timestamp)
                    else str(start_date) if start_date is not None else None
                )

                transactions.append({
                    "insider": str(row.get("Insider", "N/A")),
                    "type": tx_type,
                    "text": text,
                    "shares": shares,
                    "value": value,
                    "date": date_str,
                })

            summary = {
                "totalTransactions": len(transactions),
                "buyCount": buy_count,
                "sellCount": sell_count,
                "otherCount": len(transactions) - buy_count - sell_count,
                "totalBuyValue": buy_value if buy_value > 0 else None,
                "totalSellValue": sell_value if sell_value > 0 else None,
            }

            return {
                "_ticker": ticker,
                "summary": summary,
                "transactions": transactions,
            }

        except (TickerNotFoundError, NoDataAvailableError):
            raise
        except Exception as e:
            self._handle_error(e, ticker, "get_insider_transactions")

    # ------------------------------------------------------------------
    # 16. get_upgrades_downgrades
    # ------------------------------------------------------------------

    @cached(ttl_seconds=CacheTTL.UPGRADES_DOWNGRADES)
    async def get_upgrades_downgrades(
        self, ticker: str, limit: int = 20
    ) -> dict[str, Any]:
        """Fetch recent analyst upgrades and downgrades for a stock.

        Args:
            ticker: Stock ticker symbol.
            limit: Maximum number of entries to return.

        Returns:
            Dict with ``_ticker`` and ``upgrades_downgrades`` (list of dicts
            with firm, to_grade, from_grade, action, date).

        Raises:
            TickerNotFoundError: If the ticker is invalid.
            NoDataAvailableError: If no upgrade/downgrade data is available.
            ExternalAPIError: On unexpected errors.
        """
        try:
            yf_ticker = yf.Ticker(ticker)
            info: dict[str, Any] = await self._run_sync(getattr, yf_ticker, "info")

            if not info or not info.get("shortName"):
                raise TickerNotFoundError(ticker=ticker)

            try:
                df: pd.DataFrame = await self._run_sync(
                    getattr, yf_ticker, "upgrades_downgrades"
                )
            except Exception:
                df = None

            if df is None or df.empty:
                raise NoDataAvailableError(
                    message=f"No upgrades/downgrades data available for '{ticker}'.",
                    source="yfinance",
                    ticker=ticker,
                )

            entries: list[dict[str, Any]] = []
            for date_idx, row in df.head(limit).iterrows():
                date_str = (
                    date_idx.strftime("%Y-%m-%d")
                    if isinstance(date_idx, pd.Timestamp)
                    else str(date_idx)
                )

                entries.append({
                    "date": date_str,
                    "firm": str(row.get("Firm", "N/A")),
                    "toGrade": str(row.get("ToGrade", "N/A")),
                    "fromGrade": str(row.get("FromGrade", "N/A")),
                    "action": str(row.get("Action", "N/A")),
                })

            return {
                "_ticker": ticker,
                "upgrades_downgrades": entries,
            }

        except (TickerNotFoundError, NoDataAvailableError):
            raise
        except Exception as e:
            self._handle_error(e, ticker, "get_upgrades_downgrades")

    # ------------------------------------------------------------------
    # 17. get_earnings_dates
    # ------------------------------------------------------------------

    @cached(ttl_seconds=CacheTTL.EARNINGS_DATES)
    async def get_earnings_dates(
        self, ticker: str, limit: int = 8
    ) -> dict[str, Any]:
        """Fetch upcoming and past earnings dates with EPS estimates.

        Unlike ``get_earnings_data`` which focuses on beat/miss analysis,
        this method returns a simple calendar view of earnings dates with
        EPS estimate, reported EPS, and surprise percentage.

        Args:
            ticker: Stock ticker symbol.
            limit: Maximum number of entries to return.

        Returns:
            Dict with ``_ticker`` and ``earnings_dates`` (list of dicts
            with date, eps_estimate, reported_eps, surprise_pct, is_upcoming).

        Raises:
            TickerNotFoundError: If the ticker is invalid.
            NoDataAvailableError: If no earnings date data is available.
            ExternalAPIError: On unexpected errors.
        """
        try:
            yf_ticker = yf.Ticker(ticker)
            info: dict[str, Any] = await self._run_sync(getattr, yf_ticker, "info")

            if not info or not info.get("shortName"):
                raise TickerNotFoundError(ticker=ticker)

            try:
                df: pd.DataFrame = await self._run_sync(
                    getattr, yf_ticker, "earnings_dates"
                )
            except Exception:
                df = None

            if df is None or df.empty:
                raise NoDataAvailableError(
                    message=f"No earnings date data available for '{ticker}'.",
                    source="yfinance",
                    ticker=ticker,
                )

            now = pd.Timestamp.now(tz="UTC")

            entries: list[dict[str, Any]] = []
            for date_idx, row in df.head(limit).iterrows():
                date_str = (
                    date_idx.strftime("%Y-%m-%d")
                    if isinstance(date_idx, pd.Timestamp)
                    else str(date_idx)
                )

                # Determine if upcoming
                try:
                    is_upcoming = date_idx > now
                except TypeError:
                    is_upcoming = date_idx > pd.Timestamp.now()

                entries.append({
                    "date": date_str,
                    "epsEstimate": _safe_float(
                        row.get("EPS Estimate") if "EPS Estimate" in df.columns else None
                    ),
                    "reportedEps": _safe_float(
                        row.get("Reported EPS") if "Reported EPS" in df.columns else None
                    ),
                    "surprisePct": _safe_float(
                        row.get("Surprise(%)") if "Surprise(%)" in df.columns else None
                    ),
                    "isUpcoming": bool(is_upcoming),
                })

            return {
                "_ticker": ticker,
                "earnings_dates": entries,
            }

        except (TickerNotFoundError, NoDataAvailableError):
            raise
        except Exception as e:
            self._handle_error(e, ticker, "get_earnings_dates")

    # ------------------------------------------------------------------
    # 18. get_stock_news
    # ------------------------------------------------------------------

    @cached(ttl_seconds=CacheTTL.STOCK_NEWS)
    async def get_stock_news(
        self, ticker: str, limit: int = 10
    ) -> dict[str, Any]:
        """Fetch recent news articles for a stock.

        Args:
            ticker: Stock ticker symbol.
            limit: Maximum number of news items to return.

        Returns:
            Dict with ``_ticker`` and ``news`` (list of dicts with title,
            publisher, date, link, related_tickers).

        Raises:
            TickerNotFoundError: If the ticker is invalid.
            NoDataAvailableError: If no news is available.
            ExternalAPIError: On unexpected errors.
        """
        try:
            yf_ticker = yf.Ticker(ticker)
            info: dict[str, Any] = await self._run_sync(getattr, yf_ticker, "info")

            if not info or not info.get("shortName"):
                raise TickerNotFoundError(ticker=ticker)

            try:
                news_list: list[dict[str, Any]] = await self._run_sync(
                    getattr, yf_ticker, "news"
                )
            except Exception:
                news_list = None

            if not news_list:
                raise NoDataAvailableError(
                    message=f"No news available for '{ticker}'.",
                    source="yfinance",
                    ticker=ticker,
                )

            entries: list[dict[str, Any]] = []
            for item in news_list[:limit]:
                # yfinance news can be flat (old format) or nested under "content" (new format)
                content = item.get("content", item)

                # Title
                title = content.get("title") or item.get("title")

                # Publisher — new format nests under provider.displayName
                provider = content.get("provider", {})
                publisher = (
                    provider.get("displayName")
                    if isinstance(provider, dict)
                    else None
                ) or item.get("publisher")

                # Date — new format uses pubDate (ISO string), old uses providerPublishTime (epoch)
                pub_date = content.get("pubDate") or item.get("pubDate")
                publish_time = item.get("providerPublishTime")
                if pub_date is not None:
                    # ISO format like "2026-05-14T14:16:00Z" — simplify
                    date_str = str(pub_date)[:16].replace("T", " ")
                elif publish_time is not None:
                    try:
                        date_str = datetime.fromtimestamp(
                            publish_time, tz=timezone.utc
                        ).strftime("%Y-%m-%d %H:%M UTC")
                    except (ValueError, TypeError, OSError):
                        date_str = str(publish_time)
                else:
                    date_str = None

                # Link — new format nests under canonicalUrl.url
                canonical = content.get("canonicalUrl", {})
                link = (
                    canonical.get("url")
                    if isinstance(canonical, dict)
                    else None
                ) or item.get("link")

                # Related tickers
                related = item.get("relatedTickers", [])

                entries.append({
                    "title": title,
                    "publisher": publisher,
                    "date": date_str,
                    "link": link,
                    "relatedTickers": related,
                })

            return {
                "_ticker": ticker,
                "news": entries,
            }

        except (TickerNotFoundError, NoDataAvailableError):
            raise
        except Exception as e:
            self._handle_error(e, ticker, "get_stock_news")

    # ------------------------------------------------------------------
    # 19. get_batch_quotes (Phase 2 stub)
    # ------------------------------------------------------------------

    @cached(ttl_seconds=CacheTTL.STOCK_INFO)
    async def get_batch_quotes(
        self,
        tickers: list[str],
        fields: str = "price",
    ) -> dict[str, Any]:
        """Fetch current quotes for multiple tickers.  Phase 2.

        Args:
            tickers: List of ticker symbols (max 20).
            fields: ``"price"``, ``"valuation"``, or ``"full"``.

        Returns:
            Dict mapping ticker to quote data dict.

        Raises:
            NotImplementedError: Always — this is a Phase 2 stub.
        """
        raise NotImplementedError("Phase 2 — not yet implemented")
