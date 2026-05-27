"""MCP tool registrations for macroeconomic data from FRED and market regime analysis.

Registers 4 tools:
- ``get_treasury_yields``: Current treasury yields (2Y, 10Y, 30Y) with history.
- ``get_economic_indicators``: Key macro indicators (CPI, unemployment, GDP, Fed Funds).
- ``get_yield_curve``: 10Y-2Y spread and yield curve inversion detection.
- ``get_market_regime``: Composite market environment assessment (S&P vs 200MA, VIX, regime).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import yfinance as yf
from mcp.server.fastmcp import FastMCP

from ..data_sources.exceptions import DataSourceError
from ..data_sources.fred_source import FREDDataSource
from ..data_sources.yfinance_source import YFinanceDataSource
from ..formatting.json_fmt import format_json
from ..formatting.markdown import (
    format_economic_indicators,
    format_market_regime,
    format_treasury_yields,
    format_yield_curve,
)

logger = logging.getLogger(__name__)


def register_macroeconomic_tools(
    mcp: FastMCP,
    fred_source: FREDDataSource,
    yfinance_source: YFinanceDataSource,
) -> None:
    """Register all macroeconomic MCP tools on the given FastMCP server.

    Args:
        mcp: The FastMCP server instance to register tools on.
        fred_source: The FREDDataSource instance for FRED API data.
        yfinance_source: The YFinanceDataSource instance for market data.
    """

    @mcp.tool()
    async def get_treasury_yields(format: str = "markdown") -> str:
        """Get current US Treasury yields (2-year, 10-year, 30-year) with recent trends.

        Returns current yield levels and 12-month history for the three major
        treasury maturities. Use this to understand the interest rate environment,
        assess fixed-income attractiveness relative to equities, and evaluate
        the cost of capital for company valuations.

        Key interpretation:
        - Rising yields = tighter financial conditions, headwind for growth stocks.
        - Falling yields = easing conditions, tailwind for bonds and long-duration assets.
        - 10Y yield is the benchmark for mortgage rates and corporate borrowing costs.

        Args:
            format: Output format - "markdown" (default) or "json"
        """
        try:
            data = await fred_source.get_treasury_yields()
            if format == "json":
                return format_json(data)
            return format_treasury_yields(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"

    @mcp.tool()
    async def get_economic_indicators(
        indicator: str = "all",
        format: str = "markdown",
    ) -> str:
        """Get key US economic indicators from FRED.

        Available indicators:
        - **cpi**: Consumer Price Index — measures inflation.
        - **unemployment**: Unemployment Rate — labor market health.
        - **gdp**: Real GDP Growth Rate (quarterly) — overall economic growth.
        - **fed_funds**: Federal Funds Rate — the Fed's benchmark interest rate.

        Use "all" to fetch all indicators at once, or specify one by name.

        These indicators provide the macro backdrop for stock analysis:
        - High CPI + rising Fed Funds = hawkish environment, bad for growth stocks.
        - Low unemployment + strong GDP = healthy economy, supports earnings growth.
        - Rising unemployment = potential recession risk, defensive positioning.

        Args:
            indicator: Indicator name ("cpi", "unemployment", "gdp", "fed_funds") or "all"
            format: Output format - "markdown" (default) or "json"
        """
        try:
            data = await fred_source.get_economic_indicators(indicator=indicator)
            if format == "json":
                return format_json(data)
            return format_economic_indicators(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"

    @mcp.tool()
    async def get_yield_curve(format: str = "markdown") -> str:
        """Get the US Treasury yield curve spread (10Y-2Y) with inversion analysis.

        The 10Y-2Y spread is the most watched recession indicator. Returns the
        current spread, inversion status, historical context, and interpretation.

        Key signals:
        - **Inverted (negative spread)**: Historically precedes recessions by 6-18 months.
          Every US recession since 1969 was preceded by inversion.
        - **Flat (near zero)**: Transitional — often precedes either inversion or steepening.
        - **Steep (> 1.5%)**: Typical of early recovery, accommodative monetary policy.

        Use this alongside other macro tools to build a complete economic picture.

        Args:
            format: Output format - "markdown" (default) or "json"
        """
        try:
            data = await fred_source.get_yield_curve()
            if format == "json":
                return format_json(data)
            return format_yield_curve(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"

    @mcp.tool()
    async def get_market_regime(format: str = "markdown") -> str:
        """Assess the current market regime (RISK-ON / CAUTIOUS / RISK-OFF).

        Analyzes multiple market signals to determine the overall environment:

        1. **S&P 500 vs 200-day MA**: Price above 200MA = bullish trend, below = bearish.
        2. **VIX (Fear Index)**: < 15 = low fear, 15-25 = normal, 25-35 = elevated, > 35 = extreme.
        3. **Market breadth**: S&P 500 recent momentum (20-day performance).

        Overall regime:
        - **RISK-ON**: S&P above 200MA + VIX < 20 — favorable for growth stocks.
        - **CAUTIOUS**: Mixed signals — favor quality, consider hedging.
        - **RISK-OFF**: S&P below 200MA + VIX elevated — favor defensive sectors, cash.

        This does NOT use FRED data (no API key needed) — it uses live market data.

        Args:
            format: Output format - "markdown" (default) or "json"
        """
        try:
            data = await _compute_market_regime(yfinance_source)
            if format == "json":
                return format_json(data)
            return format_market_regime(data)
        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"


async def _compute_market_regime(
    yfinance_source: YFinanceDataSource,
) -> dict[str, Any]:
    """Compute the current market regime from S&P 500 and VIX data.

    Uses yfinance to fetch ^GSPC (S&P 500) and ^VIX data.

    Args:
        yfinance_source: The YFinanceDataSource instance.

    Returns:
        Dict with market regime assessment.
    """
    # Fetch S&P 500 data (need 200+ days for 200MA)
    sp500_data = await yfinance_source._run_sync(
        lambda: yf.Ticker("^GSPC").history(period="1y")
    )

    # Fetch VIX data
    vix_data = await yfinance_source._run_sync(
        lambda: yf.Ticker("^VIX").history(period="3mo")
    )

    # --- S&P 500 Analysis ---
    sp500_current = None
    sp500_200ma = None
    sp500_50ma = None
    sp500_above_200ma = None
    sp500_pct_from_200ma = None
    sp500_20d_return = None

    if sp500_data is not None and not sp500_data.empty:
        sp500_current = float(sp500_data["Close"].iloc[-1])

        if len(sp500_data) >= 200:
            sp500_200ma = float(sp500_data["Close"].tail(200).mean())
        if len(sp500_data) >= 50:
            sp500_50ma = float(sp500_data["Close"].tail(50).mean())

        if sp500_current is not None and sp500_200ma is not None:
            sp500_above_200ma = sp500_current > sp500_200ma
            sp500_pct_from_200ma = round(
                ((sp500_current - sp500_200ma) / sp500_200ma) * 100, 2
            )

        # 20-day return for momentum/breadth proxy
        if len(sp500_data) >= 20:
            price_20d_ago = float(sp500_data["Close"].iloc[-20])
            sp500_20d_return = round(
                ((sp500_current - price_20d_ago) / price_20d_ago) * 100, 2
            )

    # --- VIX Analysis ---
    vix_current = None
    vix_level = "unknown"
    vix_interpretation = "VIX data unavailable."

    if vix_data is not None and not vix_data.empty:
        vix_current = round(float(vix_data["Close"].iloc[-1]), 2)

        if vix_current < 15:
            vix_level = "low"
            vix_interpretation = "Low fear — market complacency, potential for mean reversion."
        elif vix_current < 25:
            vix_level = "normal"
            vix_interpretation = "Normal volatility range — typical market conditions."
        elif vix_current < 35:
            vix_level = "elevated"
            vix_interpretation = "Elevated fear — increased uncertainty, wider price swings."
        else:
            vix_level = "extreme"
            vix_interpretation = "Extreme fear — panic conditions, often near market bottoms."

    # --- Market Regime Classification ---
    if sp500_above_200ma is None or vix_current is None:
        regime = "UNKNOWN"
        regime_description = "Insufficient data to determine market regime."
    elif sp500_above_200ma and vix_current < 20:
        regime = "RISK-ON"
        regime_description = (
            "Bullish trend (S&P above 200MA) with low volatility. "
            "Favorable environment for growth and momentum strategies."
        )
    elif not sp500_above_200ma and vix_current >= 25:
        regime = "RISK-OFF"
        regime_description = (
            "Bearish trend (S&P below 200MA) with elevated volatility. "
            "Favor defensive sectors, quality, and cash. Consider hedging."
        )
    else:
        regime = "CAUTIOUS"
        regime_description = (
            "Mixed signals — trend and volatility are not aligned. "
            "Favor quality stocks, consider position sizing, and monitor for regime change."
        )

    return {
        "regime": regime,
        "regime_description": regime_description,
        "sp500": {
            "current": sp500_current,
            "200_day_ma": round(sp500_200ma, 2) if sp500_200ma else None,
            "50_day_ma": round(sp500_50ma, 2) if sp500_50ma else None,
            "above_200ma": sp500_above_200ma,
            "pct_from_200ma": sp500_pct_from_200ma,
            "20d_return_pct": sp500_20d_return,
        },
        "vix": {
            "current": vix_current,
            "level": vix_level,
            "interpretation": vix_interpretation,
        },
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
