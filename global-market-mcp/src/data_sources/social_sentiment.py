"""Social sentiment data sources — StockTwits and Reddit public APIs.

Provides two standalone async functions (no class needed — these are
independent of the yfinance data source):

- fetch_stocktwits_sentiment(): Recent messages and sentiment ratios from StockTwits.
- fetch_reddit_sentiment(): Recent stock-related posts from Reddit.

Both use stdlib ``urllib.request`` dispatched via ``asyncio.to_thread`` to
avoid blocking the event loop without adding ``aiohttp`` as a dependency.

Graceful degradation is the #1 design goal: network errors, rate limiting,
and malformed responses are caught and returned as structured "unavailable"
dicts rather than raised as exceptions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from ..config import CacheTTL
from .cache import cached

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_REQUEST_TIMEOUT_SECONDS = 10


def _http_get_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """Synchronous HTTP GET returning parsed JSON.

    This runs in a thread via ``asyncio.to_thread`` so the event loop is
    never blocked.  All error handling is done by callers.

    Args:
        url: The URL to fetch.
        headers: Optional HTTP headers.

    Returns:
        Parsed JSON as a dict.

    Raises:
        urllib.error.URLError: On network errors.
        urllib.error.HTTPError: On HTTP error responses (4xx/5xx).
        json.JSONDecodeError: If the response body is not valid JSON.
    """
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


def _unavailable_result(ticker: str, source: str, reason: str) -> dict[str, Any]:
    """Return a standardized 'data unavailable' dict.

    This ensures the tool layer always receives a dict it can format,
    even when the external API is down.
    """
    return {
        "ticker": ticker.upper(),
        "unavailable": True,
        "source": source,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# StockTwits
# ---------------------------------------------------------------------------


@cached(ttl_seconds=CacheTTL.SOCIAL_SENTIMENT)
async def fetch_stocktwits_sentiment(
    ticker: str,
    limit: int = 15,
) -> dict[str, Any]:
    """Fetch recent StockTwits messages and sentiment summary for a ticker.

    Uses the public StockTwits API (no authentication required).
    Rate limit: ~200 requests/hour without auth.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL").
        limit: Maximum number of messages to return (default 15, max 30).

    Returns:
        Dict with keys:
        - ticker: The normalized ticker symbol.
        - sentiment_summary: {bullish_count, bearish_count, neutral_count, total}.
        - messages: List of dicts with body, created_at, sentiment, username.
        OR an "unavailable" dict if the API cannot be reached.
    """
    ticker = ticker.strip().upper()
    limit = min(max(1, limit), 30)
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"

    try:
        data = await asyncio.to_thread(_http_get_json, url, {
            "User-Agent": "FinancialAnalysisAgent/1.0",
        })
    except urllib.error.HTTPError as e:
        if e.code == 429:
            logger.warning("StockTwits rate limit hit for %s", ticker)
            return _unavailable_result(ticker, "StockTwits", "Rate limit exceeded. Try again later.")
        if e.code == 404:
            logger.info("StockTwits: ticker %s not found", ticker)
            return _unavailable_result(ticker, "StockTwits", f"Ticker '{ticker}' not found on StockTwits.")
        logger.warning("StockTwits HTTP error %d for %s: %s", e.code, ticker, e.reason)
        return _unavailable_result(ticker, "StockTwits", f"HTTP error {e.code}: {e.reason}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning("StockTwits network error for %s: %s", ticker, e)
        return _unavailable_result(ticker, "StockTwits", "Service unavailable (network error).")
    except json.JSONDecodeError:
        logger.warning("StockTwits returned invalid JSON for %s", ticker)
        return _unavailable_result(ticker, "StockTwits", "Received invalid response from StockTwits.")
    except Exception as e:
        logger.warning("StockTwits unexpected error for %s: %s", ticker, e)
        return _unavailable_result(ticker, "StockTwits", f"Unexpected error: {type(e).__name__}")

    # Parse messages
    raw_messages = data.get("messages", [])
    if not raw_messages:
        return {
            "ticker": ticker,
            "sentiment_summary": {
                "bullish_count": 0,
                "bearish_count": 0,
                "neutral_count": 0,
                "total": 0,
            },
            "messages": [],
        }

    bullish = 0
    bearish = 0
    neutral = 0
    parsed_messages: list[dict[str, Any]] = []

    for msg in raw_messages[:limit]:
        try:
            sentiment_obj = msg.get("entities", {}).get("sentiment", None)
            if sentiment_obj and isinstance(sentiment_obj, dict):
                sentiment_label = sentiment_obj.get("basic", None)
            else:
                sentiment_label = None

            if sentiment_label == "Bullish":
                bullish += 1
                display_sentiment = "Bullish"
            elif sentiment_label == "Bearish":
                bearish += 1
                display_sentiment = "Bearish"
            else:
                neutral += 1
                display_sentiment = "Neutral"

            user = msg.get("user", {})
            username = user.get("username", "unknown") if isinstance(user, dict) else "unknown"

            parsed_messages.append({
                "body": str(msg.get("body", ""))[:280],  # Truncate long messages
                "created_at": msg.get("created_at", ""),
                "sentiment": display_sentiment,
                "username": username,
            })
        except Exception:
            # Skip malformed individual messages
            continue

    return {
        "ticker": ticker,
        "sentiment_summary": {
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral,
            "total": bullish + bearish + neutral,
        },
        "messages": parsed_messages,
    }


# ---------------------------------------------------------------------------
# Reddit
# ---------------------------------------------------------------------------


@cached(ttl_seconds=CacheTTL.SOCIAL_SENTIMENT)
async def fetch_reddit_sentiment(
    ticker: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Fetch recent Reddit posts mentioning a stock ticker.

    Uses the public Reddit JSON API (no authentication required).
    A descriptive User-Agent is set to avoid 429 responses.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL").
        limit: Maximum number of posts to return (default 10, max 25).

    Returns:
        Dict with keys:
        - ticker: The normalized ticker symbol.
        - post_count: Number of posts returned.
        - posts: List of dicts with title, score, comments, subreddit, url, date.
        OR an "unavailable" dict if the API cannot be reached.
    """
    ticker = ticker.strip().upper()
    limit = min(max(1, limit), 25)

    # Search across popular finance subreddits
    subreddits = "stocks+wallstreetbets+investing+stockmarket"
    url = (
        f"https://www.reddit.com/r/{subreddits}/search.json"
        f"?q={ticker}+stock&sort=relevance&t=week&limit={limit}&restrict_sr=on"
    )

    headers = {
        "User-Agent": "FinancialAnalysisAgent/1.0 (financial analysis tool)",
        "Accept": "application/json",
    }

    try:
        data = await asyncio.to_thread(_http_get_json, url, headers)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            logger.warning("Reddit rate limit hit for %s", ticker)
            return _unavailable_result(ticker, "Reddit", "Rate limit exceeded. Try again later.")
        if e.code == 403:
            logger.warning("Reddit access denied for %s", ticker)
            return _unavailable_result(ticker, "Reddit", "Access denied by Reddit.")
        logger.warning("Reddit HTTP error %d for %s: %s", e.code, ticker, e.reason)
        return _unavailable_result(ticker, "Reddit", f"HTTP error {e.code}: {e.reason}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning("Reddit network error for %s: %s", ticker, e)
        return _unavailable_result(ticker, "Reddit", "Service unavailable (network error).")
    except json.JSONDecodeError:
        logger.warning("Reddit returned invalid JSON for %s", ticker)
        return _unavailable_result(ticker, "Reddit", "Received invalid response from Reddit.")
    except Exception as e:
        logger.warning("Reddit unexpected error for %s: %s", ticker, e)
        return _unavailable_result(ticker, "Reddit", f"Unexpected error: {type(e).__name__}")

    # Parse posts
    try:
        children = data.get("data", {}).get("children", [])
    except (AttributeError, TypeError):
        return _unavailable_result(ticker, "Reddit", "Unexpected response structure.")

    if not children:
        return {
            "ticker": ticker,
            "post_count": 0,
            "posts": [],
        }

    parsed_posts: list[dict[str, Any]] = []

    for child in children[:limit]:
        try:
            post = child.get("data", {})
            if not isinstance(post, dict):
                continue

            # Convert UTC timestamp to readable date
            created_utc = post.get("created_utc")
            if created_utc:
                try:
                    date_str = datetime.fromtimestamp(
                        float(created_utc), tz=timezone.utc
                    ).strftime("%Y-%m-%d %H:%M UTC")
                except (ValueError, TypeError, OSError):
                    date_str = "Unknown"
            else:
                date_str = "Unknown"

            parsed_posts.append({
                "title": str(post.get("title", "No title"))[:200],
                "score": int(post.get("score", 0)),
                "comments": int(post.get("num_comments", 0)),
                "subreddit": str(post.get("subreddit", "unknown")),
                "url": f"https://reddit.com{post.get('permalink', '')}",
                "date": date_str,
            })
        except Exception:
            # Skip malformed individual posts
            continue

    return {
        "ticker": ticker,
        "post_count": len(parsed_posts),
        "posts": parsed_posts,
    }
