"""Macro Pulse — daily macro snapshot generator.

Fetches market index data (S&P 500, NASDAQ, VIX) via yfinance and
economic indicators (treasury yields, CPI, unemployment, GDP, Fed Funds)
via FRED.  Formats a structured markdown digest and writes it to the
inbox as a Tier-1 "required reading" item.

Graceful degradation:
- FRED_API_KEY not set  -> skip FRED data, still produce market snapshot
- yfinance failure      -> skip market data, still try FRED
- Both fail             -> return error summary, no inbox item
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.knowledge_base.kb_api import KnowledgeBase
from src.knowledge_base.perception import add_to_inbox

_FRED_CACHE_DIR = (
    Path(__file__).resolve().parents[3] / "data" / "sources" / "fred_cache"
)


# ---------------------------------------------------------------------------
# FRED series IDs (mirrored from MCP's fred_source.py)
# ---------------------------------------------------------------------------

_SERIES_TREASURY_2Y = "GS2"
_SERIES_TREASURY_10Y = "GS10"
_SERIES_TREASURY_30Y = "GS30"
_SERIES_CPI = "CPIAUCSL"
_SERIES_UNEMPLOYMENT = "UNRATE"
_SERIES_GDP_GROWTH = "A191RL1Q225SBEA"
_SERIES_FED_FUNDS = "FEDFUNDS"
_SERIES_YIELD_SPREAD = "T10Y2Y"


# ---------------------------------------------------------------------------
# Market regime logic
# ---------------------------------------------------------------------------

def compute_market_regime(
    sp500_price: float | None,
    sp500_200ma: float | None,
    vix_level: float | None,
) -> tuple[str, str]:
    """Classify the current market regime.

    Returns (regime, description) tuple.

    Rules (from task spec + MCP macro tools):
    - S&P 500 > 200MA by >2%  -> RISK-ON  (unless VIX overrides)
    - S&P 500 within +/-2% of 200MA -> CAUTIOUS
    - S&P 500 < 200MA by >2%  -> RISK-OFF
    - VIX > 25 -> override to at least CAUTIOUS
    - VIX > 35 -> override to RISK-OFF
    """
    if sp500_price is None or sp500_200ma is None:
        if vix_level is not None and vix_level > 35:
            return "RISK-OFF", "VIX extreme — insufficient price data for full assessment."
        if vix_level is not None and vix_level > 25:
            return "CAUTIOUS", "VIX elevated — insufficient price data for full assessment."
        return "UNKNOWN", "Insufficient data to determine market regime."

    pct_from_200ma = ((sp500_price - sp500_200ma) / sp500_200ma) * 100

    # Base regime from S&P vs 200MA
    if pct_from_200ma > 2:
        regime = "RISK-ON"
        desc = (
            f"Bullish trend — S&P 500 {pct_from_200ma:+.1f}% above 200MA. "
            "Favorable for growth and momentum strategies."
        )
    elif pct_from_200ma < -2:
        regime = "RISK-OFF"
        desc = (
            f"Bearish trend — S&P 500 {pct_from_200ma:+.1f}% below 200MA. "
            "Favor defensive sectors, quality, and cash."
        )
    else:
        regime = "CAUTIOUS"
        desc = (
            f"S&P 500 near 200MA ({pct_from_200ma:+.1f}%). "
            "Mixed signals — favor quality, monitor for regime change."
        )

    # VIX overrides
    if vix_level is not None:
        if vix_level > 35:
            regime = "RISK-OFF"
            desc += f" VIX extreme ({vix_level:.1f}) — overriding to RISK-OFF."
        elif vix_level > 25 and regime == "RISK-ON":
            regime = "CAUTIOUS"
            desc += f" VIX elevated ({vix_level:.1f}) — downgrading from RISK-ON."

    return regime, desc


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def _fetch_market_data() -> dict[str, Any]:
    """Fetch S&P 500, NASDAQ, VIX data via yfinance.

    Returns a dict with keys: sp500, nasdaq, vix, regime, errors.
    All sub-dicts are empty if fetching fails.
    """
    import yfinance as yf

    result: dict[str, Any] = {
        "sp500": {},
        "nasdaq": {},
        "vix": {},
        "regime": "UNKNOWN",
        "regime_description": "",
        "errors": [],
    }

    # --- S&P 500 ---
    try:
        sp500_hist = yf.Ticker("^GSPC").history(period="1y")
        if sp500_hist is not None and not sp500_hist.empty:
            price = float(sp500_hist["Close"].iloc[-1])
            prev_close = float(sp500_hist["Close"].iloc[-2]) if len(sp500_hist) >= 2 else price
            change_pct = ((price - prev_close) / prev_close) * 100

            ma200 = None
            if len(sp500_hist) >= 200:
                ma200 = float(sp500_hist["Close"].tail(200).mean())

            pct_from_200ma = None
            if ma200 is not None:
                pct_from_200ma = ((price - ma200) / ma200) * 100

            result["sp500"] = {
                "price": round(price, 2),
                "prev_close": round(prev_close, 2),
                "change_pct": round(change_pct, 2),
                "ma200": round(ma200, 2) if ma200 is not None else None,
                "pct_from_200ma": round(pct_from_200ma, 2) if pct_from_200ma is not None else None,
            }
        else:
            result["errors"].append("S&P 500: empty data returned")
    except Exception as e:
        result["errors"].append(f"S&P 500: {e}")

    # --- NASDAQ ---
    try:
        nasdaq_hist = yf.Ticker("^IXIC").history(period="5d")
        if nasdaq_hist is not None and not nasdaq_hist.empty:
            price = float(nasdaq_hist["Close"].iloc[-1])
            prev_close = float(nasdaq_hist["Close"].iloc[-2]) if len(nasdaq_hist) >= 2 else price
            change_pct = ((price - prev_close) / prev_close) * 100
            result["nasdaq"] = {
                "price": round(price, 2),
                "change_pct": round(change_pct, 2),
            }
        else:
            result["errors"].append("NASDAQ: empty data returned")
    except Exception as e:
        result["errors"].append(f"NASDAQ: {e}")

    # --- VIX ---
    try:
        vix_hist = yf.Ticker("^VIX").history(period="5d")
        if vix_hist is not None and not vix_hist.empty:
            level = float(vix_hist["Close"].iloc[-1])
            if level < 15:
                interpretation = "Low fear — market complacency"
            elif level < 20:
                interpretation = "Below average — calm conditions"
            elif level < 25:
                interpretation = "Normal volatility range"
            elif level < 35:
                interpretation = "Elevated fear — increased uncertainty"
            else:
                interpretation = "Extreme fear — panic conditions"
            result["vix"] = {
                "level": round(level, 2),
                "interpretation": interpretation,
            }
        else:
            result["errors"].append("VIX: empty data returned")
    except Exception as e:
        result["errors"].append(f"VIX: {e}")

    # --- Compute regime ---
    sp500_price = result["sp500"].get("price")
    sp500_200ma = result["sp500"].get("ma200")
    vix_level = result["vix"].get("level")
    regime, regime_desc = compute_market_regime(sp500_price, sp500_200ma, vix_level)
    result["regime"] = regime
    result["regime_description"] = regime_desc

    return result


def _fetch_historical_market_data(as_of_date: str) -> dict[str, Any]:
    """Fetch historical S&P 500, NASDAQ, VIX data via yfinance for a past date.

    Uses explicit date ranges to reconstruct the market state that would have
    been available on *as_of_date*.

    Returns a dict with the same shape as ``_fetch_market_data()``.
    """
    import yfinance as yf

    target = datetime.strptime(as_of_date, "%Y-%m-%d")
    result: dict[str, Any] = {
        "sp500": {},
        "nasdaq": {},
        "vix": {},
        "regime": "UNKNOWN",
        "regime_description": "",
        "errors": [],
    }

    # end is exclusive in yfinance
    end_str = (target + timedelta(days=1)).strftime("%Y-%m-%d")

    # --- S&P 500 (need ~1 year for 200MA) ---
    try:
        start_sp = (target - timedelta(days=370)).strftime("%Y-%m-%d")
        sp500_hist = yf.Ticker("^GSPC").history(start=start_sp, end=end_str)
        if sp500_hist is not None and not sp500_hist.empty:
            price = float(sp500_hist["Close"].iloc[-1])
            prev_close = float(sp500_hist["Close"].iloc[-2]) if len(sp500_hist) >= 2 else price
            change_pct = ((price - prev_close) / prev_close) * 100

            ma200 = None
            if len(sp500_hist) >= 200:
                ma200 = float(sp500_hist["Close"].tail(200).mean())

            pct_from_200ma = None
            if ma200 is not None:
                pct_from_200ma = ((price - ma200) / ma200) * 100

            result["sp500"] = {
                "price": round(price, 2),
                "prev_close": round(prev_close, 2),
                "change_pct": round(change_pct, 2),
                "ma200": round(ma200, 2) if ma200 is not None else None,
                "pct_from_200ma": round(pct_from_200ma, 2) if pct_from_200ma is not None else None,
            }
        else:
            result["errors"].append("S&P 500: empty historical data")
    except Exception as e:
        result["errors"].append(f"S&P 500: {e}")

    # --- NASDAQ ---
    try:
        start_nq = (target - timedelta(days=60)).strftime("%Y-%m-%d")
        nasdaq_hist = yf.Ticker("^IXIC").history(start=start_nq, end=end_str)
        if nasdaq_hist is not None and not nasdaq_hist.empty:
            price = float(nasdaq_hist["Close"].iloc[-1])
            prev_close = float(nasdaq_hist["Close"].iloc[-2]) if len(nasdaq_hist) >= 2 else price
            change_pct = ((price - prev_close) / prev_close) * 100
            result["nasdaq"] = {
                "price": round(price, 2),
                "change_pct": round(change_pct, 2),
            }
        else:
            result["errors"].append("NASDAQ: empty historical data")
    except Exception as e:
        result["errors"].append(f"NASDAQ: {e}")

    # --- VIX ---
    try:
        start_vix = (target - timedelta(days=60)).strftime("%Y-%m-%d")
        vix_hist = yf.Ticker("^VIX").history(start=start_vix, end=end_str)
        if vix_hist is not None and not vix_hist.empty:
            level = float(vix_hist["Close"].iloc[-1])
            if level < 15:
                interpretation = "Low fear — market complacency"
            elif level < 20:
                interpretation = "Below average — calm conditions"
            elif level < 25:
                interpretation = "Normal volatility range"
            elif level < 35:
                interpretation = "Elevated fear — increased uncertainty"
            else:
                interpretation = "Extreme fear — panic conditions"
            result["vix"] = {
                "level": round(level, 2),
                "interpretation": interpretation,
            }
        else:
            result["errors"].append("VIX: empty historical data")
    except Exception as e:
        result["errors"].append(f"VIX: {e}")

    # --- Compute regime ---
    sp500_price = result["sp500"].get("price")
    sp500_200ma = result["sp500"].get("ma200")
    vix_level = result["vix"].get("level")
    regime, regime_desc = compute_market_regime(sp500_price, sp500_200ma, vix_level)
    result["regime"] = regime
    result["regime_description"] = regime_desc

    return result


def _load_fred_cache(date_str: str) -> dict[str, Any] | None:
    """Load cached FRED data for a given date, or None if not cached."""
    cache_file = _FRED_CACHE_DIR / f"{date_str}.json"
    if cache_file.is_file():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _save_fred_cache(date_str: str, data: dict[str, Any]) -> None:
    """Save FRED data to disk cache."""
    _FRED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _FRED_CACHE_DIR / f"{date_str}.json"
    cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_fred_data(
    cache_date: str | None = None,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Fetch economic data from FRED with disk caching.

    Returns a dict with keys: yields, spread, indicators, errors.
    Returns None if FRED_API_KEY is not set.

    Parameters
    ----------
    cache_date : str | None
        Date string (YYYY-MM-DD) for cache lookup/storage.
        Defaults to today (UTC).
    as_of_date : str | None
        If set, fetches historical FRED data by passing
        ``observation_end=as_of_date`` to ``fred.get_series()``.
        This returns only observations on or before that date.
    """
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        return None  # type: ignore[return-value]

    date_key = cache_date or as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cached = _load_fred_cache(date_key)
    if cached is not None:
        print(f"[macro-pulse] FRED cache hit for {date_key}")
        return cached

    from fredapi import Fred

    fred = Fred(api_key=api_key)
    result: dict[str, Any] = {
        "yields": {},
        "spread": {},
        "indicators": {},
        "errors": [],
    }

    # Build extra kwargs for historical queries
    fred_kwargs: dict[str, Any] = {}
    if as_of_date:
        fred_kwargs["observation_end"] = as_of_date

    # --- Treasury Yields ---
    for name, series_id in [
        ("10Y", _SERIES_TREASURY_10Y),
        ("2Y", _SERIES_TREASURY_2Y),
        ("30Y", _SERIES_TREASURY_30Y),
    ]:
        try:
            data = fred.get_series(series_id, **fred_kwargs)
            if data is not None and len(data) > 0:
                latest = data.dropna().iloc[-1]
                result["yields"][name] = round(float(latest), 2)
        except Exception as e:
            result["errors"].append(f"Treasury {name}: {e}")

    # --- Yield Curve Spread ---
    try:
        spread_data = fred.get_series(_SERIES_YIELD_SPREAD, **fred_kwargs)
        if spread_data is not None and len(spread_data) > 0:
            latest_spread = float(spread_data.dropna().iloc[-1])
            if latest_spread < -0.1:
                status = "inverted"
            elif latest_spread > 0.1:
                status = "normal"
            else:
                status = "flat"
            result["spread"] = {
                "value_pct": round(latest_spread, 2),
                "value_bp": round(latest_spread * 100, 0),
                "status": status,
            }
    except Exception as e:
        result["errors"].append(f"Yield spread: {e}")

    # --- Economic Indicators ---
    indicator_map = {
        "fed_funds": (_SERIES_FED_FUNDS, "Fed Funds Rate"),
        "cpi": (_SERIES_CPI, "CPI"),
        "unemployment": (_SERIES_UNEMPLOYMENT, "Unemployment Rate"),
        "gdp": (_SERIES_GDP_GROWTH, "GDP Growth"),
    }
    for key, (series_id, label) in indicator_map.items():
        try:
            data = fred.get_series(series_id, **fred_kwargs)
            if data is not None and len(data) > 0:
                series_clean = data.dropna()
                latest_val = float(series_clean.iloc[-1])
                latest_date = series_clean.index[-1]
                date_str = latest_date.strftime("%Y-%m-%d") if hasattr(latest_date, "strftime") else str(latest_date)
                entry: dict[str, Any] = {
                    "value": round(latest_val, 2),
                    "as_of": date_str,
                    "label": label,
                }
                # CPI series (CPIAUCSL) returns index values; compute YoY %
                if key == "cpi" and len(series_clean) >= 13:
                    val_12m_ago = float(series_clean.iloc[-13])
                    if val_12m_ago > 0:
                        yoy = (latest_val - val_12m_ago) / val_12m_ago * 100
                        entry["value"] = round(yoy, 1)
                        entry["index_value"] = round(latest_val, 2)
                result["indicators"][key] = entry
        except Exception as e:
            result["errors"].append(f"{label}: {e}")

    # Save to disk cache (only if we got meaningful data)
    if result.get("yields") or result.get("indicators"):
        _save_fred_cache(date_key, result)

    return result


# ---------------------------------------------------------------------------
# Markdown formatter
# ---------------------------------------------------------------------------

def format_macro_pulse(
    date_str: str,
    market: dict[str, Any],
    fred: dict[str, Any] | None,
) -> str:
    """Format the macro pulse as a structured markdown body."""
    lines: list[str] = []

    lines.append(f"# Macro Pulse -- {date_str}")
    lines.append("")

    # --- Market Regime ---
    lines.append(f"## Market Regime: {market.get('regime', 'UNKNOWN')}")
    sp = market.get("sp500", {})
    if sp:
        above_below = "above" if (sp.get("pct_from_200ma") or 0) >= 0 else "below"
        ma_info = ""
        if sp.get("pct_from_200ma") is not None:
            ma_info = f", {abs(sp['pct_from_200ma']):.1f}% {above_below} 200MA"
        lines.append(f"- S&P 500: {sp.get('price', 'N/A')} ({sp.get('change_pct', 0):+.2f}%){ma_info}")
    else:
        lines.append("- S&P 500: data unavailable")

    nq = market.get("nasdaq", {})
    if nq:
        lines.append(f"- NASDAQ: {nq.get('price', 'N/A')} ({nq.get('change_pct', 0):+.2f}%)")
    else:
        lines.append("- NASDAQ: data unavailable")

    vx = market.get("vix", {})
    if vx:
        lines.append(f"- VIX: {vx.get('level', 'N/A')} ({vx.get('interpretation', '')})")
    else:
        lines.append("- VIX: data unavailable")

    if market.get("regime_description"):
        lines.append(f"\n_{market['regime_description']}_")
    lines.append("")

    # --- Interest Rates (FRED) ---
    if fred is not None:
        yields = fred.get("yields", {})
        spread = fred.get("spread", {})
        indicators = fred.get("indicators", {})

        if yields or spread:
            lines.append("## Interest Rates")
            if "10Y" in yields:
                lines.append(f"- 10Y Treasury: {yields['10Y']}%")
            if "2Y" in yields:
                lines.append(f"- 2Y Treasury: {yields['2Y']}%")
            if spread:
                lines.append(
                    f"- 10Y-2Y Spread: {spread.get('value_bp', 'N/A')}bp "
                    f"({spread.get('status', 'unknown')})"
                )
            if "30Y" in yields:
                lines.append(f"- 30Y Treasury: {yields['30Y']}%")
            fed_funds = indicators.get("fed_funds")
            if fed_funds:
                lines.append(f"- Fed Funds: {fed_funds['value']}%")
            lines.append("")

        # --- Economic Indicators ---
        remaining = {k: v for k, v in indicators.items() if k != "fed_funds"}
        if remaining:
            lines.append("## Economic Indicators (latest readings)")
            for key in ["cpi", "unemployment", "gdp"]:
                ind = remaining.get(key)
                if ind:
                    unit = "% YoY" if key == "cpi" else "%"
                    lines.append(f"- {ind['label']}: {ind['value']}{unit} (as of {ind['as_of']})")
            lines.append("")

        # FRED errors
        if fred.get("errors"):
            lines.append("## FRED Data Gaps")
            for err in fred["errors"]:
                lines.append(f"- {err}")
            lines.append("")
    else:
        lines.append("## Interest Rates")
        lines.append("_FRED data unavailable (FRED_API_KEY not configured)_")
        lines.append("")

    # --- Market Data Errors ---
    if market.get("errors"):
        lines.append("## Market Data Gaps")
        for err in market["errors"]:
            lines.append(f"- {err}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_macro_pulse(kb: KnowledgeBase | None = None) -> dict:
    """Generate a macro pulse snapshot and add it to the inbox.

    Returns summary dict with what was fetched.
    Graceful degradation: if FRED unavailable, still generates yfinance snapshot.
    """
    if kb is None:
        kb = KnowledgeBase()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # --- Deduplication: skip if already generated today ---
    last_updated = kb.get_last_updated()
    prev = last_updated.get("macro_pulse")
    if isinstance(prev, dict):
        last_new = prev.get("last_new_data")
        if last_new and last_new.startswith(today):
            print(f"[macro-pulse] Already generated today ({today}), skipping.")
            return {"status": "skipped", "reason": "already_generated_today"}

    print(f"[macro-pulse] Generating macro pulse for {today}...")

    # --- Fetch market data (yfinance) ---
    market_data: dict[str, Any] = {}
    market_ok = False
    try:
        print("[macro-pulse] Fetching market data (S&P 500, NASDAQ, VIX)...")
        market_data = _fetch_market_data()
        # Consider market data OK if we got at least S&P price
        market_ok = bool(market_data.get("sp500", {}).get("price"))
        if market_ok:
            print(f"[macro-pulse] Market regime: {market_data.get('regime', 'UNKNOWN')}")
        else:
            print("[macro-pulse] Warning: market data incomplete")
    except Exception as e:
        print(f"[macro-pulse] Error fetching market data: {e}")
        market_data = {"sp500": {}, "nasdaq": {}, "vix": {}, "regime": "UNKNOWN",
                       "regime_description": "", "errors": [str(e)]}

    # --- Fetch FRED data ---
    fred_data: dict[str, Any] | None = None
    fred_ok = False
    try:
        fred_key_set = bool(os.environ.get("FRED_API_KEY"))
        if fred_key_set:
            print("[macro-pulse] Fetching FRED data (yields, indicators)...")
            fred_data = _fetch_fred_data()
            if fred_data is not None:
                fred_ok = bool(fred_data.get("yields") or fred_data.get("indicators"))
                if fred_ok:
                    print(f"[macro-pulse] FRED: {len(fred_data.get('yields', {}))} yields, "
                          f"{len(fred_data.get('indicators', {}))} indicators")
                else:
                    print("[macro-pulse] Warning: FRED data incomplete")
        else:
            print("[macro-pulse] FRED_API_KEY not set, skipping FRED data")
    except Exception as e:
        print(f"[macro-pulse] Error fetching FRED data: {e}")
        fred_data = None

    # --- If both failed, don't create inbox item ---
    if not market_ok and not fred_ok:
        print("[macro-pulse] Both market and FRED data unavailable. No inbox item created.")
        kb.set_last_updated("macro_pulse", new_count=0, summary="fetch failed — no data")
        return {"status": "error", "reason": "no_data_available", "market_ok": False, "fred_ok": False}

    # --- Format markdown body ---
    body = format_macro_pulse(today, market_data, fred_data)

    # --- Add to inbox ---
    title = f"Macro Pulse {today}"
    slug = add_to_inbox(
        content=body,
        source="macro_pulse",
        tier=1,
        content_type="market_data",
        title=title,
        tags=["macro", "daily"],
        published_date=today,
        kb=kb,
    )
    print(f"[macro-pulse] Inbox item created: {slug}")

    # --- Record freshness ---
    summary_parts = []
    if market_ok:
        summary_parts.append(f"regime={market_data.get('regime', '?')}")
    if fred_ok:
        summary_parts.append("FRED OK")
    else:
        summary_parts.append("no FRED")
    summary = f"daily snapshot ({', '.join(summary_parts)})"

    kb.set_last_updated("macro_pulse", new_count=1, summary=summary)

    return {
        "status": "ok",
        "slug": slug,
        "date": today,
        "regime": market_data.get("regime", "UNKNOWN"),
        "market_ok": market_ok,
        "fred_ok": fred_ok,
        "market_errors": market_data.get("errors", []),
        "fred_errors": fred_data.get("errors", []) if fred_data else [],
    }


def generate_historical_macro_pulse(as_of_date: str, kb: KnowledgeBase) -> dict:
    """Generate a macro pulse for a past date and add it to inbox.

    Uses yfinance historical data for market indices and FRED historical
    observations for economic indicators.  No deduplication check is
    performed (unlike ``generate_macro_pulse``), because historical pulses
    are generated once per retrain epoch.

    Parameters
    ----------
    as_of_date : str
        Target date in "YYYY-MM-DD" format.
    kb : KnowledgeBase
        Knowledge base instance for inbox insertion.

    Returns
    -------
    dict
        Summary dict with ``slug`` on success, or error info on failure.
    """
    print(f"[macro-pulse] Generating historical macro pulse for {as_of_date}...")

    # --- Fetch historical market data (yfinance) ---
    market_data: dict[str, Any] = {}
    market_ok = False
    try:
        print(f"[macro-pulse] Fetching historical market data for {as_of_date}...")
        market_data = _fetch_historical_market_data(as_of_date)
        market_ok = bool(market_data.get("sp500", {}).get("price"))
        if market_ok:
            print(f"[macro-pulse] Historical regime: {market_data.get('regime', 'UNKNOWN')}")
        else:
            print("[macro-pulse] Warning: historical market data incomplete")
    except Exception as e:
        print(f"[macro-pulse] Error fetching historical market data: {e}")
        market_data = {"sp500": {}, "nasdaq": {}, "vix": {}, "regime": "UNKNOWN",
                       "regime_description": "", "errors": [str(e)]}

    # --- Fetch historical FRED data ---
    fred_data: dict[str, Any] | None = None
    fred_ok = False
    try:
        fred_key_set = bool(os.environ.get("FRED_API_KEY"))
        if fred_key_set:
            print(f"[macro-pulse] Fetching FRED data as of {as_of_date}...")
            fred_data = _fetch_fred_data(cache_date=as_of_date, as_of_date=as_of_date)
            if fred_data is not None:
                fred_ok = bool(fred_data.get("yields") or fred_data.get("indicators"))
                if fred_ok:
                    print(f"[macro-pulse] FRED: {len(fred_data.get('yields', {}))} yields, "
                          f"{len(fred_data.get('indicators', {}))} indicators")
                else:
                    print("[macro-pulse] Warning: historical FRED data incomplete")
        else:
            print("[macro-pulse] FRED_API_KEY not set, skipping FRED data")
    except Exception as e:
        print(f"[macro-pulse] Error fetching historical FRED data: {e}")
        fred_data = None

    # --- If both failed, don't create inbox item ---
    if not market_ok and not fred_ok:
        print(f"[macro-pulse] Both historical data sources unavailable for {as_of_date}.")
        return {"status": "error", "reason": "no_data_available",
                "market_ok": False, "fred_ok": False}

    # --- Format markdown body ---
    body = format_macro_pulse(as_of_date, market_data, fred_data)

    # --- Add to inbox ---
    title = f"Macro Pulse {as_of_date}"
    slug = add_to_inbox(
        content=body,
        source="macro_pulse",
        tier=1,
        content_type="market_data",
        title=title,
        tags=["macro", "daily"],
        published_date=as_of_date,
        kb=kb,
    )
    print(f"[macro-pulse] Historical inbox item created: {slug}")

    return {
        "status": "ok",
        "slug": slug,
        "date": as_of_date,
        "regime": market_data.get("regime", "UNKNOWN"),
        "market_ok": market_ok,
        "fred_ok": fred_ok,
        "market_errors": market_data.get("errors", []),
        "fred_errors": fred_data.get("errors", []) if fred_data else [],
    }
