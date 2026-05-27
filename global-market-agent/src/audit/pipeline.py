"""Audit Pipeline — CLI-facing entry point for running audits.

Usage:
    uv run python -m src --audit latest
    uv run python -m src --audit 20260516_021117_0a76f4a2
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from src.audit.agent import AuditAgent, AuditResult
from src.utils.event_log import log_event

if TYPE_CHECKING:
    from src.utils.execution_logger import ExecutionLogger

logger = logging.getLogger(__name__)

# Resolve project root once
_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # global-market-agent/
_LOGS_DIR = _PROJECT_ROOT / "logs"


async def run_audit(exec_id: str, report_path: str | None = None,
                    mode: str | None = None, *,
                    verbose: bool = True,
                    execution_logger: ExecutionLogger | None = None) -> AuditResult:
    """Run audit on a completed execution.

    Parameters
    ----------
    exec_id : str
        Execution ID (directory name) or "latest" to auto-detect.
    report_path : str | None
        Explicit path to the report file.  Auto-detected if None.
    mode : str | None
        Audit mode: "analysis", "digest", or None (auto-detect).
    """
    trace_dir = _resolve_exec_dir(exec_id, mode)
    rp = Path(report_path) if report_path else None

    # Auto-detect mode if not specified
    if mode is None:
        mode = _detect_execution_mode(trace_dir)

    # Clean old audit events from per-execution event log (prevents SSE replay duplication)
    _clean_stale_audit_events(trace_dir)

    actual_exec_id = trace_dir.name
    log_event("audit.start", stage="audit", execution_id=actual_exec_id, mode=mode)
    logger.info("Auditing execution: %s (mode=%s)", actual_exec_id, mode)
    agent = AuditAgent(trace_dir, rp, mode=mode, execution_logger=execution_logger)
    result = await agent.audit()

    # Print summary
    if verbose:
        _print_summary(result, mode)
    summary = result.citations.get("summary", {})
    total = summary.get("total", summary.get("total_claims", 0))
    log_event("audit.complete", stage="audit", execution_id=actual_exec_id,
              success=True, total_claims=total)
    return result


def _clean_stale_audit_events(trace_dir: Path) -> None:
    """Remove old audit.* events from per-execution events.jsonl.

    When audit runs multiple times on the same execution, old audit events
    accumulate.  SSE replay would then show duplicated R1/R2 animations.
    """
    events_path = trace_dir / "events.jsonl"
    if not events_path.exists():
        return
    lines = events_path.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if line.strip() and '"audit.' not in line]
    removed = len(lines) - len(kept)
    if removed > 0:
        events_path.write_text(
            "\n".join(kept) + ("\n" if kept else ""),
            encoding="utf-8",
        )
        logger.info("Cleared %d stale audit events from events.jsonl", removed)


def _resolve_exec_dir(exec_id: str, mode: str | None = None) -> Path:
    """Resolve an execution ID to a trace directory path."""
    if exec_id == "latest":
        if mode == "digest":
            return _find_latest_digest()
        return _find_latest_analysis()

    # Try exact match
    candidate = _LOGS_DIR / exec_id
    if candidate.is_dir():
        return candidate

    # Try partial match (prefix)
    matches = sorted(_LOGS_DIR.glob(f"{exec_id}*"))
    dirs = [m for m in matches if m.is_dir()]
    if len(dirs) == 1:
        return dirs[0]
    if len(dirs) > 1:
        raise ValueError(
            f"Ambiguous exec_id '{exec_id}': matches {len(dirs)} directories. "
            f"Be more specific."
        )

    raise FileNotFoundError(f"No execution directory found for '{exec_id}'")


def _find_latest_digest() -> Path:
    """Find the most recent digest execution.

    A digest run is identified by having a core_digest agent JSON or
    core_digest prompt files.
    """
    for d in sorted(_LOGS_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        # Check for digest agent
        if (d / "agents" / "core_digest.json").exists():
            return d
        # Check for digest prompts
        prompts_dir = d / "trace" / "prompts"
        if prompts_dir.exists() and any(
            f.name.startswith("core_digest") for f in prompts_dir.iterdir()
        ):
            return d

    raise FileNotFoundError(
        "No digest execution found. "
        "Run a digest first: uv run python -m src --digest"
    )


def _detect_execution_mode(trace_dir: Path) -> str:
    """Auto-detect whether an execution is analysis or digest.

    Heuristic: analysis runs have specialist prompts (fundamental_, technical_);
    digest runs have core_digest prompts.
    """
    prompts_dir = trace_dir / "trace" / "prompts"
    if not prompts_dir.exists():
        # Fall back to agents/ directory
        agents_dir = trace_dir / "agents"
        if agents_dir.exists() and (agents_dir / "core_digest.json").exists():
            return "digest"
        return "analysis"

    has_specialist = any(
        f.name.startswith(("fundamental_", "technical_", "value_"))
        for f in prompts_dir.iterdir() if f.is_file()
    )
    has_digest = any(
        f.name.startswith("core_digest")
        for f in prompts_dir.iterdir() if f.is_file()
    )

    if has_specialist:
        return "analysis"
    if has_digest:
        return "digest"
    return "analysis"


def _find_latest_analysis() -> Path:
    """Find the most recent analysis execution with trace data.

    An analysis run is identified by having:
    - trace/prompts/ with specialist prompt files
    - tools/ with tool_calls files
    """
    candidates: list[Path] = []
    for d in sorted(_LOGS_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        # Must have trace prompts
        prompts_dir = d / "trace" / "prompts"
        if not prompts_dir.exists():
            continue
        # Must have specialist prompts (not just core/digest)
        has_specialist = any(
            f.name.startswith(("fundamental_", "technical_", "value_"))
            for f in prompts_dir.iterdir()
        )
        if has_specialist:
            candidates.append(d)
            break  # Sorted newest first, take the first match

    if not candidates:
        raise FileNotFoundError(
            "No analysis execution with trace data found. "
            "Run an analysis first: uv run python -m src --ticker AAPL"
        )

    return candidates[0]


def _print_summary(result: AuditResult, mode: str = "analysis") -> None:
    """Print a brief audit summary to stdout."""
    summary = result.citations.get("summary", {})

    print(f"\n{'='*60}")
    print(f"AUDIT COMPLETE [{mode.upper()}] — {result.trace_dir.name}")
    print(f"{'='*60}")
    print(f"Duration: {result.duration_seconds:.1f}s")

    if mode == "digest":
        total = summary.get("total_writes", 0)
        print(f"Total KB writes audited: {total}")
        if total > 0:
            fa = summary.get("faithful", 0)
            pf = summary.get("partially_faithful", 0)
            em = summary.get("embellished", 0)
            mc = summary.get("miscategorized", 0)
            print(f"  Faithful:            {fa} ({fa/total*100:.0f}%)")
            if pf:
                print(f"  Partially-faithful:  {pf} ({pf/total*100:.0f}%)")
            if em:
                print(f"  Embellished:         {em} ({em/total*100:.0f}%)")
            if mc:
                print(f"  Miscategorized:      {mc} ({mc/total*100:.0f}%)")
    else:
        # v3: summary = {"total": N, "verdicts": {"verified": N, ...}}
        # v2: summary = {"total_claims": N, "tool_verified": N, ...}
        total = summary.get("total", summary.get("total_claims", 0))
        verdicts = summary.get("verdicts", {})
        is_v3 = isinstance(verdicts, dict) and verdicts
        is_v2 = summary.get("audit_version") == "v2"
        label = " (v3)" if is_v3 else (" (v2 full-chain)" if is_v2 else "")
        print(f"Total claims audited: {total}{label}")
        if total > 0:
            if is_v3:
                for v_name, count in sorted(verdicts.items(), key=lambda x: -x[1]):
                    print(f"  {v_name}: {count} ({count/total*100:.0f}%)")
            else:
                # v2 stored keys → new display labels
                dualv = summary.get("dual_verified", 0)
                tv = summary.get("tool_verified", 0)
                casv = summary.get("cascade_verified", 0)
                cv = summary.get("computation_verified", 0)
                dv = summary.get("derived_from_verified", 0)
                ks = summary.get("kb_sourced", 0)
                wv = summary.get("web_verified", 0)
                li = summary.get("llm_inferred", 0)
                verified = dualv + casv
                supported = tv + dv
                computed = cv
                if verified:
                    print(f"  Verified:             {verified} ({verified/total*100:.0f}%)")
                if supported:
                    print(f"  Supported:            {supported} ({supported/total*100:.0f}%)")
                if computed:
                    print(f"  Computed:             {computed} ({computed/total*100:.0f}%)")
                if ks:
                    print(f"  KB Sourced:           {ks} ({ks/total*100:.0f}%)")
                if wv:
                    print(f"  Web Sourced:          {wv} ({wv/total*100:.0f}%)")
                if li:
                    print(f"  Unverified:           {li} ({li/total*100:.0f}%)")
        # Show Round 1 specialist summaries for v2
        r1 = summary.get("round1_summaries")
        if r1:
            print("\n  Round 1 (Specialist Fidelity):")
            for agent_name, s in r1.items():
                tc = s.get("total_claims", 0)
                stv = s.get("tool_verified", 0)
                print(f"    {agent_name}: {tc} claims ({stv} tool-verified)")

    print(f"\nResults saved to: {result.trace_dir / 'audit'}/")
    print(f"  audit_report.md  — human-readable verification log")
    print(f"  citations.json   — structured citation data for Web UI")
    print(f"{'='*60}\n")
