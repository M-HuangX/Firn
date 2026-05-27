"""Tests for Core Agent system: profiles, output_handlers, and core_agent.

Covers:
- AgentProfile configuration validation
- Output handler logic (report saving, prediction logging, divergence checks)
- CoreAgent construction, prompt building, output extraction, and run flow
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.core_agent import CoreAgent
from src.agents.output_handlers import (
    mark_library_read,
    save_report_and_log_prediction,
)
from src.agents.profiles import (
    ANALYSIS_PROFILE,
    ANALYSIS_PROMPT,
    DIGEST_PROFILE,
    DIGEST_PROMPT,
    AgentProfile,
)
from src.knowledge_base.kb_api import KnowledgeBase
from src.knowledge_base.kb_tools import KBToolSet


# =========================================================================
# TestAgentProfile
# =========================================================================


class TestAgentProfile:
    """Validate profile configurations."""

    def test_analysis_profile_has_correct_tool_names(self):
        """All ANALYSIS_PROFILE tool names must exist in KBToolSet or web tools."""
        kb = KnowledgeBase(kb_root=Path("/tmp/test_kb_profile_a"))
        kb.ensure_structure()
        ts = KBToolSet(kb)
        available = set(ts._tools.keys())
        web_tool_names = {t.name for t in CoreAgent._get_web_tools(ANALYSIS_PROFILE.tool_names)}
        all_available = available | web_tool_names
        for name in ANALYSIS_PROFILE.tool_names:
            assert name in all_available, f"Tool '{name}' not in KBToolSet or web tools: {all_available}"

    def test_digest_profile_has_correct_tool_names(self):
        """All DIGEST_PROFILE tool names must exist in KBToolSet or web tools."""
        kb = KnowledgeBase(kb_root=Path("/tmp/test_kb_profile_d"))
        kb.ensure_structure()
        ts = KBToolSet(kb)
        available = set(ts._tools.keys())
        web_tool_names = {t.name for t in CoreAgent._get_web_tools(DIGEST_PROFILE.tool_names)}
        all_available = available | web_tool_names
        for name in DIGEST_PROFILE.tool_names:
            assert name in all_available, f"Tool '{name}' not in KBToolSet or web tools: {all_available}"

    def test_profile_prompt_has_required_placeholders(self):
        """ANALYSIS_PROMPT must contain all required format placeholders."""
        required = [
            "{agent_principles}",
            "{core_mind_content}",
            "{user_views_content}",
            "{divergences_content}",
            "{ticker}",
            "{timestamp}",
        ]
        for placeholder in required:
            assert placeholder in ANALYSIS_PROMPT, (
                f"Missing placeholder {placeholder} in ANALYSIS_PROMPT"
            )

    def test_digest_prompt_has_required_placeholders(self):
        """DIGEST_PROMPT must contain all required format placeholders."""
        required = [
            "{agent_principles}",
            "{core_mind_content}",
        ]
        for placeholder in required:
            assert placeholder in DIGEST_PROMPT, (
                f"Missing placeholder {placeholder} in DIGEST_PROMPT"
            )

    def test_analysis_profile_settings(self):
        """Verify analysis profile has the expected settings."""
        assert ANALYSIS_PROFILE.name == "analysis"
        assert ANALYSIS_PROFILE.max_rounds == 45
        assert ANALYSIS_PROFILE.llm_temperature == 0.4
        assert ANALYSIS_PROFILE.llm_max_tokens == 16384

    def test_digest_profile_settings(self):
        """Verify digest profile has the expected settings."""
        assert DIGEST_PROFILE.name == "digest"
        assert DIGEST_PROFILE.max_rounds == 60
        assert DIGEST_PROFILE.llm_temperature == 0.2
        assert DIGEST_PROFILE.llm_max_tokens == 8192


# =========================================================================
# TestOutputHandlers
# =========================================================================


class TestOutputHandlers:
    """Test output handler functions."""

    @pytest.mark.asyncio
    async def test_save_report_creates_file(self, tmp_path):
        """save_report_and_log_prediction should create a report file."""
        kb = KnowledgeBase(kb_root=tmp_path / "kb")
        kb.ensure_structure()

        report = "# AAPL Report\n\nBuy recommendation."
        context = {"ticker": "AAPL"}

        with patch(
            "src.agents.output_handlers._PROJECT_ROOT", tmp_path
        ):
            await save_report_and_log_prediction(report, context, kb)

        reports_dir = tmp_path / "reports"
        assert reports_dir.exists()
        files = list(reports_dir.glob("report_AAPL_*.md"))
        assert len(files) == 1
        assert "Buy recommendation" in files[0].read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_save_report_rotates_kb(self, tmp_path):
        """KB report rotation should be called."""
        kb = MagicMock(spec=KnowledgeBase)
        kb.save_report_with_rotation = MagicMock()

        report = "# TEST Report"
        context = {"ticker": "TEST"}

        with patch(
            "src.agents.output_handlers._PROJECT_ROOT", tmp_path
        ):
            await save_report_and_log_prediction(report, context, kb)

        kb.save_report_with_rotation.assert_called_once_with("TEST", report)

    @pytest.mark.asyncio
    async def test_prediction_logged(self, tmp_path):
        """Prediction logger should be called with correct args."""
        kb = MagicMock(spec=KnowledgeBase)
        kb.save_report_with_rotation = MagicMock()

        report = "# AAPL Report\nContent here."
        context = {"ticker": "AAPL"}

        with (
            patch("src.agents.output_handlers._PROJECT_ROOT", tmp_path),
            patch(
                "src.knowledge_base.prediction_logger.log_prediction",
                return_value=True,
            ) as mock_log,
        ):
            await save_report_and_log_prediction(report, context, kb)
            mock_log.assert_called_once()
            call_args = mock_log.call_args
            assert call_args[0][0] == "AAPL"
            assert call_args[0][1] == report

    @pytest.mark.asyncio
    async def test_divergence_checked(self, tmp_path):
        """Divergence check should be called when rating is extracted."""
        kb = MagicMock(spec=KnowledgeBase)
        kb.save_report_with_rotation = MagicMock()

        report = "# AAPL\n- **Recommendation**: **Hold**\n"
        context = {"ticker": "AAPL"}

        with (
            patch("src.agents.output_handlers._PROJECT_ROOT", tmp_path),
            patch(
                "src.knowledge_base.prediction_logger.log_prediction",
                return_value=False,
            ),
            patch(
                "src.knowledge_base.prediction_logger.extract_prediction_data",
                return_value={"rating": "Hold", "risk_level": "Medium"},
            ),
            patch(
                "src.knowledge_base.divergence.check_and_record_divergence",
                return_value={"user_sentiment": "bullish"},
            ) as mock_div,
        ):
            await save_report_and_log_prediction(report, context, kb)
            mock_div.assert_called_once()
            call_kwargs = mock_div.call_args[1]
            assert call_kwargs["ticker"] == "AAPL"
            assert call_kwargs["agent_rating"] == "Hold"

    @pytest.mark.asyncio
    async def test_mark_library_read_is_noop(self, tmp_path):
        """mark_library_read is a stub and should not raise."""
        kb = KnowledgeBase(kb_root=tmp_path / "kb")
        kb.ensure_structure()
        # Should simply return None without error
        result = await mark_library_read("output", {"ticker": "X"}, kb)
        assert result is None


# =========================================================================
# TestCoreAgent
# =========================================================================


class TestCoreAgent:
    """Test CoreAgent class."""

    def test_init_creates_toolset(self, tmp_path):
        """CoreAgent should create a KBToolSet on init."""
        kb = KnowledgeBase(kb_root=tmp_path)
        kb.ensure_structure()
        agent = CoreAgent(ANALYSIS_PROFILE, kb=kb)
        assert isinstance(agent.toolset, KBToolSet)
        assert agent.profile.name == "analysis"

    def test_build_system_prompt_fills_template(self, tmp_path):
        """System prompt should be filled with KB data and context."""
        kb = KnowledgeBase(kb_root=tmp_path)
        kb.ensure_structure()
        (tmp_path / "agent_principles.md").write_text(
            "Be objective.", encoding="utf-8"
        )
        kb.write_core_mind("Macro: cautious regime.")
        (tmp_path / "user_context").mkdir(parents=True, exist_ok=True)
        (tmp_path / "user_context" / "user_views.md").write_text(
            "AAPL: bullish", encoding="utf-8"
        )

        agent = CoreAgent(ANALYSIS_PROFILE, kb=kb)
        prompt = agent._build_system_prompt(
            {"ticker": "AAPL", "timestamp": "2026-05-15"}
        )

        assert "Be objective." in prompt
        assert "Macro: cautious regime." in prompt
        assert "AAPL: bullish" in prompt
        assert "AAPL" in prompt

    def test_build_system_prompt_handles_missing_kb(self, tmp_path):
        """Should not crash when KB files don't exist."""
        kb = KnowledgeBase(kb_root=tmp_path)
        kb.ensure_structure()
        # No principles file, no core_mind, no user_views

        agent = CoreAgent(ANALYSIS_PROFILE, kb=kb)
        prompt = agent._build_system_prompt(
            {"ticker": "TSLA", "timestamp": "2026-05-15"}
        )

        assert "(principles file not found)" in prompt
        assert "(not initialized)" in prompt
        # Should still contain the ticker
        assert "TSLA" in prompt

    def test_extract_output_from_messages(self):
        """Should extract the last AIMessage content."""
        result = {
            "messages": [
                HumanMessage(content="Analyze AAPL"),
                AIMessage(content="Thinking..."),
                AIMessage(content="# AAPL Report\nBuy."),
            ]
        }
        output = CoreAgent._extract_output(result)
        assert "AAPL Report" in output
        assert "Buy." in output

    def test_extract_output_empty(self):
        """Should return fallback when no AI messages."""
        result = {"messages": [HumanMessage(content="input only")]}
        output = CoreAgent._extract_output(result)
        assert output == "No output generated."

    def test_extract_output_no_messages_key(self):
        """Should return fallback when result has no messages key."""
        output = CoreAgent._extract_output({})
        assert output == "No output generated."

    @pytest.mark.asyncio
    @patch("src.agents.core_agent.create_react_agent")
    @patch("src.agents.core_agent.create_llm")
    @patch("src.agents.core_agent.create_context_hooks")
    async def test_run_with_mock_agent(
        self, mock_hooks, mock_llm, mock_react, tmp_path
    ):
        """Full run flow with mocked LLM and agent."""
        # Setup hooks
        mock_hooks.return_value = (
            lambda s: {
                "llm_input_messages": s.get("messages", [])
            },
            lambda s: s,
        )

        # Setup mock agent
        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(
            return_value={
                "messages": [
                    HumanMessage(content="input"),
                    AIMessage(content="# AAPL Report\nBuy."),
                ]
            }
        )
        mock_react.return_value = mock_agent
        mock_llm.return_value = MagicMock()

        # Setup KB
        kb = KnowledgeBase(kb_root=tmp_path)
        kb.ensure_structure()
        (tmp_path / "agent_principles.md").write_text(
            "Be objective.", encoding="utf-8"
        )

        agent = CoreAgent(ANALYSIS_PROFILE, kb=kb)
        result = await agent.run(
            "Analyze AAPL",
            {"ticker": "AAPL", "timestamp": "2026-05-15 12:00 UTC"},
        )

        assert "AAPL" in result or "Report" in result
        mock_react.assert_called_once()
        mock_agent.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.agents.core_agent.create_react_agent")
    @patch("src.agents.core_agent.create_llm")
    @patch("src.agents.core_agent.create_context_hooks")
    async def test_run_timeout_returns_error(
        self, mock_hooks, mock_llm, mock_react, tmp_path
    ):
        """Timeout should produce an error report, not raise."""
        mock_hooks.return_value = (
            lambda s: {
                "llm_input_messages": s.get("messages", [])
            },
            lambda s: s,
        )

        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )
        mock_react.return_value = mock_agent
        mock_llm.return_value = MagicMock()

        kb = KnowledgeBase(kb_root=tmp_path)
        kb.ensure_structure()
        (tmp_path / "agent_principles.md").write_text(
            "Be objective.", encoding="utf-8"
        )

        agent = CoreAgent(ANALYSIS_PROFILE, kb=kb)
        result = await agent.run(
            "Analyze AAPL",
            {"ticker": "AAPL", "timestamp": "2026-05-15"},
        )

        assert "Error" in result
        assert "timed out" in result

    @pytest.mark.asyncio
    @patch("src.agents.core_agent.create_react_agent")
    @patch("src.agents.core_agent.create_llm")
    @patch("src.agents.core_agent.create_context_hooks")
    async def test_run_exception_returns_error(
        self, mock_hooks, mock_llm, mock_react, tmp_path
    ):
        """General exception should produce an error report, not raise."""
        mock_hooks.return_value = (
            lambda s: {
                "llm_input_messages": s.get("messages", [])
            },
            lambda s: s,
        )

        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(
            side_effect=RuntimeError("LLM connection failed")
        )
        mock_react.return_value = mock_agent
        mock_llm.return_value = MagicMock()

        kb = KnowledgeBase(kb_root=tmp_path)
        kb.ensure_structure()
        (tmp_path / "agent_principles.md").write_text(
            "Be objective.", encoding="utf-8"
        )

        agent = CoreAgent(ANALYSIS_PROFILE, kb=kb)
        result = await agent.run(
            "Analyze AAPL",
            {"ticker": "AAPL", "timestamp": "2026-05-15"},
        )

        assert "Error" in result
        assert "LLM connection failed" in result

    @pytest.mark.asyncio
    @patch("src.agents.core_agent.create_react_agent")
    @patch("src.agents.core_agent.create_llm")
    @patch("src.agents.core_agent.create_context_hooks")
    async def test_run_strips_code_block_wrapper(
        self, mock_hooks, mock_llm, mock_react, tmp_path
    ):
        """Output wrapped in ```markdown ... ``` should be stripped."""
        mock_hooks.return_value = (
            lambda s: {
                "llm_input_messages": s.get("messages", [])
            },
            lambda s: s,
        )

        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(
            return_value={
                "messages": [
                    AIMessage(
                        content="```markdown\n# Report\nContent here.\n```"
                    ),
                ]
            }
        )
        mock_react.return_value = mock_agent
        mock_llm.return_value = MagicMock()

        kb = KnowledgeBase(kb_root=tmp_path)
        kb.ensure_structure()
        (tmp_path / "agent_principles.md").write_text(
            "Be objective.", encoding="utf-8"
        )

        agent = CoreAgent(ANALYSIS_PROFILE, kb=kb)
        result = await agent.run(
            "Analyze X",
            {"ticker": "X", "timestamp": "2026-05-15"},
        )

        assert not result.startswith("```")
        assert not result.endswith("```")
        assert "# Report" in result

    @pytest.mark.asyncio
    @patch("src.agents.core_agent.create_react_agent")
    @patch("src.agents.core_agent.create_llm")
    @patch("src.agents.core_agent.create_context_hooks")
    async def test_run_calls_output_handler(
        self, mock_hooks, mock_llm, mock_react, tmp_path
    ):
        """Output handler should be called after successful run."""
        mock_hooks.return_value = (
            lambda s: {
                "llm_input_messages": s.get("messages", [])
            },
            lambda s: s,
        )

        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(
            return_value={
                "messages": [
                    AIMessage(content="# Report for AAPL"),
                ]
            }
        )
        mock_react.return_value = mock_agent
        mock_llm.return_value = MagicMock()

        kb = KnowledgeBase(kb_root=tmp_path)
        kb.ensure_structure()
        (tmp_path / "agent_principles.md").write_text(
            "Be objective.", encoding="utf-8"
        )

        handler_mock = AsyncMock()
        profile = AgentProfile(
            name="test",
            system_prompt_template="{agent_principles}{core_mind_content}{user_views_content}{divergences_content}{ticker}{timestamp}",
            tool_names=["kb_list", "kb_read"],
            max_rounds=5,
            output_handler=handler_mock,
            context_manager_config={
                "max_tokens": 10_000,
                "snip_threshold": 1000,
                "protect_last_n": 2,
            },
        )

        agent = CoreAgent(profile, kb=kb)
        await agent.run(
            "Analyze AAPL",
            {"ticker": "AAPL", "timestamp": "2026-05-15"},
        )

        handler_mock.assert_called_once()
        call_args = handler_mock.call_args[0]
        assert "Report for AAPL" in call_args[0]  # output
        assert call_args[1]["ticker"] == "AAPL"  # context
        assert call_args[2] is kb  # kb instance
