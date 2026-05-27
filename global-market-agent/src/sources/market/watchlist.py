"""Watchlist Event Monitor -- checks tracked tickers for notable events.

Monitors tickers that have KB stock files for:
1. Significant insider purchases (> $50k)
2. Analyst upgrades/downgrades (not reiterations)
3. Upcoming earnings dates (within 14 days)

Each significant event becomes one inbox item.

Graceful degradation:
- yfinance failure per ticker -> skip that ticker, continue others
- Individual data type failure -> skip that check, continue others
- No tickers in watchlist     -> return immediately
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.knowledge_base.kb_api import KnowledgeBase
from src.knowledge_base.perception import add_to_inbox

SOURCES_DIR = Path(__file__).resolve().parents[3] / "data" / "sources"
WATCHLIST_STORE_PATH = SOURCES_DIR / "watchlist_store.json"


# ---------------------------------------------------------------------------
# Significance thresholds
# ---------------------------------------------------------------------------

_INSIDER_PURCHASE_MIN_VALUE = 50_000  # USD
_INSIDER_LOOKBACK_DAYS = 30
_ANALYST_LOOKBACK_DAYS = 7
_EARNINGS_LOOKAHEAD_DAYS = 14


# ---------------------------------------------------------------------------
# Per-ticker event checkers
# ---------------------------------------------------------------------------

def _check_insider_transactions(
    ticker_name: str,
    ticker_obj: Any,
    kb: KnowledgeBase,
    now: datetime,
) -> list[dict]:
    """Check for significant insider purchases in the last 30 days.

    Only flags insider PURCHASES above $50k (selling is usually routine).
    Returns list of event dicts.
    """
    events: list[dict] = []

    try:
        insider_data = ticker_obj.insider_transactions
    except (AttributeError, TypeError, Exception):
        return events

    if insider_data is None:
        return events

    # Handle both DataFrame and dict/list returns
    if isinstance(insider_data, pd.DataFrame):
        if insider_data.empty:
            return events
        df = insider_data
    elif isinstance(insider_data, list):
        if not insider_data:
            return events
        df = pd.DataFrame(insider_data)
    elif isinstance(insider_data, dict):
        # Some versions return a dict with a data key
        inner = insider_data.get("data") or insider_data.get("transactions")
        if isinstance(inner, list):
            df = pd.DataFrame(inner)
        else:
            return events
    else:
        return events

    if df.empty:
        return events

    cutoff = now - timedelta(days=_INSIDER_LOOKBACK_DAYS)

    for _, row in df.iterrows():
        try:
            # Detect purchase transactions
            # Common column names across yfinance versions
            text = str(row.get("Text", "") or row.get("text", "") or row.get("Transaction", "") or "")
            transaction = str(row.get("Transaction", "") or row.get("transaction", "") or "")

            is_purchase = False
            for kw in ("Purchase", "Buy", "purchase", "buy", "Acquisition"):
                if kw in text or kw in transaction:
                    is_purchase = True
                    break

            if not is_purchase:
                continue

            # Parse value
            value = row.get("Value") or row.get("value") or row.get("Amount") or 0
            try:
                value = abs(float(value))
            except (ValueError, TypeError):
                value = 0

            if value < _INSIDER_PURCHASE_MIN_VALUE:
                continue

            # Parse date
            date_val = row.get("Start Date") or row.get("startDate") or row.get("Date") or row.get("date")
            if date_val is not None:
                if isinstance(date_val, str):
                    try:
                        tx_date = datetime.fromisoformat(date_val.replace("Z", "+00:00"))
                        if tx_date.tzinfo is None:
                            tx_date = tx_date.replace(tzinfo=timezone.utc)
                        if tx_date < cutoff:
                            continue
                    except (ValueError, TypeError):
                        pass  # Can't parse date, include it anyway
                elif isinstance(date_val, pd.Timestamp):
                    if date_val.tzinfo is None:
                        date_val = date_val.tz_localize("UTC")
                    if date_val < cutoff:
                        continue

            # Extract insider name
            insider_name = str(row.get("Insider", "") or row.get("insider", "") or row.get("Name", "") or "Unknown")

            # Extract shares
            shares = row.get("Shares") or row.get("shares") or row.get("Number of Shares") or "N/A"

            date_str = str(date_val)[:10] if date_val is not None else "recent"
            value_str = f"${value:,.0f}"

            body = (
                f"## {ticker_name} Insider Purchase Alert\n\n"
                f"**Insider**: {insider_name}\n"
                f"**Transaction**: Purchase ({shares} shares, {value_str})\n"
                f"**Date**: {date_str}\n\n"
                f"This is a significant insider purchase that may signal management confidence."
            )

            events.append({
                "type": "insider_purchase",
                "ticker": ticker_name,
                "body": body,
                "title": f"{ticker_name} Insider Purchase: {insider_name} ({value_str})",
                "tier": 1,
                "tags": ["insider", "purchase", ticker_name],
            })
        except Exception:
            continue  # Skip malformed rows

    return events


def _check_analyst_actions(
    ticker_name: str,
    ticker_obj: Any,
    kb: KnowledgeBase,
    now: datetime,
) -> list[dict]:
    """Check for analyst upgrades/downgrades in the last 7 days.

    Only flags actual upgrades/downgrades, not reiterations.
    Returns list of event dicts.
    """
    events: list[dict] = []

    try:
        upgrades_data = ticker_obj.upgrades_downgrades
    except (AttributeError, TypeError, Exception):
        return events

    if upgrades_data is None:
        return events

    # Handle both DataFrame and dict/list returns
    if isinstance(upgrades_data, pd.DataFrame):
        if upgrades_data.empty:
            return events
        df = upgrades_data
    elif isinstance(upgrades_data, list):
        if not upgrades_data:
            return events
        df = pd.DataFrame(upgrades_data)
    elif isinstance(upgrades_data, dict):
        inner = upgrades_data.get("data") or upgrades_data.get("upgrades")
        if isinstance(inner, list):
            df = pd.DataFrame(inner)
        else:
            return events
    else:
        return events

    if df.empty:
        return events

    cutoff = now - timedelta(days=_ANALYST_LOOKBACK_DAYS)

    for idx_val, row in df.iterrows():
        try:
            # Parse date from index or column
            date_val = None
            if isinstance(idx_val, (pd.Timestamp, datetime)):
                date_val = idx_val
            else:
                date_raw = row.get("GradeDate") or row.get("Date") or row.get("date")
                if date_raw is not None:
                    if isinstance(date_raw, str):
                        try:
                            date_val = pd.Timestamp(date_raw)
                        except Exception:
                            pass
                    elif isinstance(date_raw, (pd.Timestamp, datetime)):
                        date_val = date_raw

            if date_val is not None:
                if hasattr(date_val, "tzinfo") and date_val.tzinfo is None:
                    date_val = pd.Timestamp(date_val).tz_localize("UTC")
                if date_val < cutoff:
                    continue

            # Get action type
            action = str(row.get("Action", "") or row.get("action", "") or "")
            action_lower = action.lower()

            # Skip reiterations — only want upgrades/downgrades/initiations
            is_significant = False
            for kw in ("upgrade", "downgrade", "initiated", "init", "up", "down"):
                if kw in action_lower:
                    is_significant = True
                    break

            # If action is empty but FromGrade/ToGrade differ, it's likely significant
            from_grade = str(row.get("FromGrade", "") or row.get("From Grade", "") or "")
            to_grade = str(row.get("ToGrade", "") or row.get("To Grade", "") or "")

            if not is_significant and from_grade and to_grade and from_grade != to_grade:
                is_significant = True

            if not is_significant:
                continue

            firm = str(row.get("Firm", "") or row.get("firm", "") or "Unknown")

            date_str = str(date_val)[:10] if date_val is not None else "recent"

            grade_info = ""
            if from_grade and to_grade:
                grade_info = f" ({from_grade} -> {to_grade})"
            elif to_grade:
                grade_info = f" (to {to_grade})"

            body = (
                f"## {ticker_name} Analyst {action}\n\n"
                f"**Firm**: {firm}\n"
                f"**Action**: {action}{grade_info}\n"
                f"**Date**: {date_str}\n\n"
                f"Analyst rating change may impact sentiment and price targets."
            )

            events.append({
                "type": "analyst_action",
                "ticker": ticker_name,
                "body": body,
                "title": f"{ticker_name} {action}: {firm}{grade_info}",
                "tier": 2,
                "tags": ["analyst", action_lower.split()[0] if action_lower else "rating", ticker_name],
            })
        except Exception:
            continue

    return events


def _check_earnings_date(
    ticker_name: str,
    ticker_obj: Any,
    kb: KnowledgeBase,
    now: datetime,
) -> list[dict]:
    """Check if earnings date is within the next 14 days.

    Returns list with at most one event dict.
    """
    events: list[dict] = []

    try:
        calendar = ticker_obj.calendar
    except (AttributeError, TypeError, Exception):
        return events

    if calendar is None:
        return events

    earnings_dates: list[Any] = []

    # calendar can be a dict or DataFrame depending on yfinance version
    if isinstance(calendar, dict):
        raw = calendar.get("Earnings Date") or calendar.get("earnings_date") or calendar.get("Earnings")
        if raw is not None:
            if isinstance(raw, list):
                earnings_dates = raw
            else:
                earnings_dates = [raw]
    elif isinstance(calendar, pd.DataFrame):
        # Some versions return a DataFrame with an "Earnings Date" row
        try:
            if "Earnings Date" in calendar.index:
                vals = calendar.loc["Earnings Date"].tolist()
                earnings_dates = vals
            elif "Earnings Date" in calendar.columns:
                vals = calendar["Earnings Date"].tolist()
                earnings_dates = vals
        except Exception:
            pass

    lookahead = now + timedelta(days=_EARNINGS_LOOKAHEAD_DAYS)

    for ed in earnings_dates:
        try:
            if isinstance(ed, str):
                dt = pd.Timestamp(ed)
            elif isinstance(ed, (pd.Timestamp, datetime)):
                dt = pd.Timestamp(ed)
            elif isinstance(ed, (int, float)):
                dt = pd.Timestamp(ed, unit="s")
            else:
                continue

            if dt.tzinfo is None:
                dt = dt.tz_localize("UTC")

            now_ts = pd.Timestamp(now)
            if now_ts.tzinfo is None:
                now_ts = now_ts.tz_localize("UTC")

            if now_ts <= dt <= pd.Timestamp(lookahead):
                days_until = (dt - now_ts).days
                date_str = dt.strftime("%Y-%m-%d")

                body = (
                    f"## {ticker_name} Upcoming Earnings\n\n"
                    f"**Earnings Date**: {date_str}\n"
                    f"**Days Until**: {days_until}\n\n"
                    f"Earnings report approaching. Monitor for pre-earnings positioning, "
                    f"options activity, and analyst estimate revisions."
                )

                events.append({
                    "type": "earnings_upcoming",
                    "ticker": ticker_name,
                    "body": body,
                    "title": f"{ticker_name} Earnings in {days_until} days ({date_str})",
                    "tier": 2,
                    "tags": ["earnings", "upcoming", ticker_name],
                })
                break  # Only report once per ticker
        except Exception:
            continue

    return events


# ---------------------------------------------------------------------------
# JSON store helpers
# ---------------------------------------------------------------------------

def _watchlist_event_key(ticker: str, event_type: str, title: str) -> str:
    """Generate a stable hash key for a watchlist event."""
    raw = f"{ticker}|{event_type}|{title}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _load_watchlist_store() -> dict[str, dict]:
    """Load the watchlist JSON store. Key = hash of (ticker, type, title)."""
    if WATCHLIST_STORE_PATH.exists():
        return json.loads(WATCHLIST_STORE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_watchlist_store(store: dict[str, dict]) -> None:
    """Save the watchlist JSON store to disk."""
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    WATCHLIST_STORE_PATH.write_text(
        json.dumps(store, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def check_watchlist_events(kb: KnowledgeBase | None = None) -> dict:
    """Check tracked tickers for notable events and create inbox items.

    Returns summary dict with events found per ticker.
    """
    if kb is None:
        kb = KnowledgeBase()

    # Load JSON store for caching (enables retrain replay)
    watchlist_store = _load_watchlist_store()

    watched = kb.list_stocks()
    if not watched:
        print("[watchlist] No watched tickers in KB, skipping.")
        return {"status": "ok", "total_events": 0, "tickers_checked": 0, "events_by_ticker": {}}

    import yfinance as yf

    now = datetime.now(timezone.utc)
    total_events = 0
    errors: list[str] = []
    events_by_ticker: dict[str, list[str]] = {}

    print(f"[watchlist] Checking {len(watched)} tickers for events...")

    for ticker_name in watched:
        try:
            ticker_obj = yf.Ticker(ticker_name)
            ticker_events: list[dict] = []

            # Check insider transactions
            try:
                insider_events = _check_insider_transactions(ticker_name, ticker_obj, kb, now)
                ticker_events.extend(insider_events)
            except Exception as e:
                print(f"[watchlist] {ticker_name} insider check failed: {e}")

            # Check analyst actions
            try:
                analyst_events = _check_analyst_actions(ticker_name, ticker_obj, kb, now)
                ticker_events.extend(analyst_events)
            except Exception as e:
                print(f"[watchlist] {ticker_name} analyst check failed: {e}")

            # Check earnings date
            try:
                earnings_events = _check_earnings_date(ticker_name, ticker_obj, kb, now)
                ticker_events.extend(earnings_events)
            except Exception as e:
                print(f"[watchlist] {ticker_name} earnings check failed: {e}")

            # Create inbox items for significant events
            if ticker_events:
                today_str = now.strftime("%Y-%m-%d")
                event_types: list[str] = []
                for evt in ticker_events:
                    add_to_inbox(
                        content=evt["body"],
                        source="watchlist_monitor",
                        tier=evt["tier"],
                        content_type="event",
                        title=evt["title"],
                        ticker=ticker_name,
                        tags=evt["tags"],
                        published_date=today_str,
                        kb=kb,
                    )

                    # Cache to JSON store for retrain replay
                    store_key = _watchlist_event_key(ticker_name, evt["type"], evt["title"])
                    watchlist_store[store_key] = {
                        "type": evt["type"],
                        "ticker": ticker_name,
                        "title": evt["title"],
                        "body": evt["body"],
                        "tier": evt["tier"],
                        "tags": evt["tags"],
                        "pub_date": today_str,
                        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }

                    event_types.append(evt["type"])
                    total_events += 1

                events_by_ticker[ticker_name] = event_types
                print(f"[watchlist] {ticker_name}: {len(ticker_events)} events ({', '.join(event_types)})")
            else:
                print(f"[watchlist] {ticker_name}: no significant events")

        except Exception as e:
            print(f"[watchlist] Error checking {ticker_name}: {e}")
            errors.append(f"{ticker_name}: {e}")

    # Record freshness
    summary = f"checked {len(watched)} tickers, {total_events} events"
    kb.set_last_updated("watchlist_monitor", new_count=total_events, summary=summary)

    # Save watchlist store to disk
    _save_watchlist_store(watchlist_store)

    if total_events > 0:
        print(f"[watchlist] Total: {total_events} event items created")
    else:
        print("[watchlist] No significant events found")

    return {
        "status": "ok" if not errors else "partial",
        "total_events": total_events,
        "tickers_checked": len(watched),
        "events_by_ticker": events_by_ticker,
        "errors": errors,
    }
