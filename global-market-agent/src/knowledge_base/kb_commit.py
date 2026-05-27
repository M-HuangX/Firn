"""Git commit helper for KB changes after digest runs."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]  # financial_analysis_agent/
_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # global-market-agent/
_FIRN_DIR = _PROJECT_ROOT / "firn"
_DATA_DIR = _PROJECT_ROOT / "data"


def commit_kb_changes(message: str) -> str | None:
    """Stage firn/ and data/ directories and commit. Returns short hash or None if no changes."""
    try:
        # Check for changes in both directories
        dirs_to_check = [
            str(_FIRN_DIR.relative_to(_REPO_ROOT)),
            str(_DATA_DIR.relative_to(_REPO_ROOT)),
        ]
        result = subprocess.run(
            ["git", "status", "--porcelain", *dirs_to_check],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        if not result.stdout.strip():
            return None

        # Stage both directories
        subprocess.run(
            ["git", "add", *dirs_to_check],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )

        # Commit
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )

        # Get short hash
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    except subprocess.CalledProcessError as e:
        logger.warning("Git commit failed: %s", e)
        return None


def get_recent_digest_log(n: int = 5) -> str:
    """Read last N sessions from meta/digest_sessions.md."""
    path = _DATA_DIR / "meta" / "digest_sessions.md"
    if not path.is_file():
        return "(no digest history)"
    content = path.read_text(encoding="utf-8")
    # Split by session separator, return first n
    sections = content.split("\n\n---\n\n")
    selected = sections[:n]
    return "\n\n---\n\n".join(selected)
