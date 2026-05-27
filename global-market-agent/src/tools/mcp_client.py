"""MCP client — fetches LangChain-compatible tools from the MCP server.

Uses ``langchain-mcp-adapters`` to connect via stdio transport and convert
MCP tools into LangChain ``BaseTool`` instances that can be passed directly
to ``create_react_agent``.

The client is initialised lazily on first call and cached for the process
lifetime.
"""

from __future__ import annotations

import asyncio
import logging

from langchain_mcp_adapters.client import MultiServerMCPClient

from src.tools.mcp_config import SERVER_CONFIGS

logger = logging.getLogger(__name__)

_client: MultiServerMCPClient | None = None
_tools: list | None = None
_init_lock = asyncio.Lock()


async def get_mcp_tools() -> list:
    """Return the list of LangChain tools from the MCP server.

    The first call initialises the ``MultiServerMCPClient`` and fetches
    tools; subsequent calls return the cached list.  An ``asyncio.Lock``
    prevents duplicate initialisation when parallel agents call this
    concurrently.

    Returns:
        List of LangChain ``BaseTool`` instances (may be empty on failure).
    """
    global _client, _tools

    if _tools is not None:
        return _tools

    async with _init_lock:
        # Double-check after acquiring lock (another coroutine may have initialised)
        if _tools is not None:
            return _tools

        logger.info("Initialising MCP client with config: %s", SERVER_CONFIGS)
        try:
            _client = MultiServerMCPClient(SERVER_CONFIGS)
            loaded = await _client.get_tools()

            if not loaded:
                logger.warning("MCP server returned 0 tools — check server logs.")
                _tools = []
                return []

            _tools = loaded
            names = [t.name for t in _tools]
            logger.info("Loaded %d MCP tools: %s", len(_tools), names)
            return _tools

        except Exception:
            logger.exception("Failed to initialise MCP client or load tools")
            return []


async def close_mcp_client() -> None:
    """Release MCP client resources (call on shutdown)."""
    global _client, _tools
    if _client is not None:
        try:
            # MultiServerMCPClient may expose __aexit__ or close methods
            if hasattr(_client, "__aexit__"):
                await _client.__aexit__(None, None, None)
            elif hasattr(_client, "close"):
                await _client.close()
        except Exception:
            logger.debug("Error closing MCP client (non-fatal)", exc_info=True)
    _client = None
    _tools = None
