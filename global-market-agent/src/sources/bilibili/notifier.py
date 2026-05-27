"""
Bilibili Telegram notifier — send alerts when cookie refresh fails.

Minimal module: reads bot token and chat ID from env vars,
sends a message via Telegram Bot API, logs failures silently.
Notification failure must never block the main pipeline.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


async def send_telegram_alert(message: str) -> bool:
    """Send an alert message via Telegram Bot API.

    Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from environment.
    Returns True if sent successfully, False otherwise.
    Logs errors but never raises — notification failure is non-fatal.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        logger.warning(
            "[bilibili] Telegram alert skipped: TELEGRAM_BOT_TOKEN or "
            "TELEGRAM_CHAT_ID not configured"
        )
        return False

    url = TELEGRAM_API_URL.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            logger.info("[bilibili] Telegram alert sent successfully")
            return True
    except Exception as e:
        logger.error("[bilibili] Telegram alert failed: %s", e)
        return False
