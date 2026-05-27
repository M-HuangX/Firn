"""Divergence tracker -- monitors agent vs user view disagreements.

Part of the Two-Mind architecture: tracks where the agent's objective
analysis disagrees with the user's stated views, and records outcomes
for learning.
"""

from __future__ import annotations

import logging
import re
import time

from src.knowledge_base.kb_api import KnowledgeBase

logger = logging.getLogger(__name__)

# Mapping from 5-tier ratings to sentiment direction
_BULLISH_RATINGS = {"Buy", "Overweight"}
_BEARISH_RATINGS = {"Sell", "Underweight"}
_NEUTRAL_RATINGS = {"Hold"}


def _rating_to_sentiment(rating: str) -> str:
    """Map a 5-tier rating to a simple sentiment direction."""
    if rating in _BULLISH_RATINGS:
        return "bullish"
    if rating in _BEARISH_RATINGS:
        return "bearish"
    return "neutral"


def _get_kb(kb: KnowledgeBase | None) -> KnowledgeBase:
    """Return the provided KB or create a default one with structure ensured."""
    if kb is None:
        kb = KnowledgeBase()
    kb.ensure_structure()
    return kb


def _count_existing_divergences(text: str) -> int:
    """Count the number of divergence entries by counting ### # headers."""
    return len(re.findall(r"^### #\d+", text, re.MULTILINE))


def check_and_record_divergence(
    ticker: str,
    agent_rating: str,
    agent_thesis: str,
    kb: KnowledgeBase | None = None,
) -> dict | None:
    """Check if the agent's analysis diverges from user's view for a ticker.

    If divergence detected, records it in divergences.md.

    Args:
        ticker: Stock symbol
        agent_rating: Agent's recommendation (Buy/Hold/Sell etc.)
        agent_thesis: Brief summary of agent's thesis

    Returns:
        dict describing the divergence if found, None if views align or no user view exists
    """
    kb = _get_kb(kb)
    ticker = ticker.upper()

    # Import here to avoid circular imports
    from src.knowledge_base.user_input import get_user_view_for_ticker

    user_view = get_user_view_for_ticker(ticker, kb)
    if user_view is None:
        return None

    user_sentiment = user_view.get("sentiment", "neutral")
    user_view_text = user_view.get("view", "")
    agent_sentiment = _rating_to_sentiment(agent_rating)

    # Determine if there's a divergence
    is_divergent = False

    if agent_sentiment == "bullish" and user_sentiment == "bearish":
        is_divergent = True
    elif agent_sentiment == "bearish" and user_sentiment == "bullish":
        is_divergent = True
    elif agent_sentiment == "neutral" and user_sentiment in ("bullish", "bearish"):
        # Minor divergence: agent is neutral but user has a strong view
        is_divergent = True

    if not is_divergent:
        return None

    # Record the divergence
    date_str = time.strftime("%Y-%m-%d")
    existing = kb.read_divergences() or "# Divergences\n"

    # Determine entry number
    entry_num = _count_existing_divergences(existing) + 1

    entry = (
        f"\n---\n"
        f"### #{entry_num} {ticker} ({date_str})\n"
        f"**Status**: Active\n"
        f"| Dimension | Agent View | User View |\n"
        f"|-----------|-----------|----------|\n"
        f"| Rating | {agent_rating} | {user_sentiment} |\n"
        f"| Thesis | {agent_thesis} | {user_view_text} |\n"
        f"**Follow-up**: Track until next analysis or price target reached\n"
        f"---\n"
    )

    updated = existing.rstrip("\n") + "\n" + entry
    kb.write_divergences(updated)

    # Audit log (best-effort)
    try:
        kb.append_log(
            f"Divergence #{entry_num} recorded: {ticker} "
            f"(agent={agent_rating}, user={user_sentiment})"
        )
    except Exception:
        pass

    logger.info(
        "divergence: recorded #%d for %s (agent=%s, user=%s)",
        entry_num, ticker, agent_rating, user_sentiment,
    )

    return {
        "entry_num": entry_num,
        "ticker": ticker,
        "agent_view": agent_rating,
        "agent_sentiment": agent_sentiment,
        "user_view": user_view_text,
        "user_sentiment": user_sentiment,
        "date": date_str,
        "status": "Active",
    }


def resolve_divergence(
    ticker: str,
    resolution: str,
    winner: str = "pending",
    kb: KnowledgeBase | None = None,
) -> bool:
    """Mark a divergence as resolved.

    Args:
        ticker: Stock symbol
        resolution: What happened (e.g. "Stock dropped 15%, agent was right")
        winner: "agent" | "user" | "both_wrong" | "pending"

    Returns:
        True if divergence was found and resolved
    """
    kb = _get_kb(kb)
    ticker = ticker.upper()

    existing = kb.read_divergences()
    if not existing:
        return False

    # Find the active divergence for this ticker
    # Pattern: ### #N TICKER (date)\n**Status**: Active
    pattern = re.compile(
        rf"(### #\d+ {re.escape(ticker)} \(\d{{4}}-\d{{2}}-\d{{2}}\)\n)"
        rf"\*\*Status\*\*: Active",
    )

    match = pattern.search(existing)
    if not match:
        return False

    # Replace "Active" with "Resolved" and add resolution details
    date_str = time.strftime("%Y-%m-%d")
    old_status = f"{match.group(1)}**Status**: Active"
    new_status = (
        f"{match.group(1)}**Status**: Resolved\n"
        f"**Resolved**: {date_str}\n"
        f"**Winner**: {winner}\n"
        f"**Resolution**: {resolution}"
    )

    updated = existing.replace(old_status, new_status, 1)
    kb.write_divergences(updated)

    # Audit log (best-effort)
    try:
        kb.append_log(f"Divergence resolved: {ticker} (winner={winner})")
    except Exception:
        pass

    logger.info("divergence: resolved for %s (winner=%s)", ticker, winner)
    return True


def get_active_divergences(
    kb: KnowledgeBase | None = None,
) -> list[dict]:
    """Get all active (unresolved) divergences.

    Returns list of dicts with: ticker, agent_view, user_view, date, status
    """
    if kb is None:
        kb = KnowledgeBase()

    existing = kb.read_divergences()
    if not existing:
        return []

    results: list[dict] = []

    # Split by "---" and process sections with Active status
    sections = re.split(r"^---$", existing, flags=re.MULTILINE)

    for section in sections:
        if "**Status**: Active" not in section:
            continue

        # Extract header: ### #N TICKER (DATE)
        header_match = re.search(
            r"### #(\d+) (\S+) \((\d{4}-\d{2}-\d{2})\)", section
        )
        if not header_match:
            continue

        entry_num = int(header_match.group(1))
        ticker = header_match.group(2)
        date = header_match.group(3)

        # Extract agent and user views from the table
        agent_view = ""
        user_view = ""
        rating_row = re.search(
            r"\| Rating \| (.+?) \| (.+?) \|", section
        )
        if rating_row:
            agent_view = rating_row.group(1).strip()
            user_view = rating_row.group(2).strip()

        results.append({
            "entry_num": entry_num,
            "ticker": ticker,
            "agent_view": agent_view,
            "user_view": user_view,
            "date": date,
            "status": "Active",
        })

    return results
