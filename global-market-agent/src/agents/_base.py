"""Shared logic for analysis agents (fundamental, technical, value).

Each analysis agent follows the same pattern:
1. Extract ticker/query from state
2. Build a detailed prompt from a template
3. Create a ReAct agent with LLM + MCP tools
4. Invoke and extract the last AI message
5. Store result in state[data][<data_key>]

This module provides ``run_react_analysis`` so each agent file only needs to
define its prompt template and call this function.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent
from tenacity import (
    retry,
    retry_if_exception_type,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.tools.mcp_client import get_mcp_tools
from src.utils.event_log import log_event
from src.utils.execution_logger import get_execution_logger
from src.utils.llm_clients import create_llm
from src.utils.observability import AgentObserver
from src.utils.state_definition import AgentState

# Per-agent timeout in seconds (default 5 minutes)
AGENT_TIMEOUT = int(os.getenv("AGENT_TIMEOUT_SECONDS", "300"))
# Max retries for the whole agent invocation (for non-timeout transient errors)
AGENT_MAX_RETRIES = int(os.getenv("AGENT_MAX_RETRIES", "2"))

logger = logging.getLogger(__name__)


def normalize_content(content: Any) -> str:
    """Convert AIMessage.content (str or list) to a plain string.

    Some LLM providers (e.g. DeepSeek with thinking mode) may return content
    as a list of dicts like ``[{"type": "text", "text": "..."}]`` instead of
    a plain string.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text", ""))
        return "".join(parts)
    return str(content)


async def run_react_analysis(
    state: AgentState,
    *,
    agent_name: str,
    data_key: str,
    system_prompt: str,
    user_prompt: str,
) -> dict:
    """Run a ReAct agent loop and store the result in ``state["data"][data_key]``.

    Args:
        state: Current workflow state.
        agent_name: Human-readable name for logging (e.g. ``"fundamental"``).
        data_key: Key under ``state["data"]`` to write the analysis text.
        system_prompt: Role definition, tools, output format (passed as system message).
        user_prompt: The specific analysis task (passed as user message).

    Returns:
        A dict suitable for merging back into ``AgentState``.
    """
    execution_logger = get_execution_logger()
    data = dict(state.get("data", {}))
    metadata = dict(state.get("metadata", {}))

    sid = metadata.get("event_sid", "")
    exec_id = metadata.get("execution_id", "")

    execution_logger.log_agent_start(agent_name, {
        "ticker": data.get("ticker"),
        "query": data.get("query"),
    })
    log_event(f"specialist.{agent_name}.start", stage="analysis",
              sid=sid, execution_id=exec_id,
              ticker=data.get("ticker", ""))

    t0 = time.time()

    try:
        # 1. Create LLM
        llm = create_llm()

        # 2. Get MCP tools
        tools = await get_mcp_tools()
        if not tools:
            msg = "MCP tools unavailable — check MCP server."
            logger.error("%s: %s", agent_name, msg)
            data[data_key] = f"Analysis unavailable: {msg}"
            data[f"{data_key}_error"] = msg
            execution_logger.log_agent_complete(
                agent_name, {"error": msg}, time.time() - t0, False, msg
            )
            return {"data": data, "messages": [], "metadata": metadata}

        logger.info(
            "%s: creating ReAct agent with %d tools", agent_name, len(tools)
        )

        # 3. Save full prompts to trace (before invocation — crash-safe)
        execution_logger.log_trace_prompt(agent_name, "system", system_prompt)
        execution_logger.log_trace_prompt(agent_name, "user", user_prompt)

        # 4. Create and invoke ReAct agent (with timeout + retry)
        agent = create_react_agent(llm, tools, prompt=system_prompt)
        observer = AgentObserver(
            agent_name,
            sid=sid,
            execution_id=exec_id,
            stage="analysis",
        )

        @retry(
            stop=stop_after_attempt(AGENT_MAX_RETRIES),
            wait=wait_exponential(multiplier=2, min=4, max=30),
            retry=(
                retry_if_exception_type((RuntimeError, ConnectionError, OSError))
                & retry_if_not_exception_type(GraphRecursionError)
            ),
            before_sleep=lambda rs: logger.warning(
                "%s: retrying agent (attempt %d/%d)",
                agent_name, rs.attempt_number + 1, AGENT_MAX_RETRIES,
            ),
            reraise=True,
        )
        async def _invoke_with_retry():
            return await asyncio.wait_for(
                agent.ainvoke(
                    {"messages": [HumanMessage(content=user_prompt)]},
                    config={"callbacks": [observer]},
                ),
                timeout=AGENT_TIMEOUT,
            )

        response = await _invoke_with_retry()

        elapsed = time.time() - t0

        # 4. Extract last AI message
        result = "No analysis generated."
        if "messages" in response:
            ai_msgs = [
                m for m in response["messages"] if isinstance(m, AIMessage)
            ]
            if ai_msgs:
                result = normalize_content(ai_msgs[-1].content)

        logger.info(
            "%s: analysis complete (%d chars, %.1fs)",
            agent_name,
            len(result),
            elapsed,
        )

        # 5. Log observability data (tool calls + token usage + trace steps)
        execution_logger.log_tool_calls(agent_name, observer.get_tool_calls())
        execution_logger.log_trace_steps(agent_name, observer.get_react_steps())
        token_usage = observer.get_token_usage()
        execution_logger.log_token_usage(agent_name, token_usage)

        log_event(f"specialist.{agent_name}.complete", stage="analysis",
                  sid=sid, execution_id=exec_id,
                  success=True, ticker=data.get("ticker", ""),
                  output_length=len(result), elapsed_s=round(elapsed, 1),
                  token_total=token_usage.get("total_tokens", 0),
                  tool_count=len(observer.get_tool_calls()))

        # 6. Log and return
        execution_logger.log_llm_interaction(
            agent_name=agent_name,
            interaction_type="react_agent",
            input_messages=[
                {"role": "system", "content": system_prompt[:300] + "..."},
                {"role": "user", "content": user_prompt[:300]},
            ],
            output_content=result,
            model_config={"provider": "env", "temperature": "env"},
            execution_time=elapsed,
        )
        execution_logger.log_agent_complete(
            agent_name,
            {"analysis_length": len(result), "preview": result[:300]},
            elapsed,
            True,
        )

        data[data_key] = result
        metadata[f"{agent_name}_executed"] = True
        metadata[f"{agent_name}_seconds"] = round(elapsed, 2)
        return {"data": data, "messages": [], "metadata": metadata}

    except asyncio.TimeoutError:
        elapsed = time.time() - t0
        msg = f"Agent timed out after {AGENT_TIMEOUT}s"
        logger.error("%s: %s", agent_name, msg)
        log_event(f"specialist.{agent_name}.complete", stage="analysis",
                  sid=sid, execution_id=exec_id,
                  success=False, error=msg[:200], elapsed_s=round(elapsed, 1))
        data[data_key] = f"Analysis unavailable: {msg}"
        data[f"{data_key}_error"] = msg
        execution_logger.log_agent_complete(
            agent_name, {"error": msg}, elapsed, False, msg
        )
        return {"data": data, "messages": [], "metadata": metadata}

    except Exception as e:
        elapsed = time.time() - t0
        logger.exception("%s: error during analysis", agent_name)
        log_event(f"specialist.{agent_name}.complete", stage="analysis",
                  sid=sid, execution_id=exec_id,
                  success=False, error=str(e)[:200], elapsed_s=round(elapsed, 1))
        data[data_key] = f"Analysis error: {e}"
        data[f"{data_key}_error"] = str(e)
        execution_logger.log_agent_complete(
            agent_name, {"error": str(e)}, elapsed, False, str(e)
        )
        return {"data": data, "messages": [], "metadata": metadata}
