"""Output handlers for Core Agent profiles.

Each handler runs after the Core Agent produces its output.
Analysis handler: saves report + logs prediction + checks divergence.
Digest handler: marks inbox items as processed (stub for 4.31).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from src.knowledge_base.kb_api import KnowledgeBase
from src.utils.event_log import log_event

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # global-market-agent/


async def save_report_and_log_prediction(
    output: str, context: dict, kb: KnowledgeBase
) -> None:
    """Analysis profile output handler.

    1. Save report to reports/ directory (legacy location)
    2. Rotate report in KB (latest_report.md + history)
    3. Log prediction (best-effort)
    4. Check divergence (best-effort)
    """
    ticker = context.get("ticker", "UNKNOWN")

    # 1. Save to reports/ (same as old _save_report in summary_agent.py)
    report_path = _save_report_file(ticker, output)
    if report_path:
        log_event("analysis.report_saved", stage="analysis",
                  sid=context.get("event_sid", ""),
                  ticker=ticker, path=report_path)

    # P0-FIX-1: Log report path for API discoverability
    try:
        from src.utils.execution_logger import get_execution_logger
        el = get_execution_logger()
        el.log_final_report(output, str(report_path) if report_path else "")
    except Exception:
        pass  # don't break analysis if logging fails

    # 2. KB report rotation
    try:
        kb.save_report_with_rotation(ticker, output)
        logger.info("Report rotated in KB for %s", ticker)
    except Exception as e:
        logger.warning("Failed to rotate report in KB: %s", e)

    # 3. Prediction logging (best-effort, from summary_agent.py lines 371-379)
    try:
        from src.knowledge_base.prediction_logger import log_prediction, extract_prediction_data

        logged = log_prediction(ticker, output, kb=kb, report_path=report_path or "")
        if logged:
            logger.info("Prediction logged for %s", ticker)
    except Exception as e:
        logger.warning("Prediction logging failed: %s", e)

    # 4. Divergence check (best-effort, from summary_agent.py lines 381-396)
    try:
        from src.knowledge_base.prediction_logger import extract_prediction_data
        from src.knowledge_base.divergence import check_and_record_divergence

        pred_data = extract_prediction_data(output)
        if pred_data.get("rating"):
            log_event("analysis.prediction", stage="analysis",
                      sid=context.get("event_sid", ""),
                      ticker=ticker,
                      rating=pred_data.get("rating", ""),
                      conviction=pred_data.get("conviction", ""))
            divergence = check_and_record_divergence(
                ticker=ticker,
                agent_rating=pred_data["rating"],
                agent_thesis=(
                    f"Rating: {pred_data['rating']}, "
                    f"Risk: {pred_data.get('risk_level', 'N/A')}"
                ),
                kb=kb,
            )
            if divergence:
                logger.info(
                    "Divergence detected for %s: agent=%s, user=%s",
                    ticker,
                    pred_data["rating"],
                    divergence.get("user_sentiment"),
                )
                log_event("analysis.divergence", stage="analysis",
                          sid=context.get("event_sid", ""),
                          ticker=ticker,
                          agent_view=pred_data["rating"],
                          user_view=divergence.get("user_sentiment", ""))
    except Exception as e:
        logger.warning("Divergence check failed: %s", e)


async def mark_library_read(
    output: str, context: dict, kb: KnowledgeBase
) -> None:
    """Digest profile output handler — marks batch items as read.

    Reads ``batch_items`` from *context* (list of inbox slugs) and moves
    each from ``library/unread/`` to ``library/read/``.
    """
    batch_items = context.get("batch_items", [])
    for slug in batch_items:
        try:
            kb.mark_read(slug)
        except FileNotFoundError:
            logger.warning("Item already read or not found: %s", slug)


def _save_report_file(ticker: str, report: str) -> str | None:
    """Save report to reports/ directory. Returns file path or None."""
    try:
        reports_dir = _PROJECT_ROOT / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"report_{ticker}_{timestamp}.md"
        path = reports_dir / filename
        path.write_text(report, encoding="utf-8")
        logger.info("Report saved to %s", path)
        return str(path)
    except Exception as e:
        logger.warning("Failed to save report: %s", e)
        return None
