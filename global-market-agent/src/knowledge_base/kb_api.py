"""Knowledge Base API — thin file I/O wrappers for the agent cognitive architecture."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

_SNAPSHOT_ID_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}_[a-f0-9]{8}$")


def _format_age(iso_ts: str | None, now: datetime) -> str:
    """Format an ISO timestamp as a human-readable relative age."""
    if not iso_ts:
        return "unknown"
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        total_seconds = int((now - dt).total_seconds())
        if total_seconds < 60:
            return "just now"
        if total_seconds < 3600:
            return f"{total_seconds // 60}m ago"
        if total_seconds < 86400:
            return f"{total_seconds // 3600}h ago"
        return f"{total_seconds // 86400}d ago"
    except (ValueError, TypeError):
        return "unknown"


class KnowledgeBase:
    """Read/write interface for the agent's file-based knowledge base.

    The KB stores the agent's cognitive state: principles, source trust registry,
    notebook (core mind, themes, events, stocks), user context, and
    a library of articles (unread and read).

    All paths use ``pathlib.Path``.  Read methods return ``str | None`` (None when
    the target file does not exist).  Write methods create parent directories
    automatically.
    """

    # Subdirectory layout under firn/ (Firn's clearable cognitive state)
    _FIRN_DIRS: list[str] = [
        "notebook",
        "notebook/themes",
        "notebook/events",
        "notebook/sectors",
        "notebook/stocks",
        "notebook/core_mind_history",
        "user_context",
        "user_context/forwarded",
        "library/unread",
        "library/read",
        "archive",
    ]

    # Subdirectory layout under data/ (persistent, never cleared)
    _DATA_DIRS: list[str] = [
        "sources",
        "meta",
    ]

    def __init__(self, project_root: Path | None = None, *, kb_root: Path | None = None) -> None:
        if kb_root is not None:
            # Legacy / test compat: kb_root is both firn root and data root
            # (co-located to avoid cross-test pollution via shared parent dirs)
            self.root = kb_root
            self.data_root = kb_root
        elif project_root is not None:
            self.root = project_root / "firn"
            self.data_root = project_root / "data"
        else:
            _project = Path(__file__).resolve().parents[2]  # global-market-agent/
            self.root = _project / "firn"
            self.data_root = _project / "data"

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def ensure_structure(self) -> None:
        """Create the full directory tree if any part is missing."""
        for d in self._FIRN_DIRS:
            (self.root / d).mkdir(parents=True, exist_ok=True)
        for d in self._DATA_DIRS:
            (self.data_root / d).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------

    def _read_text(self, path: Path) -> str | None:
        if path.is_file():
            return path.read_text(encoding="utf-8")
        return None

    def _write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _list_md_slugs(self, directory: Path) -> list[str]:
        """Return sorted slug names (without .md) of all markdown files in *directory*."""
        if not directory.is_dir():
            return []
        return sorted(p.stem for p in directory.iterdir() if p.suffix == ".md")

    # ------------------------------------------------------------------
    # Principles (read-only)
    # ------------------------------------------------------------------

    def read_principles(self) -> str:
        """Return the agent investment principles (always exists)."""
        path = self.root / "agent_principles.md"
        text = self._read_text(path)
        if text is None:
            raise FileNotFoundError(f"Principles file not found: {path}")
        return text

    # ------------------------------------------------------------------
    # Source Registry
    # ------------------------------------------------------------------

    def read_source_registry(self) -> dict:
        """Parse and return the full source registry YAML."""
        path = self.data_root / "sources" / "source_registry.yaml"
        text = self._read_text(path)
        if text is None:
            # Legacy fallback: root/source_registry.yaml (tests using kb_root)
            text = self._read_text(self.root / "source_registry.yaml")
        if text is None:
            raise FileNotFoundError(f"Source registry not found: {path}")
        return yaml.safe_load(text)

    def get_source_info(self, source_name: str) -> dict | None:
        """Return the config dict for a single source, or None."""
        registry = self.read_source_registry()
        return registry.get("sources", {}).get(source_name)

    def get_source_tier(self, source_name: str) -> int | None:
        """Return the effective trust tier (1-5) for a source, or None if unknown.

        Supports dual-tier format: agent_tier takes precedence over human_tier.
        Also supports legacy single 'tier' field for backward compatibility.
        """
        info = self.get_source_info(source_name)
        if info is None:
            return None
        agent_tier = info.get("agent_tier")
        if agent_tier is not None:
            return agent_tier
        human_tier = info.get("human_tier")
        if human_tier is not None:
            return human_tier
        return info.get("tier")  # legacy fallback

    # ------------------------------------------------------------------
    # Notebook — Core
    # ------------------------------------------------------------------

    def read_core_mind(self) -> str | None:
        return self._read_text(self.root / "notebook" / "core_mind.md")

    def write_core_mind(self, content: str) -> None:
        self._write_text(self.root / "notebook" / "core_mind.md", content)

    # ------------------------------------------------------------------
    # Notebook — Core Mind History (snapshots)
    # ------------------------------------------------------------------

    def snapshot_core_mind(self, exec_id: str) -> str | None:
        """Save current core_mind.md as a historical snapshot.

        Storage: notebook/core_mind_history/{date}_{exec_id[:8]}.md
        Index:   notebook/core_mind_history/index.json

        Returns snapshot_id or None if core_mind doesn't exist.
        """
        content = self.read_core_mind()
        if content is None:
            return None

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        short_id = exec_id[:8]
        snapshot_id = f"{date_str}_{short_id}"

        history_dir = self.root / "notebook" / "core_mind_history"
        history_dir.mkdir(parents=True, exist_ok=True)

        # Write snapshot file
        self._write_text(history_dir / f"{snapshot_id}.md", content)

        # Update index
        index_path = history_dir / "index.json"
        index: list[dict] = []
        if index_path.is_file():
            try:
                index = json.loads(index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                index = []

        entry = {
            "id": snapshot_id,
            "date": date_str,
            "exec_id_short": short_id,
            "char_count": len(content),
        }
        index.append(entry)
        self._write_text(
            index_path,
            json.dumps(index, indent=2, ensure_ascii=False) + "\n",
        )
        return snapshot_id

    def create_snapshot(self, execution_dir: Path, snapshot_type: str = "before") -> dict:
        """Create a snapshot of the KB notebook contents for execution archive.

        Captures notebook files (core_mind, themes, events, sectors, stock theses)
        but excludes reports and report_history to keep snapshots small (~50KB).

        Args:
            execution_dir: Path to the execution directory (logs/{exec_id}/).
            snapshot_type: Label for the snapshot (e.g. "before", "after", "context").

        Returns:
            Snapshot dict with file contents.
        """
        obj_dir = self.root / "notebook"
        files: dict[str, str] = {}
        total_chars = 0
        skip_dirs = {"core_mind_history", "report_history"}

        if obj_dir.is_dir():
            for md_file in sorted(obj_dir.rglob("*.md")):
                # Skip history directories and report files
                parts = md_file.relative_to(obj_dir).parts
                if any(d in skip_dirs for d in parts):
                    continue
                if md_file.name == "latest_report.md":
                    continue
                try:
                    content = md_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                rel_path = str(md_file.relative_to(self.root))
                files[rel_path] = content
                total_chars += len(content)

        snapshot = {
            "snapshot_type": snapshot_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "files": files,
            "file_count": len(files),
            "total_chars": total_chars,
        }

        snapshots_dir = execution_dir / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        (snapshots_dir / f"kb_{snapshot_type}.json").write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return snapshot

    def list_core_mind_snapshots(self) -> list[dict]:
        """Read core_mind_history/index.json -> list of snapshot metadata."""
        index_path = self.root / "notebook" / "core_mind_history" / "index.json"
        if not index_path.is_file():
            return []
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def read_core_mind_snapshot(self, snapshot_id: str) -> str | None:
        """Read a specific snapshot file by its snapshot_id."""
        if not _SNAPSHOT_ID_RE.match(snapshot_id):
            return None
        path = self.root / "notebook" / "core_mind_history" / f"{snapshot_id}.md"
        return self._read_text(path)

    # ------------------------------------------------------------------
    # Notebook — Themes
    # ------------------------------------------------------------------

    def list_themes(self) -> list[str]:
        return self._list_md_slugs(self.root / "notebook" / "themes")

    def read_theme(self, slug: str) -> str | None:
        return self._read_text(self.root / "notebook" / "themes" / f"{slug}.md")

    def write_theme(self, slug: str, content: str) -> None:
        self._write_text(self.root / "notebook" / "themes" / f"{slug}.md", content)

    def archive_theme(self, slug: str) -> None:
        """Move a theme file from themes/ to archive/."""
        src = self.root / "notebook" / "themes" / f"{slug}.md"
        if not src.is_file():
            raise FileNotFoundError(f"Theme not found: {src}")
        dest_dir = self.root / "archive"
        dest_dir.mkdir(parents=True, exist_ok=True)
        src.rename(dest_dir / f"{slug}.md")

    # ------------------------------------------------------------------
    # Notebook — Events
    # ------------------------------------------------------------------

    def list_events(self) -> list[str]:
        return self._list_md_slugs(self.root / "notebook" / "events")

    def read_event(self, slug: str) -> str | None:
        return self._read_text(self.root / "notebook" / "events" / f"{slug}.md")

    def write_event(self, slug: str, content: str) -> None:
        self._write_text(self.root / "notebook" / "events" / f"{slug}.md", content)

    # ------------------------------------------------------------------
    # Notebook — Sectors
    # ------------------------------------------------------------------

    def read_sector(self, slug: str) -> str | None:
        return self._read_text(self.root / "notebook" / "sectors" / f"{slug}.md")

    def write_sector(self, slug: str, content: str) -> None:
        self._write_text(self.root / "notebook" / "sectors" / f"{slug}.md", content)

    # ------------------------------------------------------------------
    # Notebook — Stocks
    # ------------------------------------------------------------------

    def list_stocks(self) -> list[str]:
        """Return sorted ticker names that have directories under stocks/."""
        stocks_dir = self.root / "notebook" / "stocks"
        if not stocks_dir.is_dir():
            return []
        return sorted(d.name for d in stocks_dir.iterdir() if d.is_dir())

    def list_stock_files(self, ticker: str) -> list[str]:
        """Return sorted filenames (without .md) under stocks/{TICKER}/."""
        stock_dir = self.root / "notebook" / "stocks" / ticker.upper()
        return self._list_md_slugs(stock_dir)

    def read_stock(self, ticker: str, filename: str) -> str | None:
        return self._read_text(
            self.root / "notebook" / "stocks" / ticker.upper() / f"{filename}.md"
        )

    def write_stock(self, ticker: str, filename: str, content: str) -> None:
        self._write_text(
            self.root / "notebook" / "stocks" / ticker.upper() / f"{filename}.md",
            content,
        )

    # ------------------------------------------------------------------
    # User Context
    # ------------------------------------------------------------------

    def read_user_views(self) -> str | None:
        return self._read_text(self.root / "user_context" / "user_views.md")

    def write_user_views(self, content: str) -> None:
        self._write_text(self.root / "user_context" / "user_views.md", content)

    def read_divergences(self) -> str | None:
        return self._read_text(self.root / "user_context" / "divergences.md")

    def write_divergences(self, content: str) -> None:
        self._write_text(self.root / "user_context" / "divergences.md", content)

    def list_forwarded(self) -> list[str]:
        return self._list_md_slugs(self.root / "user_context" / "forwarded")

    def read_forwarded(self, slug: str) -> str | None:
        return self._read_text(self.root / "user_context" / "forwarded" / f"{slug}.md")

    def write_forwarded(self, slug: str, content: str) -> None:
        self._write_text(self.root / "user_context" / "forwarded" / f"{slug}.md", content)

    # ------------------------------------------------------------------
    # Library (unread / read articles)
    # ------------------------------------------------------------------

    def add_unread(self, slug: str, content: str) -> None:
        self._write_text(self.root / "library" / "unread" / f"{slug}.md", content)

    def list_unread(self) -> list[str]:
        return self._list_md_slugs(self.root / "library" / "unread")

    def read_unread(self, slug: str) -> str | None:
        return self._read_text(self.root / "library" / "unread" / f"{slug}.md")

    def mark_read(self, slug: str) -> None:
        """Move an article from library/unread/ to library/read/."""
        src = self.root / "library" / "unread" / f"{slug}.md"
        if not src.is_file():
            raise FileNotFoundError(f"Unread item not found: {src}")
        dest_dir = self.root / "library" / "read"
        dest_dir.mkdir(parents=True, exist_ok=True)
        src.rename(dest_dir / f"{slug}.md")

    def list_read(self) -> list[str]:
        """Return sorted slug names of all read (library) articles."""
        return self._list_md_slugs(self.root / "library" / "read")

    def read_article(self, slug: str) -> str | None:
        """Read a processed article from the library."""
        return self._read_text(self.root / "library" / "read" / f"{slug}.md")

    def list_all_library(self) -> list[str]:
        """Return sorted slugs of ALL library articles (read + unread)."""
        read = set(self._list_md_slugs(self.root / "library" / "read"))
        unread = set(self._list_md_slugs(self.root / "library" / "unread"))
        return sorted(read | unread)

    # ------------------------------------------------------------------
    # Report rotation & section helpers
    # ------------------------------------------------------------------

    def save_report_with_rotation(self, ticker: str, report: str) -> str:
        """Save report and rotate old one to history.

        1. If stocks/{TICKER}/latest_report.md exists, move it to
           stocks/{TICKER}/report_history/{date}.md
        2. Write the new latest_report.md
        3. Return the new file path as a string.
        """
        ticker = ticker.upper()
        stock_dir = self.root / "notebook" / "stocks" / ticker
        latest = stock_dir / "latest_report.md"

        if latest.is_file():
            history_dir = stock_dir / "report_history"
            history_dir.mkdir(parents=True, exist_ok=True)
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            dest = history_dir / f"{date_str}.md"
            # If same-day rotation already happened, overwrite the history copy
            latest.rename(dest)

        self._write_text(latest, report)
        return str(latest)

    def list_sectors(self) -> list[str]:
        """Return sorted slug names of all .md files in sectors/."""
        return self._list_md_slugs(self.root / "notebook" / "sectors")

    def archive_file(self, section_dir: str, slug: str) -> None:
        """Move a file from any section to archive/ with date prefix.

        *section_dir* is relative to ``kb.root``, e.g. ``"notebook/themes"``.
        Destination: ``archive/{date}_{slug}.md``.
        """
        src = self.root / section_dir / f"{slug}.md"
        if not src.is_file():
            raise FileNotFoundError(f"File not found: {src}")
        dest_dir = self.root / "archive"
        dest_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        src.rename(dest_dir / f"{date_str}_{slug}.md")

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------

    def get_last_updated(self) -> dict:
        """Return the parsed last_updated.json (empty dict if missing)."""
        path = self.data_root / "meta" / "last_updated.json"
        text = self._read_text(path)
        if text is None:
            return {}
        return json.loads(text)

    def set_last_updated(
        self,
        source: str,
        *,
        new_count: int = 0,
        summary: str = "",
    ) -> None:
        """Record freshness info for *source*.

        Args:
            source: Source identifier (e.g. "wechat_ExampleAnalyst").
            new_count: Number of new items found this check.  When > 0,
                       ``last_new_data`` is set to now; otherwise the
                       previous value is preserved.
            summary: One-line status description.
        """
        now = datetime.now(timezone.utc).isoformat()
        data = self.get_last_updated()

        # Preserve last_new_data from previous record when no new data
        prev = data.get(source)
        prev_last_new = None
        if isinstance(prev, dict):
            prev_last_new = prev.get("last_new_data")
        elif isinstance(prev, str):
            prev_last_new = prev  # legacy format migration

        entry = {
            "last_checked": now,
            "last_new_data": now if new_count > 0 else prev_last_new,
            "new_count": new_count,
            "summary": summary,
        }
        data[source] = entry
        self._write_text(
            self.data_root / "meta" / "last_updated.json",
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        )

    def build_source_descriptions(self) -> str:
        """Build data source descriptions for the digest system prompt.

        Reads ``prompt_description`` fields from source_registry.yaml.
        Only sources with this field are included. Returns empty string
        if no descriptions are found (e.g. registry missing).
        """
        try:
            registry = self.read_source_registry()
        except FileNotFoundError:
            return ""

        lines: list[str] = []
        for name, info in registry.get("sources", {}).items():
            desc = info.get("prompt_description", "").strip()
            if not desc:
                continue
            tier = info.get("human_tier", "?")
            lines.append(f"**{name}** — Tier {tier}. {desc}")

        if not lines:
            return ""
        return "\n\n".join(lines)

    def build_source_status(self) -> str:
        """Generate human-readable source freshness summary."""
        data = self.get_last_updated()
        if not data:
            return "No source freshness data recorded yet."

        now = datetime.now(timezone.utc)
        lines: list[str] = []

        for source, info in sorted(data.items()):
            if isinstance(info, str):
                # Legacy format: bare timestamp string
                lines.append(f"  {source}: last updated {info}")
                continue

            checked = info.get("last_checked")
            last_new = info.get("last_new_data")
            new_count = info.get("new_count", 0)
            summary = info.get("summary", "")

            checked_ago = _format_age(checked, now) if checked else "never"

            if new_count > 0:
                detail = f"{new_count} new"
                if summary:
                    detail += f" ({summary})"
                detail += f" — checked {checked_ago}"
            elif last_new:
                new_ago = _format_age(last_new, now)
                detail = f"no new data — checked {checked_ago}, last new {new_ago}"
            else:
                detail = f"no data yet — checked {checked_ago}"

            lines.append(f"  {source}: {detail}")

        return "Source Freshness:\n" + "\n".join(lines)

    def append_log(self, entry: str) -> None:
        """Append a timestamped line to meta/update_log.md."""
        path = self.data_root / "meta" / "update_log.md"
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        line = f"- [{ts}] {entry}\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
