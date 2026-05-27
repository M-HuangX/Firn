"""Tests for AuditToolSet — sandboxed trace read/search tools."""

import json
import pytest
from pathlib import Path

from src.audit.tools import AuditToolSet


@pytest.fixture
def trace_dir(tmp_path):
    """Create a mock trace directory with realistic structure."""
    exec_dir = tmp_path / "20260516_021117_abc12345"
    exec_dir.mkdir()

    # execution_info.json
    (exec_dir / "execution_info.json").write_text(json.dumps({
        "execution_id": "20260516_021117_abc12345",
        "start_time": "2026-05-16T02:11:17",
        "success": True,
    }))

    # trace/prompts/
    prompts_dir = exec_dir / "trace" / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "fundamental_system.txt").write_text("You are a fundamental analyst.")
    (prompts_dir / "fundamental_user.txt").write_text("Analyze NOW stock.")
    (prompts_dir / "core_analysis_system.txt").write_text("You are the core analyst.")
    (prompts_dir / "core_analysis_user.txt").write_text("Synthesize the analysis for NOW.")

    # trace/react_steps/
    steps_dir = exec_dir / "trace" / "react_steps"
    steps_dir.mkdir(parents=True)
    steps = [
        {"step": 1, "output": {"text": "Reading stock data", "tool_calls": [{"name": "kb_search", "args": {"query": "NOW"}}]}},
        {"step": 2, "output": {"text": "P/E is 62.5x", "tool_calls": []}},
    ]
    with open(steps_dir / "core_analysis_steps.jsonl", "w") as f:
        for s in steps:
            f.write(json.dumps(s) + "\n")

    # tools/
    tools_dir = exec_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "fundamental_tool_calls.json").write_text(json.dumps({
        "agent_name": "fundamental",
        "tool_calls": [
            {"tool_name": "get_stock_info", "output": {"trailingPE": 62.5, "currentPrice": 185.30}},
            {"tool_name": "get_financial_metrics", "output": {"revenueGrowth": 0.22}},
        ]
    }))
    (tools_dir / "core_analysis_tool_calls.json").write_text(json.dumps({
        "agent_name": "core_analysis",
        "tool_calls": [
            {"tool_name": "kb_search", "output": "Found: ai-capex theme"},
            {"tool_name": "web_search", "input": {"query": "NOW CEO 2026"}, "output": "Kevin Warsh"},
        ]
    }))

    # reports/ (empty — report is external)
    (exec_dir / "reports").mkdir()
    (exec_dir / "agents").mkdir()
    (exec_dir / "llm").mkdir()

    return exec_dir


@pytest.fixture
def report_file(tmp_path):
    """Create a mock report file."""
    report = tmp_path / "report_NOW.md"
    report.write_text(
        "# NOW Analysis Report\n\n"
        "## Executive Summary\n"
        "NOW trades at 185.30 with a P/E of 62.5x.\n"
        "Revenue growth is 22%.\n"
        "## Valuation\n"
        "Kevin Warsh was appointed CEO in 2026.\n"
    )
    return report


@pytest.fixture
def toolset(trace_dir, report_file):
    return AuditToolSet(trace_dir, report_file)


class TestPathSecurity:
    def test_resolve_valid_path(self, toolset, trace_dir):
        result = toolset._resolve_path("tools/fundamental_tool_calls.json")
        assert result is not None
        assert result.exists()

    def test_resolve_report_alias(self, toolset, report_file):
        result = toolset._resolve_path("report.md")
        assert result == report_file

    def test_reject_path_traversal(self, toolset):
        result = toolset._resolve_path("../../etc/passwd")
        assert result is None

    def test_reject_absolute_path(self, toolset):
        result = toolset._resolve_path("/etc/passwd")
        assert result is None

    def test_resolve_nonexistent_file(self, toolset):
        # Path resolves (within sandbox) but file doesn't exist
        result = toolset._resolve_path("tools/nonexistent.json")
        assert result is not None  # Path is valid
        assert not result.exists()  # But file doesn't exist


class TestReadTraceFile:
    def test_read_text_file(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["read_trace_file"].invoke({"path": "trace/prompts/fundamental_system.txt"})
        assert "fundamental analyst" in result

    def test_read_json_pretty_printed(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["read_trace_file"].invoke({"path": "tools/fundamental_tool_calls.json"})
        assert "trailingPE" in result
        assert "62.5" in result
        # Should be pretty-printed (has indentation)
        assert "  " in result

    def test_read_jsonl_formatted(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["read_trace_file"].invoke({"path": "trace/react_steps/core_analysis_steps.jsonl"})
        assert "Step 1" in result
        assert "Step 2" in result
        assert "kb_search" in result

    def test_read_report_alias(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["read_trace_file"].invoke({"path": "report.md"})
        assert "NOW Analysis Report" in result

    def test_read_nonexistent(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["read_trace_file"].invoke({"path": "nonexistent.txt"})
        assert "ERROR" in result

    def test_read_path_traversal_blocked(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["read_trace_file"].invoke({"path": "../../etc/passwd"})
        assert "ERROR" in result
        assert "outside" in result

    def test_read_directory_blocked(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["read_trace_file"].invoke({"path": "tools"})
        assert "ERROR" in result
        assert "directory" in result


class TestGrepTrace:
    def test_grep_finds_number(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["grep_trace"].invoke({"pattern": "62.5"})
        assert "62.5" in result
        assert "fundamental_tool_calls.json" in result

    def test_grep_finds_in_report(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["grep_trace"].invoke({"pattern": "185.30"})
        assert "report.md" in result

    def test_grep_case_insensitive(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["grep_trace"].invoke({"pattern": "kevin warsh"})
        assert "Kevin Warsh" in result

    def test_grep_scoped_to_file(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["grep_trace"].invoke({
            "pattern": "62.5",
            "path": "tools/fundamental_tool_calls.json"
        })
        assert "62.5" in result
        assert "fundamental_tool_calls.json" in result

    def test_grep_no_matches(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["grep_trace"].invoke({"pattern": "zzz_nonexistent_zzz"})
        assert "No matches" in result

    def test_grep_empty_pattern_rejected(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["grep_trace"].invoke({"pattern": ""})
        assert "ERROR" in result

    def test_grep_path_traversal_blocked(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["grep_trace"].invoke({"pattern": "test", "path": "../../etc"})
        assert "ERROR" in result


class TestListTraceFiles:
    def test_list_all(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["list_trace_files"].invoke({"subdir": ""})
        assert "trace" in result or "tools" in result
        assert "fundamental_tool_calls.json" in result

    def test_list_subdir(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["list_trace_files"].invoke({"subdir": "trace/prompts"})
        assert "fundamental_system.txt" in result
        assert "core_analysis_system.txt" in result

    def test_list_shows_report(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["list_trace_files"].invoke({"subdir": ""})
        assert "report.md" in result

    def test_list_nonexistent_subdir(self, toolset):
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["list_trace_files"].invoke({"subdir": "nonexistent"})
        assert "ERROR" in result


class TestGrepTraceRegex:
    """Tests for ripgrep-backed grep_trace with full regex support."""

    def test_grep_trace_regex_escape(self, toolset, trace_dir):
        """Pattern with regex escape like 62\\.25 should match 62.25."""
        # Create a trace file with "62.25"
        data_file = trace_dir / "tools" / "test_data.json"
        data_file.write_text('{"pe_ratio": 62.25, "note": "forward PE"}')

        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["grep_trace"].invoke({"pattern": "62\\.25"})
        assert "62.25" in result
        assert "test_data.json" in result

    def test_grep_trace_regex_wildcard(self, toolset, trace_dir):
        """Pattern with .* wildcard should work."""
        data_file = trace_dir / "trace" / "specialist_outputs"
        data_file.mkdir(parents=True, exist_ok=True)
        (data_file / "fundamental_output.md").write_text(
            "FCF margin: -115M, significantly negative\n"
            "Revenue growth: 22%\n"
        )

        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["grep_trace"].invoke({
            "pattern": "FCF.*-115",
            "path": "trace/specialist_outputs/"
        })
        assert "FCF" in result
        assert "-115" in result

    def test_grep_trace_context_with_line_numbers(self, toolset, trace_dir):
        """context > 0 should show surrounding lines with line numbers."""
        data_file = trace_dir / "tools" / "context_test.txt"
        data_file.write_text(
            "line one\n"
            "line two\n"
            "target value 999\n"
            "line four\n"
            "line five\n"
        )

        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["grep_trace"].invoke({
            "pattern": "999",
            "path": "tools/context_test.txt",
            "context": 1
        })
        assert "999" in result
        # Context should show surrounding lines
        assert "line two" in result
        assert "line four" in result

    def test_grep_trace_case_insensitive_default(self, toolset, trace_dir):
        """Default search should be case insensitive."""
        data_file = trace_dir / "tools" / "case_test.txt"
        data_file.write_text("Revenue Growth is STRONG\n")

        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["grep_trace"].invoke({
            "pattern": "revenue growth",
            "path": "tools/case_test.txt"
        })
        assert "Revenue Growth" in result

    def test_grep_trace_or_pattern(self, toolset, trace_dir):
        """pipe | should work as OR (regex alternation)."""
        data_file = trace_dir / "tools" / "or_test.txt"
        data_file.write_text(
            "alpha value\n"
            "beta value\n"
            "gamma value\n"
        )

        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["grep_trace"].invoke({
            "pattern": "alpha|gamma",
            "path": "tools/or_test.txt"
        })
        assert "alpha" in result
        assert "gamma" in result

    def test_grep_trace_invalid_regex(self, toolset):
        """Invalid regex should return error, not crash."""
        tools = {t.name: t for t in toolset.get_tools()}
        result = tools["grep_trace"].invoke({"pattern": "[invalid"})
        assert "ERROR" in result

    def test_grep_trace_allowed_search_dirs(self, tmp_path):
        """allowed_search_dirs should restrict grep_trace paths."""
        exec_dir = tmp_path / "restricted_test"
        exec_dir.mkdir()

        tools_dir = exec_dir / "tools"
        tools_dir.mkdir()
        (tools_dir / "data.txt").write_text("target data here\n")

        spec_dir = exec_dir / "trace" / "specialist_outputs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "output.txt").write_text("target data here\n")

        ts = AuditToolSet(exec_dir, allowed_search_dirs=["tools/"])
        tools = {t.name: t for t in ts.get_tools()}

        # Searching in allowed dir should work
        result_ok = tools["grep_trace"].invoke({
            "pattern": "target",
            "path": "tools/"
        })
        assert "target" in result_ok
        assert "ERROR" not in result_ok

        # Searching in disallowed dir should fail
        result_err = tools["grep_trace"].invoke({
            "pattern": "target",
            "path": "trace/specialist_outputs/"
        })
        assert "ERROR" in result_err
        assert "can only search in" in result_err

        # Searching with no path should fail (must specify)
        result_no_path = tools["grep_trace"].invoke({
            "pattern": "target"
        })
        assert "ERROR" in result_no_path
        assert "must specify" in result_no_path

    def test_grep_trace_allowed_read_files(self, tmp_path):
        """allowed_read_files should restrict read_trace_file."""
        exec_dir = tmp_path / "read_restricted_test"
        exec_dir.mkdir()

        tools_dir = exec_dir / "tools"
        tools_dir.mkdir()
        (tools_dir / "fundamental_tool_calls.json").write_text('{"data": "secret"}')

        report = tmp_path / "report.md"
        report.write_text("# Report\nPublic content.\n")

        ts = AuditToolSet(exec_dir, report, allowed_read_files=["report.md"])
        tools = {t.name: t for t in ts.get_tools()}

        # Reading allowed file should work
        result_ok = tools["read_trace_file"].invoke({"path": "report.md"})
        assert "Report" in result_ok
        assert "ERROR" not in result_ok

        # Reading disallowed file should fail
        result_err = tools["read_trace_file"].invoke({
            "path": "tools/fundamental_tool_calls.json"
        })
        assert "ERROR" in result_err
        assert "can only read" in result_err

    def test_grep_history_recorded(self, toolset, trace_dir):
        """grep_trace should append to _grep_history."""
        assert len(toolset._grep_history) == 0

        tools = {t.name: t for t in toolset.get_tools()}
        tools["grep_trace"].invoke({"pattern": "62.5"})

        assert len(toolset._grep_history) == 1
        record = toolset._grep_history[0]
        assert record.pattern == "62.5"
        assert "62.5" in record.result_text or record.result_text == ""

    def test_grep_history_recorded_on_no_match(self, toolset):
        """grep_trace should record history even when no matches."""
        tools = {t.name: t for t in toolset.get_tools()}
        tools["grep_trace"].invoke({"pattern": "zzz_no_match_zzz"})

        assert len(toolset._grep_history) == 1
        assert toolset._grep_history[0].result_text == ""


class TestToolSetAPI:
    def test_get_tools_returns_three(self, toolset):
        tools = toolset.get_tools()
        assert len(tools) == 3
        names = {t.name for t in tools}
        assert names == {"read_trace_file", "grep_trace", "list_trace_files"}

    def test_get_tools_by_names(self, toolset):
        tools = toolset.get_tools_by_names(["read_trace_file", "grep_trace"])
        assert len(tools) == 2

    def test_get_tools_by_names_ignores_unknown(self, toolset):
        tools = toolset.get_tools_by_names(["read_trace_file", "nonexistent"])
        assert len(tools) == 1


class TestEvidenceTools:
    """Tests for Step 2-3: evidence verification and new record tools."""

    def test_verify_evidence_matches_grep(self, tmp_path):
        """Evidence that matches a recent grep should be accepted."""
        # Setup: create toolset with a proper tool_calls.json (indent=2)
        trace_dir = tmp_path / "trace_dir"
        trace_dir.mkdir()
        (trace_dir / "tools").mkdir()
        f = trace_dir / "tools" / "fundamental_tool_calls.json"
        f.write_text(json.dumps({
            "agent_name": "fundamental",
            "timestamp": "2026-01-01",
            "tool_call_count": 1,
            "tool_calls": [
                {
                    "tool_name": "get_income_statement",
                    "input": "AAPL",
                    "start_time": 0,
                    "output": "{\"totalRevenue\": 5100000000}",
                    "duration_seconds": 1,
                    "success": True
                }
            ]
        }, indent=2))
        ts = AuditToolSet(trace_dir)
        tools = {t.name: t for t in ts.get_round2_source_tools()}
        # First grep
        grep = tools["grep_trace"]
        result = grep.invoke({"pattern": "5100", "path": "tools/fundamental_tool_calls.json"})
        assert "5100" in result
        # Now record with evidence from grep (auto-resolves agent/tool from file+line)
        record = tools["record_source_evidence"]
        result = record.invoke({
            "claim": "Revenue was $5.1B",
            "claim_in_report": "total revenue reached **$5.1B**",
            "grep_file": "tools/fundamental_tool_calls.json",
            "grep_line": 10,
            "raw_value": "5100000000",
            "grep_evidence": result,  # paste from grep
        })
        assert "OK" in result

    def test_verify_evidence_rejects_fabricated(self, tmp_path):
        """Evidence that doesn't match any grep should be rejected."""
        trace_dir = tmp_path / "trace_dir"
        trace_dir.mkdir()
        (trace_dir / "tools").mkdir()
        f = trace_dir / "tools" / "fundamental_tool_calls.json"
        f.write_text(json.dumps({
            "agent_name": "fundamental",
            "timestamp": "2026-01-01",
            "tool_call_count": 1,
            "tool_calls": [
                {
                    "tool_name": "get_income_statement",
                    "input": "AAPL",
                    "start_time": 0,
                    "output": "{\"totalRevenue\": 5100000000}",
                    "duration_seconds": 1,
                    "success": True
                }
            ]
        }, indent=2))
        ts = AuditToolSet(trace_dir)
        tools = {t.name: t for t in ts.get_round2_source_tools()}
        # NO grep first — go straight to record with fabricated evidence
        record = tools["record_source_evidence"]
        result = record.invoke({
            "claim": "Revenue was $5.1B",
            "claim_in_report": "total revenue reached **$5.1B**",
            "grep_file": "tools/fundamental_tool_calls.json",
            "grep_line": 10,
            "raw_value": "5100000000",
            "grep_evidence": "tools/fundamental_tool_calls.json:10: totalRevenue: 5100000000",
        })
        assert "ERROR" in result

    def test_derived_skips_evidence_check(self, tmp_path):
        """source_type='derived' should skip grep evidence verification."""
        trace_dir = tmp_path / "trace_dir"
        trace_dir.mkdir()
        ts = AuditToolSet(trace_dir)
        tools = {t.name: t for t in ts.get_round2_source_tools()}
        record = tools["record_source_evidence"]
        result = record.invoke({
            "claim": "Revenue grew 26% YoY",
            "claim_in_report": "revenue grew **26% YoY**",
            "grep_file": "tools/fundamental_tool_calls.json",
            "grep_line": -1,
            "raw_value": "computed from 5.1B and 4.05B",
            "grep_evidence": "derived calculation",
            "source_type": "derived",
        })
        assert "OK" in result

    def test_specialist_evidence_tool(self, tmp_path):
        """Specialist evidence tool should work with valid grep evidence."""
        trace_dir = tmp_path / "trace_dir"
        trace_dir.mkdir()
        spec_dir = trace_dir / "trace" / "specialist_outputs"
        spec_dir.mkdir(parents=True)
        f = spec_dir / "fundamental_output.md"
        f.write_text("Revenue reached $5.1B in fiscal 2025.\n")
        ts = AuditToolSet(trace_dir)
        tools = {t.name: t for t in ts.get_round2_specialist_tools()}
        # Grep first
        grep = tools["grep_trace"]
        result = grep.invoke({"pattern": "5.1", "path": "trace/specialist_outputs/"})
        assert "5.1" in result
        # Record
        record = tools["record_specialist_evidence"]
        result = record.invoke({
            "claim": "Revenue was $5.1B",
            "claim_in_report": "total revenue reached **$5.1B**",
            "specialist_agent": "fundamental",
            "grep_line": 1,
            "specialist_excerpt": "Revenue reached $5.1B in fiscal 2025.",
            "grep_evidence": result,
        })
        assert "OK" in result
        # Verify JSONL written
        jsonl = trace_dir / "audit" / "specialist_evidence.jsonl"
        assert jsonl.exists()

    def test_evidence_jsonl_format(self, tmp_path):
        """JSONL output should have correct fields."""
        trace_dir = tmp_path / "trace_dir"
        trace_dir.mkdir()
        (trace_dir / "tools").mkdir()
        f = trace_dir / "tools" / "fundamental_tool_calls.json"
        f.write_text(json.dumps({
            "agent_name": "fundamental",
            "timestamp": "2026-01-01",
            "tool_call_count": 1,
            "tool_calls": [
                {
                    "tool_name": "get_stock_info",
                    "input": "AAPL",
                    "start_time": 0,
                    "output": "{\"pe_ratio\": 18.923}",
                    "duration_seconds": 1,
                    "success": True
                }
            ]
        }, indent=2))
        ts = AuditToolSet(trace_dir)
        tools = {t.name: t for t in ts.get_round2_source_tools()}
        grep = tools["grep_trace"]
        grep_result = grep.invoke({"pattern": "18.923", "path": "tools/fundamental_tool_calls.json"})
        record = tools["record_source_evidence"]
        record.invoke({
            "claim": "P/E of 18.9x",
            "claim_in_report": 'trailing P/E of **18.9x**',
            "grep_file": "tools/fundamental_tool_calls.json",
            "grep_line": 10,
            "raw_value": "18.923",
            "grep_evidence": grep_result,
        })
        jsonl = trace_dir / "audit" / "source_evidence.jsonl"
        entry = json.loads(jsonl.read_text().strip())
        assert entry["claim_in_report"] == 'trailing P/E of **18.9x**'
        assert entry["source_tool"] == "get_stock_info"
        assert entry["raw_value"] == "18.923"
        assert "verdict" not in entry  # No verdict in evidence!

    def test_get_round2_specialist_tools(self, tmp_path):
        """get_round2_specialist_tools should return correct tool set."""
        ts = AuditToolSet(tmp_path)
        tools = ts.get_round2_specialist_tools()
        names = {t.name for t in tools}
        assert "record_specialist_evidence" in names
        assert "grep_trace" in names
        assert "record_source_evidence" not in names
        assert "record_citation" not in names

    def test_get_round2_source_tools(self, tmp_path):
        """get_round2_source_tools should return correct tool set."""
        ts = AuditToolSet(tmp_path)
        tools = ts.get_round2_source_tools()
        names = {t.name for t in tools}
        assert "record_source_evidence" in names
        assert "read_tool_call" in names
        assert "record_specialist_evidence" not in names


class TestClaimInReportVerification:
    """Tests for claim_in_report enforcement against actual report text."""

    @pytest.fixture
    def report_text(self):
        return (
            "# COPX Analysis Report\n\n"
            "## Executive Summary\n\n"
            "COPX trades at **$81.71** with a trailing P/E of **21.6x**.\n"
            "The ETF saw a **+109% one-year rally** driven by copper demand.\n\n"
            "## Macro Context\n\n"
            "| **Market Regime** | **RISK-ON** — S&P 500 at 7,408, VIX 17.7 | Tailwind |\n"
            "| **Fed Funds Rate** | **3.64%** (cut from 4.33% mid-2025) | Lower capex |\n\n"
            "## Technical Snapshot\n\n"
            "Above SMA50 ($80.33, +1.71%) and SMA200 ($69.84, +17%)\n"
            "RSI(14) at 47.92 — Neutral.\n"
            "Dividend Yield: 2.43% (semi-annual)\n\n"
            "## Volume & Buybacks\n\n"
            "Volume during the May 14-15 peak showed some distribution (profit-taking).\n"
            "Massive $40.1B in share buybacks during the year.\n"
        )

    @pytest.fixture
    def cir_toolset(self, tmp_path, report_text):
        """Toolset with a report loaded for claim_in_report verification."""
        trace_dir = tmp_path / "trace_cir"
        trace_dir.mkdir()
        (trace_dir / "tools").mkdir()
        f = trace_dir / "tools" / "fundamental_tool_calls.json"
        f.write_text(json.dumps({
            "agent_name": "fundamental",
            "timestamp": "2026-01-01",
            "tool_call_count": 1,
            "tool_calls": [{
                "tool_name": "get_stock_info",
                "input": "COPX", "start_time": 0,
                "output": '{"trailingPE": 21.6, "currentPrice": 81.71}',
                "duration_seconds": 1, "success": True,
            }]
        }, indent=2))
        spec_dir = trace_dir / "trace" / "specialist_outputs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fundamental_output.md").write_text(
            "P/E is 21.6x. Current price $81.71.\n")
        report_path = tmp_path / "report.md"
        report_path.write_text(report_text)
        return AuditToolSet(trace_dir, report_path)

    # ── Phase 1: normalized substring ──

    def test_exact_match_passes(self, cir_toolset):
        ok, _ = cir_toolset._verify_claim_in_report("VIX 17.7")
        assert ok

    def test_markdown_stripped_match_passes(self, cir_toolset):
        """Bold markers stripped, should still match."""
        ok, _ = cir_toolset._verify_claim_in_report(
            "COPX trades at **$81.71** with a trailing P/E of **21.6x**.")
        assert ok

    def test_table_pipe_match_passes(self, cir_toolset):
        """Table row with pipes should match after pipe stripping."""
        ok, _ = cir_toolset._verify_claim_in_report(
            '| **Market Regime** | **RISK-ON** — S&P 500 at 7,408, VIX 17.7 | Tailwind |')
        assert ok

    def test_partial_line_match_passes(self, cir_toolset):
        """Substring of a report line should match."""
        ok, _ = cir_toolset._verify_claim_in_report("trailing P/E of **21.6x**")
        assert ok

    # ── Non-substring rejections (no fuzzy fallback) ──

    def test_near_miss_non_substring_rejected(self, cir_toolset):
        """Text with matching numbers but not a substring → reject.

        No Phase 2 fallback: frontend Phase 0 uses substring matching for
        claim_in_report, so backend must reject non-substrings too.
        """
        ok, _ = cir_toolset._verify_claim_in_report("SMA50 at $80.33")
        assert not ok

    def test_paraphrase_rejected(self, cir_toolset):
        """Paraphrased text with same facts but different wording → reject.

        NVDA #61: claim says "distribution was visible" but report says
        "peak showed some distribution".  Not a substring.
        """
        ok, err = cir_toolset._verify_claim_in_report(
            "distribution was visible on May 14-15 "
            "(heavy volume, price pulling back from the high)")
        assert not ok

    def test_partial_data_rejected(self, cir_toolset):
        """Claim with extra data not in report → reject.

        NVDA #69: claim has $40.1B + $33.7B but report only has $40.1B.
        """
        ok, err = cir_toolset._verify_claim_in_report(
            "**$40.1B** in FY2026 repurchases (up from $33.7B in FY2025)")
        assert not ok

    # ── Rejections ──

    def test_annotation_rejected(self, cir_toolset):
        """Parenthetical annotation is not report text."""
        ok, err = cir_toolset._verify_claim_in_report(
            "(Not explicitly in the report, but implied)")
        assert not ok
        assert "not found" in err.lower()

    def test_absent_data_rejected(self, cir_toolset):
        """Data that doesn't appear in the report should be rejected."""
        ok, err = cir_toolset._verify_claim_in_report(
            "$0.428 (2017 dividend)")
        assert not ok

    def test_specialist_only_data_rejected(self, cir_toolset):
        """Technical data not in report is rejected."""
        ok, err = cir_toolset._verify_claim_in_report(
            "Bollinger %B: 0.44")
        assert not ok

    def test_meta_commentary_rejected(self, cir_toolset):
        ok, err = cir_toolset._verify_claim_in_report(
            "(From value analysis)")
        assert not ok

    def test_too_short_rejected(self, cir_toolset):
        ok, err = cir_toolset._verify_claim_in_report("hi")
        assert not ok
        assert "short" in err.lower()

    # ── Skip when no report ──

    def test_no_report_skips_verification(self, tmp_path):
        """Without a report_path, verification is skipped (always OK)."""
        ts = AuditToolSet(tmp_path)
        ok, _ = ts._verify_claim_in_report("anything goes")
        assert ok

    # ── Integration: record tools reject bad claim_in_report ──

    def test_source_evidence_rejects_bad_cir(self, cir_toolset):
        """record_source_evidence should reject annotation claim_in_report."""
        tools = {t.name: t for t in cir_toolset.get_round2_source_tools()}
        # Grep first to satisfy grep evidence check
        grep = tools["grep_trace"]
        grep_result = grep.invoke({
            "pattern": "21.6", "path": "tools/fundamental_tool_calls.json"})
        record = tools["record_source_evidence"]
        result = record.invoke({
            "claim": "P/E is 21.6x",
            "claim_in_report": "(Technical indicator from specialist)",
            "grep_file": "tools/fundamental_tool_calls.json",
            "grep_line": 10,
            "raw_value": "21.6",
            "grep_evidence": grep_result,
        })
        assert "ERROR" in result
        assert "not found in the report" in result

    def test_specialist_evidence_rejects_bad_cir(self, cir_toolset):
        """record_specialist_evidence should reject annotation claim_in_report."""
        tools = {t.name: t for t in cir_toolset.get_round2_specialist_tools()}
        grep = tools["grep_trace"]
        grep_result = grep.invoke({
            "pattern": "21.6", "path": "trace/specialist_outputs/"})
        record = tools["record_specialist_evidence"]
        result = record.invoke({
            "claim": "P/E is 21.6x",
            "claim_in_report": "(Not in the report)",
            "specialist_agent": "fundamental",
            "grep_line": 1,
            "specialist_excerpt": "P/E is 21.6x.",
            "grep_evidence": grep_result,
        })
        assert "ERROR" in result
        assert "not found in the report" in result

    def test_source_evidence_accepts_good_cir(self, cir_toolset):
        """record_source_evidence should accept valid claim_in_report."""
        tools = {t.name: t for t in cir_toolset.get_round2_source_tools()}
        grep = tools["grep_trace"]
        grep_result = grep.invoke({
            "pattern": "21.6", "path": "tools/fundamental_tool_calls.json"})
        record = tools["record_source_evidence"]
        result = record.invoke({
            "claim": "P/E is 21.6x",
            "claim_in_report": "trailing P/E of **21.6x**",
            "grep_file": "tools/fundamental_tool_calls.json",
            "grep_line": 10,
            "raw_value": "21.6",
            "grep_evidence": grep_result,
        })
        assert "OK" in result

    def test_enforcement_log_records_cir_rejection(self, cir_toolset):
        """CIR rejection should be recorded in enforcement log."""
        tools = {t.name: t for t in cir_toolset.get_round2_source_tools()}
        grep = tools["grep_trace"]
        grep_result = grep.invoke({
            "pattern": "21.6", "path": "tools/fundamental_tool_calls.json"})
        record = tools["record_source_evidence"]
        record.invoke({
            "claim": "P/E is 21.6x",
            "claim_in_report": "(annotation not in report)",
            "grep_file": "tools/fundamental_tool_calls.json",
            "grep_line": 10,
            "raw_value": "21.6",
            "grep_evidence": grep_result,
        })
        assert cir_toolset.enforcement_count >= 1
        entry = cir_toolset._enforcement_log[-1]
        assert "claim_in_report" in entry
        assert "not found" in entry["reason"].lower()


# ---------------------------------------------------------------------------
# Claim-in-specialist-output verification (v4.3)
# ---------------------------------------------------------------------------

class TestClaimInSpecialistOutputVerification:
    """Tests for R1 claim enforcement against specialist output text."""

    SPECIALIST_OUTPUT = (
        "<!-- agent: fundamental | ticker: GOOG | generated: 2026-05-21 -->\n\n"
        "# Fundamental Analysis Report: Alphabet Inc. (GOOG)\n\n"
        "**Current Price:** $386.43\n"
        "**Market Cap:** ~$4.67 trillion (12.088B shares × $386.35)\n"
        "Revenue growth was **22% YoY** reaching $350.02B in FY2025.\n"
        "Operating margin improved to **32.8%** from 27.4%.\n"
        "| Metric | Value |\n"
        "| P/E Ratio | 29.4x |\n"
        "| Free Cash Flow | $63.7B |\n"
        "No insider buying detected in the last 6 months.\n"
        "FCF Yield: ~1.55% ($63.7B / $4.67T market cap)\n"
    )

    @pytest.fixture
    def ciso_toolset(self, tmp_path):
        """Toolset with specialist outputs loaded for verification."""
        trace_dir = tmp_path / "trace_ciso"
        trace_dir.mkdir()
        (trace_dir / "tools").mkdir()
        tc_file = trace_dir / "tools" / "fundamental_tool_calls.json"
        tc_file.write_text(json.dumps({
            "agent_name": "fundamental",
            "timestamp": "2026-01-01",
            "tool_call_count": 2,
            "tool_calls": [
                {
                    "tool_name": "get_stock_info",
                    "input": "GOOG", "start_time": 0,
                    "output": '{"trailingPE": 29.4, "currentPrice": 386.43}',
                    "duration_seconds": 1, "success": True,
                },
                {
                    "tool_name": "get_cash_flow",
                    "input": "GOOG", "start_time": 1,
                    "output": '{"freeCashFlow": 63700000000}',
                    "duration_seconds": 1, "success": True,
                },
            ]
        }, indent=2))
        spec_dir = trace_dir / "trace" / "specialist_outputs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fundamental_output.md").write_text(self.SPECIALIST_OUTPUT)
        (spec_dir / "technical_output.md").write_text(
            "RSI(14) at 52.3 — Neutral.\n"
            "Above SMA200 ($310.50, +24.5%)\n"
        )
        return AuditToolSet(trace_dir)

    # ── Phase 1: normalized substring ──

    def test_exact_match_passes(self, ciso_toolset):
        ok, _ = ciso_toolset._verify_claim_in_specialist_output(
            "Current Price: $386.43", "fundamental")
        assert ok

    def test_markdown_stripped_match(self, ciso_toolset):
        ok, _ = ciso_toolset._verify_claim_in_specialist_output(
            "**Current Price:** $386.43", "fundamental")
        assert ok

    def test_partial_line_match(self, ciso_toolset):
        ok, _ = ciso_toolset._verify_claim_in_specialist_output(
            "Revenue growth was 22% YoY", "fundamental")
        assert ok

    def test_table_cell_match(self, ciso_toolset):
        ok, _ = ciso_toolset._verify_claim_in_specialist_output(
            "P/E Ratio | 29.4x", "fundamental")
        assert ok

    def test_cross_agent_fails(self, ciso_toolset):
        """Claim from technical output should not match fundamental."""
        ok, _ = ciso_toolset._verify_claim_in_specialist_output(
            "RSI(14) at 52.3", "fundamental")
        assert not ok

    def test_cross_agent_correct_agent_passes(self, ciso_toolset):
        ok, _ = ciso_toolset._verify_claim_in_specialist_output(
            "RSI(14) at 52.3", "technical")
        assert ok

    # ── Substring after markdown strip ──

    def test_table_content_substring_match(self, ciso_toolset):
        """Table pipes stripped → 'Free Cash Flow $63.7B' is a substring."""
        ok, _ = ciso_toolset._verify_claim_in_specialist_output(
            "Free Cash Flow $63.7B", "fundamental")
        assert ok

    # ── Non-substring rejections (no fuzzy fallback) ──

    def test_near_miss_non_substring_rejected(self, ciso_toolset):
        """Matching numbers but different phrasing → not a substring → reject."""
        ok, _ = ciso_toolset._verify_claim_in_specialist_output(
            "Operating margin 32.8% up from 27.4%", "fundamental")
        assert not ok

    def test_near_miss_different_preposition_rejected(self, ciso_toolset):
        """'SMA200 at $310.50' vs 'SMA200 ($310.50' — not a substring."""
        ok, _ = ciso_toolset._verify_claim_in_specialist_output(
            "SMA200 at $310.50", "technical")
        assert not ok

    # ── Rejections ──

    def test_paraphrased_claim_rejected(self, ciso_toolset):
        """Paraphrased text not in specialist output."""
        ok, err = ciso_toolset._verify_claim_in_specialist_output(
            "The company has incredibly strong revenue momentum", "fundamental")
        assert not ok
        assert "not found" in err.lower()

    def test_fabricated_number_rejected(self, ciso_toolset):
        ok, err = ciso_toolset._verify_claim_in_specialist_output(
            "Revenue was $999.9B", "fundamental")
        assert not ok

    def test_too_short_rejected(self, ciso_toolset):
        ok, err = ciso_toolset._verify_claim_in_specialist_output(
            "hi", "fundamental")
        assert not ok
        assert "too short" in err.lower()

    def test_missing_agent_skips(self, ciso_toolset):
        """No output loaded for macro → verification skipped (ok=True)."""
        ok, _ = ciso_toolset._verify_claim_in_specialist_output(
            "anything goes", "macro")
        assert ok

    # ── R1 record_specialist_claim integration ──

    def test_r1_record_rejects_fabricated_claim(self, ciso_toolset):
        """record_specialist_claim should reject claims not in specialist output."""
        tools = {t.name: t for t in ciso_toolset.get_round1_tools()}

        # First grep to get evidence in history
        tools["grep_trace"].invoke({"pattern": "386.43",
                                    "path": "tools/fundamental_tool_calls.json"})

        grep_result = ciso_toolset._grep_history[-1].result_text

        result = tools["record_specialist_claim"].invoke({
            "agent": "fundamental",
            "claim": "The stock is wildly overvalued and will crash",
            "output_line": 5,
            "verdict": "found",
            "grep_file": "tools/fundamental_tool_calls.json",
            "grep_line": 6,
            "raw_value": "386.43",
            "grep_evidence": grep_result,
        })
        assert "ERROR" in result
        assert "not found" in result.lower()

    def test_r1_record_accepts_valid_claim(self, ciso_toolset):
        """record_specialist_claim should accept claims found in specialist output."""
        tools = {t.name: t for t in ciso_toolset.get_round1_tools()}

        tools["grep_trace"].invoke({"pattern": "386.43",
                                    "path": "tools/fundamental_tool_calls.json"})
        grep_result = ciso_toolset._grep_history[-1].result_text

        result = tools["record_specialist_claim"].invoke({
            "agent": "fundamental",
            "claim": "Current Price: $386.43",
            "output_line": 5,
            "verdict": "found",
            "grep_file": "tools/fundamental_tool_calls.json",
            "grep_line": 6,
            "raw_value": "386.43",
            "grep_evidence": grep_result,
        })
        assert result.startswith("OK")

    def test_r1_enforcement_log_records_ciso_rejection(self, ciso_toolset):
        """Enforcement log should capture specialist output rejections."""
        tools = {t.name: t for t in ciso_toolset.get_round1_tools()}

        tools["grep_trace"].invoke({"pattern": "29.4",
                                    "path": "tools/fundamental_tool_calls.json"})
        grep_result = ciso_toolset._grep_history[-1].result_text

        tools["record_specialist_claim"].invoke({
            "agent": "fundamental",
            "claim": "This is a completely made up claim about PE ratios",
            "output_line": 10,
            "verdict": "found",
            "grep_file": "tools/fundamental_tool_calls.json",
            "grep_line": 6,
            "raw_value": "29.4",
            "grep_evidence": grep_result,
        })
        assert ciso_toolset.enforcement_count >= 1
        entry = ciso_toolset._enforcement_log[-1]
        assert entry["tool"] == "record_specialist_claim"
        assert "not found" in entry["reason"].lower()

    def test_r1_not_found_verdict_still_verified(self, ciso_toolset):
        """not-found claims still need to exist in the specialist output."""
        tools = {t.name: t for t in ciso_toolset.get_round1_tools()}

        result = tools["record_specialist_claim"].invoke({
            "agent": "fundamental",
            "claim": "No insider buying detected in the last 6 months",
            "output_line": 12,
            "verdict": "not-found",
            "grep_file": "",
            "grep_line": -1,
            "raw_value": "",
            "grep_evidence": "",
        })
        assert result.startswith("OK")

    def test_r1_not_found_fabricated_rejected(self, ciso_toolset):
        """not-found with fabricated claim text should still be rejected."""
        tools = {t.name: t for t in ciso_toolset.get_round1_tools()}

        result = tools["record_specialist_claim"].invoke({
            "agent": "fundamental",
            "claim": "Management guided for 50% revenue growth next year",
            "output_line": 15,
            "verdict": "not-found",
            "grep_file": "",
            "grep_line": -1,
            "raw_value": "",
            "grep_evidence": "",
        })
        assert "ERROR" in result
