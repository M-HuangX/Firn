"""Core Agent -- profile-driven ReAct agent with KB tools.

Replaces summary_agent.py. Uses KBToolSet (4.29) for knowledge base
access and context_manager hooks for context window management.

Does NOT use _base.py's run_react_analysis (which uses MCP tools).
Core Agent has its own invocation logic (SQU M6).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.prebuilt import create_react_agent
from langgraph.errors import GraphRecursionError
from tenacity import (
    retry,
    retry_if_exception_type,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.agents._base import normalize_content
from src.agents.profiles import AgentProfile
from src.knowledge_base.kb_api import KnowledgeBase
from src.utils.event_log import log_event
from src.knowledge_base.kb_tools import KBToolSet
from src.utils.context_manager import create_context_hooks
from src.utils.execution_logger import get_execution_logger
from src.utils.llm_clients import create_llm
from src.utils.observability import AgentObserver

logger = logging.getLogger(__name__)

AGENT_TIMEOUT = int(os.getenv("AGENT_TIMEOUT_SECONDS", "300"))


class CoreAgent:
    """Profile-driven Core Agent. One class, multiple behaviors via AgentProfile."""

    def __init__(self, profile: AgentProfile, kb: KnowledgeBase | None = None):
        self.profile = profile
        self.kb = kb or KnowledgeBase()
        self.toolset = KBToolSet(self.kb)

    async def run(self, input_data: str, context: dict[str, Any]) -> str:
        """Execute the agent loop and return final output text."""
        execution_logger = get_execution_logger()
        agent_name = f"core_{self.profile.name}"

        # Thread observability IDs to KB toolset
        self.toolset.event_sid = context.get("event_sid", "")
        self.toolset.execution_id = execution_logger.execution_id if execution_logger else ""

        observer = AgentObserver(
            agent_name,
            sid=context.get("event_sid", ""),
            execution_id=self.toolset.execution_id,
            stage=self.profile.name,
        )

        execution_logger.log_agent_start(agent_name, {
            "profile": self.profile.name,
            "ticker": context.get("ticker"),
        })

        t0 = time.time()

        try:
            # 1. Create LLM
            llm = create_llm(
                temperature=self.profile.llm_temperature,
                max_tokens=self.profile.llm_max_tokens,
            )

            # 2. Select tools by profile
            tools = self.toolset.get_tools_by_names(self.profile.tool_names)
            tools = tools + self._get_web_tools(self.profile.tool_names)

            # 3. Build system prompt
            system_prompt = self._build_system_prompt(context)

            # 4. Context management hooks
            pre_hook, post_hook = create_context_hooks(
                **self.profile.context_manager_config
            )

            # 5. Save full prompts to trace (before invocation — crash-safe)
            execution_logger.log_trace_prompt(agent_name, "system", system_prompt)
            execution_logger.log_trace_prompt(agent_name, "user", input_data)

            # 6. Create ReAct agent (NOT using _base.py -- SQU M6)
            agent = create_react_agent(
                llm, tools,
                prompt=system_prompt,
                pre_model_hook=pre_hook,
                post_model_hook=post_hook,
            )

            # 6. Invoke with timeout + retry
            # Each ReAct round = 4 graph nodes when hooks are present:
            # pre_model_hook → call_model → post_model_hook → tools
            recursion_limit = 4 * self.profile.max_rounds + 1

            @retry(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=2, min=4, max=30),
                retry=(
                    retry_if_exception_type(
                        (RuntimeError, ConnectionError, OSError)
                    ) & retry_if_not_exception_type(GraphRecursionError)
                ),
                before_sleep=lambda rs: logger.warning(
                    "%s: retrying (attempt %d/3)",
                    agent_name,
                    rs.attempt_number + 1,
                ),
                reraise=True,
            )
            async def _invoke():
                return await asyncio.wait_for(
                    agent.ainvoke(
                        {"messages": [HumanMessage(content=input_data)]},
                        config={
                            "recursion_limit": recursion_limit,
                            "callbacks": [observer],
                        },
                    ),
                    timeout=AGENT_TIMEOUT,
                )

            result = await _invoke()
            elapsed = time.time() - t0

            # 7. Extract output
            output = self._extract_output(result)

            # Strip code block wrappers (same as old summary_agent)
            output = output.strip()
            if output.startswith("```markdown"):
                output = output[len("```markdown"):]
            elif output.startswith("```"):
                output = output[3:]
            if output.endswith("```"):
                output = output[:-3]
            output = output.strip()

            # Log observability data (tool calls + token usage + trace steps)
            execution_logger.log_tool_calls(agent_name, observer.get_tool_calls())
            execution_logger.log_trace_steps(agent_name, observer.get_react_steps())
            token_usage = observer.get_token_usage()
            execution_logger.log_token_usage(agent_name, token_usage)

            logger.info(
                "%s: output generated (%d chars, %.1fs, %d tool calls)",
                agent_name, len(output), elapsed, len(observer.get_tool_calls()),
            )

            log_event(f"{self.profile.name}.core_complete",
                      stage=self.profile.name,
                      sid=context.get("event_sid", ""),
                      execution_id=self.toolset.execution_id,
                      ticker=context.get("ticker", ""),
                      output_length=len(output), elapsed_s=round(elapsed, 1),
                      token_total=token_usage.get("total_tokens", 0),
                      tool_count=len(observer.get_tool_calls()))

            # Log to execution logger
            execution_logger.log_llm_interaction(
                agent_name=agent_name,
                interaction_type="core_react_agent",
                input_messages=[
                    {"role": "system", "content": system_prompt[:300] + "..."},
                    {"role": "user", "content": f"[{len(input_data)} chars]"},
                ],
                output_content=output,
                model_config={"temperature": self.profile.llm_temperature},
                execution_time=elapsed,
            )

            # 8. Run output handler
            if self.profile.output_handler:
                try:
                    await self.profile.output_handler(output, context, self.kb)
                except Exception as e:
                    logger.warning(
                        "%s: output handler error: %s", agent_name, e
                    )

            execution_logger.log_agent_complete(
                agent_name,
                {"output_length": len(output)},
                elapsed,
                True,
            )

            return output

        except asyncio.TimeoutError:
            elapsed = time.time() - t0
            msg = f"Core agent timed out after {AGENT_TIMEOUT}s"
            logger.error("%s: %s", agent_name, msg)
            execution_logger.log_agent_complete(
                agent_name, {"error": msg}, elapsed, False, msg
            )
            return f"# Analysis Error\n\n**Error**: {msg}"

        except Exception as e:
            elapsed = time.time() - t0
            logger.exception("%s: error during execution", agent_name)
            execution_logger.log_agent_complete(
                agent_name, {"error": str(e)}, elapsed, False, str(e)
            )
            return f"# Analysis Error\n\n**Error**: {e}"

    def _build_system_prompt(self, context: dict[str, Any]) -> str:
        """Fill profile's prompt template with live KB data + context."""
        # Read from KB directly (lazy-load -- replaces context_injection.py)
        try:
            principles = self.kb.read_principles()
        except FileNotFoundError:
            principles = "(principles file not found)"

        core_mind = self.kb.read_core_mind() or "(not initialized)"
        user_views = self.kb.read_user_views() or ""
        divergences = self.kb.read_divergences() or ""
        data_sources = self.kb.build_source_descriptions()

        return self.profile.system_prompt_template.format(
            agent_principles=principles,
            core_mind_content=core_mind,
            user_views_content=user_views,
            divergences_content=divergences,
            data_sources=data_sources,
            **context,
        )

    @staticmethod
    def _extract_output(result: dict) -> str:
        """Extract the last AIMessage content from ReAct agent result."""
        if "messages" not in result:
            return "No output generated."
        ai_msgs = [m for m in result["messages"] if isinstance(m, AIMessage)]
        if not ai_msgs:
            return "No output generated."
        return normalize_content(ai_msgs[-1].content)

    @staticmethod
    def _get_web_tools(tool_names: list[str]) -> list:
        """Load web search tools if requested by profile."""
        web_names = {"web_search", "fetch_url"}
        requested = web_names & set(tool_names)
        if not requested:
            return []
        try:
            from src.tools.web_search import WEB_TOOLS
            return [t for t in WEB_TOOLS if t.name in requested]
        except ImportError:
            logger.warning("Web search tools requested but package not installed")
            return []
