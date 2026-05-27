"""Per-run execution logger — records agent interactions, LLM calls, and reports.

Each invocation of the analysis pipeline creates a timestamped directory under
``logs/`` containing structured JSON logs for every agent and LLM call.  This
supports the L1 (tool-call correctness) evaluation layer described in
PROJECT_BLUEPRINT.md.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Resolve project root once so log paths are always absolute.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # global-market-agent/


class ExecutionLogger:
    """Structured logger for a single analysis run."""

    def __init__(self, base_log_dir: str = "logs") -> None:
        log_path = Path(base_log_dir)
        if not log_path.is_absolute():
            log_path = _PROJECT_ROOT / log_path
        self.base_log_dir = log_path
        self.execution_id = self._make_id()
        self.execution_dir = self._init_dirs()
        self.start_time = time.time()
        self._log_start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_agent_start(self, agent_name: str, input_data: Dict[str, Any]) -> None:
        self._save_json(
            {
                "agent_name": agent_name,
                "start_time": datetime.now().isoformat(),
                "input_data": input_data,
                "status": "started",
            },
            f"agents/{agent_name}.json",
        )

    def log_agent_complete(
        self,
        agent_name: str,
        output_data: Dict[str, Any],
        execution_time: float,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        existing = self._load_json(f"agents/{agent_name}.json") or {}
        existing.update(
            {
                "end_time": datetime.now().isoformat(),
                "execution_time_seconds": execution_time,
                "output_data": output_data,
                "success": success,
                "error": error,
                "status": "completed" if success else "failed",
            }
        )
        self._save_json(existing, f"agents/{agent_name}.json")

    def log_llm_interaction(
        self,
        agent_name: str,
        interaction_type: str,
        input_messages: List[Dict[str, Any]],
        output_content: str,
        model_config: Dict[str, Any],
        execution_time: float,
    ) -> None:
        iid = uuid.uuid4().hex[:8]
        self._save_json(
            {
                "interaction_id": iid,
                "agent_name": agent_name,
                "interaction_type": interaction_type,
                "timestamp": datetime.now().isoformat(),
                "model_config": model_config,
                "input": {
                    "messages": input_messages,
                    "total_input_length": sum(
                        len(str(m.get("content", ""))) for m in input_messages
                    ),
                },
                "output": {
                    "content_length": len(output_content),
                    "preview": output_content[:500],
                },
                "execution_time_seconds": execution_time,
            },
            f"llm/{agent_name}_{interaction_type}_{iid}.json",
        )

    def log_tool_calls(self, agent_name: str, tool_calls: List[Dict[str, Any]]) -> None:
        """Log all tool calls from a ReAct agent invocation.

        Uses append-aware naming: if the file already exists (multi-batch
        digest), subsequent calls write to ``_b{n}`` suffixed files so that
        no data is overwritten.
        """
        if not tool_calls:
            return
        base = f"tools/{agent_name}_tool_calls.json"
        path = self.execution_dir / base
        rel = base
        if path.exists():
            n = 2
            while True:
                rel = f"tools/{agent_name}_b{n}_tool_calls.json"
                path = self.execution_dir / rel
                if not path.exists():
                    break
                n += 1
        self._save_json(
            {
                "agent_name": agent_name,
                "timestamp": datetime.now().isoformat(),
                "tool_call_count": len(tool_calls),
                "tool_calls": tool_calls,
            },
            rel,
        )

    def log_token_usage(self, agent_name: str, usage: Dict[str, Any]) -> None:
        """Log aggregated token usage for an agent.

        Merges a ``token_usage`` field into the existing agent JSON file.
        """
        if not usage:
            return
        existing = self._load_json(f"agents/{agent_name}.json") or {}
        existing["token_usage"] = usage
        self._save_json(existing, f"agents/{agent_name}.json")

    def log_final_report(self, report_content: str, report_path: str) -> None:
        self._save_json(
            {
                "timestamp": datetime.now().isoformat(),
                "report_path": report_path,
                "report_length": len(report_content),
            },
            "reports/final_report_info.json",
        )
        self._save_text(report_content, "reports/final_report.md")

    def log_verification(self, name: str, data: Dict[str, Any]) -> None:
        """Save a verification sidecar to trace/verification/.

        Used by deterministic computation modules (e.g. reverse_dcf) to record
        their exact inputs and outputs so the Audit Agent can cross-check results.
        """
        self._save_json(data, f"trace/verification/{name}.json")

    def log_trace_prompt(self, agent_name: str, role: str, content: str) -> None:
        """Save a full (untruncated) prompt to trace/prompts/.

        Handles multi-batch scenarios by appending _b{n} suffix when the
        base filename already exists.
        """
        base = f"{agent_name}_{role}.txt"
        rel = f"trace/prompts/{base}"
        path = self.execution_dir / rel
        if path.exists():
            n = 2
            while True:
                rel = f"trace/prompts/{agent_name}_b{n}_{role}.txt"
                path = self.execution_dir / rel
                if not path.exists():
                    break
                n += 1
        self._save_text(content, rel)

    def log_trace_steps(self, agent_name: str, steps: List[Dict[str, Any]]) -> None:
        """Append ReAct steps as JSONL to trace/react_steps/.

        Each call appends to the same file, so multi-batch digest sessions
        naturally accumulate all steps in one JSONL stream.
        """
        if not steps:
            return
        rel = f"trace/react_steps/{agent_name}_steps.jsonl"
        path = self.execution_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for step in steps:
                f.write(json.dumps(step, ensure_ascii=False, default=str) + "\n")

    def save_extra_info(self, extra: dict) -> None:
        """Merge additional fields into execution_info.json."""
        info = self._load_json("execution_info.json") or {}
        info.update(extra)
        self._save_json(info, "execution_info.json")

    def finalize(self, success: bool = True, error: str | None = None) -> None:
        info = self._load_json("execution_info.json") or {}
        info.update(
            {
                "end_time": datetime.now().isoformat(),
                "total_seconds": time.time() - self.start_time,
                "success": success,
                "error": error,
            }
        )
        self._save_json(info, "execution_info.json")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _make_id() -> str:
        return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    def _init_dirs(self) -> Path:
        d = self.base_log_dir / self.execution_id
        for sub in ("agents", "llm", "reports", "tools", "trace/prompts", "trace/react_steps", "trace/verification"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        return d

    def _log_start(self) -> None:
        self._save_json(
            {
                "execution_id": self.execution_id,
                "start_time": datetime.now().isoformat(),
                "env": {
                    "LLM_PROVIDER": os.getenv("LLM_PROVIDER", ""),
                    "LLM_MODEL": os.getenv("LLM_MODEL", ""),
                },
            },
            "execution_info.json",
        )

    def _save_json(self, data: Any, filename: str) -> None:
        path = self.execution_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    def _load_json(self, filename: str) -> Dict[str, Any] | None:
        path = self.execution_dir / filename
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _save_text(self, content: str, filename: str) -> None:
        path = self.execution_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_logger: ExecutionLogger | None = None


def initialize_execution_logger(base_log_dir: str = "logs") -> ExecutionLogger:
    global _logger
    _logger = ExecutionLogger(base_log_dir)
    return _logger


def set_execution_logger(el: ExecutionLogger) -> None:
    """Set a pre-created ExecutionLogger as the global singleton.

    Used by the API service layer to ensure output handlers can access
    the same logger instance via get_execution_logger().
    """
    global _logger
    _logger = el


def get_execution_logger() -> ExecutionLogger:
    global _logger
    if _logger is None:
        _logger = ExecutionLogger()
    return _logger


def finalize_execution_logger(success: bool = True, error: str | None = None) -> None:
    global _logger
    if _logger:
        _logger.finalize(success, error)
        _logger = None
