"""Digest pipeline — LLM-powered batch processing of inbox items.

Flow: load pending → filter → batch → CoreAgent(DIGEST_PROFILE) per batch
→ session log → DigestResult.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from src.agents.core_agent import CoreAgent
from src.agents.filter_agent import filter_items
from src.agents.output_handlers import mark_library_read
from src.agents.profiles import DIGEST_PROFILE
from src.knowledge_base.kb_api import KnowledgeBase
from src.knowledge_base.perception import InboxItem, parse_inbox_item
from src.utils.event_log import log_event, new_session_id
from src.utils.execution_logger import ExecutionLogger, initialize_execution_logger, finalize_execution_logger, set_execution_logger

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    batch_num: int
    item_slugs: list[str]
    items_detail: list[tuple[str, str, int]]  # (slug, title, tier)
    agent_output: str


@dataclass
class DigestResult:
    total_inbox: int
    auto_passed: int
    filter_kept: int
    filter_dropped: int
    batches_completed: int
    items_processed: int
    session_summary: str
    batch_results: list[BatchResult]


async def run_digest(
    batch_size: int = 8,
    max_batch_chars: int = 400_000,
    filter_low_trust: bool = True,
    kb: KnowledgeBase | None = None,
    *,
    execution_logger: ExecutionLogger | None = None,
    simulated_date: str | None = None,
    retrain_slugs: list[str] | None = None,
) -> DigestResult:
    """Run the full digest pipeline on pending inbox items."""
    t_start = time.monotonic()
    sid = new_session_id("digest")
    _external_logger = execution_logger is not None
    exec_logger = execution_logger or initialize_execution_logger()
    if _external_logger:
        set_execution_logger(exec_logger)
    exec_id = exec_logger.execution_id
    kb = kb or KnowledgeBase()

    # KB snapshot before digest
    try:
        kb.create_snapshot(exec_logger.execution_dir, "before")
    except Exception:
        logger.debug("Failed to create pre-digest KB snapshot", exc_info=True)

    # Generate market snapshot as inbox item (normal mode only; retrain handles per-epoch)
    if retrain_slugs is None:
        try:
            from src.sources.market.snapshot import generate_market_snapshot_item

            snap_result = generate_market_snapshot_item(kb=kb)
            if snap_result.get("status") == "ok":
                logger.info("Market snapshot inbox item created: %s", snap_result["slug"])
        except Exception:
            logger.debug("Market snapshot generation failed (non-fatal)", exc_info=True)

    # Parse items — retrain mode reads specific unread slugs, normal mode reads all unread
    items: list[InboxItem] = []
    if retrain_slugs is not None:
        # Retrain mode: read specific slugs from unread (same source as normal mode)
        total_inbox = len(retrain_slugs)
        for slug in retrain_slugs:
            content = kb.read_unread(slug)
            if not content:
                logger.warning("retrain: article %s not found in unread, skipping", slug)
                continue
            item = parse_inbox_item(slug, content)
            if item is None:
                logger.warning("retrain: unparseable item %s, skipping", slug)
                continue
            items.append(item)
        # Skip filter in retrain mode
        filter_low_trust = False
    else:
        # Normal mode: read from pending
        pending_slugs = kb.list_unread()
        total_inbox = len(pending_slugs)
        for slug in pending_slugs:
            content = kb.read_unread(slug)
            if not content:
                continue
            item = parse_inbox_item(slug, content)
            if item is None:
                logger.warning("digest: unparseable item %s, marking digested", slug)
                try:
                    kb.mark_read(slug)
                except Exception as e:
                    logger.warning("digest: failed to mark %s digested: %s", slug, e)
                continue
            items.append(item)

    log_event("digest.session_start", stage="digest", sid=sid,
              execution_id=exec_id, total_items=total_inbox, batch_size=batch_size)

    if not items:
        if not _external_logger:
            finalize_execution_logger(success=True)
        return DigestResult(
            total_inbox=total_inbox,
            auto_passed=0,
            filter_kept=0,
            filter_dropped=0,
            batches_completed=0,
            items_processed=0,
            session_summary="",
            batch_results=[],
        )

    # Filter
    auto_passed_count = 0
    filter_kept_count = 0
    filter_dropped_count = 0

    if filter_low_trust:
        core_mind = kb.read_core_mind() or ""
        filter_result = await filter_items(items, core_mind[:2000], sid=sid)

        # Mark dropped items as digested
        for item in filter_result.dropped:
            try:
                kb.mark_read(item.slug)
            except Exception as e:
                logger.warning("digest: failed to mark dropped %s: %s", item.slug, e)

        kept = filter_result.auto_passed + filter_result.kept
        auto_passed_count = len(filter_result.auto_passed)
        filter_kept_count = len(filter_result.kept)
        filter_dropped_count = len(filter_result.dropped)
    else:
        kept = items
        filter_kept_count = len(items)

    if not kept:
        if not _external_logger:
            finalize_execution_logger(success=True)
        return DigestResult(
            total_inbox=total_inbox,
            auto_passed=auto_passed_count,
            filter_kept=filter_kept_count,
            filter_dropped=filter_dropped_count,
            batches_completed=0,
            items_processed=0,
            session_summary="",
            batch_results=[],
        )

    # Sort by published_date (oldest first) so agent reads in temporal order
    kept.sort(key=lambda item: item.published_date or "9999-99-99")

    # Save inbox manifest for execution archive
    try:
        manifest_items = [
            {
                "slug": item.slug,
                "title": item.title,
                "source": item.source,
                "tier": item.tier,
                "published_date": item.published_date,
                "char_count": len(item.body) if item.body else 0,
            }
            for item in kept
        ]
        snapshots_dir = exec_logger.execution_dir / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        (snapshots_dir / "inbox_manifest.json").write_text(
            json.dumps(manifest_items, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        logger.debug("Failed to save inbox manifest", exc_info=True)

    # Batch processing — dynamic splitting by character volume + item cap
    batches: list[list] = []
    current_batch: list = []
    current_chars = 0
    for item in kept:
        item_chars = len(item.body) if item.body else 0
        # Start new batch if adding this item would exceed limits
        # (but always allow at least 1 item per batch)
        if current_batch and (
            current_chars + item_chars > max_batch_chars
            or len(current_batch) >= batch_size
        ):
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append(item)
        current_chars += item_chars
    if current_batch:
        batches.append(current_batch)
    reading_history: list[str] = []
    batch_results: list[BatchResult] = []

    for batch_idx, batch in enumerate(batches):
        slugs = [item.slug for item in batch]

        batch_items = [
            {
                "slug": item.slug,
                "title": item.title,
                "title_en": item.title_en,
                "source": item.source,
                "published_date": item.published_date,
                "char_count": len(item.body) if item.body else 0,
            }
            for item in batch
        ]
        log_event("digest.batch_start", stage="digest", sid=sid,
                  execution_id=exec_id, batch_num=batch_idx + 1,
                  item_count=len(batch), item_slugs=slugs,
                  items=batch_items)

        input_text = _build_batch_input(
            batch, batch_idx + 1, len(batches), reading_history, kb,
            simulated_date=simulated_date,
        )

        profile = dataclasses.replace(
            DIGEST_PROFILE, output_handler=mark_library_read
        )
        agent = CoreAgent(profile, kb=kb)

        t_batch = time.monotonic()
        try:
            output = await agent.run(input_text, context={
                "batch_items": slugs,
                "event_sid": sid,
                "execution_id": exec_id,
            })
        except Exception as e:
            logger.warning("digest: batch %d error: %s", batch_idx + 1, e)
            output = f"# Batch Error\n\n**Error**: {e}"
            # Mark items as read even on error so they don't block future runs
            for slug in slugs:
                try:
                    kb.mark_read(slug)
                except Exception as mark_err:
                    logger.warning("digest: failed to mark %s: %s", slug, mark_err)
        batch_elapsed = time.monotonic() - t_batch

        log_event("digest.batch_complete", stage="digest", sid=sid,
                  execution_id=exec_id, batch_num=batch_idx + 1,
                  output_length=len(output), elapsed_s=round(batch_elapsed, 1))

        items_detail = [(item.slug, item.title, item.tier) for item in batch]
        br = BatchResult(
            batch_num=batch_idx + 1,
            item_slugs=slugs,
            items_detail=items_detail,
            agent_output=output,
        )
        batch_results.append(br)
        reading_history.append(_format_batch_for_history(br))

    successful_batches = [br for br in batch_results if not br.agent_output.startswith(("# Batch Error", "# Analysis Error"))]
    items_processed = sum(len(br.item_slugs) for br in successful_batches)
    session_summary = _build_session_summary(
        batch_results, auto_passed_count, filter_kept_count, filter_dropped_count
    )
    _append_session_log(kb, session_summary)

    # KB snapshot after digest
    try:
        kb.create_snapshot(exec_logger.execution_dir, "after")
    except Exception:
        logger.debug("Failed to create post-digest KB snapshot", exc_info=True)

    total_elapsed = time.monotonic() - t_start
    log_event("digest.session_end", stage="digest", sid=sid,
              execution_id=exec_id, batches=len(successful_batches),
              items_processed=items_processed, elapsed_s=round(total_elapsed, 1))

    all_succeeded = len(successful_batches) == len(batch_results) if batch_results else True
    if not _external_logger:
        finalize_execution_logger(success=all_succeeded)

    return DigestResult(
        total_inbox=total_inbox,
        auto_passed=auto_passed_count,
        filter_kept=filter_kept_count,
        filter_dropped=filter_dropped_count,
        batches_completed=len(successful_batches),
        items_processed=items_processed,
        session_summary=session_summary,
        batch_results=batch_results,
    )


def _build_batch_input(
    items: list[InboxItem],
    batch_num: int,
    total_batches: int,
    reading_history: list[str],
    kb: KnowledgeBase,
    simulated_date: str | None = None,
) -> str:
    """Build the input text for a single digest batch."""
    parts: list[str] = []

    # Header
    parts.append(f"## Digest Batch {batch_num}/{total_batches}")

    # Date injection
    if simulated_date:
        parts.append(f"\n**Current Date: {simulated_date}**")
        parts.append("You are processing articles published on or before this date.")
        parts.append("When reasoning about timing and relevance, use this as your reference date.")
    else:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        parts.append(f"\n**Current Date: {today}**")

    # Reading history
    if reading_history:
        parts.append("\n### Reading History\n")
        parts.append("\n---\n".join(reading_history))

    # Catalog grouped by tier
    parts.append("\n### Items to Digest\n")

    by_tier: dict[int, list[tuple[int, InboxItem]]] = {}
    for i, item in enumerate(items, 1):
        by_tier.setdefault(item.tier, []).append((i, item))

    for tier in sorted(by_tier.keys()):
        if tier <= 2:
            label = f"**Tier {tier} (high trust):**"
        elif tier == 3:
            label = "**Tier 3 (medium trust):**"
        else:
            label = f"**Tier {tier} (low trust):**"
        parts.append(label)
        for idx, item in by_tier[tier]:
            preview = item.body[:200].replace("\n", " ")
            date_tag = item.published_date or "no date"
            parts.append(
                f"{idx}. #{item.slug}  [{date_tag}] {item.source} — \"{item.title}\""
            )
            parts.append(f"   Preview: {preview}")
        parts.append("")

    # Source freshness
    source_status = kb.build_source_status()
    if not source_status.startswith("No source"):
        parts.append(f"### {source_status}")
        parts.append("")

    # KB state summary
    parts.append("### Current KB State")
    themes_count = len(kb.list_themes())
    events_count = len(kb.list_events())
    sectors_count = len(kb.list_sectors())
    core_mind = kb.read_core_mind()
    cm_status = "initialized" if core_mind else "not yet created"
    parts.append(f"- Themes: {themes_count} files")
    parts.append(f"- Events: {events_count} files")
    parts.append(f"- Sectors: {sectors_count} files")
    parts.append(f"- Core mind: {cm_status}")

    # First-session hint: when KB is empty, guide the agent to bootstrap
    if not core_mind and themes_count == 0 and events_count == 0:
        parts.append("")
        parts.append(
            "**Note: Your notebook is empty — this is a fresh start. "
            "As you digest these articles, create your initial core_mind "
            "dashboard and theme files from scratch. Focus on identifying "
            "the major macro themes, key risks, and market regime from "
            "the information available.**"
        )

    parts.append("")
    parts.append('Use read_inbox_item("slug") to read any item\'s full content.')

    return "\n".join(parts)


def _format_batch_for_history(result: BatchResult) -> str:
    """Format a batch result for the reading history section."""
    parts: list[str] = []
    parts.append(f"## Batch {result.batch_num} Summary")

    # Items line
    detail_strs: list[str] = []
    for slug, title, tier in result.items_detail[:8]:
        detail_strs.append(f"#{slug} (Tier {tier}, \"{title}\")")
    items_line = "Items: " + ", ".join(detail_strs)
    if len(result.items_detail) > 8:
        items_line += f" ... and {len(result.items_detail) - 8} more"
    parts.append(items_line)

    # Session notes (extracted from agent output)
    match = re.search(
        r"### Session Notes\n(.*?)(?:\n##|\Z)", result.agent_output, re.DOTALL
    )
    if match:
        parts.append("")
        parts.append(match.group(1).strip())
    else:
        preview = result.agent_output[:300].replace("\n", " ")
        parts.append("")
        parts.append(preview)

    return "\n".join(parts)


def _build_session_summary(
    batch_results: list[BatchResult],
    auto_passed: int,
    filter_kept: int,
    filter_dropped: int,
) -> str:
    """Build the full session summary for the digest log."""
    ts = datetime.now(timezone.utc).isoformat()
    total_processed = sum(len(br.item_slugs) for br in batch_results)

    parts: list[str] = []
    parts.append(f"## Digest Session {ts}")
    parts.append(f"- Auto-passed: {auto_passed} items (tier 1-2)")
    parts.append(f"- Filter kept: {filter_kept} | dropped: {filter_dropped}")
    parts.append(f"- Batches: {len(batch_results)}")
    parts.append(f"- Total processed: {total_processed}")

    for br in batch_results:
        parts.append("")
        parts.append(f"### Batch {br.batch_num}")
        parts.append(f"Items: {', '.join(br.item_slugs)}")
        preview = br.agent_output[:200].replace("\n", " ")
        parts.append(f"{preview}...")

    return "\n".join(parts)


def _append_session_log(kb: KnowledgeBase, summary: str) -> None:
    """Prepend session summary to meta/digest_sessions.md (newest first)."""
    path = kb.data_root / "meta" / "digest_sessions.md"
    existing = kb._read_text(path) or ""
    if existing:
        combined = summary + "\n\n---\n\n" + existing
    else:
        combined = summary
    kb._write_text(path, combined)
