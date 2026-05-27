"""Tests for AgentObserver: tool-call capture, token extraction, and JSONL emission."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from src.utils.observability import AgentObserver


# =========================================================================
# Tool-call capture
# =========================================================================


class TestToolCallCapture:
    """Verify on_tool_start / on_tool_end / on_tool_error recording."""

    def test_successful_tool_call(self):
        obs = AgentObserver("test_agent")
        rid = uuid4()
        obs.on_tool_start(
            {"name": "kb_read"}, '{"slug": "AAPL/report"}', run_id=rid
        )
        obs.on_tool_end("file contents here", run_id=rid)

        calls = obs.get_tool_calls()
        assert len(calls) == 1
        assert calls[0]["tool_name"] == "kb_read"
        assert calls[0]["success"] is True
        assert calls[0]["duration_seconds"] >= 0
        assert "file contents" in calls[0]["output"]

    def test_failed_tool_call(self):
        obs = AgentObserver("test_agent")
        rid = uuid4()
        obs.on_tool_start({"name": "kb_write"}, "input", run_id=rid)
        obs.on_tool_error(ValueError("write failed"), run_id=rid)

        calls = obs.get_tool_calls()
        assert len(calls) == 1
        assert calls[0]["success"] is False
        assert "write failed" in calls[0]["error"]

    def test_multiple_tool_calls_ordered(self):
        obs = AgentObserver("test_agent")
        rid1, rid2 = uuid4(), uuid4()
        obs.on_tool_start({"name": "tool_a"}, "in1", run_id=rid1)
        obs.on_tool_end("out1", run_id=rid1)
        obs.on_tool_start({"name": "tool_b"}, "in2", run_id=rid2)
        obs.on_tool_end("out2", run_id=rid2)

        calls = obs.get_tool_calls()
        assert len(calls) == 2
        assert calls[0]["tool_name"] == "tool_a"
        assert calls[1]["tool_name"] == "tool_b"

    def test_tool_name_fallback_to_id(self):
        """When serialized has no 'name', fall back to last element of 'id'."""
        obs = AgentObserver("test_agent")
        rid = uuid4()
        obs.on_tool_start(
            {"id": ["langchain", "tools", "my_tool"]}, "input", run_id=rid
        )
        obs.on_tool_end("output", run_id=rid)

        assert obs.get_tool_calls()[0]["tool_name"] == "my_tool"

    def test_output_truncated(self):
        obs = AgentObserver("test_agent")
        rid = uuid4()
        obs.on_tool_start({"name": "kb_read"}, "in", run_id=rid)
        long_output = "x" * 200_000
        obs.on_tool_end(long_output, run_id=rid)

        output = obs.get_tool_calls()[0]["output"]
        assert len(output) <= 100_003  # _MAX_OUTPUT_LENGTH (100000) + "..."

    def test_get_tool_calls_returns_copy(self):
        obs = AgentObserver("test_agent")
        calls1 = obs.get_tool_calls()
        calls1.append({"fake": True})
        assert len(obs.get_tool_calls()) == 0


# =========================================================================
# Token usage extraction
# =========================================================================


class TestTokenExtraction:
    """Verify _extract_token_usage from various LLMResult structures."""

    def test_path1_llm_output(self):
        """Extract from response.llm_output.token_usage (OpenAI-compatible)."""
        response = LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="hi"))]],
            llm_output={
                "token_usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                }
            },
        )
        usage = AgentObserver._extract_token_usage(response)
        assert usage["prompt_tokens"] == 100
        assert usage["completion_tokens"] == 50
        assert usage["total_tokens"] == 150

    def test_path1_with_reasoning_tokens(self):
        """DeepSeek/OpenAI o-series reasoning tokens."""
        response = LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="hi"))]],
            llm_output={
                "token_usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 80,
                    "total_tokens": 180,
                    "completion_tokens_details": {"reasoning_tokens": 30},
                }
            },
        )
        usage = AgentObserver._extract_token_usage(response)
        assert usage["reasoning_tokens"] == 30

    def test_path1_with_cache_tokens(self):
        """DeepSeek cache hit/miss tokens."""
        response = LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="hi"))]],
            llm_output={
                "token_usage": {
                    "prompt_tokens": 200,
                    "completion_tokens": 50,
                    "total_tokens": 250,
                    "prompt_cache_hit_tokens": 150,
                    "prompt_cache_miss_tokens": 50,
                }
            },
        )
        usage = AgentObserver._extract_token_usage(response)
        assert usage["prompt_cache_hit_tokens"] == 150
        assert usage["prompt_cache_miss_tokens"] == 50

    def test_path3_usage_metadata(self):
        """Extract from generation.message.usage_metadata (LangChain standard)."""
        msg = AIMessage(content="hi")
        msg.usage_metadata = {
            "input_tokens": 80,
            "output_tokens": 40,
            "total_tokens": 120,
        }
        gen = ChatGeneration(message=msg)
        response = LLMResult(generations=[[gen]], llm_output={})

        usage = AgentObserver._extract_token_usage(response)
        assert usage["prompt_tokens"] == 80
        assert usage["completion_tokens"] == 40
        assert usage["total_tokens"] == 120

    def test_no_usage_returns_empty(self):
        """Return empty dict when no token data is available."""
        response = LLMResult(generations=[[ChatGeneration(message=AIMessage(content="hi"))]])
        usage = AgentObserver._extract_token_usage(response)
        assert usage == {}

    def test_aggregation_across_llm_calls(self):
        """get_token_usage() should aggregate across multiple on_llm_end calls."""
        obs = AgentObserver("test_agent")

        for prompt_t, comp_t in [(100, 50), (200, 80)]:
            response = LLMResult(
                generations=[[ChatGeneration(message=AIMessage(content="hi"))]],
                llm_output={
                    "token_usage": {
                        "prompt_tokens": prompt_t,
                        "completion_tokens": comp_t,
                        "total_tokens": prompt_t + comp_t,
                    }
                },
            )
            obs.on_llm_end(response, run_id=uuid4())

        total = obs.get_token_usage()
        assert total["prompt_tokens"] == 300
        assert total["completion_tokens"] == 130
        assert total["total_tokens"] == 430
        assert total["llm_call_count"] == 2

    def test_no_reasoning_returns_none(self):
        """reasoning_tokens should be None when not present."""
        obs = AgentObserver("test_agent")
        response = LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="hi"))]],
            llm_output={
                "token_usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                }
            },
        )
        obs.on_llm_end(response, run_id=uuid4())
        assert obs.get_token_usage()["reasoning_tokens"] is None

    def test_cache_tokens_absent_by_default(self):
        """Cache token fields should not appear when provider doesn't send them."""
        response = LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="hi"))]],
            llm_output={
                "token_usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                }
            },
        )
        usage = AgentObserver._extract_token_usage(response)
        assert "prompt_cache_hit_tokens" not in usage
        assert "prompt_cache_miss_tokens" not in usage


# =========================================================================
# Real-time JSONL emission
# =========================================================================


class TestJSONLEmission:
    """Verify that tool-call events are emitted to JSONL in real time."""

    @patch("src.utils.observability.log_event")
    def test_tool_start_emits_event(self, mock_log_event):
        obs = AgentObserver(
            "core_digest", sid="digest-001", execution_id="exec-001", stage="digest"
        )
        rid = uuid4()
        obs.on_tool_start({"name": "kb_read"}, '{"slug": "AAPL"}', run_id=rid)

        mock_log_event.assert_called_once()
        call_kwargs = mock_log_event.call_args
        assert call_kwargs[0][0] == "agent.tool_call.start"
        assert call_kwargs[1]["agent"] == "core_digest"
        assert call_kwargs[1]["tool_name"] == "kb_read"
        assert call_kwargs[1]["stage"] == "digest"
        assert call_kwargs[1]["sid"] == "digest-001"

    @patch("src.utils.observability.log_event")
    def test_tool_end_emits_event(self, mock_log_event):
        obs = AgentObserver(
            "core_digest", sid="s1", execution_id="e1", stage="digest"
        )
        rid = uuid4()
        obs.on_tool_start({"name": "kb_write"}, "input", run_id=rid)
        mock_log_event.reset_mock()

        obs.on_tool_end("written OK", run_id=rid)

        mock_log_event.assert_called_once()
        kw = mock_log_event.call_args[1]
        assert kw["tool_name"] == "kb_write"
        assert kw["success"] is True
        assert "duration_s" in kw
        assert kw["output_length"] == len("written OK")

    @patch("src.utils.observability.log_event")
    def test_tool_error_emits_event(self, mock_log_event):
        obs = AgentObserver("agent", sid="s1", execution_id="e1")
        rid = uuid4()
        obs.on_tool_start({"name": "kb_read"}, "in", run_id=rid)
        mock_log_event.reset_mock()

        obs.on_tool_error(RuntimeError("not found"), run_id=rid)

        kw = mock_log_event.call_args[1]
        assert kw["success"] is False
        assert "not found" in kw["error"]

    @patch("src.utils.observability.log_event")
    def test_no_emission_without_context_ids(self, mock_log_event):
        """Without sid/execution_id, no JSONL events should be emitted."""
        obs = AgentObserver("test_agent")
        rid = uuid4()
        obs.on_tool_start({"name": "kb_read"}, "input", run_id=rid)
        obs.on_tool_end("output", run_id=rid)

        mock_log_event.assert_not_called()
        # But tool calls are still captured internally
        assert len(obs.get_tool_calls()) == 1

    @patch("src.utils.observability.log_event", side_effect=Exception("disk full"))
    def test_emission_failure_does_not_crash(self, mock_log_event):
        """JSONL emission failure must not affect agent execution."""
        obs = AgentObserver("agent", sid="s1", execution_id="e1")
        rid = uuid4()
        # Should not raise
        obs.on_tool_start({"name": "kb_read"}, "input", run_id=rid)
        obs.on_tool_end("output", run_id=rid)
        assert len(obs.get_tool_calls()) == 1
