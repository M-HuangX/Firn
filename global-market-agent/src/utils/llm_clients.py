"""LLM client factory — returns a LangChain ``BaseChatModel`` for any supported provider.

Switch providers by setting ``LLM_PROVIDER`` in ``.env``.  Each provider reads
its own ``<PROVIDER>_API_KEY`` and ``<PROVIDER>_MODEL`` env vars, so all keys
can coexist in a single ``.env`` file.

Supported providers:

* ``deepseek``  — DeepSeek API (with thinking mode patch)
* ``openai``    — OpenAI API
* ``gemini``    — Google Gemini API
* ``local``     — Local vLLM / Ollama (requires ``LLM_BASE_URL``)

Usage::

    from src.utils.llm_clients import create_llm
    llm = create_llm()                                   # reads .env
    llm = create_llm(temperature=0.5, max_tokens=8192)   # override defaults
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import openai
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

# Default base URLs for known OpenAI-compatible providers.
_OPENAI_COMPAT_DEFAULTS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "openai": "https://api.openai.com/v1",
}

# Per-provider env var prefixes for API key and model.
# Lookup order: provider-specific → generic LLM_API_KEY / LLM_MODEL fallback.
_PROVIDER_ENV: dict[str, dict[str, str]] = {
    "deepseek": {"key": "DEEPSEEK_API_KEY", "model": "DEEPSEEK_MODEL"},
    "openai":   {"key": "OPENAI_API_KEY",   "model": "OPENAI_MODEL"},
    "gemini":   {"key": "GEMINI_API_KEY",    "model": "GEMINI_MODEL"},
}


# ---------------------------------------------------------------------------
# DeepSeek thinking-mode patch (workaround for langchain-ai/langchain#34166)
#
# ChatOpenAI does not preserve DeepSeek's ``reasoning_content`` field across
# multi-turn tool-calling conversations.  This subclass adds three overrides:
#   1. _create_chat_result      — read reasoning_content from API response
#   2. _get_request_payload     — inject it back into outgoing requests
#   3. _convert_chunk_to_generation_chunk — handle streaming reasoning
#
# When LangChain merges a fix upstream, delete this class and use ChatOpenAI.
# ---------------------------------------------------------------------------


class ChatOpenAIDeepSeek(ChatOpenAI):
    """ChatOpenAI with DeepSeek reasoning_content round-trip support.

    Also intercepts 400 errors related to tool_call message ordering
    and dumps the full serialized payload for debugging.
    """

    _last_payload: dict | None = None

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        try:
            return super()._generate(
                messages, stop=stop, run_manager=run_manager, **kwargs
            )
        except openai.BadRequestError as e:
            if "tool_call" in str(e):
                self._dump_debug_payload(e)
            raise

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        try:
            return await super()._agenerate(
                messages, stop=stop, run_manager=run_manager, **kwargs
            )
        except openai.BadRequestError as e:
            if "tool_call" in str(e):
                self._dump_debug_payload(e)
            raise

    def _dump_debug_payload(self, error: Exception) -> None:
        """Dump the serialized API payload when a tool_call 400 error occurs."""
        dump_dir = Path("logs/debug_payloads")
        dump_dir.mkdir(parents=True, exist_ok=True)
        dump_path = dump_dir / f"tool_calls_400_{int(time.time())}.json"
        try:
            payload = self._last_payload or {}
            msgs = payload.get("messages", [])

            # Build a diagnostic summary
            ai_with_tc = []
            tool_msgs = []
            for i, m in enumerate(msgs):
                if m.get("tool_calls"):
                    ai_with_tc.append({
                        "index": i,
                        "role": m.get("role"),
                        "tool_call_ids": [
                            tc.get("id") for tc in m["tool_calls"]
                        ],
                    })
                if m.get("role") == "tool":
                    tool_msgs.append({
                        "index": i,
                        "tool_call_id": m.get("tool_call_id"),
                    })

            # Find unmatched tool_call_ids
            all_tc_ids = {
                tc_id
                for entry in ai_with_tc
                for tc_id in entry["tool_call_ids"]
            }
            responded_ids = {tm["tool_call_id"] for tm in tool_msgs}
            unmatched = all_tc_ids - responded_ids

            report = {
                "error": str(error),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "total_messages": len(msgs),
                "ai_messages_with_tool_calls": ai_with_tc,
                "tool_messages_count": len(tool_msgs),
                "unmatched_tool_call_ids": sorted(unmatched),
                "message_roles_sequence": [
                    m.get("role", "?") for m in msgs
                ],
                "full_messages": msgs,
            }
            dump_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            logger.error(
                "Tool-call 400 error — debug payload saved to %s "
                "(%d messages, %d unmatched tool_call_ids)",
                dump_path, len(msgs), len(unmatched),
            )
        except Exception as dump_err:
            logger.error("Failed to dump debug payload: %s", dump_err)

    def _create_chat_result(
        self,
        response: dict | openai.BaseModel,
        generation_info: dict | None = None,
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)

        # Extract reasoning_content from the typed response object
        if isinstance(response, openai.BaseModel):
            choices = getattr(response, "choices", None)
            if choices and hasattr(choices[0].message, "reasoning_content"):
                rc = choices[0].message.reasoning_content
                if rc is not None:
                    result.generations[0].message.additional_kwargs[
                        "reasoning_content"
                    ] = rc

        return result

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        # Capture reasoning_content from original messages before serialization
        messages = self._convert_input(input_).to_messages()
        reasoning_map: dict[int, str] = {}
        for i, msg in enumerate(messages):
            if isinstance(msg, AIMessage):
                rc = msg.additional_kwargs.get("reasoning_content")
                if rc is not None:
                    reasoning_map[i] = rc

        # Parent serializes messages (drops reasoning_content)
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        for i, message in enumerate(payload.get("messages", [])):
            if message.get("role") == "assistant":
                # Re-inject reasoning_content
                if i in reasoning_map:
                    message["reasoning_content"] = reasoning_map[i]
                # DeepSeek requires content as string, not list
                if isinstance(message.get("content"), list):
                    text_parts = [
                        b.get("text", "")
                        for b in message["content"]
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    message["content"] = "".join(text_parts) if text_parts else ""

            # DeepSeek requires tool message content as string
            elif message.get("role") == "tool" and isinstance(
                message.get("content"), list
            ):
                message["content"] = json.dumps(message["content"])

        # Fix unmatched tool_call_ids: DeepSeek sometimes generates invalid JSON
        # in tool call arguments. LangChain puts these in invalid_tool_calls but
        # still serializes them as regular tool_calls. LangGraph skips executing
        # them, so no ToolMessage exists → DeepSeek returns 400.
        payload["messages"] = self._patch_unmatched_tool_calls(
            payload.get("messages", []))

        self._last_payload = payload
        return payload

    @staticmethod
    def _patch_unmatched_tool_calls(messages: list[dict]) -> list[dict]:
        """Inject synthetic error responses for tool_calls missing responses."""
        result: list[dict] = []
        expected_ids: set[str] = set()

        for msg in messages:
            # Before a new assistant message, flush any unmatched tool responses
            if msg.get("role") == "assistant" and expected_ids:
                for tc_id in sorted(expected_ids):
                    result.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": "Error: tool call had invalid arguments and was not executed.",
                    })
                expected_ids.clear()

            result.append(msg)

            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    expected_ids.add(tc["id"])
            elif msg.get("role") == "tool":
                expected_ids.discard(msg.get("tool_call_id", ""))

        # Flush remaining at end of message list
        for tc_id in sorted(expected_ids):
            result.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": "Error: tool call had invalid arguments and was not executed.",
            })

        return result

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if generation_chunk and (choices := chunk.get("choices")):
            delta = choices[0].get("delta", {})
            rc = delta.get("reasoning_content")
            if rc is not None and isinstance(
                generation_chunk.message, AIMessageChunk
            ):
                generation_chunk.message.additional_kwargs["reasoning_content"] = rc
        return generation_chunk


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def create_llm(
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    max_retries: int | None = None,
    request_timeout: float | None = None,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> BaseChatModel:
    """Create an LLM client based on provider configuration.

    Resolution order for api_key and model:
        1. Explicit keyword argument
        2. Provider-specific env var (e.g. ``DEEPSEEK_API_KEY``, ``DEEPSEEK_MODEL``)
        3. Generic fallback (``LLM_API_KEY``, ``LLM_MODEL``)

    Returns:
        A LangChain chat model ready for ``ainvoke`` / ``create_react_agent``.

    Raises:
        ValueError: If required configuration is missing.
    """
    provider = (provider or os.getenv("LLM_PROVIDER", "deepseek")).lower().strip()

    # Resolve api_key and model with provider-specific → generic fallback
    penv = _PROVIDER_ENV.get(provider, {})
    model = model or os.getenv(penv.get("model", ""), "") or os.getenv("LLM_MODEL")
    api_key = api_key or os.getenv(penv.get("key", ""), "") or os.getenv("LLM_API_KEY")
    base_url = base_url or os.getenv("LLM_BASE_URL")

    temperature = (
        temperature
        if temperature is not None
        else float(os.getenv("LLM_TEMPERATURE", "0.3"))
    )
    max_tokens = (
        max_tokens
        if max_tokens is not None
        else int(os.getenv("LLM_MAX_TOKENS", "4096"))
    )
    max_retries = (
        max_retries
        if max_retries is not None
        else int(os.getenv("LLM_MAX_RETRIES", "3"))
    )
    request_timeout = (
        request_timeout
        if request_timeout is not None
        else float(os.getenv("LLM_REQUEST_TIMEOUT", "120"))
    )

    if not model:
        raise ValueError(
            f"Model not set for provider '{provider}'. "
            f"Set {penv.get('model', 'LLM_MODEL')} or LLM_MODEL in .env."
        )
    if not api_key:
        raise ValueError(
            f"API key not set for provider '{provider}'. "
            f"Set {penv.get('key', 'LLM_API_KEY')} or LLM_API_KEY in .env."
        )

    # --- Gemini (native Google SDK) -------------------------------------------
    if provider == "gemini":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as e:
            raise ImportError(
                "Install langchain-google-genai to use Gemini: "
                "uv add langchain-google-genai"
            ) from e

        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=temperature,
            max_output_tokens=max_tokens,
            max_retries=max_retries,
            timeout=request_timeout,
        )

    # --- DeepSeek (thinking mode enabled, with round-trip patch) ---------------
    if provider == "deepseek":
        if not base_url:
            base_url = _OPENAI_COMPAT_DEFAULTS["deepseek"]

        return ChatOpenAIDeepSeek(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            timeout=request_timeout,
            extra_body={"thinking": {"type": "enabled"}},
        )

    # --- OpenAI-compatible (openai, local, ...) --------------------------------
    if not base_url:
        base_url = _OPENAI_COMPAT_DEFAULTS.get(provider)
    if not base_url:
        raise ValueError(
            f"LLM_BASE_URL is required for provider '{provider}'. "
            "Set it in .env or pass base_url= to create_llm()."
        )

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=max_retries,
        timeout=request_timeout,
    )
