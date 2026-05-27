"""FREDDataSource — Federal Reserve Economic Data source for macroeconomic indicators.

Provides methods for fetching treasury yields, economic indicators (CPI,
unemployment, GDP, Fed Funds Rate), and yield curve data from the FRED API.

All synchronous fredapi calls are dispatched via ``_run_sync`` (which uses
``asyncio.to_thread``) so the async event loop is never blocked.  Every public
method is decorated with ``@cached`` for transparent TTL-based caching.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from datetime import datetime, timedelta
from typing import Any, Callable, TypeVar

import pandas as pd

from ..config import CacheTTL
from .cache import cached
from .exceptions import ExternalAPIError, NoDataAvailableError

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ---------------------------------------------------------------------------
# FRED series IDs
# ---------------------------------------------------------------------------

# Treasury yields
SERIES_TREASURY_2Y = "GS2"
SERIES_TREASURY_10Y = "GS10"
SERIES_TREASURY_30Y = "GS30"

# Economic indicators
SERIES_CPI = "CPIAUCSL"
SERIES_UNEMPLOYMENT = "UNRATE"
SERIES_GDP_GROWTH = "A191RL1Q225SBEA"
SERIES_FED_FUNDS = "FEDFUNDS"

# Yield curve
SERIES_YIELD_SPREAD = "T10Y2Y"

# How many data points to return for recent history
_DEFAULT_HISTORY_MONTHS = 12


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


class FREDDataSource:
    """Data source for FRED macroeconomic data.

    Requires a FRED API key (free registration at https://fred.stlouisfed.org/docs/api/api_key.html).
    The key is loaded from the ``FRED_API_KEY`` environment variable.

    All methods are async. Synchronous fredapi I/O is dispatched to a thread
    via ``_run_sync`` so the event loop is never blocked. Public methods are
    decorated with ``@cached`` for transparent TTL-based caching.
    """

    def __init__(self) -> None:
        self._api_key: str | None = os.environ.get("FRED_API_KEY")
        self._fred: Any | None = None  # Lazy-initialized Fred client

    def _get_fred(self) -> Any:
        """Lazy-initialize and return the Fred client.

        Raises:
            ExternalAPIError: If FRED_API_KEY is not configured.
        """
        if self._fred is not None:
            return self._fred

        if not self._api_key:
            raise ExternalAPIError(
                message="FRED_API_KEY is not configured. "
                "Register for a free key at https://fred.stlouisfed.org/docs/api/api_key.html "
                "and add it to your .env file.",
                source="fredapi",
            )

        from fredapi import Fred  # Import here to avoid import error if fredapi not installed

        self._fred = Fred(api_key=self._api_key)
        return self._fred

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    _FRED_TIMEOUT: float = 30.0  # seconds per individual FRED call
    _MAX_RETRIES: int = 3
    _RETRY_BASE_DELAY: float = 2.0  # seconds; actual delay = base * attempt

    @staticmethod
    async def _run_sync(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run a synchronous function in a thread with timeout and retry.

        All fredapi calls go through this method.  Each attempt has a
        30-second timeout.  Transient failures (timeouts, network errors)
        are retried up to 3 times with exponential backoff (2s, 4s, 6s).

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
        for attempt in range(1, FREDDataSource._MAX_RETRIES + 1):
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(func, *args, **kwargs),
                    timeout=FREDDataSource._FRED_TIMEOUT,
                )
            except (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError) as e:
                last_err = e
                if attempt < FREDDataSource._MAX_RETRIES:
                    delay = FREDDataSource._RETRY_BASE_DELAY * attempt
                    logger.warning(
                        "FRED _run_sync attempt %d/%d failed (%s), retrying in %.0fs",
                        attempt, FREDDataSource._MAX_RETRIES, type(e).__name__, delay,
                    )
                    await asyncio.sleep(delay)
        raise last_err  # type: ignore[misc]

    def _fetch_series(
        self,
        series_id: str,
        observation_start: str | None = None,
    ) -> pd.Series:
        """Synchronous helper to fetch a FRED series.

        Args:
            series_id: The FRED series ID (e.g., "GS10").
            observation_start: Start date as "YYYY-MM-DD" string.

        Returns:
            A pandas Series with DatetimeIndex and float values.
        """
        fred = self._get_fred()
        kwargs: dict[str, Any] = {}
        if observation_start:
            kwargs["observation_start"] = observation_start
        return fred.get_series(series_id, **kwargs)

    @staticmethod
    def _series_to_records(
        series: pd.Series,
        value_name: str = "value",
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """Convert a pandas Series to a list of date/value dicts.

        Args:
            series: pandas Series with DatetimeIndex.
            value_name: Name for the value field.
            limit: Maximum number of records (most recent first).

        Returns:
            List of dicts with "date" and *value_name* keys.
        """
        if series is None or series.empty:
            return []

        # Drop NaN values and take the most recent entries
        clean = series.dropna().tail(limit)
        records: list[dict[str, Any]] = []
        for idx, val in clean.items():
            date_str = idx.strftime("%Y-%m-%d") if isinstance(idx, pd.Timestamp) else str(idx)
            records.append({
                "date": date_str,
                value_name: _safe_float(val),
            })
        return records

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    @cached(ttl_seconds=CacheTTL.FRED_DATA)
    async def get_treasury_yields(self, as_of_date: str | None = None) -> dict[str, Any]:
        """Fetch current and recent treasury yields (2Y, 10Y, 30Y).

        Args:
            as_of_date: Optional "YYYY-MM-DD" string. When provided, returns
                data as of that date (for historical replay). Data points
                after this date are filtered out.

        Returns:
            Dict with:
            - current: Dict with 2Y, 10Y, 30Y current yield values.
            - history: List of recent yield records for each maturity.
            - as_of: Date of most recent data point.

        Raises:
            ExternalAPIError: If FRED API key is missing or API fails.
            NoDataAvailableError: If no data is returned.
        """
        ref_date = datetime.strptime(as_of_date, "%Y-%m-%d") if as_of_date else datetime.now()
        start_date = (ref_date - timedelta(days=365)).strftime("%Y-%m-%d")

        try:
            gs2 = await self._run_sync(self._fetch_series, SERIES_TREASURY_2Y, start_date)
            gs10 = await self._run_sync(self._fetch_series, SERIES_TREASURY_10Y, start_date)
            gs30 = await self._run_sync(self._fetch_series, SERIES_TREASURY_30Y, start_date)
        except ExternalAPIError:
            raise
        except Exception as e:
            raise ExternalAPIError(
                message=f"Failed to fetch treasury yields from FRED: {e}",
                source="fredapi",
            ) from e

        # Filter out data after as_of_date when in historical mode
        if as_of_date:
            cutoff = pd.Timestamp(as_of_date)
            gs2 = gs2[gs2.index <= cutoff] if gs2 is not None and not gs2.empty else gs2
            gs10 = gs10[gs10.index <= cutoff] if gs10 is not None and not gs10.empty else gs10
            gs30 = gs30[gs30.index <= cutoff] if gs30 is not None and not gs30.empty else gs30

        # Get current (most recent non-NaN) values
        gs2_clean = gs2.dropna() if gs2 is not None and not gs2.empty else pd.Series(dtype=float)
        gs10_clean = gs10.dropna() if gs10 is not None and not gs10.empty else pd.Series(dtype=float)
        gs30_clean = gs30.dropna() if gs30 is not None and not gs30.empty else pd.Series(dtype=float)

        if gs10_clean.empty:
            raise NoDataAvailableError(
                message="No treasury yield data available from FRED.",
                source="fredapi",
            )

        # Determine the latest date across all series
        latest_dates = []
        for s in [gs2_clean, gs10_clean, gs30_clean]:
            if not s.empty:
                latest_dates.append(s.index[-1])
        as_of = max(latest_dates).strftime("%Y-%m-%d") if latest_dates else "unknown"

        return {
            "current": {
                "2Y": _safe_float(gs2_clean.iloc[-1]) if not gs2_clean.empty else None,
                "10Y": _safe_float(gs10_clean.iloc[-1]) if not gs10_clean.empty else None,
                "30Y": _safe_float(gs30_clean.iloc[-1]) if not gs30_clean.empty else None,
            },
            "history": {
                "2Y": self._series_to_records(gs2, "yield_pct"),
                "10Y": self._series_to_records(gs10, "yield_pct"),
                "30Y": self._series_to_records(gs30, "yield_pct"),
            },
            "as_of": as_of,
        }

    @cached(ttl_seconds=CacheTTL.FRED_DATA)
    async def get_economic_indicators(
        self,
        indicator: str = "all",
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        """Fetch key economic indicators from FRED.

        Available indicators: CPI, unemployment, GDP growth, Fed Funds Rate.

        Args:
            indicator: Specific indicator ("cpi", "unemployment", "gdp", "fed_funds")
                or "all" for all indicators.
            as_of_date: Optional "YYYY-MM-DD" string. When provided, returns
                data as of that date (for historical replay). Data points
                after this date are filtered out.

        Returns:
            Dict with indicator data including current values and recent history.

        Raises:
            ExternalAPIError: If FRED API key is missing or API fails.
            NoDataAvailableError: If no data is returned.
        """
        indicator = indicator.lower().strip()

        # Map user-friendly names to series IDs
        indicator_map = {
            "cpi": (SERIES_CPI, "CPI (Consumer Price Index)", "index_value"),
            "unemployment": (SERIES_UNEMPLOYMENT, "Unemployment Rate", "rate_pct"),
            "gdp": (SERIES_GDP_GROWTH, "Real GDP Growth Rate (Quarterly)", "growth_pct"),
            "fed_funds": (SERIES_FED_FUNDS, "Federal Funds Rate", "rate_pct"),
        }

        if indicator != "all" and indicator not in indicator_map:
            valid = ", ".join(sorted(indicator_map.keys()))
            raise NoDataAvailableError(
                message=f"Unknown indicator '{indicator}'. Valid options: {valid}, all",
                source="fredapi",
            )

        indicators_to_fetch = (
            list(indicator_map.keys()) if indicator == "all" else [indicator]
        )

        ref_date = datetime.strptime(as_of_date, "%Y-%m-%d") if as_of_date else datetime.now()
        start_date = (ref_date - timedelta(days=730)).strftime("%Y-%m-%d")
        results: dict[str, Any] = {}

        for ind_key in indicators_to_fetch:
            series_id, display_name, value_name = indicator_map[ind_key]
            try:
                series = await self._run_sync(self._fetch_series, series_id, start_date)

                # Filter out data after as_of_date when in historical mode
                if as_of_date and series is not None and not series.empty:
                    cutoff = pd.Timestamp(as_of_date)
                    series = series[series.index <= cutoff]

                clean = series.dropna() if series is not None and not series.empty else pd.Series(dtype=float)

                if clean.empty:
                    results[ind_key] = {
                        "name": display_name,
                        "current": None,
                        "as_of": "N/A",
                        "history": [],
                    }
                    continue

                current_val = _safe_float(clean.iloc[-1])
                as_of = clean.index[-1].strftime("%Y-%m-%d") if isinstance(clean.index[-1], pd.Timestamp) else str(clean.index[-1])

                # Calculate change from previous period
                prev_val = _safe_float(clean.iloc[-2]) if len(clean) >= 2 else None
                change = None
                if current_val is not None and prev_val is not None:
                    change = round(current_val - prev_val, 4)

                results[ind_key] = {
                    "name": display_name,
                    "current": current_val,
                    "previous": prev_val,
                    "change": change,
                    "as_of": as_of,
                    "history": self._series_to_records(series, value_name),
                }

            except ExternalAPIError:
                raise
            except Exception as e:
                logger.warning("Failed to fetch %s from FRED: %s", ind_key, e)
                results[ind_key] = {
                    "name": display_name,
                    "current": None,
                    "as_of": "N/A",
                    "error": str(e),
                    "history": [],
                }

        if not results:
            raise NoDataAvailableError(
                message="No economic indicator data available from FRED.",
                source="fredapi",
            )

        return {"indicators": results}

    @cached(ttl_seconds=CacheTTL.FRED_DATA)
    async def get_yield_curve(self, as_of_date: str | None = None) -> dict[str, Any]:
        """Fetch yield curve data (10Y-2Y spread) with inversion detection.

        Args:
            as_of_date: Optional "YYYY-MM-DD" string. When provided, returns
                data as of that date (for historical replay). Data points
                after this date are filtered out.

        Returns:
            Dict with:
            - current_spread: Current 10Y-2Y spread in percentage points.
            - is_inverted: Whether the yield curve is currently inverted.
            - interpretation: Human-readable interpretation of the spread.
            - history: Recent spread history.
            - as_of: Date of most recent data point.

        Raises:
            ExternalAPIError: If FRED API key is missing or API fails.
            NoDataAvailableError: If no data is returned.
        """
        ref_date = datetime.strptime(as_of_date, "%Y-%m-%d") if as_of_date else datetime.now()
        start_date = (ref_date - timedelta(days=730)).strftime("%Y-%m-%d")

        try:
            spread = await self._run_sync(self._fetch_series, SERIES_YIELD_SPREAD, start_date)
        except ExternalAPIError:
            raise
        except Exception as e:
            raise ExternalAPIError(
                message=f"Failed to fetch yield curve data from FRED: {e}",
                source="fredapi",
            ) from e

        # Filter out data after as_of_date when in historical mode
        if as_of_date and spread is not None and not spread.empty:
            cutoff = pd.Timestamp(as_of_date)
            spread = spread[spread.index <= cutoff]

        clean = spread.dropna() if spread is not None and not spread.empty else pd.Series(dtype=float)

        if clean.empty:
            raise NoDataAvailableError(
                message="No yield curve data available from FRED.",
                source="fredapi",
            )

        current_spread = _safe_float(clean.iloc[-1])
        as_of = clean.index[-1].strftime("%Y-%m-%d") if isinstance(clean.index[-1], pd.Timestamp) else str(clean.index[-1])

        # Determine inversion status
        is_inverted = current_spread is not None and current_spread < 0

        # Interpretation
        if current_spread is None:
            interpretation = "Data unavailable."
        elif current_spread < -0.5:
            interpretation = "Deeply inverted — historically a strong recession signal."
        elif current_spread < 0:
            interpretation = "Inverted — yield curve inversion is a recession warning signal."
        elif current_spread < 0.5:
            interpretation = "Flat — often a transitional signal, may precede inversion or steepening."
        elif current_spread < 1.5:
            interpretation = "Normal — moderate positive slope, typical of healthy economic expansion."
        else:
            interpretation = "Steep — strong positive slope, often seen early in economic recovery."

        # Calculate recent trend (change over last 3 months)
        three_months_ago = ref_date - timedelta(days=90)
        recent = clean[clean.index >= pd.Timestamp(three_months_ago)]
        trend_change = None
        if len(recent) >= 2:
            trend_change = round(float(recent.iloc[-1]) - float(recent.iloc[0]), 4)

        return {
            "current_spread": current_spread,
            "is_inverted": is_inverted,
            "interpretation": interpretation,
            "trend_3m_change": trend_change,
            "history": self._series_to_records(spread, "spread_pct"),
            "as_of": as_of,
        }
