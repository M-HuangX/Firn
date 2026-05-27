"""Tests for the context management hooks (pre_model_hook / post_model_hook)."""

from __future__ import annotations

import pytest

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from src.utils.context_manager import (
    _estimate_tokens,
    _estimate_message_tokens,
    _make_snip_summary,
    _sanitize_orphan_pairs,
    _snip_old_tool_results,
    _trim_to_budget,
    _tool_call_signature,
    create_context_hooks,
)


# ---------------------------------------------------------------------------
# Fixtures — reusable message sequences
# ---------------------------------------------------------------------------


def _make_long_content(length: int = 5000) -> str:
    """Return a string of *length* ASCII characters."""
    return "x" * length


def _basic_conversation() -> list:
    """Return a 7-message conversation with one long tool result."""
    return [
        SystemMessage(content="You are an analyst."),
        HumanMessage(content="Analyze copper"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "kb_read",
                    "args": {"section": "themes", "slug": "copper"},
                    "id": "tc1",
                }
            ],
        ),
        ToolMessage(
            content=_make_long_content(5000),
            tool_call_id="tc1",
            name="kb_read",
        ),
        AIMessage(
            content="Let me check another file.",
            tool_calls=[
                {
                    "name": "kb_read",
                    "args": {"section": "events", "slug": "fed"},
                    "id": "tc2",
                }
            ],
        ),
        ToolMessage(
            content="# Fed Rate Decision\nShort content.",
            tool_call_id="tc2",
            name="kb_read",
        ),
        AIMessage(content="Based on my analysis..."),
    ]


# ---------------------------------------------------------------------------
# snip_old_tool_results
# ---------------------------------------------------------------------------


class TestSnipOldToolResults:
    def test_long_tool_message_gets_snipped(self):
        """A ToolMessage with content > snip_threshold is replaced with a summary."""
        messages = _basic_conversation()
        result = _snip_old_tool_results(
            messages, snip_threshold=3000, protect_last_n=2
        )
        # tc1 result (5000 chars, index 3) is old and long → snipped
        snipped = result[3]
        assert isinstance(snipped, ToolMessage)
        assert "[Snipped]" in snipped.content
        assert "kb_read" in snipped.content
        assert "5,000" in snipped.content
        assert snipped.tool_call_id == "tc1"

    def test_recent_tool_messages_not_snipped(self):
        """ToolMessages within protect_last_n are never snipped."""
        messages = _basic_conversation()
        result = _snip_old_tool_results(
            messages, snip_threshold=3000, protect_last_n=3
        )
        # tc2 result (index 5) is within protect_last_n=3 (indices 4,5,6) → untouched
        assert result[5].content == "# Fed Rate Decision\nShort content."
        # tc1 result (index 3) is outside protection and long → snipped
        assert "[Snipped]" in result[3].content

    def test_short_tool_message_not_snipped(self):
        """Short ToolMessages are not snipped even if old."""
        messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Question"),
            AIMessage(
                content="",
                tool_calls=[{"name": "kb_read", "args": {}, "id": "tc1"}],
            ),
            ToolMessage(content="Short result", tool_call_id="tc1", name="kb_read"),
            AIMessage(content="Done."),
        ]
        result = _snip_old_tool_results(
            messages, snip_threshold=3000, protect_last_n=1
        )
        # 12-char content is well under 3000 → not snipped
        assert result[3].content == "Short result"

    def test_tool_call_args_snipped_in_ai_message(self):
        """Large 'content' arg in AIMessage tool_calls gets snipped."""
        long_body = _make_long_content(4000)
        messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Write this"),
            AIMessage(
                content="Writing to KB.",
                tool_calls=[
                    {
                        "name": "kb_write",
                        "args": {"section": "themes", "slug": "test", "content": long_body},
                        "id": "tc1",
                    }
                ],
            ),
            ToolMessage(content="OK", tool_call_id="tc1", name="kb_write"),
            AIMessage(content="Done."),
        ]
        result = _snip_old_tool_results(
            messages, snip_threshold=3000, protect_last_n=1
        )
        ai_msg = result[2]
        assert isinstance(ai_msg, AIMessage)
        arg_content = ai_msg.tool_calls[0]["args"]["content"]
        assert "[Snipped]" in arg_content
        assert "4,000" in arg_content


# ---------------------------------------------------------------------------
# sanitize_orphan_pairs
# ---------------------------------------------------------------------------


class TestSanitizeOrphanPairs:
    def test_orphaned_tool_message_removed(self):
        """A ToolMessage with no matching AIMessage tool_call is removed."""
        messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Hello"),
            # No AIMessage with tool_call id="ghost"
            ToolMessage(content="result", tool_call_id="ghost", name="kb_read"),
            AIMessage(content="Answer"),
        ]
        result = _sanitize_orphan_pairs(messages)
        assert len(result) == 3  # ToolMessage removed
        assert all(not isinstance(m, ToolMessage) for m in result)

    def test_orphaned_tool_calls_cleared(self):
        """AIMessage tool_calls with no matching ToolMessage responses are cleared."""
        messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Hello"),
            AIMessage(
                content="Calling tool",
                tool_calls=[
                    {"name": "kb_read", "args": {}, "id": "tc_orphan"},
                ],
            ),
            # No ToolMessage with tool_call_id="tc_orphan"
            AIMessage(content="Moving on."),
        ]
        result = _sanitize_orphan_pairs(messages)
        ai_with_calls = result[2]
        assert isinstance(ai_with_calls, AIMessage)
        # tool_calls should be empty (cleared)
        assert len(ai_with_calls.tool_calls) == 0


# ---------------------------------------------------------------------------
# trim_to_budget
# ---------------------------------------------------------------------------


class TestTrimToBudget:
    def test_messages_trimmed_when_over_budget(self):
        """Oldest non-protected messages are removed to fit token budget."""
        messages = [
            SystemMessage(content="System prompt."),
            HumanMessage(content="Analyze AAPL"),
            AIMessage(content="A" * 400),   # ~100 tokens
            AIMessage(content="B" * 400),   # ~100 tokens
            AIMessage(content="C" * 400),   # ~100 tokens
        ]
        # Tiny budget forces trimming
        result = _trim_to_budget(messages, max_tokens=100)
        # SystemMessage and first HumanMessage must survive
        assert isinstance(result[0], SystemMessage)
        assert isinstance(result[1], HumanMessage)
        # At least some AIMessages should be removed
        assert len(result) < len(messages)

    def test_system_and_first_human_never_removed(self):
        """SystemMessage (idx 0) and first HumanMessage survive any trim."""
        messages = [
            SystemMessage(content="S" * 200),
            HumanMessage(content="H" * 200),
            AIMessage(content="A" * 2000),
        ]
        result = _trim_to_budget(messages, max_tokens=50)
        types = [type(m) for m in result]
        assert SystemMessage in types
        assert HumanMessage in types

    def test_tool_pairs_removed_together(self):
        """When trimming, an AIMessage with tool_calls and its ToolMessages
        are removed as a unit — no orphans left."""
        messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Go"),
            AIMessage(
                content="",
                tool_calls=[{"name": "kb_read", "args": {}, "id": "tc1"}],
            ),
            ToolMessage(content="R" * 2000, tool_call_id="tc1", name="kb_read"),
            AIMessage(content="Final answer."),
        ]
        # Budget only enough for system + human + final AIMessage
        result = _trim_to_budget(messages, max_tokens=80)
        # Verify no orphaned ToolMessages remain
        for msg in result:
            if isinstance(msg, ToolMessage):
                # If a ToolMessage survived, its AIMessage must also survive
                tc_id = msg.tool_call_id
                has_ai = any(
                    isinstance(m, AIMessage)
                    and any(tc.get("id") == tc_id for tc in getattr(m, "tool_calls", []))
                    for m in result
                )
                assert has_ai, f"Orphaned ToolMessage (tc_id={tc_id}) in result"

        # And verify no AIMessages with tool_calls lost their responses
        for msg in result:
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    tc_id = tc.get("id")
                    has_tm = any(
                        isinstance(m, ToolMessage) and m.tool_call_id == tc_id
                        for m in result
                    )
                    assert has_tm, f"Orphaned AIMessage tool_call (id={tc_id}) in result"


# ---------------------------------------------------------------------------
# LoopGuard (post_model_hook)
# ---------------------------------------------------------------------------


class TestLoopGuard:
    def test_repeated_no_tool_responses_trigger_warning(self):
        """LoopGuard injects SystemMessage after repeated content without tool calls."""
        _, post_hook = create_context_hooks(loop_guard_limit=2)

        base = [
            SystemMessage(content="System"),
            HumanMessage(content="Go"),
        ]

        # First call: same content
        state1 = {"messages": base + [AIMessage(content="I'm stuck.")]}
        result1 = post_hook(state1)
        # Not yet triggered (count=1)
        assert not any(
            isinstance(m, SystemMessage) and "LOOP DETECTED" in m.content
            for m in result1["messages"]
        )

        # Second call: same content again → triggers at count=2
        state2 = {"messages": base + [AIMessage(content="I'm stuck.")]}
        result2 = post_hook(state2)
        assert any(
            isinstance(m, SystemMessage) and "LOOP DETECTED" in m.content
            for m in result2["messages"]
        )

    def test_repeated_tool_calls_trigger_warning(self):
        """LoopGuard detects identical consecutive tool calls."""
        _, post_hook = create_context_hooks(loop_guard_limit=2)

        base = [SystemMessage(content="System"), HumanMessage(content="Go")]

        tc = [{"name": "kb_read", "args": {"section": "themes"}, "id": "tc1"}]

        # Call 1
        state1 = {"messages": base + [AIMessage(content="", tool_calls=tc)]}
        result1 = post_hook(state1)
        assert not any(
            isinstance(m, SystemMessage) and "LOOP DETECTED" in m.content
            for m in result1["messages"]
        )

        # Call 2 — same tool call → triggers
        state2 = {"messages": base + [AIMessage(content="", tool_calls=tc)]}
        result2 = post_hook(state2)
        assert any(
            isinstance(m, SystemMessage) and "LOOP DETECTED" in m.content
            for m in result2["messages"]
        )


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


class TestTokenEstimation:
    def test_ascii_tokens(self):
        """ASCII: 'hello' = 5 bytes → 5/4 = 1 (rounded), but max(1,1)=1."""
        result = _estimate_tokens("hello")
        assert result >= 1
        assert result <= 2  # 5 bytes / 4 = 1.25

    def test_cjk_tokens(self):
        """CJK: '你好世界' = 12 UTF-8 bytes → 12/4 = 3."""
        result = _estimate_tokens("你好世界")
        assert result == 3

    def test_empty_string(self):
        assert _estimate_tokens("") == 0


# ---------------------------------------------------------------------------
# Integration: create_context_hooks
# ---------------------------------------------------------------------------


class TestCreateContextHooks:
    def test_returns_two_callables(self):
        """create_context_hooks() returns (pre_hook, post_hook), both callable."""
        pre, post = create_context_hooks()
        assert callable(pre)
        assert callable(post)

    def test_pre_hook_returns_llm_input_messages(self):
        """pre_model_hook returns dict with 'llm_input_messages' key."""
        pre, _ = create_context_hooks()
        state = {
            "messages": [
                SystemMessage(content="System"),
                HumanMessage(content="Hello"),
                AIMessage(content="Hi there."),
            ]
        }
        result = pre(state)
        assert "llm_input_messages" in result
        assert isinstance(result["llm_input_messages"], list)
        assert len(result["llm_input_messages"]) == 3

    def test_post_hook_passthrough_when_no_loop(self):
        """post_model_hook passes state through unchanged when no loop."""
        _, post = create_context_hooks()
        state = {
            "messages": [
                SystemMessage(content="System"),
                HumanMessage(content="Go"),
                AIMessage(content="Unique response."),
            ]
        }
        result = post(state)
        # No LOOP DETECTED message appended
        assert len(result["messages"]) == 3

    def test_pre_hook_does_not_mutate_original(self):
        """pre_model_hook must not modify the original message list."""
        pre, _ = create_context_hooks(snip_threshold=100)
        original_messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Go"),
            AIMessage(
                content="",
                tool_calls=[{"name": "kb_read", "args": {}, "id": "tc1"}],
            ),
            ToolMessage(
                content=_make_long_content(500),
                tool_call_id="tc1",
                name="kb_read",
            ),
            AIMessage(content="Done."),
        ]
        original_content = original_messages[3].content
        state = {"messages": list(original_messages)}
        pre(state)
        # Original ToolMessage content should be unchanged
        assert original_messages[3].content == original_content
