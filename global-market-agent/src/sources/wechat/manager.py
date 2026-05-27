"""
WechatSourceManager — unified manager for all WeChat Official Account sources.

Two entry points, same pipeline:
  1. Cron (daily before market open): manager.refresh_all()
  2. Manual (user triggers mid-day): same call

No agent-side tools. The agent consumes digested KB knowledge,
not raw articles. Articles are processed through the Perception pipeline.

Local reference protocol:
  local://sources/ExampleAnalyst/article-title-here
  → resolves to full article content from local JSON store
"""

import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .scraper import SogouWechatScraper, WechatArticle


SOURCES_DIR = Path(__file__).resolve().parents[3] / "data" / "sources"
ACCOUNTS_CONFIG = SOURCES_DIR / "wechat_accounts.yaml"
LOCAL_REF_PREFIX = "local://sources/"


@dataclass
class AccountConfig:
    name: str
    human_tier: int
    agent_tier: Optional[int]
    agent_assessment: str
    description: str
    tags: list[str]

    @property
    def effective_tier(self) -> int:
        return self.agent_tier if self.agent_tier is not None else self.human_tier


class WechatSourceManager:
    """Manages all registered WeChat OA sources."""

    def __init__(self, config_path: Optional[Path] = None, delay: float = 3.0):
        self.config_path = config_path or ACCOUNTS_CONFIG
        self.scraper = SogouWechatScraper(store_dir=SOURCES_DIR, delay=delay)
        self._accounts: list[AccountConfig] = []
        self._load_config()

    def _load_config(self) -> None:
        if not self.config_path.exists():
            self._accounts = []
            return
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self._accounts = [
            AccountConfig(
                name=a["name"],
                human_tier=a.get("human_tier", 3),
                agent_tier=a.get("agent_tier"),
                agent_assessment=a.get("agent_assessment", ""),
                description=a.get("description", ""),
                tags=a.get("tags", []),
            )
            for a in data.get("accounts", [])
        ]

    @property
    def accounts(self) -> list[AccountConfig]:
        return list(self._accounts)

    def get_account(self, name: str) -> Optional[AccountConfig]:
        for a in self._accounts:
            if a.name == name:
                return a
        return None

    # ── Refresh ────────────────────────────────────────────────────

    def refresh_all(
        self, pages: int = 3, max_age_days: int = 30
    ) -> dict[str, list[WechatArticle]]:
        """
        Fetch new articles for all registered accounts.
        Returns {account_name: [new_articles]}.
        """
        results = {}
        for account in self._accounts:
            new_articles = self.scraper.fetch_new_articles(
                account.name,
                pages=pages,
                max_age_days=max_age_days,
                fetch_content=True,
            )
            results[account.name] = new_articles
        return results

    def refresh_account(
        self, name: str, pages: int = 3, max_age_days: int = 30
    ) -> list[WechatArticle]:
        """Fetch new articles for a single account."""
        return self.scraper.fetch_new_articles(
            name, pages=pages, max_age_days=max_age_days, fetch_content=True
        )

    # ── Local reference resolution ─────────────────────────────────

    @staticmethod
    def make_reference(account: str, title: str) -> str:
        """Create a local reference string for an article."""
        return f"{LOCAL_REF_PREFIX}{account}/{title}"

    def resolve_reference(self, ref: str) -> Optional[dict]:
        """
        Resolve a local://sources/... reference to full article data.
        Returns the article dict from the JSON store, or None if not found.
        """
        if not ref.startswith(LOCAL_REF_PREFIX):
            return None

        path_part = ref[len(LOCAL_REF_PREFIX):]
        # Split on first / to get account and title
        slash_idx = path_part.find("/")
        if slash_idx < 0:
            return None

        account = path_part[:slash_idx]
        title = path_part[slash_idx + 1:]

        store = self.scraper._load_store(account)
        return store.get(title)

    def get_recent_articles(
        self, account_name: str, limit: int = 10, days: int = 30
    ) -> list[dict]:
        """Get recent stored articles for an account (no network fetch)."""
        import time as _time

        cutoff = int(_time.time()) - days * 86400
        articles = self.scraper.get_stored_articles(account_name)
        filtered = [a for a in articles if a.get("timestamp", 0) >= cutoff]
        return filtered[:limit]

    # ── Agent trust tier updates ───────────────────────────────────

    def update_agent_tier(
        self, account_name: str, tier: int, assessment: str = ""
    ) -> bool:
        """
        Allow the agent to update its own trust assessment for a source.
        Writes back to wechat_accounts.yaml.
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
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            self._load_config()  # reload

        return updated
