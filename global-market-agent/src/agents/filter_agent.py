"""Filter Agent — lightweight LLM-based relevance filter for inbox items.

Separates high-trust items (auto-pass) from lower-trust items that need
LLM-based KEEP/DROP decision. Always fails safe (keeps all on error).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage

from src.knowledge_base.perception import InboxItem
from src.utils.event_log import log_event
from src.utils.llm_clients import create_llm

logger = logging.getLogger(__name__)

FILTER_PROMPT = """\
You are a relevance filter for a financial analysis system.

Your current investment focus:
{core_mind_summary}

Below are {count} new information items. Decide which are worth reading in full.

{catalog}

Output EXACTLY in this format (nothing else):
KEEP: 1, 5, 12
DROP: 2, 3, 4, 6, 7, 8, 9, 10, 11
REASON: #1 relevant to AI capex theme; #5 new tariff development"""


@dataclass
class FilterResult:
    kept: list[InboxItem] = field(default_factory=list)
    dropped: list[InboxItem] = field(default_factory=list)
    auto_passed: list[InboxItem] = field(default_factory=list)
    reasons: str = ""


def _parse_keep_ids(content: str, total: int) -> list[int]:
    """Extract KEEP IDs from LLM response. Returns all IDs on parse failure."""
    match = re.search(r"KEEP:\s*([\d,\s]+)", content)
    if not match:
        logger.warning("filter: no KEEP line found, keeping all")
        return list(range(1, total + 1))

    raw = match.group(1).strip()
    if not raw:
        logger.warning("filter: empty KEEP list, keeping all")
        return list(range(1, total + 1))

    try:
        ids = [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        logger.warning("filter: could not parse KEEP IDs, keeping all")
        return list(range(1, total + 1))

    if not ids:
        logger.warning("filter: parsed zero KEEP IDs, keeping all")
        return list(range(1, total + 1))

    return ids


async def filter_items(
    items: list[InboxItem],
    core_mind_summary: str,
    auto_pass_tier: int = 2,
    sid: str = "",
) -> FilterResult:
    """Filter inbox items: auto-pass high-trust, LLM-filter the rest."""
    if not items:
        return FilterResult()

    result = FilterResult()

    log_event("filter.start", stage="filter", sid=sid,
              total_items=len(items), auto_pass_tier=auto_pass_tier)

    # Separate auto-pass (high trust) from candidates
    candidates: list[InboxItem] = []
    for item in items:
        if item.tier <= auto_pass_tier:
            result.auto_passed.append(item)
        else:
            candidates.append(item)

    if not candidates:
        return result

    # Build numbered catalog for LLM
    catalog_lines: list[str] = []
    for i, item in enumerate(candidates, 1):
        preview = item.body[:150].replace("\n", " ")
        date_tag = item.published_date or "no date"
        catalog_lines.append(f"{i}. [{item.source}, Tier {item.tier}, {date_tag}] \"{item.title}\"")
        catalog_lines.append(f"   Preview: {preview}")

    prompt_text = FILTER_PROMPT.format(
        core_mind_summary=core_mind_summary or "(no current focus)",
        count=len(candidates),
        catalog="\n".join(catalog_lines),
    )

    try:
        llm = create_llm(temperature=0, max_tokens=500)
        response = await llm.ainvoke([HumanMessage(content=prompt_text)])
        content = response.content

        # Extract reasons
        reason_match = re.search(r"REASON:\s*(.+)", content, re.DOTALL)
        if reason_match:
            result.reasons = reason_match.group(1).strip()

        keep_ids = _parse_keep_ids(content, len(candidates))
        keep_set = set(keep_ids)

        for i, item in enumerate(candidates, 1):
            if i in keep_set:
                result.kept.append(item)
            else:
                result.dropped.append(item)

    except Exception as e:
        logger.warning("filter: LLM error (%s), keeping all candidates", e)
        result.kept = candidates

    # Log per-item decisions
    for item in result.kept:
        log_event("filter.decision", stage="filter", sid=sid, slug=item.slug, action="keep")
    for item in result.dropped:
        log_event("filter.decision", stage="filter", sid=sid, slug=item.slug, action="drop")
    for item in result.auto_passed:
        log_event("filter.decision", stage="filter", sid=sid, slug=item.slug, action="auto_pass")

    log_event("filter.complete", stage="filter", sid=sid,
              kept=len(result.kept), dropped=len(result.dropped),
              auto_passed=len(result.auto_passed), reason=result.reasons[:200])

    return result
