"""JSON formatting utilities for MCP tool output — serialization helpers for pandas and numpy types."""

from __future__ import annotations

import json
from typing import Any


def format_json(data: Any) -> str:
    """Format data as a JSON string with 2-space indentation.

    Uses ``default=str`` to handle datetime, Timestamp, and other
    non-serializable types gracefully.

    Args:
        data: Any JSON-serializable data structure (dict, list, etc.).

    Returns:
        Pretty-printed JSON string.
    """
    return json.dumps(data, indent=2, default=str, ensure_ascii=False)
