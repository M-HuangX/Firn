"""Main workflow — LangGraph StateGraph with parallel fan-out/fan-in.

Graph structure:
  start_node → [fundamental_agent, technical_agent, value_agent, macro_agent] (parallel)
             → core_analysis (waits for all four) → END

Usage:
  uv run python -m src.main --ticker AAPL
  uv run python -m src.main --ticker AAPL --query "Is Apple a good buy?"
  uv run python -m src.main --forward "article text" --source seeking_alpha --ticker NVDA
  uv run python -m src.main --view "Very bullish on AI demand" --ticker NVDA --sentiment bullish
  uv run python -m src.main --divergences
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import dataclasses
import re
import sys
import time
from pathlib import Path

from langgraph.graph import END, StateGraph

from src.agents.core_agent import CoreAgent
from src.agents.fundamental_agent import fundamental_agent
from src.agents.macro_agent import macro_agent
from src.agents.output_handlers import save_report_and_log_prediction
from src.agents.profiles import ANALYSIS_PROFILE
from src.agents.technical_agent import technical_agent
from src.agents.value_agent import value_agent
from src.tools.mcp_client import close_mcp_client
from src.utils.event_log import log_event, new_session_id
from src.utils.execution_logger import (
    ExecutionLogger,
    finalize_execution_logger,
    get_execution_logger,
    initialize_execution_logger,
    set_execution_logger,
)
from src.utils.logging_config import setup_logger
from src.utils.reverse_dcf import calculate_reverse_dcf, format_reverse_dcf_report
from src.utils.state_definition import AgentState

# Valid ticker format: 1-20 chars, alphanumeric + dots + carets + hyphens
_TICKER_RE = re.compile(r"^[A-Z0-9.\-^]{1,20}$")

logger = setup_logger(__name__)


def build_graph() -> StateGraph:
    """Construct and compile the analysis workflow graph."""
    workflow = StateGraph(AgentState)

    # Nodes
    workflow.add_node("start_node", _start_node)
    workflow.add_node("fundamental_analyst", fundamental_agent)
    workflow.add_node("technical_analyst", technical_agent)
    workflow.add_node("value_analyst", value_agent)
    workflow.add_node("macro_analyst", macro_agent)
    workflow.add_node("core_analysis", _run_core_analysis)

    # Entry
    workflow.set_entry_point("start_node")

    # Fan-out: start → 4 parallel agents
    workflow.add_edge("start_node", "fundamental_analyst")
    workflow.add_edge("start_node", "technical_analyst")
    workflow.add_edge("start_node", "value_analyst")
    workflow.add_edge("start_node", "macro_analyst")

    # Fan-in: 4 agents → core_analysis
    workflow.add_edge("fundamental_analyst", "core_analysis")
    workflow.add_edge("technical_analyst", "core_analysis")
    workflow.add_edge("value_analyst", "core_analysis")
    workflow.add_edge("macro_analyst", "core_analysis")

    # core_analysis → END
    workflow.add_edge("core_analysis", END)

    return workflow.compile()


async def _start_node(state: AgentState) -> dict:
    """Validate input and log workflow start."""
    data = dict(state.get("data", {}))
    metadata = dict(state.get("metadata", {}))

    ticker = data.get("ticker")
    if not ticker:
        raise ValueError("No ticker provided in state. Use --ticker argument.")
    if not _TICKER_RE.match(ticker):
        raise ValueError(
            f"Invalid ticker format: '{ticker}'. "
            "Expected 1-20 alphanumeric characters (e.g., AAPL, NESN.SW, ^GSPC)."
        )

    metadata["workflow_start_time"] = time.time()
    logger.info("Workflow started for ticker: %s", ticker)
    return {"data": data, "messages": [], "metadata": metadata}


async def _precompute_implied_expectations(ticker: str) -> str | None:
    """Fetch price/FCF/EPS from yfinance and compute reverse DCF pre-analysis.

    Returns a formatted markdown section, or None if the ticker is an ETF
    or data is insufficient. Errors are logged but never propagate.
    """
    try:
        import yfinance as yf

        yf_ticker = yf.Ticker(ticker)
        info = await asyncio.to_thread(getattr, yf_ticker, "info")

        if not info or not info.get("shortName"):
            return None

        # Skip non-equity instruments (ETFs, indices, etc.)
        if info.get("quoteType", "EQUITY") != "EQUITY":
            logger.info("Skipping implied expectations for non-equity: %s", ticker)
            return None

        price = info.get("currentPrice") or info.get("regularMarketPrice")
        shares = info.get("sharesOutstanding")
        fcf = info.get("freeCashflow")
        eps = info.get("trailingEps")
        forward_eps = info.get("forwardEps")

        result = calculate_reverse_dcf(
            current_price=price,
            shares_outstanding=shares,
            current_fcf=fcf,
            current_eps=eps,
        )

        if "error" in result and result.get("implied_growth_rate") is None:
            logger.info("Reverse DCF unavailable for %s: %s", ticker, result["error"])
            return None

        # Estimate analyst consensus growth from forward vs trailing EPS
        analyst_growth = None
        if forward_eps and eps and eps > 0:
            analyst_growth = (forward_eps - eps) / eps

        # Save verification sidecar for Audit Agent
        try:
            el = get_execution_logger()
            el.log_verification("reverse_dcf", {
                "module": "reverse_dcf",
                "description": (
                    "Binary-search DCF solver: given current price and cash flow per share, "
                    "back-solves for the implied annual growth rate that justifies the price. "
                    "Formula: V = sum(CF*(1+g)^t / (1+r)^t, t=1..n) + TV/(1+r)^n, "
                    "where TV = CF*(1+g)^n * (1+g_term) / (r - g_term). "
                    "Also produces sensitivity table (implied growth at different discount rates) "
                    "and valuation grid (fair value at different growth assumptions)."
                ),
                "ticker": ticker,
                "inputs": {
                    "current_price": price,
                    "shares_outstanding": shares,
                    "current_fcf": fcf,
                    "current_eps": eps,
                    "forward_eps": forward_eps,
                    "discount_rate": 0.10,
                    "terminal_growth": 0.03,
                    "projection_years": 5,
                },
                "result": result,
                "analyst_consensus_growth": analyst_growth,
            })
        except Exception:
            logger.debug("Failed to save reverse_dcf verification sidecar", exc_info=True)

        report = format_reverse_dcf_report(result, ticker, analyst_growth)
        logger.info(
            "Pre-computed implied expectations for %s: implied growth %.1f%%",
            ticker,
            (result["implied_growth_rate"] or 0) * 100,
        )
        return report

    except Exception:
        logger.debug("Failed to pre-compute implied expectations for %s", ticker, exc_info=True)
        return None


async def _run_core_analysis(state: AgentState) -> dict:
    """Synthesize specialist analyses using CoreAgent with ANALYSIS_PROFILE."""
    execution_logger = get_execution_logger()
    data = dict(state.get("data", {}))
    messages = list(state.get("messages", []))
    metadata = dict(state.get("metadata", {}))

    ticker = data.get("ticker", "UNKNOWN")
    t0 = time.time()

    # Gather analyses from upstream agents
    fundamental = data.get("fundamental_analysis", "Not available — agent did not produce output.")
    technical = data.get("technical_analysis", "Not available — agent did not produce output.")
    value = data.get("value_analysis", "Not available — agent did not produce output.")
    macro = data.get("macro_analysis", "Not available — agent did not produce output.")

    # Save specialist outputs as independent files for full-chain audit (D36.1)
    if execution_logger:
        specialist_outputs = {
            "fundamental": fundamental,
            "technical": technical,
            "value": value,
            "macro": macro,
        }
        outputs_dir = execution_logger.execution_dir / "trace" / "specialist_outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M UTC")
        for name, text in specialist_outputs.items():
            header = f"<!-- agent: {name} | ticker: {ticker} | generated: {ts} -->\n\n"
            (outputs_dir / f"{name}_output.md").write_text(
                header + text, encoding="utf-8"
            )
        logger.info("Saved specialist outputs to %s", outputs_dir)

    # Collect any errors
    errors = []
    for key in ("fundamental_analysis_error", "technical_analysis_error",
                "value_analysis_error", "macro_analysis_error"):
        if key in data:
            errors.append(f"- {key}: {data[key]}")
    error_section = ""
    if errors:
        error_section = "\n## ANALYSIS ERRORS (handle gracefully):\n" + "\n".join(errors)

    # Build input for CoreAgent
    query = data.get("query", "")
    implied = data.get("implied_expectations", "")
    implied_section = ""
    if implied:
        implied_section = f"""
---

## IMPLIED EXPECTATIONS (pre-computed reverse DCF):
{implied}
"""

    input_data = f"""Generate a comprehensive dual-perspective report for **{ticker}**.

User's original query: {query}

---

## FUNDAMENTAL ANALYSIS:
{fundamental}

---

## TECHNICAL ANALYSIS:
{technical}

---

## VALUE ANALYSIS:
{value}

---

## MACRO ENVIRONMENT ANALYSIS:
{macro}
{implied_section}
{error_section}

Please produce the full report now."""

    context = {
        "ticker": ticker,
        "timestamp": time.strftime("%Y-%m-%d %H:%M UTC"),
        "event_sid": metadata.get("event_sid", ""),
    }

    try:
        # Wire output handler
        profile = dataclasses.replace(
            ANALYSIS_PROFILE,
            output_handler=save_report_and_log_prediction,
        )

        agent = CoreAgent(profile)
        log_event("analysis.core_start", stage="analysis",
                  sid=metadata.get("event_sid", ""),
                  execution_id=metadata.get("execution_id", ""),
                  ticker=ticker)

        # KB context snapshot — captures what core agent "knows" at synthesis start
        try:
            from src.knowledge_base.kb_api import KnowledgeBase
            _kb = KnowledgeBase()
            _kb.create_snapshot(execution_logger.execution_dir, "context")
        except Exception:
            logger.debug("Failed to create KB context snapshot", exc_info=True)

        report = await agent.run(input_data, context)

        elapsed = time.time() - t0

        data["final_report"] = report
        # Try to get report_path from the reports/ dir (the handler saves it)
        metadata["core_analysis_executed"] = True
        metadata["core_analysis_seconds"] = round(elapsed, 2)
        # For backward compat with the print block in _async_main
        metadata["summary_executed"] = True
        metadata["summary_seconds"] = round(elapsed, 2)

    except Exception as e:
        elapsed = time.time() - t0
        logger.exception("Core analysis failed")
        data["final_report"] = f"# {ticker} Analysis Report\n\n**Error**: {e}\n\nPlease review individual analyses."
        data["summary_error"] = str(e)

    return {"data": data, "messages": messages, "metadata": metadata}


async def run_analysis(ticker: str, query: str | None = None, *, execution_logger: ExecutionLogger | None = None) -> dict:
    """Run the full analysis pipeline for a given ticker.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL", "MSFT", "NESN.SW")
        query: Optional user query for additional context
        execution_logger: Optional pre-created ExecutionLogger instance. When
            provided the caller owns lifecycle management (finalize is NOT called
            here). When None (default), a new singleton logger is created and
            finalized internally — preserving CLI behavior.

    Returns:
        Final state dict with report in data["final_report"]
    """
    _external_logger = execution_logger is not None
    if not _external_logger:
        execution_logger = initialize_execution_logger()
    else:
        # Set as global singleton so output handlers can access it via get_execution_logger()
        set_execution_logger(execution_logger)
    logger.info("Execution log directory: %s", execution_logger.execution_dir)
    exec_id = execution_logger.execution_id

    sid = new_session_id("analysis")
    log_event("analysis.start", stage="analysis", sid=sid,
              execution_id=exec_id, ticker=ticker.upper(), query=query or "")

    # Pre-compute implied expectations (reverse DCF) before fan-out
    implied = await _precompute_implied_expectations(ticker.upper())

    initial_data = {
        "ticker": ticker.upper(),
        "query": query or f"Analyze {ticker.upper()} stock",
    }
    if implied:
        initial_data["implied_expectations"] = implied

    initial_state = AgentState(
        messages=[],
        data=initial_data,
        metadata={"event_sid": sid, "execution_id": exec_id},
    )

    execution_logger.log_agent_start("main", {
        "ticker": ticker.upper(),
        "query": initial_state["data"]["query"],
    })

    t0 = time.time()
    try:
        app = build_graph()
        final_state = await app.ainvoke(initial_state)

        elapsed = time.time() - t0
        log_event("analysis.end", stage="analysis", sid=sid,
                  execution_id=exec_id, success=True,
                  elapsed_s=round(elapsed, 1))
        if not _external_logger:
            finalize_execution_logger(success=True)
        return final_state

    except Exception as e:
        elapsed = time.time() - t0
        log_event("analysis.end", stage="analysis", sid=sid,
                  execution_id=exec_id, success=False,
                  error=str(e)[:200], elapsed_s=round(elapsed, 1))
        logger.exception("Workflow failed")
        if not _external_logger:
            finalize_execution_logger(success=False, error=str(e))
        raise



async def _async_main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Global Market Financial Analysis Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python -m src.main --ticker AAPL
  uv run python -m src.main --ticker MSFT --query "Is Microsoft overvalued?"
  uv run python -m src.main --ticker NESN.SW --query "Nestle dividend analysis"
""",
    )
    parser.add_argument(
        "--ticker", "-t",
        type=str,
        required=False,
        default=None,
        help="Stock ticker symbol (e.g., AAPL, MSFT, NESN.SW)",
    )
    parser.add_argument(
        "--query", "-q",
        type=str,
        default=None,
        help="Optional analysis query for additional context",
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="Review past predictions instead of running analysis",
    )
    parser.add_argument(
        "--perceive",
        action="store_true",
        help="Process pending library items (perception pipeline)",
    )
    parser.add_argument(
        "--forward",
        type=str,
        default=None,
        help="Forward content to the agent for processing (text or file path)",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Source of forwarded content (e.g. seeking_alpha, twitter)",
    )
    parser.add_argument(
        "--view",
        type=str,
        default=None,
        help="Record your view on a stock (use with --ticker)",
    )
    parser.add_argument(
        "--sentiment",
        type=str,
        choices=["bullish", "bearish", "neutral"],
        default="neutral",
        help="Your sentiment (use with --view)",
    )
    parser.add_argument(
        "--divergences",
        action="store_true",
        help="Show active agent-user divergences",
    )
    parser.add_argument(
        "--refresh-sources",
        action="store_true",
        help="Refresh all WeChat OA sources and run perception pipeline",
    )
    parser.add_argument(
        "--digest",
        action="store_true",
        help="Run LLM-powered digest pipeline (filter + batch digest unread articles)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Items per digest batch (default: 25)",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Skip LLM filter during digest (force-feed all items)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset Firn state: backup + clear notebook, library, archive, logs. Run before --retrain for fresh start.",
    )
    parser.add_argument(
        "--retrain",
        action="store_true",
        help="Retrain from library articles chronologically with simulated dates (run --reset first for fresh start)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show retrain schedule without executing (use with --retrain)",
    )
    parser.add_argument(
        "--epochs",
        type=str,
        default=None,
        help="Epoch range for retrain (e.g., '3' for first 3, '5-8' for range)",
    )
    parser.add_argument(
        "--min-articles",
        type=int,
        default=3,
        help="Minimum articles per retrain epoch (default: 3)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Auto-commit KB changes after digest",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show source freshness status",
    )
    parser.add_argument(
        "--cost",
        type=int,
        nargs="?",
        const=0,
        default=None,
        metavar="DAYS",
        help="Show token usage summary (optionally filter to last N days, default: all)",
    )
    parser.add_argument(
        "--ingest-cached",
        action="store_true",
        help="One-time import: add cached articles to library/unread",
    )
    parser.add_argument(
        "--audit",
        type=str,
        nargs="?",
        const="latest",
        default=None,
        metavar="EXEC_ID",
        help="Audit a completed analysis (default: latest). Verifies report claims against trace data.",
    )
    parser.add_argument(
        "--audit-digest",
        type=str,
        nargs="?",
        const="latest",
        default=None,
        metavar="EXEC_ID",
        help="Audit a completed digest session (default: latest). Verifies KB writes against source articles.",
    )
    parser.add_argument(
        "--with-audit",
        action="store_true",
        help="Automatically run audit after analysis completes",
    )
    args = parser.parse_args()

    # Handle --audit mode
    if args.audit is not None:
        from src.audit.pipeline import run_audit

        await run_audit(args.audit)
        return

    # Handle --audit-digest mode
    if args.audit_digest is not None:
        from src.audit.pipeline import run_audit

        await run_audit(args.audit_digest, mode="digest")
        return

    # Handle --digest mode
    if args.digest:
        from src.knowledge_base.digest_pipeline import run_digest

        result = await run_digest(
            batch_size=args.batch_size,
            filter_low_trust=not args.no_filter,
        )
        print(f"\nDigest complete:")
        print(f"  Items: {result.total_inbox} unread, {result.items_processed} processed")
        print(f"  Filter: {result.auto_passed} auto-passed, {result.filter_kept} kept, {result.filter_dropped} dropped")
        print(f"  Batches: {result.batches_completed}")
        if result.session_summary:
            print(f"\n{result.session_summary}")
        if args.commit:
            from src.knowledge_base.kb_commit import commit_kb_changes

            msg = f"[digest] {result.items_processed} items in {result.batches_completed} batches"
            commit_hash = commit_kb_changes(msg)
            if commit_hash:
                print(f"\nKB changes committed: {commit_hash}")
            else:
                print("\nNo KB changes to commit.")
        return

    # Handle --reset mode
    if args.reset:
        from src.knowledge_base.kb_api import KnowledgeBase
        from src.knowledge_base.retrain_pipeline import reset_firn

        kb = KnowledgeBase()
        backup_dir = reset_firn(kb)
        print(f"\nFirn state reset complete.")
        print(f"  Backup: {backup_dir}")
        print(f"  Cleared: notebook, library, archive, logs")
        print(f"\n  Next steps:")
        print(f"    uv run python -m src --ingest-cached   # repopulate library from JSON stores")
        print(f"    uv run python -m src --retrain          # retrain from scratch")
        return

    # Handle --retrain mode
    if args.retrain:
        from src.knowledge_base.retrain_pipeline import run_retrain

        # Parse epoch range
        epoch_range = None
        if args.epochs:
            if "-" in args.epochs:
                parts = args.epochs.split("-", 1)
                epoch_range = (int(parts[0]), int(parts[1]))
            else:
                epoch_range = (1, int(args.epochs))

        await run_retrain(
            epoch_range=epoch_range,
            dry_run=args.dry_run,
            min_articles=args.min_articles,
        )
        return

    # Handle --status mode
    if args.status:
        from src.knowledge_base.kb_api import KnowledgeBase

        kb = KnowledgeBase()
        print(kb.build_source_status())
        return

    # Handle --cost mode
    if args.cost is not None:
        from src.utils.cost_tracker import print_cost_summary

        print_cost_summary(last_n_days=args.cost if args.cost > 0 else None)
        return

    # Handle --ingest-cached mode
    if args.ingest_cached:
        from src.sources.refresh_pipeline import ingest_cached_articles

        result = ingest_cached_articles(max_age_days=180)
        print(f"\n{result['total_created']} articles imported from cache.")
        for name, count in result["per_account"].items():
            if count:
                print(f"  {name}: {count}")
        return

    # Handle --refresh-sources mode
    if args.refresh_sources:
        from src.sources.refresh_pipeline import refresh_sources

        result = refresh_sources()
        if result["new_articles"] == 0:
            print("All sources up to date.")
        else:
            print(f"\nSummary:")
            for name, count in result.get("per_account", {}).items():
                print(f"  {name}: {count} new articles")
            print(f"  Total: {result['new_articles']} new → {result['inbox_items']} library items")
            print("  Run --digest to process them.")
        return

    # Handle --review mode
    if args.review:
        from src.knowledge_base.prediction_logger import review_predictions
        review = await review_predictions(args.ticker)
        print(review)
        return

    # Handle --perceive mode (DEPRECATED)
    if args.perceive:
        print("WARNING: --perceive is deprecated. Use --digest instead.")
        print("  --digest uses LLM-powered processing (filter + batch digest)")
        print("  --perceive used rule-based routing (no LLM, no understanding)")
        from src.knowledge_base.perception import process_inbox

        results = process_inbox()
        if not results:
            print("\nNo pending items in library.")
        else:
            print(f"\nProcessed {len(results)} items (legacy mode):")
            for r in results:
                print(f"  {r['slug']}: {r['action']} -> {r.get('location', 'N/A')}")
        return

    # Handle --forward mode
    if args.forward:
        from src.knowledge_base.user_input import process_user_forward
        content = args.forward
        if Path(content).is_file():
            content = Path(content).read_text(encoding="utf-8")
        result = process_user_forward(
            content=content,
            source=args.source,
            ticker=args.ticker,
        )
        print("Content forwarded and stored:")
        print(f"  Slug: {result['slug']}")
        print(f"  Source: {result['source']} (Tier {result['tier']})")
        if result.get("ticker"):
            print(f"  Ticker: {result['ticker']}")
        print(f"  Stored at: {result['stored_at']}")
        return

    # Handle --view mode
    if args.view:
        if not args.ticker:
            parser.error("--view requires --ticker")
        from src.knowledge_base.user_input import update_user_view
        update_user_view(
            ticker=args.ticker,
            view=args.view,
            sentiment=args.sentiment,
        )
        print(f"View recorded for {args.ticker.upper()}: {args.sentiment}")
        print(f"  {args.view}")
        return

    # Handle --divergences mode
    if args.divergences:
        from src.knowledge_base.divergence import get_active_divergences
        divs = get_active_divergences()
        if not divs:
            print("No active divergences.")
        else:
            print(f"Active Divergences ({len(divs)}):")
            for d in divs:
                print(f"  {d.get('ticker', '?')}: Agent={d.get('agent_view', '?')} vs User={d.get('user_view', '?')} ({d.get('date', '?')})")
        return

    # For analysis mode, --ticker is required
    if not args.ticker:
        parser.error("--ticker is required for analysis (or use --review)")

    print(f"\n{'='*60}")
    print(f"  Financial Analysis Agent — {args.ticker.upper()}")
    print(f"{'='*60}")
    print(f"  Running: Fundamental + Technical + Value + Macro → Core Analysis")
    print(f"  This may take 2-5 minutes depending on LLM speed...")
    print(f"{'='*60}\n")

    t0 = time.time()

    try:
        final_state = await run_analysis(args.ticker, args.query)

        elapsed = time.time() - t0
        data = final_state.get("data", {})

        if "final_report" in data:
            print("\n" + data["final_report"])
            if "report_path" in data:
                print(f"\n[Report saved to: {data['report_path']}]")
        else:
            print("\nERROR: No final report generated.")
            if "summary_error" in data:
                print(f"  Summary error: {data['summary_error']}")

        print(f"\n{'='*60}")
        print(f"  Completed in {elapsed:.1f}s")

        # Show per-agent timing
        metadata = final_state.get("metadata", {})
        for agent in ("fundamental", "technical", "value", "macro", "core_analysis"):
            secs = metadata.get(f"{agent}_seconds")
            if secs:
                print(f"    {agent:>12}: {secs:.1f}s")
        print(f"{'='*60}\n")

        # Auto-audit if requested
        if args.with_audit:
            print("Running audit on completed analysis...\n")
            from src.audit.pipeline import run_audit

            exec_id = metadata.get("execution_id", "latest")
            await run_audit(exec_id)

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        sys.exit(1)
    finally:
        await close_mcp_client()


def main():
    """Sync wrapper for CLI."""
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
