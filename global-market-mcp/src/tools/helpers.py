"""MCP helper tools — parameter discovery and constant listing.

Registers 1 MVP tool:
- list_tool_constants: Lists valid parameter values for period, interval,
  exchange, index, and indicator parameters used across other tools.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..formatting.json_fmt import format_json
from ..formatting.markdown import format_tool_constants

# Valid parameter values across all MCP tools.
# This is the single source of truth that agents query to discover
# what values they can pass to other tools.
CONSTANTS: dict[str, list[str] | dict[str, str]] = {
    "period": [
        "1d", "5d", "1mo", "3mo", "6mo",
        "1y", "2y", "5y", "10y", "ytd", "max",
    ],
    "interval": [
        "1m", "2m", "5m", "15m", "30m",
        "60m", "90m", "1h", "1d", "5d",
        "1wk", "1mo", "3mo",
    ],
    "exchange": {
        "XNYS": "NYSE",
        "XNAS": "NASDAQ",
        "XSWX": "SIX Swiss",
        "XLON": "London",
    },
    "index": {
        "SP500": "^GSPC",
        "NASDAQ": "^IXIC",
        "DOW": "^DJI",
        "VIX": "^VIX",
        "RUSSELL2000": "^RUT",
    },
    "indicator": [
        "standard", "trend", "momentum", "volatility", "volume",
    ],
}


def register_helper_tools(mcp: FastMCP) -> None:
    """Register helper/utility MCP tools on the given server instance.

    These tools do not require a data source — they serve static configuration
    and parameter discovery information.

    Args:
        mcp: The FastMCP server to register tools on.
    """

    @mcp.tool()
    async def list_tool_constants(
        kind: str | None = None,
        format: str = "markdown",
    ) -> str:
        """List valid parameter values for MCP tool parameters.

        Returns the set of accepted values for parameters like period, interval,
        exchange, index, and indicator.  Useful when you need to discover what
        values a tool parameter accepts before calling it.

        When called with no arguments, returns all constant categories.
        When called with a specific kind, returns only that category's values.

        Available kinds: "period", "interval", "exchange", "index", "indicator".

        Args:
            kind: Optional category to filter by (e.g., "period", "exchange").
                  If None, returns all categories.
            format: "markdown" (default) or "json".
        """
        try:
            if kind is not None:
                kind_lower = kind.strip().lower()
                if kind_lower not in CONSTANTS:
                    valid_kinds = ", ".join(sorted(CONSTANTS.keys()))
                    return (
                        f"Error: Unknown constant kind '{kind}'. "
                        f"Valid kinds are: {valid_kinds}"
                    )
                result = {kind_lower: CONSTANTS[kind_lower]}
            else:
                result = CONSTANTS

            if format == "json":
                return format_json(result)
            return format_tool_constants(result)
        except Exception as e:
            return f"Error: An unexpected error occurred: {e}"
