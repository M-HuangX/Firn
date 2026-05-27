"""Audit Agent — independent claim verification against execution traces.

v1 (existing): Single-session, memory-based verification.
v2 (D36): Two-round full-chain audit with grep-mandatory verification.
v3 (D38): Parallel R2a + R2b evidence collection with deterministic verdict merger.
  - Round 1: Parallel specialist fidelity (4 agents) — unchanged from v2
  - Round 2a: Specialist Evidence Agent (report -> specialist outputs)
  - Round 2b: Source Evidence Agent (report -> raw tool data)
  - Merge: Deterministic program logic assigns verdicts (no LLM)

Produces:
  - audit/audit_report.md — human-readable verification log
  - audit/citations.json — structured citation data for Web UI
  - audit/specialist_citations/*.jsonl — per-specialist claims (R1)
  - audit/specialist_evidence.jsonl — R2a evidence (v3)
  - audit/source_evidence.jsonl — R2b evidence (v3)
  - audit/audit_summary.json — aggregated stats
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from src.audit.manifest import generate_analysis_manifest, generate_digest_manifest
from src.audit.prompts import (
    AUDIT_SYSTEM_PROMPT,
    AUDIT_USER_PROMPT_TEMPLATE,
    DIGEST_AUDIT_SYSTEM_PROMPT,
    DIGEST_AUDIT_USER_PROMPT_TEMPLATE,
    SPECIALIST_AUDIT_SYSTEM_PROMPT,
    SPECIALIST_AUDIT_USER_TEMPLATE,
    SPECIALIST_EVIDENCE_SYSTEM_PROMPT,
    SPECIALIST_EVIDENCE_USER_TEMPLATE,
    SOURCE_EVIDENCE_SYSTEM_PROMPT,
    SOURCE_EVIDENCE_USER_TEMPLATE,
)
from src.audit.tools import AuditToolSet
from src.audit.verdict import merge_evidence_and_verdict
from src.utils.event_log import log_event
from src.utils.llm_clients import create_llm
from src.utils.observability import AgentObserver

if TYPE_CHECKING:
    from src.utils.execution_logger import ExecutionLogger

logger = logging.getLogger(__name__)

_SPECIALISTS = ("fundamental", "technical", "value", "macro")


@dataclass
class AuditResult:
    """Result of an audit run."""

    audit_report: str  # Human-readable markdown
    citations: dict[str, Any]  # Structured JSON
    trace_dir: Path
    duration_seconds: float


class AuditAgent:
    """Independent agent that audits analysis reports against trace data.

    Parameters
    ----------
    trace_dir : Path
        Execution directory (``logs/<exec_id>/``).
    report_path : Path | None
        Path to the final report.  Auto-detected if not provided.
    mode : str
        Audit mode: ``"analysis"`` (default) or ``"digest"``.
    """

    def __init__(self, trace_dir: Path, report_path: Path | None = None,
                 mode: str = "analysis", *,
                 execution_logger: "ExecutionLogger | None" = None) -> None:
        self.trace_dir = trace_dir.resolve()
        self.mode = mode
        self.report_path = self._find_report(report_path) if mode == "analysis" else None
        self.execution_logger = execution_logger

    def _save_tool_calls(self, agent_name: str, tool_calls: list) -> None:
        """Save tool calls to audit/tool_calls/{agent_name}.json.

        Falls back to local file when execution_logger is not available
        (standalone --audit mode).
        """
        if self.execution_logger:
            self.execution_logger.log_tool_calls(agent_name, tool_calls)
        else:
            tc_dir = self.trace_dir / "audit" / "tool_calls"
            tc_dir.mkdir(parents=True, exist_ok=True)
            (tc_dir / f"{agent_name}.json").write_text(
                json.dumps(tool_calls, indent=2, ensure_ascii=False,
                           default=str),
                encoding="utf-8",
            )

    async def audit(self) -> AuditResult:
        """Run the audit pipeline."""
        if self.mode == "analysis":
            return await self._audit_v2()
        return await self._audit_v1()

    # ==================================================================
    # v2 — Full-Chain Audit (D36)
    # ==================================================================

    async def _audit_v2(self) -> AuditResult:
        """Two-round full-chain audit for analysis mode."""
        start = time.time()
        exec_id = self.trace_dir.name

        # Check prerequisite: specialist outputs exist
        outputs_dir = self.trace_dir / "trace" / "specialist_outputs"
        available_specialists = []
        for s in _SPECIALISTS:
            if (outputs_dir / f"{s}_output.md").exists():
                available_specialists.append(s)

        if not available_specialists:
            logger.warning("No specialist outputs found — falling back to v1 audit")
            return await self._audit_v1()

        logger.info("Starting v2 audit: %d specialists, exec=%s",
                     len(available_specialists), exec_id)

        # Prepare audit directory — clear stale JSONL from previous runs
        audit_dir = self.trace_dir / "audit"
        audit_dir.mkdir(exist_ok=True)
        (audit_dir / "specialist_citations").mkdir(exist_ok=True)
        for stale in audit_dir.glob("*.jsonl"):
            stale.unlink()
        for stale in (audit_dir / "specialist_citations").glob("*.jsonl"):
            stale.unlink()

        # ---- Round 1: Parallel Specialist Fidelity ----
        log_event("audit.round1.start", stage="audit", execution_id=exec_id,
                  specialists=available_specialists)

        round1_tasks = []
        for agent_name in available_specialists:
            round1_tasks.append(self._run_specialist_audit(agent_name))

        round1_results = await asyncio.gather(*round1_tasks, return_exceptions=True)

        # Collect Round 1 summaries
        round1_summaries: dict[str, dict] = {}
        for agent_name, result in zip(available_specialists, round1_results):
            if isinstance(result, Exception):
                logger.error("Round 1 failed for %s: %s", agent_name, result)
                round1_summaries[agent_name] = {
                    "error": str(result), "total_claims": 0,
                }
            else:
                round1_summaries[agent_name] = result

        log_event("audit.round1.end", stage="audit", execution_id=exec_id,
                  summaries=round1_summaries)
        logger.info("Round 1 complete: %s",
                     {k: v.get("total_claims", 0) for k, v in round1_summaries.items()})

        # ---- Round 2: Parallel Evidence Collection ----
        r1_claims = self._load_all_r1_claims()
        r1_claims_text = self._format_r1_claims_for_specialist_agent(r1_claims)

        log_event("audit.round2.start", stage="audit", execution_id=exec_id)

        r2a_task = self._run_specialist_evidence_agent(r1_claims_text)
        r2b_task = self._run_source_evidence_agent()

        r2_results = await asyncio.gather(r2a_task, r2b_task, return_exceptions=True)

        r2a_data = r2_results[0] if not isinstance(r2_results[0], Exception) else {"error": str(r2_results[0]), "entries": []}
        r2b_data = r2_results[1] if not isinstance(r2_results[1], Exception) else {"error": str(r2_results[1]), "entries": []}

        if isinstance(r2_results[0], Exception):
            logger.error("R2a (specialist evidence) failed: %s", r2_results[0])
        if isinstance(r2_results[1], Exception):
            logger.error("R2b (source evidence) failed: %s", r2_results[1])

        log_event("audit.round2.end", stage="audit", execution_id=exec_id,
                  specialist_evidence=len(r2a_data.get("entries", [])),
                  source_evidence=len(r2b_data.get("entries", [])))

        # ---- Merge + Verdict (deterministic program logic) ----
        citations = merge_evidence_and_verdict(
            r2a_data.get("entries", []),
            r2b_data.get("entries", []),
            r1_claims,
        )

        duration = time.time() - start

        # Emit per-citation events (post-merge verdicts for frontend mini-log).
        # These fire at once after merge — real-time R2 animation is driven by
        # audit.evidence_recorded events emitted during R2a/R2b agent execution.
        for c in citations.get("citations", []):
            specialist = c.get("specialist", {})
            source = c.get("source", {})
            log_event("audit.citation_recorded", stage="audit",
                      execution_id=exec_id,
                      claim_id=c.get("id", 0),
                      claim=c.get("claim", "")[:100],
                      verdict=c.get("verdict", ""),
                      source_agent=specialist.get("agent", source.get("agent", "")),
                      source_index=source.get("index", -1))
        audit_report = self._generate_audit_report_v3(
            round1_summaries, r2a_data, r2b_data, citations, duration)
        self._save_results(audit_report, citations)

        # Save structured summary
        summary_path = audit_dir / "audit_summary.json"
        r1_slim = {k: {kk: vv for kk, vv in v.items() if kk != "claims"}
                   for k, v in round1_summaries.items()}
        summary_path.write_text(
            json.dumps({"round1": r1_slim,
                        "round2_specialist": len(r2a_data.get("entries", [])),
                        "round2_source": len(r2b_data.get("entries", [])),
                        "verdicts": citations.get("summary", {}),
                        "duration_seconds": round(duration, 1)},
                       indent=2, ensure_ascii=False),
            encoding="utf-8")

        return AuditResult(
            audit_report=audit_report,
            citations=citations,
            trace_dir=self.trace_dir,
            duration_seconds=duration,
        )

    async def _run_specialist_audit(self, agent_name: str) -> dict:
        """Run Round 1 audit for a single specialist."""
        exec_id = self.trace_dir.name

        log_event("audit.round1.specialist_start", stage="audit",
                  execution_id=exec_id, agent=agent_name)

        toolset = AuditToolSet(self.trace_dir, self.report_path,
                               event_emitter=log_event)
        tools = toolset.get_round1_tools()

        system_prompt = SPECIALIST_AUDIT_SYSTEM_PROMPT
        user_prompt = SPECIALIST_AUDIT_USER_TEMPLATE.format(agent=agent_name)

        llm = create_llm(temperature=0.1, max_tokens=8192)
        agent = create_react_agent(llm, tools, prompt=system_prompt)

        max_rounds = 400
        recursion_limit = 4 * max_rounds + 1

        observer = AgentObserver(
            f"audit_r1_{agent_name}",
            sid="", execution_id=exec_id, stage="audit",
        )

        if self.execution_logger:
            self.execution_logger.log_trace_prompt(
                f"audit_r1_{agent_name}", "system", system_prompt)
            self.execution_logger.log_trace_prompt(
                f"audit_r1_{agent_name}", "user", user_prompt)

        logger.info("Round 1: Starting %s audit (max_rounds=%d)", agent_name, max_rounds)
        try:
            result = await asyncio.wait_for(
                agent.ainvoke(
                    {"messages": [HumanMessage(content=user_prompt)]},
                    config={"recursion_limit": recursion_limit,
                            "callbacks": [observer]},
                ),
                timeout=900,  # 15 minutes per specialist
            )
        except asyncio.TimeoutError:
            logger.error("Round 1 %s timed out", agent_name)
            self._save_tool_calls(
                f"audit_r1_{agent_name}", observer.get_tool_calls())
            toolset.save_enforcement_log()
            log_event("audit.round1.specialist_end", stage="audit",
                      execution_id=exec_id, agent=agent_name,
                      error="timeout")
            return {"error": "timeout", "total_claims": 0}
        except Exception as e:
            logger.error("Round 1 %s failed: %s", agent_name, e)
            toolset.save_enforcement_log()
            log_event("audit.round1.specialist_end", stage="audit",
                      execution_id=exec_id, agent=agent_name,
                      error=str(e))
            raise

        # Log observability data
        self._save_tool_calls(
            f"audit_r1_{agent_name}", observer.get_tool_calls())
        toolset.save_enforcement_log()
        if toolset.enforcement_count:
            logger.info("R1 %s grep enforcement: %d rejections",
                        agent_name, toolset.enforcement_count)
        if self.execution_logger:
            self.execution_logger.log_trace_steps(
                f"audit_r1_{agent_name}", observer.get_react_steps())
            self.execution_logger.log_token_usage(
                f"audit_r1_{agent_name}", observer.get_token_usage())

        # Read back the JSONL to produce summary
        summary = self._read_specialist_citations(agent_name)

        log_event("audit.round1.specialist_end", stage="audit",
                  execution_id=exec_id, agent=agent_name,
                  total_claims=summary.get("total_claims", 0),
                  tool_verified=summary.get("tool_verified", 0),
                  derived=summary.get("derived_from_verified", 0),
                  misread=summary.get("misread", 0),
                  inferred=summary.get("llm_inferred", 0))

        logger.info("Round 1 %s: %d claims", agent_name, summary.get("total_claims", 0))
        return summary

    def _read_specialist_citations(self, agent_name: str) -> dict:
        """Read specialist_citations/{agent}.jsonl and produce a summary."""
        jsonl_path = self.trace_dir / "audit" / "specialist_citations" / f"{agent_name}.jsonl"
        if not jsonl_path.exists():
            return {"total_claims": 0}

        claims = []
        for line in jsonl_path.read_text().strip().split("\n"):
            if line.strip():
                try:
                    claims.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        verdict_counts: dict[str, int] = {}
        for c in claims:
            v = c.get("verdict", "unknown").replace("-", "_")
            verdict_counts[v] = verdict_counts.get(v, 0) + 1

        return {
            "total_claims": len(claims),
            **verdict_counts,
            "claims": claims,  # full data for Round 2 reference
        }

    # ------------------------------------------------------------------
    # R2a + R2b: Parallel Evidence Collection (v3)
    # ------------------------------------------------------------------

    def _load_all_r1_claims(self) -> list[dict]:
        """Load all R1 specialist claims from JSONL files."""
        claims: list[dict] = []
        citations_dir = self.trace_dir / "audit" / "specialist_citations"
        if not citations_dir.exists():
            return claims
        for jsonl in citations_dir.glob("*.jsonl"):
            for line in jsonl.read_text().strip().split("\n"):
                if line.strip():
                    try:
                        claims.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return claims

    def _format_r1_claims_for_specialist_agent(self, claims: list[dict]) -> str:
        """Format R1 claims as context for R2a agent."""
        if not claims:
            return "(No Round 1 claims available.)"

        parts = ["## Round 1 Verified Claims\n"]
        by_agent: dict[str, list[dict]] = {}
        for c in claims:
            agent = c.get("agent", "unknown")
            by_agent.setdefault(agent, []).append(c)

        for agent, agent_claims in by_agent.items():
            parts.append(f"### {agent} ({len(agent_claims)} claims)")
            for c in agent_claims:
                verdict = c.get("verdict", "?")
                claim_text = c.get("claim", "?")
                parts.append(f"  [{verdict}] {claim_text}")
            parts.append("")

        return "\n".join(parts)

    async def _run_specialist_evidence_agent(self, r1_claims_text: str) -> dict:
        """Run R2a: Specialist Evidence Agent."""
        exec_id = self.trace_dir.name

        log_event("audit.round2.r2a_start", stage="audit",
                  execution_id=exec_id)

        toolset = AuditToolSet(
            self.trace_dir, self.report_path,
            event_emitter=log_event,
            allowed_search_dirs=["trace/specialist_outputs/"],
            allowed_read_files=["report.md"],
        )
        tools = toolset.get_round2_specialist_tools()

        system_prompt = SPECIALIST_EVIDENCE_SYSTEM_PROMPT
        user_prompt = SPECIALIST_EVIDENCE_USER_TEMPLATE.format(
            r1_claims=r1_claims_text,
        )

        llm = create_llm(temperature=0.1, max_tokens=8192)
        agent = create_react_agent(llm, tools, prompt=system_prompt)

        max_rounds = 400
        recursion_limit = 4 * max_rounds + 1

        observer = AgentObserver(
            "audit_r2a_specialist",
            sid="", execution_id=exec_id, stage="audit",
        )

        if self.execution_logger:
            self.execution_logger.log_trace_prompt(
                "audit_r2a_specialist", "system", system_prompt)
            self.execution_logger.log_trace_prompt(
                "audit_r2a_specialist", "user", user_prompt)

        logger.info("Round 2a: Starting specialist evidence agent (max_rounds=%d)",
                     max_rounds)
        try:
            await asyncio.wait_for(
                agent.ainvoke(
                    {"messages": [HumanMessage(content=user_prompt)]},
                    config={"recursion_limit": recursion_limit,
                            "callbacks": [observer]},
                ),
                timeout=900,  # 15 minutes
            )
        except asyncio.TimeoutError:
            logger.error("R2a (specialist evidence) timed out")
        except Exception:
            logger.error("R2a (specialist evidence) failed", exc_info=True)
            raise
        finally:
            self._save_tool_calls("audit_r2a_specialist", observer.get_tool_calls())
            toolset.save_enforcement_log()
            if toolset.enforcement_count:
                logger.info("R2a grep enforcement: %d rejections", toolset.enforcement_count)
            if self.execution_logger:
                self.execution_logger.log_trace_steps(
                    "audit_r2a_specialist", observer.get_react_steps())
                self.execution_logger.log_token_usage(
                    "audit_r2a_specialist", observer.get_token_usage())

        result = self._read_specialist_evidence()

        log_event("audit.round2.r2a_end", stage="audit",
                  execution_id=exec_id,
                  total=result.get("total", 0))
        logger.info("R2a complete: %d specialist evidence entries",
                     result.get("total", 0))
        return result

    async def _run_source_evidence_agent(self) -> dict:
        """Run R2b: Source Evidence Agent."""
        exec_id = self.trace_dir.name

        log_event("audit.round2.r2b_start", stage="audit",
                  execution_id=exec_id)

        toolset = AuditToolSet(
            self.trace_dir, self.report_path,
            event_emitter=log_event,
            allowed_search_dirs=["tools/"],
            allowed_read_files=["report.md"],
        )
        tools = toolset.get_round2_source_tools()

        system_prompt = SOURCE_EVIDENCE_SYSTEM_PROMPT
        user_prompt = SOURCE_EVIDENCE_USER_TEMPLATE

        llm = create_llm(temperature=0.1, max_tokens=8192)
        agent = create_react_agent(llm, tools, prompt=system_prompt)

        max_rounds = 400
        recursion_limit = 4 * max_rounds + 1

        observer = AgentObserver(
            "audit_r2b_source",
            sid="", execution_id=exec_id, stage="audit",
        )

        if self.execution_logger:
            self.execution_logger.log_trace_prompt(
                "audit_r2b_source", "system", system_prompt)
            self.execution_logger.log_trace_prompt(
                "audit_r2b_source", "user", user_prompt)

        logger.info("Round 2b: Starting source evidence agent (max_rounds=%d)",
                     max_rounds)
        try:
            await asyncio.wait_for(
                agent.ainvoke(
                    {"messages": [HumanMessage(content=user_prompt)]},
                    config={"recursion_limit": recursion_limit,
                            "callbacks": [observer]},
                ),
                timeout=900,  # 15 minutes
            )
        except asyncio.TimeoutError:
            logger.error("R2b (source evidence) timed out")
        except Exception:
            logger.error("R2b (source evidence) failed", exc_info=True)
            raise
        finally:
            self._save_tool_calls("audit_r2b_source", observer.get_tool_calls())
            toolset.save_enforcement_log()
            if toolset.enforcement_count:
                logger.info("R2b grep enforcement: %d rejections", toolset.enforcement_count)
            if self.execution_logger:
                self.execution_logger.log_trace_steps(
                    "audit_r2b_source", observer.get_react_steps())
                self.execution_logger.log_token_usage(
                    "audit_r2b_source", observer.get_token_usage())

        result = self._read_source_evidence()

        log_event("audit.round2.r2b_end", stage="audit",
                  execution_id=exec_id,
                  total=result.get("total", 0))
        logger.info("R2b complete: %d source evidence entries",
                     result.get("total", 0))
        return result

    def _read_specialist_evidence(self) -> dict:
        """Read specialist_evidence.jsonl and return entries."""
        jsonl_path = self.trace_dir / "audit" / "specialist_evidence.jsonl"
        if not jsonl_path.exists():
            return {"entries": [], "total": 0}
        entries: list[dict] = []
        for line in jsonl_path.read_text().strip().split("\n"):
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return {"entries": entries, "total": len(entries)}

    def _read_source_evidence(self) -> dict:
        """Read source_evidence.jsonl and return entries."""
        jsonl_path = self.trace_dir / "audit" / "source_evidence.jsonl"
        if not jsonl_path.exists():
            return {"entries": [], "total": 0}
        entries: list[dict] = []
        for line in jsonl_path.read_text().strip().split("\n"):
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return {"entries": entries, "total": len(entries)}

    def _generate_audit_report_v3(
        self,
        round1: dict[str, dict],
        r2a_data: dict,
        r2b_data: dict,
        citations: dict,
        duration: float,
    ) -> str:
        """Generate human-readable audit report (v3 format)."""
        lines = [
            "# Full-Chain Audit Report (v3)\n",
            f"Duration: {duration:.1f}s\n",
            "## Round 1 — Specialist Fidelity\n",
        ]
        r1_total = 0
        for agent_name, s in round1.items():
            total = s.get("total_claims", 0)
            r1_total += total
            if s.get("error"):
                lines.append(f"### {agent_name}: ERROR — {s['error']}\n")
                continue
            found = s.get("found", 0)
            derived = s.get("derived", 0)
            not_found = s.get("not_found", s.get("not-found", 0))
            lines.append(f"### {agent_name}: {total} claims "
                         f"({found} found, "
                         f"{derived} derived, "
                         f"{not_found} not-found)\n")
        lines.append(f"**Round 1 total: {r1_total} specialist claims**\n")

        lines.append("## Round 2 — Evidence Collection\n")
        lines.append(f"- Specialist evidence (R2a): {len(r2a_data.get('entries', []))} matches")
        if r2a_data.get("error"):
            lines.append(f"  WARNING: R2a error: {r2a_data['error']}")
        lines.append(f"- Source evidence (R2b): {len(r2b_data.get('entries', []))} matches")
        if r2b_data.get("error"):
            lines.append(f"  WARNING: R2b error: {r2b_data['error']}")

        lines.append("\n## Verdict Summary (program-assigned)\n")
        summary = citations.get("summary", {})
        verdicts = summary.get("verdicts", {})
        lines.append(f"Total claims: {summary.get('total', 0)}")
        for v_name in ["verified", "supported", "specialist-judgment",
                        "computed", "kb-sourced", "web-sourced", "unverified"]:
            count = verdicts.get(v_name, 0)
            if count > 0:
                lines.append(f"- {v_name}: {count}")

        return "\n".join(lines)

    # ==================================================================
    # v1 — Legacy Single-Session Audit
    # ==================================================================

    async def _audit_v1(self) -> AuditResult:
        """Original single-session audit (used for digest mode and fallback)."""
        start = time.time()

        # 1. Generate manifest (mode-dependent)
        if self.mode == "digest":
            manifest = generate_digest_manifest(self.trace_dir)
            system_prompt = DIGEST_AUDIT_SYSTEM_PROMPT
            user_prompt = DIGEST_AUDIT_USER_PROMPT_TEMPLATE.format(manifest=manifest)
        else:
            manifest = generate_analysis_manifest(self.trace_dir, self.report_path)
            system_prompt = AUDIT_SYSTEM_PROMPT
            user_prompt = AUDIT_USER_PROMPT_TEMPLATE.format(manifest=manifest)

        logger.info("Manifest generated (%d chars, mode=%s)", len(manifest), self.mode)

        # Save manifest for meta-audit
        audit_dir = self.trace_dir / "audit"
        audit_dir.mkdir(exist_ok=True)
        (audit_dir / "audit_manifest.txt").write_text(manifest, encoding="utf-8")

        # 2. Create LLM
        llm = create_llm(temperature=0.1, max_tokens=16384)

        # 3. Create ReAct agent with audit tools
        toolset = AuditToolSet(self.trace_dir, self.report_path)
        tools = toolset.get_tools()
        agent = create_react_agent(llm, tools, prompt=system_prompt)

        # 4. Run agent
        max_rounds = 160
        recursion_limit = 4 * max_rounds + 1

        observer = AgentObserver(
            f"audit_{self.mode}",
            sid="",
            execution_id=self.trace_dir.name,
            stage="audit",
        )
        if self.execution_logger:
            self.execution_logger.log_trace_prompt(f"audit_{self.mode}", "system", system_prompt)
            self.execution_logger.log_trace_prompt(f"audit_{self.mode}", "user", user_prompt)

        logger.info("Starting v1 audit agent (max_rounds=%d, mode=%s)", max_rounds, self.mode)
        try:
            result = await asyncio.wait_for(
                agent.ainvoke(
                    {"messages": [HumanMessage(content=user_prompt)]},
                    config={
                        "recursion_limit": recursion_limit,
                        "callbacks": [observer],
                    },
                ),
                timeout=600,
            )
        except asyncio.TimeoutError:
            logger.error("Audit agent timed out after 600s")
            duration = time.time() - start
            timeout_report = (
                "# Audit Timed Out\n\n"
                "The audit agent exceeded the 10-minute timeout. "
                "Partial results may be available in the trace directory."
            )
            timeout_citations: dict[str, Any] = {"summary": {"error": "timeout"}, "citations": []}
            self._save_results(timeout_report, timeout_citations)
            return AuditResult(
                audit_report=timeout_report,
                citations=timeout_citations,
                trace_dir=self.trace_dir,
                duration_seconds=duration,
            )

        # 5. Extract output
        raw_output = _extract_final_output(result)
        duration = time.time() - start
        logger.info("Audit agent completed in %.1fs", duration)

        self._save_tool_calls(f"audit_{self.mode}", observer.get_tool_calls())
        if self.execution_logger:
            self.execution_logger.log_trace_steps(f"audit_{self.mode}", observer.get_react_steps())
            self.execution_logger.log_token_usage(f"audit_{self.mode}", observer.get_token_usage())

        # 6. Parse into structured results
        audit_report = _extract_audit_report(raw_output)
        citations = _extract_citations(raw_output)

        # 7. Save results to trace dir
        self._save_results(audit_report, citations)

        return AuditResult(
            audit_report=audit_report,
            citations=citations,
            trace_dir=self.trace_dir,
            duration_seconds=duration,
        )

    # ------------------------------------------------------------------
    # Shared Helpers
    # ------------------------------------------------------------------

    def _find_report(self, explicit_path: Path | None) -> Path | None:
        """Auto-detect the report file for this execution."""
        if explicit_path:
            return explicit_path.resolve()

        # Check inside trace dir first
        in_trace = self.trace_dir / "reports" / "final_report.md"
        if in_trace.exists() and in_trace.stat().st_size > 0:
            return in_trace

        # Try KB path from final_report_info.json
        info_path = self.trace_dir / "reports" / "final_report_info.json"
        if info_path.exists():
            try:
                data = json.loads(info_path.read_text())
                rp = data.get("report_path", "")
                if rp:
                    p = Path(rp)
                    if p.exists():
                        return p
            except (json.JSONDecodeError, OSError):
                pass

        # Fallback: find report in KB by ticker from execution_info
        exec_info_path = self.trace_dir / "execution_info.json"
        if exec_info_path.exists():
            try:
                info = json.loads(exec_info_path.read_text())
                ticker = info.get("ticker")
                if ticker:
                    firn_root = self.trace_dir.parents[1] / "firn"
                    kb_report = firn_root / "notebook" / "stocks" / ticker / "latest_report.md"
                    if kb_report.exists():
                        return kb_report
            except (json.JSONDecodeError, OSError):
                pass

        # Legacy fallback: standalone reports/ directory
        exec_id = self.trace_dir.name
        ts_match = re.match(r"(\d{8})_(\d{6})_", exec_id)
        if ts_match:
            reports_dir = self.trace_dir.parents[1] / "reports"
            if reports_dir.exists():
                date_str = ts_match.group(1)
                candidates = sorted(
                    reports_dir.glob(f"report_*_{date_str}_*.md"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if candidates:
                    return candidates[0]

        return None

    def _save_results(self, audit_report: str, citations: dict) -> None:
        """Save audit results to the trace directory."""
        audit_dir = self.trace_dir / "audit"
        audit_dir.mkdir(exist_ok=True)

        report_path = audit_dir / "audit_report.md"
        report_path.write_text(audit_report, encoding="utf-8")

        citations_path = audit_dir / "citations.json"
        with open(citations_path, "w", encoding="utf-8") as f:
            json.dump(citations, f, indent=2, ensure_ascii=False)

        logger.info("Audit results saved to %s", audit_dir)


# ---------------------------------------------------------------------------
# Output parsing (v1)
# ---------------------------------------------------------------------------

def _extract_final_output(result: dict) -> str:
    """Extract the final text from the agent result."""
    messages = result.get("messages", [])
    for msg in reversed(messages):
        content = getattr(msg, "content", "")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            text_parts = [
                block.get("text", "") for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            if text_parts:
                return "\n".join(text_parts)
    return ""


def _extract_audit_report(raw: str) -> str:
    """Extract the AUDIT_REPORT section from agent output."""
    patterns = [
        r"### AUDIT_REPORT\s*\n(.*?)(?=### CITATIONS_JSON|$)",
        r"## Audit Summary\s*\n(.*?)(?=### CITATIONS_JSON|## CITATIONS_JSON|$)",
        r"AUDIT_REPORT\s*\n(.*?)(?=CITATIONS_JSON|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, re.DOTALL)
        if match:
            return match.group(0).strip()

    if "CITATIONS_JSON" in raw:
        return raw[:raw.index("CITATIONS_JSON")].strip()

    return raw.strip()


def _extract_citations(raw: str) -> dict:
    """Extract the CITATIONS_JSON section from agent output."""
    patterns = [
        r"CITATIONS_JSON.*?```json\s*\n(.*?)```",
        r"CITATIONS_JSON.*?```\s*\n(.*?)```",
        r"```json\s*\n(\{.*?\"citations\".*?\})\s*```",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue

    json_pattern = r"\{[^{}]*\"citations\"[^{}]*\[.*?\][^{}]*\}"
    match = re.search(json_pattern, raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse CITATIONS_JSON from agent output")
    return {
        "citations": [],
        "summary": {"total_claims": 0, "parse_error": True},
        "raw_output_tail": raw[-500:] if len(raw) > 500 else raw,
    }
