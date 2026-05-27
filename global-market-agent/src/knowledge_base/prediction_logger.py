"""Prediction logging -- records analysis predictions and reviews accuracy."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from src.knowledge_base.kb_api import KnowledgeBase

logger = logging.getLogger(__name__)

# Rating values the system uses (5-tier scale)
_VALID_RATINGS = {"Buy", "Overweight", "Hold", "Underweight", "Sell"}

# Patterns for extracting data from the report
_RATING_PATTERNS = [
    # Long-term section: - **Recommendation**: **Hold**
    r"\*\*Recommendation\*\*\s*:\s*\*\*(\w+)\*\*",
    # Decision Dashboard table: | **Already Own** | **Hold** |
    r"\|\s*\*\*Already Own\*\*\s*\|\s*\*\*(\w+)\*\*",
    # Decision Dashboard: | **Considering Buying** | **Overweight** |
    r"\|\s*\*\*Considering Buying\*\*\s*\|\s*\*\*(\w+)\*\*",
]

_CONVICTION_PATTERNS = [
    r"\*\*Conviction Level\*\*\s*:\s*\*\*([\w-]+)\*\*",
    r"\*\*Conviction Level\*\*\s*:\s*(High|Medium|Low)",
]

_RISK_PATTERNS = [
    r"\*\*Risk Level\*\*\s*:\s*\*\*([\w\s]+?)\*\*",
    r"\*\*Risk Level\*\*\s*:\s*(Low|Medium|High|Very High)",
]

# Price near the start of the report -- e.g. "At $298.21" or "trading ... at $235.67"
_PRICE_PATTERNS = [
    r"[Aa]t\s+\$([0-9]+(?:\.[0-9]+)?)",
    r"trading\s+(?:\w+\s+)*at\s+\$([0-9]+(?:\.[0-9]+)?)",
    r"current(?:\s+\w+)*\s+price\s+(?:\w+\s+)*\$([0-9]+(?:\.[0-9]+)?)",
]


def extract_prediction_data(report: str) -> dict:
    """Extract prediction data from a markdown report using regex.

    Returns dict with:
    - rating: str | None  (Buy/Overweight/Hold/Underweight/Sell)
    - conviction: str | None  (High/Medium/Low or similar)
    - risk_level: str | None  (Low/Medium/High/Very High)
    - current_price: float | None  (extracted from report if possible)
    """
    result: dict = {
        "rating": None,
        "conviction": None,
        "risk_level": None,
        "current_price": None,
    }

    if not report or not isinstance(report, str):
        return result

    # Extract rating -- try each pattern, pick the first valid one
    for pattern in _RATING_PATTERNS:
        match = re.search(pattern, report)
        if match:
            candidate = match.group(1).strip()
            if candidate in _VALID_RATINGS:
                result["rating"] = candidate
                break

    # Extract conviction
    for pattern in _CONVICTION_PATTERNS:
        match = re.search(pattern, report)
        if match:
            result["conviction"] = match.group(1).strip()
            break

    # Extract risk level
    for pattern in _RISK_PATTERNS:
        match = re.search(pattern, report)
        if match:
            raw = match.group(1).strip()
            # Normalize: take just the risk level keyword(s) before any dash/em-dash
            cleaned = re.split(r"\s*[—–\-]\s*", raw)[0].strip()
            if cleaned in ("Low", "Medium", "High", "Very High"):
                result["risk_level"] = cleaned
            break

    # Extract current price (first match near the start of the report)
    # Search only in the first ~2000 chars for relevance
    head = report[:2000]
    for pattern in _PRICE_PATTERNS:
        match = re.search(pattern, head)
        if match:
            try:
                result["current_price"] = float(match.group(1))
            except ValueError:
                pass
            break

    return result


def format_prediction_record(
    ticker: str,
    data: dict,
    report_path: str | None = None,
) -> str:
    """Format a prediction record as markdown.

    Example output:
    ---
    ### 2026-05-14 | AAPL | $189.50
    - **Rating**: Overweight (Medium conviction)
    - **Risk Level**: Medium
    - **Report**: reports/report_AAPL_20260514_143022.md
    ---
    """
    date_str = time.strftime("%Y-%m-%d")
    price_str = f"${data['current_price']:.2f}" if data.get("current_price") else "N/A"
    rating = data.get("rating") or "Unknown"
    conviction = data.get("conviction")
    risk_level = data.get("risk_level") or "Unknown"

    conv_suffix = f" ({conviction} conviction)" if conviction else ""

    # Make report path relative if it's an absolute path
    report_ref = ""
    if report_path:
        rp = Path(report_path)
        # Try to make it relative to the project root
        try:
            project_root = Path(__file__).resolve().parents[2]
            report_ref = str(rp.relative_to(project_root))
        except (ValueError, RuntimeError):
            report_ref = str(rp.name)

    lines = [
        "---",
        f"### {date_str} | {ticker.upper()} | {price_str}",
        f"- **Rating**: {rating}{conv_suffix}",
        f"- **Risk Level**: {risk_level}",
    ]
    if report_ref:
        lines.append(f"- **Report**: {report_ref}")
    lines.append("---")

    return "\n".join(lines) + "\n"


def log_prediction(
    ticker: str,
    report: str,
    kb: KnowledgeBase | None = None,
    report_path: str | None = None,
) -> bool:
    """Extract key prediction data from a report and log to KB.

    Appends a structured prediction record to stocks/{TICKER}/predictions.md.

    Returns True if prediction was logged successfully, False otherwise.
    """
    try:
        data = extract_prediction_data(report)

        # If we couldn't extract even a rating, the report is too malformed
        if data["rating"] is None and data["current_price"] is None:
            logger.debug("prediction: no extractable data from report for %s", ticker)
            return False

        record = format_prediction_record(ticker, data, report_path=report_path)

        if kb is None:
            kb = KnowledgeBase()

        # Read existing predictions, append new record
        existing = kb.read_stock(ticker, "predictions") or "# Predictions\n\n"
        updated = existing.rstrip("\n") + "\n\n" + record
        kb.write_stock(ticker, "predictions", updated)

        # Audit log
        try:
            kb.append_log(f"Prediction logged for {ticker}")
        except Exception:
            pass  # audit logging is best-effort

        return True

    except Exception as e:
        logger.debug("prediction: failed to log for %s: %s", ticker, e)
        return False


async def review_predictions(
    ticker: str | None = None,
    kb: KnowledgeBase | None = None,
) -> str:
    """Review past predictions by comparing with current prices.

    If ticker is specified, reviews only that ticker.
    Otherwise reviews all tickers with predictions.

    Returns a formatted markdown review report.
    Uses yfinance to get current prices (import inside function).
    """
    if kb is None:
        kb = KnowledgeBase()

    # Find all tickers with predictions
    tickers_to_review: list[str] = []
    stocks_dir = kb.root / "notebook" / "stocks"
    if ticker:
        tickers_to_review = [ticker.upper()]
    else:
        if stocks_dir.is_dir():
            for d in sorted(stocks_dir.iterdir()):
                if d.is_dir() and (d / "predictions.md").is_file():
                    tickers_to_review.append(d.name)

    if not tickers_to_review:
        return "# Prediction Review\n\nNo predictions found in the knowledge base."

    # Try to import yfinance for current prices
    yf_available = True
    try:
        import yfinance as yf  # noqa: F401
    except ImportError:
        yf_available = False

    lines = ["# Prediction Review", ""]
    lines.append(f"*Generated: {time.strftime('%Y-%m-%d %H:%M UTC')}*")
    lines.append("")

    found_any = False

    for tkr in tickers_to_review:
        predictions_text = kb.read_stock(tkr, "predictions")
        if not predictions_text:
            continue

        # Parse prediction records
        records = _parse_prediction_records(predictions_text)
        if not records:
            continue

        found_any = True

        # Get current price
        current_price = None
        if yf_available:
            try:
                import yfinance as yf

                stock = yf.Ticker(tkr)
                current_price = stock.info.get("currentPrice") or stock.info.get(
                    "regularMarketPrice"
                )
            except Exception as e:
                logger.debug("review: failed to fetch price for %s: %s", tkr, e)

        lines.append(f"## {tkr}")
        lines.append("")

        if current_price:
            lines.append(f"**Current Price**: ${current_price:.2f}")
            lines.append("")

        # Build review table
        lines.append(
            "| Date | Rating | Price Then | Price Now | Return | Verdict |"
        )
        lines.append("|------|--------|-----------|----------|--------|---------|")

        for rec in records:
            date = rec.get("date", "?")
            rating = rec.get("rating", "?")
            price_then = rec.get("price")

            if current_price and price_then:
                ret = (current_price - price_then) / price_then * 100
                ret_str = f"{ret:+.1f}%"
                # Verdict: did the rating direction match the actual return?
                verdict = _compute_verdict(rating, ret)
                price_now_str = f"${current_price:.2f}"
                price_then_str = f"${price_then:.2f}"
            else:
                ret_str = "N/A"
                verdict = "N/A"
                price_now_str = f"${current_price:.2f}" if current_price else "N/A"
                price_then_str = f"${price_then:.2f}" if price_then else "N/A"

            lines.append(
                f"| {date} | {rating} | {price_then_str} | {price_now_str} | {ret_str} | {verdict} |"
            )

        lines.append("")

    if not found_any:
        return "# Prediction Review\n\nNo predictions found in the knowledge base."

    return "\n".join(lines)


def _parse_prediction_records(text: str) -> list[dict]:
    """Parse prediction records from a predictions.md file.

    Each record looks like:
    ### 2026-05-14 | AAPL | $189.50
    - **Rating**: Overweight (Medium conviction)
    ...

    Returns list of dicts with keys: date, ticker, price, rating.
    """
    records: list[dict] = []

    # Match the header line: ### DATE | TICKER | $PRICE
    header_pattern = re.compile(
        r"###\s+(\d{4}-\d{2}-\d{2})\s*\|\s*(\w+)\s*\|\s*\$?([\d.]+|N/A)"
    )
    rating_pattern = re.compile(r"\*\*Rating\*\*\s*:\s*(\w+)")

    # Split by "---" sections and process each
    sections = re.split(r"^---$", text, flags=re.MULTILINE)

    for section in sections:
        header_match = header_pattern.search(section)
        if not header_match:
            continue

        date_str = header_match.group(1)
        ticker = header_match.group(2)
        price_str = header_match.group(3)

        price = None
        if price_str != "N/A":
            try:
                price = float(price_str)
            except ValueError:
                pass

        rating_match = rating_pattern.search(section)
        rating = rating_match.group(1) if rating_match else "Unknown"

        records.append(
            {
                "date": date_str,
                "ticker": ticker,
                "price": price,
                "rating": rating,
            }
        )

    return records


def _compute_verdict(rating: str, return_pct: float) -> str:
    """Compute a simple verdict: did the rating direction match the return?"""
    bullish_ratings = {"Buy", "Overweight"}
    bearish_ratings = {"Sell", "Underweight"}

    if rating in bullish_ratings:
        if return_pct > 2:
            return "Correct"
        elif return_pct < -2:
            return "Wrong"
        else:
            return "Neutral"
    elif rating in bearish_ratings:
        if return_pct < -2:
            return "Correct"
        elif return_pct > 2:
            return "Wrong"
        else:
            return "Neutral"
    else:
        # Hold
        if abs(return_pct) < 5:
            return "Correct"
        else:
            return "Missed Move"
