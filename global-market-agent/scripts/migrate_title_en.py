"""
Migration script to add `title_en` (English translation) to:
  1. Library files' YAML frontmatter (default)
  2. JSON store files in data/sources/ (--json-stores)

Usage:
    cd global-market-agent
    uv run python scripts/migrate_title_en.py --dry-run            # library preview
    uv run python scripts/migrate_title_en.py                       # library migration
    uv run python scripts/migrate_title_en.py --json-stores --dry-run  # JSON stores preview
    uv run python scripts/migrate_title_en.py --json-stores            # JSON stores migration
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEEPL_URL = "https://api-free.deepl.com/v2/translate"
BATCH_SIZE = 50
BATCH_DELAY = 1.0  # seconds between API batches

_PROJECT = Path(__file__).resolve().parents[1]
FIRN_ROOT = _PROJECT / "firn"
DATA_ROOT = _PROJECT / "data"
LIBRARY_DIRS = [
    FIRN_ROOT / "library" / "unread",
    FIRN_ROOT / "library" / "read",
]
SOURCES_DIR = DATA_ROOT / "sources"

# Frontmatter delimiter
FM_DELIM = "---"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_cjk(text: str) -> bool:
    """Return True if *text* contains any CJK Unified Ideograph."""
    return any("\u4e00" <= c <= "\u9fff" for c in text)


def _parse_frontmatter(content: str) -> tuple[dict[str, str], int, int]:
    """Parse YAML frontmatter between ``---`` markers.

    Returns:
        (metadata_dict, fm_start_line_idx, fm_end_line_idx)
        where the indices are *line numbers* (0-based) of the opening and
        closing ``---`` lines.  Returns ({}, -1, -1) if no frontmatter found.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != FM_DELIM:
        return {}, -1, -1

    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == FM_DELIM:
            end_idx = i
            break

    if end_idx == -1:
        return {}, -1, -1

    metadata: dict[str, str] = {}
    for line in lines[1:end_idx]:
        m = re.match(r"^(\w[\w_]*):\s*(.*)$", line)
        if m:
            metadata[m.group(1)] = m.group(2).strip()

    return metadata, 0, end_idx


def _find_title_line_idx(content: str, fm_end: int) -> int:
    """Return the 0-based line index of the ``title:`` line in the frontmatter."""
    lines = content.split("\n")
    for i in range(1, fm_end):
        if lines[i].startswith("title:"):
            return i
    return -1


def _insert_title_en(content: str, title_en: str) -> str:
    """Insert a ``title_en:`` line right after the ``title:`` line."""
    lines = content.split("\n")
    _, _, fm_end = _parse_frontmatter(content)
    title_idx = _find_title_line_idx(content, fm_end)
    if title_idx == -1:
        return content  # safety: no title line found

    new_line = f"title_en: {title_en}"
    lines.insert(title_idx + 1, new_line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DeepL translation
# ---------------------------------------------------------------------------


def _translate_batch(titles: list[str], api_key: str) -> list[str]:
    """Translate a batch of titles via DeepL. Returns list of translated strings.

    On failure, returns empty strings for the entire batch so the caller can
    skip gracefully.
    """
    try:
        resp = httpx.post(
            DEEPL_URL,
            headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
            json={"text": titles, "source_lang": "ZH", "target_lang": "EN"},
            timeout=30.0,
        )
        if resp.status_code != 200:
            print(
                f"[migrate] WARNING: DeepL returned status {resp.status_code} — skipping batch",
                file=sys.stderr,
            )
            return [""] * len(titles)

        translations = resp.json().get("translations", [])
        return [t.get("text", "") for t in translations]

    except Exception as exc:
        print(
            f"[migrate] WARNING: DeepL request failed ({exc}) — skipping batch",
            file=sys.stderr,
        )
        return [""] * len(titles)


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------


def _collect_files() -> list[Path]:
    """Return all .md files in the library directories."""
    files: list[Path] = []
    for d in LIBRARY_DIRS:
        if d.is_dir():
            dir_files = sorted(d.glob("*.md"))
            label = d.relative_to(KB_ROOT)
            print(f"[migrate] Scanning {label}/... found {len(dir_files)} files")
            files.extend(dir_files)
        else:
            label = d.relative_to(KB_ROOT)
            print(f"[migrate] Scanning {label}/... directory not found, skipping")
    return files


def _filter_files(files: list[Path]) -> list[tuple[Path, str, str]]:
    """Filter to files needing title_en translation.

    Returns list of (path, file_content, title_value) tuples.
    """
    needs_translation: list[tuple[Path, str, str]] = []
    skipped = 0

    for fpath in files:
        content = fpath.read_text(encoding="utf-8")
        meta, _, _ = _parse_frontmatter(content)

        # Skip: already has title_en
        if "title_en" in meta:
            skipped += 1
            continue

        title = meta.get("title", "")

        # Skip: no title field
        if not title:
            skipped += 1
            continue

        # Skip: no CJK characters (English sources)
        if not _has_cjk(title):
            skipped += 1
            continue

        needs_translation.append((fpath, content, title))

    print(
        f"[migrate] {len(needs_translation)} files need title_en translation "
        f"({skipped} skipped: already have title_en or no CJK)"
    )
    return needs_translation


def _run_dry_run(items: list[tuple[Path, str, str]]) -> None:
    """Print what would happen without making changes."""
    print(f"[DRY RUN] Would translate {len(items)} titles and update files")
    # Show up to 5 samples
    for _, _, title in items[:5]:
        print(f'[DRY RUN] Sample: "{title}" -> (would translate)')


def _run_migration(items: list[tuple[Path, str, str]], api_key: str) -> None:
    """Translate titles in batches and update files."""
    total = len(items)
    num_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    updated = 0
    skipped_translation = 0

    for batch_idx in range(num_batches):
        start = batch_idx * BATCH_SIZE
        end = min(start + BATCH_SIZE, total)
        batch = items[start:end]

        print(f"[migrate] Translating batch {batch_idx + 1}/{num_batches} ({len(batch)} titles)...")

        titles = [title for _, _, title in batch]
        translations = _translate_batch(titles, api_key)

        for (fpath, content, _title), translated in zip(batch, translations):
            if not translated:
                skipped_translation += 1
                continue
            new_content = _insert_title_en(content, translated)
            fpath.write_text(new_content, encoding="utf-8")
            updated += 1

        # Delay between batches (not after the last one)
        if batch_idx < num_batches - 1:
            time.sleep(BATCH_DELAY)

    print(f"[migrate] Done. {updated} files updated.", end="")
    if skipped_translation:
        print(f" ({skipped_translation} failed translations skipped.)", end="")
    print()


# ---------------------------------------------------------------------------
# JSON store migration
# ---------------------------------------------------------------------------


def _construct_store_title(entry: dict, store_type: str) -> str:
    """Construct the full inbox title for a JSON store entry.

    Matches the exact title format used by the ingest pipeline:
      - WeChat: "[{account}] {title}"
      - Bilibili dynamic: "[{author_name}] 动态 {date}"
      - Bilibili subtitle: "[{author_name}] {title}"
    """
    entry_type = entry.get("type", "")

    if store_type == "wechat":
        account = entry.get("account", "")
        title = entry.get("title", "")
        return f"[{account}] {title}" if account and title else title

    if entry_type == "dynamic":
        author = entry.get("author_name", "")
        ts = entry.get("timestamp", 0)
        pub_date = (
            datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            if ts
            else "unknown"
        )
        return f"[{author}] 动态 {pub_date}"

    if entry_type == "video_subtitle":
        author = entry.get("author_name", "")
        title = entry.get("title", "")
        return f"[{author}] {title}"

    return ""


def _collect_json_store_items() -> list[tuple[Path, str, str, str]]:
    """Scan JSON store files and collect entries needing title_en.

    Returns list of (json_path, entry_key, constructed_title, store_type) tuples.
    """
    if not SOURCES_DIR.is_dir():
        print(f"[migrate] Sources dir not found: {SOURCES_DIR}")
        return []

    items: list[tuple[Path, str, str, str]] = []
    total_entries = 0
    skipped = 0

    for json_path in sorted(SOURCES_DIR.glob("*.json")):
        # Determine store type from filename
        fname = json_path.name
        if fname.endswith("_articles.json"):
            store_type = "wechat"
        elif fname.endswith("_bilibili.json"):
            store_type = "bilibili"
        else:
            continue

        data = json.loads(json_path.read_text(encoding="utf-8"))
        print(f"[migrate] Scanning {fname}... {len(data)} entries")
        total_entries += len(data)

        for entry_key, entry in data.items():
            # Skip entries that already have title_en
            if entry.get("title_en"):
                skipped += 1
                continue

            # Skip non-content bilibili entries (e.g. video_no_subtitle)
            if store_type == "bilibili":
                etype = entry.get("type", "")
                if etype not in ("dynamic", "video_subtitle"):
                    skipped += 1
                    continue

            constructed_title = _construct_store_title(entry, store_type)
            if not constructed_title:
                skipped += 1
                continue

            # Skip if no CJK characters
            if not _has_cjk(constructed_title):
                skipped += 1
                continue

            items.append((json_path, entry_key, constructed_title, store_type))

    print(
        f"[migrate] {len(items)} store entries need title_en translation "
        f"({skipped} skipped, {total_entries} total across all stores)"
    )
    return items


def _run_json_stores_dry_run(items: list[tuple[Path, str, str, str]]) -> None:
    """Preview JSON store migration without changes."""
    print(f"[DRY RUN] Would translate {len(items)} store entry titles")
    for _, entry_key, title, store_type in items[:10]:
        print(f'[DRY RUN]   [{store_type}] "{title}"')


def _run_json_stores_migration(
    items: list[tuple[Path, str, str, str]], api_key: str
) -> None:
    """Translate titles in batches and write title_en back into JSON stores."""
    total = len(items)
    num_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    updated = 0
    skipped_translation = 0

    # Group results by file path so we can batch-update each JSON file
    # Key: json_path -> list of (entry_key, title_en)
    file_updates: dict[Path, list[tuple[str, str]]] = {}

    for batch_idx in range(num_batches):
        start = batch_idx * BATCH_SIZE
        end = min(start + BATCH_SIZE, total)
        batch = items[start:end]

        print(f"[migrate] Translating batch {batch_idx + 1}/{num_batches} ({len(batch)} titles)...")

        titles = [title for _, _, title, _ in batch]
        translations = _translate_batch(titles, api_key)

        for (json_path, entry_key, _title, _st), translated in zip(batch, translations):
            if not translated:
                skipped_translation += 1
                continue
            file_updates.setdefault(json_path, []).append((entry_key, translated))
            updated += 1

        # Delay between batches (not after the last one)
        if batch_idx < num_batches - 1:
            time.sleep(BATCH_DELAY)

    # Write updates back to each JSON file
    for json_path, updates in file_updates.items():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        for entry_key, title_en in updates:
            if entry_key in data:
                data[entry_key]["title_en"] = title_en
        json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[migrate] Updated {json_path.name}: {len(updates)} entries")

    print(f"[migrate] Done. {updated} store entries updated.", end="")
    if skipped_translation:
        print(f" ({skipped_translation} failed translations skipped.)", end="")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add title_en (English translation) to library files and/or JSON stores."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing files or calling DeepL.",
    )
    parser.add_argument(
        "--json-stores",
        action="store_true",
        help="Migrate JSON store files in data/sources/ (instead of library files).",
    )
    args = parser.parse_args()

    # Check API key (not needed for dry-run, but warn)
    api_key = os.environ.get("DEEPL_API_KEY", "")
    if not args.dry_run and not api_key:
        print(
            "[migrate] ERROR: DEEPL_API_KEY environment variable is not set.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.json_stores:
        # JSON store migration
        store_items = _collect_json_store_items()
        if not store_items:
            print("[migrate] JSON stores: nothing to do.")
        elif args.dry_run:
            _run_json_stores_dry_run(store_items)
        else:
            _run_json_stores_migration(store_items, api_key)
    else:
        # Library file migration (original behavior)
        files = _collect_files()
        items = _filter_files(files)
        if not items:
            print("[migrate] Nothing to do.")
        elif args.dry_run:
            _run_dry_run(items)
        else:
            _run_migration(items, api_key)


if __name__ == "__main__":
    main()
