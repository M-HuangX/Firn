"""Web search tools — Tavily-powered search and URL extraction.

Provides two LangChain @tool functions for CoreAgent:
- web_search: search the web for financial information
- fetch_url: fetch and read full content of a specific URL

Graceful degradation: returns error message if TAVILY_API_KEY not set.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
from urllib.parse import urlparse

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_MAX_SEARCH_CHARS = 15000
_MAX_FETCH_CHARS = 20000

# Lazy singleton
_tavily_client = None


def _get_client():
    """Get or create TavilyClient singleton."""
    global _tavily_client
    if _tavily_client is None:
        from tavily import TavilyClient
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            raise ValueError("TAVILY_API_KEY not configured")
        _tavily_client = TavilyClient(api_key=api_key)
    return _tavily_client


_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
]


def _is_url_safe(url: str) -> bool:
    """Check that URL does not point to a private/internal network address."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return False
    if hostname in ("localhost", "0.0.0.0"):
        return False
    try:
        addr = ipaddress.ip_address(hostname)
        return not any(addr in net for net in _BLOCKED_NETWORKS)
    except ValueError:
        # hostname is a domain name, not a raw IP — allow
        return True


def _sanitize_content(text: str) -> str:
    """Remove potential prompt injection patterns from web content."""
    patterns = [
        r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts)",
        r"(?i)you\s+are\s+now\s+",
        r"(?i)new\s+instructions?\s*:",
        r"(?i)system\s*:\s*",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "[REDACTED]", text)
    return text


@tool
def web_search(query: str, topic: str = "finance", max_results: int = 5) -> str:
    """Search the web for current information on stocks, markets, or financial news.

    Use this to:
    - Verify recent earnings, guidance, or news
    - Check analyst ratings and price targets
    - Confirm macroeconomic data (Fed decisions, inflation)
    - Find recent company announcements

    Args:
        query: Natural language search query (e.g., "NVDA Q1 2026 earnings")
        topic: "general", "news", or "finance" (default: finance)
        max_results: Number of results, 1-10 (default: 5)

    Returns:
        Formatted search results with AI summary and full content.
    """
    if not os.getenv("TAVILY_API_KEY"):
        return "Web search unavailable: TAVILY_API_KEY not configured."

    try:
        client = _get_client()
        results = client.search(
            query=query,
            max_results=min(max_results, 10),
            topic=topic if topic in ("general", "news", "finance") else "finance",
            search_depth="advanced",
            include_answer=True,
        )

        parts = [f"Search results for: {query}\n"]

        if results.get("answer"):
            parts.append(f"**Summary**: {results['answer']}\n")

        for i, r in enumerate(results.get("results", []), 1):
            content = _sanitize_content(r.get("content", ""))
            parts.append(
                f"[{i}] {r.get('title', 'Untitled')}\n"
                f"    URL: {r.get('url', '')}\n"
                f"    {content}\n"
            )

        output = "\n".join(parts)
        if len(output) > _MAX_SEARCH_CHARS:
            output = output[:_MAX_SEARCH_CHARS] + "\n[... truncated ...]"
        return output

    except Exception as e:
        return f"Search error: {e}"


@tool
def fetch_url(url: str) -> str:
    """Fetch and read the full content of a specific web page.

    Use this after web_search when you need the complete article text.

    Args:
        url: Full URL to fetch (must start with http:// or https://)

    Returns:
        Page content as text, truncated to ~4000 chars.
    """
    if not url.startswith(("http://", "https://")):
        return f"Invalid URL: must start with http:// or https://"

    if not _is_url_safe(url):
        return "Error: URL points to a private/internal network address."

    if not os.getenv("TAVILY_API_KEY"):
        return "URL fetch unavailable: TAVILY_API_KEY not configured."

    try:
        client = _get_client()
        result = client.extract(urls=[url])

        if result.get("results"):
            content = result["results"][0].get("raw_content", "")
            content = _sanitize_content(content)
            if len(content) > _MAX_FETCH_CHARS:
                content = content[:_MAX_FETCH_CHARS] + "\n[... truncated ...]"
            return content or "Page returned empty content."

        failed = result.get("failed_results", [])
        if failed:
            return f"Failed to fetch URL: {failed[0] if failed else url}"
        return "No content extracted from URL."

    except Exception as e:
        # Fallback: try httpx directly
        try:
            import httpx
            resp = httpx.get(url, timeout=15, follow_redirects=True)
            resp.raise_for_status()
            # Try markdownify for cleaner output
            try:
                from markdownify import markdownify
                content = markdownify(resp.text)
            except ImportError:
                content = resp.text
            content = _sanitize_content(content)
            if len(content) > _MAX_FETCH_CHARS:
                content = content[:_MAX_FETCH_CHARS] + "\n[... truncated ...]"
            return content
        except Exception as fallback_err:
            return f"Fetch error: {e} (fallback also failed: {fallback_err})"


# Export list for CoreAgent
WEB_TOOLS: list = [web_search, fetch_url]
