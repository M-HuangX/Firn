"""DEPRECATED (D26): Context injection — replaced by Core Agent KB tools.

The Core Agent now uses KBToolSet to read KB data directly via tools,
replacing the passive injection approach. This module is kept for
backward compatibility but will be removed.

Original description:
When the agent analyzes a stock, this module loads relevant Knowledge Base
context and formats it for injection into agent prompts.  This gives the
agent "memory" — it remembers its world view, past analyses, and user
perspectives.

All functions are safe to call even when the KB does not exist or has no
data.  The system works perfectly fine without a KB — this is optional
enrichment.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Short principles reminder (not the full file — keeps token count low)
_PRINCIPLES_REMINDER = (
    "1. Epistemic humility: estimate probabilities, don't predict certainties.\n"
    "2. Valuation discipline: good company != good investment at any price.\n"
    "3. Expectation-gap thinking: alpha = reality minus expectations.\n"
    "4. Contrarian alertness: consensus is already priced in.\n"
    "5. Source skepticism: consider source incentives.\n"
    "6. Anti-FOMO: missing an opportunity is not a loss.\n"
    "7. Falsifiability: every judgment needs 'what would prove me wrong?'"
)

# Maximum characters to load from any single KB file to prevent prompt bloat
_MAX_FILE_CHARS = 3000


def _safe_read(text: str | None) -> str | None:
    """Truncate text to _MAX_FILE_CHARS if it's too long, or return None."""
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    if len(text) > _MAX_FILE_CHARS:
        return text[:_MAX_FILE_CHARS] + "\n\n[... truncated for context length ...]"
    return text


def load_kb_context(ticker: str, kb: "KnowledgeBase | None" = None) -> dict:
    """Load all relevant KB context for analyzing a stock.

    Returns a dict with available context (values are ``str | None``).
    Gracefully handles missing KB or files — returns dict with
    ``available=False`` on error.

    Parameters
    ----------
    ticker:
        Stock ticker symbol (e.g. "AAPL").
    kb:
        Optional pre-existing KnowledgeBase instance.  If *None*, a default
        one is created (pointing to ``global-market-agent/firn/``).
    """
    empty_result: dict = {
        "core_mind": None,
        "stock_thesis": None,
        "stock_expectations": None,
        "stock_predictions": None,
        "user_views": None,
        "divergences": None,
        "principles_summary": _PRINCIPLES_REMINDER,
        "theme_list": [],
        "available": False,
    }

    try:
        if kb is None:
            from src.knowledge_base.kb_api import KnowledgeBase
            kb = KnowledgeBase()

        # If the KB root directory doesn't even exist, bail early
        if not kb.root.is_dir():
            logger.debug("KB root does not exist: %s", kb.root)
            return empty_result

        ticker_upper = ticker.upper()

        result: dict = {
            "core_mind": _safe_read(kb.read_core_mind()),
            "stock_thesis": _safe_read(kb.read_stock(ticker_upper, "thesis")),
            "stock_expectations": _safe_read(kb.read_stock(ticker_upper, "expectations")),
            "stock_predictions": _safe_read(kb.read_stock(ticker_upper, "predictions")),
            "user_views": _safe_read(kb.read_user_views()),
            "divergences": _safe_read(kb.read_divergences()),
            "principles_summary": _PRINCIPLES_REMINDER,
            "theme_list": kb.list_themes(),
            "available": True,
        }

        logger.debug(
            "KB context loaded for %s: core_mind=%s, thesis=%s, themes=%d",
            ticker_upper,
            result["core_mind"] is not None,
            result["stock_thesis"] is not None,
            len(result["theme_list"]),
        )
        return result

    except Exception:
        logger.warning("Failed to load KB context for %s", ticker, exc_info=True)
        return empty_result


def format_kb_context_for_summary(ctx: dict, ticker: str) -> str:
    """Format KB context as a section to append to the summary agent's user prompt.

    Returns empty string if no meaningful context is available.
    """
    if not ctx.get("available"):
        return ""

    sections: list[str] = []

    if ctx.get("core_mind"):
        sections.append(
            "### Agent's Current World View (Core Mind)\n" + ctx["core_mind"]
        )

    if ctx.get("stock_thesis"):
        sections.append(
            f"### Previous Analysis of {ticker}\n" + ctx["stock_thesis"]
        )

    if ctx.get("stock_expectations"):
        sections.append(
            f"### Previous Implied Expectations for {ticker}\n"
            + ctx["stock_expectations"]
        )

    if ctx.get("stock_predictions"):
        sections.append(
            f"### Past Predictions for {ticker}\n" + ctx["stock_predictions"]
        )

    if ctx.get("user_views"):
        sections.append(
            "### User's Investment Views\n" + ctx["user_views"]
        )

    if ctx.get("divergences"):
        sections.append(
            "### Agent-User Divergences\n" + ctx["divergences"]
        )

    if ctx.get("principles_summary"):
        sections.append(
            "### Agent Principles Reminder\n" + ctx["principles_summary"]
        )

    if not sections:
        return ""

    return "## KNOWLEDGE BASE CONTEXT\n\n" + "\n\n".join(sections)


def format_kb_context_for_value(ctx: dict, ticker: str) -> str:
    """Format KB context relevant to value analysis (lighter weight).

    Only includes stock expectations and the market regime line from core mind.
    Returns empty string if no meaningful context is available.
    """
    if not ctx.get("available"):
        return ""

    sections: list[str] = []

    if ctx.get("stock_expectations"):
        sections.append(
            f"### Previous Implied Expectations for {ticker}\n"
            + ctx["stock_expectations"]
        )

    # Extract just the market regime line from core_mind (if present)
    core_mind = ctx.get("core_mind")
    if core_mind:
        regime_line = _extract_regime_line(core_mind)
        if regime_line:
            sections.append("### Current Market Regime\n" + regime_line)

    if not sections:
        return ""

    return "## KNOWLEDGE BASE CONTEXT\n\n" + "\n\n".join(sections)


def _extract_regime_line(core_mind: str) -> str | None:
    """Extract the market regime line from core_mind content.

    Looks for lines containing 'regime' (case-insensitive) and returns
    the first match.  Falls back to the first non-header, non-empty line.
    """
    for line in core_mind.splitlines():
        stripped = line.strip()
        if stripped and "regime" in stripped.lower():
            # Remove leading markdown header markers
            return stripped.lstrip("#").strip()

    return None
