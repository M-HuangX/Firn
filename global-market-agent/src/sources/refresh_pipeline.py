"""
Refresh pipeline — bridge between WeChat source fetching and Perception.

Called by CLI --refresh-sources or by cron.
Same pipeline for both triggers.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone

from src.knowledge_base.kb_api import KnowledgeBase
from src.knowledge_base.perception import add_to_inbox
from src.sources.wechat.manager import WechatSourceManager, WechatArticle
from src.utils.event_log import log_event, new_session_id


def _run_macro_pulse(kb: KnowledgeBase) -> dict:
    """Run macro pulse generation with error isolation.

    Macro pulse failure must never block the WeChat refresh pipeline.
    """
    try:
        from src.sources.market.macro_pulse import generate_macro_pulse

        return generate_macro_pulse(kb=kb)
    except Exception as e:
        print(f"[refresh] Macro pulse failed (non-fatal): {e}")
        return {"status": "error", "reason": str(e)}


def _run_market_snapshot(kb: KnowledgeBase) -> dict:
    """Run market snapshot generation with error isolation."""
    try:
        from src.sources.market.snapshot import generate_market_snapshot_item

        return generate_market_snapshot_item(kb=kb)
    except Exception as e:
        print(f"[refresh] Market snapshot failed (non-fatal): {e}")
        return {"status": "error", "reason": str(e)}


def _run_news_fetch(kb: KnowledgeBase) -> dict:
    """Run market news fetch with error isolation.

    News fetch failure must never block other pipeline steps.
    """
    try:
        from src.sources.market.news import fetch_market_news

        return fetch_market_news(kb=kb)
    except Exception as e:
        print(f"[refresh] News fetch failed (non-fatal): {e}")
        return {"status": "error", "reason": str(e)}


def _run_watchlist_check(kb: KnowledgeBase) -> dict:
    """Run watchlist event check with error isolation.

    Watchlist check failure must never block other pipeline steps.
    """
    try:
        from src.sources.market.watchlist import check_watchlist_events

        return check_watchlist_events(kb=kb)
    except Exception as e:
        print(f"[refresh] Watchlist check failed (non-fatal): {e}")
        return {"status": "error", "reason": str(e)}


def _run_bilibili_fetch(kb: KnowledgeBase) -> dict:
    """Run Bilibili content fetch with error isolation.

    Bilibili failure must never block other pipeline steps.
    """
    try:
        import asyncio
        from src.sources.bilibili.manager import BilibiliSourceManager

        async def _fetch():
            manager = BilibiliSourceManager()
            if not manager.accounts:
                return {"status": "skipped", "reason": "no accounts configured"}
            return await manager.refresh_all_to_inbox(kb=kb)

        return asyncio.run(_fetch())
    except Exception as e:
        print(f"[refresh] Bilibili fetch failed (non-fatal): {e}")
        return {"status": "error", "reason": str(e)}


def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug, preserving Chinese characters."""
    text = text.strip()
    text = re.sub(r"[^\w\u4e00-\u9fff\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80]


def _article_to_inbox_content(article: WechatArticle, account_config) -> str:
    """Format a WeChat article as inbox content with local reference."""
    ref = WechatSourceManager.make_reference(article.account, article.title)
    lines = [
        article.content or article.summary or "(no content)",
        "",
        f"---",
        f"Reference: {ref}",
    ]
    if article.wechat_url:
        lines.append(f"Original URL: {article.wechat_url}")
    return "\n".join(lines)


def _collect_existing_titles(kb: KnowledgeBase) -> set[str]:
    """Scan library for existing article titles (for dedup)."""
    existing: set[str] = set()
    for subdir in ("library/unread", "library/read"):
        inbox_dir = kb.root / subdir
        if inbox_dir.is_dir():
            for f in inbox_dir.glob("*.md"):
                for line in f.read_text(encoding="utf-8").splitlines()[:10]:
                    if line.startswith("title: "):
                        existing.add(line[7:].strip())
                        break
    return existing


def ingest_cached_articles(max_age_days: int = 90) -> dict:
    """Bulk import: create library items from all cached WeChat + Bilibili articles.

    Scans JSON stores for both sources and adds uncached items to library/unread.
    Deduplicates against existing library items by title.

    Returns summary dict with counts per account.
    """
    t0 = time.time()
    sid = new_session_id("ingest-cached")
    log_event("source.ingest_cached_start", stage="source", sid=sid)

    kb = KnowledgeBase()
    existing_titles = _collect_existing_titles(kb)

    per_account: dict[str, int] = {}
    total_created = 0

    # --- WeChat ---
    manager = WechatSourceManager()
    for account in manager.accounts:
        name = account.name
        stored = manager.get_recent_articles(name, limit=500, days=max_age_days)
        created = 0

        for art in stored:
            title = art.get("title", "")
            timestamp = art.get("timestamp", 0)
            if not title or not timestamp:
                continue

            full_title = f"[{name}] {title}"
            if full_title in existing_titles:
                continue

            article = WechatArticle(
                title=title,
                account=art.get("account", name),
                timestamp=timestamp,
                summary=art.get("summary", ""),
                sogou_link=art.get("sogou_link", ""),
                wechat_url=art.get("wechat_url", ""),
                content=art.get("content", ""),
            )

            content = _article_to_inbox_content(article, account)
            tags = list(account.tags) if account.tags else []
            pub_date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d") if timestamp else None

            title_en = art.get("title_en") or None

            add_to_inbox(
                content=content,
                source=f"wechat_{_slugify(name)}",
                tier=account.effective_tier,
                content_type="analysis",
                title=full_title,
                title_en=title_en,
                tags=tags,
                published_date=pub_date,
                kb=kb,
            )
            existing_titles.add(full_title)
            created += 1

        per_account[name] = created
        total_created += created
        if created:
            print(f"[ingest] {name}: {created} cached WeChat articles → library")

    # --- Bilibili ---
    bilibili_created = _ingest_bilibili_cached(kb, existing_titles, per_account, max_age_days)
    total_created += bilibili_created

    # --- News ---
    news_created = _ingest_news_cached(kb, existing_titles, max_age_days)
    total_created += news_created
    if news_created:
        per_account["market_news"] = news_created

    # --- Watchlist ---
    watchlist_created = _ingest_watchlist_cached(kb, existing_titles, max_age_days)
    total_created += watchlist_created
    if watchlist_created:
        per_account["watchlist"] = watchlist_created

    elapsed = time.time() - t0
    log_event("source.ingest_cached_end", stage="source", sid=sid,
              total_created=total_created, elapsed_s=round(elapsed, 1))

    if total_created == 0:
        print("[ingest] All cached articles already in library — nothing to do.")
    else:
        print(f"[ingest] Total: {total_created} articles imported. Run --digest to process.")

    return {"total_created": total_created, "per_account": per_account}


def _ingest_bilibili_cached(
    kb: KnowledgeBase,
    existing_titles: set[str],
    per_account: dict[str, int],
    max_age_days: int,
) -> int:
    """Import cached Bilibili store entries into library/unread."""
    try:
        from src.sources.bilibili.manager import BilibiliSourceManager
        from src.sources.bilibili.client import DynamicItem, SubtitleResult
    except ImportError:
        print("[ingest] Bilibili module not available, skipping")
        return 0

    try:
        manager = BilibiliSourceManager()
    except (ValueError, Exception) as e:
        print(f"[ingest] Bilibili manager init failed (non-fatal): {e}")
        return 0
    if not manager.accounts:
        return 0

    since_ts = int(time.time()) - max_age_days * 86400
    total = 0

    for account in manager.accounts:
        store = manager._load_store(account.name)
        created = 0

        for entry_id, entry in store.items():
            entry_type = entry.get("type", "")
            ts = entry.get("timestamp") or entry.get("publish_timestamp", 0)
            if ts and ts < since_ts:
                continue

            if entry_type == "dynamic":
                text = entry.get("text", "")
                if not text:
                    continue
                dyn = DynamicItem(
                    dynamic_id=entry.get("dynamic_id", entry_id),
                    type=entry.get("dynamic_type", "DYNAMIC_TYPE_WORD"),
                    text=text,
                    timestamp=entry.get("timestamp", 0),
                    bvid=entry.get("bvid"),
                    is_charging=entry.get("is_charging", False),
                    author_name=entry.get("author_name", account.name),
                    author_uid=entry.get("author_uid", account.uid),
                )
                item = manager._make_dynamic_inbox_item(dyn, account)

            elif entry_type == "video_subtitle":
                subtitle_text = entry.get("subtitle_text", "")
                if not subtitle_text:
                    continue
                sub = SubtitleResult(
                    bvid=entry.get("bvid", entry_id),
                    title=entry.get("title", ""),
                    subtitle_text=subtitle_text,
                    subtitle_with_ts=entry.get("subtitle_with_ts", []),
                    subtitle_type=entry.get("subtitle_type", ""),
                    duration_seconds=entry.get("duration_seconds", 0),
                    publish_timestamp=ts,
                )
                item = manager._make_subtitle_inbox_item(sub, account)

            else:
                continue

            title = item["title"]
            if title in existing_titles:
                continue

            title_en = entry.get("title_en") or None

            add_to_inbox(
                content=item["content"],
                source=item["source"],
                tier=item["tier"],
                content_type=item["content_type"],
                title=title,
                title_en=title_en,
                tags=item.get("tags", []),
                published_date=item.get("published_date"),
                kb=kb,
            )
            existing_titles.add(title)
            created += 1

        per_account[account.name] = per_account.get(account.name, 0) + created
        total += created
        if created:
            print(f"[ingest] {account.name}: {created} cached Bilibili items → library")

    return total


def _ingest_news_cached(
    kb: KnowledgeBase,
    existing_titles: set[str],
    max_age_days: int,
) -> int:
    """Import cached news store entries into library/unread."""
    store_path = kb.data_root / "sources" / "news_store.json"

    if not store_path.exists():
        return 0

    try:
        store = json.loads(store_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0

    since_ts = int(time.time()) - max_age_days * 86400
    created = 0

    for _uid, entry in store.items():
        title = entry.get("title", "")
        if not title or title in existing_titles:
            continue

        # Apply max_age_days filter via pub_date
        pub_date = entry.get("pub_date")
        if pub_date:
            try:
                pub_dt = datetime.strptime(pub_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if pub_dt.timestamp() < since_ts:
                    continue
            except (ValueError, TypeError):
                pass

        source_type = entry.get("source_type", "market_news_yfinance")
        add_to_inbox(
            content=entry.get("body", ""),
            source=source_type,
            tier=entry.get("tier", 3),
            content_type="news",
            title=title,
            ticker=entry.get("ticker"),
            tags=entry.get("tags", []),
            published_date=pub_date,
            kb=kb,
        )
        existing_titles.add(title)
        created += 1

    if created:
        print(f"[ingest] News: {created} cached articles → library")

    return created


def _ingest_watchlist_cached(
    kb: KnowledgeBase,
    existing_titles: set[str],
    max_age_days: int,
) -> int:
    """Import cached watchlist store entries into library/unread."""
    store_path = kb.data_root / "sources" / "watchlist_store.json"

    if not store_path.exists():
        return 0

    try:
        store = json.loads(store_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0

    since_ts = int(time.time()) - max_age_days * 86400
    created = 0

    for _key, entry in store.items():
        title = entry.get("title", "")
        if not title or title in existing_titles:
            continue

        # Apply max_age_days filter via pub_date
        pub_date = entry.get("pub_date")
        if pub_date:
            try:
                pub_dt = datetime.strptime(pub_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if pub_dt.timestamp() < since_ts:
                    continue
            except (ValueError, TypeError):
                pass

        add_to_inbox(
            content=entry.get("body", ""),
            source="watchlist_monitor",
            tier=entry.get("tier", 2),
            content_type="event",
            title=title,
            ticker=entry.get("ticker"),
            tags=entry.get("tags", []),
            published_date=pub_date,
            kb=kb,
        )
        existing_titles.add(title)
        created += 1

    if created:
        print(f"[ingest] Watchlist: {created} cached events → library")

    return created


def refresh_sources(
    pages: int = 3,
    max_age_days: int = 30,
) -> dict:
    """Refresh all registered WeChat accounts and create inbox items.

    Fetches new articles and adds them to ``library/unread/``.
    Does NOT run digest — use ``--digest`` separately for LLM-powered processing.

    Returns summary dict with counts per account.
    """
    t0 = time.time()
    sid = new_session_id("refresh")
    log_event("source.refresh_start", stage="source", sid=sid,
              sources=["wechat", "macro_pulse", "market_snapshot", "news", "watchlist", "bilibili"])

    manager = WechatSourceManager()
    kb = KnowledgeBase()

    print(f"[refresh] {len(manager.accounts)} registered accounts")

    # Step 1: Fetch new articles from all accounts
    all_new = manager.refresh_all(pages=pages, max_age_days=max_age_days)

    # Record freshness per account
    for account in manager.accounts:
        name = account.name
        arts = all_new.get(name, [])
        count = len(arts)
        summary = f"{count} new articles" if count else "no new articles"
        kb.set_last_updated(f"wechat_{name}", new_count=count, summary=summary)
        log_event("source.fetch_complete", stage="source", sid=sid,
                  source=f"wechat_{name}", new_count=count, error=None)

    total_new = sum(len(arts) for arts in all_new.values())

    # Step 2: Create inbox items for each new article
    inbox_slugs = []
    if total_new > 0:
        for account_name, articles in all_new.items():
            if not articles:
                continue

            account_config = manager.get_account(account_name)
            tier = account_config.effective_tier if account_config else 3

            for article in articles:
                content = _article_to_inbox_content(article, account_config)
                date_str = datetime.fromtimestamp(article.timestamp).strftime("%Y-%m-%d")
                title_slug = _slugify(article.title)
                slug = f"wechat-{date_str}-{title_slug}"

                tags = []
                if account_config:
                    tags = list(account_config.tags)

                pub_date = datetime.fromtimestamp(article.timestamp, tz=timezone.utc).strftime("%Y-%m-%d")

                add_to_inbox(
                    content=content,
                    source=f"wechat_{_slugify(account_name)}",
                    tier=tier,
                    content_type="analysis",
                    title=f"[{account_name}] {article.title}",
                    tags=tags,
                    published_date=pub_date,
                    kb=kb,
                )
                inbox_slugs.append(slug)

        print(f"[refresh] {total_new} new articles → {len(inbox_slugs)} inbox items created")
    else:
        print("[refresh] No new articles found across all accounts.")

    # Step 3: Generate macro pulse (independent of WeChat — errors don't block)
    macro_result = _run_macro_pulse(kb)
    log_event("source.fetch_complete", stage="source", sid=sid,
              source="macro_pulse",
              new_count=1 if macro_result.get("status") == "ok" else 0,
              error=macro_result.get("reason"))

    # Step 3b: Generate market snapshot (independent — errors don't block)
    snapshot_result = _run_market_snapshot(kb)
    log_event("source.fetch_complete", stage="source", sid=sid,
              source="market_snapshot",
              new_count=1 if snapshot_result.get("status") == "ok" else 0,
              error=snapshot_result.get("reason"))

    # Step 4: Market news fetch (independent — errors don't block)
    news_result = _run_news_fetch(kb)
    log_event("source.fetch_complete", stage="source", sid=sid,
              source="news",
              new_count=news_result.get("total_created", 0) if isinstance(news_result, dict) else 0,
              error=news_result.get("reason") if isinstance(news_result, dict) else None)

    # Step 5: Watchlist event check (independent — errors don't block)
    watchlist_result = _run_watchlist_check(kb)
    log_event("source.fetch_complete", stage="source", sid=sid,
              source="watchlist",
              new_count=watchlist_result.get("total_events", 0) if isinstance(watchlist_result, dict) else 0,
              error=watchlist_result.get("reason") if isinstance(watchlist_result, dict) else None)

    # Step 6: Bilibili content fetch (independent — errors don't block)
    bilibili_result = _run_bilibili_fetch(kb)
    log_event("source.fetch_complete", stage="source", sid=sid,
              source="bilibili",
              new_count=bilibili_result.get("total_items", 0) if isinstance(bilibili_result, dict) else 0,
              error=bilibili_result.get("reason") if isinstance(bilibili_result, dict) else None)

    # Count total inbox items created across all sources
    macro_items = 1 if macro_result.get("status") == "ok" else 0
    snapshot_items = 1 if snapshot_result.get("status") == "ok" else 0
    news_items = news_result.get("total_created", 0) if isinstance(news_result, dict) else 0
    watchlist_items = watchlist_result.get("total_events", 0) if isinstance(watchlist_result, dict) else 0
    bilibili_items = bilibili_result.get("total_items", 0) if isinstance(bilibili_result, dict) else 0
    total_inbox = len(inbox_slugs) + macro_items + snapshot_items + news_items + watchlist_items + bilibili_items

    if total_inbox > 0:
        print("[refresh] Run --digest to process them with the LLM-powered pipeline.")

    elapsed = time.time() - t0
    log_event("source.refresh_end", stage="source", sid=sid,
              total_new=total_inbox, elapsed_s=round(elapsed, 1))

    return {
        "new_articles": total_new,
        "inbox_items": total_inbox,
        "per_account": {name: len(arts) for name, arts in all_new.items()},
        "macro_pulse": macro_result,
        "market_snapshot": snapshot_result,
        "news_fetch": news_result,
        "watchlist_check": watchlist_result,
        "bilibili_fetch": bilibili_result,
    }
