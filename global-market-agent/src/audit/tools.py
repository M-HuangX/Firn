"""Audit Tool Set — sandboxed read/search/record tools for Audit Agent v1–v3.

Tools are restricted to a specific trace directory (logs/<exec_id>/) plus
an optional report file path. Path traversal outside the sandbox is blocked.

v2 additions (Full-Chain Audit, D36):
  - grep_trace: multi-pattern OR (|) + context lines
  - read_tool_call: targeted single tool call read
  - read_trace_section: partial file read by line range
  - record_specialist_claim: Round 1 atomic write (specialist fidelity)

v3 additions (Audit v3, D38):
  - grep_trace: ripgrep backend with full regex support
  - GrepRecord: history tracking for evidence verification
  - allowed_search_dirs / allowed_read_files: per-agent restriction

v4 additions (Tool Call Animation, D42):
  - resolve_tool_call_location: grep line → (tool_name, index)
  - grep_trace annotations: [@ tool_call #N: tool_name]
  - read_trace_file: large JSON summary mode
  - record_specialist_claim: grep_file/grep_line params, auto-resolve
  - record_source_evidence: auto-resolve agent + tool from grep coords
  - record_specialist_evidence: R1 cross-reference for source tracking

v4.2 additions (claim_in_report enforcement):
  - _verify_claim_in_report: rejects R2a/R2b claims not found in final report

v4.3 additions (claim_in_specialist_output enforcement):
  - _verify_claim_in_specialist_output: rejects R1 claims not found in
    specialist output — cascades into higher R1↔R2 match quality

Uses the closure pattern (same as KBToolSet) because LangChain's @tool
decorator does not work on instance methods.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_MIN_EVIDENCE_LEN = 20  # minimum grep_evidence length to accept


# ---------------------------------------------------------------------------
# claim_in_report verification helpers
# ---------------------------------------------------------------------------

_MD_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_MD_ITALIC_RE = re.compile(r"\*([^*]+)\*")
_MD_STRIKE_RE = re.compile(r"~~([^~]+)~~")
_MD_CODE_RE = re.compile(r"`([^`]+)`")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_HEADING_RE = re.compile(r"^#+\s*", flags=re.MULTILINE)
def _strip_md(text: str) -> str:
    """Strip markdown formatting for text comparison."""
    text = _MD_BOLD_RE.sub(r"\1", text)
    text = _MD_ITALIC_RE.sub(r"\1", text)
    text = _MD_STRIKE_RE.sub(r"\1", text)
    text = _MD_CODE_RE.sub(r"\1", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = text.replace("|", " ")
    text = _MD_HEADING_RE.sub("", text)
    # Normalize dashes (em-dash, en-dash → hyphen)
    text = text.replace("\u2014", "-").replace("\u2013", "-")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# ripgrep binary discovery
# ---------------------------------------------------------------------------

def _find_rg_binary() -> str:
    """Find ripgrep binary. Prefer Claude Code's vendored copy."""
    vendored = Path.home() / ".npm-global/lib/node_modules/@anthropic-ai/claude-code/vendor/ripgrep/x64-linux/rg"
    if vendored.exists():
        return str(vendored)
    system_rg = shutil.which("rg")
    if system_rg:
        return system_rg
    raise FileNotFoundError("ripgrep (rg) not found. Install with: apt install ripgrep")


_RG_BINARY: str | None = None


def _get_rg() -> str:
    global _RG_BINARY
    if _RG_BINARY is None:
        _RG_BINARY = _find_rg_binary()
    return _RG_BINARY


# ---------------------------------------------------------------------------
# Grep history record (Step 2 prep)
# ---------------------------------------------------------------------------

@dataclass
class GrepRecord:
    pattern: str
    path: str
    result_text: str
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Path relativization helper for rg output
# ---------------------------------------------------------------------------

def _relativize_rg_line(line: str, trace_dir: Path, report_path: Path | None) -> str:
    """Convert absolute paths in rg output to trace-relative paths."""
    # rg output format: /absolute/path:linenum:content or /absolute/path:linenum-content
    colon_idx = line.find(":")
    if colon_idx <= 0:
        return line
    file_part = line[:colon_idx]
    rest = line[colon_idx:]

    abs_path = Path(file_part)
    if report_path and abs_path == report_path:
        return "report.md" + rest
    try:
        rel = abs_path.relative_to(trace_dir)
        return str(rel) + rest
    except ValueError:
        return line


# ---------------------------------------------------------------------------
# Tool call resolution helpers (module-level)
# ---------------------------------------------------------------------------

def resolve_tool_call_location(
    trace_dir: Path, grep_file: str, grep_line: int
) -> tuple[str, int]:
    """Resolve (tool_name, tool_call_index) from a grep file:line reference.

    tool_calls.json layout: 5-line header + 8 lines per tool call (6 fields).
    Formula: index = (grep_line - 6) // 8

    This depends on execution_logger.py using json.dump(indent=2) with exactly
    6 fields per tool call entry. Validated against actual JSON to catch drift.

    Falls back to ("", -1) if resolution fails.
    """
    if not grep_file or grep_line < 6:
        return ("", -1)
    # Must be a tool_calls.json file
    if not re.match(r"tools/\w+_tool_calls\.json$", grep_file):
        return ("", -1)
    index = (grep_line - 6) // 8
    if index < 0:
        return ("", -1)
    # Validate against actual JSON
    full_path = trace_dir / grep_file
    if not full_path.exists():
        return ("", -1)
    try:
        data = json.loads(full_path.read_text(encoding="utf-8"))
        calls = data.get("tool_calls", [])
        if 0 <= index < len(calls):
            return (calls[index].get("tool_name", ""), index)
    except (json.JSONDecodeError, KeyError):
        pass
    return ("", -1)


def _extract_agent_from_grep_file(grep_file: str) -> str:
    """Extract agent name from grep file path.

    'tools/fundamental_tool_calls.json' -> 'fundamental'
    'trace/specialist_outputs/fundamental_output.md' -> 'fundamental'
    """
    m = re.match(r"tools/(\w+)_tool_calls\.json$", grep_file)
    if m:
        return m.group(1)
    m = re.match(r"trace/specialist_outputs/(\w+)_output\.md$", grep_file)
    if m:
        return m.group(1)
    return ""


def _load_r1_claims_for_agent(trace_dir: Path, agent: str) -> list[dict]:
    """Load R1 specialist claims for a given agent from JSONL."""
    jsonl_path = trace_dir / "audit" / "specialist_citations" / f"{agent}.jsonl"
    if not jsonl_path.exists():
        return []
    claims = []
    for line in jsonl_path.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            try:
                claims.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return claims


_PUNCT_RE = __import__("re").compile(r"[^\w\s.]")


def _claim_word_similarity(a: str, b: str) -> float:
    """Word-level Jaccard similarity between two claim strings.

    Strips punctuation (except dots for decimals) before tokenising
    so that ``"Target:"`` matches ``"target"`` and ``"($1.38)"``
    matches ``"1.38"``.
    """
    if not a or not b:
        return 0.0
    a_clean = _PUNCT_RE.sub("", a.lower())
    b_clean = _PUNCT_RE.sub("", b.lower())
    a_words = set(a_clean.split())
    b_words = set(b_clean.split())
    if not a_words or not b_words:
        return 0.0
    return len(a_words & b_words) / len(a_words | b_words)


def _find_nearest_r1_claim(
    r1_claims: list[dict],
    grep_line: int,
    r2a_claim: str,
    max_line_distance: int = 5,
) -> dict | None:
    """Find the best matching R1 claim for an R2a evidence entry.

    Strategy:
    1. Primary: line-distance within +/-max_line_distance (existing logic).
    2. Fallback: if no line-distance match, use text similarity across all
       R1 claims for this agent.  Minimum similarity threshold = 0.45.
    """
    if not r1_claims or grep_line < 0:
        return None

    # --- Primary: line distance ---
    line_candidates = []
    for c in r1_claims:
        output_line = c.get("output_line", -1)
        if output_line < 0:
            continue
        dist = abs(output_line - grep_line)
        if dist <= max_line_distance:
            line_candidates.append((dist, c))
    if line_candidates:
        line_candidates.sort(key=lambda x: x[0])
        return line_candidates[0][1]

    # --- Fallback: text similarity ---
    MIN_SIMILARITY = 0.45
    best_sim = 0.0
    best_claim = None
    for c in r1_claims:
        sim = _claim_word_similarity(r2a_claim, c.get("claim", ""))
        if sim > best_sim:
            best_sim = sim
            best_claim = c
    if best_claim and best_sim >= MIN_SIMILARITY:
        return best_claim
    return None


class AuditToolSet:
    """Per-invocation tool set for auditing a single execution trace.

    Parameters
    ----------
    trace_dir : Path
        The execution directory (``logs/<exec_id>/``).
    report_path : Path | None
        Path to the final report file.  If the report lives outside
        ``trace_dir`` (e.g. in ``reports/report_NOW_*.md``), provide it
        here so ``read_trace_file`` can access it as ``report.md``.
    event_emitter : callable | None
        Optional ``log_event(event, *, stage, execution_id, **data)``
        function for emitting SSE events from record tools.
    """

    def __init__(self, trace_dir: Path, report_path: Path | None = None,
                 *, event_emitter: Any | None = None,
                 allowed_search_dirs: list[str] | None = None,
                 allowed_read_files: list[str] | None = None) -> None:
        self.trace_dir = trace_dir.resolve()
        self.report_path = report_path.resolve() if report_path else None
        self._event_emitter = event_emitter
        self._allowed_search_dirs = allowed_search_dirs
        self._allowed_read_files = allowed_read_files
        self._grep_history: list[GrepRecord] = []
        self._enforcement_log: list[dict] = []

        # Preload tool_calls.json line-number -> (tool_name, index) mapping
        self._tc_line_map: dict[str, list[tuple[str, int, int]]] = {}
        self._preload_tool_call_maps()

        # Preload report text for claim_in_report verification
        self._report_text = ""
        self._report_normalized = ""
        if self.report_path and self.report_path.exists():
            try:
                self._report_text = self.report_path.read_text(encoding="utf-8")
                self._report_normalized = _strip_md(self._report_text).lower()
            except Exception:
                logger.debug("Could not load report for CIR verification",
                             exc_info=True)

        # Preload specialist output texts for claim-in-specialist verification
        self._specialist_texts: dict[str, str] = {}
        self._specialist_normalized: dict[str, str] = {}
        spec_dir = self.trace_dir / "trace" / "specialist_outputs"
        if spec_dir.is_dir():
            for agent_name in ("fundamental", "technical", "value", "macro"):
                output_file = spec_dir / f"{agent_name}_output.md"
                if output_file.exists():
                    try:
                        text = output_file.read_text(encoding="utf-8")
                        self._specialist_texts[agent_name] = text
                        self._specialist_normalized[agent_name] = (
                            _strip_md(text).lower()
                        )
                    except Exception:
                        logger.debug(
                            "Could not load specialist output for %s",
                            agent_name, exc_info=True,
                        )

        # Build all tools as closures capturing self
        self._tools: dict[str, Any] = {}
        self._build_tools()

    def _verify_claim_in_report(self, claim_in_report: str) -> tuple[bool, str]:
        """Verify that claim_in_report text actually appears in the report.

        Returns (ok, error_message).  Skips verification if no report loaded.
        """
        if not self._report_text:
            return True, ""  # No report loaded, skip

        claim = claim_in_report.strip()
        if len(claim) < 5:
            return False, (
                "claim_in_report is too short (< 5 chars). "
                "Copy the exact sentence from the report."
            )

        # Normalized substring match — aligned with frontend Phase 0 which
        # also uses substring matching for claim_in_report.  No fuzzy fallback:
        # if it's not a substring, the frontend can't locate it either.
        norm_claim = _strip_md(claim).lower()
        if norm_claim in self._report_normalized:
            return True, ""

        return False, (
            "claim_in_report text not found in the report. "
            "Copy the EXACT sentence from the report that contains this "
            "claim. Do not paraphrase, annotate, or describe - paste "
            "verbatim text."
        )

    def _verify_claim_in_specialist_output(
        self, claim: str, agent: str,
    ) -> tuple[bool, str]:
        """Verify that a claim actually appears in the specialist's output.

        Normalized substring match against the specialist output text.

        Returns (ok, error_message).  Skips if no output loaded for *agent*.
        """
        if agent not in self._specialist_texts:
            return True, ""  # No output loaded, skip

        claim_stripped = claim.strip()
        if len(claim_stripped) < 5:
            return False, (
                "claim is too short (< 5 chars). "
                "Copy the exact factual statement from the specialist output."
            )

        spec_normalized = self._specialist_normalized[agent]
        spec_text = self._specialist_texts[agent]

        norm_claim = _strip_md(claim_stripped).lower()
        if norm_claim in spec_normalized:
            return True, ""

        return False, (
            "claim text not found in the specialist output. "
            "Copy the EXACT factual statement from the specialist's "
            "output. Do not paraphrase or summarize — paste the claim "
            "as it appears in the specialist output file."
        )

    def _preload_tool_call_maps(self) -> None:
        """Build line-number lookup tables for all tool_calls.json files."""
        tools_dir = self.trace_dir / "tools"
        if not tools_dir.is_dir():
            return
        for tc_file in tools_dir.glob("*_tool_calls.json"):
            try:
                data = json.loads(tc_file.read_text(encoding="utf-8"))
                calls = data.get("tool_calls", [])
                rel_path = f"tools/{tc_file.name}"
                entries = []
                for i, tc in enumerate(calls):
                    start_line = 6 + i * 8  # line where this tc's { starts
                    end_line = start_line + 7  # inclusive last line
                    entries.append((tc.get("tool_name", ""), i, start_line))
                self._tc_line_map[rel_path] = entries
            except (json.JSONDecodeError, KeyError):
                pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_tools(self) -> list:
        """Return basic audit tools (read + grep + list)."""
        return [self._tools[n] for n in ("read_trace_file", "grep_trace", "list_trace_files")
                if n in self._tools]

    def get_round1_tools(self) -> list:
        """Return tools for Round 1 specialist fidelity audit."""
        names = ["grep_trace", "read_trace_file", "read_tool_call",
                 "read_trace_section", "list_trace_files", "record_specialist_claim"]
        return [self._tools[n] for n in names if n in self._tools]

    def get_round2_specialist_tools(self) -> list:
        """Tools for R2a — Specialist Evidence Agent."""
        names = ["grep_trace", "read_trace_file", "read_trace_section",
                 "list_trace_files", "record_specialist_evidence"]
        return [self._tools[n] for n in names if n in self._tools]

    def get_round2_source_tools(self) -> list:
        """Tools for R2b — Source Evidence Agent."""
        names = ["grep_trace", "read_trace_file", "read_tool_call",
                 "read_trace_section", "list_trace_files", "record_source_evidence"]
        return [self._tools[n] for n in names if n in self._tools]

    def get_tools_by_names(self, names: list[str]) -> list:
        """Return a subset of tools by name."""
        return [self._tools[n] for n in names if n in self._tools]

    def save_enforcement_log(self) -> None:
        """Write enforcement rejections to audit/enforcement_log.jsonl."""
        if not self._enforcement_log:
            return
        log_path = self.trace_dir / "audit" / "enforcement_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            for entry in self._enforcement_log:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    @property
    def enforcement_count(self) -> int:
        """Number of record calls rejected by grep enforcement."""
        return len(self._enforcement_log)

    # ------------------------------------------------------------------
    # Path security
    # ------------------------------------------------------------------

    def _resolve_path(self, path_str: str) -> Path | None:
        """Resolve a user-provided path safely within the sandbox.

        Returns None if the path escapes the trace directory.
        Supports the virtual path ``report.md`` which maps to the
        external report file (if provided).
        """
        # Virtual alias for the report file
        if path_str.strip() in ("report.md", "report"):
            return self.report_path

        candidate = (self.trace_dir / path_str).resolve()
        if self.trace_dir in candidate.parents or candidate == self.trace_dir:
            return candidate
        return None

    # ------------------------------------------------------------------
    # Event helper
    # ------------------------------------------------------------------

    def _emit(self, event: str, **data: Any) -> None:
        """Emit an SSE event if an emitter is configured."""
        if self._event_emitter:
            try:
                self._event_emitter(
                    event, stage="audit",
                    execution_id=self.trace_dir.name, **data)
            except Exception:
                logger.debug("Failed to emit event %s", event, exc_info=True)

    # ------------------------------------------------------------------
    # Tool construction
    # ------------------------------------------------------------------

    def _build_tools(self) -> None:
        trace_dir = self.trace_dir
        resolve_path = self._resolve_path
        report_path = self.report_path
        emit = self._emit
        allowed_search_dirs = self._allowed_search_dirs
        allowed_read_files = self._allowed_read_files
        grep_history = self._grep_history
        enforcement_log = self._enforcement_log
        tc_line_map = self._tc_line_map
        verify_cir = self._verify_claim_in_report
        verify_ciso = self._verify_claim_in_specialist_output

        # ---- local annotation helper ----
        def _annotate_tc_line(line: str) -> str:
            """Add [@ tool_call #N: name] to tool_calls.json grep matches."""
            m = re.match(r"(tools/\w+_tool_calls\.json):(\d+)[:-]", line)
            if not m:
                return line
            rel_path = m.group(1)
            line_num = int(m.group(2))
            entries = tc_line_map.get(rel_path, [])
            for tool_name, idx, start_line in entries:
                if start_line <= line_num <= start_line + 7:
                    return f"{line}  [@ tool_call #{idx}: {tool_name}]"
            return line

        # ---- read_trace_file ----
        @tool
        def read_trace_file(path: str) -> str:
            """Read a file from the execution trace directory.

            Args:
                path: Relative path within the trace dir (e.g.
                    "trace/prompts/fundamental_system.txt",
                    "tools/fundamental_tool_calls.json",
                    "report.md").

            Returns:
                File contents as text.  JSON files are pretty-printed.
            """
            # Enforce allowed_read_files restriction
            if allowed_read_files is not None:
                if path.strip() not in allowed_read_files:
                    return f"ERROR: you can only read: {', '.join(allowed_read_files)}"

            resolved = resolve_path(path)
            if resolved is None:
                return f"ERROR: path '{path}' is outside the trace directory."
            if not resolved.exists():
                return f"ERROR: file not found: {path}"
            if not resolved.is_file():
                return f"ERROR: '{path}' is a directory, not a file. Use list_trace_files instead."

            try:
                raw = resolved.read_text(encoding="utf-8")
            except Exception as e:
                return f"ERROR: cannot read '{path}': {e}"

            # Pretty-print JSON for readability
            if resolved.suffix == ".json":
                try:
                    data = json.loads(raw)
                    pretty = json.dumps(data, indent=2, ensure_ascii=False)
                except json.JSONDecodeError:
                    pretty = None

                # Large tool_calls.json -> return summary instead of full content
                if resolved.name.endswith("_tool_calls.json") and len(raw) > 10000:
                    try:
                        data = json.loads(raw)
                        calls = data.get("tool_calls", [])
                        summary_lines = [f"[{i}] {tc['tool_name']}  input={str(tc.get('input', ''))[:80]}"
                                         for i, tc in enumerate(calls)]
                        return (f"{path}: {len(calls)} tool calls (file too large for full read, showing summary)\n"
                                + "\n".join(summary_lines)
                                + "\n\nUse read_tool_call(agent, index) to read specific calls, "
                                "or grep_trace() to search for values.")
                    except (json.JSONDecodeError, KeyError):
                        pass

                if pretty is not None:
                    return pretty

            # For JSONL, format each line
            if resolved.suffix == ".jsonl":
                lines = raw.strip().split("\n")
                formatted = []
                for i, line in enumerate(lines, 1):
                    try:
                        obj = json.loads(line)
                        formatted.append(f"--- Step {i} ---\n{json.dumps(obj, indent=2, ensure_ascii=False)}")
                    except json.JSONDecodeError:
                        formatted.append(f"--- Step {i} ---\n{line}")
                return "\n\n".join(formatted)

            return raw

        # ---- grep_trace (v3: ripgrep backend) ----
        @tool
        def grep_trace(pattern: str, path: str = "", context: int = 0,
                       case_insensitive: bool = True) -> str:
            """Search for a pattern in trace files using regex (powered by ripgrep).

            Supports full regex syntax: "62\\.25", "FCF.*-115", "revenue|earnings"

            Args:
                pattern: Regex pattern to search for.
                    Supports full regex syntax: "62\\.25", "FCF.*-115", "revenue|earnings"
                    Use | for OR alternatives: "5.1|5100|5098"
                path: Relative path within trace dir (file or directory).
                    ALWAYS specify when you know which layer to search.
                    Examples: "tools/", "trace/specialist_outputs/",
                    "tools/fundamental_tool_calls.json".
                context: Lines of surrounding context (0-10). Default 0.
                    Use 2-3 for tool_calls.json to see tool_name near values.
                case_insensitive: Case insensitive search. Default True.

            Returns:
                Matching lines with file:linenum:content format.
                Context lines shown with file:linenum-content format.
                Groups separated by --.
            """
            if not pattern or not pattern.strip():
                return "ERROR: pattern cannot be empty."

            # Enforce allowed_search_dirs restriction
            if allowed_search_dirs is not None:
                if not path:
                    return ("ERROR: you must specify a search path. Allowed: "
                            + ", ".join(allowed_search_dirs))
                if not any(path.startswith(d) or path == d.rstrip("/")
                           for d in allowed_search_dirs):
                    return f"ERROR: you can only search in: {', '.join(allowed_search_dirs)}"

            context = max(0, min(context, 10))

            # Resolve search path within sandbox
            if path:
                resolved = resolve_path(path)
                if resolved is None:
                    return f"ERROR: path '{path}' is outside the trace directory."
                if not resolved.exists():
                    return f"ERROR: path not found: {path}"
                search_path = resolved
            else:
                search_path = trace_dir

            # Build rg args
            try:
                rg_path = _get_rg()
            except FileNotFoundError as e:
                return f"ERROR: {e}"

            args: list[str] = [rg_path, "--no-heading", "--with-filename",
                              "--max-columns", "500", "-n"]

            if case_insensitive:
                args.append("-i")

            if context > 0:
                args.extend(["-C", str(context)])

            # Pattern starting with dash — use -e flag
            if pattern.startswith("-"):
                args.extend(["-e", pattern])
            else:
                args.append(pattern)

            # Restrict to trace file types
            args.extend(["--type-add", "trace:*.{txt,json,jsonl,md}", "--type", "trace"])

            args.append(str(search_path))

            # Also include report if searching entire trace dir
            if not path and report_path and report_path.exists():
                args.append(str(report_path))

            # Run ripgrep
            try:
                result = subprocess.run(
                    args, capture_output=True, text=True, timeout=15)
            except subprocess.TimeoutExpired:
                return "ERROR: search timed out (15s). Narrow your search path or pattern."
            except Exception as e:
                return f"ERROR: ripgrep failed: {e}"

            # rg exit codes: 0=matches, 1=no matches, 2=error
            if result.returncode == 1:
                grep_history.append(GrepRecord(
                    pattern=pattern, path=path, result_text=""))
                return f"No matches found for pattern: {pattern}"
            if result.returncode == 2:
                return f"ERROR: regex error — {result.stderr.strip()}"

            raw_output = result.stdout.strip()
            lines = raw_output.split("\n")

            # Convert absolute paths to trace-relative and annotate
            output_lines = []
            for line in lines:
                rel_line = _relativize_rg_line(line, trace_dir, report_path)
                # Annotate tool_calls.json matches with [@ tool_call #N: tool_name]
                annotated = _annotate_tc_line(rel_line)
                output_lines.append(annotated)

            # Apply head limit
            MAX_MATCHES = 200
            if len(output_lines) > MAX_MATCHES:
                output_lines = output_lines[:MAX_MATCHES]
                output_lines.append(
                    f"\n... truncated at {MAX_MATCHES} lines. "
                    "Narrow your search path or pattern.")

            # Record grep history (store processed output that agents see,
            # not raw rg stdout — annotations must match for verification)
            grep_history.append(GrepRecord(
                pattern=pattern, path=path,
                result_text="\n".join(output_lines)))

            return "\n".join(output_lines)

        # ---- grep evidence verification (Step 2) ----
        def _verify_grep_evidence(grep_evidence: str) -> tuple[bool, str]:
            """Verify that grep_evidence text matches a recent grep result.

            Returns (ok, error_message).
            """
            if not grep_history:
                return False, (
                    "No grep calls recorded. You must call grep_trace() first "
                    "to find evidence before recording."
                )

            # Extract meaningful lines from evidence (skip empty, skip "Found N matches" header)
            evidence_lines = [
                l.strip() for l in grep_evidence.strip().split("\n")
                if l.strip() and not l.strip().startswith("Found ")
            ]
            if not evidence_lines:
                return False, "grep_evidence is empty or contains only headers."

            # Check: does any evidence line appear (as substring) in any recent grep output?
            all_grep_text = "\n".join(g.result_text for g in grep_history[-20:])

            for ev_line in evidence_lines[:5]:  # check first 5 lines
                # Normalize: strip leading context markers (>>, spaces) and path prefixes
                normalized = ev_line.lstrip("> ").strip()
                if len(normalized) < 10:
                    continue  # skip very short lines

                # Try exact substring match
                if normalized in all_grep_text:
                    return True, ""

                # Try without path prefix (evidence might use relative, grep used absolute)
                # Pattern: "file:num: content" — extract content part
                parts = normalized.split(":", 2)
                if len(parts) >= 3 and parts[1].strip().lstrip("-").isdigit():
                    content_part = parts[2].strip()
                    if len(content_part) >= 15 and content_part in all_grep_text:
                        return True, ""

            return False, (
                "grep_evidence does not match any recent grep_trace result. "
                "Call grep_trace() to search for the value, then paste the matching "
                "line into grep_evidence."
            )

        # ---- JSONL line counter helper ----
        def _count_jsonl_lines(path: Path) -> int:
            if not path.exists():
                return 0
            return sum(1 for line in path.read_text().strip().split("\n") if line.strip())

        # ---- read_tool_call ----
        @tool
        def read_tool_call(agent: str, index: int) -> str:
            """Read a specific tool call from an agent's tool_calls.json.

            Args:
                agent: Agent name (fundamental, technical, value, macro,
                    core_analysis).
                index: 0-based index of the tool call within the array.

            Returns:
                The complete tool call object (tool_name, input, output,
                duration). Much smaller than reading the entire file.

            Use this when:
              - grep found a match and you need to check the tool call's
                INPUT parameters (e.g. verify period=annual vs quarterly)
              - You need the full output context around a matched value
            """
            tc_path = trace_dir / "tools" / f"{agent}_tool_calls.json"
            if not tc_path.exists():
                return f"ERROR: file not found: tools/{agent}_tool_calls.json"

            try:
                data = json.loads(tc_path.read_text(encoding="utf-8"))
            except Exception as e:
                return f"ERROR: cannot parse: {e}"

            calls = data.get("tool_calls", [])
            if index < 0 or index >= len(calls):
                return (f"ERROR: index {index} out of range. "
                        f"{agent} has {len(calls)} tool calls (0-{len(calls) - 1}).")

            tc = calls[index]
            header = (f"Agent: {agent} | Tool call #{index} of {len(calls)}\n"
                      f"Tool: {tc.get('tool_name', '?')}\n"
                      f"---\n")
            return header + json.dumps(tc, indent=2, ensure_ascii=False)

        # ---- read_trace_section ----
        @tool
        def read_trace_section(path: str, start_line: int, end_line: int) -> str:
            """Read specific lines from a trace file.

            Args:
                path: Relative path within trace directory.
                start_line: First line to read (1-indexed, inclusive).
                end_line: Last line to read (inclusive). Max span: 100 lines.

            Use after grep_trace identifies a relevant section. Avoids
            loading entire large files into context.
            """
            resolved = resolve_path(path)
            if resolved is None:
                return f"ERROR: path '{path}' is outside the trace directory."
            if not resolved.exists():
                return f"ERROR: file not found: {path}"
            if not resolved.is_file():
                return f"ERROR: '{path}' is a directory."

            if end_line - start_line + 1 > 100:
                return "ERROR: max span is 100 lines. Narrow your range."
            if start_line < 1:
                start_line = 1

            try:
                all_lines = resolved.read_text(encoding="utf-8").split("\n")
            except Exception as e:
                return f"ERROR: cannot read '{path}': {e}"

            end_line = min(end_line, len(all_lines))
            selected = all_lines[start_line - 1:end_line]

            header = f"{path} (lines {start_line}-{end_line} of {len(all_lines)}):\n"
            numbered = [f"{start_line + i}: {line}" for i, line in enumerate(selected)]
            return header + "\n".join(numbered)

        # ---- record_specialist_claim (Round 1) ----
        @tool
        def record_specialist_claim(
            agent: str,
            claim: str,
            output_line: int,
            verdict: str,
            grep_file: str,
            grep_line: int,
            raw_value: str,
            grep_evidence: str,
            input_verified: bool = False,
            input_note: str = "",
        ) -> str:
            """Record one verified specialist claim (Round 1).

            MANDATORY: You MUST call grep_trace() first and paste the
            matching output line into grep_evidence. Empty evidence is
            REJECTED.

            Args:
                agent: Specialist name (fundamental, technical, value, macro).
                claim: The factual claim from specialist_output.md.
                output_line: Line number in specialist_outputs/<agent>_output.md.
                verdict: One of: found, derived, not-found.
                grep_file: File path from grep output (e.g.
                    "tools/fundamental_tool_calls.json"). Use "" for not-found.
                grep_line: Line number from grep output (e.g. 18). Use -1
                    for not-found.
                raw_value: Exact value found in tool call output.
                grep_evidence: The grep_trace output proving this match.
                    REQUIRED — empty or short evidence is rejected.
                input_verified: True if you checked the tool call's INPUT
                    params (e.g. confirmed period=annual).
                input_note: Description if input_verified (e.g.
                    "confirmed period=annual").

            Returns:
                Confirmation with claim ID, or ERROR if evidence missing.
            """
            valid_agents = ("fundamental", "technical", "value", "macro")
            if agent not in valid_agents:
                return f"ERROR: invalid agent '{agent}'. Must be one of: {', '.join(valid_agents)}"

            valid_verdicts = ("found", "derived", "not-found")
            if verdict not in valid_verdicts:
                return f"ERROR: invalid verdict '{verdict}'. Must be one of: {', '.join(valid_verdicts)}"

            if verdict != "not-found" and (
                not grep_evidence or len(grep_evidence.strip()) < _MIN_EVIDENCE_LEN
            ):
                return ("ERROR: grep_evidence is required and must contain actual "
                        "grep_trace output (min 20 chars). Call grep_trace() first, "
                        "then paste the relevant match line here.")

            # Verify grep evidence against actual grep history
            if verdict not in ("not-found", "derived"):
                ok, err = _verify_grep_evidence(grep_evidence)
                if not ok:
                    enforcement_log.append({
                        "tool": "record_specialist_claim",
                        "claim": claim[:100],
                        "agent": agent,
                        "verdict": verdict,
                        "reason": err,
                        "timestamp": time.time(),
                    })
                    return f"ERROR: {err}"

            # Verify claim text appears in the specialist output
            ok, err = verify_ciso(claim, agent)
            if not ok:
                enforcement_log.append({
                    "tool": "record_specialist_claim",
                    "claim": claim[:100],
                    "agent": agent,
                    "verdict": verdict,
                    "reason": err,
                    "timestamp": time.time(),
                })
                return f"ERROR: {err}"

            # Resolve tool call location from grep coordinates
            source_tool, source_index = resolve_tool_call_location(trace_dir, grep_file, grep_line)
            if source_index == -1 and verdict not in ("not-found", "derived"):
                return ("ERROR: cannot resolve tool call from grep_file/grep_line. "
                        f"Got grep_file='{grep_file}', grep_line={grep_line}. "
                        "Check that the file path and line number match your grep output.")

            # Append to JSONL
            citations_dir = trace_dir / "audit" / "specialist_citations"
            citations_dir.mkdir(parents=True, exist_ok=True)
            jsonl_path = citations_dir / f"{agent}.jsonl"

            # Determine claim_id from existing entries
            existing = 0
            if jsonl_path.exists():
                existing = sum(1 for line in jsonl_path.read_text().strip().split("\n") if line.strip())

            claim_id = existing + 1
            entry = {
                "claim_id": claim_id,
                "agent": agent,
                "claim": claim,
                "output_line": output_line,
                "verdict": verdict,
                "source_tool": source_tool,
                "source_index": source_index,
                "grep_file": grep_file,
                "grep_line": grep_line,
                "raw_value": raw_value,
                "grep_evidence": grep_evidence.strip(),
                "input_verified": input_verified,
                "input_note": input_note,
                "timestamp": time.time(),
            }
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            emit("audit.claim_recorded",
                 agent=agent, claim_id=claim_id, verdict=verdict,
                 source_tool=source_tool, source_index=source_index,
                 claim=claim[:100])

            return (f"OK: Recorded specialist claim #{claim_id} for {agent} "
                    f"[{verdict}] — {source_tool}#{source_index}")

        # ---- record_specialist_evidence (R2a — Specialist Evidence Agent) ----
        @tool
        def record_specialist_evidence(
            claim: str,
            claim_in_report: str,
            specialist_agent: str,
            grep_line: int,
            specialist_excerpt: str,
            grep_evidence: str,
            source_type: str = "standard",
        ) -> str:
            """Record evidence that a specialist also stated a report claim.

            You are collecting EVIDENCE, not determining verdicts.
            The program will determine the final verdict after merging all evidence.

            Args:
                claim: The factual claim being verified (your summary).
                claim_in_report: The EXACT sentence(s) from the report that contain
                    this claim. Copy verbatim — this is used for positioning.
                specialist_agent: Which specialist's output contains the match
                    (fundamental, technical, value, macro).
                grep_line: Line number from the grep match in the specialist output.
                    Used to cross-reference with Round 1 claims for tool call tracking.
                specialist_excerpt: EXACT text from the specialist output that
                    states or supports this claim. Copy verbatim.
                grep_evidence: The grep_trace output proving the match.
                    REQUIRED — paste the relevant grep result lines.
                source_type: Type of source. One of: standard, kb, web,
                    derived, computation. Default: standard.

            Returns:
                Confirmation or ERROR.
            """
            valid_agents = ("fundamental", "technical", "value", "macro")
            if specialist_agent not in valid_agents:
                return f"ERROR: invalid specialist_agent. Must be: {', '.join(valid_agents)}"

            valid_types = ("standard", "kb", "web", "derived", "computation")
            if source_type not in valid_types:
                return f"ERROR: invalid source_type. Must be: {', '.join(valid_types)}"

            # Verify grep evidence (skip for derived/kb/web that might not have direct grep)
            if source_type in ("standard", "computation"):
                ok, err = _verify_grep_evidence(grep_evidence)
                if not ok:
                    enforcement_log.append({
                        "tool": "record_specialist_evidence",
                        "claim": claim[:100],
                        "specialist_agent": specialist_agent,
                        "reason": err,
                        "timestamp": time.time(),
                    })
                    return f"ERROR: {err}"

            # Verify claim_in_report is actual report text
            ok, err = verify_cir(claim_in_report)
            if not ok:
                enforcement_log.append({
                    "tool": "record_specialist_evidence",
                    "claim": claim[:100],
                    "claim_in_report": claim_in_report[:200],
                    "reason": err,
                    "timestamp": time.time(),
                })
                return f"ERROR: {err}"

            # R1 cross-reference: find the source tool call via R1 claims
            source_tool, source_index, r1_claim_id = "", -1, None
            r1_claims = _load_r1_claims_for_agent(trace_dir, specialist_agent)
            if r1_claims:
                best_r1 = _find_nearest_r1_claim(r1_claims, grep_line, claim)
                if best_r1:
                    source_tool = best_r1.get("source_tool", "")
                    source_index = best_r1.get("source_index", -1)
                    r1_claim_id = best_r1.get("claim_id")

            # Write to JSONL
            jsonl_path = trace_dir / "audit" / "specialist_evidence.jsonl"
            jsonl_path.parent.mkdir(parents=True, exist_ok=True)

            existing = _count_jsonl_lines(jsonl_path)
            entry = {
                "id": existing + 1,
                "claim": claim,
                "claim_in_report": claim_in_report,
                "specialist_agent": specialist_agent,
                "grep_line": grep_line,
                "specialist_excerpt": specialist_excerpt,
                "grep_evidence": grep_evidence.strip(),
                "source_type": source_type,
                "source_tool": source_tool,
                "source_index": source_index,
                "r1_claim_id": r1_claim_id,
                "timestamp": time.time(),
            }
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            emit("audit.evidence_recorded",
                 evidence_type="specialist", id=existing + 1,
                 specialist_agent=specialist_agent,
                 source_tool=source_tool,
                 source_index=source_index,
                 claim=claim[:100])

            return f"OK: Recorded specialist evidence #{existing + 1} — {specialist_agent}"

        # ---- record_source_evidence (R2b — Source Evidence Agent) ----
        @tool
        def record_source_evidence(
            claim: str,
            claim_in_report: str,
            grep_file: str,
            grep_line: int,
            raw_value: str,
            grep_evidence: str,
            source_type: str = "standard",
        ) -> str:
            """Record evidence that raw source data supports a report claim.

            You are collecting EVIDENCE, not determining verdicts.
            The program will determine the final verdict after merging all evidence.

            Args:
                claim: The factual claim being verified (your summary).
                claim_in_report: The EXACT sentence(s) from the report that contain
                    this claim. Copy verbatim — this is used for positioning.
                grep_file: File path from grep output (e.g.
                    "tools/fundamental_tool_calls.json").
                grep_line: Line number from grep output (e.g. 18).
                raw_value: The exact value from the raw data. Copy verbatim.
                grep_evidence: The grep_trace output proving the match.
                    REQUIRED — paste the relevant grep result lines.
                source_type: Type of source. One of: standard, kb, web,
                    derived, computation. Default: standard.

            Returns:
                Confirmation or ERROR.
            """
            valid_types = ("standard", "kb", "web", "derived", "computation")
            if source_type not in valid_types:
                return f"ERROR: invalid source_type. Must be: {', '.join(valid_types)}"

            # Verify grep evidence
            if source_type in ("standard", "computation"):
                ok, err = _verify_grep_evidence(grep_evidence)
                if not ok:
                    enforcement_log.append({
                        "tool": "record_source_evidence",
                        "claim": claim[:100],
                        "grep_file": grep_file,
                        "reason": err,
                        "timestamp": time.time(),
                    })
                    return f"ERROR: {err}"

            # Verify claim_in_report is actual report text
            ok, err = verify_cir(claim_in_report)
            if not ok:
                enforcement_log.append({
                    "tool": "record_source_evidence",
                    "claim": claim[:100],
                    "claim_in_report": claim_in_report[:200],
                    "reason": err,
                    "timestamp": time.time(),
                })
                return f"ERROR: {err}"

            # Auto-resolve agent and tool call from grep coordinates
            source_agent = _extract_agent_from_grep_file(grep_file)
            source_tool, source_index = resolve_tool_call_location(trace_dir, grep_file, grep_line)

            # For standard/computation, agent must be resolvable
            if not source_agent and source_type in ("standard", "computation"):
                return f"ERROR: cannot determine source_agent from grep_file='{grep_file}'"

            valid_agents = ("fundamental", "technical", "value", "macro", "core_analysis")
            if source_agent and source_agent not in valid_agents:
                return f"ERROR: resolved source_agent '{source_agent}' not recognized. Must be: {', '.join(valid_agents)}"

            # Write to JSONL
            jsonl_path = trace_dir / "audit" / "source_evidence.jsonl"
            jsonl_path.parent.mkdir(parents=True, exist_ok=True)

            existing = _count_jsonl_lines(jsonl_path)
            entry = {
                "id": existing + 1,
                "claim": claim,
                "claim_in_report": claim_in_report,
                "source_agent": source_agent,
                "source_tool": source_tool,
                "source_index": source_index,
                "grep_file": grep_file,
                "grep_line": grep_line,
                "raw_value": raw_value,
                "grep_evidence": grep_evidence.strip(),
                "source_type": source_type,
                "timestamp": time.time(),
            }
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            emit("audit.evidence_recorded",
                 evidence_type="source", id=existing + 1,
                 source_agent=source_agent, source_tool=source_tool,
                 source_index=source_index,
                 claim=claim[:100])

            return f"OK: Recorded source evidence #{existing + 1} — {source_agent}/{source_tool}"

        # ---- list_trace_files ----
        @tool
        def list_trace_files(subdir: str = "") -> str:
            """List files in the execution trace directory.

            Args:
                subdir: Optional subdirectory to list (e.g. "trace/prompts",
                    "tools", "trace/react_steps").  Defaults to showing
                    the top-level structure.

            Returns:
                File listing with sizes, organized by directory.
            """
            if subdir:
                resolved = resolve_path(subdir)
                if resolved is None:
                    return f"ERROR: path '{subdir}' is outside the trace directory."
                if not resolved.exists():
                    return f"ERROR: directory not found: {subdir}"
                root = resolved
            else:
                root = trace_dir

            lines: list[str] = []

            if root.is_file():
                size = root.stat().st_size
                lines.append(f"  {root.name} ({_fmt_size(size)})")
            else:
                for dirpath, dirnames, filenames in os.walk(root):
                    dirnames.sort()
                    rel_dir = Path(dirpath).relative_to(trace_dir)
                    depth = len(rel_dir.parts)
                    indent = "  " * depth

                    if rel_dir != Path("."):
                        lines.append(f"{indent}{rel_dir.name}/")

                    for fname in sorted(filenames):
                        fpath = Path(dirpath) / fname
                        size = fpath.stat().st_size
                        lines.append(f"{indent}  {fname} ({_fmt_size(size)})")

            # Note the external report if available
            if not subdir and report_path and report_path.exists():
                size = report_path.stat().st_size
                lines.append(f"  [external] report.md ({_fmt_size(size)})")

            if not lines:
                return "Empty directory."

            header = f"Trace directory: {trace_dir.name}\n"
            return header + "\n".join(lines)

        self._tools = {
            "read_trace_file": read_trace_file,
            "grep_trace": grep_trace,
            "list_trace_files": list_trace_files,
            "read_tool_call": read_tool_call,
            "read_trace_section": read_trace_section,
            "record_specialist_claim": record_specialist_claim,
            "record_specialist_evidence": record_specialist_evidence,
            "record_source_evidence": record_source_evidence,
        }


def _fmt_size(size: int) -> str:
    """Format byte count as human-readable string."""
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size / (1024 * 1024):.1f}MB"
