"""LangChain callback handler for observing ReAct agent tool calls and token usage.

Instantiate one ``AgentObserver`` per agent invocation and pass it via
``config={"callbacks": [observer]}``.  After the invocation completes,
retrieve structured data with ``get_tool_calls()`` and ``get_token_usage()``.

Real-time JSONL emission: when *sid* or *execution_id* is provided, tool-call
events are streamed to ``pipeline_events.jsonl`` as they happen, enabling
live dashboards to display the agent's "thinking process".
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

from src.utils.event_log import log_event

logger = logging.getLogger(__name__)

# Maximum characters to keep when logging tool outputs.
_MAX_OUTPUT_LENGTH = 100_000


class AgentObserver(BaseCallbackHandler):
    """Captures tool calls and token usage during a single agent invocation.

    This handler is **not** a singleton --- create a fresh instance for every
    ``agent.ainvoke()`` call so that data from different runs never mixes.

    Args:
        agent_name: Human-readable agent identifier for logging.
        sid: Pipeline session ID for JSONL event correlation.
        execution_id: Execution logger ID for cross-referencing logs.
        stage: Pipeline stage (e.g. ``"analysis"``, ``"digest"``).
    """

    def __init__(
        self,
        agent_name: str,
        *,
        sid: str = "",
        execution_id: str = "",
        stage: str = "analysis",
    ) -> None:
        super().__init__()
        self.agent_name = agent_name
        self._sid = sid
        self._execution_id = execution_id
        self._stage = stage
        self._tool_calls: List[Dict[str, Any]] = []
        self._llm_calls: List[Dict[str, Any]] = []
        self._react_steps: List[Dict[str, Any]] = []
        # Track in-progress tool calls by run_id
        self._pending_tools: Dict[str, Dict[str, Any]] = {}
        # Track in-progress LLM calls by run_id (for pairing start/end)
        self._pending_llm: Dict[str, Dict[str, Any]] = {}
        self._step_counter: int = 0

    # ------------------------------------------------------------------
    # Tool lifecycle
    # ------------------------------------------------------------------

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        inputs: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        tool_name = serialized.get("name") or serialized.get("id", ["unknown"])[-1]
        entry = {
            "tool_name": tool_name,
            "input": self._truncate(input_str),
            "start_time": time.time(),
        }
        self._pending_tools[str(run_id)] = entry
        self._emit_event(
            "agent.tool_call.start",
            tool_name=tool_name,
            input=self._truncate(input_str, 200),
        )

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        rid = str(run_id)
        entry = self._pending_tools.pop(rid, {})
        start = entry.get("start_time", time.time())
        duration = round(time.time() - start, 3)
        entry.update({
            "output": self._truncate(str(output)),
            "duration_seconds": duration,
            "success": True,
        })
        self._tool_calls.append(entry)
        self._emit_event(
            "agent.tool_call.end",
            tool_name=entry.get("tool_name", "unknown"),
            duration_s=duration,
            success=True,
            output_length=len(str(output)),
        )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> Any:
        rid = str(run_id)
        entry = self._pending_tools.pop(rid, {})
        start = entry.get("start_time", time.time())
        duration = round(time.time() - start, 3)
        entry.update({
            "output": None,
            "error": self._truncate(str(error)),
            "duration_seconds": duration,
            "success": False,
        })
        self._tool_calls.append(entry)
        self._emit_event(
            "agent.tool_call.end",
            tool_name=entry.get("tool_name", "unknown"),
            duration_s=duration,
            success=False,
            error=self._truncate(str(error), 200),
        )

    # ------------------------------------------------------------------
    # LLM lifecycle (token usage + ReAct step capture)
    # ------------------------------------------------------------------

    def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """Capture the input state at the start of each LLM call (ReAct round)."""
        msg_list = messages[0] if messages else []
        total_chars = sum(len(str(getattr(m, "content", ""))) for m in msg_list)
        self._pending_llm[str(run_id)] = {
            "start_time": time.time(),
            "message_count": len(msg_list),
            "total_chars": total_chars,
        }

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Any:
        usage = self._extract_token_usage(response)
        if usage:
            self._llm_calls.append(usage)

        # Build ReAct step record by pairing with on_chat_model_start data
        pending = self._pending_llm.pop(str(run_id), None)
        if pending is None:
            return

        self._step_counter += 1
        output_text, tool_calls_made = self._extract_llm_output(response)

        step: Dict[str, Any] = {
            "step": self._step_counter,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "input": {
                "message_count": pending["message_count"],
                "total_chars": pending["total_chars"],
            },
            "output": {
                "text": output_text,
                "text_length": len(output_text),
                "tool_calls": tool_calls_made,
            },
        }
        if usage:
            step["tokens"] = usage
        self._react_steps.append(step)

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_tool_calls(self) -> List[Dict[str, Any]]:
        """Return a list of recorded tool calls (in order of completion)."""
        return list(self._tool_calls)

    def get_react_steps(self) -> List[Dict[str, Any]]:
        """Return ReAct step records captured during the agent invocation.

        Each step corresponds to one LLM call within the ReAct loop and
        contains input message stats, output text, and any tool-call decisions.
        """
        return list(self._react_steps)

    def get_token_usage(self) -> Dict[str, Any]:
        """Return aggregated token usage across all LLM calls in this invocation.

        Returns an empty dict if no token usage data was captured (e.g. the
        provider did not include it in the response).
        """
        if not self._llm_calls:
            return {}

        total: Dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "reasoning_tokens": None,
            "llm_call_count": len(self._llm_calls),
        }

        has_reasoning = False
        for call in self._llm_calls:
            total["prompt_tokens"] += call.get("prompt_tokens", 0)
            total["completion_tokens"] += call.get("completion_tokens", 0)
            total["total_tokens"] += call.get("total_tokens", 0)
            rt = call.get("reasoning_tokens")
            if rt is not None:
                has_reasoning = True
                total["reasoning_tokens"] = (total["reasoning_tokens"] or 0) + rt

        if not has_reasoning:
            total["reasoning_tokens"] = None

        return total

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_llm_output(response: LLMResult) -> tuple:
        """Extract output text and tool_calls from an LLMResult.

        Returns:
            (output_text, tool_calls_made) where tool_calls_made is a list of
            dicts with 'name' and 'args' keys.
        """
        output_text = ""
        tool_calls_made: List[Dict[str, Any]] = []
        try:
            generations = getattr(response, "generations", None) or []
            if generations and generations[0]:
                gen = generations[0][0]
                msg = getattr(gen, "message", None)
                if msg is not None:
                    content = getattr(msg, "content", "")
                    if isinstance(content, str):
                        output_text = content
                    elif isinstance(content, list):
                        parts = []
                        for item in content:
                            if isinstance(item, str):
                                parts.append(item)
                            elif isinstance(item, dict):
                                parts.append(item.get("text", ""))
                        output_text = "".join(parts)
                    # Extract tool calls from AIMessage
                    raw_calls = getattr(msg, "tool_calls", None) or []
                    for tc in raw_calls:
                        if isinstance(tc, dict):
                            tool_calls_made.append({
                                "name": tc.get("name", ""),
                                "args": tc.get("args", {}),
                            })
        except (IndexError, AttributeError):
            pass
        return output_text, tool_calls_made

    @staticmethod
    def _truncate(text: str, max_length: int = _MAX_OUTPUT_LENGTH) -> str:
        """Truncate text to *max_length* chars, appending an ellipsis if cut."""
        if len(text) <= max_length:
            return text
        return text[:max_length] + "..."

    def _emit_event(self, event: str, **data: Any) -> None:
        """Emit a real-time event to the JSONL pipeline log."""
        if not self._sid and not self._execution_id:
            return  # No context IDs — skip JSONL emission (e.g. in tests)
        try:
            log_event(
                event,
                stage=self._stage,
                sid=self._sid,
                execution_id=self._execution_id,
                agent=self.agent_name,
                **data,
            )
        except Exception:
            pass  # Observability must never crash the agent

    @staticmethod
    def _extract_token_usage(response: LLMResult) -> Dict[str, Any]:
        """Best-effort extraction of token usage from an ``LLMResult``.

        Checks three paths (in priority order):
        1. ``response.llm_output["token_usage"]`` — OpenAI-compatible providers
        2. ``response.generations[0][0].generation_info`` — fallback
        3. ``response.generations[0][0].message.usage_metadata`` — LangChain standard

        Path 3 uses LangChain's normalized ``input_tokens``/``output_tokens`` keys,
        which work across all providers (DeepSeek, OpenAI, Gemini).
        """
        usage: Dict[str, Any] = {}

        # Path 1: response.llm_output (most common for OpenAI-compatible)
        llm_output = getattr(response, "llm_output", None) or {}
        token_usage = llm_output.get("token_usage", {})

        # Path 2: response.generations[0][0].generation_info
        gen_info: Dict[str, Any] = {}
        # Path 3: response.generations[0][0].message.usage_metadata
        usage_metadata: Dict[str, Any] = {}
        try:
            generations = getattr(response, "generations", None) or []
            if generations and generations[0]:
                gen_info = getattr(generations[0][0], "generation_info", None) or {}
                gen_message = getattr(generations[0][0], "message", None)
                if gen_message is not None:
                    um = getattr(gen_message, "usage_metadata", None)
                    if um and isinstance(um, dict):
                        usage_metadata = um
        except (IndexError, AttributeError):
            pass

        # Merge — prefer llm_output, fall back to generation_info, then usage_metadata
        src = token_usage or gen_info.get("token_usage", {}) or gen_info

        prompt_tokens = src.get("prompt_tokens", 0) or usage_metadata.get("input_tokens", 0)
        completion_tokens = src.get("completion_tokens", 0) or usage_metadata.get("output_tokens", 0)
        total_tokens = src.get("total_tokens", 0) or usage_metadata.get("total_tokens", 0)

        if not any([prompt_tokens, completion_tokens, total_tokens]):
            return {}

        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens or (prompt_tokens + completion_tokens),
        }

        # Reasoning tokens (DeepSeek / OpenAI o-series)
        details = src.get("completion_tokens_details", {}) or {}
        reasoning = details.get("reasoning_tokens")
        usage["reasoning_tokens"] = reasoning  # may be None

        # Cache tokens (DeepSeek-specific, harmless None for others)
        cache_hit = src.get("prompt_cache_hit_tokens")
        cache_miss = src.get("prompt_cache_miss_tokens")
        if cache_hit is not None:
            usage["prompt_cache_hit_tokens"] = cache_hit
        if cache_miss is not None:
            usage["prompt_cache_miss_tokens"] = cache_miss

        return usage
