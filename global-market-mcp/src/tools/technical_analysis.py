"""MCP tool registrations for technical analysis — indicators, signals, patterns.

Registers two MVP tools:
- get_technical_indicators: Computes ~25 technical indicators from OHLCV data using the ta library.
- get_price_analysis: Price statistics, moving average analysis, and trend assessment.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import pandas as pd
import ta
import ta.momentum
import ta.trend
import ta.volatility
import ta.volume
from mcp.server.fastmcp import FastMCP

from ..data_sources.exceptions import DataSourceError
from ..data_sources.validation import validate_ticker_lenient
from ..data_sources.yfinance_source import YFinanceDataSource
from ..formatting.json_fmt import format_json
from ..formatting.markdown import format_price_analysis, format_technical_indicators

logger = logging.getLogger(__name__)


def _safe_float(value: Any) -> float | None:
    """Convert a value to float, returning None for NaN/Inf/missing."""
    if value is None:
        return None
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 4)
    except (ValueError, TypeError):
        return None


def _compute_indicators(df: pd.DataFrame, indicators: str) -> dict[str, dict[str, float | None]]:
    """Compute technical indicators from OHLCV DataFrame.

    Args:
        df: DataFrame with Open, High, Low, Close, Volume columns.
        indicators: Which group to compute — "standard", "trend", "momentum",
                    "volatility", or "volume".

    Returns:
        Dict of category -> indicator_name -> latest value.
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    result: dict[str, dict[str, float | None]] = {}

    if indicators in ("standard", "trend"):
        sma_20 = ta.trend.sma_indicator(close, window=20)
        sma_50 = ta.trend.sma_indicator(close, window=50)
        sma_200 = ta.trend.sma_indicator(close, window=200)
        ema_12 = ta.trend.ema_indicator(close, window=12)
        ema_26 = ta.trend.ema_indicator(close, window=26)
        macd_obj = ta.trend.MACD(close)
        adx_values = ta.trend.adx(high, low, close)

        result["trend"] = {
            "SMA_20": _safe_float(sma_20.iloc[-1]),
            "SMA_50": _safe_float(sma_50.iloc[-1]),
            "SMA_200": _safe_float(sma_200.iloc[-1]),
            "EMA_12": _safe_float(ema_12.iloc[-1]),
            "EMA_26": _safe_float(ema_26.iloc[-1]),
            "MACD_Line": _safe_float(macd_obj.macd().iloc[-1]),
            "MACD_Signal": _safe_float(macd_obj.macd_signal().iloc[-1]),
            "MACD_Histogram": _safe_float(macd_obj.macd_diff().iloc[-1]),
            "ADX_14": _safe_float(adx_values.iloc[-1]),
        }

    if indicators in ("standard", "momentum"):
        rsi_14 = ta.momentum.rsi(close)
        stoch = ta.momentum.StochasticOscillator(high, low, close)
        williams_r = ta.momentum.williams_r(high, low, close)
        cci_20 = ta.trend.cci(high, low, close)
        roc_12 = ta.momentum.roc(close, window=12)

        result["momentum"] = {
            "RSI_14": _safe_float(rsi_14.iloc[-1]),
            "Stochastic_K": _safe_float(stoch.stoch().iloc[-1]),
            "Stochastic_D": _safe_float(stoch.stoch_signal().iloc[-1]),
            "Williams_R": _safe_float(williams_r.iloc[-1]),
            "CCI_20": _safe_float(cci_20.iloc[-1]),
            "ROC_12": _safe_float(roc_12.iloc[-1]),
        }

    if indicators in ("standard", "volatility"):
        bb = ta.volatility.BollingerBands(close)
        atr_14 = ta.volatility.average_true_range(high, low, close)

        result["volatility"] = {
            "BB_Upper": _safe_float(bb.bollinger_hband().iloc[-1]),
            "BB_Middle": _safe_float(bb.bollinger_mavg().iloc[-1]),
            "BB_Lower": _safe_float(bb.bollinger_lband().iloc[-1]),
            "BB_PctB": _safe_float(bb.bollinger_pband().iloc[-1]),
            "ATR_14": _safe_float(atr_14.iloc[-1]),
        }

    if indicators in ("standard", "volume"):
        obv = ta.volume.on_balance_volume(close, volume)
        cmf_20 = ta.volume.chaikin_money_flow(high, low, close, volume)
        volume_sma_20 = volume.rolling(window=20).mean()

        result["volume"] = {
            "OBV": _safe_float(obv.iloc[-1]),
            "CMF_20": _safe_float(cmf_20.iloc[-1]),
            "Volume_SMA_20": _safe_float(volume_sma_20.iloc[-1]),
        }

    return result


def register_technical_analysis_tools(mcp: FastMCP, data_source: YFinanceDataSource) -> None:
    """Register technical analysis tools with the MCP server.

    Args:
        mcp: The FastMCP server instance.
        data_source: The YFinanceDataSource instance for fetching market data.
    """

    @mcp.tool()
    async def get_technical_indicators(
        ticker: str,
        period: str = "1y",
        indicators: str = "standard",
        format: str = "markdown",
    ) -> str:
        """Compute technical indicators for a stock from OHLCV data.

        Returns ~25 technical indicators grouped by category: trend (SMA, EMA,
        MACD, ADX), momentum (RSI, Stochastic, Williams %R, CCI, ROC),
        volatility (Bollinger Bands, ATR), and volume (OBV, CMF). Also includes
        the current price for context.

        Use 'indicators' to request a specific category or 'standard' for all.
        Price data is fetched internally — no need to call get_historical_prices first.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "MSFT").
            period: Price data period — "3mo", "6mo", "1y", or "2y". Default "1y".
            indicators: Indicator group — "standard" (all), "trend", "momentum",
                        "volatility", or "volume". Default "standard".
            format: Output format — "markdown" or "json". Default "markdown".

        Returns:
            Formatted string with technical indicator values grouped by category.
        """
        try:
            ticker = await validate_ticker_lenient(ticker)

            # Validate parameters
            valid_periods = ("3mo", "6mo", "1y", "2y")
            if period not in valid_periods:
                return f"Error: Invalid period '{period}'. Valid periods: {', '.join(valid_periods)}"

            valid_indicators = ("standard", "trend", "momentum", "volatility", "volume")
            if indicators not in valid_indicators:
                return (
                    f"Error: Invalid indicators group '{indicators}'. "
                    f"Valid groups: {', '.join(valid_indicators)}"
                )

            # Get raw OHLCV data from data source
            tech_data = await data_source.get_technical_data(ticker, period)
            ohlcv_records = tech_data["ohlcv"]

            if not ohlcv_records:
                return f"Error: No OHLCV data available for '{ticker}' (period={period})."

            # Convert back to DataFrame for ta library computation
            df = pd.DataFrame(ohlcv_records)
            # Ensure correct column types
            for col in ("Open", "High", "Low", "Close"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")

            if len(df) < 30:
                return (
                    f"Error: Insufficient data for '{ticker}' — "
                    f"only {len(df)} data points (need at least 30 for meaningful indicators)."
                )

            # Compute indicators
            computed = _compute_indicators(df, indicators)

            # Get current price for context
            current_price = _safe_float(df["Close"].iloc[-1])

            # Spread indicator categories at top level for the formatter
            result_data: dict[str, Any] = {
                "_ticker": ticker,
                "period": period,
                "indicators_group": indicators,
                "current_price": current_price,
                "data_points": len(df),
            }
            result_data.update(computed)

            if format == "json":
                return format_json(result_data)
            return format_technical_indicators(result_data)

        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"

    @mcp.tool()
    async def get_price_analysis(
        ticker: str,
        period: str = "6mo",
        format: str = "markdown",
    ) -> str:
        """Analyze price action: statistics, moving average positions, trend direction.

        Returns price statistics (current price, period high/low, change %),
        moving average analysis (price vs SMA 20/50/200, MA alignment,
        golden/death cross status), and trend assessment (short/medium/long-term).

        Useful for understanding price context before examining technical indicators.

        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "MSFT").
            period: Analysis period — "1mo", "3mo", "6mo", or "1y". Default "6mo".
            format: Output format — "markdown" or "json". Default "markdown".

        Returns:
            Formatted string with price statistics, moving average analysis,
            and trend assessment.
        """
        try:
            ticker = await validate_ticker_lenient(ticker)

            valid_periods = ("1mo", "3mo", "6mo", "1y")
            if period not in valid_periods:
                return f"Error: Invalid period '{period}'. Valid periods: {', '.join(valid_periods)}"

            data = await data_source.get_price_analysis(ticker, period)

            if format == "json":
                return format_json(data)
            return format_price_analysis(data)

        except DataSourceError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"
