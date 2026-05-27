"""Retrain Pipeline -- clear KB and re-learn from library articles chronologically.

Scans the KB's entire library (both unread and read), groups articles into
chronological epochs with simulated dates, then processes each epoch through
the digest pipeline.  Processed articles move from unread/ to read/ normally.

Primary use cases:
  1. Clear Firn's KB and retrain from scratch with simulated time progression
  2. Debug: run only the first few epochs instead of processing hundreds of articles

Usage (via CLI)::

    uv run python -m src --retrain --dry-run       # preview schedule
    uv run python -m src --retrain                  # full retrain
    uv run python -m src --retrain --epochs 3       # first 3 epochs only
    uv run python -m src --retrain --epochs 5-8     # epochs 5 through 8
"""

from __future__ import annotations

import logging
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.knowledge_base.kb_api import KnowledgeBase
from src.knowledge_base.perception import parse_inbox_item

logger = logging.getLogger(__name__)


def _is_valid_date(date_str: str) -> bool:
    """Check if a string is a valid YYYY-MM-DD date."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RetrainEpoch:
    """A single epoch in a retrain schedule."""

    epoch_num: int              # 1-based
    simulated_date: str         # YYYY-MM-DD -- agent's "today"
    covers_dates: list[str]     # calendar days covered
    article_slugs: list[str]    # article slugs to process
    article_count: int
    total_chars: int


@dataclass
class RetrainSchedule:
    """Full retrain schedule containing all epochs."""

    epochs: list[RetrainEpoch]
    total_articles: int
    total_chars: int
    date_range: tuple[str, str]  # (earliest, latest)


# ---------------------------------------------------------------------------
# Schedule computation
# ---------------------------------------------------------------------------

def compute_schedule(
    kb: KnowledgeBase,
    min_articles: int = 3,
    max_gap_days: int = 7,
) -> RetrainSchedule:
    """Scan the entire KB library and build a chronological retrain schedule.

    Groups articles by ``published_date``, then aggregates sparse days into
    epochs that each contain at least *min_articles* articles.  A new epoch
    is also forced when the calendar gap between consecutive dates exceeds
    *max_gap_days*.

    Scans both ``library/unread/`` and ``library/read/`` so the schedule
    reflects ALL available articles regardless of processing state.

    Parameters
    ----------
    kb:
        KnowledgeBase instance.
    min_articles:
        Minimum number of articles before an epoch boundary is placed.
    max_gap_days:
        Maximum calendar-day gap within a single epoch.

    Returns
    -------
    RetrainSchedule
        A schedule object containing the ordered list of epochs.
    """
    slugs = kb.list_all_library()
    if not slugs:
        logger.info("retrain: library is empty, nothing to schedule")
        return RetrainSchedule(
            epochs=[],
            total_articles=0,
            total_chars=0,
            date_range=("", ""),
        )

    # Track which slugs are still unread (only those will be processed)
    unread_set = set(kb.list_unread())

    # -- Step 1: parse each article, group by published_date ----------------
    date_groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
    unknown_articles: list[tuple[str, int]] = []

    for slug in slugs:
        # Read from whichever directory the article is in
        content = kb.read_unread(slug) if slug in unread_set else kb.read_article(slug)
        if not content:
            logger.debug("retrain: slug %s has no content, skipping", slug)
            continue
        item = parse_inbox_item(slug, content)
        if item is None:
            logger.warning("retrain: could not parse item %s, skipping", slug)
            continue
        char_count = len(content)
        pd = item.published_date
        if pd and pd != "unknown" and _is_valid_date(pd):
            date_groups[pd].append((slug, char_count))
        else:
            unknown_articles.append((slug, char_count))

    sorted_dates = sorted(date_groups.keys())

    if not sorted_dates:
        # All articles have unknown dates -- single epoch with today's date
        if unknown_articles:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            all_slugs = [s for s, _ in unknown_articles]
            total_ch = sum(c for _, c in unknown_articles)
            epoch = RetrainEpoch(
                epoch_num=1,
                simulated_date=today,
                covers_dates=[],
                article_slugs=all_slugs,
                article_count=len(all_slugs),
                total_chars=total_ch,
            )
            return RetrainSchedule(
                epochs=[epoch],
                total_articles=len(all_slugs),
                total_chars=total_ch,
                date_range=(today, today),
            )
        return RetrainSchedule(epochs=[], total_articles=0, total_chars=0, date_range=("", ""))

    # -- Step 2: walk dates and aggregate into groups -----------------------
    raw_groups: list[list[str]] = []
    current_group_dates: list[str] = []
    current_group_count: int = 0

    for date_str in sorted_dates:
        day_count = len(date_groups[date_str])

        if current_group_dates:
            prev_date = datetime.strptime(current_group_dates[-1], "%Y-%m-%d")
            curr_date = datetime.strptime(date_str, "%Y-%m-%d")
            gap = (curr_date - prev_date).days

            if gap > max_gap_days:
                raw_groups.append(current_group_dates)
                current_group_dates = []
                current_group_count = 0
            elif current_group_count >= min_articles:
                raw_groups.append(current_group_dates)
                current_group_dates = []
                current_group_count = 0

        current_group_dates.append(date_str)
        current_group_count += day_count

    if current_group_dates:
        raw_groups.append(current_group_dates)

    # -- Step 3: build RetrainEpoch objects ---------------------------------
    epochs: list[RetrainEpoch] = []
    for idx, group_dates in enumerate(raw_groups):
        ep_slugs: list[str] = []
        ep_chars: int = 0
        for d in group_dates:
            for slug, chars in date_groups[d]:
                ep_slugs.append(slug)
                ep_chars += chars

        epoch = RetrainEpoch(
            epoch_num=idx + 1,
            simulated_date=group_dates[-1],
            covers_dates=group_dates,
            article_slugs=ep_slugs,
            article_count=len(ep_slugs),
            total_chars=ep_chars,
        )
        epochs.append(epoch)

    # Append unknown-date articles to the last epoch
    if unknown_articles and epochs:
        last = epochs[-1]
        for slug, chars in unknown_articles:
            last.article_slugs.append(slug)
            last.total_chars += chars
        last.article_count = len(last.article_slugs)
        logger.info(
            "retrain: appended %d unknown-date articles to epoch %d",
            len(unknown_articles),
            last.epoch_num,
        )

    total_articles = sum(e.article_count for e in epochs)
    total_chars = sum(e.total_chars for e in epochs)
    date_range = (sorted_dates[0], sorted_dates[-1])

    schedule = RetrainSchedule(
        epochs=epochs,
        total_articles=total_articles,
        total_chars=total_chars,
        date_range=date_range,
    )

    logger.info(
        "retrain: computed schedule — %d epochs, %d articles, date range %s to %s",
        len(epochs),
        total_articles,
        date_range[0],
        date_range[1],
    )
    return schedule


# ---------------------------------------------------------------------------
# Retrain execution
# ---------------------------------------------------------------------------

async def run_retrain(
    epoch_range: tuple[int, int] | None = None,
    dry_run: bool = False,
    min_articles: int = 3,
    max_gap_days: int = 7,
) -> RetrainSchedule | None:
    """Run the retrain pipeline — clear KB and re-learn chronologically.

    Computes a schedule from ALL library articles (read + unread), then
    processes only the unread articles in each selected epoch.  Processed
    articles move from ``library/unread/`` to ``library/read/`` normally.

    Parameters
    ----------
    epoch_range:
        Optional ``(start, end)`` 1-based inclusive range of epochs to run.
        ``None`` means run all epochs.
    dry_run:
        If True, compute and print the schedule without executing anything.
    min_articles:
        Minimum articles per epoch (passed to :func:`compute_schedule`).
    max_gap_days:
        Maximum calendar-day gap within an epoch (passed to :func:`compute_schedule`).

    Returns
    -------
    RetrainSchedule | None
        The computed schedule, or None if the library is empty.
    """
    from src.knowledge_base.digest_pipeline import run_digest

    kb = KnowledgeBase()
    schedule = compute_schedule(kb, min_articles=min_articles, max_gap_days=max_gap_days)

    if not schedule.epochs:
        logger.warning("retrain: no epochs to run (empty library?)")
        print("\nNo articles found in library. Nothing to retrain.")
        return None

    if dry_run:
        print_schedule(schedule)
        return schedule

    # Determine which epochs to run
    if epoch_range is not None:
        start, end = epoch_range
        selected = [e for e in schedule.epochs if start <= e.epoch_num <= end]
    else:
        selected = schedule.epochs

    if not selected:
        logger.warning("retrain: epoch_range %s matched no epochs", epoch_range)
        print(f"\nEpoch range {epoch_range} matched no epochs in the schedule.")
        return schedule

    print_schedule(schedule)

    # Note: reset_firn() must be called separately BEFORE retrain if a fresh
    # start is needed (followed by ingest_cached_articles to repopulate library).
    # retrain itself only processes existing unread articles — it never clears.

    # Snapshot unread set once for filtering
    unread_set = set(kb.list_unread())

    # Run each epoch
    total_start = time.monotonic()
    epochs_run = 0
    for epoch in selected:
        # Filter to only unread articles in this epoch
        unread_slugs = [s for s in epoch.article_slugs if s in unread_set]
        if not unread_slugs:
            print(
                f"  Epoch {epoch.epoch_num}/{len(schedule.epochs)} "
                f"[{epoch.simulated_date}] — all {epoch.article_count} articles "
                f"already processed, skipping"
            )
            continue

        epoch_start = time.monotonic()
        skipped = epoch.article_count - len(unread_slugs)
        skip_note = f" ({skipped} already processed)" if skipped else ""
        logger.info(
            "retrain: starting epoch %d/%d — date=%s, %d articles%s",
            epoch.epoch_num,
            len(schedule.epochs),
            epoch.simulated_date,
            len(unread_slugs),
            skip_note,
        )
        print(
            f"  Epoch {epoch.epoch_num}/{len(schedule.epochs)} "
            f"[{epoch.simulated_date}] — {len(unread_slugs)} articles{skip_note} ...",
            end=" ",
            flush=True,
        )

        # Generate historical macro pulse for this epoch's simulated date
        try:
            from src.sources.market.macro_pulse import generate_historical_macro_pulse

            pulse_result = generate_historical_macro_pulse(
                as_of_date=epoch.simulated_date, kb=kb,
            )
            if pulse_result.get("status") == "ok":
                pulse_slug = pulse_result["slug"]
                unread_slugs.append(pulse_slug)
                logger.info(
                    "retrain: epoch %d — macro pulse added: %s",
                    epoch.epoch_num, pulse_slug,
                )
            else:
                logger.warning(
                    "retrain: epoch %d — macro pulse skipped: %s",
                    epoch.epoch_num, pulse_result.get("reason", "unknown"),
                )
        except Exception as exc:
            logger.warning(
                "retrain: epoch %d — macro pulse failed (non-fatal): %s",
                epoch.epoch_num, exc,
            )

        # Generate historical market snapshot for this epoch's simulated date
        try:
            from src.sources.market.snapshot import generate_historical_market_snapshot_item

            snap_result = generate_historical_market_snapshot_item(
                as_of_date=epoch.simulated_date, kb=kb,
            )
            if snap_result.get("status") == "ok":
                snap_slug = snap_result["slug"]
                unread_slugs.append(snap_slug)
                logger.info(
                    "retrain: epoch %d — market snapshot added: %s",
                    epoch.epoch_num, snap_slug,
                )
            else:
                logger.warning(
                    "retrain: epoch %d — market snapshot skipped: %s",
                    epoch.epoch_num, snap_result.get("reason", "unknown"),
                )
        except Exception as exc:
            logger.warning(
                "retrain: epoch %d — market snapshot failed (non-fatal): %s",
                epoch.epoch_num, exc,
            )

        try:
            await run_digest(
                retrain_slugs=unread_slugs,
                simulated_date=epoch.simulated_date,
                filter_low_trust=False,
                kb=kb,
            )
            # Remove processed slugs from unread_set
            for s in unread_slugs:
                unread_set.discard(s)
            elapsed = time.monotonic() - epoch_start
            logger.info("retrain: epoch %d complete in %.1fs", epoch.epoch_num, elapsed)
            print(f"done ({elapsed:.1f}s)")
            epochs_run += 1
        except Exception as exc:
            elapsed = time.monotonic() - epoch_start
            logger.error(
                "retrain: epoch %d failed after %.1fs: %s",
                epoch.epoch_num,
                elapsed,
                exc,
                exc_info=True,
            )
            print(f"FAILED ({elapsed:.1f}s) — {exc}")
            continue

    total_elapsed = time.monotonic() - total_start
    print(
        f"\n  Retrain complete: {epochs_run} epochs in {total_elapsed:.1f}s "
        f"({total_elapsed / 60:.1f} min)"
    )
    logger.info(
        "retrain: finished %d epochs in %.1fs",
        epochs_run,
        total_elapsed,
    )

    return schedule


# ---------------------------------------------------------------------------
# KB backup and clear helpers
# ---------------------------------------------------------------------------

def reset_firn(kb: KnowledgeBase) -> Path:
    """Full Firn state reset: backup everything, then clear for fresh retrain.

    Backs up to ``data/meta/kb_backup_{timestamp}/``, then clears:
      - ``firn/notebook/`` — themes, events, sectors, stocks, core_mind, history
      - ``firn/library/`` — unread and read articles
      - ``firn/archive/`` — archived KB notes
      - ``logs/`` — execution logs (accretion history)

    Preserves:
      - ``firn/agent_principles.md``
      - ``firn/user_context/``
      - ``data/`` — sources, meta, JSON stores (never cleared)

    Returns the backup directory path.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = kb.data_root / "meta" / f"kb_backup_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # --- Backup phase ---

    # Notebook
    obj_dir = kb.root / "notebook"
    if obj_dir.is_dir():
        shutil.copytree(obj_dir, backup_dir / "notebook")
        logger.info("retrain: backed up notebook")

    # Library
    lib_dir = kb.root / "library"
    if lib_dir.is_dir():
        shutil.copytree(lib_dir, backup_dir / "library")
        logger.info("retrain: backed up library")

    # Archive
    archive_dir = kb.root / "archive"
    if archive_dir.is_dir() and any(archive_dir.iterdir()):
        shutil.copytree(archive_dir, backup_dir / "archive")
        logger.info("retrain: backed up archive")

    # Execution logs
    logs_dir = kb.root.parent / "logs"
    if logs_dir.is_dir() and any(logs_dir.iterdir()):
        shutil.move(str(logs_dir), str(backup_dir / "logs"))
        logs_dir.mkdir()
        logger.info("retrain: backed up logs")

    # --- Clear phase ---

    # Notebook: clear content dirs, remove files
    dirs_to_clear = ["themes", "events", "sectors", "stocks", "core_mind_history"]
    for d in dirs_to_clear:
        target = obj_dir / d
        if target.is_dir():
            shutil.rmtree(target)
            target.mkdir()

    for f in ["core_mind.md", "latest_report.md"]:
        p = obj_dir / f
        if p.is_file():
            p.unlink()

    rpt_hist = obj_dir / "report_history"
    if rpt_hist.is_dir():
        shutil.rmtree(rpt_hist)
        rpt_hist.mkdir()

    # Library: clear unread and read (preserve .gitkeep)
    for subdir in ["unread", "read"]:
        target = lib_dir / subdir
        if target.is_dir():
            for item in target.iterdir():
                if item.name == ".gitkeep":
                    continue
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)

    # Archive: clear
    if archive_dir.is_dir():
        for item in archive_dir.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)

    logger.info("retrain: Firn state reset complete (backup at %s)", backup_dir)
    return backup_dir


# ---------------------------------------------------------------------------
# Schedule printing
# ---------------------------------------------------------------------------

def print_schedule(schedule: RetrainSchedule) -> None:
    """Print a human-readable schedule table to stdout."""
    print(f"\n{'=' * 70}")
    print("  Retrain Schedule")
    print(f"  Date range: {schedule.date_range[0]} -> {schedule.date_range[1]}")
    print(f"  Total: {schedule.total_articles} articles in {len(schedule.epochs)} epochs")
    print(f"  Total chars: {schedule.total_chars:,}")
    print(f"{'=' * 70}\n")

    print(f"  {'Epoch':>5} | {'Simulated Date':>14} | {'Articles':>8} | {'Chars':>10} | Covers")
    print(f"  {'-' * 5}-+-{'-' * 14}-+-{'-' * 8}-+-{'-' * 10}-+-{'-' * 20}")

    for e in schedule.epochs:
        if len(e.covers_dates) > 1:
            covers_str = f"{e.covers_dates[0]}..{e.covers_dates[-1]}"
        elif e.covers_dates:
            covers_str = e.covers_dates[0]
        else:
            covers_str = "unknown"
        print(
            f"  {e.epoch_num:>5} | {e.simulated_date:>14} | "
            f"{e.article_count:>8} | {e.total_chars:>10,} | {covers_str}"
        )

    print()
