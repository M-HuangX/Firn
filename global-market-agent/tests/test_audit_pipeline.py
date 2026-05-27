"""Tests for Audit Agent output parsing and pipeline utilities."""

import json
import pytest
from pathlib import Path

from src.audit.agent import (
    _extract_final_output,
    _extract_audit_report,
    _extract_citations,
    AuditAgent,
)
from src.audit.pipeline import (
    _resolve_exec_dir,
    _find_latest_analysis,
    _find_latest_digest,
    _detect_execution_mode,
)


class TestExtractFinalOutput:
    def test_extract_string_content(self):
        class MockMsg:
            content = "Final answer here"

        result = _extract_final_output({"messages": [MockMsg()]})
        assert result == "Final answer here"

    def test_extract_list_content(self):
        class MockMsg:
            content = [{"type": "text", "text": "Part 1"}, {"type": "text", "text": "Part 2"}]

        result = _extract_final_output({"messages": [MockMsg()]})
        assert "Part 1" in result
        assert "Part 2" in result

    def test_extract_last_non_empty(self):
        class Msg1:
            content = "First"
        class Msg2:
            content = ""
        class Msg3:
            content = "Last real message"

        result = _extract_final_output({"messages": [Msg1(), Msg2(), Msg3()]})
        assert result == "Last real message"

    def test_empty_messages(self):
        result = _extract_final_output({"messages": []})
        assert result == ""


class TestExtractAuditReport:
    def test_extract_with_header(self):
        raw = "### AUDIT_REPORT\n## Audit Summary\nTotal: 10\n### CITATIONS_JSON\n{}"
        report = _extract_audit_report(raw)
        assert "Audit Summary" in report
        assert "Total: 10" in report
        assert "CITATIONS_JSON" not in report

    def test_extract_with_summary_header(self):
        raw = "## Audit Summary\n- Total: 5\n- Verified: 3\n\n### CITATIONS_JSON\n```json\n{}\n```"
        report = _extract_audit_report(raw)
        assert "Total: 5" in report

    def test_fallback_before_citations(self):
        raw = "Some audit text\nMore details\nCITATIONS_JSON\n{}"
        report = _extract_audit_report(raw)
        assert "Some audit text" in report

    def test_no_markers_returns_all(self):
        raw = "Just the whole output"
        report = _extract_audit_report(raw)
        assert report == "Just the whole output"


class TestExtractCitations:
    def test_extract_json_block(self):
        raw = '### CITATIONS_JSON\n```json\n{"citations": [{"id": 1}], "summary": {"total_claims": 1}}\n```'
        citations = _extract_citations(raw)
        assert citations["citations"][0]["id"] == 1
        assert citations["summary"]["total_claims"] == 1

    def test_extract_without_json_fence(self):
        raw = '### CITATIONS_JSON\n```\n{"citations": [{"id": 2}], "summary": {"total_claims": 1}}\n```'
        citations = _extract_citations(raw)
        assert citations["citations"][0]["id"] == 2

    def test_malformed_json_returns_empty(self):
        raw = '### CITATIONS_JSON\n```json\n{invalid json}\n```'
        citations = _extract_citations(raw)
        assert citations["citations"] == []
        assert citations["summary"].get("parse_error") is True

    def test_no_citations_section(self):
        raw = "Just some text without citations"
        citations = _extract_citations(raw)
        assert citations["citations"] == []


class TestAuditAgentFindReport:
    def test_find_report_in_trace(self, tmp_path):
        exec_dir = tmp_path / "logs" / "20260516_021117_abc"
        reports_dir = exec_dir / "reports"
        reports_dir.mkdir(parents=True)
        report = reports_dir / "final_report.md"
        report.write_text("# Report")
        (exec_dir / "trace" / "prompts").mkdir(parents=True)
        (exec_dir / "trace" / "react_steps").mkdir(parents=True)
        (exec_dir / "tools").mkdir()

        agent = AuditAgent(exec_dir)
        assert agent.report_path == report

    def test_find_report_in_standalone_dir(self, tmp_path):
        # Setup: logs dir + standalone reports dir
        logs_dir = tmp_path / "logs"
        exec_dir = logs_dir / "20260516_021117_abc"
        for sub in ("trace/prompts", "trace/react_steps", "tools", "reports", "agents", "llm"):
            (exec_dir / sub).mkdir(parents=True)

        # No report in trace dir, but one in global reports/
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        report = reports_dir / "report_NOW_20260516_021357.md"
        report.write_text("# NOW Report")

        agent = AuditAgent(exec_dir)
        assert agent.report_path == report

    def test_no_report_found(self, tmp_path):
        exec_dir = tmp_path / "logs" / "20260516_021117_abc"
        for sub in ("trace/prompts", "trace/react_steps", "tools", "reports"):
            (exec_dir / sub).mkdir(parents=True)

        agent = AuditAgent(exec_dir)
        assert agent.report_path is None


class TestResolveExecDir:
    def test_latest_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.audit.pipeline._LOGS_DIR", tmp_path)
        with pytest.raises(FileNotFoundError, match="No analysis execution"):
            _find_latest_analysis()

    def test_exact_match(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.audit.pipeline._LOGS_DIR", tmp_path)
        exec_dir = tmp_path / "20260516_021117_abc"
        exec_dir.mkdir()
        result = _resolve_exec_dir("20260516_021117_abc")
        assert result == exec_dir

    def test_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.audit.pipeline._LOGS_DIR", tmp_path)
        with pytest.raises(FileNotFoundError):
            _resolve_exec_dir("nonexistent")

    def test_find_latest_with_trace(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.audit.pipeline._LOGS_DIR", tmp_path)

        # Older run without trace
        old = tmp_path / "20260515_100000_aaa"
        old.mkdir()

        # Newer run with trace + specialist prompts
        new = tmp_path / "20260516_100000_bbb"
        prompts = new / "trace" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "fundamental_system.txt").write_text("test")

        result = _find_latest_analysis()
        assert result == new


class TestFindLatestDigest:
    def test_find_by_agent_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.audit.pipeline._LOGS_DIR", tmp_path)

        d = tmp_path / "20260516_100000_digest1"
        agents = d / "agents"
        agents.mkdir(parents=True)
        (agents / "core_digest.json").write_text("{}")

        result = _find_latest_digest()
        assert result == d

    def test_find_by_prompt_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.audit.pipeline._LOGS_DIR", tmp_path)

        d = tmp_path / "20260516_100000_digest2"
        prompts = d / "trace" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "core_digest_system.txt").write_text("sys")

        result = _find_latest_digest()
        assert result == d

    def test_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.audit.pipeline._LOGS_DIR", tmp_path)
        with pytest.raises(FileNotFoundError, match="No digest execution"):
            _find_latest_digest()


class TestDetectExecutionMode:
    def test_detect_analysis(self, tmp_path):
        prompts = tmp_path / "trace" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "fundamental_system.txt").write_text("sys")
        (prompts / "core_analysis_system.txt").write_text("sys")

        assert _detect_execution_mode(tmp_path) == "analysis"

    def test_detect_digest(self, tmp_path):
        prompts = tmp_path / "trace" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "core_digest_system.txt").write_text("sys")

        assert _detect_execution_mode(tmp_path) == "digest"

    def test_fallback_to_agents_dir(self, tmp_path):
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "core_digest.json").write_text("{}")

        assert _detect_execution_mode(tmp_path) == "digest"

    def test_default_analysis(self, tmp_path):
        # No trace dir, no agents dir
        assert _detect_execution_mode(tmp_path) == "analysis"
