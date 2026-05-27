"""Analysis routes: submit, list, detail, report, trace, audit."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

_EXEC_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

from src.api import LOGS_DIR, KB_ROOT
from src.api.dependencies import (
    CurrentUser,
    check_visitor_analysis_budget,
    get_current_user,
    rate_limit,
)
from src.api.models import AuditResult, Citation, SubmitResponse
from src.api.services import submit_analysis, submit_audit

router = APIRouter(dependencies=[Depends(rate_limit)])


# --- Request models ---

class AnalysisRequest(BaseModel):
    ticker: str
    query: str | None = None


# --- Response models (lightweight for list) ---

class AnalysisSummary(BaseModel):
    exec_id: str
    ticker: str | None = None
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    has_audit: bool = False


class AnalysisDetail(BaseModel):
    exec_id: str
    ticker: str | None = None
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    report: str | None = None
    report_length: int | None = None
    agent_timings: dict[str, float] = {}
    token_usage: dict[str, int] = {}
    has_audit: bool = False


# --- Endpoints ---

@router.post("/analysis", response_model=SubmitResponse)
async def submit(
    body: AnalysisRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    check_visitor_analysis_budget(request, user)
    exec_id = await submit_analysis(body.ticker, body.query)
    return SubmitResponse(exec_id=exec_id)


@router.get("/analysis", response_model=list[AnalysisSummary])
async def list_analyses(
    limit: int = 20,
    user: CurrentUser = Depends(get_current_user),
):
    """List analysis executions, most recent first."""
    results = []
    if not LOGS_DIR.exists():
        return results

    dirs = sorted(
        (d for d in LOGS_DIR.iterdir() if d.is_dir()),
        key=lambda d: d.name,
        reverse=True,
    )

    for exec_dir in dirs:
        if not _is_analysis(exec_dir):
            continue
        info = _read_exec_info(exec_dir)
        if info is None:
            continue
        results.append(
            AnalysisSummary(
                exec_id=exec_dir.name,
                ticker=_extract_ticker(exec_dir, info),
                status=_derive_status(exec_dir.name, info),
                started_at=info.get("start_time"),
                completed_at=info.get("end_time"),
                has_audit=(exec_dir / "audit" / "citations.json").exists(),
            )
        )
        if len(results) >= limit:
            break

    return results


@router.get("/analysis/{exec_id}", response_model=AnalysisDetail)
async def get_analysis(exec_id: str, user: CurrentUser = Depends(get_current_user)):
    if not _EXEC_ID_RE.match(exec_id):
        raise HTTPException(status_code=400, detail="Invalid exec_id format")
    exec_dir = LOGS_DIR / exec_id
    if not exec_dir.exists():
        raise HTTPException(status_code=404, detail="Execution not found")

    info = _read_exec_info(exec_dir) or {}
    report = _find_report(exec_dir)

    return AnalysisDetail(
        exec_id=exec_id,
        ticker=_extract_ticker(exec_dir, info),
        status=_derive_status(exec_id, info),
        started_at=info.get("start_time"),
        completed_at=info.get("end_time"),
        report=report,
        report_length=len(report) if report else None,
        agent_timings=_read_agent_timings(exec_dir),
        token_usage=_read_token_usage(exec_dir),
        has_audit=(exec_dir / "audit" / "citations.json").exists(),
    )


@router.get("/analysis/{exec_id}/report")
async def get_report(exec_id: str, user: CurrentUser = Depends(get_current_user)):
    if not _EXEC_ID_RE.match(exec_id):
        raise HTTPException(status_code=400, detail="Invalid exec_id format")
    exec_dir = LOGS_DIR / exec_id
    if not exec_dir.exists():
        raise HTTPException(status_code=404, detail="Execution not found")
    report = _find_report(exec_dir)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"report_markdown": report}


@router.get("/analysis/{exec_id}/tool-calls")
async def get_tool_calls(exec_id: str, user: CurrentUser = Depends(get_current_user)):
    """Return tool call data grouped by agent name (visitor-accessible)."""
    if not _EXEC_ID_RE.match(exec_id):
        raise HTTPException(status_code=400, detail="Invalid exec_id format")
    exec_dir = LOGS_DIR / exec_id
    if not exec_dir.exists():
        raise HTTPException(status_code=404, detail="Execution not found")

    result: dict[str, list] = {}
    for tc_file in sorted(exec_dir.glob("**/*tool_calls*.json")):
        try:
            data = json.loads(tc_file.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            continue
        agent_name = data.get("agent_name", tc_file.stem.replace("_tool_calls", ""))
        calls = data.get("tool_calls", [])
        if agent_name in result:
            result[agent_name].extend(calls)
        else:
            result[agent_name] = list(calls)
    # Sort each agent's calls by start_time to match SSE start order
    for agent_name in result:
        result[agent_name].sort(key=lambda c: c.get("start_time", 0))
    return result


@router.get("/analysis/{exec_id}/trace")
async def get_trace(exec_id: str, user: CurrentUser = Depends(get_current_user)):
    """Return structured trace data (prompts, tool calls, react steps)."""
    if not _EXEC_ID_RE.match(exec_id):
        raise HTTPException(status_code=400, detail="Invalid exec_id format")
    exec_dir = LOGS_DIR / exec_id
    if not exec_dir.exists():
        raise HTTPException(status_code=404, detail="Execution not found")

    trace_dir = exec_dir / "trace"
    trace_data: dict = {"prompts": {}, "react_steps": {}, "tool_calls": {}, "verification": {}}

    if not trace_dir.exists():
        return trace_data

    # Prompts
    prompts_dir = trace_dir / "prompts"
    if prompts_dir.exists():
        for f in prompts_dir.iterdir():
            if f.suffix == ".txt":
                trace_data["prompts"][f.stem] = f.read_text(errors="replace")

    # React steps
    steps_dir = trace_dir / "react_steps"
    if steps_dir.exists():
        for f in steps_dir.iterdir():
            if f.suffix == ".jsonl":
                lines = f.read_text(errors="replace").strip().splitlines()
                trace_data["react_steps"][f.stem] = [
                    json.loads(l) for l in lines if l.strip()
                ]

    # Tool calls (at exec_dir root level too)
    for tc_file in exec_dir.glob("**/tool_calls*.json"):
        trace_data["tool_calls"][tc_file.stem] = json.loads(
            tc_file.read_text(errors="replace")
        )

    # Verification sidecars
    verif_dir = trace_dir / "verification"
    if verif_dir.exists():
        for f in verif_dir.iterdir():
            if f.suffix == ".json":
                trace_data["verification"][f.stem] = json.loads(
                    f.read_text(errors="replace")
                )

    return trace_data


@router.get("/analysis/{exec_id}/audit", response_model=AuditResult | None)
async def get_audit(exec_id: str, user: CurrentUser = Depends(get_current_user)):
    if not _EXEC_ID_RE.match(exec_id):
        raise HTTPException(status_code=400, detail="Invalid exec_id format")
    exec_dir = LOGS_DIR / exec_id
    audit_dir = exec_dir / "audit"

    citations_path = audit_dir / "citations.json"
    report_path = audit_dir / "audit_report.md"

    if not citations_path.exists():
        raise HTTPException(status_code=404, detail="Audit not found")

    raw = json.loads(citations_path.read_text())
    citations_raw = raw.get("citations", [])
    summary = raw.get("summary", {})

    # v3 summary has {total, verdicts: {...}}; extract verdicts dict
    verdicts = summary.get("verdicts", {})
    if not verdicts:
        # Fallback: flat summary with numeric values (legacy)
        for k, v in summary.items():
            if isinstance(v, (int, float)) and k not in ("total",):
                verdicts[k.replace("_", "-")] = int(v)

    citations = [
        Citation(
            id=i + 1,
            claim=c.get("claim", ""),
            claim_in_report=c.get("claim_in_report", ""),
            verdict=c.get("verdict", "llm-inferred"),
            source=c.get("source", {}),
            specialist=c.get("specialist"),
            evidence=c.get("evidence"),
            r1_match=c.get("r1_match"),
        )
        for i, c in enumerate(citations_raw)
    ]

    audit_report = report_path.read_text(errors="replace") if report_path.exists() else ""

    # Duration from execution info
    duration = None
    info = _read_exec_info(exec_dir)
    if info and info.get("start_time") and info.get("end_time"):
        try:
            from datetime import datetime

            start = datetime.fromisoformat(info["start_time"])
            end = datetime.fromisoformat(info["end_time"])
            duration = (end - start).total_seconds()
        except (ValueError, TypeError):
            pass

    return AuditResult(
        total_claims=len(citations),
        verdicts=verdicts,
        citations=citations,
        audit_report=audit_report,
        duration_seconds=duration,
    )


@router.post("/analysis/{exec_id}/audit", response_model=SubmitResponse)
async def trigger_audit(exec_id: str, user: CurrentUser = Depends(get_current_user)):
    if not _EXEC_ID_RE.match(exec_id):
        raise HTTPException(status_code=400, detail="Invalid exec_id format")
    exec_dir = LOGS_DIR / exec_id
    if not exec_dir.exists():
        raise HTTPException(status_code=404, detail="Execution not found")
    audit_exec_id = await submit_audit(exec_id)
    return SubmitResponse(exec_id=audit_exec_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_analysis(exec_dir: Path) -> bool:
    return (exec_dir / "agents" / "fundamental.json").exists()


def _read_exec_info(exec_dir: Path) -> dict | None:
    info_path = exec_dir / "execution_info.json"
    if not info_path.exists():
        return None
    try:
        return json.loads(info_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _derive_status(exec_id: str, info: dict) -> str:
    from src.api.services import get_execution_status as mem_status

    mem = mem_status(exec_id)
    if mem == "running":
        return "running"
    if info.get("end_time"):
        return "complete" if info.get("success", True) else "failed"
    # CLI-triggered tasks: check if events.jsonl was recently modified
    events_path = LOGS_DIR / exec_id / "events.jsonl"
    if events_path.exists():
        age = time.time() - events_path.stat().st_mtime
        if age < 300:  # 5 minutes
            return "running"
    # No end_time, not in memory, no recent activity → crashed or interrupted
    return "failed"


def _extract_ticker(exec_dir: Path, info: dict | None = None) -> str | None:
    """Extract ticker from execution data (multiple strategies)."""
    # Strategy 1: ticker saved directly in execution_info.json
    if info and info.get("ticker"):
        return info["ticker"]

    # Strategy 2: Parse from final_report_info.json report_path
    info_path = exec_dir / "reports" / "final_report_info.json"
    if info_path.exists():
        try:
            data = json.loads(info_path.read_text())
            rp = data.get("report_path", "")
            parts = rp.replace("\\", "/").split("/")
            # Pattern: .../stocks/AAPL/...
            if "stocks" in parts:
                idx = parts.index("stocks")
                if idx + 1 < len(parts):
                    return parts[idx + 1]
            # Pattern: report_AAPL_20260514_195626.md
            filename = parts[-1] if parts else ""
            if filename.startswith("report_"):
                # report_AAPL_20260514_195626.md → AAPL
                name_parts = filename.replace(".md", "").split("_")
                if len(name_parts) >= 2:
                    return name_parts[1]
        except (json.JSONDecodeError, OSError):
            pass

    # Strategy 3: Parse from agents/fundamental.json input_data
    fund_path = exec_dir / "agents" / "fundamental.json"
    if fund_path.exists():
        try:
            data = json.loads(fund_path.read_text())
            inp = data.get("input_data", {})
            if isinstance(inp, dict) and inp.get("ticker"):
                return inp["ticker"]
        except (json.JSONDecodeError, OSError):
            pass

    # Strategy 4: Parse from events.jsonl (first analysis.core_start event)
    events_path = exec_dir / "events.jsonl"
    if events_path.exists():
        try:
            for line in events_path.open():
                if not line.strip():
                    continue
                evt = json.loads(line)
                if evt.get("event") == "analysis.core_start":
                    t = evt.get("data", {}).get("ticker")
                    if t:
                        return t
        except (json.JSONDecodeError, OSError):
            pass

    return None


def _find_report(exec_dir: Path) -> str | None:
    """Find analysis report — check exec dir first, then KB path, then KB by ticker."""
    # Direct report in exec dir
    direct = exec_dir / "reports" / "final_report.md"
    if direct.exists():
        text = direct.read_text(errors="replace")
        if text.strip():
            return text

    # KB path from final_report_info.json
    info_path = exec_dir / "reports" / "final_report_info.json"
    if info_path.exists():
        try:
            data = json.loads(info_path.read_text())
            rp = data.get("report_path", "")
            if rp:
                kb_path = Path(rp)
                if not kb_path.is_absolute():
                    from src.api import PROJECT_ROOT

                    kb_path = PROJECT_ROOT / kb_path
                if kb_path.exists():
                    return kb_path.read_text(errors="replace")
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback: find latest_report.md in KB by ticker
    info = _read_exec_info(exec_dir)
    ticker = _extract_ticker(exec_dir, info)
    if ticker:
        kb_report = KB_ROOT / "notebook" / "stocks" / ticker / "latest_report.md"
        if kb_report.exists():
            return kb_report.read_text(errors="replace")

    return None


def _read_agent_timings(exec_dir: Path) -> dict[str, float]:
    agents_dir = exec_dir / "agents"
    if not agents_dir.exists():
        return {}
    timings = {}
    for f in agents_dir.iterdir():
        if f.suffix == ".json":
            try:
                data = json.loads(f.read_text())
                if "execution_time" in data:
                    timings[f.stem] = data["execution_time"]
            except (json.JSONDecodeError, OSError):
                pass
    return timings


def _read_token_usage(exec_dir: Path) -> dict[str, int]:
    agents_dir = exec_dir / "agents"
    if not agents_dir.exists():
        return {}
    usage = {}
    for f in agents_dir.iterdir():
        if f.suffix == ".json":
            try:
                data = json.loads(f.read_text())
                tokens = data.get("token_usage", {})
                total = tokens.get("total_tokens", 0)
                if total:
                    usage[f.stem] = total
            except (json.JSONDecodeError, OSError):
                pass
    return usage
