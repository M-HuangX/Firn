"""
Sogou WeChat scraper — fetch articles from WeChat Official Accounts
via weixin.sogou.com search without requiring a WeChat login.

Usage:
    from src.sources.wechat.scraper import SogouWechatScraper

    scraper = SogouWechatScraper()
    new_articles = scraper.fetch_new_articles("ExampleAccount", pages=3)
"""

import json
import re
import time
import html as html_lib
import urllib.request
import urllib.parse
import http.cookiejar
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# Default store location
DEFAULT_STORE_DIR = Path(__file__).resolve().parents[3] / "data" / "sources"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _translate_title_en(title: str) -> str:
    """Translate a CJK title to English. Returns '' if not CJK or on failure."""
    if not any('\u4e00' <= c <= '\u9fff' for c in title):
        return ""
    from src.knowledge_base.perception import _translate_single_title
    return _translate_single_title(title)


@dataclass
class WechatArticle:
    title: str
    account: str
    timestamp: int  # unix
    summary: str
    sogou_link: str
    wechat_url: str = ""
    content: str = ""
    fetched_at: str = ""

    @property
    def date_str(self) -> str:
        return datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d")


class SogouWechatScraper:
    """Scrapes Sogou WeChat search for articles from a specific Official Account."""

    def __init__(self, store_dir: Optional[Path] = None, delay: float = 2.0):
        self.store_dir = store_dir or DEFAULT_STORE_DIR
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay  # seconds between requests to avoid anti-spider
        self._cookie_jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookie_jar)
        )

    def _store_path(self, account: str) -> Path:
        safe = re.sub(r"[^\w\u4e00-\u9fff]", "_", account)
        return self.store_dir / f"{safe}_articles.json"

    def _load_store(self, account: str) -> dict[str, dict]:
        """Load existing article store. Key = title."""
        path = self._store_path(account)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def _save_store(self, account: str, store: dict[str, dict]) -> None:
        path = self._store_path(account)
        path.write_text(
            json.dumps(store, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _request(self, url: str, referer: str = "") -> str:
        headers = {**HEADERS}
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        resp = self._opener.open(req, timeout=20)
        return resp.read().decode("utf-8", errors="ignore")

    # ── Search parsing ─────────────────────────────────────────────

    def _search_url(self, query: str, page: int) -> str:
        params = urllib.parse.urlencode({
            "query": query,
            "type": "2",
            "s_from": "input",
            "page": str(page),
            "ie": "utf8",
        })
        return f"https://weixin.sogou.com/weixin?{params}"

    def _parse_search_page(self, html_content: str) -> list[WechatArticle]:
        """Extract articles from a Sogou search results page."""
        articles = []

        # Find all <li> items inside the news-list
        ul_match = re.search(
            r'<ul class="news-list"[^>]*>(.*?)</ul>', html_content, re.DOTALL
        )
        if not ul_match:
            return articles

        items = re.findall(r"<li[^>]*>(.*?)</li>", ul_match.group(1), re.DOTALL)

        for item in items:
            # Title + link
            title_match = re.search(
                r'<h3>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>\s*</h3>',
                item, re.DOTALL,
            )
            if not title_match:
                continue

            sogou_path = html_lib.unescape(title_match.group(1))
            raw_title = title_match.group(2)
            # Strip <em>, <!--red_beg-->, etc.
            title = re.sub(r"<[^>]+>", "", raw_title)
            title = re.sub(r"<!--.*?-->", "", title)
            title = html_lib.unescape(title).strip()

            # Account name
            account_match = re.search(
                r'class="all-time-y2"[^>]*>(.*?)</span>', item
            )
            account = account_match.group(1).strip() if account_match else ""

            # Timestamp
            ts_match = re.search(r"timeConvert\('(\d+)'\)", item)
            timestamp = int(ts_match.group(1)) if ts_match else 0

            # Summary
            summary_match = re.search(
                r'class="txt-info"[^>]*>(.*?)</p>', item, re.DOTALL
            )
            summary = ""
            if summary_match:
                summary = re.sub(r"<[^>]+>", "", summary_match.group(1))
                summary = re.sub(r"<!--.*?-->", "", summary)
                summary = html_lib.unescape(summary).strip()

            # Build full Sogou link
            if sogou_path.startswith("/"):
                sogou_link = "https://weixin.sogou.com" + sogou_path
            else:
                sogou_link = sogou_path

            articles.append(WechatArticle(
                title=title,
                account=account,
                timestamp=timestamp,
                summary=summary,
                sogou_link=sogou_link,
            ))

        return articles

    # ── Article content fetching ───────────────────────────────────

    def _resolve_wechat_url(self, sogou_link: str, referer: str) -> str:
        """Follow Sogou redirect to extract real mp.weixin.qq.com URL."""
        js_page = self._request(sogou_link, referer=referer)
        parts = re.findall(r"url \+= '([^']*)'", js_page)
        if not parts:
            return ""
        real_url = "".join(parts).replace("@", "")
        if "mp.weixin.qq.com" in real_url:
            return real_url
        return ""

    def _fetch_article_content(self, wechat_url: str) -> str:
        """Fetch article full text from mp.weixin.qq.com."""
        html_content = self._request(wechat_url)
        # Content is in <div id="js_content">
        match = re.search(
            r'id="js_content"[^>]*>(.*?)</div>\s*(?:<div|<script)',
            html_content, re.DOTALL,
        )
        if not match:
            # Fallback: try a broader match
            match = re.search(
                r'id="js_content"[^>]*>(.*?)</div>',
                html_content, re.DOTALL,
            )
        if match:
            text = re.sub(r"<[^>]+>", "", match.group(1))
            text = html_lib.unescape(text)
            text = re.sub(r"\s+", " ", text).strip()
            # Remove common boilerplate
            text = re.sub(r"点击上方蓝字关注我们", "", text).strip()
            return text
        # Fallback: og:description
        og = re.search(r'property="og:description"\s+content="([^"]+)"', html_content)
        return og.group(1) if og else ""

    # ── Main API ───────────────────────────────────────────────────

    def search_articles(
        self, account_name: str, pages: int = 3, max_age_days: int = 30
    ) -> list[WechatArticle]:
        """Search Sogou and return articles matching the exact account name."""
        cutoff_ts = int(time.time()) - max_age_days * 86400
        all_articles = []
        for page in range(1, pages + 1):
            url = self._search_url(account_name, page)
            try:
                html_content = self._request(url)
                articles = self._parse_search_page(html_content)
                all_articles.extend(articles)
            except Exception as e:
                print(f"  [!] Page {page} fetch failed: {e}")
            if page < pages:
                time.sleep(self.delay)

        # Filter: exact account name match + within max_age_days
        filtered = [
            a for a in all_articles
            if a.account == account_name and a.timestamp >= cutoff_ts
        ]
        # Sort by timestamp descending (newest first)
        filtered.sort(key=lambda a: a.timestamp, reverse=True)
        return filtered

    def fetch_new_articles(
        self,
        account_name: str,
        pages: int = 3,
        max_age_days: int = 30,
        fetch_content: bool = True,
    ) -> list[WechatArticle]:
        """
        Search, deduplicate against local store, fetch content for new articles,
        and update the store. Returns only the newly discovered articles.
        """
        print(f"[sogou] Searching for '{account_name}' (pages 1-{pages}, max {max_age_days}d)...")
        candidates = self.search_articles(account_name, pages=pages, max_age_days=max_age_days)
        print(f"[sogou] Found {len(candidates)} articles from '{account_name}'")

        store = self._load_store(account_name)
        new_articles = [a for a in candidates if a.title not in store]

        if not new_articles:
            print("[sogou] No new articles found.")
            return []

        print(f"[sogou] {len(new_articles)} new articles to process")

        search_url = self._search_url(account_name, 1)

        for i, article in enumerate(new_articles):
            if fetch_content:
                try:
                    time.sleep(self.delay)
                    wechat_url = self._resolve_wechat_url(
                        article.sogou_link, referer=search_url
                    )
                    if wechat_url:
                        article.wechat_url = wechat_url
                        time.sleep(self.delay)
                        article.content = self._fetch_article_content(wechat_url)
                        print(
                            f"  [{i+1}/{len(new_articles)}] {article.title} "
                            f"({len(article.content)} chars)"
                        )
                    else:
                        print(f"  [{i+1}/{len(new_articles)}] {article.title} (URL resolve failed)")
                except Exception as e:
                    print(f"  [{i+1}/{len(new_articles)}] {article.title} (error: {e})")

            article.fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry = asdict(article)
            full_title = f"[{account_name}] {article.title}"
            entry["title_en"] = _translate_title_en(full_title)
            store[article.title] = entry

        self._save_store(account_name, store)
        print(f"[sogou] Store updated: {len(store)} total articles")
        return new_articles

    def get_stored_articles(self, account_name: str) -> list[dict]:
        """Return all stored articles for an account, sorted by timestamp desc."""
        store = self._load_store(account_name)
        articles = list(store.values())
        articles.sort(key=lambda a: a.get("timestamp", 0), reverse=True)
        return articles
