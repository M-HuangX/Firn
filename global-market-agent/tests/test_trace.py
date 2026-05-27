"""Tests for the full-fidelity trace system (prompts + ReAct steps)."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from src.utils.execution_logger import ExecutionLogger
from src.utils.observability import AgentObserver


# =========================================================================
# ExecutionLogger trace methods
# =========================================================================


class TestLogTracePrompt:
    """Verify log_trace_prompt saves full prompts and handles multi-batch."""

    def test_saves_full_prompt(self, tmp_path):
        logger = ExecutionLogger(base_log_dir=str(tmp_path))
        prompt = "You are a financial analyst." * 100  # ~3500 chars

        logger.log_trace_prompt("fundamental", "system", prompt)

        path = logger.execution_dir / "trace/prompts/fundamental_system.txt"
        assert path.exists()
        assert path.read_text(encoding="utf-8") == prompt

    def test_saves_user_prompt(self, tmp_path):
        logger = ExecutionLogger(base_log_dir=str(tmp_path))
        user_prompt = "Analyze AAPL stock fundamentals..." * 50

        logger.log_trace_prompt("fundamental", "user", user_prompt)

        path = logger.execution_dir / "trace/prompts/fundamental_user.txt"
        assert path.exists()
        assert path.read_text(encoding="utf-8") == user_prompt

    def test_multi_batch_auto_numbering(self, tmp_path):
        logger = ExecutionLogger(base_log_dir=str(tmp_path))

        logger.log_trace_prompt("core_digest", "system", "batch 1 system")
        logger.log_trace_prompt("core_digest", "system", "batch 2 system")
        logger.log_trace_prompt("core_digest", "system", "batch 3 system")

        prompts_dir = logger.execution_dir / "trace/prompts"
        assert (prompts_dir / "core_digest_system.txt").read_text() == "batch 1 system"
        assert (prompts_dir / "core_digest_b2_system.txt").read_text() == "batch 2 system"
        assert (prompts_dir / "core_digest_b3_system.txt").read_text() == "batch 3 system"

    def test_multi_batch_user_prompts(self, tmp_path):
        logger = ExecutionLogger(base_log_dir=str(tmp_path))

        logger.log_trace_prompt("core_digest", "user", "batch 1 articles")
        logger.log_trace_prompt("core_digest", "user", "batch 2 articles")

        prompts_dir = logger.execution_dir / "trace/prompts"
        assert (prompts_dir / "core_digest_user.txt").read_text() == "batch 1 articles"
        assert (prompts_dir / "core_digest_b2_user.txt").read_text() == "batch 2 articles"

    def test_different_agents_no_collision(self, tmp_path):
        logger = ExecutionLogger(base_log_dir=str(tmp_path))

        logger.log_trace_prompt("fundamental", "system", "fund sys")
        logger.log_trace_prompt("technical", "system", "tech sys")
        logger.log_trace_prompt("core_analysis", "system", "core sys")

        prompts_dir = logger.execution_dir / "trace/prompts"
        assert (prompts_dir / "fundamental_system.txt").read_text() == "fund sys"
        assert (prompts_dir / "technical_system.txt").read_text() == "tech sys"
        assert (prompts_dir / "core_analysis_system.txt").read_text() == "core sys"


class TestLogTraceSteps:
    """Verify log_trace_steps writes JSONL correctly."""

    def test_writes_jsonl(self, tmp_path):
        logger = ExecutionLogger(base_log_dir=str(tmp_path))
        steps = [
            {"step": 1, "ts": "2026-05-16T10:00:00", "output": {"text": "hello"}},
            {"step": 2, "ts": "2026-05-16T10:00:05", "output": {"text": "world"}},
        ]

        logger.log_trace_steps("fundamental", steps)

        path = logger.execution_dir / "trace/react_steps/fundamental_steps.jsonl"
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["step"] == 1
        assert json.loads(lines[1])["output"]["text"] == "world"

    def test_append_mode_for_multi_batch(self, tmp_path):
        logger = ExecutionLogger(base_log_dir=str(tmp_path))

        # Batch 1
        logger.log_trace_steps("core_digest", [
            {"step": 1, "batch": 1, "output": {"text": "b1s1"}},
            {"step": 2, "batch": 1, "output": {"text": "b1s2"}},
        ])
        # Batch 2
        logger.log_trace_steps("core_digest", [
            {"step": 1, "batch": 2, "output": {"text": "b2s1"}},
        ])

        path = logger.execution_dir / "trace/react_steps/core_digest_steps.jsonl"
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3
        assert json.loads(lines[0])["batch"] == 1
        assert json.loads(lines[2])["batch"] == 2

    def test_empty_steps_no_file(self, tmp_path):
        logger = ExecutionLogger(base_log_dir=str(tmp_path))
        logger.log_trace_steps("fundamental", [])

        path = logger.execution_dir / "trace/react_steps/fundamental_steps.jsonl"
        assert not path.exists()

    def test_unicode_content(self, tmp_path):
        logger = ExecutionLogger(base_log_dir=str(tmp_path))
        steps = [{"step": 1, "output": {"text": "分析贵州茅台的基本面"}}]

        logger.log_trace_steps("core_analysis", steps)

        path = logger.execution_dir / "trace/react_steps/core_analysis_steps.jsonl"
        data = json.loads(path.read_text(encoding="utf-8").strip())
        assert "贵州茅台" in data["output"]["text"]


class TestLogToolCallsMultiBatch:
    """Verify tool_calls files are not overwritten in multi-batch digest."""

    def test_single_batch_uses_base_name(self, tmp_path):
        logger = ExecutionLogger(base_log_dir=str(tmp_path))
        logger.log_tool_calls("core_digest", [{"tool_name": "kb_read", "output": "data1"}])

        path = logger.execution_dir / "tools/core_digest_tool_calls.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["tool_call_count"] == 1

    def test_multi_batch_auto_numbers(self, tmp_path):
        logger = ExecutionLogger(base_log_dir=str(tmp_path))

        # Batch 1
        logger.log_tool_calls("core_digest", [{"tool_name": "read_inbox_item", "output": "article1"}])
        # Batch 2
        logger.log_tool_calls("core_digest", [{"tool_name": "read_inbox_item", "output": "article2"}])
        # Batch 3
        logger.log_tool_calls("core_digest", [{"tool_name": "kb_write", "output": "wrote theme"}])

        tools_dir = logger.execution_dir / "tools"
        assert (tools_dir / "core_digest_tool_calls.json").exists()
        assert (tools_dir / "core_digest_b2_tool_calls.json").exists()
        assert (tools_dir / "core_digest_b3_tool_calls.json").exists()

        # Verify each file has its own data (not overwritten)
        b1 = json.loads((tools_dir / "core_digest_tool_calls.json").read_text())
        b2 = json.loads((tools_dir / "core_digest_b2_tool_calls.json").read_text())
        b3 = json.loads((tools_dir / "core_digest_b3_tool_calls.json").read_text())
        assert b1["tool_calls"][0]["output"] == "article1"
        assert b2["tool_calls"][0]["output"] == "article2"
        assert b3["tool_calls"][0]["tool_name"] == "kb_write"

    def test_different_agents_no_collision(self, tmp_path):
        logger = ExecutionLogger(base_log_dir=str(tmp_path))

        logger.log_tool_calls("fundamental", [{"tool_name": "get_stock_info"}])
        logger.log_tool_calls("technical", [{"tool_name": "get_price_history"}])

        tools_dir = logger.execution_dir / "tools"
        assert (tools_dir / "fundamental_tool_calls.json").exists()
        assert (tools_dir / "technical_tool_calls.json").exists()


class TestTraceDirectoryInit:
    """Verify trace directories are created on logger init."""

    def test_trace_dirs_created(self, tmp_path):
        logger = ExecutionLogger(base_log_dir=str(tmp_path))

        assert (logger.execution_dir / "trace/prompts").is_dir()
        assert (logger.execution_dir / "trace/react_steps").is_dir()
        assert (logger.execution_dir / "trace/verification").is_dir()


class TestLogVerification:
    """Verify log_verification saves sidecar JSON with full inputs/outputs."""

    def test_saves_verification_sidecar(self, tmp_path):
        logger = ExecutionLogger(base_log_dir=str(tmp_path))
        data = {
            "ticker": "AAPL",
            "inputs": {"current_price": 185.0, "current_eps": 6.5},
            "result": {"implied_growth_rate": 0.092, "cf_per_share": 6.5},
        }

        logger.log_verification("reverse_dcf", data)

        path = logger.execution_dir / "trace/verification/reverse_dcf.json"
        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["ticker"] == "AAPL"
        assert loaded["inputs"]["current_price"] == 185.0
        assert loaded["result"]["implied_growth_rate"] == 0.092

    def test_overwrites_on_second_call(self, tmp_path):
        logger = ExecutionLogger(base_log_dir=str(tmp_path))

        logger.log_verification("reverse_dcf", {"version": 1})
        logger.log_verification("reverse_dcf", {"version": 2})

        path = logger.execution_dir / "trace/verification/reverse_dcf.json"
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["version"] == 2

    def test_multiple_modules(self, tmp_path):
        logger = ExecutionLogger(base_log_dir=str(tmp_path))

        logger.log_verification("reverse_dcf", {"module": "dcf"})
        logger.log_verification("scenario_analysis", {"module": "scenario"})

        dcf_path = logger.execution_dir / "trace/verification/reverse_dcf.json"
        scenario_path = logger.execution_dir / "trace/verification/scenario_analysis.json"
        assert dcf_path.exists()
        assert scenario_path.exists()


# =========================================================================
# AgentObserver ReAct step capture
# =========================================================================


def _make_llm_result(content: str = "analysis text", tool_calls=None, tokens=None):
    """Helper to create an LLMResult with optional tool_calls and token usage."""
    msg = AIMessage(content=content)
    if tool_calls:
        msg.tool_calls = tool_calls
    gen = ChatGeneration(message=msg)
    llm_output = {}
    if tokens:
        llm_output = {"token_usage": tokens}
    return LLMResult(generations=[[gen]], llm_output=llm_output)


class TestReActStepCapture:
    """Verify on_chat_model_start + on_llm_end pairing → get_react_steps()."""

    def test_single_step_captured(self):
        obs = AgentObserver("test_agent")
        rid = uuid4()

        # Simulate one ReAct round
        obs.on_chat_model_start(
            {},
            [[SystemMessage(content="sys"), HumanMessage(content="user query")]],
            run_id=rid,
        )
        obs.on_llm_end(
            _make_llm_result("I should check the stock info"),
            run_id=rid,
        )

        steps = obs.get_react_steps()
        assert len(steps) == 1
        assert steps[0]["step"] == 1
        assert steps[0]["input"]["message_count"] == 2
        assert steps[0]["input"]["total_chars"] > 0
        assert steps[0]["output"]["text"] == "I should check the stock info"
        assert steps[0]["output"]["tool_calls"] == []

    def test_step_with_tool_calls(self):
        obs = AgentObserver("test_agent")
        rid = uuid4()

        obs.on_chat_model_start({}, [[HumanMessage(content="analyze")]], run_id=rid)
        obs.on_llm_end(
            _make_llm_result(
                "Let me check fundamentals",
                tool_calls=[
                    {"name": "get_stock_info", "args": {"ticker": "AAPL"}, "id": "1"},
                ],
            ),
            run_id=rid,
        )

        steps = obs.get_react_steps()
        assert len(steps[0]["output"]["tool_calls"]) == 1
        assert steps[0]["output"]["tool_calls"][0]["name"] == "get_stock_info"
        assert steps[0]["output"]["tool_calls"][0]["args"] == {"ticker": "AAPL"}

    def test_multiple_steps_sequential(self):
        obs = AgentObserver("test_agent")

        for i in range(3):
            rid = uuid4()
            obs.on_chat_model_start(
                {}, [[HumanMessage(content=f"round {i}")]], run_id=rid
            )
            obs.on_llm_end(
                _make_llm_result(f"output {i}"),
                run_id=rid,
            )

        steps = obs.get_react_steps()
        assert len(steps) == 3
        assert steps[0]["step"] == 1
        assert steps[1]["step"] == 2
        assert steps[2]["step"] == 3
        assert steps[2]["output"]["text"] == "output 2"

    def test_step_with_token_usage(self):
        obs = AgentObserver("test_agent")
        rid = uuid4()

        obs.on_chat_model_start({}, [[HumanMessage(content="q")]], run_id=rid)
        obs.on_llm_end(
            _make_llm_result(
                "answer",
                tokens={
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
            ),
            run_id=rid,
        )

        steps = obs.get_react_steps()
        assert steps[0]["tokens"]["prompt_tokens"] == 100
        assert steps[0]["tokens"]["completion_tokens"] == 50

    def test_get_react_steps_returns_copy(self):
        obs = AgentObserver("test_agent")
        rid = uuid4()
        obs.on_chat_model_start({}, [[HumanMessage(content="q")]], run_id=rid)
        obs.on_llm_end(_make_llm_result("a"), run_id=rid)

        steps1 = obs.get_react_steps()
        steps1.append({"fake": True})
        assert len(obs.get_react_steps()) == 1

    def test_llm_end_without_start_ignored(self):
        """on_llm_end without matching on_chat_model_start produces no step."""
        obs = AgentObserver("test_agent")
        obs.on_llm_end(_make_llm_result("orphan"), run_id=uuid4())

        assert len(obs.get_react_steps()) == 0
        # But token usage is still captured
        assert obs.get_token_usage() == {}  # no tokens in this result

    def test_list_content_format(self):
        """Handle DeepSeek-style list content in AIMessage."""
        msg = AIMessage(content=[{"type": "text", "text": "思考过程..."}, {"type": "text", "text": "结论"}])
        gen = ChatGeneration(message=msg)
        result = LLMResult(generations=[[gen]], llm_output={})

        obs = AgentObserver("test_agent")
        rid = uuid4()
        obs.on_chat_model_start({}, [[HumanMessage(content="q")]], run_id=rid)
        obs.on_llm_end(result, run_id=rid)

        steps = obs.get_react_steps()
        assert steps[0]["output"]["text"] == "思考过程...结论"
