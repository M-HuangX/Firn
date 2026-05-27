"""Context management hooks for LangGraph ReAct agent loops.

Provides ``create_context_hooks()`` which returns a ``(pre_model_hook,
post_model_hook)`` pair that can be passed directly to
``langgraph.prebuilt.create_react_agent``.

The **pre_model_hook** compresses messages before they reach the LLM so the
context window stays within budget.  It never mutates ``state["messages"]`` —
it returns a *view* via ``{"llm_input_messages": ...}``.

The **post_model_hook** implements a LoopGuard that detects degenerate loops
(repeated no-tool responses or identical consecutive tool calls) and injects
a warning ``SystemMessage`` to break the cycle.

Pipeline (pre_model_hook)::

    messages
       │
       ▼
    ① sanitize_orphan_pairs
    ② snip_old_tool_results
    ③ sanitize_pairs_post_snip  (safety net)
    ④ trim_to_budget
    ⑤ append_reminder  (optional)
       │
       ▼
    {"llm_input_messages": compressed}
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Callable

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def _estimate_tokens(text: str) -> int:
    """Estimate token count.  Uses UTF-8 byte length / 4 for CJK support."""
    if not text:
        return 0
    return max(1, len(text.encode("utf-8")) // 4)


def _estimate_message_tokens(msg: Any) -> int:
    """Estimate tokens for a single message (content + tool_calls)."""
    total = 0
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        total += _estimate_tokens(content)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                total += _estimate_tokens(item.get("text", ""))
            elif isinstance(item, str):
                total += _estimate_tokens(item)
    # Count tool-call arguments
    for tc in getattr(msg, "tool_calls", []):
        total += _estimate_tokens(str(tc.get("args", {})))
    return total + 4  # per-message overhead


# ---------------------------------------------------------------------------
# Helper: tool-call / tool-result bookkeeping
# ---------------------------------------------------------------------------


def _tool_call_ids(msg: Any) -> set[str]:
    """Return the set of tool_call ids carried by an AIMessage."""
    return {
        tc["id"]
        for tc in getattr(msg, "tool_calls", [])
        if isinstance(tc, dict) and "id" in tc
    }


def _find_tool_result_indices(
    messages: list[Any], ai_msg_index: int
) -> list[int]:
    """Find indices of ToolMessages that respond to the AIMessage at *ai_msg_index*."""
    tc_ids = _tool_call_ids(messages[ai_msg_index])
    if not tc_ids:
        return []
    indices: list[int] = []
    for i in range(ai_msg_index + 1, len(messages)):
        msg = messages[i]
        if hasattr(msg, "tool_call_id") and msg.tool_call_id in tc_ids:
            indices.append(i)
        elif not hasattr(msg, "tool_call_id"):
            break  # past the tool results
    return indices


def _tool_call_signature(tool_calls: list[dict[str, Any]]) -> str:
    """Create a hashable signature for a list of tool calls."""
    parts: list[str] = []
    for tc in tool_calls:
        name = tc.get("name", "")
        args = str(tc.get("args", {}))
        parts.append(f"{name}({args})")
    return "|".join(sorted(parts))


# ---------------------------------------------------------------------------
# ① Sanitize orphan pairs
# ---------------------------------------------------------------------------


def _sanitize_orphan_pairs(messages: list[Any]) -> list[Any]:
    """Remove orphaned tool results and clear orphaned tool_calls.

    - A ``ToolMessage`` is orphaned if no preceding ``AIMessage`` has a
      ``tool_call`` with the matching ``id``.
    - An ``AIMessage`` has orphaned ``tool_calls`` if any of its tool_call
      ids has no corresponding ``ToolMessage`` response.
    """
    # Collect all tool_call ids from AIMessages and all tool_call_ids from
    # ToolMessages for cross-referencing.
    ai_tc_ids: set[str] = set()
    for msg in messages:
        ai_tc_ids.update(_tool_call_ids(msg))

    tm_tc_ids: set[str] = set()
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tm_tc_ids.add(msg.tool_call_id)

    result: list[Any] = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            if msg.tool_call_id not in ai_tc_ids:
                # Orphaned tool result — drop it
                logger.debug(
                    "Dropping orphaned ToolMessage (tool_call_id=%s)",
                    msg.tool_call_id,
                )
                continue
            result.append(msg)
        elif isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            # Check if any tool_call has no matching response
            valid_tcs = [
                tc
                for tc in msg.tool_calls
                if tc.get("id") in tm_tc_ids
            ]
            if len(valid_tcs) != len(msg.tool_calls):
                # Some tool_calls are orphaned — rebuild AIMessage without them
                new_msg = AIMessage(
                    content=msg.content,
                    tool_calls=valid_tcs if valid_tcs else [],
                    id=getattr(msg, "id", None),
                    additional_kwargs=getattr(msg, "additional_kwargs", {}),
                )
                result.append(new_msg)
                logger.debug(
                    "Cleared %d orphaned tool_calls from AIMessage",
                    len(msg.tool_calls) - len(valid_tcs),
                )
            else:
                result.append(msg)
        else:
            result.append(msg)
    return result


# ---------------------------------------------------------------------------
# ② Snip old tool results
# ---------------------------------------------------------------------------

# Arguments whose values should be snipped when they appear in tool_calls
# (e.g. the ``content`` arg of ``kb_write`` / ``kb_edit``).
_SNIP_ARG_NAMES = frozenset({"content", "new_content", "body", "old_text", "new_text"})


def _make_snip_summary(msg: ToolMessage) -> str:
    """Create an informative 1-line summary for a snipped ToolMessage."""
    content = getattr(msg, "content", "")
    char_count = len(content) if isinstance(content, str) else 0
    name = getattr(msg, "name", "tool")
    return f"[Snipped] {name} result ({char_count:,} chars)"


def _snip_old_tool_results(
    messages: list[Any],
    *,
    snip_threshold: int,
    protect_last_n: int,
) -> list[Any]:
    """Replace oversized ToolMessage content with a compact summary.

    Messages within the last *protect_last_n* messages are never touched.
    ``SystemMessage`` and ``HumanMessage`` are never touched.

    For ``AIMessage`` tool_calls, large argument values (``content``,
    ``new_content``, ``body``) are also snipped.
    """
    total = len(messages)
    # Ensure at least 5 messages are eligible for snipping, even when
    # total ≤ protect_last_n (prevents protect_last_n from shielding everything).
    effective_protect = min(protect_last_n, max(0, total - 5))
    cutoff = max(0, total - effective_protect)

    result: list[Any] = []
    for i, msg in enumerate(messages):
        protected = i >= cutoff

        # --- ToolMessage snipping ---
        if isinstance(msg, ToolMessage) and not protected:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if len(content) > snip_threshold:
                summary = _make_snip_summary(msg)
                new_msg = ToolMessage(
                    content=summary,
                    tool_call_id=msg.tool_call_id,
                    name=getattr(msg, "name", "tool"),
                )
                result.append(new_msg)
                continue

        # --- AIMessage tool_call arg snipping ---
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None) and not protected:
            needs_snip = False
            for tc in msg.tool_calls:
                args = tc.get("args", {})
                for arg_name in _SNIP_ARG_NAMES:
                    val = args.get(arg_name, "")
                    if isinstance(val, str) and len(val) > snip_threshold:
                        needs_snip = True
                        break
                if needs_snip:
                    break

            if needs_snip:
                new_tcs: list[dict[str, Any]] = []
                for tc in msg.tool_calls:
                    new_args = dict(tc.get("args", {}))
                    for arg_name in _SNIP_ARG_NAMES:
                        val = new_args.get(arg_name, "")
                        if isinstance(val, str) and len(val) > snip_threshold:
                            new_args[arg_name] = (
                                f"[Snipped] ({len(val):,} chars)"
                            )
                    new_tc = {**tc, "args": new_args}
                    new_tcs.append(new_tc)
                new_msg = AIMessage(
                    content=msg.content,
                    tool_calls=new_tcs,
                    id=getattr(msg, "id", None),
                    additional_kwargs=getattr(msg, "additional_kwargs", {}),
                )
                result.append(new_msg)
                continue

        result.append(msg)
    return result


# ---------------------------------------------------------------------------
# ④ Trim to budget
# ---------------------------------------------------------------------------


def _trim_to_budget(messages: list[Any], *, max_tokens: int) -> list[Any]:
    """Drop oldest messages (after SystemMessage) until under token budget.

    Rules:
    - SystemMessage at index 0 is never removed.
    - The first HumanMessage is never removed.
    - Tool-call / tool-result pairs are removed atomically.
    """
    total_tokens = sum(_estimate_message_tokens(m) for m in messages)
    if total_tokens <= max_tokens:
        return messages

    # Build removal-candidate indices (skip index 0 if SystemMessage,
    # skip first HumanMessage).
    first_human_idx: int | None = None
    for idx, msg in enumerate(messages):
        if isinstance(msg, HumanMessage):
            first_human_idx = idx
            break

    protected: set[int] = set()
    if messages and isinstance(messages[0], SystemMessage):
        protected.add(0)
    if first_human_idx is not None:
        protected.add(first_human_idx)

    # Work on a mutable copy of indices
    remaining = list(range(len(messages)))
    result_indices = set(remaining)

    # Build a mapping from tool_call_id → AIMessage index for pair removal
    ai_tc_map: dict[str, int] = {}
    for idx in remaining:
        msg = messages[idx]
        if isinstance(msg, AIMessage):
            for tc in getattr(msg, "tool_calls", []):
                tc_id = tc.get("id")
                if tc_id:
                    ai_tc_map[tc_id] = idx

    # Iterate oldest-first (after protected) and remove until under budget
    for idx in remaining:
        if total_tokens <= max_tokens:
            break
        if idx in protected or idx not in result_indices:
            continue

        msg = messages[idx]

        # If it's an AIMessage with tool_calls, also remove its ToolMessage responses
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            group = {idx}
            result_indices_list = sorted(result_indices)
            group.update(_find_tool_result_indices_from_set(
                messages, idx, result_indices_list
            ))
            for gi in group:
                if gi in result_indices and gi not in protected:
                    result_indices.discard(gi)
                    total_tokens -= _estimate_message_tokens(messages[gi])

        # If it's a ToolMessage, also remove the AIMessage that called it
        elif isinstance(msg, ToolMessage):
            tc_id = getattr(msg, "tool_call_id", None)
            ai_idx = ai_tc_map.get(tc_id) if tc_id else None
            group = {idx}
            if ai_idx is not None and ai_idx not in protected:
                group.add(ai_idx)
                # Also remove other ToolMessages for that AIMessage
                result_indices_list = sorted(result_indices)
                group.update(_find_tool_result_indices_from_set(
                    messages, ai_idx, result_indices_list
                ))
            for gi in group:
                if gi in result_indices and gi not in protected:
                    result_indices.discard(gi)
                    total_tokens -= _estimate_message_tokens(messages[gi])

        else:
            # Plain AIMessage (no tool_calls) or other
            if idx not in protected:
                result_indices.discard(idx)
                total_tokens -= _estimate_message_tokens(messages[idx])

    return [messages[i] for i in sorted(result_indices)]


def _find_tool_result_indices_from_set(
    messages: list[Any], ai_msg_index: int, valid_indices: list[int]
) -> list[int]:
    """Like ``_find_tool_result_indices`` but only considers *valid_indices*."""
    tc_ids = _tool_call_ids(messages[ai_msg_index])
    if not tc_ids:
        return []
    indices: list[int] = []
    for i in valid_indices:
        if i <= ai_msg_index:
            continue
        msg = messages[i]
        if isinstance(msg, ToolMessage) and msg.tool_call_id in tc_ids:
            indices.append(i)
    return indices


# ---------------------------------------------------------------------------
# ⑤ Append reminder
# ---------------------------------------------------------------------------

_REMINDER_TEXT = (
    "Reminder: You are the Core Agent. Stay focused on the current task. "
    "Use KB tools to read/write knowledge. Produce structured output when done."
)


def _append_reminder(messages: list[Any]) -> list[Any]:
    """Append a brief role-reminder SystemMessage at the end."""
    return [*messages, SystemMessage(content=_REMINDER_TEXT)]


# ---------------------------------------------------------------------------
# Public API: create_context_hooks
# ---------------------------------------------------------------------------


def create_context_hooks(
    *,
    max_tokens: int = 40_000,
    snip_threshold: int = 3_000,
    protect_last_n: int = 3,
    snip_trigger_ratio: float = 0.85,
    enable_reminder: bool = False,
    loop_guard_limit: int = 3,
) -> tuple[Callable, Callable]:
    """Create ``pre_model_hook`` and ``post_model_hook`` for a LangGraph ReAct agent.

    KV-cache-aware strategy (optimized for DeepSeek prefix caching):

    * **Don't snip until necessary** — trigger late (default 85% of budget)
      so the message prefix stays identical across rounds → KV cache hits.
    * **When triggered, snip aggressively** — use a low threshold so one
      cleanup pass removes the bulk of old tool content in a single shot.
      This creates a large headroom gap before the next trigger, keeping
      the prefix stable for many subsequent rounds.
    * **Trim is last resort** — reasoning content (``additional_kwargs``)
      contains the agent's synthesis of articles it read; trimming deletes
      entire messages including reasoning.  Snipping only replaces raw
      ToolMessage payloads while the agent's thinking is preserved.

    Args:
        max_tokens: Hard token budget.  ``trim_to_budget`` drops oldest
            messages when total exceeds this.
        snip_threshold: Character length above which old ToolMessage content
            and AI tool_call arguments are replaced with a 1-line summary.
            Set low (e.g. 2000) for aggressive single-pass cleanup.
        protect_last_n: Number of most-recent messages exempt from snipping.
        snip_trigger_ratio: Fraction of *max_tokens* at which snipping
            activates (default 0.85).  Below this, messages are untouched.
        enable_reminder: Whether to append a role-reminder SystemMessage.
        loop_guard_limit: Consecutive identical responses before LoopGuard
            injects a warning.

    Returns:
        ``(pre_model_hook, post_model_hook)`` — pass to
        ``create_react_agent()``.
    """
    snip_trigger_tokens = int(max_tokens * snip_trigger_ratio)

    def pre_model_hook(state: dict[str, Any]) -> dict[str, Any]:
        messages = list(state.get("messages", []))
        if not messages:
            return {"llm_input_messages": messages}

        # ① Sanitize orphan pairs
        messages = _sanitize_orphan_pairs(messages)

        # ② Snip old tool results — only when approaching token budget.
        #    Trigger late + snip aggressively = one big cleanup, then stable
        #    prefix for many rounds → maximizes DeepSeek KV-cache savings.
        total_tokens = sum(_estimate_message_tokens(m) for m in messages)
        if total_tokens > snip_trigger_tokens:
            logger.info(
                "Context snip triggered: %d tokens > %d threshold (%.0f%% of %d budget)",
                total_tokens, snip_trigger_tokens,
                100 * total_tokens / max_tokens, max_tokens,
            )
            messages = _snip_old_tool_results(
                messages,
                snip_threshold=snip_threshold,
                protect_last_n=protect_last_n,
            )
            # ③ Safety-net: re-sanitize after snipping
            messages = _sanitize_orphan_pairs(messages)
            post_snip_tokens = sum(_estimate_message_tokens(m) for m in messages)
            logger.info(
                "Context snip complete: %d → %d tokens (freed %d, now %.0f%% of budget)",
                total_tokens, post_snip_tokens,
                total_tokens - post_snip_tokens,
                100 * post_snip_tokens / max_tokens,
            )

        # ④ Trim to token budget (last resort — drops entire messages
        #    including reasoning content; should rarely trigger after
        #    aggressive snipping)
        messages = _trim_to_budget(messages, max_tokens=max_tokens)

        # ⑤ Optional reminder
        if enable_reminder:
            messages = _append_reminder(messages)

        return {"llm_input_messages": messages}

    post_model_hook = _make_post_hook(loop_guard_limit)

    return pre_model_hook, post_model_hook


# ---------------------------------------------------------------------------
# post_model_hook: LoopGuard
# ---------------------------------------------------------------------------


def _make_post_hook(loop_guard_limit: int) -> Callable:
    """Create a ``post_model_hook`` that detects degenerate loops."""

    no_tool_count = 0
    last_content_hash: int | None = None
    recent_tool_calls: list[str] = []

    def post_model_hook(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal no_tool_count, last_content_hash, recent_tool_calls

        messages = state.get("messages", [])
        if not messages:
            return state

        last_msg = messages[-1]

        # --- Check 1: No tool calls + repeated content ---
        if not getattr(last_msg, "tool_calls", None):
            content_hash = hash(str(getattr(last_msg, "content", "")))
            if content_hash == last_content_hash:
                no_tool_count += 1
            else:
                no_tool_count = 1
                last_content_hash = content_hash

            if no_tool_count >= loop_guard_limit:
                return {
                    "messages": messages
                    + [
                        SystemMessage(
                            content=(
                                "LOOP DETECTED: You have produced similar "
                                "responses without tool calls. Either use a "
                                "tool to make progress or produce your final "
                                "output."
                            )
                        )
                    ]
                }
        else:
            no_tool_count = 0
            last_content_hash = None

            # --- Check 2: Repeated identical tool calls ---
            sig = _tool_call_signature(last_msg.tool_calls)
            recent_tool_calls.append(sig)
            if len(recent_tool_calls) > loop_guard_limit:
                recent_tool_calls = recent_tool_calls[-loop_guard_limit:]

            if (
                len(recent_tool_calls) >= loop_guard_limit
                and len(set(recent_tool_calls)) == 1
            ):
                return {
                    "messages": messages
                    + [
                        SystemMessage(
                            content=(
                                f"LOOP DETECTED: You have made "
                                f"{loop_guard_limit} identical tool calls "
                                f"({recent_tool_calls[0]}). Break the loop "
                                "— try a different approach or produce your "
                                "final output."
                            )
                        )
                    ]
                }

        return state

    return post_model_hook
