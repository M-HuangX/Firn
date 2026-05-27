"""Token usage & cost tracker — CLI query for historical LLM consumption.

Scans ``logs/`` execution directories and aggregates token usage from
per-agent JSON files.  Supports filtering by date range and provides
per-run and per-agent breakdowns.

Usage::

    uv run python -m src --cost          # all-time summary
    uv run python -m src --cost 7        # last 7 days
    uv run python -m src --cost 30       # last 30 days
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

_LOGS_DIR = Path(__file__).resolve().parents[2] / "logs"

# DeepSeek pricing (per 1M tokens) — update if provider changes
_PRICING = {
    "deepseek": {
        "input": 0.27,       # $0.27 / 1M input (cache miss)
        "input_cached": 0.07, # $0.07 / 1M input (cache hit)
        "output": 1.10,      # $1.10 / 1M output
    },
}


def _parse_run_date(run_id: str) -> datetime | None:
    """Extract datetime from execution ID like '20260512_141531_f72e0fdf'."""
    try:
        return datetime.strptime(run_id[:15], "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    except (ValueError, IndexError):
        return None


def _classify_run(agents_dir: Path) -> str:
    """Classify a run as 'analysis', 'digest', or 'audit' based on agent files."""
    names = {f.stem for f in agents_dir.glob("*.json")}
    if "digest" in names or "digest_agent" in names:
        return "digest"
    if any("audit" in n for n in names):
        return "audit"
    if names & {"fundamental", "technical", "value", "summary"}:
        return "analysis"
    return "other"


def gather_token_data(
    last_n_days: int | None = None,
) -> list[dict]:
    """Scan logs/ and return per-run token summaries.

    Returns a list of dicts, each with:
      run_id, run_date, run_type, agents: {name: {prompt_tokens, completion_tokens, ...}},
      total_prompt, total_completion, total_tokens
    """
    if not _LOGS_DIR.is_dir():
        return []

    cutoff = None
    if last_n_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=last_n_days)

    runs = []
    for run_dir in sorted(_LOGS_DIR.iterdir()):
        if not run_dir.is_dir() or run_dir.name in ("latest", "__pycache__"):
            continue

        run_date = _parse_run_date(run_dir.name)
        if run_date is None:
            continue
        if cutoff and run_date < cutoff:
            continue

        agents_dir = run_dir / "agents"
        if not agents_dir.is_dir():
            continue

        run_total_prompt = 0
        run_total_completion = 0
        run_total_tokens = 0
        agent_data = {}

        for f in agents_dir.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            tu = d.get("token_usage", {})
            if not tu:
                continue
            name = d.get("agent_name", f.stem)
            prompt = tu.get("prompt_tokens", 0)
            completion = tu.get("completion_tokens", 0)
            total = tu.get("total_tokens", 0) or (prompt + completion)
            reasoning = tu.get("reasoning_tokens")
            cache_hit = tu.get("prompt_cache_hit_tokens", 0)
            cache_miss = tu.get("prompt_cache_miss_tokens", 0)

            agent_data[name] = {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": total,
                "reasoning_tokens": reasoning,
                "cache_hit": cache_hit,
                "cache_miss": cache_miss,
            }
            run_total_prompt += prompt
            run_total_completion += completion
            run_total_tokens += total

        if not agent_data:
            continue

        runs.append({
            "run_id": run_dir.name,
            "run_date": run_date,
            "run_type": _classify_run(agents_dir),
            "agents": agent_data,
            "total_prompt": run_total_prompt,
            "total_completion": run_total_completion,
            "total_tokens": run_total_tokens,
        })

    return runs


def _estimate_cost(runs: list[dict], provider: str = "deepseek") -> dict:
    """Estimate cost in USD based on token counts and provider pricing."""
    pricing = _PRICING.get(provider, _PRICING["deepseek"])

    total_input = sum(r["total_prompt"] for r in runs)
    total_output = sum(r["total_completion"] for r in runs)
    total_cache_hit = sum(
        sum(a.get("cache_hit", 0) for a in r["agents"].values())
        for r in runs
    )
    total_cache_miss = sum(
        sum(a.get("cache_miss", 0) for a in r["agents"].values())
        for r in runs
    )

    # If cache breakdown available, use it; otherwise treat all input as cache-miss
    if total_cache_hit or total_cache_miss:
        input_cost = (total_cache_hit * pricing["input_cached"] + total_cache_miss * pricing["input"]) / 1_000_000
    else:
        input_cost = total_input * pricing["input"] / 1_000_000

    output_cost = total_output * pricing["output"] / 1_000_000

    return {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cache_hit_tokens": total_cache_hit,
        "cache_miss_tokens": total_cache_miss,
        "input_cost_usd": input_cost,
        "output_cost_usd": output_cost,
        "total_cost_usd": input_cost + output_cost,
    }


def print_cost_summary(last_n_days: int | None = None) -> None:
    """Print a formatted token usage summary to stdout."""
    runs = gather_token_data(last_n_days=last_n_days)

    if not runs:
        period = f"last {last_n_days} days" if last_n_days else "all time"
        print(f"No runs with token data found ({period}).")
        return

    # Header
    period = f"last {last_n_days} days" if last_n_days else "all time"
    date_range = f"{runs[0]['run_date'].strftime('%Y-%m-%d')} ~ {runs[-1]['run_date'].strftime('%Y-%m-%d')}"
    print(f"\n=== Token Usage Summary ({period}) ===")
    print(f"Date range: {date_range}")
    print(f"Runs with token data: {len(runs)}")

    # Per-type breakdown
    type_counts: dict[str, int] = defaultdict(int)
    type_tokens: dict[str, int] = defaultdict(int)
    for r in runs:
        type_counts[r["run_type"]] += 1
        type_tokens[r["run_type"]] += r["total_tokens"]

    print(f"\n--- By Run Type ---")
    print(f"{'Type':<12} {'Runs':>6} {'Tokens':>14} {'Avg/Run':>12}")
    print(f"{'-'*12} {'-'*6} {'-'*14} {'-'*12}")
    for rtype in sorted(type_counts.keys()):
        cnt = type_counts[rtype]
        tok = type_tokens[rtype]
        avg = tok // cnt if cnt else 0
        print(f"{rtype:<12} {cnt:>6} {tok:>14,} {avg:>12,}")

    # Per-agent breakdown
    agent_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"prompt": 0, "completion": 0, "total": 0, "runs": 0})
    for r in runs:
        for name, data in r["agents"].items():
            agent_totals[name]["prompt"] += data["prompt_tokens"]
            agent_totals[name]["completion"] += data["completion_tokens"]
            agent_totals[name]["total"] += data["total_tokens"]
            agent_totals[name]["runs"] += 1

    print(f"\n--- By Agent ---")
    print(f"{'Agent':<16} {'Runs':>5} {'Input':>12} {'Output':>12} {'Total':>14}")
    print(f"{'-'*16} {'-'*5} {'-'*12} {'-'*12} {'-'*14}")
    for name in sorted(agent_totals.keys(), key=lambda n: -agent_totals[n]["total"]):
        d = agent_totals[name]
        print(f"{name:<16} {d['runs']:>5} {d['prompt']:>12,} {d['completion']:>12,} {d['total']:>14,}")

    # Grand total + cost estimate
    cost = _estimate_cost(runs)
    total = sum(r["total_tokens"] for r in runs)

    print(f"\n--- Grand Total ---")
    print(f"Input tokens:    {cost['input_tokens']:>14,}")
    print(f"Output tokens:   {cost['output_tokens']:>14,}")
    print(f"Total tokens:    {total:>14,}")
    if cost["cache_hit_tokens"]:
        print(f"Cache hit:       {cost['cache_hit_tokens']:>14,}")
        print(f"Cache miss:      {cost['cache_miss_tokens']:>14,}")

    print(f"\n--- Estimated Cost (DeepSeek) ---")
    print(f"Input:   ${cost['input_cost_usd']:>8.2f}")
    print(f"Output:  ${cost['output_cost_usd']:>8.2f}")
    print(f"Total:   ${cost['total_cost_usd']:>8.2f}")

    # Recent runs (last 5)
    print(f"\n--- Recent Runs (last 5) ---")
    print(f"{'Run ID':<28} {'Type':<10} {'Tokens':>12}")
    print(f"{'-'*28} {'-'*10} {'-'*12}")
    for r in runs[-5:]:
        print(f"{r['run_id']:<28} {r['run_type']:<10} {r['total_tokens']:>12,}")
    print()
