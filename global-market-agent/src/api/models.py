"""Pydantic v2 response models for the FastAPI layer."""

from __future__ import annotations

from pydantic import BaseModel
from typing import Literal


# --- Submission / Status ---

class SubmitResponse(BaseModel):
    exec_id: str
    status: Literal["queued"] = "queued"


class ExecutionStatus(BaseModel):
    exec_id: str
    status: Literal["running", "completed", "unknown"]


# --- Analysis ---

class AnalysisResult(BaseModel):
    exec_id: str
    ticker: str
    query: str | None = None
    status: Literal["running", "complete", "failed"]
    started_at: str
    completed_at: str | None = None
    report: str | None = None
    report_length: int | None = None
    agent_timings: dict[str, float] = {}
    token_usage: dict[str, int] = {}
    audit: AuditResult | None = None


class AuditResult(BaseModel):
    total_claims: int
    verdicts: dict[str, int]
    citations: list[Citation]
    audit_report: str
    duration_seconds: float | None = None


class Citation(BaseModel):
    id: int
    claim: str
    claim_in_report: str = ""      # EXACT text from report for positioning
    verdict: str
    source: dict = {}               # {agent, tool, index, raw_value}
    specialist: dict | None = None  # {agent, excerpt}
    evidence: dict | None = None    # {source_grep, specialist_grep}
    r1_match: dict | None = None    # {agent, claim_id, verdict}


# --- Digest ---

class DigestResult(BaseModel):
    exec_id: str
    status: Literal["running", "complete", "failed"]
    started_at: str
    completed_at: str | None = None
    batches_total: int | None = None
    batches_complete: int = 0
    articles_processed: int = 0
    kb_mutations: list[KBMutation] = []


class KBMutation(BaseModel):
    type: Literal["create", "update", "delete"]
    path: str
    fidelity_verdict: str | None = None


# --- System ---

class SystemStatus(BaseModel):
    day_n: int
    total_articles: int
    total_themes: int
    total_stocks: int
    total_events: int = 0
    core_mind_chars: int
    library_unread: int = 0
    library_read: int = 0
    last_digest: str | None = None
    last_analysis: str | None = None
    llm_provider: str
    test_counts: dict[str, int] = {}


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    active_executions: int = 0


# --- Auth ---

class LoginRequest(BaseModel):
    password: str


class TokenInfo(BaseModel):
    role: Literal["admin", "visitor"]
    exp: int
    iat: int


# Rebuild forward refs for nested models
AnalysisResult.model_rebuild()
AuditResult.model_rebuild()
