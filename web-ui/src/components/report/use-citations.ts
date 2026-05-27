"use client";

import { useMemo } from "react";
import { matchAllCitations } from "@/lib/citation-matcher";
import type { Citation, MatchResult, MatchStats } from "@/lib/citation-matcher";
import type { AuditCitation } from "@/lib/types";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface MatchedCitation {
  id: number;
  claim: string;
  claimInReport?: string;
  verdict: string;
  section: string;
  source?: {
    agent?: string;
    tool?: string;
    raw_value?: unknown;
  };
  specialist?: {
    agent?: string;
    excerpt?: string;
  };
  /** Matched line in markdown (1-based) */
  matchedLine: number;
  confidence: number;
  matchType: string;
  charOffset?: number;
  charLength?: number;
  /** For compound claims: [firstLine, lastLine] */
  lineSpan?: [number, number];
  /** Sequential display number (1-based), assigned in document order */
  displayNumber: number;
}

export interface UnmatchedCitation {
  id: number;
  claim: string;
  verdict: string;
  section: string;
  /** Original report_line hint from audit agent */
  estimatedLine: number;
}

export interface CitationData {
  matched: MatchedCitation[];
  unmatched: UnmatchedCitation[];
  stats: MatchStats | null;
  /** Citations grouped by matched line number */
  byLine: Map<number, MatchedCitation[]>;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

/**
 * Runs citation-matcher on audit citations against report markdown.
 * Memoized — only re-runs when inputs change.
 */
export function useCitations(
  reportMarkdown: string | undefined,
  auditCitations: AuditCitation[] | undefined
): CitationData {
  return useMemo(() => {
    if (!reportMarkdown || !auditCitations || auditCitations.length === 0) {
      return { matched: [], unmatched: [], stats: null, byLine: new Map() };
    }

    // Convert AuditCitation[] to Citation[] format expected by matcher
    const citations: Citation[] = auditCitations.map((c) => ({
      id: c.id,
      claim: c.claim,
      claim_in_report: c.claim_in_report,
      report_line: 1,  // dummy — not used for positioning anymore, claim_in_report handles it
      verdict: c.verdict,
    }));

    // Run matcher (note: matchAllCitations takes (citations, markdown) order)
    const { results, stats } = matchAllCitations(citations, reportMarkdown);

    // Build result maps — use 0.50 threshold to separate matched/unmatched
    const MATCH_THRESHOLD = 0.50;
    const resultMap = new Map<number, MatchResult>();
    for (const r of results) {
      resultMap.set(r.citationId, r);
    }

    const matched: MatchedCitation[] = [];
    const unmatched: UnmatchedCitation[] = [];

    for (const citation of citations) {
      const result = resultMap.get(citation.id);
      const auditCit = auditCitations.find((c) => c.id === citation.id);

      if (result && result.confidence >= MATCH_THRESHOLD) {
        matched.push({
          id: citation.id,
          claim: citation.claim,
          claimInReport: auditCit?.claim_in_report,
          verdict: citation.verdict,
          section: auditCit?.source?.agent ?? auditCit?.specialist?.agent ?? "",
          source: auditCit?.source ? {
            agent: auditCit.source.agent,
            tool: auditCit.source.tool,
            raw_value: auditCit.source.raw_value,
          } : undefined,
          specialist: auditCit?.specialist,
          matchedLine: result.matchedLine,
          confidence: result.confidence,
          matchType: result.matchType,
          charOffset: result.charOffset,
          charLength: result.charLength,
          lineSpan: result.lineSpan,
          displayNumber: 0, // assigned below
        });
      } else {
        unmatched.push({
          id: citation.id,
          claim: citation.claim,
          verdict: citation.verdict,
          section: auditCit?.source?.agent ?? auditCit?.specialist?.agent ?? "",
          estimatedLine: citation.report_line,
        });
      }
    }

    // Assign display numbers in document order (line ASC, charOffset ASC)
    matched.sort((a, b) => a.matchedLine - b.matchedLine || (a.charOffset ?? 0) - (b.charOffset ?? 0));
    for (let i = 0; i < matched.length; i++) {
      matched[i].displayNumber = i + 1;
    }

    // Group by line
    const byLine = new Map<number, MatchedCitation[]>();
    for (const m of matched) {
      const existing = byLine.get(m.matchedLine) ?? [];
      existing.push(m);
      byLine.set(m.matchedLine, existing);
    }

    return { matched, unmatched, stats, byLine };
  }, [reportMarkdown, auditCitations]);
}
