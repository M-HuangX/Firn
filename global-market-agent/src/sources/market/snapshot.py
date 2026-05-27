"""Market Snapshot — provides price context for digest sessions.

Fetches current prices and change metrics for benchmark tickers and tracked
portfolio tickers. Output is a compact markdown table delivered as an inbox
item so the digest agent can read it alongside other articles.

Also provides historical snapshot support for retrain mode via
``build_historical_market_snapshot()``, which reconstructs price context
for a past date using yfinance historical data.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
_WATCHLIST_PATH = _CONFIG_DIR / "digest_watchlist.yaml"
_SNAPSHOT_CACHE_DIR = (
    Path(__file__).resolve().parents[3] / "data" / "sources" / "market_snapshots"
)


def load_watchlist() -> dict[str, list[str]]:
    """Load the benchmark watchlist from config/digest_watchlist.yaml.

    Returns a dict of {category_label: [tickers]}.
    """
    if not _WATCHLIST_PATH.exists():
        logger.warning("Watchlist config not found: %s", _WATCHLIST_PATH)
        return {}

    with open(_WATCHLIST_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    categories = data.get("categories", {})
    result: dict[str, list[str]] = {}
    for _key, cat_data in categories.items():
        label = cat_data.get("label", _key)
        tickers = cat_data.get("tickers", [])
        if tickers:
            result[label] = [str(t) for t in tickers]
    return result


def fetch_snapshot(tickers: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch price data for a list of tickers via yfinance.

    Returns a dict of {ticker: {price, change_1d, change_1w, change_1m, week52_pos}}.
    Errors for individual tickers are logged and skipped.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed")
        return {}

    results: dict[str, dict[str, Any]] = {}

    for ticker in tickers:
        try:
            data = _fetch_single(yf, ticker)
            if data:
                results[ticker] = data
        except Exception:
            logger.debug("Failed to fetch %s", ticker, exc_info=True)

    return results


def _fetch_single(yf: Any, ticker: str) -> dict[str, Any] | None:
    """Fetch price data for a single ticker."""
    t = yf.Ticker(ticker)
    info = t.info

    if not info or not info.get("shortName"):
        return None

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")

    if not price:
        return None

    # 1-day change
    change_1d = None
    if prev_close and prev_close > 0:
        change_1d = (price - prev_close) / prev_close

    # 52-week high/low position
    high_52 = info.get("fiftyTwoWeekHigh")
    low_52 = info.get("fiftyTwoWeekLow")
    week52_pos = None
    if high_52 and low_52 and high_52 > low_52:
        week52_pos = (price - low_52) / (high_52 - low_52)

    # 1-week and 1-month changes from history
    change_1w = None
    change_1m = None
    try:
        hist = t.history(period="1mo", interval="1d")
        if hist is not None and len(hist) >= 2:
            closes = hist["Close"]
            if len(closes) >= 5:
                price_1w = closes.iloc[-5] if len(closes) >= 5 else closes.iloc[0]
                change_1w = (price - price_1w) / price_1w
            price_1m = closes.iloc[0]
            change_1m = (price - price_1m) / price_1m
    except Exception:
        pass

    return {
        "price": price,
        "currency": info.get("currency", "USD"),
        "change_1d": change_1d,
        "change_1w": change_1w,
        "change_1m": change_1m,
        "week52_pos": week52_pos,
        "short_name": info.get("shortName", ticker),
    }


def build_market_snapshot(
    tracked_tickers: list[str] | None = None,
) -> str:
    """Build a complete market snapshot markdown section.

    Parameters
    ----------
    tracked_tickers : list[str] | None
        Additional tickers from the portfolio (kb.list_stocks()).
        De-duplicated against the benchmark watchlist.

    Returns
    -------
    str
        Markdown table ready for injection into digest prompt.
        Returns empty string if no data could be fetched.
    """
    watchlist = load_watchlist()

    # Collect all benchmark tickers (preserving order)
    benchmark_tickers: list[str] = []
    ticker_to_category: dict[str, str] = {}
    for label, tickers in watchlist.items():
        for t in tickers:
            if t not in ticker_to_category:
                benchmark_tickers.append(t)
                ticker_to_category[t] = label

    # De-duplicate tracked tickers against benchmarks
    tracked = tracked_tickers or []
    portfolio_only: list[str] = [
        t for t in tracked if t not in ticker_to_category
    ]

    # Fetch all at once
    all_tickers = benchmark_tickers + portfolio_only
    if not all_tickers:
        return ""

    logger.info("Fetching market snapshot for %d tickers...", len(all_tickers))
    data = fetch_snapshot(all_tickers)

    if not data:
        logger.warning("Market snapshot: no data fetched")
        return ""

    # Build markdown
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    lines.append(f"### Market Snapshot ({now})\n")
    lines.append("| Category | Ticker | Price | 1D | 1W | 1M | 52W Pos |")
    lines.append("|----------|--------|------:|---:|---:|---:|--------:|")

    for ticker in benchmark_tickers:
        if ticker not in data:
            continue
        d = data[ticker]
        cat = ticker_to_category[ticker]
        lines.append(_format_row(cat, ticker, d))

    # Portfolio section (compact, single line per ticker)
    if portfolio_only:
        portfolio_with_data = [t for t in portfolio_only if t in data]
        if portfolio_with_data:
            lines.append("")
            parts = []
            for t in portfolio_with_data:
                d = data[t]
                p = f"${d['price']:.2f}" if d["price"] < 10000 else f"${d['price']:,.0f}"
                chg = _fmt_pct(d.get("change_1d"))
                parts.append(f"{t}({p},{chg})")
            lines.append(f"**Tracked portfolio**: {', '.join(parts)}")

    lines.append("")
    return "\n".join(lines)


def _format_row(category: str, ticker: str, d: dict) -> str:
    """Format a single ticker row for the snapshot table."""
    price = d["price"]
    currency = d.get("currency", "USD")

    # Format price
    if currency == "USD":
        p_str = f"${price:.2f}" if price < 10000 else f"${price:,.0f}"
    else:
        p_str = f"{price:.2f} {currency}"

    chg_1d = _fmt_pct(d.get("change_1d"))
    chg_1w = _fmt_pct(d.get("change_1w"))
    chg_1m = _fmt_pct(d.get("change_1m"))
    w52 = _fmt_pct(d.get("week52_pos")) if d.get("week52_pos") is not None else "—"

    return f"| {category} | {ticker} | {p_str} | {chg_1d} | {chg_1w} | {chg_1m} | {w52} |"


def _fmt_pct(val: float | None) -> str:
    """Format a float as a percentage string."""
    if val is None:
        return "—"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1%}"


# ---------------------------------------------------------------------------
# Historical snapshot support (retrain mode)
# ---------------------------------------------------------------------------


def _fetch_historical_single(
    yf: Any, ticker: str, as_of_date: str,
) -> dict[str, Any] | None:
    """Fetch historical price data for a single ticker as of a specific date.

    Uses yfinance ``history()`` with explicit date range to reconstruct the
    price context that would have been available on *as_of_date*.

    Parameters
    ----------
    yf : module
        The ``yfinance`` module.
    ticker : str
        Ticker symbol (e.g. "AAPL").
    as_of_date : str
        Target date in "YYYY-MM-DD" format.

    Returns
    -------
    dict or None
        Same format as ``_fetch_single()`` output, or None on failure.
    """
    target = datetime.strptime(as_of_date, "%Y-%m-%d")

    # Fetch ~40 trading days ending at as_of_date
    # (covers 1-month lookback + buffer for weekends/holidays)
    start = (target - timedelta(days=60)).strftime("%Y-%m-%d")
    end = (target + timedelta(days=1)).strftime("%Y-%m-%d")  # end is exclusive

    t = yf.Ticker(ticker)
    hist = t.history(start=start, end=end, interval="1d")

    if hist is None or hist.empty:
        return None

    closes = hist["Close"]
    if closes.empty:
        return None

    price = float(closes.iloc[-1])

    # 1-day change
    change_1d = None
    if len(closes) >= 2:
        prev = float(closes.iloc[-2])
        if prev > 0:
            change_1d = (price - prev) / prev

    # 1-week change (~5 trading days)
    change_1w = None
    if len(closes) >= 5:
        price_1w = float(closes.iloc[-5])
        if price_1w > 0:
            change_1w = (price - price_1w) / price_1w

    # 1-month change (~20 trading days)
    change_1m = None
    if len(closes) >= 20:
        price_1m = float(closes.iloc[-20])
        if price_1m > 0:
            change_1m = (price - price_1m) / price_1m

    # 52-week position: need ~1 year of history
    week52_pos = None
    try:
        start_52w = (target - timedelta(days=370)).strftime("%Y-%m-%d")
        hist_52w = t.history(start=start_52w, end=end, interval="1d")
        if hist_52w is not None and len(hist_52w) >= 20:
            all_closes = hist_52w["Close"]
            high_52 = float(all_closes.max())
            low_52 = float(all_closes.min())
            if high_52 > low_52:
                week52_pos = (price - low_52) / (high_52 - low_52)
    except Exception:
        pass

    return {
        "price": price,
        "currency": "USD",
        "change_1d": change_1d,
        "change_1w": change_1w,
        "change_1m": change_1m,
        "week52_pos": week52_pos,
        "short_name": ticker,
    }


def build_historical_market_snapshot(
    as_of_date: str,
    tracked_tickers: list[str] | None = None,
) -> str:
    """Build a market snapshot as if it were *as_of_date*.

    Uses yfinance historical data to reconstruct price context for a past
    date.  The output format matches ``build_market_snapshot()`` so callers
    can substitute seamlessly.

    Parameters
    ----------
    as_of_date : str
        Target date in "YYYY-MM-DD" format.
    tracked_tickers : list[str] | None
        Additional portfolio tickers.

    Returns
    -------
    str
        Markdown table with historical prices, or empty string on failure.
    """
    # Check disk cache first
    cached = _load_snapshot_cache(as_of_date)
    if cached is not None:
        logger.info("Historical snapshot cache hit for %s (%d chars)", as_of_date, len(cached))
        return cached

    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed")
        return ""

    watchlist = load_watchlist()

    # Collect all benchmark tickers (preserving order)
    benchmark_tickers: list[str] = []
    ticker_to_category: dict[str, str] = {}
    for label, tickers in watchlist.items():
        for t in tickers:
            if t not in ticker_to_category:
                benchmark_tickers.append(t)
                ticker_to_category[t] = label

    # De-duplicate tracked tickers against benchmarks
    tracked = tracked_tickers or []
    portfolio_only: list[str] = [
        t for t in tracked if t not in ticker_to_category
    ]

    all_tickers = benchmark_tickers + portfolio_only
    if not all_tickers:
        return ""

    logger.info(
        "Fetching historical market snapshot for %d tickers (as_of=%s)...",
        len(all_tickers), as_of_date,
    )

    # Fetch historical data for each ticker
    data: dict[str, dict[str, Any]] = {}
    for ticker in all_tickers:
        try:
            result = _fetch_historical_single(yf, ticker, as_of_date)
            if result:
                data[ticker] = result
        except Exception:
            logger.debug("Failed to fetch historical %s", ticker, exc_info=True)

    if not data:
        logger.warning("Historical market snapshot: no data fetched")
        return ""

    # Build markdown (same format as build_market_snapshot)
    lines: list[str] = []
    lines.append(f"### Market Snapshot (as of {as_of_date})\n")
    lines.append("| Category | Ticker | Price | 1D | 1W | 1M | 52W Pos |")
    lines.append("|----------|--------|------:|---:|---:|---:|--------:|")

    for ticker in benchmark_tickers:
        if ticker not in data:
            continue
        d = data[ticker]
        cat = ticker_to_category[ticker]
        lines.append(_format_row(cat, ticker, d))

    # Portfolio section
    if portfolio_only:
        portfolio_with_data = [t for t in portfolio_only if t in data]
        if portfolio_with_data:
            lines.append("")
            parts = []
            for t in portfolio_with_data:
                d = data[t]
                p = f"${d['price']:.2f}" if d["price"] < 10000 else f"${d['price']:,.0f}"
                chg = _fmt_pct(d.get("change_1d"))
                parts.append(f"{t}({p},{chg})")
            lines.append(f"**Tracked portfolio**: {', '.join(parts)}")

    lines.append("")
    snapshot = "\n".join(lines)

    # Save to disk cache
    _save_snapshot_cache(as_of_date, snapshot)

    return snapshot


def _load_snapshot_cache(as_of_date: str) -> str | None:
    """Load a cached historical snapshot from disk, or None if not cached."""
    cache_file = _SNAPSHOT_CACHE_DIR / f"{as_of_date}.md"
    if cache_file.is_file():
        return cache_file.read_text(encoding="utf-8")
    return None


def _save_snapshot_cache(as_of_date: str, snapshot: str) -> None:
    """Save a historical snapshot to disk cache."""
    _SNAPSHOT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _SNAPSHOT_CACHE_DIR / f"{as_of_date}.md"
    cache_file.write_text(snapshot, encoding="utf-8")
    logger.info("Historical snapshot cached: %s (%d chars)", cache_file.name, len(snapshot))


# ---------------------------------------------------------------------------
# Inbox item generators (parallel to macro_pulse pattern)
# ---------------------------------------------------------------------------


def generate_market_snapshot_item(kb: "KnowledgeBase | None" = None) -> dict:
    """Generate a market snapshot and add it to the inbox as a regular item.

    Deduplicates by date — skips if already generated today.
    Returns summary dict with ``slug`` on success.
    """
    from src.knowledge_base.kb_api import KnowledgeBase
    from src.knowledge_base.perception import add_to_inbox

    if kb is None:
        kb = KnowledgeBase()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Dedup: skip if already generated today
    last_updated = kb.get_last_updated()
    prev = last_updated.get("market_snapshot")
    if isinstance(prev, dict):
        last_new = prev.get("last_new_data")
        if last_new and last_new.startswith(today):
            print(f"[market-snapshot] Already generated today ({today}), skipping.")
            return {"status": "skipped", "reason": "already_generated_today"}

    print(f"[market-snapshot] Generating snapshot for {today}...")

    body = build_market_snapshot(tracked_tickers=kb.list_stocks())
    if not body:
        print("[market-snapshot] No data fetched, skipping.")
        kb.set_last_updated("market_snapshot", new_count=0, summary="fetch failed — no data")
        return {"status": "error", "reason": "no_data_available"}

    title = f"Market Snapshot {today}"
    slug = add_to_inbox(
        content=body,
        source="market_snapshot",
        tier=1,
        content_type="market_data",
        title=title,
        tags=["market", "snapshot"],
        published_date=today,
        kb=kb,
    )
    print(f"[market-snapshot] Inbox item created: {slug}")

    kb.set_last_updated("market_snapshot", new_count=1, summary="daily snapshot")

    return {"status": "ok", "slug": slug, "date": today}


def generate_historical_market_snapshot_item(
    as_of_date: str, kb: "KnowledgeBase",
) -> dict:
    """Generate a historical market snapshot and add it to the inbox.

    No deduplication — intended for one-per-retrain-epoch usage.
    """
    from src.knowledge_base.perception import add_to_inbox

    print(f"[market-snapshot] Generating historical snapshot for {as_of_date}...")

    body = build_historical_market_snapshot(
        as_of_date=as_of_date, tracked_tickers=kb.list_stocks(),
    )
    if not body:
        print(f"[market-snapshot] No historical data for {as_of_date}, skipping.")
        return {"status": "error", "reason": "no_data_available"}

    title = f"Market Snapshot {as_of_date}"
    slug = add_to_inbox(
        content=body,
        source="market_snapshot",
        tier=1,
        content_type="market_data",
        title=title,
        tags=["market", "snapshot"],
        published_date=as_of_date,
        kb=kb,
    )
    print(f"[market-snapshot] Historical inbox item created: {slug}")

    return {"status": "ok", "slug": slug, "date": as_of_date}
