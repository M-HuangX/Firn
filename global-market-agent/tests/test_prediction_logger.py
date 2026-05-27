"""Tests for the prediction logger."""

import re
from unittest.mock import MagicMock, patch

import pytest

from src.knowledge_base.kb_api import KnowledgeBase
from src.knowledge_base.prediction_logger import (
    _compute_verdict,
    _parse_prediction_records,
    extract_prediction_data,
    format_prediction_record,
    log_prediction,
    review_predictions,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

REALISTIC_REPORT = """# AAPL Comprehensive Analysis Report

## Executive Summary
Apple Inc. (AAPL) is the world's largest technology company. At $298.21, the market
is pricing in 20-32% annual FCF growth for five years.

---

## Decision Dashboard

| | Recommendation | Action |
|---|---|---|
| **Already Own** | **Hold** | Maintain position; consider trimming on rallies above $305. |
| **Considering Buying** | **Underweight** | Avoid initiating new long positions at current levels. |
| **Short-term Trade** | **Hold** | No compelling entry now. |

**Key Price Levels**: Support $292, $287, $280 | Resistance $300.92, $301.44, $310
**Next Catalyst**: Earnings release (FQ3 2026) -- **July 30, 2026**
**Risk Level**: **High** -- Stock trades at 36x trailing earnings

---

## Long-term Investment Perspective (1-5 Year Horizon)

- **Thesis**: Apple is a world-class business with a wide moat.
- **Quality Rating**: **9/10**
- **Value Rating**: **2/10**
- **Recommendation**: **Hold** (for existing owners) / **Underweight** (for new buyers)
- **Conviction Level**: **Low** -- The quality is undeniable.

---

## Short-term Trading Perspective (Days to Weeks)

- **Current Bias**: **Bullish** but **overbought**
- **Recommendation**: **Hold** -- Do not chase.
"""

BULLISH_REPORT = """# NVDA Comprehensive Analysis Report

## Executive Summary
NVIDIA Corporation remains the dominant force in AI computing, trading near all-time highs at $235.67.

## Decision Dashboard

| | Recommendation | Action |
|---|---|---|
| **Already Own** | **Overweight** | Hold core position |
| **Considering Buying** | **Hold** for now | Wait for pullback |
| **Short-term Trade** | **Buy** (aggressive) | Long above $236.05 |

**Risk Level**: **High** -- extreme overbought readings

## Long-term Investment Perspective (1-5 Year Horizon)

- **Recommendation**: **Overweight**
- **Conviction Level**: **Medium** -- business quality is high
"""


@pytest.fixture
def kb(tmp_path):
    """Return a KnowledgeBase rooted in a temporary directory."""
    _kb = KnowledgeBase(kb_root=tmp_path)
    _kb.ensure_structure()
    return _kb


# ---------------------------------------------------------------------------
# extract_prediction_data
# ---------------------------------------------------------------------------


class TestExtractPredictionData:
    def test_extracts_rating_from_realistic_report(self):
        data = extract_prediction_data(REALISTIC_REPORT)
        # Should extract "Hold" from the first recommendation pattern match
        assert data["rating"] in ("Hold", "Underweight")

    def test_extracts_conviction(self):
        data = extract_prediction_data(REALISTIC_REPORT)
        assert data["conviction"] == "Low"

    def test_extracts_risk_level(self):
        data = extract_prediction_data(REALISTIC_REPORT)
        assert data["risk_level"] == "High"

    def test_extracts_current_price(self):
        data = extract_prediction_data(REALISTIC_REPORT)
        assert data["current_price"] == pytest.approx(298.21)

    def test_extracts_overweight_rating(self):
        data = extract_prediction_data(BULLISH_REPORT)
        assert data["rating"] == "Overweight"

    def test_extracts_bullish_price(self):
        data = extract_prediction_data(BULLISH_REPORT)
        assert data["current_price"] == pytest.approx(235.67)

    def test_extracts_medium_conviction(self):
        data = extract_prediction_data(BULLISH_REPORT)
        assert data["conviction"] == "Medium"

    def test_empty_report_returns_nones(self):
        data = extract_prediction_data("")
        assert data["rating"] is None
        assert data["conviction"] is None
        assert data["risk_level"] is None
        assert data["current_price"] is None

    def test_none_report_returns_nones(self):
        data = extract_prediction_data(None)
        assert data["rating"] is None

    def test_malformed_report_returns_nones(self):
        data = extract_prediction_data("This is just a random paragraph with no structured data.")
        assert data["rating"] is None
        assert data["conviction"] is None
        assert data["risk_level"] is None

    def test_buy_rating_extraction(self):
        report = '- **Recommendation**: **Buy**\n- **Conviction Level**: **High**'
        data = extract_prediction_data(report)
        assert data["rating"] == "Buy"
        assert data["conviction"] == "High"

    def test_sell_rating_extraction(self):
        report = '- **Recommendation**: **Sell**\n- **Conviction Level**: **High**'
        data = extract_prediction_data(report)
        assert data["rating"] == "Sell"


# ---------------------------------------------------------------------------
# format_prediction_record
# ---------------------------------------------------------------------------


class TestFormatPredictionRecord:
    def test_produces_correct_format(self):
        data = {
            "rating": "Overweight",
            "conviction": "Medium",
            "risk_level": "High",
            "current_price": 189.50,
        }
        record = format_prediction_record("AAPL", data)
        assert "### " in record
        assert "AAPL" in record
        assert "$189.50" in record
        assert "**Rating**: Overweight (Medium conviction)" in record
        assert "**Risk Level**: High" in record
        assert record.startswith("---\n")
        assert record.rstrip().endswith("---")

    def test_handles_none_price(self):
        data = {"rating": "Hold", "conviction": None, "risk_level": None, "current_price": None}
        record = format_prediction_record("TSLA", data)
        assert "N/A" in record
        assert "TSLA" in record
        assert "**Rating**: Hold" in record

    def test_includes_report_path(self):
        data = {"rating": "Buy", "conviction": "High", "risk_level": "Low", "current_price": 100.0}
        record = format_prediction_record("MSFT", data, report_path="/some/path/report_MSFT.md")
        assert "**Report**:" in record

    def test_handles_none_conviction(self):
        data = {"rating": "Buy", "conviction": None, "risk_level": "Medium", "current_price": 50.0}
        record = format_prediction_record("GME", data)
        assert "**Rating**: Buy" in record
        # Should NOT have "(None conviction)"
        assert "None" not in record

    def test_handles_unknown_rating(self):
        data = {"rating": None, "conviction": None, "risk_level": None, "current_price": 100.0}
        record = format_prediction_record("XYZ", data)
        assert "**Rating**: Unknown" in record


# ---------------------------------------------------------------------------
# log_prediction
# ---------------------------------------------------------------------------


class TestLogPrediction:
    def test_logs_prediction_with_realistic_report(self, kb):
        result = log_prediction("AAPL", REALISTIC_REPORT, kb=kb)
        assert result is True

        # Verify prediction was written
        content = kb.read_stock("AAPL", "predictions")
        assert content is not None
        assert "AAPL" in content
        assert "Hold" in content or "Underweight" in content

    def test_appends_on_second_call(self, kb):
        log_prediction("AAPL", REALISTIC_REPORT, kb=kb)
        log_prediction("AAPL", BULLISH_REPORT, kb=kb)

        content = kb.read_stock("AAPL", "predictions")
        assert content is not None
        # Should have two prediction records (two "###" headers)
        headers = [line for line in content.splitlines() if line.startswith("### ")]
        assert len(headers) == 2

    def test_returns_false_for_bad_report(self, kb):
        result = log_prediction("AAPL", "No useful data here whatsoever.", kb=kb)
        assert result is False

    def test_returns_false_for_empty_report(self, kb):
        result = log_prediction("AAPL", "", kb=kb)
        assert result is False

    def test_writes_to_correct_stock_directory(self, kb):
        log_prediction("NVDA", BULLISH_REPORT, kb=kb)
        assert "predictions" in kb.list_stock_files("NVDA")

    def test_includes_report_path(self, kb):
        path = "/home/user/reports/report_AAPL_20260514.md"
        log_prediction("AAPL", REALISTIC_REPORT, kb=kb, report_path=path)
        content = kb.read_stock("AAPL", "predictions")
        assert "report_AAPL_20260514.md" in content

    def test_creates_audit_log(self, kb):
        log_prediction("AAPL", REALISTIC_REPORT, kb=kb)
        log_path = kb.root / "meta" / "update_log.md"
        assert log_path.is_file()
        text = log_path.read_text(encoding="utf-8")
        assert "Prediction logged for AAPL" in text

    def test_default_kb_used_when_none(self):
        """log_prediction should not crash when no KB is provided (it creates a default)."""
        # We just verify it doesn't raise; actual file writes go to default KB location
        # which may or may not exist in test environment -- the function should handle it gracefully
        # We mock the KB to avoid side effects
        with patch("src.knowledge_base.prediction_logger.KnowledgeBase") as MockKB:
            mock_instance = MagicMock()
            mock_instance.read_stock.return_value = None
            MockKB.return_value = mock_instance
            result = log_prediction("TEST", REALISTIC_REPORT)
            # Should have called write_stock
            assert mock_instance.write_stock.called or not result


# ---------------------------------------------------------------------------
# _parse_prediction_records
# ---------------------------------------------------------------------------


class TestParsePredictionRecords:
    def test_parses_single_record(self):
        text = """# Predictions

---
### 2026-05-14 | AAPL | $298.21
- **Rating**: Hold (Low conviction)
- **Risk Level**: High
---
"""
        records = _parse_prediction_records(text)
        assert len(records) == 1
        assert records[0]["date"] == "2026-05-14"
        assert records[0]["ticker"] == "AAPL"
        assert records[0]["price"] == pytest.approx(298.21)
        assert records[0]["rating"] == "Hold"

    def test_parses_multiple_records(self):
        text = """# Predictions

---
### 2026-05-10 | AAPL | $280.00
- **Rating**: Buy (High conviction)
---

---
### 2026-05-14 | AAPL | $298.21
- **Rating**: Hold (Low conviction)
---
"""
        records = _parse_prediction_records(text)
        assert len(records) == 2
        assert records[0]["date"] == "2026-05-10"
        assert records[1]["date"] == "2026-05-14"

    def test_handles_na_price(self):
        text = """---
### 2026-05-14 | TSLA | N/A
- **Rating**: Underweight
---
"""
        records = _parse_prediction_records(text)
        assert len(records) == 1
        assert records[0]["price"] is None

    def test_handles_empty_text(self):
        records = _parse_prediction_records("")
        assert records == []


# ---------------------------------------------------------------------------
# _compute_verdict
# ---------------------------------------------------------------------------


class TestComputeVerdict:
    def test_buy_with_positive_return(self):
        assert _compute_verdict("Buy", 10.0) == "Correct"

    def test_buy_with_negative_return(self):
        assert _compute_verdict("Buy", -10.0) == "Wrong"

    def test_buy_with_flat_return(self):
        assert _compute_verdict("Buy", 1.0) == "Neutral"

    def test_sell_with_negative_return(self):
        assert _compute_verdict("Sell", -10.0) == "Correct"

    def test_sell_with_positive_return(self):
        assert _compute_verdict("Sell", 10.0) == "Wrong"

    def test_hold_with_small_move(self):
        assert _compute_verdict("Hold", 3.0) == "Correct"

    def test_hold_with_large_move(self):
        assert _compute_verdict("Hold", 15.0) == "Missed Move"

    def test_overweight_is_bullish(self):
        assert _compute_verdict("Overweight", 10.0) == "Correct"

    def test_underweight_is_bearish(self):
        assert _compute_verdict("Underweight", -10.0) == "Correct"


# ---------------------------------------------------------------------------
# review_predictions
# ---------------------------------------------------------------------------


class TestReviewPredictions:
    @pytest.mark.asyncio
    async def test_no_predictions_returns_message(self, kb):
        result = await review_predictions(kb=kb)
        assert "No predictions found" in result

    @pytest.mark.asyncio
    async def test_reviews_ticker_with_predictions(self, kb):
        # Seed a prediction
        kb.write_stock("AAPL", "predictions", """# Predictions

---
### 2026-05-10 | AAPL | $280.00
- **Rating**: Buy (High conviction)
- **Risk Level**: Medium
---
""")
        # Mock yfinance
        with patch.dict("sys.modules", {"yfinance": MagicMock()}):
            mock_yf = MagicMock()
            mock_ticker = MagicMock()
            mock_ticker.info = {"currentPrice": 300.0}
            mock_yf.Ticker.return_value = mock_ticker

            with patch("src.knowledge_base.prediction_logger.yf", mock_yf, create=True):
                import sys
                sys.modules["yfinance"] = mock_yf
                try:
                    result = await review_predictions(ticker="AAPL", kb=kb)
                finally:
                    del sys.modules["yfinance"]

        assert "AAPL" in result
        assert "Prediction Review" in result

    @pytest.mark.asyncio
    async def test_reviews_all_tickers(self, kb):
        # Seed predictions for two tickers
        kb.write_stock("AAPL", "predictions", """# Predictions

---
### 2026-05-10 | AAPL | $280.00
- **Rating**: Buy
---
""")
        kb.write_stock("NVDA", "predictions", """# Predictions

---
### 2026-05-10 | NVDA | $200.00
- **Rating**: Overweight
---
""")
        # Without yfinance available
        with patch.dict("sys.modules", {"yfinance": None}):
            result = await review_predictions(kb=kb)

        assert "AAPL" in result
        assert "NVDA" in result

    @pytest.mark.asyncio
    async def test_handles_yfinance_import_error(self, kb):
        """If yfinance is not installed, review still works without current prices."""
        kb.write_stock("AAPL", "predictions", """# Predictions

---
### 2026-05-10 | AAPL | $280.00
- **Rating**: Buy
---
""")
        # Make yfinance import fail
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "yfinance":
                raise ImportError("No module named 'yfinance'")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            result = await review_predictions(ticker="AAPL", kb=kb)

        assert "AAPL" in result
        assert "N/A" in result  # prices should show N/A

    @pytest.mark.asyncio
    async def test_specific_ticker_not_found(self, kb):
        """Reviewing a ticker that has no predictions."""
        result = await review_predictions(ticker="XYZ", kb=kb)
        assert "No predictions found" in result
