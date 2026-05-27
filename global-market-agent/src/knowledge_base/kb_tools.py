"""KB Tool Set — per-invocation LangChain tools wrapping KnowledgeBase.

Each KBToolSet instance owns its own read_tracker state, preventing
cross-invocation leakage (SQU M1/M2).

Tools use the closure pattern because LangChain's @tool decorator does
not work on instance methods.
"""

from __future__ import annotations

import difflib
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.tools import tool

from src.knowledge_base.kb_api import KnowledgeBase
from src.utils.event_log import log_event

# ---------------------------------------------------------------------------
# Section topology
# ---------------------------------------------------------------------------

SECTION_MAP: dict[str, str] = {
    # Layer 2: Agent's notebook (read-write)
    "core_mind": "notebook/core_mind.md",
    "themes": "notebook/themes/",
    "events": "notebook/events/",
    "sectors": "notebook/sectors/",
    "stocks": "notebook/stocks/",
    # Layer 1: Raw data warehouse (read-only)
    "user_views": "user_context/user_views.md",
    "forwarded": "user_context/forwarded/",
    "inbox": "library/unread/",
    "library": "library/read/",
    # Meta (read-only) — resolved via data_root, not firn root
    "digest_history": "meta/digest_sessions.md",
}

WRITABLE_SECTIONS: set[str] = {"core_mind", "themes", "events", "sectors", "stocks"}
READ_ONLY_SECTIONS: set[str] = {"inbox", "forwarded", "user_views", "library", "digest_history"}

# Single-file sections (slug is ignored during path resolution)
_SINGLE_FILE_SECTIONS: set[str] = {"core_mind", "user_views", "digest_history"}


class KBToolSet:
    """Per-invocation tool set wrapping :class:`KnowledgeBase`.

    All 10 tools are created as closures in ``__init__`` so they
    capture ``self`` (the *toolset* instance) without requiring
    LangChain to call bound methods.

    Usage::

        ts = KBToolSet()
        tools = ts.get_tools()            # all 10
        tools = ts.get_tools_by_names(["kb_read", "kb_list"])  # subset
    """

    _MAX_READ_CHARS: int = 50_000
    _MAX_SEARCH_CHARS: int = 3000
    _MAX_SEARCH_RESULTS: int = 10

    def __init__(self, kb: KnowledgeBase | None = None) -> None:
        self.kb = kb or KnowledgeBase()
        self.read_tracker: set[str] = set()
        self.event_sid: str = ""        # set by CoreAgent before run
        self.execution_id: str = ""     # set by CoreAgent before run

        # Alias for closures
        toolset = self

        # ---------------------------------------------------------------
        # READ tools
        # ---------------------------------------------------------------

        @tool
        def kb_list(section: str) -> str:
            """List files in a KB section.

            Args:
                section: One of core_mind, themes, events, sectors, stocks,
                         user_views, forwarded, inbox, library.

            Returns:
                Numbered list of file slugs, or error if section unknown.

            Examples:
                kb_list("themes")
                kb_list("stocks")
                kb_list("inbox")
            """
            if section not in SECTION_MAP:
                return f"Unknown section: {section}. Valid: {', '.join(sorted(SECTION_MAP))}"

            if section in _SINGLE_FILE_SECTIONS:
                rel = SECTION_MAP[section]
                path = toolset._section_root(section) / rel
                if path.is_file():
                    return f"1. {Path(rel).stem} (single file)"
                return f"{section}: file does not exist yet."

            dir_path = toolset._section_root(section) / SECTION_MAP[section]
            if not dir_path.is_dir():
                return f"{section}: directory does not exist."

            slugs = sorted(
                str(p.relative_to(dir_path).with_suffix(""))
                for p in dir_path.rglob("*.md")
                if p.is_file()
            )
            if not slugs:
                return f"{section}: (empty)"

            lines = [f"{i+1}. {s}" for i, s in enumerate(slugs)]
            return "\n".join(lines)

        @tool
        def kb_read(section: str, slug: str) -> str:
            """Read a KB file's full content.

            Args:
                section: KB section name (themes, stocks, events, etc.)
                slug: File identifier within the section.
                      For stocks use "AAPL/latest_report" format.

            Returns:
                File content (truncated at 15000 chars), or "Not found" message.

            Examples:
                kb_read("themes", "copper-cycle")
                kb_read("stocks", "AAPL/latest_report")
                kb_read("user_views", "")
            """
            path = toolset._resolve_path(section, slug)
            if path is None:
                return f"Unknown section: {section}. Valid: {', '.join(sorted(SECTION_MAP))}"

            toolset._check_sandbox(path)
            content = toolset.kb._read_text(path)
            key = f"{section}/{slug}" if slug else section
            toolset.read_tracker.add(key)
            # Also track the canonical key for single-file sections
            if section in _SINGLE_FILE_SECTIONS:
                toolset.read_tracker.add(f"{section}/")

            if content is None:
                return f"Not found: {section}/{slug}"
            if len(content) > toolset._MAX_READ_CHARS:
                return content[: toolset._MAX_READ_CHARS] + "\n\n[... truncated ...]"
            return content

        @tool
        def kb_read_core_mind() -> str:
            """Read the agent's core mind (notebook/core_mind.md).

            This is the agent's central worldview document. Returns content
            or a message indicating it doesn't exist yet.
            """
            toolset.read_tracker.add("core_mind/")
            content = toolset.kb.read_core_mind()
            if content is None:
                return "core_mind.md does not exist yet."
            if len(content) > toolset._MAX_READ_CHARS:
                return content[: toolset._MAX_READ_CHARS] + "\n\n[... truncated ...]"
            return content

        @tool
        def read_inbox_item(item_id: str) -> str:
            """Read an article by its ID (slug). Searches unread library first,
            then the read library (previously digested articles).

            Use this to read both new items and articles from earlier batches
            or previous sessions.

            Args:
                item_id: The slug of the item (without .md).

            Returns:
                Full content of the article, truncated at 15000 chars.
            """
            # Try unread first
            path = toolset.kb.root / "library" / "unread" / f"{item_id}.md"
            if not path.is_file():
                # Fall back to library (read)
                path = toolset.kb.root / "library" / "read" / f"{item_id}.md"
            toolset._check_sandbox(path)
            content = toolset.kb._read_text(path)
            toolset.read_tracker.add(f"inbox/{item_id}")

            if content is None:
                return f"Article not found: {item_id} (checked unread and read library)"
            if len(content) > toolset._MAX_READ_CHARS:
                return content[: toolset._MAX_READ_CHARS] + "\n\n[... truncated ...]"
            return content

        @tool
        def kb_search(query: str) -> str:
            """Search across all KB markdown files (case-insensitive grep).

            Args:
                query: Search string (plain text, not regex).

            Returns:
                Up to 10 matching lines with file paths and line numbers.

            Example:
                kb_search("copper")
                kb_search("AAPL earnings")
            """
            results: list[str] = []
            query_lower = query.lower()
            skip_dirs = {"archive", "inbox", "meta"}

            for md_file in sorted(toolset.kb.root.rglob("*.md")):
                # Skip archive/ and inbox/ (use read_inbox_item for articles)
                parts = md_file.relative_to(toolset.kb.root).parts
                if any(d in skip_dirs for d in parts):
                    continue

                try:
                    lines = md_file.read_text(encoding="utf-8").splitlines()
                except (OSError, UnicodeDecodeError):
                    continue

                for line_num, line in enumerate(lines, 1):
                    if query_lower in line.lower():
                        rel = md_file.relative_to(toolset.kb.root)
                        results.append(f"{rel}:{line_num}: {line.strip()}")
                        if len(results) >= toolset._MAX_SEARCH_RESULTS:
                            break
                if len(results) >= toolset._MAX_SEARCH_RESULTS:
                    break

            if not results:
                return f"No matches for '{query}'."
            output = "\n".join(results)
            if len(output) > toolset._MAX_SEARCH_CHARS:
                output = output[: toolset._MAX_SEARCH_CHARS] + "\n[... truncated ...]"
            return output

        # ---------------------------------------------------------------
        # WRITE tools
        # ---------------------------------------------------------------

        @tool
        def kb_write(section: str, slug: str, content: str) -> str:
            """Write (create or overwrite) a KB file.

            If the file already exists, you MUST read it first with kb_read.
            Only writable sections: core_mind, themes, events, sectors, stocks.

            Args:
                section: Target section (must be writable).
                slug: File slug. For stocks use "AAPL/latest_report".
                content: Full file content to write.

            Returns:
                Success message or error string.

            Examples:
                kb_write("themes", "ai-boom", "# AI Boom\\nSemiconductor cycle...")
                kb_write("stocks", "NVDA/thesis", "# NVDA Investment Thesis\\n...")
            """
            # Permission check
            if section in READ_ONLY_SECTIONS:
                return f"Error: section '{section}' is read-only (Layer 1). Cannot write."
            if section not in WRITABLE_SECTIONS:
                return f"Unknown section: {section}. Writable: {', '.join(sorted(WRITABLE_SECTIONS))}"

            path = toolset._resolve_path(section, slug)
            if path is None:
                return f"Could not resolve path for {section}/{slug}."
            toolset._check_sandbox(path)

            # Read-before-write check (only for existing files)
            key = f"{section}/{slug}" if slug else section
            canonical_key = f"{section}/" if section in _SINGLE_FILE_SECTIONS else key
            if path.is_file() and key not in toolset.read_tracker and canonical_key not in toolset.read_tracker:
                return (
                    f"Error: {section}/{slug} already exists. "
                    f"You must read it first (kb_read) before overwriting."
                )

            old_content = toolset.kb._read_text(path) if path.is_file() else None
            was_existing = old_content is not None
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            toolset.read_tracker.add(key)
            toolset.kb.append_log(f"kb_write: {section}/{slug} ({len(content)} chars)")
            write_diff = ""
            if old_content is not None:
                write_diff = "\n".join(difflib.unified_diff(
                    old_content.splitlines(), content.splitlines(),
                    fromfile=f"{section}/{slug}", tofile=f"{section}/{slug}",
                    lineterm=""
                ))
            log_event("kb.write", stage="kb", sid=toolset.event_sid, execution_id=toolset.execution_id,
                      section=section, slug=slug, size=len(content), is_new=not was_existing,
                      content=content, diff=write_diff)

            # Soft size warning for notebook files
            _SIZE_WARN = 4000
            if len(content) > _SIZE_WARN and section in ("themes", "events", "sectors"):
                return (
                    f"Written: {section}/{slug} ({len(content)} chars) — "
                    f"WARNING: exceeds {_SIZE_WARN} char target. "
                    f"Consider summarizing or splitting into sub-topics."
                )
            return f"Written: {section}/{slug} ({len(content)} chars)"

        @tool
        def kb_write_core_mind(content: str) -> str:
            """Write the core mind document (notebook/core_mind.md).

            You MUST read it first with kb_read_core_mind before overwriting.

            Args:
                content: Full replacement content for core_mind.md.

            Returns:
                Success message or error if not read first.
            """
            if "core_mind/" not in toolset.read_tracker:
                cm_path = toolset.kb.root / "notebook" / "core_mind.md"
                if cm_path.is_file():
                    return (
                        "Error: core_mind.md exists. "
                        "You must read it first (kb_read_core_mind) before overwriting."
                    )

            old_core_mind = toolset.kb.read_core_mind() or ""
            toolset.kb.write_core_mind(content)
            toolset.read_tracker.add("core_mind/")
            toolset.kb.append_log(f"kb_write_core_mind ({len(content)} chars)")
            cm_diff = "\n".join(difflib.unified_diff(
                old_core_mind.splitlines(), content.splitlines(),
                fromfile="core_mind.md", tofile="core_mind.md",
                lineterm=""
            ))
            log_event("kb.core_mind_updated", stage="kb", sid=toolset.event_sid,
                      execution_id=toolset.execution_id, size=len(content), diff=cm_diff)

            # Auto-snapshot after core_mind update
            if toolset.execution_id:
                toolset.kb.snapshot_core_mind(toolset.execution_id)

            # Soft size warning — core_mind should be a dashboard, not a journal
            _CM_WARN = 4500
            if len(content) > _CM_WARN:
                return (
                    f"Written: core_mind.md ({len(content)} chars) — "
                    f"WARNING: exceeds {_CM_WARN} char target. "
                    f"core_mind should be a concise dashboard (~4000 chars). "
                    f"Move detailed analysis to theme/event notebooks."
                )
            return f"Written: core_mind.md ({len(content)} chars)"

        @tool
        def kb_archive(section: str, slug: str) -> str:
            """Move a KB file to archive/ with a date prefix.

            Only files in writable sections can be archived.

            Args:
                section: Source section.
                slug: File slug to archive.

            Returns:
                Success message or error.

            Example:
                kb_archive("themes", "old-theme")
            """
            if section in READ_ONLY_SECTIONS:
                return f"Error: cannot archive from read-only section '{section}'."
            if section not in WRITABLE_SECTIONS:
                return f"Unknown section: {section}."

            if section in _SINGLE_FILE_SECTIONS:
                return f"Error: cannot archive single-file section '{section}'."

            section_dir = SECTION_MAP[section].rstrip("/")
            try:
                toolset.kb.archive_file(section_dir, slug)
            except FileNotFoundError:
                return f"Not found: {section}/{slug}"

            toolset.kb.append_log(f"kb_archive: {section}/{slug}")
            log_event("kb.archive", stage="kb", sid=toolset.event_sid, execution_id=toolset.execution_id, section=section, slug=slug)
            return f"Archived: {section}/{slug}"

        # ---------------------------------------------------------------
        # EDIT tool
        # ---------------------------------------------------------------

        @tool
        def kb_edit(section: str, slug: str, old_text: str, new_text: str) -> str:
            """Replace exact text in a KB file (surgical edit).

            The old_text must appear exactly ONCE in the file.
            You MUST read the file first.

            Args:
                section: Target section (must be writable).
                slug: File slug.
                old_text: Exact text to find (must be unique in file).
                new_text: Replacement text.

            Returns:
                Success message or error.

            Example:
                kb_edit("themes", "ai-boom", "## Status: Active", "## Status: Cooling")
            """
            if section in READ_ONLY_SECTIONS:
                return f"Error: section '{section}' is read-only. Cannot edit."
            if section not in WRITABLE_SECTIONS:
                return f"Unknown section: {section}."

            path = toolset._resolve_path(section, slug)
            if path is None:
                return f"Could not resolve path for {section}/{slug}."
            toolset._check_sandbox(path)

            key = f"{section}/{slug}" if slug else section
            canonical_key = f"{section}/" if section in _SINGLE_FILE_SECTIONS else key
            if key not in toolset.read_tracker and canonical_key not in toolset.read_tracker:
                return (
                    f"Error: you must read {section}/{slug} first before editing."
                )

            content = toolset.kb._read_text(path)
            if content is None:
                return f"Not found: {section}/{slug}"

            count = content.count(old_text)
            if count == 0:
                return f"Error: old_text not found in {section}/{slug}."
            if count > 1:
                return (
                    f"Error: old_text appears {count} times in {section}/{slug}. "
                    f"Must be unique (exactly 1 match)."
                )

            new_content = content.replace(old_text, new_text, 1)
            path.write_text(new_content, encoding="utf-8")
            toolset.kb.append_log(
                f"kb_edit: {section}/{slug} "
                f"(replaced {len(old_text)} chars with {len(new_text)} chars)"
            )
            diff_text = "\n".join(difflib.unified_diff(
                content.splitlines(), new_content.splitlines(),
                fromfile=f"{section}/{slug}", tofile=f"{section}/{slug}",
                lineterm=""
            ))
            log_event("kb.edit", stage="kb", sid=toolset.event_sid, execution_id=toolset.execution_id,
                      section=section, slug=slug, old_len=len(content), new_len=len(new_content),
                      diff=diff_text)

            # Size warnings (consistent with kb_write / kb_write_core_mind)
            result_msg = f"Edited: {section}/{slug} ({len(new_content)} chars)"
            if section == "core_mind":
                _CM_WARN = 4500
                if len(new_content) > _CM_WARN:
                    result_msg += (
                        f" — WARNING: core_mind.md exceeds {_CM_WARN} char target. "
                        f"Move detailed analysis to theme/event notebooks."
                    )
            elif section in ("themes", "events", "sectors"):
                _SIZE_WARN = 4000
                if len(new_content) > _SIZE_WARN:
                    result_msg += (
                        f" — WARNING: exceeds {_SIZE_WARN} char target. "
                        f"Consider summarizing or splitting."
                    )
            return result_msg

        # ---------------------------------------------------------------
        # META tool
        # ---------------------------------------------------------------

        @tool
        def kb_log(message: str) -> str:
            """Append a message to the KB operation log.

            Use this to record significant reasoning steps or decisions
            about knowledge base updates.

            Args:
                message: Log message to record.

            Returns:
                Confirmation string.

            Example:
                kb_log("Upgraded AAPL thesis from Neutral to Bullish after Q2 beat")
            """
            toolset.kb.append_log(message)
            return f"Logged: {message}"

        # ---------------------------------------------------------------
        # Store all tools
        # ---------------------------------------------------------------

        self._tools: dict[str, object] = {
            "kb_list": kb_list,
            "kb_read": kb_read,
            "kb_read_core_mind": kb_read_core_mind,
            "read_inbox_item": read_inbox_item,
            "kb_search": kb_search,
            "kb_write": kb_write,
            "kb_write_core_mind": kb_write_core_mind,
            "kb_archive": kb_archive,
            "kb_edit": kb_edit,
            "kb_log": kb_log,
        }

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def get_tools(self) -> list:
        """Return all 10 tools as a list (for LangGraph tool binding)."""
        return list(self._tools.values())

    def get_tools_by_names(self, names: list[str]) -> list:
        """Return a subset of tools by name. Unknown names are silently skipped."""
        return [self._tools[n] for n in names if n in self._tools]

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    def _section_root(self, section: str) -> Path:
        """Return the filesystem root for a section (firn root or data root)."""
        if section == "digest_history":
            return self.kb.data_root
        return self.kb.root

    def _resolve_path(self, section: str, slug: str) -> Path | None:
        """Convert (section, slug) to an absolute Path, or None if section unknown."""
        if section not in SECTION_MAP:
            return None

        root = self._section_root(section)
        if section in _SINGLE_FILE_SECTIONS:
            return root / SECTION_MAP[section]

        base_dir = root / SECTION_MAP[section]
        # stocks/ supports nested slugs like "AAPL/latest_report"
        return base_dir / f"{slug}.md"

    def _check_sandbox(self, path: Path) -> None:
        """Ensure *path* is inside ``kb.root`` or ``kb.data_root``. Raise ValueError on traversal."""
        resolved = path.resolve()
        firn_resolved = self.kb.root.resolve()
        data_resolved = self.kb.data_root.resolve()
        if not (resolved.is_relative_to(firn_resolved) or resolved.is_relative_to(data_resolved)):
            raise ValueError(
                f"Path traversal blocked: {path} is outside KB roots"
            )
