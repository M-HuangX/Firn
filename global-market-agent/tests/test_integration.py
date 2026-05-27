"""Integration tests for the LangGraph multi-agent financial analysis system.

Uses mock LLM + mock MCP throughout — no real API calls.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from src.main import build_graph, _start_node
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
    """Return a mock that substitutes ``create_react_agent``.

    The returned callable produces an object whose ``ainvoke`` returns a
    message list containing the expected ``AIMessage``.
    """
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
# 1. Graph Structure Tests
# ===================================================================


class TestGraphStructure:
    """Verify that ``build_graph`` produces the expected compiled graph."""

    def test_build_graph_compiles(self):
        """build_graph() returns a compiled graph without errors."""
        graph = build_graph()
        assert graph is not None

    def test_graph_has_expected_nodes(self):
        """The compiled graph contains the six expected node names."""
        graph = build_graph()
        # LangGraph compiled graphs expose node names via .get_graph().nodes
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


# ===================================================================
# 2. Start Node Tests
# ===================================================================


class TestStartNode:
    """Validate the ``_start_node`` entry-point logic."""

    async def test_start_node_valid_ticker(self):
        """'AAPL' passes validation and returns data with workflow_start_time."""
        state = _base_state("AAPL")
        result = await _start_node(state)

        assert result["data"]["ticker"] == "AAPL"
        assert "workflow_start_time" in result["metadata"]
        assert isinstance(result["metadata"]["workflow_start_time"], float)

    async def test_start_node_invalid_ticker_lowercase(self):
        """Lowercase ticker 'aapl' is rejected."""
        state = _base_state("aapl")
        with pytest.raises(ValueError, match="Invalid ticker format"):
            await _start_node(state)

    async def test_start_node_invalid_ticker_special_chars(self):
        """Ticker with invalid characters raises ValueError."""
        state = _base_state("INVALID!!!")
        with pytest.raises(ValueError, match="Invalid ticker format"):
            await _start_node(state)

    async def test_start_node_missing_ticker(self):
        """Empty data (no ticker) raises ValueError."""
        state = AgentState(messages=[], data={}, metadata={})
        with pytest.raises(ValueError, match="No ticker provided"):
            await _start_node(state)

    async def test_start_node_swiss_ticker(self):
        """'NESN.SW' passes validation (dot is allowed)."""
        state = _base_state("NESN.SW")
        result = await _start_node(state)
        assert result["data"]["ticker"] == "NESN.SW"

    async def test_start_node_index_ticker(self):
        """'^GSPC' passes validation (caret is allowed)."""
        state = _base_state("^GSPC")
        result = await _start_node(state)
        assert result["data"]["ticker"] == "^GSPC"


# ===================================================================
# 3. Individual Agent Tests (mock LLM + mock MCP)
# ===================================================================

# Patch targets live in the module where the names are looked up (_base.py).
_BASE = "src.agents._base"


class TestAnalysisAgents:
    """Test each analysis agent with mocked LLM and MCP tools."""

    @patch(f"{_BASE}.create_react_agent")
    @patch(f"{_BASE}.get_mcp_tools", new_callable=AsyncMock)
    @patch(f"{_BASE}.create_llm")
    async def test_fundamental_agent_success(
        self, mock_create_llm, mock_get_tools, mock_create_react
    ):
        from src.agents.fundamental_agent import fundamental_agent

        expected_text = "Fundamental analysis for AAPL complete."

        mock_create_llm.return_value = make_mock_llm()
        mock_get_tools.return_value = make_mock_tools()
        mock_create_react.side_effect = make_mock_react_agent(expected_text)

        state = _base_state("AAPL")
        result = await fundamental_agent(state)

        assert result["data"]["fundamental_analysis"] == expected_text
        assert result["metadata"]["fundamental_executed"] is True
        assert "fundamental_seconds" in result["metadata"]

    @patch(f"{_BASE}.create_react_agent")
    @patch(f"{_BASE}.get_mcp_tools", new_callable=AsyncMock)
    @patch(f"{_BASE}.create_llm")
    async def test_technical_agent_success(
        self, mock_create_llm, mock_get_tools, mock_create_react
    ):
        from src.agents.technical_agent import technical_agent

        expected_text = "Technical analysis for AAPL complete."

        mock_create_llm.return_value = make_mock_llm()
        mock_get_tools.return_value = make_mock_tools()
        mock_create_react.side_effect = make_mock_react_agent(expected_text)

        state = _base_state("AAPL")
        result = await technical_agent(state)

        assert result["data"]["technical_analysis"] == expected_text
        assert result["metadata"]["technical_executed"] is True
        assert "technical_seconds" in result["metadata"]

    @patch(f"{_BASE}.create_react_agent")
    @patch(f"{_BASE}.get_mcp_tools", new_callable=AsyncMock)
    @patch(f"{_BASE}.create_llm")
    async def test_value_agent_success(
        self, mock_create_llm, mock_get_tools, mock_create_react
    ):
        from src.agents.value_agent import value_agent

        expected_text = "Value analysis for AAPL complete."

        mock_create_llm.return_value = make_mock_llm()
        mock_get_tools.return_value = make_mock_tools()
        mock_create_react.side_effect = make_mock_react_agent(expected_text)

        state = _base_state("AAPL")
        result = await value_agent(state)

        assert result["data"]["value_analysis"] == expected_text
        assert result["metadata"]["value_executed"] is True
        assert "value_seconds" in result["metadata"]

    @patch(f"{_BASE}.get_mcp_tools", new_callable=AsyncMock)
    @patch(f"{_BASE}.create_llm")
    async def test_agent_mcp_tools_empty(self, mock_create_llm, mock_get_tools):
        """When get_mcp_tools returns [], agent sets a graceful error."""
        from src.agents.fundamental_agent import fundamental_agent

        mock_create_llm.return_value = make_mock_llm()
        mock_get_tools.return_value = []

        state = _base_state("AAPL")
        result = await fundamental_agent(state)

        assert "Analysis unavailable" in result["data"]["fundamental_analysis"]
        assert "fundamental_analysis_error" in result["data"]

    @patch(f"{_BASE}.create_react_agent")
    @patch(f"{_BASE}.get_mcp_tools", new_callable=AsyncMock)
    @patch(f"{_BASE}.create_llm")
    async def test_agent_llm_exception(
        self, mock_create_llm, mock_get_tools, mock_create_react
    ):
        """When the ReAct agent raises, the wrapper catches and sets error."""
        from src.agents.technical_agent import technical_agent

        mock_create_llm.return_value = make_mock_llm()
        mock_get_tools.return_value = make_mock_tools()

        # create_react_agent returns an agent whose ainvoke raises
        bad_agent = MagicMock()
        bad_agent.ainvoke = AsyncMock(side_effect=RuntimeError("LLM exploded"))
        mock_create_react.return_value = bad_agent

        state = _base_state("AAPL")
        result = await technical_agent(state)

        assert "Analysis error" in result["data"]["technical_analysis"]
        assert "technical_analysis_error" in result["data"]
        assert "LLM exploded" in result["data"]["technical_analysis_error"]


# ===================================================================
# 4. Core Analysis Tests (replaces Summary Agent — D26)
# ===================================================================

_CORE_AGENT = "src.main"


class TestCoreAnalysis:
    """Test the core_analysis node with mocked CoreAgent."""

    @patch(f"{_CORE_AGENT}.CoreAgent")
    async def test_core_analysis_success(self, mock_core_cls):
        from src.main import _run_core_analysis

        report_text = "# AAPL Comprehensive Analysis Report\n\nGreat stock."
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=report_text)
        mock_core_cls.return_value = mock_instance

        state = AgentState(
            messages=[],
            data={
                "ticker": "AAPL",
                "query": "Analyze AAPL",
                "fundamental_analysis": "Strong fundamentals.",
                "technical_analysis": "Bullish trend.",
                "value_analysis": "Undervalued.",
                "macro_analysis": "Risk-on environment.",
            },
            metadata={},
        )

        result = await _run_core_analysis(state)

        assert "final_report" in result["data"]
        assert "AAPL" in result["data"]["final_report"]
        assert result["metadata"]["summary_executed"] is True
        assert "summary_seconds" in result["metadata"]

    @patch(f"{_CORE_AGENT}.CoreAgent")
    async def test_core_analysis_with_missing_analysis(self, mock_core_cls):
        from src.main import _run_core_analysis

        report_text = "# AAPL Report — partial data"
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=report_text)
        mock_core_cls.return_value = mock_instance

        # Only fundamental_analysis present; others missing
        state = AgentState(
            messages=[],
            data={
                "ticker": "AAPL",
                "query": "Analyze AAPL",
                "fundamental_analysis": "Strong fundamentals.",
            },
            metadata={},
        )

        result = await _run_core_analysis(state)

        assert "final_report" in result["data"]
        mock_instance.run.assert_awaited_once()

    @patch(f"{_CORE_AGENT}.CoreAgent")
    async def test_core_analysis_error(self, mock_core_cls):
        from src.main import _run_core_analysis

        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(side_effect=RuntimeError("LLM down"))
        mock_core_cls.return_value = mock_instance

        state = AgentState(
            messages=[],
            data={
                "ticker": "AAPL",
                "query": "Analyze AAPL",
                "fundamental_analysis": "FA",
                "technical_analysis": "TA",
                "value_analysis": "VA",
                "macro_analysis": "MA",
            },
            metadata={},
        )

        result = await _run_core_analysis(state)

        assert "final_report" in result["data"]
        assert "Error" in result["data"]["final_report"]
        assert "summary_error" in result["data"]
        assert "LLM down" in result["data"]["summary_error"]


# ===================================================================
# 5. Full Graph End-to-End Test (all mocked)
# ===================================================================


class TestFullGraphEndToEnd:
    """Run the compiled graph end-to-end with everything mocked."""

    @patch(f"{_CORE_AGENT}.CoreAgent")
    @patch(f"{_BASE}.create_react_agent")
    @patch(f"{_BASE}.get_mcp_tools", new_callable=AsyncMock)
    @patch(f"{_BASE}.create_llm")
    async def test_full_graph_end_to_end(
        self,
        mock_base_llm,
        mock_get_tools,
        mock_create_react,
        mock_core_cls,
    ):
        """Mock everything, invoke the compiled graph with AAPL, verify outputs."""
        # --- Set up analysis agent mocks ---
        mock_base_llm.return_value = make_mock_llm()
        mock_get_tools.return_value = make_mock_tools()
        mock_create_react.side_effect = make_mock_react_agent(
            "Detailed mock analysis for AAPL."
        )

        # --- Set up core analysis mock ---
        summary_report = (
            "# AAPL Comprehensive Analysis Report\n\n"
            "## Executive Summary\n"
            "AAPL is a great stock.\n\n"
            "## Conclusion\n"
            "Buy."
        )
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=summary_report)
        mock_core_cls.return_value = mock_instance

        # --- Build and invoke ---
        graph = build_graph()
        initial_state = AgentState(
            messages=[],
            data={"ticker": "AAPL", "query": "Analyze AAPL stock"},
            metadata={},
        )

        final_state = await graph.ainvoke(initial_state)

        # --- Assertions ---
        data = final_state["data"]

        # All four analyses should be present
        assert "fundamental_analysis" in data
        assert "technical_analysis" in data
        assert "value_analysis" in data
        assert "macro_analysis" in data

        # Final report should exist
        assert "final_report" in data
        assert "AAPL" in data["final_report"]

        # Metadata should reflect execution
        metadata = final_state["metadata"]
        assert "workflow_start_time" in metadata
