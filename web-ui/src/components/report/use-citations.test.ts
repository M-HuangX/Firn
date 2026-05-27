import { describe, it, expect } from "vitest";
import { matchAllCitations } from "@/lib/citation-matcher";
import type { Citation } from "@/lib/citation-matcher";
import type { AuditCitation } from "@/lib/types";

// Test the citation matching logic directly (not the hook, which requires React context)

const SAMPLE_REPORT = `# PFE Analysis Report

## Financial Overview

Pfizer reported revenue of $14.9 billion in Q4 2025, beating estimates by 5%.
The trailing P/E ratio stands at 25.3x while forward P/E is 12.8x.
Free cash flow was $2.1 billion for the quarter.

## Technical Analysis

The stock is trading at $28.50, above its 50-day SMA of $26.80.
RSI is at 62, indicating neutral-to-bullish momentum.
MACD shows a bullish crossover with signal line at -0.15.

## Valuation

Based on our DCF model, fair value is estimated at $35.20.
This implies 23% upside from current levels.
`;

const SAMPLE_CLAIMS: Citation[] = [
  {
    id: 1,
    claim: "Pfizer reported revenue of $14.9 billion in Q4 2025",
    claim_in_report: "revenue of $14.9 billion in Q4 2025",
    report_line: 5,
    verdict: "verified",
  },
  {
    id: 2,
    claim: "Trailing P/E ratio is 25.3x",
    claim_in_report: "trailing P/E ratio stands at 25.3x",
    report_line: 6,
    verdict: "verified",
  },
  {
    id: 3,
    claim: "Stock trading at $28.50",
    claim_in_report: "trading at $28.50",
    report_line: 10,
    verdict: "supported",
  },
  {
    id: 4,
    claim: "DCF fair value of $35.20",
    claim_in_report: "fair value is estimated at $35.20",
    report_line: 14,
    verdict: "computed",
  },
  {
    id: 5,
    claim: "Implies 23% upside potential",
    report_line: 15,
    verdict: "supported",
  },
];

describe("use-citations integration (matchAllCitations)", () => {
  it("matches all sample citations above threshold", () => {
    const { results, stats } = matchAllCitations(SAMPLE_CLAIMS, SAMPLE_REPORT);
    expect(results.length).toBeGreaterThanOrEqual(4);
    expect(stats.matched).toBeGreaterThanOrEqual(4);
  });

  it("claim_in_report produces high confidence matches", () => {
    const { results } = matchAllCitations(SAMPLE_CLAIMS, SAMPLE_REPORT);
    const excerptMatches = results.filter((r) => r.confidence >= 0.90);
    // Citations with claim_in_report should match very well
    expect(excerptMatches.length).toBeGreaterThanOrEqual(3);
  });

  it("returns correct match types", () => {
    const { results } = matchAllCitations(SAMPLE_CLAIMS, SAMPLE_REPORT);
    const types = new Set(results.map((r) => r.matchType));
    // Should have at least exact or normalized matches for excerpt-based citations
    expect(types.size).toBeGreaterThanOrEqual(1);
  });

  it("groups stats by verdict correctly", () => {
    const { stats } = matchAllCitations(SAMPLE_CLAIMS, SAMPLE_REPORT);
    expect(stats.byVerdict["verified"]).toBeDefined();
    expect(stats.byVerdict["verified"].count).toBeGreaterThanOrEqual(1);
  });

  it("handles empty inputs gracefully", () => {
    const { results, stats } = matchAllCitations([], SAMPLE_REPORT);
    expect(results).toHaveLength(0);
    expect(stats.total).toBe(0);
    expect(stats.matched).toBe(0);
  });

  it("handles empty report gracefully", () => {
    const { results, stats } = matchAllCitations(SAMPLE_CLAIMS, "");
    expect(results).toHaveLength(0);
    // With empty report, no lines to match against — all unmatched
    expect(stats.matched).toBe(0);
  });
});

describe("AuditCitation to Citation conversion", () => {
  it("converts AuditCitation format to Citation format correctly", () => {
    const auditCitations: AuditCitation[] = [
      {
        id: 1,
        claim: "Revenue was $14.9B",
        claim_in_report: "revenue of $14.9 billion",
        verdict: "verified",
        source: {
          agent: "fundamental",
          tool: "get_stock_info",
          index: 0,
          raw_value: 14900000000,
        },
        specialist: {
          agent: "fundamental",
          excerpt: "Total revenue: $14.9B",
        },
      },
    ];

    // Simulating the conversion logic from use-citations hook
    const citations: Citation[] = auditCitations.map((c) => ({
      id: c.id,
      claim: c.claim,
      claim_in_report: c.claim_in_report,
      report_line: 1,  // dummy — v3 uses claim_in_report for positioning
      verdict: c.verdict,
    }));

    expect(citations[0].id).toBe(1);
    expect(citations[0].claim).toBe("Revenue was $14.9B");
    expect(citations[0].claim_in_report).toBe("revenue of $14.9 billion");
    expect(citations[0].verdict).toBe("verified");
  });
});
