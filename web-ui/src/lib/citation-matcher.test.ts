import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { matchAllCitations, Citation, MatchResult } from './citation-matcher';

// ─── Load real PLTR data ─────────────────────────────────────────────────────

const CITATIONS_PATH = resolve(
  __dirname,
  '../../../global-market-agent/logs/20260516_082842_153a75bb/audit/citations.json',
);
const REPORT_PATH = resolve(
  __dirname,
  '../../../global-market-agent/reports/report_PLTR_20260516_083136.md',
);

const rawCitations = JSON.parse(readFileSync(CITATIONS_PATH, 'utf-8'));
const citations: Citation[] = rawCitations.citations.map((c: any) => ({
  id: c.id,
  claim: c.claim,
  report_line: c.report_line,
  verdict: c.verdict,
}));
const reportMarkdown = readFileSync(REPORT_PATH, 'utf-8');

// ─── Full Match Run ──────────────────────────────────────────────────────────

const { results, stats } = matchAllCitations(citations, reportMarkdown);

// Helper to find result by citation id
function resultFor(id: number): MatchResult {
  const r = results.find(r => r.citationId === id);
  if (!r) throw new Error(`No result for citation #${id}`);
  return r;
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('matchAllCitations — full PLTR dataset', () => {
  it('should match at least 35/40 citations above threshold 0.50', () => {
    expect(stats.matched).toBeGreaterThanOrEqual(35);
    console.log(`\nOverall: ${stats.matched}/${stats.total} matched (${stats.unmatched} unmatched)`);
  });

  it('should produce results for every citation', () => {
    expect(results.length).toBe(citations.length);
  });

  it('should compute valid stats', () => {
    expect(stats.total).toBe(40);
    expect(stats.matched + stats.unmatched).toBe(stats.total);
    expect(Object.keys(stats.byVerdict).length).toBeGreaterThan(0);
    expect(Object.keys(stats.byMatchType).length).toBeGreaterThan(0);
  });
});

describe('specific EASY cases', () => {
  it('#2 "75.2% annual FCF/share growth" should match on line 7', () => {
    const r = resultFor(2);
    expect(r.confidence).toBeGreaterThanOrEqual(0.50);
    expect(r.matchedLine).toBe(7);
  });

  it('#24 "RSI at 43.48" should match near line 82', () => {
    const r = resultFor(24);
    expect(r.confidence).toBeGreaterThanOrEqual(0.50);
    expect(Math.abs(r.matchedLine - 82)).toBeLessThanOrEqual(5);
  });

  it('#26 "EPS beat ($0.33 vs $0.28 est.)" should match near line 88', () => {
    const r = resultFor(26);
    expect(r.confidence).toBeGreaterThanOrEqual(0.50);
    expect(Math.abs(r.matchedLine - 88)).toBeLessThanOrEqual(5);
  });
});

describe('compound case', () => {
  it('#29 "Peter Thiel sold $290M, Alex Karp $66M..." should match insider data', () => {
    const r = resultFor(29);
    expect(r.confidence).toBeGreaterThanOrEqual(0.50);
    // The claim data appears in two places:
    //   Line 74: paragraph summary with all names + amounts
    //   Lines 161-165: insider table with one row per person
    // Both are valid matches. Accept either location.
    const matchesParagraph = r.matchedLine >= 72 && r.matchedLine <= 76;
    const matchesTable = r.matchedLine >= 158 && r.matchedLine <= 170;
    expect(matchesParagraph || matchesTable).toBe(true);
  });
});

describe('non-unique number case', () => {
  it('#1 "Current price $133.99" should match despite $133.99 appearing multiple times', () => {
    const r = resultFor(1);
    expect(r.confidence).toBeGreaterThanOrEqual(0.50);
    // $133.99 appears on lines 7, 17, 19, 80, etc. — should pick one near report_line 3
    expect(r.matchedLine).toBeGreaterThanOrEqual(1);
  });
});

describe('edge cases', () => {
  it('handles claims with many financial metrics (compound multiples)', () => {
    // Citation #27: "Trailing P/E 152.3x, Forward P/E 64.9x, P/S 61.5x, EV/EBITDA 155.3x, PEG 1.94x"
    const r = resultFor(27);
    expect(r.confidence).toBeGreaterThanOrEqual(0.50);
  });

  it('handles table-based data (insider selling table)', () => {
    // Citation #5: "$443M in insider sales"
    const r = resultFor(5);
    expect(r.confidence).toBeGreaterThanOrEqual(0.50);
  });

  it('handles short claims like "VIX at 18.43"', () => {
    const r = resultFor(19);
    expect(r.confidence).toBeGreaterThanOrEqual(0.50);
  });

  it('handles analyst actions claim (#35)', () => {
    const r = resultFor(35);
    expect(r.confidence).toBeGreaterThanOrEqual(0.50);
  });
});

// ─── Sub-paragraph positioning (charOffset) ─────────────────────────────────

describe('charOffset positioning', () => {
  it('exact matches should have charOffset', () => {
    const exactResults = results.filter(r => r.matchType === 'exact');
    for (const r of exactResults) {
      expect(r.charOffset).toBeDefined();
      expect(r.charOffset).toBeGreaterThanOrEqual(0);
    }
  });

  it('normalized matches should have charOffset', () => {
    const normResults = results.filter(r => r.matchType === 'normalized');
    for (const r of normResults) {
      expect(r.charOffset).toBeDefined();
    }
  });

  it('line 7 (Executive Summary) citations should have different charOffsets', () => {
    const line7Results = results.filter(r => r.matchedLine === 7 && r.charOffset !== undefined);
    if (line7Results.length > 1) {
      const offsets = line7Results.map(r => r.charOffset!);
      // Not all offsets should be identical — different claims sit at different positions
      const unique = new Set(offsets);
      expect(unique.size).toBeGreaterThan(1);
    }
  });
});

// ─── Edge cases: robustness ──────────────────────────────────────────────────

describe('edge cases — robustness', () => {
  it('handles empty citations array', () => {
    const { results: r, stats: s } = matchAllCitations([], reportMarkdown);
    expect(r).toEqual([]);
    expect(s.total).toBe(0);
  });

  it('handles empty report', () => {
    const { results: r, stats: s } = matchAllCitations(
      [{ id: 1, claim: 'test', report_line: 1, verdict: 'llm-inferred' }],
      '',
    );
    expect(r).toEqual([]);
    expect(s.total).toBe(0);
  });

  it('handles a claim with no numbers at all', () => {
    const { results: r } = matchAllCitations(
      [{ id: 99, claim: 'Zero insider purchases', report_line: 5, verdict: 'source-verified' }],
      reportMarkdown,
    );
    expect(r.length).toBe(1);
    expect(r[0].confidence).toBeGreaterThanOrEqual(0.50);
  });

  it('handles Windows line endings (\\r\\n)', () => {
    const winReport = reportMarkdown.replace(/\n/g, '\r\n');
    const { results: r, stats: s } = matchAllCitations(citations, winReport);
    expect(s.matched).toBeGreaterThanOrEqual(35);
  });

  it('handles a very short claim', () => {
    const { results: r } = matchAllCitations(
      [{ id: 100, claim: 'VIX', report_line: 38, verdict: 'source-verified' }],
      reportMarkdown,
    );
    expect(r.length).toBe(1);
    // Very short claim may not score well, but should not crash
    expect(r[0].matchedLine).toBeGreaterThan(0);
  });

  it('handles a claim that appears nowhere in the report', () => {
    const { results: r } = matchAllCitations(
      [{ id: 101, claim: 'Bitcoin surged to $999,999 today', report_line: 1, verdict: 'llm-inferred' }],
      reportMarkdown,
    );
    expect(r.length).toBe(1);
    expect(r[0].confidence).toBeLessThan(0.50); // should be unmatched
  });

  it('handles a claim with special regex characters', () => {
    const { results: r } = matchAllCitations(
      [{ id: 102, claim: 'P/E of 152x (trailing)', report_line: 19, verdict: 'source-verified' }],
      reportMarkdown,
    );
    expect(r.length).toBe(1);
    expect(r[0].confidence).toBeGreaterThanOrEqual(0.50);
  });
});

// ─── claim_in_report fast path (Phase 0) ────────────────────────────────────

describe('claim_in_report fast path', () => {
  it('excerpt exact match — verbatim substring from report', () => {
    const { results: r } = matchAllCitations(
      [{
        id: 200,
        claim: '$443M in insider sales',
        claim_in_report: '$443M in insider sales and zero insider purchases',
        report_line: 7,
        verdict: 'source-verified',
      }],
      reportMarkdown,
    );
    expect(r.length).toBe(1);
    expect(r[0].confidence).toBe(1.0);
    expect(r[0].matchType).toBe('exact');
  });

  it('excerpt normalized match — markdown bold stripped to match', () => {
    const { results: r } = matchAllCitations(
      [{
        id: 201,
        claim: 'current price $133.99',
        claim_in_report: '**$133.99**',
        report_line: 7,
        verdict: 'source-verified',
      }],
      reportMarkdown,
    );
    expect(r.length).toBe(1);
    expect(r[0].confidence).toBeGreaterThanOrEqual(0.95);
    expect(['exact', 'normalized']).toContain(r[0].matchType);
  });

  it('excerpt miss — falls back to claim-based cascade', () => {
    const { results: r } = matchAllCitations(
      [{
        id: 202,
        claim: 'VIX at 18.43',
        claim_in_report: 'this excerpt does not exist anywhere in the report at all',
        report_line: 46,
        verdict: 'source-verified',
      }],
      reportMarkdown,
    );
    expect(r.length).toBe(1);
    expect(r[0].confidence).toBeGreaterThanOrEqual(0.50);
  });

  it('no excerpt field — normal cascade works', () => {
    const { results: r } = matchAllCitations(
      [{
        id: 203,
        claim: 'VIX at 18.43',
        report_line: 46,
        verdict: 'source-verified',
      }],
      reportMarkdown,
    );
    expect(r.length).toBe(1);
    expect(r[0].confidence).toBeGreaterThanOrEqual(0.50);
  });

  it('empty string excerpt — skips Phase 0, falls through to normal cascade', () => {
    const { results: r } = matchAllCitations(
      [{
        id: 204,
        claim: 'VIX at 18.43',
        claim_in_report: '',
        report_line: 46,
        verdict: 'source-verified',
      }],
      reportMarkdown,
    );
    expect(r.length).toBe(1);
    expect(r[0].confidence).toBeGreaterThanOrEqual(0.50);
  });
});

// ─── Summary Table ───────────────────────────────────────────────────────────

describe('summary table', () => {
  it('prints all 40 citation match results', () => {
    console.log('\n' + '='.repeat(120));
    console.log('CITATION MATCH RESULTS — PLTR Audit');
    console.log('='.repeat(120));
    console.log(
      'ID'.padStart(4) + '  ' +
      'Verdict'.padEnd(20) + '  ' +
      'Type'.padEnd(12) + '  ' +
      'Conf'.padStart(6) + '  ' +
      'Est'.padStart(5) + '  ' +
      'Match'.padStart(5) + '  ' +
      'Offset'.padStart(6) + '  ' +
      'Claim (truncated)'.padEnd(45),
    );
    console.log('-'.repeat(120));

    for (const r of results) {
      const cit = citations.find(c => c.id === r.citationId)!;
      const claimTrunc = cit.claim.length > 45 ? cit.claim.slice(0, 42) + '...' : cit.claim;
      const flag = r.confidence < 0.50 ? ' !!!' : '';
      const offset = r.charOffset !== undefined ? String(r.charOffset) : '-';
      console.log(
        String(r.citationId).padStart(4) + '  ' +
        cit.verdict.padEnd(20) + '  ' +
        r.matchType.padEnd(12) + '  ' +
        r.confidence.toFixed(3).padStart(6) + '  ' +
        String(cit.report_line).padStart(5) + '  ' +
        String(r.matchedLine).padStart(5) + '  ' +
        offset.padStart(6) + '  ' +
        claimTrunc + flag,
      );
    }

    console.log('-'.repeat(120));
    console.log(`\nMatched: ${stats.matched}/${stats.total}  |  Unmatched: ${stats.unmatched}`);
    console.log('\nBy match type:', JSON.stringify(stats.byMatchType));
    console.log('By verdict:');
    for (const [v, s] of Object.entries(stats.byVerdict)) {
      console.log(`  ${v}: ${s.count} citations, avg confidence ${s.avgConfidence.toFixed(3)}`);
    }
    console.log('='.repeat(120));

    // This test always passes — it's for output only
    expect(true).toBe(true);
  });
});
