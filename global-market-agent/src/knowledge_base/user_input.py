"""User input handler -- processes user-forwarded content and opinions.

Implements the Two-Mind architecture's user_context layer:
- User opinions -> user_context/user_views.md
- User-forwarded articles -> user_context/forwarded/ with agent assessment
- Source trust rules applied (Tier 4-5 content never enters notebook)
"""

from __future__ import annotations

import logging
import re
import time

from src.knowledge_base.kb_api import KnowledgeBase

logger = logging.getLogger(__name__)

# Source tier descriptions used in agent assessment headers
_TIER_DESCRIPTIONS: dict[int, str] = {
    1: "Tier 1 (objective facts). Data can be trusted directly.",
    2: "Tier 2 (professional analysis). High trust; note institutional bias.",
    3: "Tier 3 (mixed source). Facts should be verified against primary sources. Opinions are editorial.",
    4: "Tier 4 (social/subjective). Low trust. Never enters notebook.",
    5: "Tier 5 (user intuition). Respect but verify independently.",
}


def _slugify(text: str, max_len: int = 30) -> str:
    """Create a filesystem-safe slug from text."""
    # Take first max_len chars, lowercase, replace non-alphanum with hyphens
    slug = text[:max_len].lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "untitled"


def _get_kb(kb: KnowledgeBase | None) -> KnowledgeBase:
    """Return the provided KB or create a default one with structure ensured."""
    if kb is None:
        kb = KnowledgeBase()
    kb.ensure_structure()
    return kb


def process_user_forward(
    content: str,
    source: str | None = None,
    ticker: str | None = None,
    kb: KnowledgeBase | None = None,
) -> dict:
    """Process content forwarded by the user.

    Steps:
    1. Determine source tier (user_forwarded = Tier 4 by default)
    2. Create a forwarded record with agent assessment header
    3. Save to user_context/forwarded/{slug}.md
    4. If ticker mentioned, note in user_views.md

    Args:
        content: The forwarded text/article content
        source: Source identifier (e.g. "seeking_alpha", "twitter", "personal")
        ticker: Associated stock ticker if known

    Returns:
        dict with: slug, source, tier, ticker, stored_at
    """
    kb = _get_kb(kb)

    # Determine source and tier
    effective_source = source or "user_forwarded"
    tier = 4  # default for user-forwarded content

    # Look up source in registry (best-effort)
    try:
        registry_tier = kb.get_source_tier(effective_source)
        if registry_tier is not None:
            tier = registry_tier
    except FileNotFoundError:
        pass  # no registry file — use default tier

    # Generate slug
    date_str = time.strftime("%Y-%m-%d")
    title_slug = _slugify(content)
    slug = f"{date_str}_{effective_source}_{title_slug}"

    # Build agent assessment
    tier_desc = _TIER_DESCRIPTIONS.get(tier, f"Tier {tier}. Verify before trusting.")
    ticker_line = f"**Ticker**: {ticker.upper()}\n" if ticker else ""

    record = (
        f"# Forwarded Content\n"
        f"**Date**: {date_str}\n"
        f"**Source**: {effective_source} (Tier {tier})\n"
        f"{ticker_line}"
        f"**Agent Assessment**: This is {tier_desc}\n"
        f"\n---\n\n"
        f"{content}"
    )

    # Save to user_context/forwarded/
    kb.write_forwarded(slug, record)
    stored_at = str(kb.root / "user_context" / "forwarded" / f"{slug}.md")

    # If ticker provided, add a note in user_views.md
    if ticker:
        _note_forwarded_for_ticker(ticker.upper(), slug, kb)

    # Audit log (best-effort)
    try:
        kb.append_log(f"User forwarded content stored: {slug}")
    except Exception:
        pass

    logger.info("user_input: forwarded content stored as %s (Tier %d)", slug, tier)

    return {
        "slug": slug,
        "source": effective_source,
        "tier": tier,
        "ticker": ticker.upper() if ticker else None,
        "stored_at": stored_at,
    }


def _note_forwarded_for_ticker(ticker: str, slug: str, kb: KnowledgeBase) -> None:
    """Add a note in user_views.md about forwarded content for a ticker."""
    views_text = kb.read_user_views() or "# User Views\n"
    date_str = time.strftime("%Y-%m-%d")

    # Check if ticker section exists
    ticker_header = f"### {ticker}"
    if ticker_header not in views_text:
        # No existing section — don't create a full view, just add a note section
        note = (
            f"\n\n### {ticker}\n"
            f"**Sentiment**: neutral\n"
            f"**Updated**: {date_str}\n"
            f"**View**: (forwarded content, no explicit view stated)\n"
            f"**Forwarded**: {slug}\n"
        )
        views_text = views_text.rstrip("\n") + note
        kb.write_user_views(views_text)


def update_user_view(
    ticker: str,
    view: str,
    sentiment: str = "neutral",
    kb: KnowledgeBase | None = None,
) -> None:
    """Record or update the user's view on a specific stock.

    Appends/updates the user's current stance in user_views.md.

    Args:
        ticker: Stock symbol
        view: User's view text (e.g. "Very bullish on NVDA due to AI demand")
        sentiment: bullish / bearish / neutral
    """
    kb = _get_kb(kb)

    ticker = ticker.upper()
    date_str = time.strftime("%Y-%m-%d")
    sentiment = sentiment.lower()
    if sentiment not in ("bullish", "bearish", "neutral"):
        sentiment = "neutral"

    views_text = kb.read_user_views() or "# User Views\n"

    new_section = (
        f"### {ticker}\n"
        f"**Sentiment**: {sentiment.capitalize()}\n"
        f"**Updated**: {date_str}\n"
        f"**View**: {view}\n"
    )

    # Check if ticker section already exists
    ticker_header = f"### {ticker}"
    if ticker_header in views_text:
        # Replace the existing section
        # Find the section boundaries: from "### TICKER" to the next "### " or end
        pattern = re.compile(
            rf"(### {re.escape(ticker)}\n)"  # header
            rf"(.*?)"  # section body
            rf"(?=\n### |\Z)",  # next section or end
            re.DOTALL,
        )
        views_text = pattern.sub(new_section.rstrip("\n"), views_text)
    else:
        # Append new section
        views_text = views_text.rstrip("\n") + "\n\n" + new_section

    kb.write_user_views(views_text)

    # Audit log (best-effort)
    try:
        kb.append_log(f"User view updated: {ticker} ({sentiment})")
    except Exception:
        pass

    logger.info("user_input: view updated for %s (%s)", ticker, sentiment)


def get_user_view_for_ticker(
    ticker: str,
    kb: KnowledgeBase | None = None,
) -> dict | None:
    """Extract the user's current view for a specific ticker from user_views.md.

    Returns dict with: ticker, view, sentiment, updated_date
    Or None if no view exists for this ticker.
    """
    if kb is None:
        kb = KnowledgeBase()

    views_text = kb.read_user_views()
    if not views_text:
        return None

    ticker = ticker.upper()
    ticker_header = f"### {ticker}"

    if ticker_header not in views_text:
        return None

    # Extract the section for this ticker
    # Find from "### TICKER" to the next "### " or end of text
    pattern = re.compile(
        rf"### {re.escape(ticker)}\n"
        rf"(.*?)"
        rf"(?=\n### |\Z)",
        re.DOTALL,
    )
    match = pattern.search(views_text)
    if not match:
        return None

    section = match.group(1)

    # Parse fields
    sentiment = "neutral"
    sentiment_match = re.search(r"\*\*Sentiment\*\*\s*:\s*(\w+)", section)
    if sentiment_match:
        sentiment = sentiment_match.group(1).lower()

    view = ""
    view_match = re.search(r"\*\*View\*\*\s*:\s*(.+?)(?:\n|$)", section)
    if view_match:
        view = view_match.group(1).strip()

    updated_date = ""
    date_match = re.search(r"\*\*Updated\*\*\s*:\s*(\S+)", section)
    if date_match:
        updated_date = date_match.group(1).strip()

    return {
        "ticker": ticker,
        "view": view,
        "sentiment": sentiment,
        "updated_date": updated_date,
    }
