"""Perception agent -- processes inbox items and updates the KB.

The perception pipeline:
1. Scan library/unread/ for items
2. Parse metadata (source, tier, content type)
3. Route to appropriate KB location based on type + tier
4. Move processed items to library/read/
5. Log all actions

No LLM calls — this is pure logic + file I/O.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.knowledge_base.kb_api import KnowledgeBase
from src.utils.event_log import log_event

logger = logging.getLogger(__name__)

# Allowed content_type values
_VALID_CONTENT_TYPES = {"market_data", "news", "analysis", "user_content", "event"}

# Default values for optional fields
_DEFAULT_TIER = 3
_DEFAULT_CONTENT_TYPE = "news"


@dataclass
class InboxItem:
    """Parsed inbox item with metadata."""

    slug: str
    source: str  # e.g. "fred_api", "user_forwarded", "finnhub_news"
    tier: int  # 1-5
    content_type: str  # "market_data" | "news" | "analysis" | "user_content" | "event"
    ticker: str | None  # Associated ticker if any
    title: str  # Short title/summary
    body: str  # Main content
    tags: list[str] = field(default_factory=list)  # Optional tags
    published_date: str | None = None  # ISO date string e.g. "2025-03-15"
    title_en: str = ""  # English translation of title (for CJK titles)
    raw: str = ""  # Original file content


def _parse_frontmatter(content: str) -> tuple[dict[str, str], str] | None:
    """Parse YAML-like frontmatter between ``---`` markers.

    Returns (metadata_dict, body) or None if no valid frontmatter found.
    Uses simple string splitting, not a YAML library.
    """
    stripped = content.strip()
    if not stripped.startswith("---"):
        return None

    # Find the closing ---
    rest = stripped[3:]  # skip opening ---
    end_idx = rest.find("\n---")
    if end_idx == -1:
        return None

    front = rest[:end_idx].strip()
    body = rest[end_idx + 4:].strip()  # skip \n---

    # Parse simple key: value lines
    metadata: dict[str, str] = {}
    for line in front.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^(\w+)\s*:\s*(.+)$", line)
        if match:
            metadata[match.group(1)] = match.group(2).strip()

    return metadata, body


def parse_inbox_item(slug: str, content: str) -> InboxItem | None:
    """Parse an inbox markdown file with YAML-like frontmatter.

    Expected format::

        ---
        source: finnhub_news
        tier: 3
        content_type: news
        ticker: NVDA
        title: NVDA earnings beat expectations
        tags: earnings, technology
        ---
        (body content here)

    Returns None if content has no valid frontmatter.
    Missing fields use sensible defaults (tier=3, content_type="news").
    """
    result = _parse_frontmatter(content)
    if result is None:
        return None

    metadata, body = result

    source = metadata.get("source", "unknown")

    # Tier: parse as int, default to _DEFAULT_TIER
    try:
        tier = int(metadata.get("tier", str(_DEFAULT_TIER)))
    except (ValueError, TypeError):
        tier = _DEFAULT_TIER

    # Content type: validate, default if invalid
    content_type = metadata.get("content_type", _DEFAULT_CONTENT_TYPE)
    if content_type not in _VALID_CONTENT_TYPES:
        content_type = _DEFAULT_CONTENT_TYPE

    ticker = metadata.get("ticker")
    if ticker:
        ticker = ticker.upper()

    title = metadata.get("title", slug)

    # Tags: comma-separated string to list
    tags_str = metadata.get("tags", "")
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []

    published_date = metadata.get("published_date")
    title_en = metadata.get("title_en", "")

    return InboxItem(
        slug=slug,
        source=source,
        tier=tier,
        content_type=content_type,
        ticker=ticker,
        title=title,
        body=body,
        tags=tags,
        published_date=published_date,
        title_en=title_en,
        raw=content,
    )


def _format_body(item: InboxItem) -> str:
    """Format the body for storage with source attribution."""
    header = f"# {item.title}\n\n"
    attribution = f"**Source**: {item.source} (Tier {item.tier})\n"
    if item.ticker:
        attribution += f"**Ticker**: {item.ticker}\n"
    if item.tags:
        attribution += f"**Tags**: {', '.join(item.tags)}\n"
    attribution += "\n"
    return header + attribution + item.body


def route_item(item: InboxItem, kb: KnowledgeBase) -> dict:
    """Route an inbox item to the appropriate KB location based on its metadata.

    Routing rules:
    - Tier >= 4 or content_type == "user_content" -> user_context/forwarded/
    - content_type == "event" or "market_data" -> notebook/events/
    - content_type == "analysis" -> notebook/themes/
    - content_type == "news" and tier <= 2 -> notebook/events/
    - content_type == "news" and tier == 3 -> notebook/events/ (facts only)
    """
    formatted = _format_body(item)

    # User content and low-trust sources -> user_context/forwarded/
    if item.tier >= 4 or item.content_type == "user_content":
        kb.write_forwarded(item.slug, formatted)
        action = "stored_as_forwarded"
        location = f"user_context/forwarded/{item.slug}.md"
        logger.info("perception: routed %s -> forwarded (tier %d)", item.slug, item.tier)

    # Events and market data -> notebook/events/
    elif item.content_type in ("event", "market_data"):
        kb.write_event(item.slug, formatted)
        action = "stored_as_event"
        location = f"notebook/events/{item.slug}.md"
        logger.info("perception: routed %s -> events (%s)", item.slug, item.content_type)

    # Analysis -> notebook/themes/
    elif item.content_type == "analysis":
        kb.write_theme(item.slug, formatted)
        action = "stored_as_theme"
        location = f"notebook/themes/{item.slug}.md"
        logger.info("perception: routed %s -> themes (analysis)", item.slug)

    # News (tier 1-3) -> notebook/events/
    elif item.content_type == "news":
        kb.write_event(item.slug, formatted)
        action = "stored_as_event"
        location = f"notebook/events/{item.slug}.md"
        logger.info("perception: routed %s -> events (news, tier %d)", item.slug, item.tier)

    # Fallback — should not normally happen
    else:
        kb.write_event(item.slug, formatted)
        action = "stored_as_event"
        location = f"notebook/events/{item.slug}.md"
        logger.info("perception: routed %s -> events (fallback)", item.slug)

    return {"slug": item.slug, "action": action, "location": location}


def process_inbox(kb: KnowledgeBase | None = None) -> list[dict]:
    """Process all pending inbox items.

    Returns a list of dicts describing what was done with each item::

        [{"slug": "...", "action": "stored_as_event", "location": "events/..."}, ...]
    """
    if kb is None:
        kb = KnowledgeBase()

    results = []
    pending = kb.list_unread()
    if not pending:
        logger.info("perception: no pending items in inbox")
        return results

    for slug in pending:
        content = kb.read_unread(slug)
        if not content:
            continue

        item = parse_inbox_item(slug, content)
        if item is None:
            logger.warning("perception: could not parse inbox item: %s", slug)
            results.append({"slug": slug, "action": "parse_error", "location": None})
            # Still move to processed so it doesn't block future runs
            try:
                kb.mark_read(slug)
            except Exception as e:
                logger.warning("perception: failed to mark %s as processed: %s", slug, e)
            continue

        result = route_item(item, kb)
        results.append(result)

        # Move to processed
        try:
            kb.mark_read(slug)
        except Exception as e:
            logger.warning("perception: failed to mark %s as processed: %s", slug, e)

    # Log summary
    if results:
        actions = {}
        for r in results:
            a = r["action"]
            actions[a] = actions.get(a, 0) + 1
        summary_parts = [f"{v} {k}" for k, v in sorted(actions.items())]
        kb.append_log(f"Perception: processed {len(results)} items ({', '.join(summary_parts)})")

    return results


def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80]  # cap length


def _has_cjk(text: str) -> bool:
    """Return True if *text* contains any CJK Unified Ideograph character."""
    return any('\u4e00' <= c <= '\u9fff' for c in text)


def _translate_single_title(title: str) -> str:
    """Translate a single title via DeepL.  Returns "" on any failure."""
    api_key = os.environ.get("DEEPL_API_KEY", "")
    if not api_key:
        return ""
    try:
        import httpx
        resp = httpx.post(
            "https://api-free.deepl.com/v2/translate",
            headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
            json={"text": [title], "source_lang": "ZH", "target_lang": "EN"},
            timeout=10.0,
        )
        if resp.status_code == 200:
            translations = resp.json().get("translations", [])
            if translations:
                return translations[0]["text"]
    except Exception:
        pass
    return ""


def add_to_inbox(
    content: str,
    source: str,
    tier: int | None = None,
    content_type: str = "news",
    ticker: str | None = None,
    title: str | None = None,
    title_en: str | None = None,
    tags: list[str] | None = None,
    published_date: str | None = None,
    kb: KnowledgeBase | None = None,
) -> str:
    """Convenience function to add an item to the inbox with proper formatting.

    Auto-resolves tier from source_registry if not provided.
    Returns the slug of the created item.
    """
    if kb is None:
        kb = KnowledgeBase()

    # Auto-resolve tier from source registry if not provided
    if tier is None:
        resolved_tier = kb.get_source_tier(source)
        tier = resolved_tier if resolved_tier is not None else _DEFAULT_TIER

    # Validate content_type
    if content_type not in _VALID_CONTENT_TYPES:
        content_type = _DEFAULT_CONTENT_TYPE

    # Generate slug from published_date (or today) + title
    date_str = published_date if published_date else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title_slug = _slugify(title) if title else _slugify(source)
    slug = f"{date_str}_{title_slug}"

    # Resolve title_en: translate CJK titles when not explicitly provided
    if title_en is None:
        resolved_title = title or source
        if _has_cjk(resolved_title):
            title_en = _translate_single_title(resolved_title)
        else:
            title_en = ""

    # Build frontmatter
    lines = [
        "---",
        f"source: {source}",
        f"tier: {tier}",
        f"content_type: {content_type}",
    ]
    if ticker:
        lines.append(f"ticker: {ticker.upper()}")
    if title:
        lines.append(f"title: {title}")
    if title_en:
        lines.append(f"title_en: {title_en}")
    if tags:
        lines.append(f"tags: {', '.join(tags)}")
    lines.append(f"published_date: {published_date if published_date else 'unknown'}")
    lines.append("---")
    lines.append("")
    lines.append(content)

    formatted = "\n".join(lines)
    kb.add_unread(slug, formatted)

    log_event("inbox.item_created", stage="inbox", source=source, tier=tier,
              slug=slug, title=(title or "")[:80])

    logger.info("perception: added inbox item %s (source=%s, tier=%d)", slug, source, tier)
    return slug
