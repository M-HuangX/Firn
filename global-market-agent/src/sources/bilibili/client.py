"""
Bilibili API client — thin wrapper around bilibili-api-python.

Handles credential lifecycle, rate limiting, and exposes only
the methods we need: video subtitles and user dynamics.

Usage:
    from src.sources.bilibili.client import BilibiliClient

    client = BilibiliClient(sessdata="...", bili_jct="...", buvid3="...",
                            refresh_token="...")
    subtitle = await client.get_video_subtitle_text("BV1xxxxxxxxxx")
    dynamics = await client.get_all_recent_dynamics(uid=12345678)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx
from bilibili_api import Credential, select_client, user, video

logger = logging.getLogger(__name__)

# Use curl_cffi backend for browser-grade TLS fingerprints (anti-412).
# In bilibili-api-python >=17.4, curl_cffi is the default, but we
# explicitly select it to be safe.
select_client("curl_cffi")

# Subtitle language preference (highest priority first)
_SUBTITLE_LANG_PRIORITY = ["ai-zh", "zh-CN", "zh-Hans", "zh"]

# Dynamic types we care about
DYNAMIC_TYPE_WORD = "DYNAMIC_TYPE_WORD"        # pure text dynamic
DYNAMIC_TYPE_DRAW = "DYNAMIC_TYPE_DRAW"        # text + images
DYNAMIC_TYPE_AV = "DYNAMIC_TYPE_AV"            # video dynamic
DYNAMIC_TYPE_FORWARD = "DYNAMIC_TYPE_FORWARD"  # repost (skip)
DYNAMIC_TYPE_LIVE = "DYNAMIC_TYPE_LIVE_RCMD"   # live stream (skip)


class CookieExpiredError(Exception):
    """Raised when Bilibili cookie is expired and auto-refresh failed."""


@dataclass
class SubtitleResult:
    """Extracted subtitle data from a Bilibili video."""

    bvid: str
    title: str
    subtitle_text: str                          # joined content, no timestamps
    subtitle_with_ts: list[dict] = field(default_factory=list)  # [{"from": 0.0, "to": 3.5, "content": "..."}]
    subtitle_type: str = ""                     # "ai-zh" | "zh-CN" | etc.
    duration_seconds: float = 0.0
    publish_timestamp: int = 0                  # video publish time (unix seconds)


@dataclass
class DynamicItem:
    """A single dynamic entry from a user's feed."""

    dynamic_id: str
    type: str                   # DYNAMIC_TYPE_WORD | DYNAMIC_TYPE_AV | etc.
    text: str                   # extracted plain text
    timestamp: int              # unix seconds
    bvid: str | None = None     # if video dynamic, the associated bvid
    is_charging: bool = False   # basic.is_only_fans
    author_name: str = ""
    author_uid: int = 0


@dataclass
class DynamicPage:
    """One page of dynamics from a user's feed."""

    items: list[DynamicItem] = field(default_factory=list)
    has_more: bool = False
    offset: str = ""


def _mask_cookie(value: str) -> str:
    """Mask cookie value for safe logging (show first 4 chars only)."""
    if not value or len(value) <= 4:
        return "****"
    return value[:4] + "****"


class BilibiliClient:
    """Thin wrapper around bilibili-api-python for our specific needs.

    Provides: login check, cookie refresh, video subtitles, user dynamics.
    All methods are async (the underlying library is fully async).
    """

    def __init__(
        self,
        sessdata: str,
        bili_jct: str,
        buvid3: str,
        refresh_token: str | None = None,
        request_interval: float = 2.5,
    ):
        self.credential = Credential(
            sessdata=sessdata,
            bili_jct=bili_jct,
            buvid3=buvid3,
            ac_time_value=refresh_token or "",
        )
        self._interval = request_interval
        self._last_request_ts: float = 0.0

        logger.info(
            "[bilibili] Client initialized (sessdata=%s, interval=%.1fs)",
            _mask_cookie(sessdata),
            request_interval,
        )

    # ── Rate limiting ──────────────────────────────────────────────

    async def _rate_limit(self) -> None:
        """Enforce minimum interval between API requests."""
        now = time.monotonic()
        elapsed = now - self._last_request_ts
        if elapsed < self._interval:
            wait = self._interval - elapsed
            await asyncio.sleep(wait)
        self._last_request_ts = time.monotonic()

    # ── Auth ───────────────────────────────────────────────────────

    async def check_login_status(self) -> bool:
        """Check if the current credential is still valid.

        Returns True if logged in, False otherwise.
        """
        try:
            result = await self.credential.check_valid()
            return bool(result)
        except Exception as e:
            logger.warning("[bilibili] Login check failed: %s", e)
            return False

    async def check_refresh_needed(self) -> bool:
        """Check if the credential needs refreshing.

        Returns True if a refresh is needed.
        """
        try:
            return await self.credential.check_refresh()
        except Exception as e:
            logger.warning("[bilibili] Refresh check failed: %s", e)
            return False

    async def refresh_cookie_if_needed(self) -> tuple[bool, dict[str, str]]:
        """Auto-refresh cookie if needed.

        Returns (refreshed: bool, new_cookies: dict).
        new_cookies is empty if no refresh happened.

        Note: B站 deprecated ac_time_value (refresh_token) in late 2024.
        Without it, auto-refresh is not possible. In that case we just
        verify the current cookie is still valid and raise CookieExpiredError
        if it's not.
        """
        # If no refresh token, skip refresh attempt — just validate current cookie
        if not self.credential.ac_time_value:
            is_valid = await self.check_login_status()
            if is_valid:
                logger.info("[bilibili] Cookie valid (no refresh_token, skip refresh)")
                return False, {}
            raise CookieExpiredError(
                "Bilibili cookie expired. ac_time_value unavailable "
                "(deprecated by B站 since late 2024), cannot auto-refresh. "
                "Please re-login in browser and update .env."
            )

        try:
            needs_refresh = await self.check_refresh_needed()
            if not needs_refresh:
                logger.info("[bilibili] Cookie still valid, no refresh needed")
                return False, {}

            logger.info("[bilibili] Cookie needs refresh, attempting...")
            await self.credential.refresh()

            new_cookies = {
                "sessdata": self.credential.sessdata or "",
                "bili_jct": self.credential.bili_jct or "",
                "refresh_token": self.credential.ac_time_value or "",
            }

            logger.info(
                "[bilibili] Cookie refreshed successfully (new sessdata=%s)",
                _mask_cookie(new_cookies["sessdata"]),
            )
            return True, new_cookies

        except Exception as e:
            logger.error("[bilibili] Cookie refresh failed: %s", e)
            raise CookieExpiredError(
                f"Bilibili cookie expired and auto-refresh failed: {e}"
            ) from e

    # ── Video APIs ─────────────────────────────────────────────────

    async def get_video_subtitle_text(self, bvid: str, _is_retry: bool = False) -> SubtitleResult | None:
        """Fetch video subtitle text for the given bvid.

        Returns SubtitleResult with joined text, or None if no subtitle available.
        Prefers ai-zh > zh-CN > zh-Hans > zh.
        """
        await self._rate_limit()

        try:
            v = video.Video(bvid=bvid, credential=self.credential)
            info = await v.get_info()
            title = info.get("title", bvid)
            duration = info.get("duration", 0)
            pubdate = info.get("pubdate", 0)
            cid = info.get("cid")

            # Get player info which contains subtitle list (requires cid)
            await self._rate_limit()
            player_info = await v.get_player_info(cid=cid)

            subtitle_list = (
                player_info.get("subtitle", {}).get("subtitles", [])
            )
            if not subtitle_list:
                logger.info("[bilibili] No subtitles for %s (%s)", bvid, title)
                return None

            # Pick best subtitle by language priority
            chosen = None
            chosen_lang = ""
            for pref_lang in _SUBTITLE_LANG_PRIORITY:
                for sub in subtitle_list:
                    if sub.get("lan", "") == pref_lang:
                        chosen = sub
                        chosen_lang = pref_lang
                        break
                if chosen:
                    break

            # Fallback: take first available
            if not chosen:
                chosen = subtitle_list[0]
                chosen_lang = chosen.get("lan", "unknown")

            # Download subtitle JSON
            sub_url = chosen.get("subtitle_url", "")
            if not sub_url:
                logger.warning("[bilibili] Subtitle URL empty for %s", bvid)
                return None

            # URL may need https: prefix
            if sub_url.startswith("//"):
                sub_url = "https:" + sub_url

            await self._rate_limit()
            async with httpx.AsyncClient(timeout=15.0) as http_client:
                resp = await http_client.get(sub_url)
                resp.raise_for_status()
                sub_data = resp.json()

            body = sub_data.get("body", [])
            if not body:
                logger.info("[bilibili] Empty subtitle body for %s", bvid)
                return None

            # Extract text
            subtitle_text = "\n".join(item["content"] for item in body if "content" in item)

            result = SubtitleResult(
                bvid=bvid,
                title=title,
                subtitle_text=subtitle_text,
                subtitle_with_ts=body,
                subtitle_type=chosen_lang,
                duration_seconds=float(duration),
                publish_timestamp=int(pubdate) if pubdate else 0,
            )

            logger.info(
                "[bilibili] Subtitle fetched: %s (%s, %d chars, lang=%s)",
                bvid, title, len(subtitle_text), chosen_lang,
            )
            return result

        except Exception as e:
            if "412" in str(e) and not _is_retry:
                return await self._retry_on_412(
                    self.get_video_subtitle_text, bvid, True,
                    context=f"subtitle for {bvid}",
                )
            logger.error("[bilibili] Failed to get subtitle for %s: %s", bvid, e)
            return None

    # ── Dynamic APIs ───────────────────────────────────────────────

    async def get_user_dynamics(self, uid: int, offset: str = "", _is_retry: bool = False) -> DynamicPage:
        """Fetch one page of dynamics for the given user.

        Args:
            uid: Bilibili user ID.
            offset: Pagination offset (empty for first page).

        Returns:
            DynamicPage with items, has_more flag, and next offset.
        """
        await self._rate_limit()

        try:
            u = user.User(uid=uid, credential=self.credential)
            data = await u.get_dynamics_new(offset=offset)

            items: list[DynamicItem] = []
            for item in data.get("items", []):
                parsed = self._parse_dynamic_item(item, uid)
                if parsed is not None:
                    items.append(parsed)

            has_more = bool(data.get("has_more", False))
            next_offset = str(data.get("offset", ""))

            return DynamicPage(items=items, has_more=has_more, offset=next_offset)

        except Exception as e:
            if "412" in str(e) and not _is_retry:
                result = await self._retry_on_412(
                    self.get_user_dynamics, uid, offset, True,
                    context=f"dynamics for uid={uid}",
                )
                return result if result is not None else DynamicPage()
            logger.error("[bilibili] Failed to get dynamics for uid=%d: %s", uid, e)
            return DynamicPage()

    async def get_all_recent_dynamics(
        self,
        uid: int,
        max_pages: int = 3,
        since_ts: int = 0,
    ) -> list[DynamicItem]:
        """Fetch multiple pages of recent dynamics, stopping at since_ts.

        Args:
            uid: Bilibili user ID.
            max_pages: Maximum number of pages to fetch.
            since_ts: Stop fetching when we see items older than this timestamp.

        Returns:
            List of DynamicItem, newest first.
        """
        all_items: list[DynamicItem] = []
        offset = ""

        for page_num in range(1, max_pages + 1):
            page = await self.get_user_dynamics(uid, offset=offset)

            if not page.items:
                break

            reached_cutoff = False
            seen_newer = False
            for item in page.items:
                if since_ts > 0 and item.timestamp < since_ts:
                    if seen_newer:
                        # Truly past the cutoff (items are chronological after pinned)
                        reached_cutoff = True
                        break
                    # Skip out-of-order old items (e.g. pinned posts)
                    continue
                seen_newer = True
                all_items.append(item)

            if reached_cutoff or not page.has_more:
                break

            offset = page.offset
            logger.info(
                "[bilibili] Fetched dynamics page %d for uid=%d (%d items so far)",
                page_num, uid, len(all_items),
            )

        logger.info(
            "[bilibili] Total %d dynamics fetched for uid=%d",
            len(all_items), uid,
        )
        return all_items

    # ── Internal helpers ───────────────────────────────────────────

    def _parse_dynamic_item(self, raw: dict, uid: int) -> DynamicItem | None:
        """Parse a raw dynamic API item into a DynamicItem.

        Returns None for unsupported types (FORWARD, LIVE, etc.).
        """
        dynamic_id = raw.get("id_str", "")
        dynamic_type = raw.get("type", "")

        # Skip unsupported types
        if dynamic_type in (DYNAMIC_TYPE_FORWARD, DYNAMIC_TYPE_LIVE):
            return None

        modules = raw.get("modules", {})

        # Author info
        author_module = modules.get("module_author", {})
        author_name = author_module.get("name", "")
        author_uid = author_module.get("mid", uid)
        pub_ts_raw = author_module.get("pub_ts", 0)
        pub_ts = int(pub_ts_raw) if pub_ts_raw else 0

        # Charging status
        is_charging = raw.get("basic", {}).get("is_only_fans", False)

        # Extract text content
        text = ""
        dynamic_module = modules.get("module_dynamic", {})
        desc = dynamic_module.get("desc")
        if desc and isinstance(desc, dict):
            text = desc.get("text", "")

        # Extract bvid for video dynamics, and text from OPUS/archive
        bvid: str | None = None
        major = dynamic_module.get("major")
        if major and isinstance(major, dict):
            major_type = major.get("type", "")

            archive = major.get("archive")
            if archive and isinstance(archive, dict):
                bvid = archive.get("bvid")
                # For video dynamics, if no text in desc, use video title
                if not text:
                    text = archive.get("title", "")

            # MAJOR_TYPE_OPUS: B站 rich-text post format (图文动态)
            # Text lives in opus.summary.text, not in desc
            if not text and major_type == "MAJOR_TYPE_OPUS":
                opus = major.get("opus")
                if opus and isinstance(opus, dict):
                    summary = opus.get("summary", {})
                    text = summary.get("text", "")

        # Skip items with no useful text
        if not text and not bvid:
            return None

        return DynamicItem(
            dynamic_id=dynamic_id,
            type=dynamic_type,
            text=text,
            timestamp=pub_ts,
            bvid=bvid,
            is_charging=is_charging,
            author_name=author_name,
            author_uid=author_uid,
        )

    async def _retry_on_412(self, func, *args, context: str = ""):
        """Retry a function once after 30s backoff on 412 error."""
        logger.warning(
            "[bilibili] 412 error for %s, retrying in 30s...", context,
        )
        await asyncio.sleep(30)
        try:
            return await func(*args)
        except Exception as retry_err:
            logger.error(
                "[bilibili] 412 retry failed for %s: %s", context, retry_err,
            )
            return None
