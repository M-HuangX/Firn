"""Markdown formatting utilities for MCP tool output — tables, headers, lists.

Each ``format_*`` function takes the dict returned by the corresponding
``YFinanceDataSource`` method and returns a human-readable markdown string
suitable for both LLM agents and human consumption.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Number formatting helpers
# ---------------------------------------------------------------------------


def _fmt_number(
    val: Any,
    decimals: int = 2,
    prefix: str = "",
    suffix: str = "",
    large: bool = False,
) -> str:
    """Format a number for display. Returns ``'N/A'`` if *val* is None."""
    if val is None:
        return "N/A"
    try:
        val = float(val)
    except (ValueError, TypeError):
        return str(val)
    if large:
        return _fmt_large(val)
    return f"{prefix}{val:,.{decimals}f}{suffix}"


def _fmt_pct(val: Any, decimals: int = 2) -> str:
    """Format a value as a percentage string. Returns ``'N/A'`` if None."""
    if val is None:
        return "N/A"
    try:
        val = float(val)
    except (ValueError, TypeError):
        return str(val)
    return f"{val:.{decimals}f}%"


def _fmt_large(val: Any) -> str:
    """Format large numbers as ``$1.23B`` / ``$45.6M`` / ``$1.2K``.

    Returns ``'N/A'`` if *val* is None.
    """
    if val is None:
        return "N/A"
    try:
        val = float(val)
    except (ValueError, TypeError):
        return str(val)
    abs_val = abs(val)
    sign = "-" if val < 0 else ""
    if abs_val >= 1e12:
        return f"{sign}${abs_val / 1e12:.2f}T"
    if abs_val >= 1e9:
        return f"{sign}${abs_val / 1e9:.2f}B"
    if abs_val >= 1e6:
        return f"{sign}${abs_val / 1e6:.2f}M"
    if abs_val >= 1e3:
        return f"{sign}${abs_val / 1e3:.1f}K"
    return f"{sign}${val:,.2f}"


def _fmt_int(val: Any) -> str:
    """Format an integer with commas. Returns ``'N/A'`` if None."""
    if val is None:
        return "N/A"
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val)


def _na(val: Any) -> str:
    """Return the string representation or ``'N/A'`` if None."""
    if val is None:
        return "N/A"
    return str(val)


# ---------------------------------------------------------------------------
# 1. Stock Info
# ---------------------------------------------------------------------------


def format_stock_info(data: dict) -> str:
    """Format ``get_stock_info`` output as markdown.

    Sections: Identity, Price, Market, and (for ETFs) Fund Info.
    """
    ticker = data.get("_ticker", "")
    identity = data.get("identity", {})
    price = data.get("price", {})
    market = data.get("market", {})
    fund_info = data.get("fund_info")
    quote_type = identity.get("quoteType", "EQUITY")

    type_label = "ETF" if quote_type == "ETF" else "Stock"
    lines: list[str] = [f"# {type_label} Info: {identity.get('shortName', ticker)} ({ticker})"]

    # Identity
    lines.append("")
    lines.append("## Identity")
    lines.append(f"- **Name**: {_na(identity.get('longName'))}")
    lines.append(f"- **Symbol**: {_na(identity.get('symbol'))}")
    lines.append(f"- **Type**: {_na(quote_type)}")
    lines.append(f"- **Sector**: {_na(identity.get('sector'))}")
    lines.append(f"- **Industry**: {_na(identity.get('industry'))}")
    lines.append(f"- **Country**: {_na(identity.get('country'))}")
    lines.append(f"- **Website**: {_na(identity.get('website'))}")
    lines.append(f"- **Employees**: {_fmt_int(identity.get('fullTimeEmployees'))}")

    # Fund Info (ETFs only)
    if fund_info:
        lines.append("")
        lines.append("## Fund Info")
        lines.append(f"- **Category**: {_na(fund_info.get('category'))}")
        lines.append(f"- **Fund Family**: {_na(fund_info.get('fundFamily'))}")
        lines.append(f"- **Total Assets**: {_fmt_large(fund_info.get('totalAssets'))}")
        lines.append(f"- **NAV Price**: {_fmt_number(fund_info.get('navPrice'), prefix='$')}")
        lines.append(f"- **Expense Ratio**: {_fmt_pct(fund_info.get('expenseRatio'))}")
        lines.append(f"- **YTD Return**: {_fmt_pct(fund_info.get('ytdReturn'))}")
        lines.append(f"- **3-Year Avg Return**: {_fmt_pct(fund_info.get('threeYearReturn'))}")
        lines.append(f"- **5-Year Avg Return**: {_fmt_pct(fund_info.get('fiveYearReturn'))}")
        summary = fund_info.get("longBusinessSummary")
        if summary:
            lines.append(f"- **Description**: {summary[:300]}")

    # Price
    lines.append("")
    lines.append("## Price")
    lines.append(f"- **Current Price**: {_fmt_number(price.get('currentPrice'), prefix='$')}")
    lines.append(f"- **Previous Close**: {_fmt_number(price.get('previousClose'), prefix='$')}")
    lines.append(f"- **52-Week High**: {_fmt_number(price.get('fiftyTwoWeekHigh'), prefix='$')}")
    lines.append(f"- **52-Week Low**: {_fmt_number(price.get('fiftyTwoWeekLow'), prefix='$')}")
    lines.append(f"- **50-Day Average**: {_fmt_number(price.get('fiftyDayAverage'), prefix='$')}")
    lines.append(f"- **200-Day Average**: {_fmt_number(price.get('twoHundredDayAverage'), prefix='$')}")
    lines.append(f"- **Beta**: {_fmt_number(price.get('beta'))}")
    lines.append(f"- **Volume**: {_fmt_int(price.get('volume'))}")

    # Market
    lines.append("")
    lines.append("## Market")
    lines.append(f"- **Exchange**: {_na(market.get('exchange'))}")
    lines.append(f"- **Currency**: {_na(market.get('currency'))}")
    lines.append(f"- **Market State**: {_na(market.get('marketState'))}")
    lines.append(f"- **Timezone**: {_na(market.get('exchangeTimezoneName'))}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. Historical Prices
# ---------------------------------------------------------------------------


def format_historical_prices(data: dict) -> str:
    """Format ``get_historical_prices`` output as markdown.

    Shows summary statistics followed by an OHLCV table (last 20 rows).
    """
    ticker = data.get("_ticker", "")
    period = data.get("period", "")
    interval = data.get("interval", "")
    summary = data.get("summary", {})
    prices = data.get("prices", [])

    lines: list[str] = [f"# Historical Prices: {ticker}"]
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- **Period**: {summary.get('start_date', 'N/A')} to {summary.get('end_date', 'N/A')} ({period}, {interval})")
    lines.append(f"- **Total Rows**: {_fmt_int(summary.get('total_rows'))}")
    lines.append(f"- **Price Change**: {_fmt_pct(summary.get('price_change_pct'))}")
    lines.append(f"- **Period High**: {_fmt_number(summary.get('period_high'), prefix='$')}")
    lines.append(f"- **Period Low**: {_fmt_number(summary.get('period_low'), prefix='$')}")
    lines.append(f"- **Avg Volume**: {_fmt_int(summary.get('avg_volume'))}")

    # OHLCV table — last 20 rows
    lines.append("")
    display_prices = prices[-20:] if len(prices) > 20 else prices
    if len(prices) > 20:
        lines.append(f"## Price Data (last 20 of {len(prices)} rows)")
    else:
        lines.append(f"## Price Data ({len(prices)} rows)")

    if display_prices:
        lines.append("")
        lines.append("| Date | Open | High | Low | Close | Volume |")
        lines.append("|------|------|------|-----|-------|--------|")
        for row in display_prices:
            lines.append(
                f"| {row.get('Date', 'N/A')} "
                f"| {_fmt_number(row.get('Open'), prefix='$')} "
                f"| {_fmt_number(row.get('High'), prefix='$')} "
                f"| {_fmt_number(row.get('Low'), prefix='$')} "
                f"| {_fmt_number(row.get('Close'), prefix='$')} "
                f"| {_fmt_int(row.get('Volume'))} |"
            )
    else:
        lines.append("\nNo price data available.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. Dividends
# ---------------------------------------------------------------------------


def format_dividends(data: dict) -> str:
    """Format ``get_dividends`` output as markdown.

    Shows yield summary, annual totals, and dividend history table.
    """
    ticker = data.get("_ticker", "")
    summary = data.get("summary", {})
    annual_totals = data.get("annual_totals", {})
    history = data.get("history", [])

    lines: list[str] = [f"# Dividend History: {ticker}"]

    # Summary
    lines.append("")
    lines.append("## Yield Summary")
    div_yield = summary.get("dividendYield")
    if div_yield is not None:
        lines.append(f"- **Dividend Yield**: {_fmt_pct(div_yield * 100)}")
    else:
        lines.append("- **Dividend Yield**: N/A")
    lines.append(f"- **Dividend Rate**: {_fmt_number(summary.get('dividendRate'), prefix='$')}")
    payout = summary.get("payoutRatio")
    if payout is not None:
        lines.append(f"- **Payout Ratio**: {_fmt_pct(payout * 100)}")
    else:
        lines.append("- **Payout Ratio**: N/A")
    lines.append(f"- **Ex-Dividend Date**: {_na(summary.get('exDividendDate'))}")
    five_yr = summary.get("fiveYearAvgDividendYield")
    lines.append(f"- **5-Year Avg Yield**: {_fmt_pct(five_yr) if five_yr is not None else 'N/A'}")
    lines.append(f"- **Trailing Annual Rate**: {_fmt_number(summary.get('trailingAnnualDividendRate'), prefix='$')}")
    trailing_yield = summary.get("trailingAnnualDividendYield")
    if trailing_yield is not None:
        lines.append(f"- **Trailing Annual Yield**: {_fmt_pct(trailing_yield * 100)}")
    else:
        lines.append("- **Trailing Annual Yield**: N/A")
    lines.append(f"- **Consecutive Years**: {_na(summary.get('consecutiveYearsWithDividends'))}")
    lines.append(f"- **Total Payments**: {_na(summary.get('totalPaymentsInPeriod'))}")

    # Annual totals
    if annual_totals:
        lines.append("")
        lines.append("## Annual Totals")
        lines.append("")
        lines.append("| Year | Total Dividends |")
        lines.append("|------|-----------------|")
        for year in sorted(annual_totals.keys(), reverse=True):
            lines.append(f"| {year} | {_fmt_number(annual_totals[year], prefix='$')} |")

    # Dividend history table
    lines.append("")
    if history:
        lines.append(f"## Payment History ({len(history)} payments)")
        lines.append("")
        lines.append("| Date | Amount |")
        lines.append("|------|--------|")
        for entry in history:
            lines.append(f"| {entry.get('date', 'N/A')} | {_fmt_number(entry.get('amount'), prefix='$')} |")
    else:
        lines.append("## Payment History")
        lines.append("\nNo dividend payments found in the requested period.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. Search Results
# ---------------------------------------------------------------------------


def format_search_results(results: list[dict]) -> str:
    """Format ``search_stocks`` output as markdown.

    Shows a table of matching stocks.
    """
    lines: list[str] = [f"# Search Results ({len(results)} matches)"]

    if results:
        lines.append("")
        lines.append("| Symbol | Name | Exchange | Sector | Industry | Type |")
        lines.append("|--------|------|----------|--------|----------|------|")
        for r in results:
            lines.append(
                f"| {_na(r.get('symbol'))} "
                f"| {_na(r.get('name'))} "
                f"| {_na(r.get('exchange'))} "
                f"| {_na(r.get('sector'))} "
                f"| {_na(r.get('industry'))} "
                f"| {_na(r.get('quoteType'))} |"
            )
    else:
        lines.append("\nNo results found.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5/6/7. Financial Statements (shared format)
# ---------------------------------------------------------------------------


def _format_financial_statement_md(data: dict, title: str) -> str:
    """Shared formatter for income statement, balance sheet, and cash flow.

    Periods are displayed as columns, line items as rows.  Large numbers are
    formatted with ``_fmt_large``.
    """
    ticker = data.get("_ticker", "")
    period_type = data.get("period_type", "annual")
    periods = data.get("periods", [])
    stmt_data = data.get("data", {})

    lines: list[str] = [f"# {title}: {ticker} ({period_type})"]

    if not periods or not stmt_data:
        lines.append("\nNo data available.")
        return "\n".join(lines)

    # Build table header
    header_cols = ["Line Item"] + periods
    lines.append("")
    lines.append("| " + " | ".join(header_cols) + " |")
    lines.append("| " + " | ".join(["---"] * len(header_cols)) + " |")

    # Build rows
    for line_item, values in stmt_data.items():
        formatted_vals: list[str] = []
        for val in values:
            formatted_vals.append(_fmt_large(val))
        row = f"| {line_item} | " + " | ".join(formatted_vals) + " |"
        lines.append(row)

    return "\n".join(lines)


def format_income_statement(data: dict) -> str:
    """Format ``get_income_statement`` output as markdown."""
    return _format_financial_statement_md(data, "Income Statement")


def format_balance_sheet(data: dict) -> str:
    """Format ``get_balance_sheet`` output as markdown."""
    return _format_financial_statement_md(data, "Balance Sheet")


def format_cash_flow(data: dict) -> str:
    """Format ``get_cash_flow`` output as markdown."""
    return _format_financial_statement_md(data, "Cash Flow Statement")


# ---------------------------------------------------------------------------
# 8. Financial Metrics
# ---------------------------------------------------------------------------


_SECTION_TITLES: dict[str, str] = {
    "valuation": "Valuation",
    "profitability": "Profitability",
    "growth": "Growth",
    "per_share": "Per Share",
    "financial_health": "Financial Health",
    "cash_flow": "Cash Flow",
    "dividends": "Dividends",
}

_METRIC_LABELS: dict[str, str] = {
    # Valuation
    "trailingPE": "Trailing P/E",
    "forwardPE": "Forward P/E",
    "priceToBook": "Price/Book",
    "priceToSales": "Price/Sales",
    "pegRatio": "PEG Ratio",
    "enterpriseToEbitda": "EV/EBITDA",
    "enterpriseToRevenue": "EV/Revenue",
    # Profitability
    "returnOnEquity": "Return on Equity",
    "returnOnAssets": "Return on Assets",
    "grossMargins": "Gross Margin",
    "operatingMargins": "Operating Margin",
    "profitMargins": "Profit Margin",
    "ebitdaMargins": "EBITDA Margin",
    # Growth
    "revenueGrowth": "Revenue Growth",
    "earningsGrowth": "Earnings Growth",
    "earningsQuarterlyGrowth": "Quarterly Earnings Growth",
    # Per Share
    "trailingEps": "Trailing EPS",
    "forwardEps": "Forward EPS",
    "bookValue": "Book Value",
    "revenuePerShare": "Revenue/Share",
    # Financial Health
    "debtToEquity": "Debt/Equity",
    "currentRatio": "Current Ratio",
    "quickRatio": "Quick Ratio",
    "interestCoverage": "Interest Coverage",
    # Cash Flow
    "freeCashflow": "Free Cash Flow",
    "operatingCashflow": "Operating Cash Flow",
    "fcfYield": "FCF Yield",
    "ocfToNetIncome": "OCF/Net Income",
    # Dividends
    "dividendYield": "Dividend Yield",
    "payoutRatio": "Payout Ratio",
    "fiveYearAvgDividendYield": "5-Year Avg Yield",
}

# Metrics that should be formatted as percentages (values are ratios 0-1)
_RATIO_METRICS: set[str] = {
    "returnOnEquity", "returnOnAssets",
    "grossMargins", "operatingMargins", "profitMargins", "ebitdaMargins",
    "revenueGrowth", "earningsGrowth", "earningsQuarterlyGrowth",
    "dividendYield", "payoutRatio", "fcfYield",
}

# Metrics that should be formatted as large dollar amounts
_LARGE_METRICS: set[str] = {
    "freeCashflow", "operatingCashflow",
}

# Metrics that should be formatted as dollar amounts
_DOLLAR_METRICS: set[str] = {
    "trailingEps", "forwardEps", "bookValue", "revenuePerShare",
}


def format_financial_metrics(data: dict) -> str:
    """Format ``get_financial_metrics`` output as markdown.

    Metrics are organized into sections with human-readable labels.
    """
    ticker = data.get("_ticker", "")

    lines: list[str] = [f"# Financial Metrics: {ticker}"]

    for section_key, section_title in _SECTION_TITLES.items():
        section_data = data.get(section_key)
        if not section_data:
            continue

        lines.append("")
        lines.append(f"## {section_title}")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")

        for metric_key, val in section_data.items():
            label = _METRIC_LABELS.get(metric_key, metric_key)
            if metric_key in _RATIO_METRICS:
                if val is not None:
                    formatted = _fmt_pct(val * 100)
                else:
                    formatted = "N/A"
            elif metric_key in _LARGE_METRICS:
                formatted = _fmt_large(val)
            elif metric_key in _DOLLAR_METRICS:
                formatted = _fmt_number(val, prefix="$")
            elif metric_key == "fiveYearAvgDividendYield":
                # This one comes as a percentage already from yfinance
                formatted = _fmt_pct(val) if val is not None else "N/A"
            else:
                formatted = _fmt_number(val)
            lines.append(f"| {label} | {formatted} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 9. Technical Indicators
# ---------------------------------------------------------------------------


def format_technical_indicators(data: dict) -> str:
    """Format ``get_technical_indicators`` output as markdown.

    Indicators are grouped by category (trend, momentum, volatility, volume).
    The data dict is expected to have keys per category, each containing
    a dict of indicator name -> value.
    """
    ticker = data.get("_ticker", "")
    period = data.get("period", "")

    lines: list[str] = [f"# Technical Indicators: {ticker} ({period})"]

    current_price = data.get("current_price")
    if current_price is not None:
        lines.append("")
        lines.append(f"**Current Price**: {_fmt_number(current_price, prefix='$')}")

    category_order = ["trend", "momentum", "volatility", "volume"]
    category_titles = {
        "trend": "Trend",
        "momentum": "Momentum",
        "volatility": "Volatility",
        "volume": "Volume",
    }

    for cat_key in category_order:
        cat_data = data.get(cat_key)
        if not cat_data or not isinstance(cat_data, dict):
            continue

        cat_title = category_titles.get(cat_key, cat_key.capitalize())
        lines.append("")
        lines.append(f"## {cat_title}")
        lines.append("")
        lines.append("| Indicator | Value |")
        lines.append("|-----------|-------|")

        for indicator_name, val in cat_data.items():
            lines.append(f"| {indicator_name} | {_fmt_number(val)} |")

    # Signal summary (if present)
    signal = data.get("signal_summary")
    if signal and isinstance(signal, dict):
        lines.append("")
        lines.append("## Signal Summary")
        lines.append("")
        for key, val in signal.items():
            lines.append(f"- **{key}**: {_na(val)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 10. Price Analysis
# ---------------------------------------------------------------------------


def format_price_analysis(data: dict) -> str:
    """Format ``get_price_analysis`` output as markdown.

    Sections: Price Statistics, Moving Average Analysis, Trend Assessment.
    """
    ticker = data.get("_ticker", "")
    period = data.get("period", "")
    price_stats = data.get("price_stats", {})
    moving_averages = data.get("moving_averages", {})
    trend = data.get("trend", {})

    lines: list[str] = [f"# Price Analysis: {ticker} ({period})"]

    # Price statistics
    lines.append("")
    lines.append("## Price Statistics")
    lines.append(f"- **Current Price**: {_fmt_number(price_stats.get('currentPrice'), prefix='$')}")
    lines.append(f"- **Period High**: {_fmt_number(price_stats.get('periodHigh'), prefix='$')}")
    lines.append(f"- **Period Low**: {_fmt_number(price_stats.get('periodLow'), prefix='$')}")
    lines.append(f"- **Price Change**: {_fmt_pct(price_stats.get('priceChangePct'))}")
    lines.append(f"- **Avg Daily Range**: {_fmt_number(price_stats.get('avgDailyRange'), prefix='$')}")
    lines.append(f"- **Avg Volume**: {_fmt_int(price_stats.get('avgVolume'))}")

    # Moving average analysis
    lines.append("")
    lines.append("## Moving Average Analysis")
    lines.append("")
    lines.append("| MA | Value | Position | Distance |")
    lines.append("|----|-------|----------|----------|")

    for ma_key in ("SMA20", "SMA50", "SMA200"):
        ma_data = moving_averages.get(ma_key, {})
        ma_val = _fmt_number(ma_data.get("value"), prefix="$")
        position = _na(ma_data.get("position"))
        distance = _fmt_pct(ma_data.get("distance_pct"))
        lines.append(f"| {ma_key} | {ma_val} | {position} | {distance} |")

    alignment = moving_averages.get("alignment", "N/A")
    cross_status = moving_averages.get("crossStatus")
    lines.append("")
    lines.append(f"- **MA Alignment**: {alignment}")
    if cross_status:
        cross_label = "Golden Cross" if cross_status == "golden_cross" else "Death Cross"
        lines.append(f"- **Cross Status**: {cross_label}")

    # Trend assessment
    lines.append("")
    lines.append("## Trend Assessment")
    lines.append(f"- **Short-Term (vs SMA20)**: {_na(trend.get('shortTerm'))}")
    lines.append(f"- **Medium-Term (vs SMA50)**: {_na(trend.get('mediumTerm'))}")
    lines.append(f"- **Long-Term (vs SMA200)**: {_na(trend.get('longTerm'))}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 11. Analyst Data
# ---------------------------------------------------------------------------


def format_analyst_data(data: dict) -> str:
    """Format ``get_analyst_data`` output as markdown.

    Sections: Price Targets, Consensus Recommendation, Recent Trend.
    """
    ticker = data.get("_ticker", "")
    current_price = data.get("currentPrice")
    rec_key = data.get("recommendationKey")
    rec_mean = data.get("recommendationMean")
    price_targets = data.get("price_targets", {})
    consensus = data.get("consensus", {})
    recent_trend = data.get("recent_trend", [])

    lines: list[str] = [f"# Analyst Data: {ticker}"]

    # Overall recommendation
    lines.append("")
    lines.append(f"**Current Price**: {_fmt_number(current_price, prefix='$')}")
    if rec_key:
        lines.append(f"**Recommendation**: {rec_key.upper()}")
    if rec_mean is not None:
        lines.append(f"**Recommendation Mean**: {_fmt_number(rec_mean)} (1=Strong Buy, 5=Strong Sell)")

    # Price targets
    if price_targets:
        lines.append("")
        lines.append("## Price Targets")
        lines.append(f"- **Current Target**: {_fmt_number(price_targets.get('current'), prefix='$')}")
        lines.append(f"- **Mean Target**: {_fmt_number(price_targets.get('mean'), prefix='$')}")
        lines.append(f"- **Median Target**: {_fmt_number(price_targets.get('median'), prefix='$')}")
        lines.append(f"- **High Target**: {_fmt_number(price_targets.get('high'), prefix='$')}")
        lines.append(f"- **Low Target**: {_fmt_number(price_targets.get('low'), prefix='$')}")
        lines.append(f"- **Number of Analysts**: {_fmt_int(price_targets.get('numberOfAnalysts'))}")
        upside = price_targets.get("upsidePct")
        if upside is not None:
            label = "Upside" if upside >= 0 else "Downside"
            lines.append(f"- **{label}**: {_fmt_pct(upside)}")

    # Consensus
    if consensus:
        lines.append("")
        lines.append("## Consensus Breakdown")
        lines.append("")
        lines.append("| Rating | Count |")
        lines.append("|--------|-------|")
        for key in ("strongBuy", "buy", "hold", "sell", "strongSell"):
            label = {
                "strongBuy": "Strong Buy",
                "buy": "Buy",
                "hold": "Hold",
                "sell": "Sell",
                "strongSell": "Strong Sell",
            }.get(key, key)
            lines.append(f"| {label} | {_fmt_int(consensus.get(key))} |")
        lines.append(f"| **Total** | **{_fmt_int(consensus.get('totalAnalysts'))}** |")

    # Recent trend
    if recent_trend:
        lines.append("")
        lines.append("## Recent Trend")
        lines.append("")
        lines.append("| Period | Strong Buy | Buy | Hold | Sell | Strong Sell |")
        lines.append("|--------|------------|-----|------|------|-------------|")
        for entry in recent_trend:
            lines.append(
                f"| {_na(entry.get('period'))} "
                f"| {_fmt_int(entry.get('strongBuy'))} "
                f"| {_fmt_int(entry.get('buy'))} "
                f"| {_fmt_int(entry.get('hold'))} "
                f"| {_fmt_int(entry.get('sell'))} "
                f"| {_fmt_int(entry.get('strongSell'))} |"
            )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 12. Institutional Holders
# ---------------------------------------------------------------------------


def format_institutional_holders(data: dict) -> str:
    """Format ``get_institutional_holders`` output as markdown.

    Sections: Ownership Overview, Top Holders, Short Interest.
    """
    ticker = data.get("_ticker", "")
    overview = data.get("overview", {})
    top_holders = data.get("top_holders", [])
    short_interest = data.get("short_interest", {})

    lines: list[str] = [f"# Institutional Holders: {ticker}"]

    # Overview
    if overview:
        lines.append("")
        lines.append("## Ownership Overview")
        for label, val in overview.items():
            lines.append(f"- **{label}**: {val}")

    # Top holders table
    if top_holders:
        lines.append("")
        lines.append(f"## Top {len(top_holders)} Institutional Holders")
        lines.append("")

        # Determine columns from the first entry
        columns = list(top_holders[0].keys())
        col_labels = {
            "Holder": "Holder",
            "Shares": "Shares",
            "Date Reported": "Date Reported",
            "% Out": "% Out",
            "Value": "Value",
        }

        header = [col_labels.get(c, c) for c in columns]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join(["---"] * len(header)) + " |")

        for holder in top_holders:
            row_vals: list[str] = []
            for col in columns:
                val = holder.get(col)
                if val is None:
                    row_vals.append("N/A")
                elif col == "Value" and isinstance(val, (int, float)):
                    row_vals.append(_fmt_large(val))
                elif col == "Shares" and isinstance(val, (int, float)):
                    row_vals.append(_fmt_int(val))
                elif col == "% Out" and isinstance(val, (int, float)):
                    row_vals.append(_fmt_pct(val))
                else:
                    row_vals.append(str(val))
            lines.append("| " + " | ".join(row_vals) + " |")

    # Short interest
    lines.append("")
    lines.append("## Short Interest")
    lines.append(f"- **Short Ratio**: {_fmt_number(short_interest.get('shortRatio'))}")
    short_pct = short_interest.get("shortPercentOfFloat")
    if short_pct is not None:
        lines.append(f"- **Short % of Float**: {_fmt_pct(short_pct * 100)}")
    else:
        lines.append("- **Short % of Float**: N/A")
    lines.append(f"- **Shares Short**: {_fmt_int(short_interest.get('sharesShort'))}")
    lines.append(f"- **Shares Short (Prior Month)**: {_fmt_int(short_interest.get('sharesShortPriorMonth'))}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 13. Earnings Data
# ---------------------------------------------------------------------------


def format_earnings_data(data: dict) -> str:
    """Format ``get_earnings_data`` output as markdown.

    Sections: Next Earnings, Earnings History, Beat/Miss Summary.
    """
    ticker = data.get("_ticker", "")
    next_earnings = data.get("next_earnings", {})
    history = data.get("history", [])
    bm_summary = data.get("beat_miss_summary", {})

    lines: list[str] = [f"# Earnings Data: {ticker}"]

    # Next earnings
    lines.append("")
    lines.append("## Next Earnings")
    if next_earnings:
        lines.append(f"- **Date**: {_na(next_earnings.get('date'))}")
        lines.append(f"- **EPS Estimate**: {_fmt_number(next_earnings.get('epsEstimate'), prefix='$')}")
    else:
        lines.append("No upcoming earnings date available.")

    # Earnings history
    lines.append("")
    if history:
        lines.append(f"## Earnings History ({len(history)} quarters)")
        lines.append("")
        lines.append("| Date | EPS Estimate | EPS Actual | Surprise % |")
        lines.append("|------|-------------|------------|------------|")
        for entry in history:
            surprise = entry.get("surprisePct")
            surprise_str = _fmt_pct(surprise) if surprise is not None else "N/A"
            lines.append(
                f"| {_na(entry.get('date'))} "
                f"| {_fmt_number(entry.get('epsEstimate'), prefix='$')} "
                f"| {_fmt_number(entry.get('epsActual'), prefix='$')} "
                f"| {surprise_str} |"
            )
    else:
        lines.append("## Earnings History")
        lines.append("\nNo historical earnings data available.")

    # Beat/miss summary
    lines.append("")
    lines.append("## Beat/Miss Summary")
    total = bm_summary.get("totalWithData", 0)
    beats = bm_summary.get("beats", 0)
    misses = bm_summary.get("misses", 0)
    meets = bm_summary.get("meets", 0)
    beat_rate = bm_summary.get("beatRate")

    if total > 0:
        lines.append(f"- **Beat**: {beats} of {total} quarters")
        lines.append(f"- **Miss**: {misses} of {total} quarters")
        lines.append(f"- **Meet**: {meets} of {total} quarters")
        if beat_rate is not None:
            lines.append(f"- **Beat Rate**: {_fmt_pct(beat_rate * 100)}")
    else:
        lines.append("No earnings comparison data available.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 14. Index Data
# ---------------------------------------------------------------------------


def format_index_data(data: dict) -> str:
    """Format ``get_index_data`` output as markdown.

    Shows index name, summary stats, and period performance.
    """
    ticker = data.get("_ticker", "")
    name = data.get("name", ticker)
    period = data.get("period", "")
    summary = data.get("summary", {})

    lines: list[str] = [f"# Index Data: {name} ({ticker})"]

    lines.append("")
    lines.append(f"**Period**: {period}")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- **Current Value**: {_fmt_number(summary.get('currentValue'), prefix='$')}")
    lines.append(f"- **Period Change**: {_fmt_pct(summary.get('periodChangePct'))}")
    lines.append(f"- **Period High**: {_fmt_number(summary.get('periodHigh'), prefix='$')}")
    lines.append(f"- **Period Low**: {_fmt_number(summary.get('periodLow'), prefix='$')}")
    lines.append(f"- **52-Week High**: {_fmt_number(summary.get('fiftyTwoWeekHigh'), prefix='$')}")
    lines.append(f"- **52-Week Low**: {_fmt_number(summary.get('fiftyTwoWeekLow'), prefix='$')}")
    vs_sma = summary.get("vsSMA200Pct")
    if vs_sma is not None:
        label = "above" if vs_sma >= 0 else "below"
        lines.append(f"- **vs SMA200**: {_fmt_pct(abs(vs_sma))} {label}")
    else:
        lines.append("- **vs SMA200**: N/A")

    # Historical data (optional — only when info_type == "history")
    history = data.get("history", [])
    if history:
        lines.append("")
        display = history[-20:] if len(history) > 20 else history
        if len(history) > 20:
            lines.append(f"## Price History (last 20 of {len(history)} rows)")
        else:
            lines.append(f"## Price History ({len(history)} rows)")
        lines.append("")
        lines.append("| Date | Open | High | Low | Close | Volume |")
        lines.append("|------|------|------|-----|-------|--------|")
        for row in display:
            lines.append(
                f"| {row.get('Date', 'N/A')} "
                f"| {_fmt_number(row.get('Open'), prefix='$')} "
                f"| {_fmt_number(row.get('High'), prefix='$')} "
                f"| {_fmt_number(row.get('Low'), prefix='$')} "
                f"| {_fmt_number(row.get('Close'), prefix='$')} "
                f"| {_fmt_int(row.get('Volume'))} |"
            )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 15. Market Status
# ---------------------------------------------------------------------------


def format_market_status(data: dict) -> str:
    """Format ``get_market_status`` output as markdown.

    Shows market state, current time, session times, and next holiday.
    """
    lines: list[str] = ["# Market Status"]

    lines.append("")
    lines.append(f"- **Exchange**: {_na(data.get('exchange'))}")
    lines.append(f"- **Market State**: {_na(data.get('market_state'))}")
    lines.append(f"- **Current Time (UTC)**: {_na(data.get('current_time_utc'))}")
    lines.append(f"- **Current Time (Local)**: {_na(data.get('current_time_local'))}")
    lines.append(f"- **Is Trading Day**: {'Yes' if data.get('is_trading_day') else 'No'}")

    next_td = data.get("next_trading_day")
    if next_td:
        lines.append(f"- **Next Trading Day**: {next_td}")

    session = data.get("session_times")
    if session and isinstance(session, dict):
        lines.append("")
        lines.append("## Today's Session")
        lines.append(f"- **Open**: {_na(session.get('open'))}")
        lines.append(f"- **Close**: {_na(session.get('close'))}")

    next_holiday = data.get("next_holiday")
    if next_holiday and isinstance(next_holiday, dict):
        lines.append("")
        lines.append("## Next Holiday")
        lines.append(f"- **Date**: {_na(next_holiday.get('date'))}")
        lines.append(f"- **Name**: {_na(next_holiday.get('name'))}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 16. Trading Day
# ---------------------------------------------------------------------------


def format_trading_day(data: dict) -> str:
    """Format ``is_trading_day`` output as markdown."""
    lines: list[str] = ["# Trading Day Check"]

    lines.append("")
    lines.append(f"- **Date**: {_na(data.get('date'))}")
    exchange = data.get("exchange", "")
    exchange_name = data.get("exchange_name", "")
    if exchange_name:
        lines.append(f"- **Exchange**: {exchange} ({exchange_name})")
    else:
        lines.append(f"- **Exchange**: {_na(exchange)}")
    is_trading = data.get("is_trading_day")
    lines.append(f"- **Is Trading Day**: {'Yes' if is_trading else 'No'}")

    reason = data.get("reason")
    if reason:
        lines.append(f"- **Reason**: {reason}")

    prev_day = data.get("previous_trading_day")
    next_day = data.get("next_trading_day")
    if prev_day:
        lines.append(f"- **Previous Trading Day**: {prev_day}")
    if next_day:
        lines.append(f"- **Next Trading Day**: {next_day}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 17. Trading Calendar
# ---------------------------------------------------------------------------


def format_trading_calendar(data: dict) -> str:
    """Format ``get_trading_calendar`` output as markdown.

    Handles different ``info_type`` values: holidays, sessions, hours.
    """
    exchange = data.get("exchange", "")
    info_type = data.get("info_type", "holidays")

    lines: list[str] = [f"# Trading Calendar: {exchange}"]
    lines.append("")
    lines.append(f"**Info Type**: {info_type}")

    if info_type == "holidays":
        year = data.get("year", "")
        holidays = data.get("holidays", [])
        lines.append(f"**Year**: {year}")
        lines.append("")

        if holidays:
            lines.append(f"## Holidays ({len(holidays)})")
            lines.append("")
            lines.append("| Date | Name |")
            lines.append("|------|------|")
            for h in holidays:
                if isinstance(h, dict):
                    lines.append(f"| {_na(h.get('date'))} | {_na(h.get('name'))} |")
                else:
                    lines.append(f"| {h} | - |")
        else:
            lines.append("\nNo holidays found.")

    elif info_type == "sessions":
        start = data.get("start_date", "")
        end = data.get("end_date", "")
        session_count = data.get("session_count")
        calendar_days = data.get("calendar_days")
        non_trading = data.get("non_trading_days")
        lines.append(f"**Range**: {start} to {end}")
        lines.append("")
        if session_count is not None:
            lines.append(f"- **Total Trading Sessions**: {_fmt_int(session_count)}")
        if calendar_days is not None:
            lines.append(f"- **Calendar Days**: {_fmt_int(calendar_days)}")
        if non_trading is not None:
            lines.append(f"- **Non-Trading Days**: {_fmt_int(non_trading)}")

        sessions = data.get("sessions", [])
        if sessions:
            display = sessions[:20]
            lines.append("")
            if len(sessions) > 20:
                lines.append(f"## Sessions (showing first 20 of {len(sessions)})")
            else:
                lines.append(f"## Sessions ({len(sessions)})")
            lines.append("")
            for s in display:
                lines.append(f"- {s}")

    elif info_type == "hours":
        hours = data.get("market_hours", {})
        lines.append("")
        lines.append("## Market Hours")
        for key, val in hours.items():
            lines.append(f"- **{key}**: {_na(val)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 18. StockTwits Sentiment
# ---------------------------------------------------------------------------


def format_stocktwits_sentiment(data: dict) -> str:
    """Format ``fetch_stocktwits_sentiment`` output as markdown.

    Shows a sentiment ratio bar, summary counts, and recent messages
    with sentiment labels.  Handles the "unavailable" case gracefully.
    """
    ticker = data.get("ticker", "")

    # Graceful degradation: unavailable
    if data.get("unavailable"):
        lines = [f"# StockTwits Sentiment: {ticker}"]
        lines.append("")
        lines.append(f"Data unavailable: {data.get('reason', 'Unknown reason')}")
        return "\n".join(lines)

    summary = data.get("sentiment_summary", {})
    messages = data.get("messages", [])

    bullish = summary.get("bullish_count", 0)
    bearish = summary.get("bearish_count", 0)
    neutral = summary.get("neutral_count", 0)
    total = summary.get("total", 0)

    lines: list[str] = [f"# StockTwits Sentiment: {ticker}"]

    # Sentiment summary
    lines.append("")
    lines.append("## Sentiment Summary")
    lines.append(f"- **Total Messages**: {total}")
    lines.append(f"- **Bullish**: {bullish}")
    lines.append(f"- **Bearish**: {bearish}")
    lines.append(f"- **Neutral**: {neutral}")

    # Sentiment ratio bar (visual)
    if total > 0:
        bull_pct = bullish / total * 100
        bear_pct = bearish / total * 100
        lines.append("")
        bull_bar = int(bull_pct / 5)  # Each block = 5%
        bear_bar = int(bear_pct / 5)
        neut_bar = 20 - bull_bar - bear_bar
        bar = "+" * bull_bar + "o" * neut_bar + "-" * bear_bar
        lines.append(f"**Sentiment Bar**: [{bar}]")
        lines.append(f"Bullish {bull_pct:.0f}% | Bearish {bear_pct:.0f}% | Neutral {100 - bull_pct - bear_pct:.0f}%")

    # Recent messages
    if messages:
        lines.append("")
        lines.append(f"## Recent Messages ({len(messages)})")
        lines.append("")
        for i, msg in enumerate(messages, 1):
            sentiment = msg.get("sentiment", "Neutral")
            username = msg.get("username", "unknown")
            body = msg.get("body", "")
            created = msg.get("created_at", "")

            # Sentiment indicator
            if sentiment == "Bullish":
                indicator = "[+]"
            elif sentiment == "Bearish":
                indicator = "[-]"
            else:
                indicator = "[o]"

            lines.append(f"{i}. {indicator} **@{username}** ({created})")
            lines.append(f"   {body}")
            lines.append("")
    else:
        lines.append("")
        lines.append("No recent messages found.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 19. Reddit Sentiment
# ---------------------------------------------------------------------------


def format_reddit_sentiment(data: dict) -> str:
    """Format ``fetch_reddit_sentiment`` output as markdown.

    Shows a numbered list of posts with title, subreddit, upvotes,
    and comments count.  Handles the "unavailable" case gracefully.
    """
    ticker = data.get("ticker", "")

    # Graceful degradation: unavailable
    if data.get("unavailable"):
        lines = [f"# Reddit Discussion: {ticker}"]
        lines.append("")
        lines.append(f"Data unavailable: {data.get('reason', 'Unknown reason')}")
        return "\n".join(lines)

    post_count = data.get("post_count", 0)
    posts = data.get("posts", [])

    lines: list[str] = [f"# Reddit Discussion: {ticker}"]

    lines.append("")
    lines.append(f"**Posts Found**: {post_count} (from r/stocks, r/wallstreetbets, r/investing, r/stockmarket)")

    if posts:
        lines.append("")
        lines.append("## Recent Posts")
        lines.append("")

        for i, post in enumerate(posts, 1):
            title = post.get("title", "No title")
            subreddit = post.get("subreddit", "unknown")
            score = post.get("score", 0)
            comments = post.get("comments", 0)
            date = post.get("date", "Unknown")
            url = post.get("url", "")

            lines.append(f"{i}. **{title}**")
            lines.append(f"   - Subreddit: r/{subreddit} | Upvotes: {_fmt_int(score)} | Comments: {_fmt_int(comments)}")
            lines.append(f"   - Date: {date}")
            if url:
                lines.append(f"   - Link: {url}")
            lines.append("")
    else:
        lines.append("")
        lines.append("No recent posts found for this ticker.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 20. Insider Transactions
# ---------------------------------------------------------------------------


def format_insider_transactions(data: dict) -> str:
    """Format ``get_insider_transactions`` output as markdown.

    Sections: Summary, Transaction Table.
    """
    ticker = data.get("_ticker", "")
    summary = data.get("summary", {})
    transactions = data.get("transactions", [])

    lines: list[str] = [f"# Insider Transactions: {ticker}"]

    # Summary
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- **Total Transactions**: {_fmt_int(summary.get('totalTransactions'))}")
    lines.append(f"- **Buys**: {_fmt_int(summary.get('buyCount'))}")
    lines.append(f"- **Sells**: {_fmt_int(summary.get('sellCount'))}")
    lines.append(f"- **Other**: {_fmt_int(summary.get('otherCount'))}")
    buy_val = summary.get("totalBuyValue")
    sell_val = summary.get("totalSellValue")
    if buy_val is not None:
        lines.append(f"- **Total Buy Value**: {_fmt_large(buy_val)}")
    if sell_val is not None:
        lines.append(f"- **Total Sell Value**: {_fmt_large(sell_val)}")

    # Transaction table
    lines.append("")
    if transactions:
        lines.append(f"## Transactions ({len(transactions)})")
        lines.append("")
        lines.append("| Date | Insider | Type | Shares | Value |")
        lines.append("|------|---------|------|--------|-------|")
        for tx in transactions:
            lines.append(
                f"| {_na(tx.get('date'))} "
                f"| {_na(tx.get('insider'))} "
                f"| {_na(tx.get('type'))} "
                f"| {_fmt_int(tx.get('shares'))} "
                f"| {_fmt_large(tx.get('value'))} |"
            )
    else:
        lines.append("## Transactions")
        lines.append("\nNo insider transactions found.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 21. Upgrades/Downgrades
# ---------------------------------------------------------------------------


def format_upgrades_downgrades(data: dict) -> str:
    """Format ``get_upgrades_downgrades`` output as markdown.

    Shows a table of recent analyst rating changes.
    """
    ticker = data.get("_ticker", "")
    entries = data.get("upgrades_downgrades", [])

    lines: list[str] = [f"# Upgrades/Downgrades: {ticker}"]

    lines.append("")
    if entries:
        lines.append(f"## Recent Rating Changes ({len(entries)})")
        lines.append("")
        lines.append("| Date | Firm | Action | From Grade | To Grade |")
        lines.append("|------|------|--------|------------|----------|")
        for entry in entries:
            lines.append(
                f"| {_na(entry.get('date'))} "
                f"| {_na(entry.get('firm'))} "
                f"| {_na(entry.get('action'))} "
                f"| {_na(entry.get('fromGrade'))} "
                f"| {_na(entry.get('toGrade'))} |"
            )
    else:
        lines.append("No upgrades/downgrades data available.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 22. Earnings Dates
# ---------------------------------------------------------------------------


def format_earnings_dates(data: dict) -> str:
    """Format ``get_earnings_dates`` output as markdown.

    Shows upcoming and past earnings dates with EPS data.
    """
    ticker = data.get("_ticker", "")
    entries = data.get("earnings_dates", [])

    lines: list[str] = [f"# Earnings Dates: {ticker}"]

    # Split into upcoming and past
    upcoming = [e for e in entries if e.get("isUpcoming")]
    past = [e for e in entries if not e.get("isUpcoming")]

    # Upcoming
    lines.append("")
    if upcoming:
        lines.append(f"## Upcoming ({len(upcoming)})")
        lines.append("")
        lines.append("| Date | EPS Estimate |")
        lines.append("|------|-------------|")
        for entry in upcoming:
            lines.append(
                f"| {_na(entry.get('date'))} "
                f"| {_fmt_number(entry.get('epsEstimate'), prefix='$')} |"
            )
    else:
        lines.append("## Upcoming")
        lines.append("\nNo upcoming earnings dates.")

    # Past
    lines.append("")
    if past:
        lines.append(f"## Past ({len(past)})")
        lines.append("")
        lines.append("| Date | EPS Estimate | Reported EPS | Surprise % |")
        lines.append("|------|-------------|-------------|------------|")
        for entry in past:
            surprise = entry.get("surprisePct")
            surprise_str = _fmt_pct(surprise) if surprise is not None else "N/A"
            lines.append(
                f"| {_na(entry.get('date'))} "
                f"| {_fmt_number(entry.get('epsEstimate'), prefix='$')} "
                f"| {_fmt_number(entry.get('reportedEps'), prefix='$')} "
                f"| {surprise_str} |"
            )
    else:
        lines.append("## Past")
        lines.append("\nNo past earnings dates.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 23. Stock News
# ---------------------------------------------------------------------------


def format_stock_news(data: dict) -> str:
    """Format ``get_stock_news`` output as markdown.

    Shows a numbered list of news articles with title, publisher, date, and link.
    """
    ticker = data.get("_ticker", "")
    news = data.get("news", [])

    lines: list[str] = [f"# Stock News: {ticker}"]

    lines.append("")
    if news:
        lines.append(f"**{len(news)} recent articles**")
        lines.append("")
        for i, item in enumerate(news, 1):
            title = _na(item.get("title"))
            publisher = _na(item.get("publisher"))
            date = _na(item.get("date"))
            link = item.get("link")
            related = item.get("relatedTickers", [])

            lines.append(f"{i}. **{title}**")
            lines.append(f"   - Publisher: {publisher}")
            lines.append(f"   - Date: {date}")
            if link:
                lines.append(f"   - Link: {link}")
            if related:
                lines.append(f"   - Related: {', '.join(related)}")
            lines.append("")
    else:
        lines.append("No recent news available.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 24. Tool Constants
# ---------------------------------------------------------------------------


def format_tool_constants(data: dict) -> str:
    """Format ``list_tool_constants`` output as markdown.

    Lists valid parameter values by category.
    """
    lines: list[str] = ["# Tool Constants"]

    for category, values in data.items():
        if category.startswith("_"):
            continue
        lines.append("")
        lines.append(f"## {category}")
        lines.append("")

        if isinstance(values, dict):
            lines.append("| Key | Value |")
            lines.append("|-----|-------|")
            for k, v in values.items():
                lines.append(f"| {k} | {v} |")
        elif isinstance(values, list):
            for v in values:
                lines.append(f"- {v}")
        else:
            lines.append(str(values))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 25. Treasury Yields
# ---------------------------------------------------------------------------


def format_treasury_yields(data: dict) -> str:
    """Format treasury yield data as markdown.

    Shows current yields for 2Y, 10Y, 30Y maturities with recent history.
    """
    lines: list[str] = ["# Treasury Yields"]
    lines.append("")
    lines.append(f"*Data as of: {data.get('as_of', 'N/A')}*")
    lines.append("")

    current = data.get("current", {})
    lines.append("## Current Yields")
    lines.append("")
    lines.append("| Maturity | Yield |")
    lines.append("|----------|-------|")
    lines.append(f"| 2-Year | {_fmt_pct(current.get('2Y'))} |")
    lines.append(f"| 10-Year | {_fmt_pct(current.get('10Y'))} |")
    lines.append(f"| 30-Year | {_fmt_pct(current.get('30Y'))} |")

    # Spread calculation
    y2 = current.get("2Y")
    y10 = current.get("10Y")
    if y2 is not None and y10 is not None:
        spread = round(y10 - y2, 2)
        lines.append("")
        lines.append(f"**10Y-2Y Spread**: {spread:+.2f}% {'(INVERTED)' if spread < 0 else ''}")

    # Recent history for 10Y
    history = data.get("history", {})
    h10 = history.get("10Y", [])
    if h10:
        lines.append("")
        lines.append("## Recent 10Y Yield History")
        lines.append("")
        lines.append("| Date | Yield |")
        lines.append("|------|-------|")
        for rec in h10[-6:]:  # Last 6 entries
            lines.append(f"| {rec.get('date', 'N/A')} | {_fmt_pct(rec.get('yield_pct'))} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 26. Economic Indicators
# ---------------------------------------------------------------------------


def format_economic_indicators(data: dict) -> str:
    """Format economic indicator data as markdown.

    Shows current values, changes, and recent history for each indicator.
    """
    lines: list[str] = ["# Economic Indicators"]
    lines.append("")

    indicators = data.get("indicators", {})

    for key, ind in indicators.items():
        name = ind.get("name", key)
        current = ind.get("current")
        previous = ind.get("previous")
        change = ind.get("change")
        as_of = ind.get("as_of", "N/A")

        lines.append(f"## {name}")
        lines.append("")
        lines.append(f"- **Current**: {_fmt_number(current, decimals=2)}")
        if previous is not None:
            lines.append(f"- **Previous**: {_fmt_number(previous, decimals=2)}")
        if change is not None:
            direction = "+" if change > 0 else ""
            lines.append(f"- **Change**: {direction}{change:.4f}")
        lines.append(f"- **As of**: {as_of}")

        if ind.get("error"):
            lines.append(f"- **Note**: {ind['error']}")

        # Recent history
        history = ind.get("history", [])
        if history:
            lines.append("")
            lines.append("| Date | Value |")
            lines.append("|------|-------|")
            for rec in history[-6:]:
                # Get the value from whichever key is present
                val = None
                for vk in ("rate_pct", "index_value", "growth_pct", "value"):
                    val = rec.get(vk)
                    if val is not None:
                        break
                lines.append(f"| {rec.get('date', 'N/A')} | {_fmt_number(val, decimals=2)} |")

        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 27. Yield Curve
# ---------------------------------------------------------------------------


def format_yield_curve(data: dict) -> str:
    """Format yield curve spread data as markdown.

    Shows current spread, inversion status, and recent trend.
    """
    lines: list[str] = ["# Yield Curve (10Y-2Y Spread)"]
    lines.append("")
    lines.append(f"*Data as of: {data.get('as_of', 'N/A')}*")
    lines.append("")

    spread = data.get("current_spread")
    is_inverted = data.get("is_inverted", False)

    lines.append(f"**Current Spread**: {_fmt_pct(spread)}")
    lines.append(f"**Status**: {'INVERTED' if is_inverted else 'Normal (positive slope)'}")
    lines.append(f"**Interpretation**: {data.get('interpretation', 'N/A')}")

    trend = data.get("trend_3m_change")
    if trend is not None:
        direction = "widening" if trend > 0 else "narrowing"
        lines.append(f"**3-Month Trend**: {trend:+.4f}% ({direction})")

    # Recent history
    history = data.get("history", [])
    if history:
        lines.append("")
        lines.append("## Recent Spread History")
        lines.append("")
        lines.append("| Date | Spread |")
        lines.append("|------|--------|")
        for rec in history[-6:]:
            spread_val = rec.get("spread_pct")
            inverted_marker = " (INV)" if spread_val is not None and spread_val < 0 else ""
            lines.append(f"| {rec.get('date', 'N/A')} | {_fmt_pct(spread_val)}{inverted_marker} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 28. Market Regime
# ---------------------------------------------------------------------------


def format_market_regime(data: dict) -> str:
    """Format market regime assessment as markdown.

    Shows regime classification, S&P 500 vs moving averages, and VIX analysis.
    """
    regime = data.get("regime", "UNKNOWN")
    lines: list[str] = [f"# Market Regime: {regime}"]
    lines.append("")
    lines.append(f"*As of: {data.get('as_of', 'N/A')}*")
    lines.append("")
    lines.append(f"**Assessment**: {data.get('regime_description', 'N/A')}")
    lines.append("")

    # S&P 500 section
    sp500 = data.get("sp500", {})
    lines.append("## S&P 500 Trend")
    lines.append("")
    lines.append(f"- **Current Price**: {_fmt_number(sp500.get('current'), decimals=2, prefix='$')}")
    lines.append(f"- **200-Day MA**: {_fmt_number(sp500.get('200_day_ma'), decimals=2, prefix='$')}")
    lines.append(f"- **50-Day MA**: {_fmt_number(sp500.get('50_day_ma'), decimals=2, prefix='$')}")

    above = sp500.get("above_200ma")
    if above is not None:
        trend_label = "ABOVE" if above else "BELOW"
        pct = sp500.get("pct_from_200ma")
        pct_str = f" ({pct:+.2f}%)" if pct is not None else ""
        lines.append(f"- **Trend**: {trend_label} 200-day MA{pct_str}")

    ret_20d = sp500.get("20d_return_pct")
    if ret_20d is not None:
        lines.append(f"- **20-Day Return**: {ret_20d:+.2f}%")

    lines.append("")

    # VIX section
    vix = data.get("vix", {})
    lines.append("## VIX (Fear Index)")
    lines.append("")
    lines.append(f"- **Current**: {_fmt_number(vix.get('current'), decimals=2)}")
    lines.append(f"- **Level**: {vix.get('level', 'N/A').upper()}")
    lines.append(f"- **Reading**: {vix.get('interpretation', 'N/A')}")

    return "\n".join(lines)
