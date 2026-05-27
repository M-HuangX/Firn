"""Tests for audit v3 deterministic verdict merger."""

import pytest

from src.audit.verdict import (
    merge_evidence_and_verdict,
    match_evidence_pairs,
    text_similarity,
    determine_verdict,
    find_r1_match,
    extract_numbers,
)


class TestTextSimilarity:
    def test_identical(self):
        assert text_similarity("hello world", "hello world") == 1.0

    def test_contained(self):
        assert text_similarity("hello", "hello world") == 0.9

    def test_empty(self):
        assert text_similarity("", "hello") == 0.0

    def test_no_overlap(self):
        assert text_similarity("foo bar", "baz qux") == 0.0

    def test_partial_overlap(self):
        sim = text_similarity("revenue grew 26%", "revenue increased 26% YoY")
        assert 0.2 < sim < 0.8


class TestExtractNumbers:
    def test_integers(self):
        assert "5100" in extract_numbers("totalRevenue: 5100000000")

    def test_decimals(self):
        assert "18.923" in extract_numbers("trailingPE: 18.923")

    def test_negative(self):
        assert "-115" in extract_numbers("FCF: -115M")

    def test_no_numbers(self):
        assert extract_numbers("no numbers here") == set()

    def test_comma_separated(self):
        nums = extract_numbers("value: 1,234,567")
        assert "1234567" in nums


class TestDetermineVerdict:
    def test_verified_all_paths(self):
        """R1 strong + R2a + R2b = verified"""
        r1 = {"verdict": "found"}
        assert determine_verdict(True, True, r1, "standard") == "verified"

    def test_verified_specialist_chain_only(self):
        """R1 strong + R2a (no R2b) = verified"""
        r1 = {"verdict": "found"}
        assert determine_verdict(False, True, r1, "standard") == "verified"

    def test_supported_source_only(self):
        """R2b only (no specialist chain) = supported"""
        assert determine_verdict(True, False, None, "standard") == "supported"

    def test_specialist_judgment_no_r1(self):
        """R2a only, no R1 match = specialist-judgment"""
        assert determine_verdict(False, True, None, "standard") == "specialist-judgment"

    def test_specialist_judgment_weak_r1(self):
        """R2a + R1 derived = specialist-judgment"""
        r1 = {"verdict": "derived"}
        assert determine_verdict(False, True, r1, "standard") == "specialist-judgment"

    def test_specialist_judgment_not_found_r1(self):
        """R2a + R1 not-found = specialist-judgment"""
        r1 = {"verdict": "not-found"}
        assert determine_verdict(False, True, r1, "standard") == "specialist-judgment"

    def test_supported_specialist_plus_source(self):
        """R2a + R2b (source) but no strong R1 = supported"""
        assert determine_verdict(True, True, None, "standard") == "supported"

    def test_supported_source_plus_weak_r1(self):
        """R2b + R2a + weak R1 = supported (has source)"""
        r1 = {"verdict": "derived"}
        assert determine_verdict(True, True, r1, "standard") == "supported"

    def test_unverified(self):
        """No evidence = unverified"""
        assert determine_verdict(False, False, None, "standard") == "unverified"

    def test_kb_sourced(self):
        assert determine_verdict(True, True, {"verdict": "tool-verified"}, "kb") == "kb-sourced"

    def test_web_sourced(self):
        assert determine_verdict(False, False, None, "web") == "web-sourced"

    def test_computed_from_computation(self):
        assert determine_verdict(True, False, None, "computation") == "computed"

    def test_computed_from_derived(self):
        assert determine_verdict(False, False, None, "derived") == "computed"


class TestFindR1Match:
    def test_exact_number_match(self):
        r1_claims = [
            {"agent": "fundamental", "claim": "Revenue $5.1B", "raw_value": "5100000000", "verdict": "tool-verified"},
            {"agent": "fundamental", "claim": "P/E 18.9x", "raw_value": "18.923", "verdict": "tool-verified"},
        ]
        match = find_r1_match("fundamental", "Revenue reached $5.1B in fiscal 2025", r1_claims)
        assert match is not None
        assert "5.1" in match["claim"] or "5100" in match["raw_value"]

    def test_wrong_agent(self):
        r1_claims = [
            {"agent": "fundamental", "claim": "Revenue $5.1B", "raw_value": "5100000000", "verdict": "tool-verified"},
        ]
        match = find_r1_match("technical", "Revenue $5.1B", r1_claims)
        assert match is None

    def test_no_claims(self):
        match = find_r1_match("fundamental", "Revenue $5.1B", [])
        assert match is None

    def test_low_similarity(self):
        r1_claims = [
            {"agent": "fundamental", "claim": "CEO is John", "raw_value": "", "verdict": "tool-verified"},
        ]
        match = find_r1_match("fundamental", "Revenue was $5.1 billion", r1_claims)
        assert match is None  # no number overlap, no text overlap


class TestMatchEvidencePairs:
    def test_exact_match(self):
        spec = [{"claim_in_report": "revenue of $5.1B", "specialist_agent": "fundamental"}]
        src = [{"claim_in_report": "revenue of $5.1B", "source_agent": "fundamental"}]
        merged = match_evidence_pairs(spec, src)
        assert len(merged) == 1
        assert "specialist_evidence" in merged[0]
        assert "source_evidence" in merged[0]

    def test_no_match(self):
        spec = [{"claim_in_report": "revenue of $5.1B"}]
        src = [{"claim_in_report": "P/E ratio of 18.9x"}]
        merged = match_evidence_pairs(spec, src)
        assert len(merged) == 2  # one specialist-only, one source-only

    def test_empty_inputs(self):
        merged = match_evidence_pairs([], [])
        assert merged == []


class TestMergeEvidenceAndVerdict:
    def test_full_pipeline(self):
        specialist_ev = [{
            "claim": "Revenue $5.1B",
            "claim_in_report": "total revenue reached **$5.1B**",
            "specialist_agent": "fundamental",
            "specialist_excerpt": "Revenue: $5.1B (+26% YoY)",
            "source_type": "standard",
        }]
        source_ev = [{
            "claim": "Revenue $5.1B",
            "claim_in_report": "total revenue reached **$5.1B**",
            "source_agent": "fundamental",
            "source_tool": "get_income_statement",
            "source_index": 0,
            "raw_value": "5100000000",
            "source_type": "standard",
        }]
        r1_claims = [{
            "agent": "fundamental",
            "claim": "Revenue $5.1B",
            "raw_value": "5100000000",
            "verdict": "found",
        }]
        result = merge_evidence_and_verdict(specialist_ev, source_ev, r1_claims)
        assert "citations" in result
        assert "summary" in result
        assert len(result["citations"]) == 1
        assert result["citations"][0]["verdict"] == "verified"
