"""Reverse DCF / Implied Expectations calculator.

Pure Python module — no LLM, no MCP dependencies. Given a stock's current
price, this module back-solves for the annual FCF (or EPS) growth rate that
the market is *implying*, then compares it to analyst consensus or the user's
own estimate to identify expectation gaps.

Key functions
-------------
- ``calculate_reverse_dcf``  — core solver
- ``format_reverse_dcf_report`` — markdown-formatted output for reports
"""

from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _dcf_value(
    current_cf_per_share: float,
    growth_rate: float,
    discount_rate: float,
    terminal_growth: float,
    projection_years: int,
) -> float:
    """Return the per-share DCF value given a constant annual growth rate *g*.

    Model
    -----
    ``V = sum(CF*(1+g)^t / (1+r)^t, t=1..n) + TV/(1+r)^n``
    where ``TV = CF*(1+g)^n * (1+g_terminal) / (r - g_terminal)``
    """
    r = discount_rate
    g = growth_rate
    g_term = terminal_growth

    pv_sum = 0.0
    for t in range(1, projection_years + 1):
        future_cf = current_cf_per_share * (1 + g) ** t
        pv_sum += future_cf / (1 + r) ** t

    # Terminal value at end of projection period
    final_cf = current_cf_per_share * (1 + g) ** projection_years
    terminal_value = final_cf * (1 + g_term) / (r - g_term)
    pv_terminal = terminal_value / (1 + r) ** projection_years

    return pv_sum + pv_terminal


def _solve_implied_growth(
    target_price: float,
    current_cf_per_share: float,
    discount_rate: float,
    terminal_growth: float,
    projection_years: int,
    *,
    low: float = -0.50,
    high: float = 1.00,
    tol: float = 1e-6,
    max_iter: int = 200,
) -> float | None:
    """Binary-search for the growth rate *g* that yields ``target_price``.

    Returns ``None`` when convergence fails within *max_iter* iterations.
    The search range is [``low``, ``high``] (default -50% to +100%).
    """
    # Evaluate at boundaries to verify sign change
    f_low = _dcf_value(current_cf_per_share, low, discount_rate,
                       terminal_growth, projection_years) - target_price
    f_high = _dcf_value(current_cf_per_share, high, discount_rate,
                        terminal_growth, projection_years) - target_price

    # If both same sign, no root in interval
    if f_low * f_high > 0:
        return None

    for _ in range(max_iter):
        mid = (low + high) / 2.0
        f_mid = _dcf_value(current_cf_per_share, mid, discount_rate,
                           terminal_growth, projection_years) - target_price

        if abs(f_mid) < tol or (high - low) / 2.0 < tol:
            return mid

        if f_low * f_mid < 0:
            high = mid
            f_high = f_mid
        else:
            low = mid
            f_low = f_mid

    return (low + high) / 2.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_reverse_dcf(
    current_price: float | None,
    shares_outstanding: float | None,
    current_fcf: float | None,
    current_eps: float | None,
    discount_rate: float = 0.10,
    terminal_growth: float = 0.03,
    projection_years: int = 5,
) -> dict[str, Any]:
    """Calculate the implied growth rate embedded in *current_price*.

    Parameters
    ----------
    current_price : float
        Current market price per share.
    shares_outstanding : float
        Total diluted shares outstanding (used only for context; the
        calculation is per-share).
    current_fcf : float | None
        Most recent trailing-twelve-month free cash flow *total*.
        Preferred metric; if negative or ``None``, the function falls back
        to *current_eps*.
    current_eps : float | None
        Most recent trailing-twelve-month EPS.  Used as fallback when
        FCF is unavailable or negative.
    discount_rate : float
        Required annual return / WACC (default 10 %).
    terminal_growth : float
        Long-run perpetuity growth rate (default 3 %).
    projection_years : int
        Number of explicit projection years (default 5).

    Returns
    -------
    dict
        A dict containing ``implied_growth_rate``, sensitivity tables,
        valuation grid, and diagnostic flags.  On error, ``"error"`` key
        is set.
    """
    # --- Input validation ------------------------------------------------
    if current_price is None or current_price <= 0:
        return {"error": "current_price must be a positive number.",
                "current_price": current_price}

    if discount_rate <= terminal_growth:
        return {"error": (f"discount_rate ({discount_rate:.2%}) must exceed "
                          f"terminal_growth ({terminal_growth:.2%}).")}

    if projection_years < 1 or projection_years > 30:
        return {"error": "projection_years must be between 1 and 30."}

    # --- Determine per-share cash-flow metric ----------------------------
    use_fcf = True
    cf_per_share: float | None = None

    if (current_fcf is not None
            and shares_outstanding is not None
            and shares_outstanding > 0
            and current_fcf > 0):
        cf_per_share = current_fcf / shares_outstanding
    else:
        use_fcf = False

    if cf_per_share is None or cf_per_share <= 0:
        # Fall back to EPS
        use_fcf = False
        if current_eps is not None and current_eps > 0:
            cf_per_share = current_eps
        else:
            return {
                "error": ("Cannot compute reverse DCF: both FCF and EPS are "
                          "non-positive or unavailable."),
                "current_price": current_price,
                "current_fcf": current_fcf,
                "current_eps": current_eps,
            }

    metric_label = "FCF/share" if use_fcf else "EPS"

    # --- Solve for implied growth ----------------------------------------
    implied_g = _solve_implied_growth(
        current_price, cf_per_share, discount_rate,
        terminal_growth, projection_years,
    )

    # Flags
    flags: list[str] = []
    if implied_g is None:
        flags.append("convergence_failed")
    else:
        if implied_g > 0.50:
            flags.append("unrealistic_high_growth")
        if implied_g < -0.20:
            flags.append("unrealistic_negative_growth")

    if not use_fcf:
        flags.append("eps_fallback")

    # --- Sensitivity: implied growth at different discount rates ----------
    sensitivity: dict[str, float | None] = {}
    for dr_label, dr_val in [("discount_8pct", 0.08),
                              ("discount_10pct", 0.10),
                              ("discount_12pct", 0.12)]:
        if dr_val <= terminal_growth:
            sensitivity[dr_label] = None
            continue
        g = _solve_implied_growth(
            current_price, cf_per_share, dr_val,
            terminal_growth, projection_years,
        )
        sensitivity[dr_label] = round(g, 6) if g is not None else None

    # --- Valuation grid: fair value at various growth assumptions ---------
    valuation_grid: dict[str, float] = {}
    for g_label, g_val in [("growth_0pct", 0.00),
                            ("growth_5pct", 0.05),
                            ("growth_10pct", 0.10),
                            ("growth_15pct", 0.15),
                            ("growth_20pct", 0.20),
                            ("growth_25pct", 0.25),
                            ("growth_30pct", 0.30)]:
        fv = _dcf_value(cf_per_share, g_val, discount_rate,
                        terminal_growth, projection_years)
        valuation_grid[g_label] = round(fv, 2)

    result: dict[str, Any] = {
        "implied_growth_rate": round(implied_g, 6) if implied_g is not None else None,
        "current_price": current_price,
        "cf_per_share": round(cf_per_share, 4),
        "metric_used": metric_label,
        "discount_rate": discount_rate,
        "terminal_growth": terminal_growth,
        "projection_years": projection_years,
        "sensitivity": sensitivity,
        "valuation_at_growth_rates": valuation_grid,
        "flags": flags,
    }

    if implied_g is None:
        result["error"] = ("Could not solve for implied growth rate in the "
                           "range [-50%, +100%]. The current price may imply "
                           "extreme expectations.")

    return result


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------

def format_reverse_dcf_report(
    result: dict[str, Any],
    ticker: str,
    analyst_consensus_growth: float | None = None,
) -> str:
    """Format a ``calculate_reverse_dcf`` result as a markdown section.

    Parameters
    ----------
    result : dict
        Output of ``calculate_reverse_dcf``.
    ticker : str
        Stock ticker symbol.
    analyst_consensus_growth : float | None
        Analyst consensus annual growth rate (e.g. 0.15 for 15 %).

    Returns
    -------
    str
        Markdown-formatted section for inclusion in a report.
    """
    lines: list[str] = []
    lines.append(f"### Implied Expectations Analysis ({ticker})")
    lines.append("")

    # Handle error cases
    if "error" in result and result.get("implied_growth_rate") is None:
        lines.append(f"> **Note:** {result['error']}")
        lines.append("")
        if result.get("current_price"):
            lines.append(f"- Current Price: ${result['current_price']:.2f}")
        if result.get("current_fcf") is not None:
            lines.append(f"- Current FCF: ${result['current_fcf']:,.0f}")
        if result.get("current_eps") is not None:
            lines.append(f"- Current EPS: ${result['current_eps']:.2f}")
        return "\n".join(lines)

    implied_g = result["implied_growth_rate"]
    metric = result.get("metric_used", "FCF/share")
    cf_per_share = result["cf_per_share"]
    price = result["current_price"]
    dr = result["discount_rate"]
    tg = result["terminal_growth"]
    years = result["projection_years"]

    # --- Core finding ---
    lines.append(
        f"**What does ${price:.2f} imply?** At a {dr:.0%} discount rate "
        f"and {tg:.0%} terminal growth over {years} years, the current price "
        f"implies **{implied_g:.1%} annual {metric} growth**."
    )
    lines.append("")

    # --- Flags ---
    flags = result.get("flags", [])
    if "unrealistic_high_growth" in flags:
        lines.append(
            f"> **Warning:** Implied growth of {implied_g:.1%} is very high "
            f"(>50%). The market may be pricing in speculative momentum "
            f"rather than fundamentals."
        )
        lines.append("")
    if "unrealistic_negative_growth" in flags:
        lines.append(
            f"> **Warning:** Implied growth of {implied_g:.1%} is deeply "
            f"negative (<-20%). This may signal distress pricing or "
            f"a broken business model."
        )
        lines.append("")
    if "eps_fallback" in flags:
        lines.append(
            f"> **Note:** FCF was negative or unavailable; analysis uses "
            f"EPS (${cf_per_share:.2f}) as a proxy."
        )
        lines.append("")

    # --- Analyst consensus comparison ---
    if analyst_consensus_growth is not None:
        gap = implied_g - analyst_consensus_growth
        lines.append("#### Expectation Gap")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Market-implied growth | {implied_g:.1%} |")
        lines.append(
            f"| Analyst consensus growth | {analyst_consensus_growth:.1%} |"
        )
        lines.append(f"| **Expectation gap** | **{gap:+.1%}** |")
        lines.append("")

        # Interpret the gap
        if gap > 0.05:
            lines.append(
                f"**Interpretation:** The market implies {gap:.1%} *more* "
                f"growth than analysts expect. This suggests the stock may "
                f"be **overvalued** relative to consensus — the price "
                f"already bakes in optimistic expectations."
            )
        elif gap < -0.05:
            lines.append(
                f"**Interpretation:** The market implies {abs(gap):.1%} *less* "
                f"growth than analysts expect. This suggests the stock may "
                f"be **undervalued** relative to consensus — the market "
                f"is pricing in lower expectations than analysts forecast."
            )
        else:
            lines.append(
                f"**Interpretation:** The expectation gap is small "
                f"({gap:+.1%}). The stock appears **fairly valued** "
                f"relative to analyst consensus."
            )
        lines.append("")

    # --- Sensitivity table ---
    sensitivity = result.get("sensitivity", {})
    if sensitivity:
        lines.append("#### Sensitivity: Implied Growth vs Discount Rate")
        lines.append("")
        lines.append("| Discount Rate | Implied Growth |")
        lines.append("|---------------|----------------|")
        for label, val in sensitivity.items():
            dr_pct = label.replace("discount_", "").replace("pct", "%")
            if val is not None:
                lines.append(f"| {dr_pct} | {val:.1%} |")
            else:
                lines.append(f"| {dr_pct} | N/A |")
        lines.append("")

    # --- Valuation grid ---
    val_grid = result.get("valuation_at_growth_rates", {})
    if val_grid:
        lines.append("#### Fair Value at Different Growth Assumptions")
        lines.append("")
        lines.append(f"| Growth Rate | Fair Value | vs Current (${price:.2f}) |")
        lines.append(f"|-------------|------------|--------------------------|")
        for label, fv in val_grid.items():
            g_pct = label.replace("growth_", "").replace("pct", "%")
            diff_pct = (fv - price) / price
            marker = ""
            if abs(diff_pct) < 0.05:
                marker = " <-- ~current price"
            lines.append(
                f"| {g_pct} | ${fv:.2f} | {diff_pct:+.1%}{marker} |"
            )
        lines.append("")

    return "\n".join(lines)
