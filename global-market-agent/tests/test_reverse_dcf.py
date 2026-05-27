"""Tests for the reverse DCF / implied expectations calculator.

Tests cover:
- Basic calculation with known inputs
- Sensitivity and valuation grid outputs
- Edge cases (negative FCF, zero EPS, convergence failure, None inputs)
- EPS fallback when FCF is unavailable
- Report formatting with and without analyst consensus
- Expectation gap interpretation (over/under/fair)
- Flag detection (unrealistic growth, eps_fallback)
"""

from __future__ import annotations

import pytest

from src.utils.reverse_dcf import (
    _dcf_value,
    _solve_implied_growth,
    calculate_reverse_dcf,
    format_reverse_dcf_report,
)


# ===================================================================
# 1. Internal helper tests
# ===================================================================


class TestDcfValue:
    """Validate the forward DCF valuation helper."""

    def test_zero_growth(self):
        """With 0% growth, value is just discounted CF stream + terminal."""
        val = _dcf_value(
            current_cf_per_share=10.0,
            growth_rate=0.0,
            discount_rate=0.10,
            terminal_growth=0.03,
            projection_years=5,
        )
        # Should be a positive finite number
        assert val > 0
        assert not (val != val)  # not NaN

    def test_higher_growth_yields_higher_value(self):
        """Higher growth should produce a higher valuation."""
        kwargs = dict(
            current_cf_per_share=5.0,
            discount_rate=0.10,
            terminal_growth=0.03,
            projection_years=5,
        )
        v_low = _dcf_value(growth_rate=0.05, **kwargs)
        v_high = _dcf_value(growth_rate=0.20, **kwargs)
        assert v_high > v_low

    def test_higher_discount_yields_lower_value(self):
        """Higher discount rate should reduce the present value."""
        kwargs = dict(
            current_cf_per_share=5.0,
            growth_rate=0.15,
            terminal_growth=0.03,
            projection_years=5,
        )
        v_low_dr = _dcf_value(discount_rate=0.08, **kwargs)
        v_high_dr = _dcf_value(discount_rate=0.15, **kwargs)
        assert v_low_dr > v_high_dr


class TestSolveImpliedGrowth:
    """Validate the binary-search solver."""

    def test_roundtrip(self):
        """Solving for g from a known fair value should recover the original g."""
        g_true = 0.15
        price = _dcf_value(
            current_cf_per_share=3.0,
            growth_rate=g_true,
            discount_rate=0.10,
            terminal_growth=0.03,
            projection_years=5,
        )
        g_solved = _solve_implied_growth(
            target_price=price,
            current_cf_per_share=3.0,
            discount_rate=0.10,
            terminal_growth=0.03,
            projection_years=5,
        )
        assert g_solved is not None
        assert abs(g_solved - g_true) < 1e-4

    def test_no_solution_returns_none(self):
        """If target price is way beyond any feasible growth, return None."""
        # Extremely high price with tiny CF — requires >100% growth
        result = _solve_implied_growth(
            target_price=100000.0,
            current_cf_per_share=0.01,
            discount_rate=0.10,
            terminal_growth=0.03,
            projection_years=5,
        )
        assert result is None

    def test_negative_growth(self):
        """A price below zero-growth value should imply negative growth."""
        zero_g_price = _dcf_value(
            current_cf_per_share=5.0,
            growth_rate=0.0,
            discount_rate=0.10,
            terminal_growth=0.03,
            projection_years=5,
        )
        # Set target to half of zero-growth price
        g = _solve_implied_growth(
            target_price=zero_g_price * 0.5,
            current_cf_per_share=5.0,
            discount_rate=0.10,
            terminal_growth=0.03,
            projection_years=5,
        )
        assert g is not None
        assert g < 0


# ===================================================================
# 2. Main function tests
# ===================================================================


class TestCalculateReverseDcf:
    """Test the public ``calculate_reverse_dcf`` function."""

    def test_basic_fcf_calculation(self):
        """Standard case: positive price, FCF, shares."""
        result = calculate_reverse_dcf(
            current_price=150.0,
            shares_outstanding=1_000_000,
            current_fcf=5_000_000,  # $5 FCF/share
            current_eps=4.0,
        )
        assert "error" not in result
        assert result["implied_growth_rate"] is not None
        assert result["metric_used"] == "FCF/share"
        assert result["cf_per_share"] == 5.0
        assert result["current_price"] == 150.0

    def test_sensitivity_keys(self):
        """Sensitivity dict has the expected keys."""
        result = calculate_reverse_dcf(
            current_price=100.0,
            shares_outstanding=1_000_000,
            current_fcf=3_000_000,
            current_eps=2.5,
        )
        assert "sensitivity" in result
        assert "discount_8pct" in result["sensitivity"]
        assert "discount_10pct" in result["sensitivity"]
        assert "discount_12pct" in result["sensitivity"]

    def test_valuation_grid_keys(self):
        """Valuation grid has the expected growth-rate keys."""
        result = calculate_reverse_dcf(
            current_price=100.0,
            shares_outstanding=1_000_000,
            current_fcf=3_000_000,
            current_eps=2.5,
        )
        grid = result["valuation_at_growth_rates"]
        assert "growth_0pct" in grid
        assert "growth_10pct" in grid
        assert "growth_20pct" in grid
        assert "growth_30pct" in grid
        # Values should be increasing with growth
        assert grid["growth_30pct"] > grid["growth_10pct"] > grid["growth_0pct"]

    def test_eps_fallback_when_fcf_negative(self):
        """When FCF is negative, should fall back to EPS."""
        result = calculate_reverse_dcf(
            current_price=50.0,
            shares_outstanding=1_000_000,
            current_fcf=-1_000_000,  # Negative FCF
            current_eps=3.0,
        )
        assert "error" not in result
        assert result["metric_used"] == "EPS"
        assert result["cf_per_share"] == 3.0
        assert "eps_fallback" in result["flags"]

    def test_eps_fallback_when_fcf_none(self):
        """When FCF is None, should fall back to EPS."""
        result = calculate_reverse_dcf(
            current_price=50.0,
            shares_outstanding=1_000_000,
            current_fcf=None,
            current_eps=3.0,
        )
        assert "error" not in result
        assert result["metric_used"] == "EPS"

    def test_eps_fallback_when_shares_none(self):
        """When shares_outstanding is None, FCF per share can't be computed."""
        result = calculate_reverse_dcf(
            current_price=50.0,
            shares_outstanding=None,
            current_fcf=5_000_000,
            current_eps=3.0,
        )
        assert "error" not in result
        assert result["metric_used"] == "EPS"

    def test_error_both_negative(self):
        """When both FCF and EPS are negative, return error."""
        result = calculate_reverse_dcf(
            current_price=50.0,
            shares_outstanding=1_000_000,
            current_fcf=-1_000_000,
            current_eps=-2.0,
        )
        assert "error" in result
        assert "non-positive" in result["error"]

    def test_error_both_none(self):
        """When both FCF and EPS are None, return error."""
        result = calculate_reverse_dcf(
            current_price=50.0,
            shares_outstanding=1_000_000,
            current_fcf=None,
            current_eps=None,
        )
        assert "error" in result

    def test_error_price_zero(self):
        """Price of zero should return error."""
        result = calculate_reverse_dcf(
            current_price=0.0,
            shares_outstanding=1_000_000,
            current_fcf=5_000_000,
            current_eps=4.0,
        )
        assert "error" in result
        assert "positive" in result["error"]

    def test_error_price_none(self):
        """Price of None should return error."""
        result = calculate_reverse_dcf(
            current_price=None,
            shares_outstanding=1_000_000,
            current_fcf=5_000_000,
            current_eps=4.0,
        )
        assert "error" in result

    def test_error_price_negative(self):
        """Negative price should return error."""
        result = calculate_reverse_dcf(
            current_price=-10.0,
            shares_outstanding=1_000_000,
            current_fcf=5_000_000,
            current_eps=4.0,
        )
        assert "error" in result

    def test_error_discount_le_terminal(self):
        """discount_rate <= terminal_growth should return error."""
        result = calculate_reverse_dcf(
            current_price=100.0,
            shares_outstanding=1_000_000,
            current_fcf=5_000_000,
            current_eps=4.0,
            discount_rate=0.03,
            terminal_growth=0.03,
        )
        assert "error" in result
        assert "discount_rate" in result["error"]

    def test_error_projection_years_invalid(self):
        """projection_years out of range should return error."""
        result = calculate_reverse_dcf(
            current_price=100.0,
            shares_outstanding=1_000_000,
            current_fcf=5_000_000,
            current_eps=4.0,
            projection_years=0,
        )
        assert "error" in result
        assert "projection_years" in result["error"]

    def test_flag_unrealistic_high_growth(self):
        """Very high price relative to CF should flag unrealistic growth."""
        # With tiny CF and high price, implied growth > 50%
        result = calculate_reverse_dcf(
            current_price=500.0,
            shares_outstanding=1_000_000,
            current_fcf=1_000_000,  # $1 FCF/share
            current_eps=0.8,
        )
        if result.get("implied_growth_rate") is not None:
            if result["implied_growth_rate"] > 0.50:
                assert "unrealistic_high_growth" in result["flags"]

    def test_flag_unrealistic_negative_growth(self):
        """Very low price relative to CF should flag negative growth."""
        # Price much lower than zero-growth value
        result = calculate_reverse_dcf(
            current_price=5.0,
            shares_outstanding=1_000_000,
            current_fcf=10_000_000,  # $10 FCF/share
            current_eps=8.0,
        )
        if result.get("implied_growth_rate") is not None:
            if result["implied_growth_rate"] < -0.20:
                assert "unrealistic_negative_growth" in result["flags"]

    def test_custom_parameters(self):
        """Custom discount rate, terminal growth, and projection years."""
        result = calculate_reverse_dcf(
            current_price=100.0,
            shares_outstanding=1_000_000,
            current_fcf=4_000_000,
            current_eps=3.0,
            discount_rate=0.12,
            terminal_growth=0.02,
            projection_years=10,
        )
        assert "error" not in result
        assert result["discount_rate"] == 0.12
        assert result["terminal_growth"] == 0.02
        assert result["projection_years"] == 10

    def test_implied_growth_sign_check(self):
        """A high price/CF ratio should imply positive growth."""
        # At 30x FCF, there should be positive implied growth
        result = calculate_reverse_dcf(
            current_price=150.0,
            shares_outstanding=1_000_000,
            current_fcf=5_000_000,  # $5 FCF/share -> 30x
            current_eps=4.0,
        )
        assert result["implied_growth_rate"] is not None
        assert result["implied_growth_rate"] > 0

    def test_convergence_failure_extreme_price(self):
        """Price beyond solvable range should produce error or flag."""
        result = calculate_reverse_dcf(
            current_price=1_000_000.0,
            shares_outstanding=1_000_000,
            current_fcf=100,  # $0.0001/share
            current_eps=0.0001,
        )
        # Should either have error or convergence flag
        has_issue = ("error" in result or
                     result.get("implied_growth_rate") is None)
        assert has_issue


# ===================================================================
# 3. Report formatting tests
# ===================================================================


class TestFormatReverseDcfReport:
    """Test the markdown report formatter."""

    def _make_result(self, implied_g=0.20, **overrides):
        """Helper to build a standard result dict."""
        base = {
            "implied_growth_rate": implied_g,
            "current_price": 135.0,
            "cf_per_share": 5.0,
            "metric_used": "FCF/share",
            "discount_rate": 0.10,
            "terminal_growth": 0.03,
            "projection_years": 5,
            "sensitivity": {
                "discount_8pct": 0.17,
                "discount_10pct": 0.20,
                "discount_12pct": 0.23,
            },
            "valuation_at_growth_rates": {
                "growth_0pct": 60.0,
                "growth_10pct": 95.0,
                "growth_15pct": 115.0,
                "growth_20pct": 138.0,
                "growth_25pct": 165.0,
                "growth_30pct": 195.0,
            },
            "flags": [],
        }
        base.update(overrides)
        return base

    def test_basic_report_structure(self):
        """Report includes the key section header and core finding."""
        result = self._make_result()
        report = format_reverse_dcf_report(result, "NVDA")

        assert "### Implied Expectations Analysis (NVDA)" in report
        assert "20.0% annual FCF/share growth" in report
        assert "Sensitivity" in report
        assert "Fair Value" in report

    def test_report_with_consensus_overvalued(self):
        """When implied > consensus by >5%, should say overvalued."""
        result = self._make_result(implied_g=0.25)
        report = format_reverse_dcf_report(
            result, "NVDA", analyst_consensus_growth=0.15
        )

        assert "Expectation Gap" in report
        assert "overvalued" in report.lower()
        assert "+10.0%" in report

    def test_report_with_consensus_undervalued(self):
        """When implied < consensus by >5%, should say undervalued."""
        result = self._make_result(implied_g=0.10)
        report = format_reverse_dcf_report(
            result, "NVDA", analyst_consensus_growth=0.20
        )

        assert "Expectation Gap" in report
        assert "undervalued" in report.lower()

    def test_report_with_consensus_fairly_valued(self):
        """When gap is small, should say fairly valued."""
        result = self._make_result(implied_g=0.18)
        report = format_reverse_dcf_report(
            result, "NVDA", analyst_consensus_growth=0.20
        )

        assert "fairly valued" in report.lower()

    def test_report_without_consensus(self):
        """Without analyst consensus, no expectation gap section."""
        result = self._make_result()
        report = format_reverse_dcf_report(result, "NVDA")

        assert "Expectation Gap" not in report

    def test_report_with_eps_fallback_flag(self):
        """EPS fallback flag should appear in the report."""
        result = self._make_result(
            metric_used="EPS",
            flags=["eps_fallback"],
        )
        report = format_reverse_dcf_report(result, "TSLA")

        assert "EPS" in report
        assert "FCF was negative" in report or "EPS" in report

    def test_report_with_unrealistic_high_flag(self):
        """Unrealistic high growth flag should produce a warning."""
        result = self._make_result(
            implied_g=0.65,
            flags=["unrealistic_high_growth"],
        )
        report = format_reverse_dcf_report(result, "MEME")

        assert "Warning" in report
        assert "speculative" in report.lower()

    def test_report_with_unrealistic_negative_flag(self):
        """Unrealistic negative growth flag should produce a warning."""
        result = self._make_result(
            implied_g=-0.30,
            flags=["unrealistic_negative_growth"],
        )
        report = format_reverse_dcf_report(result, "DEAD")

        assert "Warning" in report
        assert "distress" in report.lower()

    def test_report_error_case(self):
        """When result has error and no implied_growth, report should note it."""
        result = {
            "error": "Cannot compute reverse DCF: both FCF and EPS are non-positive.",
            "current_price": 50.0,
            "current_fcf": -1000000,
            "current_eps": -2.0,
            "implied_growth_rate": None,
        }
        report = format_reverse_dcf_report(result, "FAIL")

        assert "FAIL" in report
        assert "Note" in report
        assert "non-positive" in report

    def test_sensitivity_table_in_report(self):
        """Sensitivity table should include all discount rate rows."""
        result = self._make_result()
        report = format_reverse_dcf_report(result, "AAPL")

        assert "8%" in report
        assert "10%" in report
        assert "12%" in report

    def test_valuation_grid_in_report(self):
        """Valuation grid should show dollar values at different growth rates."""
        result = self._make_result()
        report = format_reverse_dcf_report(result, "AAPL")

        assert "$60.00" in report
        assert "$95.00" in report
        assert "$195.00" in report
