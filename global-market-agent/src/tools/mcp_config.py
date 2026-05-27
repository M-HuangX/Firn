"""MCP server connection configuration.

The agent system connects to the global-market-mcp server via stdio transport.
The server path is resolved relative to this project's root directory, or can
be overridden via environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path

# Resolve default MCP server directory relative to this project.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # global-market-agent/
_DEFAULT_MCP_DIR = str(_PROJECT_ROOT.parent / "global-market-mcp")

MCP_COMMAND = os.getenv("MCP_SERVER_COMMAND", "uv")
MCP_DIR = os.getenv("MCP_SERVER_DIR", _DEFAULT_MCP_DIR)
MCP_SCRIPT = os.getenv("MCP_SERVER_SCRIPT", "mcp_server.py")

SERVER_CONFIGS: dict = {
    "global_market_mcp": {
        "command": MCP_COMMAND,
        "args": [
            "run",
            "--directory",
            MCP_DIR,
            "python",
            MCP_SCRIPT,
        ],
        "transport": "stdio",
    }
}
