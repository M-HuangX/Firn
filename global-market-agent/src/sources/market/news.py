"""Market News Fetcher -- fetches news headlines via yfinance.

Fetches market-wide news (via SPY) and stock-specific news for watched
tickers (those with directories in KB stocks/).  Each article becomes one
inbox item so the filter agent can decide individually.

Graceful degradation:
- yfinance failure for SPY  -> skip market news, try stock-specific
- yfinance failure per ticker -> skip that ticker, continue others
- All fail                  -> return summary, no inbox items
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.knowledge_base.kb_api import KnowledgeBase
from src.knowledge_base.perception import add_to_inbox

SOURCES_DIR = Path(__file__).resolve().parents[3] / "data" / "sources"
NEWS_STORE_PATH = SOURCES_DIR / "news_store.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _article_uuid(article: dict) -> str:
    """Extract a unique identifier for dedup.

    Prefers the yfinance uuid field; falls back to a hash of the title.
    """
    uid = article.get("uuid") or article.get("id")
    if uid:
        return str(uid)
    title = article.get("title", "")
    return hashlib.sha256(title.encode()).hexdigest()[:16]


def _get_news_list(ticker_obj: Any) -> list[dict]:
    """Safely extract the news list from a yfinance Ticker object.

    yfinance versions differ in how `.news` is structured:
    - Some return a plain list of dicts
    - Some return a dict with a 'news' key containing the list
    - Some may raise or return None

    Returns a (possibly empty) list of article dicts.
    """
    try:
        raw = ticker_obj.news
    except (AttributeError, TypeError, Exception):
        return []

    if raw is None:
        return []

    # If it's already a list, use it directly
    if isinstance(raw, list):
        return raw

    # Some versions return {"news": [...], ...}
    if isinstance(raw, dict):
        inner = raw.get("news")
        if isinstance(inner, list):
            return inner
        return []

    return []


def _format_article_body(article: dict) -> str:
    """Format a single news article as markdown body."""
    title = article.get("title", "(no title)")
    publisher = article.get("publisher", "Unknown")
    link = article.get("link", "")

    # Handle different date field names
    pub_time = article.get("providerPublishTime") or article.get("publishedDate")
    if pub_time and isinstance(pub_time, (int, float)):
        date_str = datetime.fromtimestamp(pub_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    elif pub_time:
        date_str = str(pub_time)
    else:
        date_str = "unknown"

    related = article.get("relatedTickers", [])
    if not isinstance(related, list):
        related = []

    lines = [
        f"**{title}**",
        "",
        f"Publisher: {publisher}",
        f"Date: {date_str}",
    ]
    if link:
        lines.append(f"Link: {link}")
    if related:
        lines.append(f"\nRelated tickers: {', '.join(related)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON store helpers
# ---------------------------------------------------------------------------

def _load_news_store() -> dict[str, dict]:
    """Load the news JSON store. Key = article UUID."""
    if NEWS_STORE_PATH.exists():
        return json.loads(NEWS_STORE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_news_store(store: dict[str, dict]) -> None:
    """Save the news JSON store to disk."""
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    NEWS_STORE_PATH.write_text(
        json.dumps(store, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def fetch_market_news(kb: KnowledgeBase | None = None, max_articles: int = 10) -> dict:
    """Fetch market-wide news and create inbox items.

    Also fetches news for any tickers tracked in the KB watchlist
    (i.e. tickers with directories under stocks/).

    Returns summary dict with counts.
    """
    if kb is None:
        kb = KnowledgeBase()

    # Load JSON store for caching (enables retrain replay)
    news_store = _load_news_store()

    # Load previously seen article UUIDs for dedup
    last_updated = kb.get_last_updated()
    prev_news = last_updated.get("market_news_yfinance")
    seen_uuids: set[str] = set()
    if isinstance(prev_news, dict):
        raw_seen = prev_news.get("seen_uuids", [])
        if isinstance(raw_seen, list):
            seen_uuids = set(raw_seen)

    import yfinance as yf

    total_created = 0
    errors: list[str] = []
    new_uuids: list[str] = []

    # --- Step 1: Market-wide news via SPY ---
    market_count = 0
    try:
        print("[news] Fetching market-wide news via SPY...")
        spy = yf.Ticker("SPY")
        articles = _get_news_list(spy)
        if articles:
            for article in articles[:max_articles]:
                uid = _article_uuid(article)
                if uid in seen_uuids:
                    continue

                title = article.get("title") or ""
                if not title.strip():
                    continue  # skip empty/broken articles
                body = _format_article_body(article)

                pub_time = article.get("providerPublishTime") or article.get("publishedDate")
                pub_date = None
                if pub_time and isinstance(pub_time, (int, float)):
                    pub_date = datetime.fromtimestamp(pub_time, tz=timezone.utc).strftime("%Y-%m-%d")
                elif pub_time and isinstance(pub_time, str):
                    pub_date = pub_time[:10]  # "YYYY-MM-DD..." → "YYYY-MM-DD"

                add_to_inbox(
                    content=body,
                    source="market_news_yfinance",
                    tier=3,
                    content_type="news",
                    title=title,
                    tags=["market-news"],
                    published_date=pub_date,
                    kb=kb,
                )

                # Cache to JSON store for retrain replay
                publisher = article.get("publisher", "Unknown")
                news_store[uid] = {
                    "title": title,
                    "publisher": publisher,
                    "body": body,
                    "source_type": "market_news_yfinance",
                    "ticker": None,
                    "pub_date": pub_date,
                    "tags": ["market-news"],
                    "tier": 3,
                    "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }

                seen_uuids.add(uid)
                new_uuids.append(uid)
                market_count += 1
                total_created += 1

            print(f"[news] SPY: {market_count} new articles (of {len(articles)} total)")
        else:
            print("[news] SPY: no news articles returned")
    except Exception as e:
        print(f"[news] Error fetching SPY news: {e}")
        errors.append(f"SPY: {e}")

    # --- Step 2: Watchlist ticker news ---
    watched_tickers = kb.list_stocks()
    ticker_counts: dict[str, int] = {}

    if watched_tickers:
        print(f"[news] Checking news for {len(watched_tickers)} watched tickers...")
        for ticker_name in watched_tickers:
            try:
                t = yf.Ticker(ticker_name)
                articles = _get_news_list(t)
                if not articles:
                    continue

                count = 0
                for article in articles[:max_articles]:
                    uid = _article_uuid(article)
                    if uid in seen_uuids:
                        continue

                    title = article.get("title") or ""
                    if not title.strip():
                        continue  # skip empty/broken articles
                    body = _format_article_body(article)

                    pub_time = article.get("providerPublishTime") or article.get("publishedDate")
                    pub_date = None
                    if pub_time and isinstance(pub_time, (int, float)):
                        pub_date = datetime.fromtimestamp(pub_time, tz=timezone.utc).strftime("%Y-%m-%d")

                    add_to_inbox(
                        content=body,
                        source="stock_news_yfinance",
                        tier=3,
                        content_type="news",
                        title=title,
                        ticker=ticker_name,
                        tags=["stock-news", ticker_name],
                        published_date=pub_date,
                        kb=kb,
                    )

                    # Cache to JSON store for retrain replay
                    publisher = article.get("publisher", "Unknown")
                    news_store[uid] = {
                        "title": title,
                        "publisher": publisher,
                        "body": body,
                        "source_type": "stock_news_yfinance",
                        "ticker": ticker_name,
                        "pub_date": pub_date,
                        "tags": ["stock-news", ticker_name],
                        "tier": 3,
                        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }

                    seen_uuids.add(uid)
                    new_uuids.append(uid)
                    count += 1
                    total_created += 1

                if count > 0:
                    ticker_counts[ticker_name] = count
                    print(f"[news] {ticker_name}: {count} new articles")
            except Exception as e:
                print(f"[news] Error fetching news for {ticker_name}: {e}")
                errors.append(f"{ticker_name}: {e}")
    else:
        print("[news] No watched tickers in KB")

    # --- Record freshness ---
    summary_parts = [f"{market_count} market"]
    if ticker_counts:
        stock_total = sum(ticker_counts.values())
        summary_parts.append(f"{stock_total} stock-specific")
    summary = f"{total_created} articles ({', '.join(summary_parts)})"

    # Store seen UUIDs for dedup (keep last 500 to avoid unbounded growth)
    all_seen = list(seen_uuids)[-500:]
    kb.set_last_updated("market_news_yfinance", new_count=total_created, summary=summary)
    # Persist seen UUIDs in the last_updated entry
    lu = kb.get_last_updated()
    entry = lu.get("market_news_yfinance", {})
    if isinstance(entry, dict):
        entry["seen_uuids"] = all_seen
        lu["market_news_yfinance"] = entry
        (kb.data_root / "meta" / "last_updated.json").write_text(
            json.dumps(lu, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # Save news store to disk
    _save_news_store(news_store)

    if total_created > 0:
        print(f"[news] Total: {total_created} new inbox items created")
    else:
        print("[news] No new articles found")

    return {
        "status": "ok" if total_created > 0 or not errors else "error",
        "total_created": total_created,
        "market_count": market_count,
        "ticker_counts": ticker_counts,
        "errors": errors,
    }
