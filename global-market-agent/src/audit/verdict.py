"""Audit v3 — Deterministic verdict merger.

Merges R2a (specialist evidence) and R2b (source evidence), cross-references
with R1 claims, and assigns verdicts programmatically.

No LLM calls — all logic is deterministic if/else.
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Text similarity
# ---------------------------------------------------------------------------

def text_similarity(a: str, b: str) -> float:
    """Simple text similarity for matching claim_in_report strings.

    Returns:
        1.0 if identical (case-insensitive),
        0.9 if one contains the other,
        otherwise word-level Jaccard similarity.
    """
    if not a or not b:
        return 0.0
    a_lower, b_lower = a.lower().strip(), b.lower().strip()
    if a_lower == b_lower:
        return 1.0
    if a_lower in b_lower or b_lower in a_lower:
        return 0.9
    # Word overlap (Jaccard)
    words_a = set(a_lower.split())
    words_b = set(b_lower.split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


# ---------------------------------------------------------------------------
# Number extraction
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def extract_numbers(text: str) -> set[str]:
    """Extract number strings from text for matching.

    Commas are removed so "1,234,567" becomes "1234567".
    For large integers, abbreviated forms are also included by stripping
    trailing groups of three zeros (e.g. 5100000000 -> {5100000000, 5100000, 5100}).
    This enables matching between raw API values and human-readable report numbers.
    """
    # Remove commas within numbers before matching
    cleaned = text.replace(",", "")
    raw_nums = _NUMBER_RE.findall(cleaned)

    result: set[str] = set()
    for num_str in raw_nums:
        result.add(num_str)
        # For integers (no decimal point), also add abbreviated forms
        # by stripping trailing groups of three zeros
        if "." not in num_str:
            # Strip sign for processing, re-add later
            sign = ""
            digits = num_str
            if digits.startswith("-"):
                sign = "-"
                digits = digits[1:]
            # Repeatedly strip trailing "000" while result is still >= 2 digits
            while digits.endswith("000") and len(digits) > 3:
                digits = digits[:-3]
                result.add(sign + digits)

    return result


# ---------------------------------------------------------------------------
# R1 cross-reference
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[^\w\s$%.]", re.UNICODE)


def _normalize_for_match(text: str) -> str:
    """Lowercase and strip non-essential punctuation for fuzzy matching.

    Keeps $, %, . (important for financial text) but strips colons,
    parentheses, brackets, etc. Collapses multiple spaces.
    """
    result = _PUNCT_RE.sub(" ", text.lower())
    # Collapse multiple spaces
    return " ".join(result.split())


def _tokenize(text: str) -> set[str]:
    """Split normalized text into word tokens, dropping empty strings."""
    return {w for w in _normalize_for_match(text).split() if w}


def _score_r1_candidate(
    r1_claim: dict,
    ref_nums: set[str],
    ref_norm: str,
    ref_words: set[str],
) -> float:
    """Score one R1 claim against a reference text (numbers, normalized, words)."""
    claim_text = r1_claim.get("claim", "") + " " + r1_claim.get("raw_value", "")
    claim_nums = extract_numbers(claim_text)

    # Number overlap (weight 0.5) — overlap coefficient
    if claim_nums and ref_nums:
        intersection = claim_nums & ref_nums
        num_overlap = len(intersection) / min(len(claim_nums), len(ref_nums))
    else:
        num_overlap = 0.0

    # Substring containment (weight 0.3)
    claim_norm = _normalize_for_match(r1_claim.get("claim", ""))
    substr_score = 1.0 if claim_norm in ref_norm else 0.0

    # Word overlap (weight 0.2) — overlap coefficient
    claim_words = _tokenize(claim_text)
    term_score = len(ref_words & claim_words) / max(min(len(ref_words), len(claim_words)), 1)

    return 0.5 * num_overlap + 0.3 * substr_score + 0.2 * term_score


def find_r1_match(
    specialist_agent: str,
    specialist_excerpt: str,
    r1_claims: list[dict],
    r2a_claim: str = "",
) -> dict | None:
    """Find the R1 claim that best matches an R2a entry.

    Matches against both specialist_excerpt and r2a_claim (the R2a agent's
    own claim summary), taking the higher score.  This avoids false negatives
    when the excerpt is a multi-value table row that dilutes number overlap.

    Scoring (per reference text):
        0.5 * number_overlap (overlap coefficient on extracted numbers)
        0.3 * substring_containment (1.0 if normalized claim in reference)
        0.2 * word_overlap (overlap coefficient on words)

    Threshold: 0.35
    """
    agent_claims = [c for c in r1_claims if c.get("agent") == specialist_agent]
    if not agent_claims:
        return None

    # Pre-compute features for both reference texts
    refs = [(extract_numbers(specialist_excerpt),
             _normalize_for_match(specialist_excerpt),
             _tokenize(specialist_excerpt))]
    if r2a_claim:
        refs.append((extract_numbers(r2a_claim),
                      _normalize_for_match(r2a_claim),
                      _tokenize(r2a_claim)))

    best: dict | None = None
    best_score = 0.0

    for claim in agent_claims:
        score = max(
            _score_r1_candidate(claim, ref_nums, ref_norm, ref_words)
            for ref_nums, ref_norm, ref_words in refs
        )
        if score > best_score:
            best_score, best = score, claim

    return best if best_score >= 0.35 else None


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------

def determine_verdict(
    has_source: bool,
    has_specialist: bool,
    r1_match: dict | None,
    source_type: str,
) -> str:
    """Assign a deterministic verdict based on available evidence.

    Priority order:
    1. Special source types (kb, web, computation, derived)
    2. Combined evidence rules
    """
    # Special source types take priority
    if source_type == "kb":
        return "kb-sourced"
    if source_type == "web":
        return "web-sourced"
    if source_type in ("computation", "derived"):
        return "computed"

    # R1 verification strength
    # v4: R1 verdicts simplified to found/derived/not-found
    r1_strong = (
        r1_match is not None
        and r1_match.get("verdict") == "found"
    )

    # Combined verdict — R1+R2a is "verified" regardless of R2b
    if has_specialist and r1_strong:
        return "verified"
    if has_source or has_specialist:
        # Specialist-only with no source evidence and no strong R1 match:
        # likely a specialist's own judgment/computation (e.g. scenario
        # probabilities, scores, DCF results) rather than a data-backed claim.
        if has_specialist and not has_source:
            r1_weak = r1_match is None or r1_match.get("verdict") in (
                "not-found", "derived",
            )
            if r1_weak:
                return "specialist-judgment"
        return "supported"
    return "unverified"


# ---------------------------------------------------------------------------
# Evidence pair matching (R2a <-> R2b)
# ---------------------------------------------------------------------------

def match_evidence_pairs(
    specialist_ev: list[dict],
    source_ev: list[dict],
) -> list[dict]:
    """Match specialist and source evidence by claim_in_report similarity.

    Each specialist entry is matched to at most one source entry (greedy,
    best-first). Unmatched entries appear as specialist-only or source-only.

    Threshold: 0.6 similarity.
    """
    merged: list[dict] = []
    used_source: set[int] = set()

    for se in specialist_ev:
        best_idx: int | None = None
        best_sim = 0.0
        se_text = se.get("claim_in_report", "")

        for i, de in enumerate(source_ev):
            if i in used_source:
                continue
            sim = text_similarity(se_text, de.get("claim_in_report", ""))
            if sim > best_sim:
                best_sim, best_idx = sim, i

        entry: dict = {
            "specialist_evidence": se,
            "source_type": se.get("source_type", "standard"),
        }
        if best_idx is not None and best_sim > 0.6:
            used_source.add(best_idx)
            entry["source_evidence"] = source_ev[best_idx]
            # Prefer source_type from source evidence if non-standard
            if source_ev[best_idx].get("source_type", "standard") != "standard":
                entry["source_type"] = source_ev[best_idx]["source_type"]

        merged.append(entry)

    # Add remaining source-only entries
    for i, de in enumerate(source_ev):
        if i not in used_source:
            merged.append({
                "source_evidence": de,
                "source_type": de.get("source_type", "standard"),
            })

    return merged


# ---------------------------------------------------------------------------
# Citation builder
# ---------------------------------------------------------------------------

def build_citation(
    idx: int,
    entry: dict,
    verdict: str,
    r1_match: dict | None,
) -> dict:
    """Build a single citation dict from merged evidence."""
    se = entry.get("specialist_evidence")
    de = entry.get("source_evidence")

    # Use claim_in_report from either evidence source
    claim_in_report = ""
    if se:
        claim_in_report = se.get("claim_in_report", "")
    if de and not claim_in_report:
        claim_in_report = de.get("claim_in_report", "")

    citation: dict = {
        "id": idx,
        "claim": (se or de or {}).get("claim", ""),
        "claim_in_report": claim_in_report,
        "verdict": verdict,
        "source": {},
        "evidence": {},
    }

    if de:
        citation["source"] = {
            "agent": de.get("source_agent", ""),
            "tool": de.get("source_tool", ""),
            "index": de.get("source_index", -1),
            "raw_value": de.get("raw_value", ""),
        }
        citation["evidence"]["source_grep"] = de.get("grep_evidence", "")
    elif r1_match and r1_match.get("source_index", -1) >= 0:
        # Fallback: for specialist-only citations, get source info from R1
        citation["source"] = {
            "agent": r1_match.get("agent", ""),
            "tool": r1_match.get("source_tool", ""),
            "index": r1_match.get("source_index", -1),
            "raw_value": "",
        }

    if se:
        citation["specialist"] = {
            "agent": se.get("specialist_agent", ""),
            "excerpt": se.get("specialist_excerpt", ""),
        }
        citation["evidence"]["specialist_grep"] = se.get("grep_evidence", "")

    if r1_match:
        citation["r1_match"] = {
            "agent": r1_match.get("agent", ""),
            "claim_id": r1_match.get("claim_id", 0),
            "verdict": r1_match.get("verdict", ""),
            "source_tool": r1_match.get("source_tool", ""),
            "source_index": r1_match.get("source_index", -1),
        }

    return citation


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def build_summary(citations: list[dict]) -> dict:
    """Count verdicts across all citations."""
    counts: dict[str, int] = {}
    for c in citations:
        v = c.get("verdict", "unknown")
        counts[v] = counts.get(v, 0) + 1
    return {
        "total": len(citations),
        "verdicts": counts,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def merge_evidence_and_verdict(
    specialist_evidence: list[dict],
    source_evidence: list[dict],
    r1_claims: list[dict],
) -> dict:
    """Merge R2a + R2b evidence, cross-reference R1, assign verdicts.

    Returns:
        {"citations": [...], "summary": {...}}
    """
    # 1. Match R2a <-> R2b by claim_in_report text similarity
    merged = match_evidence_pairs(specialist_evidence, source_evidence)

    # 2. For each merged entry, determine verdict
    citations: list[dict] = []
    for i, entry in enumerate(merged):
        has_source = entry.get("source_evidence") is not None
        has_specialist = entry.get("specialist_evidence") is not None
        source_type = entry.get("source_type", "standard")

        # R1 cross-reference
        r1_match = None
        if has_specialist:
            se = entry["specialist_evidence"]
            r1_match = find_r1_match(
                se.get("specialist_agent", ""),
                se.get("specialist_excerpt", ""),
                r1_claims,
                r2a_claim=se.get("claim", ""),
            )

        verdict = determine_verdict(has_source, has_specialist, r1_match, source_type)
        citation = build_citation(i + 1, entry, verdict, r1_match)
        citations.append(citation)

    # 3. Build summary
    summary = build_summary(citations)

    return {"citations": citations, "summary": summary}
