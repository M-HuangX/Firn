"""Knowledge Base read routes: themes, stocks, core mind, inbox, graph, evolution."""

from __future__ import annotations

import json
import re
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.dependencies import get_current_user, get_kb, rate_limit
from src.knowledge_base.kb_api import KnowledgeBase

router = APIRouter(dependencies=[Depends(rate_limit), Depends(get_current_user)])

# Snapshot ID format: YYYY-MM-DD_8hexchars
_SNAPSHOT_ID_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}_[a-f0-9]{8}$")


# --- Response models ---

class ThemeSummary(BaseModel):
    slug: str
    preview: str = ""


class StockSummary(BaseModel):
    ticker: str
    files: list[str] = []
    file_chars: dict[str, int] = {}
    total_chars: int = 0
    connected_themes: list[str] = []


class EventSummary(BaseModel):
    slug: str
    preview: str = ""


class LibraryStats(BaseModel):
    unread: int
    read: int


class MaturationItem(BaseModel):
    item_id: str        # e.g. "theme:ai-revolution", "stock:AAPL", "event:fed-rate-cut"
    item_type: str      # "theme" | "stock" | "event" | "core_mind"
    write_count: int
    tier: str           # "snow" | "firn" | "ice"
    last_updated: str   # ISO timestamp of last write event


class MaturationResponse(BaseModel):
    items: list[MaturationItem]
    total_sessions: int  # count of distinct execution_id values


class PulsePoint(BaseModel):
    date: str
    char_count: int
    snapshot_id: str


class PulseResponse(BaseModel):
    points: list[PulsePoint]


# --- Endpoints ---


@router.get("/themes", response_model=list[ThemeSummary])
async def list_themes(kb: KnowledgeBase = Depends(get_kb)):
    themes = kb.list_themes()
    results = []
    for slug in themes:
        content = kb.read_theme(slug)
        preview = (content or "")[:200]
        results.append(ThemeSummary(slug=slug, preview=preview))
    return results


@router.get("/themes/{slug}")
async def get_theme(slug: str, kb: KnowledgeBase = Depends(get_kb)):
    content = kb.read_theme(slug)
    if content is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    return {"slug": slug, "content": content}


@router.get("/stocks", response_model=list[StockSummary])
async def list_stocks(kb: KnowledgeBase = Depends(get_kb)):
    tickers = kb.list_stocks()
    themes = kb.list_themes()
    # Pre-read theme content for cross-referencing
    theme_contents: dict[str, str] = {}
    for slug in themes:
        theme_contents[slug] = (kb.read_theme(slug) or "").lower()

    results = []
    for ticker in tickers:
        files = kb.list_stock_files(ticker)
        file_chars: dict[str, int] = {}
        for fname in files:
            text = kb.read_stock(ticker, fname)
            file_chars[fname] = len(text) if text else 0
        total_chars = sum(file_chars.values())
        connected = [slug for slug, content in theme_contents.items()
                     if ticker.lower() in content]
        results.append(StockSummary(
            ticker=ticker, files=files,
            file_chars=file_chars, total_chars=total_chars,
            connected_themes=connected,
        ))
    return results


@router.get("/stocks/{ticker}")
async def get_stock(ticker: str, kb: KnowledgeBase = Depends(get_kb)):
    files = kb.list_stock_files(ticker)
    if not files:
        raise HTTPException(status_code=404, detail="Stock not found")
    content = {}
    for fname in files:
        text = kb.read_stock(ticker, fname)
        if text:
            content[fname] = text
    return {"ticker": ticker, "files": content}


@router.get("/events", response_model=list[EventSummary])
async def list_events(kb: KnowledgeBase = Depends(get_kb)):
    events = kb.list_events()
    results = []
    for slug in events:
        content = kb.read_event(slug) or ""
        results.append(EventSummary(slug=slug, preview=content[:200]))
    return results


@router.get("/events/{slug}")
async def get_event(slug: str, kb: KnowledgeBase = Depends(get_kb)):
    content = kb.read_event(slug)
    if content is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"slug": slug, "content": content}


@router.get("/core-mind/history")
async def list_core_mind_history(kb: KnowledgeBase = Depends(get_kb)):
    """List all core_mind snapshots."""
    snapshots = kb.list_core_mind_snapshots()
    return {"snapshots": snapshots}


@router.get("/core-mind/snapshot/{snapshot_id}")
async def get_core_mind_snapshot(snapshot_id: str, kb: KnowledgeBase = Depends(get_kb)):
    """Read a specific core_mind snapshot by ID."""
    if not _SNAPSHOT_ID_RE.match(snapshot_id):
        raise HTTPException(status_code=400, detail="Invalid snapshot_id format")
    content = kb.read_core_mind_snapshot(snapshot_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return {"id": snapshot_id, "content": content}


@router.get("/core-mind")
async def get_core_mind(kb: KnowledgeBase = Depends(get_kb)):
    content = kb.read_core_mind()
    return {"content": content}


@router.get("/inbox", response_model=LibraryStats)
async def inbox_stats(kb: KnowledgeBase = Depends(get_kb)):
    return LibraryStats(
        unread=len(kb.list_unread()),
        read=len(kb.list_read()),
    )


# --- Knowledge Graph ---


@router.get("/graph")
async def get_kb_graph(kb: KnowledgeBase = Depends(get_kb)):
    """Build knowledge graph: nodes (core_mind, themes, stocks, events) + edges (mentions)."""
    nodes: list[dict] = []
    edges: list[dict] = []

    # Core Mind node
    core_mind = kb.read_core_mind() or ""
    core_mind_lower = core_mind.lower()
    nodes.append({"id": "core_mind", "type": "core", "label": "Core Mind", "chars": len(core_mind)})

    # Read theme content once (cached for reuse in stock edge detection)
    themes = kb.list_themes()
    theme_contents: dict[str, str] = {}
    for slug in themes:
        content = kb.read_theme(slug) or ""
        theme_contents[slug] = content
        nodes.append({
            "id": f"theme:{slug}",
            "type": "theme",
            "label": slug.replace("-", " ").title(),
            "chars": len(content),
        })
        # Edge: core_mind references theme (case-insensitive, match slug or space-separated form)
        if slug in core_mind_lower or slug.replace("-", " ") in core_mind_lower:
            edges.append({"source": "core_mind", "target": f"theme:{slug}"})

    # Stock nodes + edges from theme -> stock
    stocks = kb.list_stocks()
    for ticker in stocks:
        nodes.append({"id": f"stock:{ticker}", "type": "stock", "label": ticker, "chars": 0})
        # Edge: theme mentions stock (case-insensitive, using cached content)
        for slug in themes:
            content = theme_contents[slug]
            if ticker.lower() in content.lower():
                edges.append({"source": f"theme:{slug}", "target": f"stock:{ticker}"})

    # Event nodes + edges from core_mind -> event
    events = kb.list_events()
    for slug in events:
        content = kb.read_event(slug) or ""
        nodes.append({
            "id": f"event:{slug}",
            "type": "event",
            "label": slug.replace("-", " ").title(),
            "chars": len(content),
        })
        if slug in core_mind_lower or slug.replace("-", " ") in core_mind_lower:
            edges.append({"source": "core_mind", "target": f"event:{slug}"})

    return {"nodes": nodes, "edges": edges}


# --- Evolution Timeline ---


@router.get("/evolution")
async def get_evolution_timeline(kb: KnowledgeBase = Depends(get_kb)):
    """Aggregate pipeline events by day for evolution timeline chart."""
    events_path = kb.data_root / "meta" / "pipeline_events.jsonl"
    if not events_path.is_file():
        return {"daily": [], "cumulative": []}

    daily: dict[str, dict] = defaultdict(
        lambda: {"articles_ingested": 0, "kb_writes": 0, "analyses": 0, "digests": 0}
    )

    with open(events_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = evt.get("ts", "")
            date = ts[:10]
            if not date:
                continue

            event_name = evt.get("event", "")

            if event_name == "digest.session_end":
                daily[date]["digests"] += 1
                items = evt.get("data", {}).get("items_processed", 0)
                daily[date]["articles_ingested"] += items
            elif event_name in ("kb.write", "kb.edit", "kb.core_mind_updated"):
                daily[date]["kb_writes"] += 1
            elif event_name == "analysis.end":
                data = evt.get("data", {})
                if data.get("success"):
                    daily[date]["analyses"] += 1

    # Sort by date
    result = [{"date": d, **counts} for d, counts in sorted(daily.items())]

    # Compute cumulative
    cumulative: list[dict] = []
    running = {"articles": 0, "kb_writes": 0, "analyses": 0}
    for entry in result:
        running["articles"] += entry["articles_ingested"]
        running["kb_writes"] += entry["kb_writes"]
        running["analyses"] += entry["analyses"]
        cumulative.append({"date": entry["date"], **running})

    return {"daily": result, "cumulative": cumulative}


# --- Maturation ---


def _classify_tier(write_count: int, is_core_mind: bool = False) -> str:
    """Classify maturation tier from write count."""
    if is_core_mind:
        return "ice"
    if write_count <= 1:
        return "snow"
    if write_count <= 4:
        return "firn"
    return "ice"


@router.get("/maturation", response_model=MaturationResponse)
async def get_maturation(kb: KnowledgeBase = Depends(get_kb)):
    """Aggregate kb.write / kb.edit / kb.core_mind_updated events into per-item maturation tiers."""
    events_path = kb.data_root / "meta" / "pipeline_events.jsonl"
    if not events_path.is_file():
        return MaturationResponse(items=[], total_sessions=0)

    # key = (section, slug), value = {"count": int, "last_ts": str}
    item_counts: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"count": 0, "last_ts": ""}
    )
    exec_ids: set[str] = set()

    with open(events_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_name = evt.get("event", "")
            if event_name not in ("kb.write", "kb.edit", "kb.core_mind_updated"):
                continue

            data = evt.get("data", {})
            ts = evt.get("ts", "")

            # Track distinct sessions
            eid = data.get("execution_id", "")
            if eid:
                exec_ids.add(eid)

            if event_name == "kb.core_mind_updated":
                key = ("core_mind", "")
            else:
                section = data.get("section", "")
                slug = data.get("slug", "")
                if not section:
                    continue
                # kb.edit with section="core_mind" → treat as core_mind update
                if section == "core_mind":
                    key = ("core_mind", "")
                else:
                    key = (section, slug)

            entry = item_counts[key]
            entry["count"] += 1
            if ts > entry["last_ts"]:
                entry["last_ts"] = ts

    # Section name → item_type mapping
    section_type_map = {"themes": "theme", "stocks": "stock", "events": "event"}

    items: list[MaturationItem] = []
    for (section, slug), info in item_counts.items():
        if section == "core_mind":
            item_type = "core_mind"
            item_id = "core_mind"
        else:
            item_type = section_type_map.get(section, section)
            item_id = f"{item_type}:{slug}"

        items.append(MaturationItem(
            item_id=item_id,
            item_type=item_type,
            write_count=info["count"],
            tier=_classify_tier(info["count"], is_core_mind=(item_type == "core_mind")),
            last_updated=info["last_ts"],
        ))

    # Sort by type then write_count descending
    type_order = {"core_mind": 0, "theme": 1, "stock": 2, "event": 3}
    items.sort(key=lambda x: (type_order.get(x.item_type, 99), -x.write_count))

    return MaturationResponse(items=items, total_sessions=len(exec_ids))


# --- Core Mind Pulse ---


@router.get("/core-mind/pulse", response_model=PulseResponse)
async def get_core_mind_pulse(kb: KnowledgeBase = Depends(get_kb)):
    """Return char_count time series from core mind snapshots."""
    snapshots = kb.list_core_mind_snapshots()
    points = [
        PulsePoint(
            date=s.get("date", ""),
            char_count=s.get("char_count", 0),
            snapshot_id=s.get("id", ""),
        )
        for s in snapshots
    ]
    points.sort(key=lambda p: p.date)
    return PulseResponse(points=points)
