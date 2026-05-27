"""Audit Manifest Generator — builds structured context from a trace directory.

Produces a markdown manifest that serves as the Audit Agent's primary input:
  Part 1: Pipeline overview table (agents, files, relationships)
  Part 2: Core reasoning chain (ReAct step summaries with tool references)
"""

from __future__ import annotations

import json
from pathlib import Path


def generate_analysis_manifest(trace_dir: Path, report_path: Path | None = None) -> str:
    """Generate an audit manifest for an analysis (``--ticker``) run.

    Parameters
    ----------
    trace_dir : Path
        The execution directory (``logs/<exec_id>/``).
    report_path : Path | None
        Path to the final report (may be outside trace_dir).

    Returns
    -------
    str
        Structured markdown manifest.
    """
    exec_id = trace_dir.name
    parts: list[str] = []

    # ── Header ──
    parts.append(f"# Audit Manifest — {exec_id}\n")

    # ── Execution info ──
    info = _load_json(trace_dir / "execution_info.json")
    if info:
        parts.append(f"- **Start**: {info.get('start_time', '?')}")
        parts.append(f"- **Duration**: {info.get('total_seconds', '?'):.1f}s")
        parts.append(f"- **Status**: {'SUCCESS' if info.get('success') else 'FAILED'}")
        parts.append("")

    # ── Part 1: Pipeline Overview Table ──
    parts.append("## Part 1: Pipeline Overview\n")
    parts.append("| Phase | Agent | System Prompt | User Prompt | Tool Data | Output |")
    parts.append("|-------|-------|--------------|-------------|-----------|--------|")

    # Discover specialists from trace/prompts/
    prompts_dir = trace_dir / "trace" / "prompts"
    specialists = _discover_agents(prompts_dir, exclude={"core_analysis"})
    core_agents = _discover_agents(prompts_dir, include={"core_analysis"})

    for i, agent in enumerate(sorted(specialists), 1):
        sys_prompt = _prompt_path(prompts_dir, agent, "system")
        user_prompt = _prompt_path(prompts_dir, agent, "user")
        tool_file = _tool_calls_path(trace_dir / "tools", agent)
        output = f"§{agent.upper()} in core_analysis user prompt"
        parts.append(
            f"| {i} | {agent} | {sys_prompt} | {user_prompt} | {tool_file} | {output} |"
        )

    # Core analysis phase
    for agent in sorted(core_agents):
        phase = len(specialists) + 1
        sys_prompt = _prompt_path(prompts_dir, agent, "system")
        user_prompt = _prompt_path(prompts_dir, agent, "user")
        tool_file = _tool_calls_path(trace_dir / "tools", agent)
        output = "reports/final_report.md (or report.md)"
        parts.append(
            f"| {phase} | {agent} | {sys_prompt} | {user_prompt} | {tool_file} | {output} |"
        )

    parts.append("")

    # ── Part 2: Core Reasoning Chain ──
    parts.append("## Part 2: Core Reasoning Chain\n")

    steps_file = trace_dir / "trace" / "react_steps" / "core_analysis_steps.jsonl"
    if steps_file.exists():
        steps = _load_jsonl(steps_file)
        for step in steps:
            step_num = step.get("step", "?")
            tool_calls = step.get("output", {}).get("tool_calls", [])
            output_text = step.get("output", {}).get("text", "")

            # Tool summary
            if tool_calls:
                tool_summary = ", ".join(
                    _format_tool_call(tc) for tc in tool_calls
                )
                parts.append(f"### Step {step_num} | Tools: {tool_summary}")
                # Reference the tool data file
                parts.append(
                    f"Data accessed: tools/core_analysis_tool_calls.json"
                )
            else:
                parts.append(f"### Step {step_num} | No tools (synthesis)")

            # Output text (truncated for manifest — full text accessible via tool)
            if output_text:
                preview = output_text[:500]
                if len(output_text) > 500:
                    preview += "..."
                parts.append(f"> {preview}")

            parts.append("")
    else:
        parts.append("*No ReAct steps found for core_analysis.*\n")

    # ── Specialist Step Summaries ──
    parts.append("## Specialist Agent Steps (summary)\n")
    steps_dir = trace_dir / "trace" / "react_steps"
    if steps_dir.exists():
        for agent in sorted(specialists):
            agent_steps_file = steps_dir / f"{agent}_steps.jsonl"
            if agent_steps_file.exists():
                steps = _load_jsonl(agent_steps_file)
                total = len(steps)
                tool_names = set()
                for s in steps:
                    for tc in s.get("output", {}).get("tool_calls", []):
                        tool_names.add(tc.get("name", "?"))
                tools_used = ", ".join(sorted(tool_names)) if tool_names else "none"
                parts.append(
                    f"- **{agent}**: {total} steps, tools used: {tools_used} "
                    f"(see trace/react_steps/{agent}_steps.jsonl)"
                )
        parts.append("")

    # ── Report Info ──
    parts.append("## Report Location\n")
    if report_path and report_path.exists():
        size = report_path.stat().st_size
        parts.append(
            f"- Report file: `report.md` ({size:,} bytes) — "
            f"read via `read_trace_file('report.md')`"
        )
    else:
        report_in_trace = trace_dir / "reports" / "final_report.md"
        if report_in_trace.exists():
            size = report_in_trace.stat().st_size
            parts.append(
                f"- Report file: `reports/final_report.md` ({size:,} bytes) — "
                f"read via `read_trace_file('reports/final_report.md')`"
            )
        else:
            parts.append("- **WARNING**: No report file found.")
    parts.append("")

    # ── Available Files Summary ──
    parts.append("## Available Trace Files\n")
    parts.append("Use `list_trace_files()` for full listing, or read specific files:")
    parts.append("- `read_trace_file('report.md')` — the final report to audit")
    parts.append("- `read_trace_file('tools/<agent>_tool_calls.json')` — raw MCP/KB tool returns")
    parts.append("- `read_trace_file('trace/prompts/<agent>_user.txt')` — what the agent received")
    parts.append("- `grep_trace('<number or claim>')` — search for specific values across all files")
    parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Digest Manifest
# ---------------------------------------------------------------------------


def generate_digest_manifest(trace_dir: Path) -> str:
    """Generate an audit manifest for a digest (``--digest``) run.

    A digest audit verifies that facts written to the Knowledge Base
    faithfully represent the source articles that were digested.

    Parameters
    ----------
    trace_dir : Path
        The execution directory (``logs/<exec_id>/``).

    Returns
    -------
    str
        Structured markdown manifest for digest audit.
    """
    exec_id = trace_dir.name
    parts: list[str] = []

    # ── Header ──
    parts.append(f"# Digest Audit Manifest — {exec_id}\n")

    # ── Execution info ──
    info = _load_json(trace_dir / "execution_info.json")
    if info:
        parts.append(f"- **Start**: {info.get('start_time', '?')}")
        dur = info.get("total_seconds")
        if dur:
            parts.append(f"- **Duration**: {dur:.1f}s")
        parts.append(f"- **Status**: {'SUCCESS' if info.get('success') else 'FAILED'}")
        parts.append("")

    # ── Part 1: Batch Overview ──
    parts.append("## Part 1: Batch Overview\n")

    # Discover batches from prompt files
    prompts_dir = trace_dir / "trace" / "prompts"
    batches = _discover_digest_batches(prompts_dir)

    if batches:
        parts.append("| Batch | System Prompt | User Prompt | Tool Data |")
        parts.append("|-------|--------------|-------------|-----------|")
        for batch_num, sys_file, user_file in batches:
            tool_file = _digest_tool_calls_path(trace_dir / "tools", batch_num)
            parts.append(f"| {batch_num} | {sys_file} | {user_file} | {tool_file} |")
        parts.append("")
    else:
        parts.append("*No digest batch prompts found in trace.*\n")

    # ── Part 2: KB Write Actions (auditable operations) ──
    parts.append("## Part 2: KB Write Actions (audit targets)\n")
    parts.append(
        "These are the knowledge base modifications made during this digest session. "
        "Each kb_write/kb_edit/kb_write_core_mind action should be faithful to "
        "the source articles that were read.\n"
    )

    steps_file = trace_dir / "trace" / "react_steps" / "core_digest_steps.jsonl"
    if steps_file.exists():
        steps = _load_jsonl(steps_file)
        write_steps = []
        read_steps = []
        other_steps = []

        for step in steps:
            tool_calls = step.get("output", {}).get("tool_calls", [])
            tool_names = [tc.get("name", "") for tc in tool_calls]

            if any(n in ("kb_write", "kb_edit", "kb_write_core_mind", "kb_archive") for n in tool_names):
                write_steps.append(step)
            elif any(n == "read_inbox_item" for n in tool_names):
                read_steps.append(step)
            else:
                other_steps.append(step)

        # Summarize reads
        if read_steps:
            read_slugs = []
            for s in read_steps:
                for tc in s.get("output", {}).get("tool_calls", []):
                    if tc.get("name") == "read_inbox_item":
                        slug = tc.get("args", {}).get("slug", "?")
                        read_slugs.append(slug)
            parts.append(
                f"**Articles read**: {len(read_steps)} steps reading "
                f"{len(read_slugs)} items: {', '.join(read_slugs[:10])}"
            )
            if len(read_slugs) > 10:
                parts.append(f"  ... and {len(read_slugs) - 10} more")
            parts.append("")

        # Detail write actions
        if write_steps:
            for step in write_steps:
                step_num = step.get("step", "?")
                tool_calls = step.get("output", {}).get("tool_calls", [])
                output_text = step.get("output", {}).get("text", "")

                tool_summary = ", ".join(
                    _format_tool_call(tc) for tc in tool_calls
                    if tc.get("name") in ("kb_write", "kb_edit", "kb_write_core_mind", "kb_archive")
                )
                parts.append(f"### Step {step_num} | KB writes: {tool_summary}")

                if output_text:
                    preview = output_text[:400]
                    if len(output_text) > 400:
                        preview += "..."
                    parts.append(f"> {preview}")
                parts.append("")
        else:
            parts.append("*No KB write actions found in steps.*\n")

        # Summary stats
        parts.append(f"**Step summary**: {len(steps)} total steps — "
                     f"{len(read_steps)} reads, {len(write_steps)} writes, "
                     f"{len(other_steps)} other (search/synthesis)")
        parts.append("")
    else:
        parts.append("*No ReAct steps found for core_digest.*\n")

    # ── Part 3: Available Trace Files ──
    parts.append("## Available Trace Files\n")
    parts.append("Use `list_trace_files()` for full listing, or read specific files:")
    parts.append("- `read_trace_file('tools/core_digest_tool_calls.json')` — all tool calls with KB write content")
    parts.append("- `read_trace_file('trace/prompts/core_digest_user.txt')` — batch input (article catalog)")
    parts.append("- `grep_trace('kb_write')` — find all KB write actions")
    parts.append("- `grep_trace('<keyword>')` — search for specific facts across all files")
    parts.append("")
    parts.append(
        "**Audit focus**: For each kb_write, verify the written content faithfully "
        "represents the source article(s). Check for: factual accuracy, no hallucinated "
        "details, correct attribution of dates/sources, appropriate theme categorization."
    )
    parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _discover_agents(prompts_dir: Path, exclude: set[str] | None = None,
                     include: set[str] | None = None) -> list[str]:
    """Discover agent names from prompt files in trace/prompts/."""
    agents: set[str] = set()
    if not prompts_dir.exists():
        return []
    for f in prompts_dir.iterdir():
        if f.suffix != ".txt":
            continue
        name = f.stem
        # Strip _system / _user / _b2_system etc.
        for suffix in ("_system", "_user"):
            if name.endswith(suffix):
                name = name[:-(len(suffix))]
                break
        # Strip batch prefix _b2, _b3 etc.
        import re
        name = re.sub(r"_b\d+$", "", name)
        agents.add(name)

    if include:
        agents = agents & include
    if exclude:
        agents = agents - exclude
    return sorted(agents)


def _prompt_path(prompts_dir: Path, agent: str, role: str) -> str:
    """Return the relative path string for an agent's prompt file."""
    base = f"trace/prompts/{agent}_{role}.txt"
    if (prompts_dir / f"{agent}_{role}.txt").exists():
        return base
    return f"{base} (missing)"


def _tool_calls_path(tools_dir: Path, agent: str) -> str:
    """Return the relative path string for an agent's tool calls file."""
    base = f"tools/{agent}_tool_calls.json"
    if (tools_dir / f"{agent}_tool_calls.json").exists():
        return base
    return f"{base} (missing)"


def _format_tool_call(tc: dict) -> str:
    """Format a single tool call for display."""
    name = tc.get("name", "?")
    args = tc.get("args", {})
    if isinstance(args, dict):
        # Show first arg value for context
        first_vals = []
        for k, v in list(args.items())[:2]:
            val_str = str(v)
            if len(val_str) > 40:
                val_str = val_str[:40] + "..."
            first_vals.append(f"{k}={val_str}")
        if first_vals:
            return f"{name}({', '.join(first_vals)})"
    return name


def _discover_digest_batches(prompts_dir: Path) -> list[tuple[int, str, str]]:
    """Discover digest batch prompt files.

    Returns list of (batch_num, system_prompt_path, user_prompt_path).
    """
    if not prompts_dir.exists():
        return []

    batches: list[tuple[int, str, str]] = []

    # Batch 1: core_digest_system.txt / core_digest_user.txt
    sys1 = prompts_dir / "core_digest_system.txt"
    usr1 = prompts_dir / "core_digest_user.txt"
    if sys1.exists() or usr1.exists():
        batches.append((
            1,
            "trace/prompts/core_digest_system.txt" if sys1.exists() else "(missing)",
            "trace/prompts/core_digest_user.txt" if usr1.exists() else "(missing)",
        ))

    # Batch 2+: core_digest_b2_system.txt etc.
    n = 2
    while True:
        sys_n = prompts_dir / f"core_digest_b{n}_system.txt"
        usr_n = prompts_dir / f"core_digest_b{n}_user.txt"
        if not sys_n.exists() and not usr_n.exists():
            break
        batches.append((
            n,
            f"trace/prompts/core_digest_b{n}_system.txt" if sys_n.exists() else "(missing)",
            f"trace/prompts/core_digest_b{n}_user.txt" if usr_n.exists() else "(missing)",
        ))
        n += 1

    return batches


def _digest_tool_calls_path(tools_dir: Path, batch_num: int) -> str:
    """Return the tool calls file path for a digest batch."""
    if batch_num == 1:
        base = "tools/core_digest_tool_calls.json"
        return base if (tools_dir / "core_digest_tool_calls.json").exists() else f"{base} (missing)"
    base = f"tools/core_digest_b{batch_num}_tool_calls.json"
    return base if (tools_dir / f"core_digest_b{batch_num}_tool_calls.json").exists() else f"{base} (missing)"


def _load_json(path: Path) -> dict | None:
    """Load a JSON file, returning None on any error."""
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file, returning a list of dicts."""
    items: list[dict] = []
    if not path.exists():
        return items
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    items.append(json.loads(line))
    except Exception:
        pass
    return items
