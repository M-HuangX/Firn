"""Integration tests for the refactored LangGraph graph (D26: CoreAgent replaces SummaryAgent).

Tests cover:
- Graph structure (nodes, edges, no legacy summarizer)
- _run_core_analysis node function behavior
- Value agent KB cleanup
- Summary agent removal
- Context injection deprecation
- Backward compatibility
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.utils.state_definition import AgentState


# ---------------------------------------------------------------------------
# TestGraphStructure
# ---------------------------------------------------------------------------

class TestGraphStructure:
    """Verify the compiled graph has the correct nodes and edges."""

    def test_graph_compiles(self):
        """build_graph() returns a compiled graph without errors."""
        from src.main import build_graph
        app = build_graph()
        assert app is not None

    def test_graph_has_core_analysis_node(self):
        """Graph has 'core_analysis' node, not 'summarizer'."""
        from src.main import build_graph
        app = build_graph()
        graph = app.get_graph()
        # graph.nodes may be a dict (node_id -> node) or list of node objects
        if isinstance(graph.nodes, dict):
            node_names = list(graph.nodes.keys())
        else:
            node_names = [getattr(n, "id", n) for n in graph.nodes]
        assert "core_analysis" in node_names
        assert "summarizer" not in node_names

    def test_graph_has_no_summary_import(self):
        """summary_agent should not be imported anywhere in main.py."""
        import src.main as main_module
        source = inspect.getsource(main_module)
        assert "summary_agent" not in source

    def test_graph_edges_to_core_analysis(self):
        """All 4 analyst nodes connect to core_analysis."""
        from src.main import build_graph
        app = build_graph()
        graph = app.get_graph()
        edges = [(e.source, e.target) for e in graph.edges]
        for analyst in ("fundamental_analyst", "technical_analyst", "value_analyst", "macro_analyst"):
            assert (analyst, "core_analysis") in edges

    def test_start_node_no_kb_context(self):
        """_start_node should not load kb_context anymore."""
        import src.main as main_module
        source = inspect.getsource(main_module._start_node)
        assert "load_kb_context" not in source
        assert "kb_context" not in source


# ---------------------------------------------------------------------------
# TestRunCoreAnalysis
# ---------------------------------------------------------------------------

class TestRunCoreAnalysis:
    """Test the _run_core_analysis node function."""

    @pytest.mark.asyncio
    @patch("src.main.CoreAgent")
    async def test_run_core_analysis_basic(self, mock_core_cls):
        """_run_core_analysis creates CoreAgent and calls run()."""
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value="# AAPL Report\nContent")
        mock_core_cls.return_value = mock_instance

        from src.main import _run_core_analysis
        state = AgentState(
            messages=[],
            data={
                "ticker": "AAPL",
                "query": "Analyze AAPL",
                "fundamental_analysis": "Good fundamentals",
                "technical_analysis": "Bullish trend",
                "value_analysis": "Undervalued",
                "macro_analysis": "Risk-on",
            },
            metadata={},
        )
        result = await _run_core_analysis(state)
        assert "final_report" in result["data"]
        assert "AAPL" in result["data"]["final_report"] or "Report" in result["data"]["final_report"]
        # Verify CoreAgent was constructed and run() was called
        mock_core_cls.assert_called_once()
        mock_instance.run.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("src.main.CoreAgent")
    async def test_run_core_analysis_with_errors(self, mock_core_cls):
        """Error section included when sub-agents report errors."""
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value="# Report\nContent")
        mock_core_cls.return_value = mock_instance

        from src.main import _run_core_analysis
        state = AgentState(
            messages=[],
            data={
                "ticker": "AAPL",
                "query": "",
                "fundamental_analysis": "ok",
                "technical_analysis": "ok",
                "value_analysis_error": "timeout",
                "macro_analysis": "ok",
            },
            metadata={},
        )
        result = await _run_core_analysis(state)
        # The input_data passed to CoreAgent.run should contain the error
        call_args = mock_instance.run.call_args
        input_text = call_args[0][0]  # first positional arg
        assert "ERRORS" in input_text or "error" in input_text.lower()

    @pytest.mark.asyncio
    @patch("src.main.CoreAgent")
    async def test_run_core_analysis_handles_exception(self, mock_core_cls):
        """If CoreAgent.run raises, fallback report is generated."""
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(side_effect=RuntimeError("LLM failed"))
        mock_core_cls.return_value = mock_instance

        from src.main import _run_core_analysis
        state = AgentState(
            messages=[],
            data={"ticker": "AAPL", "query": ""},
            metadata={},
        )
        result = await _run_core_analysis(state)
        assert "Error" in result["data"]["final_report"]
        assert "summary_error" in result["data"]

    @pytest.mark.asyncio
    @patch("src.main.CoreAgent")
    async def test_run_core_analysis_metadata_compat(self, mock_core_cls):
        """Both core_analysis and summary metadata keys are set for backward compat."""
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value="# Report")
        mock_core_cls.return_value = mock_instance

        from src.main import _run_core_analysis
        state = AgentState(
            messages=[],
            data={"ticker": "MSFT", "query": "Test"},
            metadata={},
        )
        result = await _run_core_analysis(state)
        meta = result["metadata"]
        assert meta.get("core_analysis_executed") is True
        assert meta.get("summary_executed") is True
        assert "core_analysis_seconds" in meta
        assert "summary_seconds" in meta

    @pytest.mark.asyncio
    @patch("src.main.CoreAgent")
    async def test_run_core_analysis_missing_analyses(self, mock_core_cls):
        """Missing upstream analyses get default 'Not available' text."""
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value="# Report")
        mock_core_cls.return_value = mock_instance

        from src.main import _run_core_analysis
        state = AgentState(
            messages=[],
            data={"ticker": "GOOG", "query": ""},
            metadata={},
        )
        result = await _run_core_analysis(state)
        call_args = mock_instance.run.call_args
        input_text = call_args[0][0]
        assert "Not available" in input_text


# ---------------------------------------------------------------------------
# TestValueAgentCleanup
# ---------------------------------------------------------------------------

class TestValueAgentCleanup:
    """Verify value_agent.py no longer uses context injection."""

    def test_value_agent_no_context_injection(self):
        """value_agent.py should not import context_injection."""
        import src.agents.value_agent as va
        source = inspect.getsource(va)
        assert "context_injection" not in source
        assert "load_kb_context" not in source

    def test_value_agent_no_kb_context_in_state(self):
        """value_agent function should not access state['data']['kb_context']."""
        from src.agents.value_agent import value_agent
        source = inspect.getsource(value_agent)
        assert "kb_context" not in source


# ---------------------------------------------------------------------------
# TestSummaryAgentRemoved
# ---------------------------------------------------------------------------

class TestSummaryAgentRemoved:
    """Verify summary_agent.py has been deleted."""

    def test_summary_agent_file_deleted(self):
        """summary_agent.py should not exist."""
        agent_dir = Path(__file__).parent.parent / "src" / "agents"
        assert not (agent_dir / "summary_agent.py").exists()

    def test_summary_agent_not_importable(self):
        """Importing summary_agent should raise ImportError."""
        with pytest.raises((ImportError, ModuleNotFoundError)):
            import src.agents.summary_agent  # noqa: F401


# ---------------------------------------------------------------------------
# TestContextInjectionDeprecated
# ---------------------------------------------------------------------------

class TestContextInjectionDeprecated:
    """Verify context_injection.py is marked deprecated."""

    def test_context_injection_marked_deprecated(self):
        """context_injection.py docstring starts with DEPRECATED."""
        import src.knowledge_base.context_injection as ci
        assert ci.__doc__ is not None
        assert "DEPRECATED" in ci.__doc__

    def test_main_does_not_import_context_injection(self):
        """main.py should not import context_injection."""
        import src.main as m
        source = inspect.getsource(m)
        assert "context_injection" not in source


# ---------------------------------------------------------------------------
# TestBackwardCompat
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    """Backward compatibility checks."""

    @pytest.mark.asyncio
    @patch("src.main.CoreAgent")
    async def test_final_report_key_exists(self, mock_core_cls):
        """Result should still use data['final_report'] key."""
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value="# Report")
        mock_core_cls.return_value = mock_instance

        from src.main import _run_core_analysis
        state = AgentState(
            messages=[],
            data={"ticker": "AAPL", "query": ""},
            metadata={},
        )
        result = await _run_core_analysis(state)
        assert "final_report" in result["data"]

    @pytest.mark.asyncio
    @patch("src.main.CoreAgent")
    async def test_metadata_keys_compat(self, mock_core_cls):
        """summary_executed and summary_seconds still set for CLI compat."""
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value="# Test Report")
        mock_core_cls.return_value = mock_instance

        from src.main import _run_core_analysis
        state = AgentState(
            messages=[],
            data={"ticker": "AAPL", "query": ""},
            metadata={},
        )
        result = await _run_core_analysis(state)
        assert result["metadata"]["summary_executed"] is True
        assert isinstance(result["metadata"]["summary_seconds"], float)

    def test_agents_init_exports(self):
        """__init__.py still exports needed agent functions."""
        from src.agents import fundamental_agent, technical_agent, value_agent, macro_agent
        assert callable(fundamental_agent)
        assert callable(technical_agent)
        assert callable(value_agent)
        assert callable(macro_agent)

    def test_agents_core_modules_accessible(self):
        """Core agent modules are accessible (may fail until Agent A delivers files)."""
        try:
            from src.agents import _base
            assert _base is not None
        except ImportError:
            pytest.skip("_base module not found — unexpected")

        # These will only pass once Agent A's files are created
        try:
            from src.agents import core_agent  # noqa: F401
            from src.agents import profiles  # noqa: F401
        except ImportError:
            pytest.skip("core_agent/profiles not yet created by Agent A")
