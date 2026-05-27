"""Tests for the macro context agent.

Tests cover:
- Agent function exists and has correct signature
- Correct data_key ("macro_analysis") is used
- Handles missing ticker gracefully
- MCP tools unavailable handling
- LLM error handling
- Graph compiles correctly with macro_analyst node
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.macro_agent import macro_agent, MACRO_SYSTEM_PROMPT, MACRO_USER_PROMPT
from src.main import build_graph
from src.utils.state_definition import AgentState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mock_llm(response_text: str = "Mock analysis result") -> MagicMock:
    """Return a mock LLM whose ``ainvoke`` returns a predictable ``AIMessage``."""
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=response_text))
    return mock_llm


def make_mock_tools() -> list:
    """Return a non-empty list of mock tools."""
    tool = MagicMock()
    tool.name = "mock_tool"
    return [tool]


def make_mock_react_agent(response_text: str = "Mock ReAct result") -> MagicMock:
    """Return a mock that substitutes ``create_react_agent``."""
    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(
        return_value={
            "messages": [
                HumanMessage(content="prompt"),
                AIMessage(content=response_text),
            ]
        }
    )

    def _factory(llm, tools, **kwargs):
        return mock_agent

    return _factory


def _base_state(ticker: str = "AAPL", query: str | None = None) -> AgentState:
    """Build a minimal ``AgentState`` suitable for most tests."""
    return AgentState(
        messages=[],
        data={
            "ticker": ticker,
            "query": query or f"Analyze {ticker}",
        },
        metadata={},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_mcp_client():
    """Reset MCP client singleton between tests."""
    import src.tools.mcp_client as mcp_mod

    mcp_mod._client = None
    mcp_mod._tools = None
    yield
    mcp_mod._client = None
    mcp_mod._tools = None


@pytest.fixture(autouse=True)
def reset_execution_logger(tmp_path):
    """Use tmp_path for execution logger to avoid polluting project dir."""
    import src.utils.execution_logger as el_mod

    el_mod._logger = None
    from src.utils.execution_logger import initialize_execution_logger

    initialize_execution_logger(str(tmp_path / "logs"))
    yield
    el_mod._logger = None


# ===================================================================
# 1. Agent Function Structure Tests
# ===================================================================

_BASE = "src.agents._base"


class TestMacroAgentStructure:
    """Verify macro_agent function signature and prompt configuration."""

    def test_macro_agent_is_callable(self):
        """macro_agent is an async callable."""
        assert callable(macro_agent)

    def test_macro_agent_is_coroutine_function(self):
        """macro_agent is an async function."""
        import asyncio
        assert asyncio.iscoroutinefunction(macro_agent)

    def test_system_prompt_has_placeholders(self):
        """System prompt contains {ticker} and {current_date} placeholders."""
        assert "{ticker}" in MACRO_SYSTEM_PROMPT
        assert "{current_date}" in MACRO_SYSTEM_PROMPT

    def test_user_prompt_has_ticker_placeholder(self):
        """User prompt contains {ticker} placeholder."""
        assert "{ticker}" in MACRO_USER_PROMPT

    def test_system_prompt_mentions_macro_tools(self):
        """System prompt references the 4 macro MCP tools + get_stock_info."""
        assert "get_market_regime" in MACRO_SYSTEM_PROMPT
        assert "get_treasury_yields" in MACRO_SYSTEM_PROMPT
        assert "get_economic_indicators" in MACRO_SYSTEM_PROMPT
        assert "get_yield_curve" in MACRO_SYSTEM_PROMPT
        assert "get_stock_info" in MACRO_SYSTEM_PROMPT

    def test_system_prompt_mentions_output_sections(self):
        """System prompt defines the expected output sections."""
        assert "Market Regime" in MACRO_SYSTEM_PROMPT
        assert "Interest Rate Environment" in MACRO_SYSTEM_PROMPT
        assert "Economic Cycle Position" in MACRO_SYSTEM_PROMPT
        assert "Inflation Assessment" in MACRO_SYSTEM_PROMPT
        assert "Sector Impact" in MACRO_SYSTEM_PROMPT
        assert "Macro Risk Factors" in MACRO_SYSTEM_PROMPT
        assert "Macro Tailwinds" in MACRO_SYSTEM_PROMPT
        assert "Overall Macro Score" in MACRO_SYSTEM_PROMPT


# ===================================================================
# 2. Agent Execution Tests (mock LLM + mock MCP)
# ===================================================================


class TestMacroAgentExecution:
    """Test macro_agent execution with mocked LLM and MCP tools."""

    @patch(f"{_BASE}.create_react_agent")
    @patch(f"{_BASE}.get_mcp_tools", new_callable=AsyncMock)
    @patch(f"{_BASE}.create_llm")
    async def test_macro_agent_success(
        self, mock_create_llm, mock_get_tools, mock_create_react
    ):
        """Successful macro analysis stores result in macro_analysis key."""
        expected_text = "Macro context assessment for AAPL complete."

        mock_create_llm.return_value = make_mock_llm()
        mock_get_tools.return_value = make_mock_tools()
        mock_create_react.side_effect = make_mock_react_agent(expected_text)

        state = _base_state("AAPL")
        result = await macro_agent(state)

        assert result["data"]["macro_analysis"] == expected_text
        assert result["metadata"]["macro_executed"] is True
        assert "macro_seconds" in result["metadata"]

    @patch(f"{_BASE}.create_react_agent")
    @patch(f"{_BASE}.get_mcp_tools", new_callable=AsyncMock)
    @patch(f"{_BASE}.create_llm")
    async def test_macro_agent_data_key(
        self, mock_create_llm, mock_get_tools, mock_create_react
    ):
        """Macro agent writes to the 'macro_analysis' data key."""
        mock_create_llm.return_value = make_mock_llm()
        mock_get_tools.return_value = make_mock_tools()
        mock_create_react.side_effect = make_mock_react_agent("Macro result")

        state = _base_state("MSFT")
        result = await macro_agent(state)

        assert "macro_analysis" in result["data"]
        assert "fundamental_analysis" not in result["data"]
        assert "technical_analysis" not in result["data"]
        assert "value_analysis" not in result["data"]

    @patch(f"{_BASE}.create_react_agent")
    @patch(f"{_BASE}.get_mcp_tools", new_callable=AsyncMock)
    @patch(f"{_BASE}.create_llm")
    async def test_macro_agent_missing_ticker(
        self, mock_create_llm, mock_get_tools, mock_create_react
    ):
        """When ticker is missing from state, agent uses 'UNKNOWN' and still runs."""
        mock_create_llm.return_value = make_mock_llm()
        mock_get_tools.return_value = make_mock_tools()
        mock_create_react.side_effect = make_mock_react_agent("Macro result with UNKNOWN")

        state = AgentState(messages=[], data={}, metadata={})
        result = await macro_agent(state)

        # Agent should still produce output (with UNKNOWN ticker)
        assert "macro_analysis" in result["data"]

    @patch(f"{_BASE}.get_mcp_tools", new_callable=AsyncMock)
    @patch(f"{_BASE}.create_llm")
    async def test_macro_agent_mcp_tools_empty(self, mock_create_llm, mock_get_tools):
        """When MCP tools unavailable, agent sets a graceful error."""
        mock_create_llm.return_value = make_mock_llm()
        mock_get_tools.return_value = []

        state = _base_state("AAPL")
        result = await macro_agent(state)

        assert "Analysis unavailable" in result["data"]["macro_analysis"]
        assert "macro_analysis_error" in result["data"]

    @patch(f"{_BASE}.create_react_agent")
    @patch(f"{_BASE}.get_mcp_tools", new_callable=AsyncMock)
    @patch(f"{_BASE}.create_llm")
    async def test_macro_agent_llm_exception(
        self, mock_create_llm, mock_get_tools, mock_create_react
    ):
        """When the ReAct agent raises, the wrapper catches and sets error."""
        mock_create_llm.return_value = make_mock_llm()
        mock_get_tools.return_value = make_mock_tools()

        bad_agent = MagicMock()
        bad_agent.ainvoke = AsyncMock(side_effect=RuntimeError("LLM exploded"))
        mock_create_react.return_value = bad_agent

        state = _base_state("AAPL")
        result = await macro_agent(state)

        assert "Analysis error" in result["data"]["macro_analysis"]
        assert "macro_analysis_error" in result["data"]
        assert "LLM exploded" in result["data"]["macro_analysis_error"]


# ===================================================================
# 3. Graph Structure Tests (with macro_analyst)
# ===================================================================


class TestGraphWithMacroAgent:
    """Verify graph structure includes macro_analyst node."""

    def test_graph_compiles_with_macro(self):
        """build_graph() compiles successfully with macro_analyst node."""
        graph = build_graph()
        assert graph is not None

    def test_graph_has_macro_analyst_node(self):
        """The compiled graph contains the macro_analyst node."""
        graph = build_graph()
        node_names = set(graph.get_graph().nodes.keys())
        assert "macro_analyst" in node_names

    def test_graph_has_all_expected_nodes(self):
        """The compiled graph contains all six expected node names."""
        graph = build_graph()
        node_names = set(graph.get_graph().nodes.keys())
        expected = {
            "start_node",
            "fundamental_analyst",
            "technical_analyst",
            "value_analyst",
            "macro_analyst",
            "core_analysis",
        }
        assert expected.issubset(node_names), (
            f"Missing nodes: {expected - node_names}"
        )
