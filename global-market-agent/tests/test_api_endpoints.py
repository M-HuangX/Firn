"""Tests for FastAPI endpoints — auth, system, analysis, digest, KB, config, SSE."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


# --- Fixtures ---

@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    """Set required env vars for auth."""
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-testing")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-pass")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("VISITOR_DAILY_BUDGET", "10")
    monkeypatch.setenv("ENVIRONMENT", "development")


@pytest.fixture
def app(env_vars):
    """Create a fresh app instance for each test."""
    # Reset auth module cached values
    import src.api.auth as auth_mod
    auth_mod._JWT_SECRET = None
    auth_mod._ADMIN_PASSWORD = None

    from src.api.app import create_app
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_client(client):
    """Client with admin auth cookie."""
    resp = client.post("/api/auth/login", json={"password": "test-admin-pass"})
    assert resp.status_code == 200
    return client


# --- Auth Tests ---

class TestAuth:
    def test_login_success(self, client):
        resp = client.post("/api/auth/login", json={"password": "test-admin-pass"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"
        assert "access_token" in resp.cookies

    def test_login_wrong_password(self, client):
        resp = client.post("/api/auth/login", json={"password": "wrong"})
        assert resp.status_code == 401

    def test_me_visitor_auto_issue(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "visitor"
        assert "access_token" in resp.cookies

    def test_me_admin(self, admin_client):
        resp = admin_client.get("/api/auth/me")
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    def test_logout(self, admin_client):
        resp = admin_client.post("/api/auth/logout")
        assert resp.status_code == 200


# --- System Tests ---

class TestSystem:
    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "active_executions" in data

    def test_status(self, app, client):
        from unittest.mock import MagicMock
        from src.api.dependencies import get_kb

        kb = MagicMock()
        kb.list_themes.return_value = ["tech", "macro"]
        kb.list_stocks.return_value = ["AAPL", "MSFT"]
        kb.list_unread.return_value = ["a.md"]
        kb.list_read.return_value = ["b.md", "c.md"]
        kb.read_core_mind.return_value = "Test core mind"
        kb.get_last_updated.return_value = {}
        app.dependency_overrides[get_kb] = lambda: kb

        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_themes"] == 2
        assert data["total_stocks"] == 2
        assert data["total_articles"] == 3
        assert data["core_mind_chars"] == 14
        assert data["llm_provider"] == "deepseek"

        app.dependency_overrides.clear()


# --- Analysis Tests ---

class TestAnalysis:
    @patch("src.api.routers.analysis.submit_analysis", new_callable=AsyncMock)
    def test_submit_analysis(self, mock_submit, admin_client):
        mock_submit.return_value = "20260516_120000_abc12345"
        resp = admin_client.post("/api/analysis", json={"ticker": "AAPL"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["exec_id"] == "20260516_120000_abc12345"
        assert data["status"] == "queued"
        mock_submit.assert_called_once_with("AAPL", None)

    @patch("src.api.routers.analysis.submit_analysis", new_callable=AsyncMock)
    def test_submit_analysis_with_query(self, mock_submit, admin_client):
        mock_submit.return_value = "20260516_120000_abc12345"
        resp = admin_client.post(
            "/api/analysis", json={"ticker": "MSFT", "query": "focus on cloud growth"}
        )
        assert resp.status_code == 200
        mock_submit.assert_called_once_with("MSFT", "focus on cloud growth")

    def test_list_analyses_empty(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("src.api.routers.analysis.LOGS_DIR", tmp_path)
        resp = client.get("/api/analysis")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_analyses_with_data(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("src.api.routers.analysis.LOGS_DIR", tmp_path)
        # Create a fake analysis exec dir
        exec_dir = tmp_path / "20260516_120000_abc12345"
        exec_dir.mkdir()
        (exec_dir / "agents").mkdir()
        (exec_dir / "agents" / "fundamental.json").write_text(
            json.dumps({"execution_time": 45.2})
        )
        (exec_dir / "execution_info.json").write_text(
            json.dumps({
                "start_time": "2026-05-16T12:00:00",
                "end_time": "2026-05-16T12:02:00",
                "success": True,
            })
        )
        (exec_dir / "reports").mkdir()
        (exec_dir / "reports" / "final_report_info.json").write_text(
            json.dumps({"report_path": "firn/notebook/stocks/AAPL/latest_report.md"})
        )

        resp = client.get("/api/analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["exec_id"] == "20260516_120000_abc12345"
        assert data[0]["ticker"] == "AAPL"
        assert data[0]["status"] == "complete"

    def test_get_analysis_not_found(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("src.api.routers.analysis.LOGS_DIR", tmp_path)
        resp = client.get("/api/analysis/nonexistent")
        assert resp.status_code == 404

    def test_get_analysis_detail(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("src.api.routers.analysis.LOGS_DIR", tmp_path)
        exec_dir = tmp_path / "20260516_120000_abc12345"
        exec_dir.mkdir()
        (exec_dir / "agents").mkdir()
        (exec_dir / "agents" / "fundamental.json").write_text(
            json.dumps({"execution_time": 45.2, "token_usage": {"total_tokens": 5000}})
        )
        (exec_dir / "agents" / "technical.json").write_text(
            json.dumps({"execution_time": 30.1, "token_usage": {"total_tokens": 3000}})
        )
        (exec_dir / "execution_info.json").write_text(
            json.dumps({
                "start_time": "2026-05-16T12:00:00",
                "end_time": "2026-05-16T12:02:00",
                "success": True,
            })
        )
        (exec_dir / "reports").mkdir()
        (exec_dir / "reports" / "final_report.md").write_text("# AAPL Analysis\n\nReport content")

        resp = client.get("/api/analysis/20260516_120000_abc12345")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "complete"
        assert data["report"] == "# AAPL Analysis\n\nReport content"
        assert data["report_length"] == len("# AAPL Analysis\n\nReport content")
        assert data["agent_timings"]["fundamental"] == 45.2
        assert data["token_usage"]["fundamental"] == 5000

    def test_get_report(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("src.api.routers.analysis.LOGS_DIR", tmp_path)
        exec_dir = tmp_path / "exec1"
        exec_dir.mkdir()
        (exec_dir / "reports").mkdir()
        (exec_dir / "reports" / "final_report.md").write_text("# Test Report")

        resp = client.get("/api/analysis/exec1/report")
        assert resp.status_code == 200
        assert resp.json()["report_markdown"] == "# Test Report"

    def test_get_audit_data(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("src.api.routers.analysis.LOGS_DIR", tmp_path)
        exec_dir = tmp_path / "exec1"
        exec_dir.mkdir()
        (exec_dir / "audit").mkdir()
        (exec_dir / "audit" / "citations.json").write_text(
            json.dumps({
                "summary": {"tool_verified": 10, "llm_inferred": 5},
                "citations": [
                    {
                        "id": 1,
                        "claim": "Revenue grew 25%",
                        "report_line": 5,
                        "verdict": "tool-verified",
                        "source": {"tool": "get_income_statement", "field": "revenue"},
                    }
                ],
            })
        )
        (exec_dir / "audit" / "audit_report.md").write_text("## Audit Summary")

        resp = client.get("/api/analysis/exec1/audit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_claims"] == 1
        # Underscore → hyphen normalization
        assert data["verdicts"]["tool-verified"] == 10
        assert data["verdicts"]["llm-inferred"] == 5
        assert data["citations"][0]["verdict"] == "tool-verified"
        assert data["audit_report"] == "## Audit Summary"

    @patch("src.api.routers.analysis.submit_audit", new_callable=AsyncMock)
    def test_trigger_audit_visitor_accessible(self, mock_submit, client, tmp_path, monkeypatch):
        monkeypatch.setattr("src.api.routers.analysis.LOGS_DIR", tmp_path)
        exec_dir = tmp_path / "exec1"
        exec_dir.mkdir()
        mock_submit.return_value = "audit_exec_123"

        # Visitor can trigger audit (no longer admin-only)
        resp = client.post("/api/analysis/exec1/audit")
        assert resp.status_code == 200
        assert resp.json()["exec_id"] == "audit_exec_123"

    @patch("src.api.routers.analysis.submit_audit", new_callable=AsyncMock)
    def test_trigger_audit_admin_success(self, mock_submit, admin_client, tmp_path, monkeypatch):
        monkeypatch.setattr("src.api.routers.analysis.LOGS_DIR", tmp_path)
        exec_dir = tmp_path / "exec1"
        exec_dir.mkdir()
        mock_submit.return_value = "audit_exec_123"

        resp = admin_client.post("/api/analysis/exec1/audit")
        assert resp.status_code == 200
        assert resp.json()["exec_id"] == "audit_exec_123"


# --- Digest Tests ---

class TestDigest:
    @patch("src.api.routers.digest.submit_digest", new_callable=AsyncMock)
    def test_submit_digest_admin_only(self, mock_submit, client):
        # Visitor gets 404
        resp = client.post("/api/digest")
        assert resp.status_code == 404

    @patch("src.api.routers.digest.submit_digest", new_callable=AsyncMock)
    def test_submit_digest_admin(self, mock_submit, admin_client):
        mock_submit.return_value = "digest_exec_123"
        resp = admin_client.post("/api/digest")
        assert resp.status_code == 200
        assert resp.json()["exec_id"] == "digest_exec_123"

    def test_list_digests_empty(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("src.api.routers.digest.LOGS_DIR", tmp_path)
        resp = client.get("/api/digest")
        assert resp.status_code == 200
        assert resp.json() == []


# --- KB Tests ---

class TestKB:
    def _mock_kb(self, app, **overrides):
        from unittest.mock import MagicMock
        from src.api.dependencies import get_kb

        kb = MagicMock()
        for k, v in overrides.items():
            setattr(kb, k, v if callable(v) else MagicMock(return_value=v))
        app.dependency_overrides[get_kb] = lambda: kb
        return kb

    def test_list_themes(self, app, client):
        kb = self._mock_kb(app)
        kb.list_themes.return_value = ["ai-chips", "macro-rates"]
        kb.read_theme.side_effect = lambda s: f"Content for {s}"

        resp = client.get("/api/kb/themes")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["slug"] == "ai-chips"
        app.dependency_overrides.clear()

    def test_get_theme(self, app, client):
        kb = self._mock_kb(app)
        kb.read_theme.return_value = "# AI Chips\n\nFull theme content"

        resp = client.get("/api/kb/themes/ai-chips")
        assert resp.status_code == 200
        assert resp.json()["content"] == "# AI Chips\n\nFull theme content"
        app.dependency_overrides.clear()

    def test_get_theme_not_found(self, app, client):
        kb = self._mock_kb(app)
        kb.read_theme.return_value = None

        resp = client.get("/api/kb/themes/nonexistent")
        assert resp.status_code == 404
        app.dependency_overrides.clear()

    def test_list_stocks(self, app, client):
        kb = self._mock_kb(app)
        kb.list_stocks.return_value = ["AAPL", "MSFT"]
        kb.list_stock_files.side_effect = lambda t: ["latest_report", "predictions"]

        resp = client.get("/api/kb/stocks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["ticker"] == "AAPL"
        assert "latest_report" in data[0]["files"]
        app.dependency_overrides.clear()

    def test_core_mind(self, app, client):
        kb = self._mock_kb(app)
        kb.read_core_mind.return_value = "Agent worldview text"

        resp = client.get("/api/kb/core-mind")
        assert resp.status_code == 200
        assert resp.json()["content"] == "Agent worldview text"
        app.dependency_overrides.clear()

    def test_inbox_stats(self, app, client):
        kb = self._mock_kb(app)
        kb.list_unread.return_value = ["a.md", "b.md"]
        kb.list_read.return_value = ["c.md"]

        resp = client.get("/api/kb/inbox")
        assert resp.status_code == 200
        data = resp.json()
        assert data["unread"] == 2
        assert data["read"] == 1
        app.dependency_overrides.clear()


# --- Config Tests ---

class TestConfig:
    def test_watchlist_admin_only(self, client):
        resp = client.get("/api/config/watchlist")
        assert resp.status_code == 404  # visitor gets 404

    def test_watchlist_admin(self, admin_client, tmp_path, monkeypatch):
        monkeypatch.setattr("src.api.routers.config._WATCHLIST_PATH", tmp_path / "watchlist.yaml")
        resp = admin_client.get("/api/config/watchlist")
        assert resp.status_code == 200
        assert resp.json() == {"categories": {}}

    def test_update_watchlist(self, admin_client, tmp_path, monkeypatch):
        wl_path = tmp_path / "watchlist.yaml"
        monkeypatch.setattr("src.api.routers.config._WATCHLIST_PATH", wl_path)

        resp = admin_client.put(
            "/api/config/watchlist",
            json={"categories": {"indices": ["SPY", "QQQ"]}},
        )
        assert resp.status_code == 200
        # Verify file was written
        import yaml
        data = yaml.safe_load(wl_path.read_text())
        assert data["indices"] == ["SPY", "QQQ"]

    @patch("src.api.routers.config.submit_refresh", new_callable=AsyncMock)
    def test_refresh_sources(self, mock_refresh, admin_client):
        mock_refresh.return_value = "refresh_exec_123"
        resp = admin_client.post("/api/config/sources/refresh")
        assert resp.status_code == 200
        assert resp.json()["exec_id"] == "refresh_exec_123"


# --- SSE Tests ---

class TestSSE:
    def test_should_send_admin_sees_all(self):
        from src.api.routers.events import _should_send

        line = json.dumps({"event": "agent.tool_call.start", "data": {}})
        assert _should_send(line, "admin") is True

    def test_should_send_visitor_sees_tool_calls(self):
        from src.api.routers.events import _should_send

        line = json.dumps({"event": "agent.tool_call.start", "data": {}})
        assert _should_send(line, "visitor") is True

    def test_should_send_visitor_sees_pipeline_events(self):
        from src.api.routers.events import _should_send

        line = json.dumps({"event": "specialist.fundamental.start", "data": {}})
        assert _should_send(line, "visitor") is True

    def test_should_send_visitor_sees_analysis_end(self):
        from src.api.routers.events import _should_send

        line = json.dumps({"event": "analysis.end", "data": {}})
        assert _should_send(line, "visitor") is True

    def test_should_send_malformed_json(self):
        from src.api.routers.events import _should_send

        assert _should_send("not json", "visitor") is True


# --- Security Tests ---

class TestSecurity:
    def test_path_traversal_dots(self, client):
        # exec_id with ".." is rejected by regex
        resp = client.get("/api/analysis/..%2F..%2Fetc")
        # FastAPI may 404 (router doesn't match %2F) or 400 (our regex)
        assert resp.status_code in (400, 404, 422)

    def test_path_traversal_special_chars(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("src.api.routers.analysis.LOGS_DIR", tmp_path)
        # exec_id with special chars rejected by regex
        resp = client.get("/api/analysis/exec%23id%26test")
        assert resp.status_code == 400

    def test_path_traversal_events_invalid(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("src.api.routers.events.LOGS_DIR", tmp_path)
        resp = client.get("/api/events/bad!exec@id")
        assert resp.status_code == 400

    def test_valid_exec_id_format(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("src.api.routers.analysis.LOGS_DIR", tmp_path)
        # Valid format but non-existent → 404 (not 400)
        resp = client.get("/api/analysis/20260516_120000_abc12345")
        assert resp.status_code == 404


# --- Rate Limiting Test ---

class TestKBEvolution:
    """Tests for Phase 5E Knowledge Evolution endpoints."""

    def _mock_kb(self, app, **overrides):
        from unittest.mock import MagicMock
        from src.api.dependencies import get_kb

        kb = MagicMock()
        for k, v in overrides.items():
            setattr(kb, k, v if callable(v) else MagicMock(return_value=v))
        app.dependency_overrides[get_kb] = lambda: kb
        return kb

    def test_core_mind_history_empty(self, app, client):
        """No snapshots initially -> returns empty list."""
        kb = self._mock_kb(app)
        kb.list_core_mind_snapshots.return_value = []

        resp = client.get("/api/kb/core-mind/history")
        assert resp.status_code == 200
        assert resp.json() == {"snapshots": []}
        app.dependency_overrides.clear()

    def test_core_mind_snapshot_not_found(self, app, client):
        """404 for valid format but non-existent snapshot."""
        kb = self._mock_kb(app)
        kb.read_core_mind_snapshot.return_value = None

        resp = client.get("/api/kb/core-mind/snapshot/2026-05-16_0a76f4a2")
        assert resp.status_code == 404
        app.dependency_overrides.clear()

    def test_core_mind_snapshot_invalid_format(self, app, client):
        """400 for invalid snapshot_id format."""
        kb = self._mock_kb(app)
        resp = client.get("/api/kb/core-mind/snapshot/bad-id")
        assert resp.status_code == 400
        app.dependency_overrides.clear()

    def test_core_mind_snapshot_roundtrip(self, app, client):
        """Create a snapshot, then GET it via the API."""
        kb = self._mock_kb(app)
        kb.list_core_mind_snapshots.return_value = [
            {"id": "2026-05-16_0a76f4a2", "date": "2026-05-16", "exec_id_short": "0a76f4a2", "char_count": 100}
        ]
        kb.read_core_mind_snapshot.return_value = "# Core Mind Snapshot"

        # Verify list endpoint
        resp = client.get("/api/kb/core-mind/history")
        assert resp.status_code == 200
        snapshots = resp.json()["snapshots"]
        assert len(snapshots) == 1
        assert snapshots[0]["id"] == "2026-05-16_0a76f4a2"

        # Verify read endpoint
        resp = client.get("/api/kb/core-mind/snapshot/2026-05-16_0a76f4a2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "2026-05-16_0a76f4a2"
        assert data["content"] == "# Core Mind Snapshot"
        app.dependency_overrides.clear()

    def test_kb_graph_structure(self, app, client):
        """Returns nodes and edges with correct types."""
        kb = self._mock_kb(app)
        kb.read_core_mind.return_value = "Focus on ai-chips theme and copper."
        kb.list_themes.return_value = ["ai-chips"]
        kb.read_theme.return_value = "# AI Chips\nNVDA is leading."
        kb.list_stocks.return_value = ["NVDA"]
        kb.list_events.return_value = ["tariff-shock"]
        kb.read_event.return_value = "# Tariff Shock\nEvent content."

        resp = client.get("/api/kb/graph")
        assert resp.status_code == 200
        data = resp.json()

        # Should have 4 nodes: core_mind, 1 theme, 1 stock, 1 event
        assert len(data["nodes"]) == 4
        node_types = {n["type"] for n in data["nodes"]}
        assert node_types == {"core", "theme", "stock", "event"}

        # Check core_mind node
        core_node = next(n for n in data["nodes"] if n["type"] == "core")
        assert core_node["id"] == "core_mind"
        assert core_node["chars"] > 0

        # Theme node
        theme_node = next(n for n in data["nodes"] if n["type"] == "theme")
        assert theme_node["id"] == "theme:ai-chips"

        # Should have edges: core_mind -> ai-chips (slug in core_mind), ai-chips -> NVDA
        assert len(data["edges"]) >= 2
        edge_pairs = [(e["source"], e["target"]) for e in data["edges"]]
        assert ("core_mind", "theme:ai-chips") in edge_pairs
        assert ("theme:ai-chips", "stock:NVDA") in edge_pairs
        app.dependency_overrides.clear()

    def test_evolution_timeline(self, app, client, tmp_path):
        """Mock events file, verify aggregation."""
        kb = self._mock_kb(app)
        # Create a temporary pipeline_events.jsonl
        events_file = tmp_path / "meta" / "pipeline_events.jsonl"
        events_file.parent.mkdir(parents=True)
        events_file.write_text(
            '{"ts": "2026-05-15T10:00:00Z", "event": "digest.session_end", "data": {"items_processed": 5}}\n'
            '{"ts": "2026-05-15T11:00:00Z", "event": "kb.write", "data": {}}\n'
            '{"ts": "2026-05-15T12:00:00Z", "event": "kb.edit", "data": {}}\n'
            '{"ts": "2026-05-16T09:00:00Z", "event": "analysis.end", "data": {"success": true}}\n'
            '{"ts": "2026-05-16T10:00:00Z", "event": "kb.core_mind_updated", "data": {}}\n'
        )
        kb.data_root = tmp_path

        resp = client.get("/api/kb/evolution")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["daily"]) == 2
        day1 = data["daily"][0]
        assert day1["date"] == "2026-05-15"
        assert day1["articles_ingested"] == 5
        assert day1["kb_writes"] == 2
        assert day1["digests"] == 1

        day2 = data["daily"][1]
        assert day2["date"] == "2026-05-16"
        assert day2["analyses"] == 1
        assert day2["kb_writes"] == 1

        # Cumulative
        assert len(data["cumulative"]) == 2
        assert data["cumulative"][1]["articles"] == 5
        assert data["cumulative"][1]["kb_writes"] == 3
        assert data["cumulative"][1]["analyses"] == 1
        app.dependency_overrides.clear()

    def test_evolution_timeline_no_events(self, app, client, tmp_path):
        """Empty result when no events file exists."""
        kb = self._mock_kb(app)
        kb.data_root = tmp_path  # no pipeline_events.jsonl

        resp = client.get("/api/kb/evolution")
        assert resp.status_code == 200
        data = resp.json()
        assert data["daily"] == []
        assert data["cumulative"] == []
        app.dependency_overrides.clear()

    def test_status_enhanced(self, app, client, tmp_path):
        """Verify day_n, total_articles, total_events, inbox fields are present."""
        from unittest.mock import MagicMock
        from src.api.dependencies import get_kb

        kb = MagicMock()
        kb.list_themes.return_value = ["tech"]
        kb.list_stocks.return_value = ["AAPL"]
        kb.list_events.return_value = ["tariff-shock"]
        kb.list_unread.return_value = ["a.md"]
        kb.list_read.return_value = ["b.md", "c.md"]
        kb.read_core_mind.return_value = "Test core mind content"
        kb.get_last_updated.return_value = {}

        # Set up a pipeline_events.jsonl for day_n calculation
        data_dir = tmp_path / "data"
        events_file = data_dir / "meta" / "pipeline_events.jsonl"
        events_file.parent.mkdir(parents=True)
        events_file.write_text(
            '{"ts": "2026-05-10T10:00:00Z", "event": "source.refresh_start"}\n'
        )
        kb.root = tmp_path / "firn"
        kb.data_root = data_dir

        app.dependency_overrides[get_kb] = lambda: kb

        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_themes"] == 1
        assert data["total_stocks"] == 1
        assert data["total_events"] == 1
        assert data["total_articles"] == 3
        assert data["core_mind_chars"] == len("Test core mind content")
        assert data["library_unread"] == 1
        assert data["library_read"] == 2
        assert data["day_n"] >= 1  # At least 1 day since 2026-05-10
        assert "llm_provider" in data  # Existing field preserved
        app.dependency_overrides.clear()


class TestSnapshotUnit:
    """Unit tests for KnowledgeBase snapshot mechanism."""

    def test_snapshot_core_mind_creates_file(self, tmp_path):
        """Test that snapshot_core_mind creates snapshot file and index."""
        from src.knowledge_base.kb_api import KnowledgeBase

        kb = KnowledgeBase(kb_root=tmp_path)
        kb.ensure_structure()

        # Write initial core_mind
        kb.write_core_mind("# My Worldview\n\nTest content here.")

        # Take snapshot
        snapshot_id = kb.snapshot_core_mind("abcdef1234567890")
        assert snapshot_id is not None
        assert snapshot_id.endswith("_abcdef12")

        # Verify file exists
        snapshot_file = tmp_path / "notebook" / "core_mind_history" / f"{snapshot_id}.md"
        assert snapshot_file.is_file()
        assert snapshot_file.read_text() == "# My Worldview\n\nTest content here."

        # Verify index
        index_file = tmp_path / "notebook" / "core_mind_history" / "index.json"
        assert index_file.is_file()
        index = json.loads(index_file.read_text())
        assert len(index) == 1
        assert index[0]["id"] == snapshot_id
        assert index[0]["exec_id_short"] == "abcdef12"
        assert index[0]["char_count"] == len("# My Worldview\n\nTest content here.")

    def test_snapshot_core_mind_no_core(self, tmp_path):
        """snapshot_core_mind returns None if core_mind.md doesn't exist."""
        from src.knowledge_base.kb_api import KnowledgeBase

        kb = KnowledgeBase(kb_root=tmp_path)
        result = kb.snapshot_core_mind("test12345678")
        assert result is None

    def test_list_core_mind_snapshots_empty(self, tmp_path):
        """Returns empty list when no snapshots exist."""
        from src.knowledge_base.kb_api import KnowledgeBase

        kb = KnowledgeBase(kb_root=tmp_path)
        assert kb.list_core_mind_snapshots() == []

    def test_read_core_mind_snapshot(self, tmp_path):
        """Read a specific snapshot after creation."""
        from src.knowledge_base.kb_api import KnowledgeBase

        kb = KnowledgeBase(kb_root=tmp_path)
        kb.ensure_structure()
        kb.write_core_mind("version 1")
        sid1 = kb.snapshot_core_mind("aaaa111122223333")

        kb.write_core_mind("version 2")
        sid2 = kb.snapshot_core_mind("bbbb444455556666")

        assert kb.read_core_mind_snapshot(sid1) == "version 1"
        assert kb.read_core_mind_snapshot(sid2) == "version 2"

        # Non-existent snapshot
        assert kb.read_core_mind_snapshot("2099-01-01_deadbeef") is None

    def test_multiple_snapshots_index(self, tmp_path):
        """Multiple snapshots accumulate in index.json."""
        from src.knowledge_base.kb_api import KnowledgeBase

        kb = KnowledgeBase(kb_root=tmp_path)
        kb.ensure_structure()
        kb.write_core_mind("v1")
        kb.snapshot_core_mind("exec_aaa11111")
        kb.write_core_mind("v2 longer")
        kb.snapshot_core_mind("exec_bbb22222")

        snapshots = kb.list_core_mind_snapshots()
        assert len(snapshots) == 2
        assert snapshots[0]["char_count"] == 2
        assert snapshots[1]["char_count"] == 9


class TestRateLimit:
    def test_rate_limit_not_triggered_for_normal_use(self, client):
        # A few requests should be fine
        for _ in range(5):
            resp = client.get("/api/health")
            assert resp.status_code == 200
