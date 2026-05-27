"""
BilibiliSourceManager — unified manager for all Bilibili creator sources.

Mirrors the WechatSourceManager pattern:
  1. Load account config from bilibili_accounts.yaml
  2. Fetch dynamics and video subtitles via BilibiliClient
  3. Dedup against local JSON store
  4. Create inbox items via add_to_inbox()

Local reference protocol:
  local://sources/bilibili/{account_name}/{bvid_or_dynamic_id}
  -> resolves to full content from local JSON store

Cookie lifecycle:
  - Auto-refresh on each refresh_all() call
  - On refresh failure: Telegram alert + skip this run
  - On refresh success: update .env with new cookie values
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import yaml

from .client import (
    BilibiliClient,
    CookieExpiredError,
    DynamicItem,
    SubtitleResult,
    DYNAMIC_TYPE_AV,
    DYNAMIC_TYPE_WORD,
    DYNAMIC_TYPE_DRAW,
)
from .notifier import send_telegram_alert

logger = logging.getLogger(__name__)

SOURCES_DIR = Path(__file__).resolve().parents[3] / "data" / "sources"
ACCOUNTS_CONFIG = SOURCES_DIR / "bilibili_accounts.yaml"
LOCAL_REF_PREFIX = "local://sources/bilibili/"

# .env file path (same directory as the agent project root)
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


def _translate_title_en(title: str) -> str:
    """Translate a CJK title to English. Returns '' if not CJK or on failure."""
    if not any('\u4e00' <= c <= '\u9fff' for c in title):
        return ""
    from src.knowledge_base.perception import _translate_single_title
    return _translate_single_title(title)


@dataclass
class BilibiliAccountConfig:
    """Configuration for a single Bilibili creator account."""

    uid: int
    name: str
    human_tier: int
    agent_tier: int | None
    agent_assessment: str
    description: str
    tags: list[str]
    fetch_subtitles: bool
    fetch_dynamics: bool

    @property
    def effective_tier(self) -> int:
        return self.agent_tier if self.agent_tier is not None else self.human_tier


@dataclass
class RefreshResult:
    """Result of refreshing a single account."""

    new_dynamics: int = 0
    new_subtitles: int = 0
    items: list[dict] = field(default_factory=list)

    @property
    def total_new(self) -> int:
        return self.new_dynamics + self.new_subtitles


def _update_env_var(key: str, value: str, env_path: Path | None = None) -> bool:
    """Update a single variable in the .env file.

    Replaces only the target line, preserving all other content.
    Returns True if the variable was found and updated.
    """
    path = env_path or _ENV_FILE
    if not path.exists():
        logger.warning("[bilibili] .env file not found at %s", path)
        return False

    content = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)

    if pattern.search(content):
        new_content = pattern.sub(lambda _m: f"{key}={value}", content)
        path.write_text(new_content, encoding="utf-8")
        logger.info("[bilibili] Updated %s in .env", key)
        return True
    else:
        # Key not found — append it
        if not content.endswith("\n"):
            content += "\n"
        content += f"{key}={value}\n"
        path.write_text(content, encoding="utf-8")
        logger.info("[bilibili] Appended %s to .env", key)
        return True


def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug, preserving Chinese characters."""
    text = text.strip()
    text = re.sub(r"[^\w\u4e00-\u9fff\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80]


class BilibiliSourceManager:
    """Manages all registered Bilibili creator accounts."""

    def __init__(self, client: BilibiliClient | None = None,
                 config_path: Path | None = None):
        self.config_path = config_path or ACCOUNTS_CONFIG
        self._accounts: list[BilibiliAccountConfig] = []
        self._load_config()

        # Initialize client from env vars if not provided.
        # Client is optional — local store reads don't need API access.
        if client is not None:
            self.client = client
        else:
            try:
                self.client = self._create_client_from_env()
            except ValueError:
                self.client = None

    def _create_client_from_env(self) -> BilibiliClient:
        """Create a BilibiliClient from environment variables."""
        sessdata = os.environ.get("BILIBILI_SESSDATA", "")
        bili_jct = os.environ.get("BILIBILI_BILI_JCT", "")
        buvid3 = os.environ.get("BILIBILI_BUVID3", "")
        refresh_token = os.environ.get("BILIBILI_REFRESH_TOKEN", "")

        if not sessdata or not bili_jct or not buvid3:
            raise ValueError(
                "Bilibili credentials not configured. "
                "Set BILIBILI_SESSDATA, BILIBILI_BILI_JCT, BILIBILI_BUVID3 in .env"
            )

        return BilibiliClient(
            sessdata=sessdata,
            bili_jct=bili_jct,
            buvid3=buvid3,
            refresh_token=refresh_token,
        )

    def _load_config(self) -> None:
        """Load account configuration from YAML file."""
        if not self.config_path.exists():
            logger.warning("[bilibili] Config not found: %s", self.config_path)
            self._accounts = []
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self._accounts = [
            BilibiliAccountConfig(
                uid=a["uid"],
                name=a["name"],
                human_tier=a.get("human_tier", 2),
                agent_tier=a.get("agent_tier"),
                agent_assessment=a.get("agent_assessment", ""),
                description=a.get("description", ""),
                tags=a.get("tags", []),
                fetch_subtitles=a.get("fetch_subtitles", True),
                fetch_dynamics=a.get("fetch_dynamics", True),
            )
            for a in data.get("accounts", [])
        ]
        logger.info("[bilibili] Loaded %d accounts from config", len(self._accounts))

    @property
    def accounts(self) -> list[BilibiliAccountConfig]:
        return list(self._accounts)

    def get_account(self, name: str) -> BilibiliAccountConfig | None:
        for a in self._accounts:
            if a.name == name:
                return a
        return None

    # ── Local JSON store ───────────────────────────────────────────

    def _store_path(self, account_name: str) -> Path:
        """Path to the local JSON store for an account."""
        safe = re.sub(r"[^\w\u4e00-\u9fff]", "_", account_name)
        return SOURCES_DIR / f"{safe}_bilibili.json"

    def _load_store(self, account_name: str) -> dict[str, dict]:
        """Load existing item store. Key = dynamic_id or bvid."""
        path = self._store_path(account_name)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def _save_store(self, account_name: str, store: dict[str, dict]) -> None:
        """Save the item store to disk."""
        SOURCES_DIR.mkdir(parents=True, exist_ok=True)
        path = self._store_path(account_name)
        path.write_text(
            json.dumps(store, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── Refresh ────────────────────────────────────────────────────

    async def refresh_all(
        self,
        max_dynamics_pages: int = 3,
        max_age_days: int = 7,
    ) -> dict[str, RefreshResult]:
        """Fetch new content for all registered accounts.

        Steps:
          1. Check/refresh cookie
          2. For each account: fetch dynamics + subtitles
          3. Dedup and save to local store

        Returns {account_name: RefreshResult}.
        """
        if not self._accounts:
            print("[bilibili] No accounts configured")
            return {}

        if self.client is None:
            raise ValueError(
                "Bilibili client not available. "
                "Set BILIBILI_SESSDATA, BILIBILI_BILI_JCT, BILIBILI_BUVID3 in .env"
            )

        # Step 0: Cookie lifecycle check
        try:
            refreshed, new_cookies = await self.client.refresh_cookie_if_needed()
            if refreshed and new_cookies:
                self._write_back_cookies(new_cookies)
                print("[bilibili] Cookie refreshed and saved to .env")
        except CookieExpiredError as e:
            msg = (
                f"[Financial Agent] Bilibili cookie expired and auto-refresh failed.\n"
                f"Please re-login in browser and update SESSDATA/bili_jct/buvid3 in .env.\n"
                f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
            )
            await send_telegram_alert(msg)
            print(f"[bilibili] Cookie expired, Telegram alert sent. Skipping this run.")
            logger.error("[bilibili] Cookie expired: %s", e)
            return {}

        print(f"[bilibili] Refreshing {len(self._accounts)} accounts")
        since_ts = int(time.time()) - max_age_days * 86400

        results: dict[str, RefreshResult] = {}
        for account in self._accounts:
            try:
                result = await self._refresh_account(
                    account,
                    max_dynamics_pages=max_dynamics_pages,
                    since_ts=since_ts,
                )
                results[account.name] = result
                if result.total_new > 0:
                    print(
                        f"[bilibili] {account.name}: "
                        f"{result.new_dynamics} dynamics, "
                        f"{result.new_subtitles} subtitles"
                    )
                else:
                    print(f"[bilibili] {account.name}: no new content")
            except Exception as e:
                logger.error("[bilibili] Failed to refresh %s: %s", account.name, e)
                print(f"[bilibili] {account.name}: error ({e})")
                results[account.name] = RefreshResult()

        total = sum(r.total_new for r in results.values())
        print(f"[bilibili] Total: {total} new items across all accounts")
        return results

    async def refresh_all_to_inbox(
        self,
        kb: "KnowledgeBase | None" = None,
        max_dynamics_pages: int = 3,
        max_age_days: int = 7,
    ) -> dict:
        """Fetch new content and write directly to inbox.

        Called by refresh_pipeline.py. Returns summary dict.
        """
        from src.knowledge_base.kb_api import KnowledgeBase as KB
        from src.knowledge_base.perception import add_to_inbox

        if kb is None:
            kb = KB()

        results = await self.refresh_all(
            max_dynamics_pages=max_dynamics_pages,
            max_age_days=max_age_days,
        )

        total_items = 0
        for account_name, result in results.items():
            for item in result.items:
                add_to_inbox(
                    content=item["content"],
                    source=item["source"],
                    tier=item["tier"],
                    content_type=item["content_type"],
                    title=item["title"],
                    title_en=item.get("title_en") or None,
                    tags=item["tags"],
                    published_date=item.get("published_date"),
                    kb=kb,
                )
                total_items += 1

        return {"status": "ok", "total_items": total_items, "per_account": {
            name: r.total_new for name, r in results.items()
        }}

    async def refresh_account(
        self,
        name: str,
        max_dynamics_pages: int = 3,
        max_age_days: int = 7,
    ) -> RefreshResult:
        """Fetch new content for a single account by name."""
        if self.client is None:
            raise ValueError(
                "Bilibili client not available. "
                "Set BILIBILI_SESSDATA, BILIBILI_BILI_JCT, BILIBILI_BUVID3 in .env"
            )
        account = self.get_account(name)
        if account is None:
            raise ValueError(f"Account not found: {name}")

        since_ts = int(time.time()) - max_age_days * 86400
        return await self._refresh_account(
            account,
            max_dynamics_pages=max_dynamics_pages,
            since_ts=since_ts,
        )

    async def _refresh_account(
        self,
        account: BilibiliAccountConfig,
        max_dynamics_pages: int = 3,
        since_ts: int = 0,
    ) -> RefreshResult:
        """Internal: fetch and process content for one account."""
        store = self._load_store(account.name)
        result = RefreshResult()
        bvids_to_fetch: list[str] = []

        # Phase 1: Fetch dynamics
        if account.fetch_dynamics:
            dynamics = await self.client.get_all_recent_dynamics(
                uid=account.uid,
                max_pages=max_dynamics_pages,
                since_ts=since_ts,
            )

            for dyn in dynamics:
                # Dedup by dynamic_id
                if dyn.dynamic_id in store:
                    continue

                # Save dynamic to store
                store[dyn.dynamic_id] = self._dynamic_to_store_entry(dyn)

                # Create inbox-ready item for text dynamics
                if dyn.type in (DYNAMIC_TYPE_WORD, DYNAMIC_TYPE_DRAW) and dyn.text:
                    result.items.append(
                        self._make_dynamic_inbox_item(dyn, account)
                    )
                    result.new_dynamics += 1

                # Note bvids for subtitle fetch
                if dyn.type == DYNAMIC_TYPE_AV and dyn.bvid:
                    if dyn.bvid not in store:
                        bvids_to_fetch.append(dyn.bvid)

        # Phase 2: Fetch video subtitles
        if account.fetch_subtitles and bvids_to_fetch:
            for bvid in bvids_to_fetch:
                # Dedup again (may have been added from a different dynamic)
                if bvid in store:
                    continue

                subtitle = await self.client.get_video_subtitle_text(bvid)
                if subtitle is not None:
                    store[bvid] = self._subtitle_to_store_entry(subtitle, account)
                    result.items.append(
                        self._make_subtitle_inbox_item(subtitle, account)
                    )
                    result.new_subtitles += 1
                else:
                    # No subtitle — store minimal entry to avoid re-fetching
                    store[bvid] = {
                        "type": "video_no_subtitle",
                        "bvid": bvid,
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                    }
                    logger.info(
                        "[bilibili] No subtitle for %s, marked in store", bvid,
                    )

        self._save_store(account.name, store)
        return result

    # ── Data formatting helpers ────────────────────────────────────

    @staticmethod
    def _dynamic_to_store_entry(dyn: DynamicItem) -> dict:
        """Convert a DynamicItem to a dict for the local JSON store."""
        # Construct the same title used by _make_dynamic_inbox_item
        pub_date = (
            datetime.fromtimestamp(dyn.timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
            if dyn.timestamp
            else "unknown"
        )
        inbox_title = f"[{dyn.author_name}] 动态 {pub_date}"
        return {
            "type": "dynamic",
            "dynamic_id": dyn.dynamic_id,
            "dynamic_type": dyn.type,
            "text": dyn.text,
            "timestamp": dyn.timestamp,
            "bvid": dyn.bvid,
            "is_charging": dyn.is_charging,
            "author_name": dyn.author_name,
            "author_uid": dyn.author_uid,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "title_en": _translate_title_en(inbox_title),
        }

    @staticmethod
    def _subtitle_to_store_entry(sub: SubtitleResult, account: BilibiliAccountConfig) -> dict:
        """Convert a SubtitleResult to a dict for the local JSON store."""
        # Construct the same title used by _make_subtitle_inbox_item
        inbox_title = f"[{account.name}] {sub.title}"
        return {
            "type": "video_subtitle",
            "bvid": sub.bvid,
            "title": sub.title,
            "subtitle_text": sub.subtitle_text,
            "subtitle_with_ts": sub.subtitle_with_ts,
            "subtitle_type": sub.subtitle_type,
            "duration_seconds": sub.duration_seconds,
            "author_name": account.name,
            "author_uid": account.uid,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "title_en": _translate_title_en(inbox_title),
        }

    @staticmethod
    def _make_dynamic_inbox_item(dyn: DynamicItem, account: BilibiliAccountConfig) -> dict:
        """Build an inbox-ready dict for a text dynamic."""
        pub_date = (
            datetime.fromtimestamp(dyn.timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
            if dyn.timestamp
            else None
        )
        pub_time_utc = (
            datetime.fromtimestamp(dyn.timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if dyn.timestamp
            else "unknown"
        )
        ref = f"{LOCAL_REF_PREFIX}{account.name}/{dyn.dynamic_id}"
        dynamic_url = f"https://t.bilibili.com/{dyn.dynamic_id}"

        tags = list(account.tags)
        if dyn.is_charging:
            tags.append("charging-exclusive")

        content_lines = [
            dyn.text,
            "",
            "---",
            f"Reference: {ref}",
            f"Dynamic URL: {dynamic_url}",
            f"Content Type: text_dynamic",
            f"Published: {pub_time_utc}",
        ]

        title = f"[{account.name}] 动态 {pub_date or 'unknown'}"
        return {
            "content": "\n".join(content_lines),
            "source": f"bilibili_{_slugify(account.name)}",
            "tier": account.effective_tier,
            "content_type": "analysis",
            "title": title,
            "title_en": _translate_title_en(title),
            "tags": tags,
            "published_date": pub_date,
        }

    @staticmethod
    def _make_subtitle_inbox_item(sub: SubtitleResult, account: BilibiliAccountConfig) -> dict:
        """Build an inbox-ready dict for a video subtitle."""
        ref = f"{LOCAL_REF_PREFIX}{account.name}/{sub.bvid}"
        video_url = f"https://www.bilibili.com/video/{sub.bvid}"

        # Format duration as MM:SS
        mins = int(sub.duration_seconds) // 60
        secs = int(sub.duration_seconds) % 60
        duration_str = f"{mins}:{secs:02d}"

        tags = list(account.tags)

        pub_time_utc = (
            datetime.fromtimestamp(sub.publish_timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if sub.publish_timestamp
            else "unknown"
        )

        content_lines = [
            sub.subtitle_text,
            "",
            "---",
            f"Reference: {ref}",
            f"Video URL: {video_url}",
            f"Content Type: video_subtitle ({sub.subtitle_type})",
            f"Duration: {duration_str}",
            f"Published: {pub_time_utc}",
        ]

        title = f"[{account.name}] {sub.title}"
        return {
            "content": "\n".join(content_lines),
            "source": f"bilibili_{_slugify(account.name)}",
            "tier": account.effective_tier,
            "content_type": "analysis",
            "title": title,
            "title_en": _translate_title_en(title),
            "tags": tags,
            "published_date": (
                datetime.fromtimestamp(sub.publish_timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
                if sub.publish_timestamp
                else datetime.now(timezone.utc).strftime("%Y-%m-%d")
            ),
        }

    # ── Cookie write-back ──────────────────────────────────────────

    @staticmethod
    def _write_back_cookies(new_cookies: dict[str, str]) -> None:
        """Write refreshed cookie values back to .env file."""
        env_map = {
            "sessdata": "BILIBILI_SESSDATA",
            "bili_jct": "BILIBILI_BILI_JCT",
            "buvid3": "BILIBILI_BUVID3",
            "refresh_token": "BILIBILI_REFRESH_TOKEN",
        }
        for cookie_key, env_key in env_map.items():
            value = new_cookies.get(cookie_key, "")
            if value:
                _update_env_var(env_key, value)

    # ── Local reference resolution ─────────────────────────────────

    @staticmethod
    def make_reference(account_name: str, item_id: str) -> str:
        """Create a local reference string for an item."""
        return f"{LOCAL_REF_PREFIX}{account_name}/{item_id}"

    def resolve_reference(self, ref: str) -> dict | None:
        """Resolve a local://sources/bilibili/... reference to full item data.

        Returns the item dict from the JSON store, or None if not found.
        """
        if not ref.startswith(LOCAL_REF_PREFIX):
            return None

        path_part = ref[len(LOCAL_REF_PREFIX):]
        slash_idx = path_part.find("/")
        if slash_idx < 0:
            return None

        account_name = path_part[:slash_idx]
        item_id = path_part[slash_idx + 1:]

        store = self._load_store(account_name)
        return store.get(item_id)

    # ── Agent trust tier updates ───────────────────────────────────

    def update_agent_tier(
        self, account_name: str, tier: int, assessment: str = ""
    ) -> bool:
        """Allow the agent to update its own trust assessment for a source.

        Writes back to bilibili_accounts.yaml.
        """
        if not self.config_path.exists():
            return False

        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        updated = False
        for account in data.get("accounts", []):
            if account["name"] == account_name:
                account["agent_tier"] = tier
                if assessment:
                    account["agent_assessment"] = assessment
                updated = True
                break

        if updated:
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    data, f,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )
            self._load_config()

        return updated
