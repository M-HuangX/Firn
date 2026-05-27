"""Tests for Audit Manifest Generator."""

import json
import pytest
from pathlib import Path

from src.audit.manifest import (
    generate_analysis_manifest,
    generate_digest_manifest,
    _discover_agents,
    _discover_digest_batches,
    _load_jsonl,
)


@pytest.fixture
def trace_dir(tmp_path):
    """Create a realistic trace directory."""
    exec_dir = tmp_path / "20260516_021117_abc12345"
    exec_dir.mkdir()

    # execution_info.json
    (exec_dir / "execution_info.json").write_text(json.dumps({
        "execution_id": "20260516_021117_abc12345",
        "start_time": "2026-05-16T02:11:17",
        "total_seconds": 159.9,
        "success": True,
    }))

    # trace/prompts/ — 5 agents
    prompts_dir = exec_dir / "trace" / "prompts"
    prompts_dir.mkdir(parents=True)
    for agent in ["fundamental", "technical", "value", "macro", "core_analysis"]:
        (prompts_dir / f"{agent}_system.txt").write_text(f"System prompt for {agent}")
        (prompts_dir / f"{agent}_user.txt").write_text(f"User prompt for {agent}")

    # trace/react_steps/
    steps_dir = exec_dir / "trace" / "react_steps"
    steps_dir.mkdir(parents=True)

    # Core analysis steps
    core_steps = [
        {"step": 1, "output": {"text": "Searching KB", "tool_calls": [
            {"name": "kb_search", "args": {"query": "NOW"}},
            {"name": "kb_search", "args": {"query": "SaaS valuation"}},
        ]}},
        {"step": 2, "output": {"text": "Reading theme", "tool_calls": [
            {"name": "kb_read", "args": {"section": "themes", "slug": "ai-capex"}},
        ]}},
        {"step": 3, "output": {"text": "Final synthesis: NOW is overvalued at 62.5x P/E", "tool_calls": []}},
    ]
    with open(steps_dir / "core_analysis_steps.jsonl", "w") as f:
        for s in core_steps:
            f.write(json.dumps(s) + "\n")

    # Specialist steps
    fund_steps = [
        {"step": 1, "output": {"text": "Got stock info", "tool_calls": [{"name": "get_stock_info", "args": {}}]}},
        {"step": 2, "output": {"text": "Got metrics", "tool_calls": [{"name": "get_financial_metrics", "args": {}}]}},
    ]
    with open(steps_dir / "fundamental_steps.jsonl", "w") as f:
        for s in fund_steps:
            f.write(json.dumps(s) + "\n")

    tech_steps = [
        {"step": 1, "output": {"text": "Got indicators", "tool_calls": [{"name": "get_technical_indicators", "args": {}}]}},
    ]
    with open(steps_dir / "technical_steps.jsonl", "w") as f:
        for s in tech_steps:
            f.write(json.dumps(s) + "\n")

    # tools/
    tools_dir = exec_dir / "tools"
    tools_dir.mkdir()
    for agent in ["fundamental", "technical", "value", "macro", "core_analysis"]:
        (tools_dir / f"{agent}_tool_calls.json").write_text(json.dumps({
            "agent_name": agent,
            "tool_calls": [{"tool_name": "test", "output": "test data"}],
        }))

    # reports/ & other dirs
    (exec_dir / "reports").mkdir()
    (exec_dir / "agents").mkdir()
    (exec_dir / "llm").mkdir()

    return exec_dir


@pytest.fixture
def report_file(tmp_path):
    report = tmp_path / "report_NOW.md"
    report.write_text("# NOW Report\nP/E is 62.5x\n")
    return report


class TestGenerateAnalysisManifest:
    def test_contains_header(self, trace_dir, report_file):
        manifest = generate_analysis_manifest(trace_dir, report_file)
        assert "Audit Manifest" in manifest
        assert "20260516_021117_abc12345" in manifest

    def test_contains_execution_info(self, trace_dir, report_file):
        manifest = generate_analysis_manifest(trace_dir, report_file)
        assert "159.9s" in manifest
        assert "SUCCESS" in manifest

    def test_contains_pipeline_table(self, trace_dir, report_file):
        manifest = generate_analysis_manifest(trace_dir, report_file)
        assert "Pipeline Overview" in manifest
        assert "fundamental" in manifest
        assert "technical" in manifest
        assert "value" in manifest
        assert "macro" in manifest
        assert "core_analysis" in manifest

    def test_contains_prompt_paths(self, trace_dir, report_file):
        manifest = generate_analysis_manifest(trace_dir, report_file)
        assert "trace/prompts/fundamental_system.txt" in manifest
        assert "trace/prompts/fundamental_user.txt" in manifest

    def test_contains_tool_paths(self, trace_dir, report_file):
        manifest = generate_analysis_manifest(trace_dir, report_file)
        assert "tools/fundamental_tool_calls.json" in manifest
        assert "tools/core_analysis_tool_calls.json" in manifest

    def test_contains_reasoning_chain(self, trace_dir, report_file):
        manifest = generate_analysis_manifest(trace_dir, report_file)
        assert "Core Reasoning Chain" in manifest
        assert "Step 1" in manifest
        assert "kb_search" in manifest
        assert "Step 3" in manifest
        assert "synthesis" in manifest.lower() or "Final synthesis" in manifest

    def test_contains_specialist_summaries(self, trace_dir, report_file):
        manifest = generate_analysis_manifest(trace_dir, report_file)
        assert "Specialist Agent Steps" in manifest
        assert "fundamental" in manifest
        assert "get_stock_info" in manifest

    def test_contains_report_location(self, trace_dir, report_file):
        manifest = generate_analysis_manifest(trace_dir, report_file)
        assert "report.md" in manifest

    def test_contains_available_files_guide(self, trace_dir, report_file):
        manifest = generate_analysis_manifest(trace_dir, report_file)
        assert "read_trace_file" in manifest
        assert "grep_trace" in manifest

    def test_no_report_warning(self, trace_dir):
        manifest = generate_analysis_manifest(trace_dir, report_path=None)
        assert "WARNING" in manifest or "No report" in manifest


class TestDiscoverAgents:
    def test_discovers_all_agents(self, trace_dir):
        prompts_dir = trace_dir / "trace" / "prompts"
        agents = _discover_agents(prompts_dir)
        assert set(agents) == {"fundamental", "technical", "value", "macro", "core_analysis"}

    def test_exclude_filter(self, trace_dir):
        prompts_dir = trace_dir / "trace" / "prompts"
        agents = _discover_agents(prompts_dir, exclude={"core_analysis"})
        assert "core_analysis" not in agents
        assert "fundamental" in agents

    def test_include_filter(self, trace_dir):
        prompts_dir = trace_dir / "trace" / "prompts"
        agents = _discover_agents(prompts_dir, include={"core_analysis"})
        assert agents == ["core_analysis"]

    def test_empty_dir(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert _discover_agents(empty) == []

    def test_nonexistent_dir(self, tmp_path):
        assert _discover_agents(tmp_path / "nonexistent") == []


class TestLoadJsonl:
    def test_load_valid(self, trace_dir):
        path = trace_dir / "trace" / "react_steps" / "core_analysis_steps.jsonl"
        items = _load_jsonl(path)
        assert len(items) == 3
        assert items[0]["step"] == 1

    def test_load_nonexistent(self, tmp_path):
        items = _load_jsonl(tmp_path / "nonexistent.jsonl")
        assert items == []


# =========================================================================
# Digest Manifest Tests
# =========================================================================


@pytest.fixture
def digest_trace_dir(tmp_path):
    """Create a realistic digest trace directory."""
    exec_dir = tmp_path / "20260516_100000_digest123"
    exec_dir.mkdir()

    # execution_info.json
    (exec_dir / "execution_info.json").write_text(json.dumps({
        "execution_id": "20260516_100000_digest123",
        "start_time": "2026-05-16T10:00:00",
        "total_seconds": 95.3,
        "success": True,
    }))

    # trace/prompts/ — digest agent (2 batches)
    prompts_dir = exec_dir / "trace" / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "core_digest_system.txt").write_text("Digest system prompt")
    (prompts_dir / "core_digest_user.txt").write_text("Batch 1 input")
    (prompts_dir / "core_digest_b2_system.txt").write_text("Batch 2 system")
    (prompts_dir / "core_digest_b2_user.txt").write_text("Batch 2 input")

    # trace/react_steps/ — digest steps
    steps_dir = exec_dir / "trace" / "react_steps"
    steps_dir.mkdir(parents=True)

    digest_steps = [
        {"step": 1, "output": {"text": "Reading article", "tool_calls": [
            {"name": "read_inbox_item", "args": {"slug": "deepseek-v4-release"}},
        ]}},
        {"step": 2, "output": {"text": "Reading article 2", "tool_calls": [
            {"name": "read_inbox_item", "args": {"slug": "uranium-weekly"}},
        ]}},
        {"step": 3, "output": {"text": "Writing theme about AI", "tool_calls": [
            {"name": "kb_write", "args": {"section": "themes", "slug": "ai-infra-boom", "content": "# AI Infra\n..."}},
        ]}},
        {"step": 4, "output": {"text": "Updating core mind", "tool_calls": [
            {"name": "kb_write_core_mind", "args": {"content": "Market overview..."}},
        ]}},
        {"step": 5, "output": {"text": "Searching KB", "tool_calls": [
            {"name": "kb_search", "args": {"query": "uranium"}},
        ]}},
    ]
    with open(steps_dir / "core_digest_steps.jsonl", "w") as f:
        for s in digest_steps:
            f.write(json.dumps(s) + "\n")

    # tools/
    tools_dir = exec_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "core_digest_tool_calls.json").write_text(json.dumps({
        "agent_name": "core_digest",
        "tool_calls": [{"tool_name": "read_inbox_item", "output": "article content"}],
    }))
    (tools_dir / "core_digest_b2_tool_calls.json").write_text(json.dumps({
        "agent_name": "core_digest",
        "tool_calls": [{"tool_name": "kb_write", "output": "ok"}],
    }))

    # agents/
    (exec_dir / "agents").mkdir()
    (exec_dir / "agents" / "core_digest.json").write_text(json.dumps({
        "agent_name": "core_digest", "status": "completed",
    }))

    return exec_dir


class TestGenerateDigestManifest:
    def test_contains_header(self, digest_trace_dir):
        manifest = generate_digest_manifest(digest_trace_dir)
        assert "Digest Audit Manifest" in manifest
        assert "20260516_100000_digest123" in manifest

    def test_contains_execution_info(self, digest_trace_dir):
        manifest = generate_digest_manifest(digest_trace_dir)
        assert "95.3s" in manifest
        assert "SUCCESS" in manifest

    def test_contains_batch_table(self, digest_trace_dir):
        manifest = generate_digest_manifest(digest_trace_dir)
        assert "Batch Overview" in manifest
        assert "core_digest_system.txt" in manifest
        assert "core_digest_b2_system.txt" in manifest

    def test_contains_kb_write_actions(self, digest_trace_dir):
        manifest = generate_digest_manifest(digest_trace_dir)
        assert "KB Write Actions" in manifest
        assert "kb_write" in manifest
        assert "kb_write_core_mind" in manifest

    def test_contains_article_reads(self, digest_trace_dir):
        manifest = generate_digest_manifest(digest_trace_dir)
        assert "deepseek-v4-release" in manifest
        assert "uranium-weekly" in manifest

    def test_contains_step_summary(self, digest_trace_dir):
        manifest = generate_digest_manifest(digest_trace_dir)
        assert "5 total steps" in manifest
        assert "2 reads" in manifest
        assert "2 writes" in manifest

    def test_contains_trace_file_guide(self, digest_trace_dir):
        manifest = generate_digest_manifest(digest_trace_dir)
        assert "core_digest_tool_calls.json" in manifest
        assert "grep_trace" in manifest


class TestDiscoverDigestBatches:
    def test_single_batch(self, tmp_path):
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "core_digest_system.txt").write_text("sys")
        (prompts_dir / "core_digest_user.txt").write_text("usr")

        batches = _discover_digest_batches(prompts_dir)
        assert len(batches) == 1
        assert batches[0][0] == 1

    def test_multi_batch(self, tmp_path):
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "core_digest_system.txt").write_text("sys")
        (prompts_dir / "core_digest_user.txt").write_text("usr")
        (prompts_dir / "core_digest_b2_system.txt").write_text("sys2")
        (prompts_dir / "core_digest_b2_user.txt").write_text("usr2")
        (prompts_dir / "core_digest_b3_system.txt").write_text("sys3")
        (prompts_dir / "core_digest_b3_user.txt").write_text("usr3")

        batches = _discover_digest_batches(prompts_dir)
        assert len(batches) == 3
        assert batches[2][0] == 3

    def test_empty_dir(self, tmp_path):
        prompts_dir = tmp_path / "empty"
        prompts_dir.mkdir()
        assert _discover_digest_batches(prompts_dir) == []

    def test_nonexistent_dir(self, tmp_path):
        assert _discover_digest_batches(tmp_path / "nope") == []
