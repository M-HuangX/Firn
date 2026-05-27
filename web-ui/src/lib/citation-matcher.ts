// citation-matcher.ts — Match audit citations to report line positions
// No external dependencies. Pure algorithm.

// ─── Types ───────────────────────────────────────────────────────────────────

export interface Citation {
  id: number;
  claim: string;
  claim_in_report?: string;  // EXACT text from report for positioning
  report_line: number;        // hint line (may be dummy value like 1)
  verdict: string;
}

export interface MatchResult {
  citationId: number;
  matchedLine: number;
  confidence: number;
  matchType: 'exact' | 'normalized' | 'scored' | 'compound';
  charOffset?: number;     // character offset within the matched line (for sub-paragraph positioning)
  charLength?: number;     // length of the matched span
  /** For compound claims: line range spanned by sub-claims [first, last] */
  lineSpan?: [number, number];
  debugScores?: {
    numberScore: number;
    termScore: number;
    similarityScore: number;
    proximityScore: number;
  };
}

export interface MatchStats {
  total: number;
  matched: number;
  unmatched: number;
  byVerdict: Record<string, { count: number; avgConfidence: number }>;
  byMatchType: Record<string, number>;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const STOP_WORDS = new Set([
  'the', 'at', 'in', 'of', 'for', 'and', 'is', 'to', 'with', 'a', 'an',
  'from', 'by', 'on', 'vs', 'are', 'was', 'not', 'but', 'or', 'this', 'that',
  'has', 'its', 'be', 'as', 'it', 'than',
]);

const NUMBER_RE = /[-+]?\$?\d[\d,]*\.?\d*[%xBMKbmk]?/g;
const FINANCIAL_TERMS = new Set([
  'P/E', 'PE', 'FCF', 'MACD', 'RSI', 'EPS', 'SMA', 'ADX', 'EBITDA', 'PEG',
  'P/S', 'DCF', 'YoY', 'MoM', 'CPI', 'GDP', 'VIX', 'SBC', 'CMF', 'ATR',
]);

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Strip markdown formatting from text */
function stripMarkdown(text: string): string {
  return text
    .replace(/\*\*([^*]+)\*\*/g, '$1')   // bold
    .replace(/\*([^*]+)\*/g, '$1')        // italic
    .replace(/~~([^~]+)~~/g, '$1')        // strikethrough
    .replace(/`([^`]+)`/g, '$1')          // inline code
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1') // links
    .replace(/\|/g, ' ')                  // table delimiters
    .replace(/^[\s|:-]+$/gm, ' ')         // table alignment rows (only full-line patterns)
    .replace(/#+\s*/g, '')                // heading markers
    .replace(/\s+/g, ' ')                // collapse whitespace
    .trim();
}

/** Find character offset of the best matching snippet within a line */
function findCharOffset(claim: string, line: string): { offset: number; length: number } | undefined {
  const normClaim = stripMarkdown(claim).toLowerCase();
  const normLine = stripMarkdown(line).toLowerCase();

  // Try exact substring of full claim
  const idx = normLine.indexOf(normClaim);
  if (idx >= 0) return { offset: idx, length: normClaim.length };

  // Try finding anchor via the most distinctive number in the claim
  const nums = claim.match(NUMBER_RE);
  if (nums && nums.length > 0) {
    for (const numStr of nums) {
      // Search for original form first (e.g. "4,395"), then stripped form (e.g. "4395")
      const original = numStr.replace(/[$+]/g, '').toLowerCase();
      const stripped = numStr.replace(/[$,+]/g, '').toLowerCase();
      let pos = normLine.indexOf(original);
      if (pos < 0) pos = normLine.indexOf(stripped);
      if (pos >= 0) {
        return { offset: Math.max(0, pos - 10), length: Math.min(normClaim.length + 20, normLine.length - pos) };
      }
    }
  }

  // Try finding anchor via a key term (proper noun or financial term)
  const terms = extractKeyTerms(claim);
  for (const t of terms) {
    const pos = normLine.indexOf(t.toLowerCase());
    if (pos >= 0) {
      return { offset: Math.max(0, pos - 5), length: Math.min(normClaim.length + 10, normLine.length - pos) };
    }
  }

  return undefined;
}

/** Normalize a number string for comparison: remove $, commas, trailing units */
function normalizeNumber(s: string): number {
  let cleaned = s.replace(/[$,]/g, '').replace(/[+]/g, '');
  const suffix = cleaned.match(/[%xBMKbmk]$/);
  if (suffix) cleaned = cleaned.slice(0, -1);
  return parseFloat(cleaned);
}

/** Extract all numbers from text */
function extractNumbers(text: string): number[] {
  const matches = text.match(NUMBER_RE) || [];
  return matches.map(normalizeNumber).filter(n => !isNaN(n));
}

/** Extract meaningful key terms from text */
function extractKeyTerms(text: string): string[] {
  const words = stripMarkdown(text).split(/[\s,;:()\[\]{}]+/);
  const terms: string[] = [];
  for (const w of words) {
    if (!w) continue;
    const upper = w.toUpperCase();
    if (FINANCIAL_TERMS.has(upper) || FINANCIAL_TERMS.has(w)) {
      terms.push(upper);
    } else if (/^[A-Z][A-Z0-9/]+$/.test(w) && w.length >= 2) {
      terms.push(w); // acronyms / tickers
    } else if (w.length > 5 && !STOP_WORDS.has(w.toLowerCase())) {
      terms.push(w.toLowerCase());
    } else if (/^[A-Z][a-z]+$/.test(w) && w.length > 3 && !STOP_WORDS.has(w.toLowerCase())) {
      terms.push(w.toLowerCase()); // proper nouns
    }
  }
  return terms;
}

/** LCS length between two strings (character-level) */
function lcsLength(a: string, b: string): number {
  const m = a.length, n = b.length;
  // Optimize: use two rows instead of full matrix
  let prev = new Uint16Array(n + 1);
  let curr = new Uint16Array(n + 1);
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (a[i - 1] === b[j - 1]) {
        curr[j] = prev[j - 1] + 1;
      } else {
        curr[j] = Math.max(prev[j], curr[j - 1]);
      }
    }
    [prev, curr] = [curr, prev];
    curr.fill(0);
  }
  return prev[n];
}

/** Check if two numbers are approximately equal (within 0.5% or absolute 0.05) */
function numbersClose(a: number, b: number): boolean {
  if (a === b) return true;
  const absA = Math.abs(a);
  const diff = Math.abs(a - b);
  if (absA < 1) return diff < 0.05;
  return diff / absA < 0.005;
}

// ─── Phase Matchers ──────────────────────────────────────────────────────────

function tryExactMatch(claim: string, lines: string[]): { line: number } | null {
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes(claim)) return { line: i + 1 };
  }
  // Try key phrases: 8+ word continuous chunks
  const words = claim.split(/\s+/);
  if (words.length >= 8) {
    for (let len = words.length; len >= 8; len--) {
      for (let start = 0; start <= words.length - len; start++) {
        const phrase = words.slice(start, start + len).join(' ');
        for (let i = 0; i < lines.length; i++) {
          if (lines[i].includes(phrase)) return { line: i + 1 };
        }
      }
    }
  }
  return null;
}

function tryNormalizedMatch(claim: string, lines: string[]): { line: number } | null {
  const normClaim = stripMarkdown(claim).toLowerCase();
  for (let i = 0; i < lines.length; i++) {
    const normLine = stripMarkdown(lines[i]).toLowerCase();
    if (normLine.includes(normClaim)) return { line: i + 1 };
  }
  return null;
}

function scoreLine(
  claim: string, line: string, candidateLine: number,
  reportLine: number, lineWindow: number,
): { score: number; debug: MatchResult['debugScores'] } {
  const claimNums = extractNumbers(claim);
  const lineNums = extractNumbers(line);
  const claimTerms = extractKeyTerms(claim);
  const lineStripped = stripMarkdown(line).toLowerCase();

  // Number score
  let numberScore = 0;
  const hasNumbers = claimNums.length > 0;
  if (hasNumbers) {
    let matched = 0;
    for (const cn of claimNums) {
      if (lineNums.some(ln => numbersClose(cn, ln))) matched++;
    }
    numberScore = matched / claimNums.length;
  }

  // Key term score
  let termScore = 0;
  if (claimTerms.length > 0) {
    let matched = 0;
    for (const t of claimTerms) {
      if (lineStripped.includes(t.toLowerCase())) matched++;
    }
    termScore = matched / claimTerms.length;
  }

  // Text similarity (LCS ratio)
  // Cap line length for LCS perf, but use claim length to decide cap:
  // short claims (<50 chars) are cheap even against long lines
  const normClaim = stripMarkdown(claim).toLowerCase();
  const lcsCap = normClaim.length < 50 ? 1000 : 600;
  const lineForLcs = lineStripped.slice(0, lcsCap);
  const lcs = lcsLength(normClaim, lineForLcs);
  const similarityScore = Math.min(1, (2 * lcs) / (normClaim.length + lineForLcs.length));

  // Proximity score
  const proximityScore = Math.max(0, 1 - Math.abs(candidateLine - reportLine) / lineWindow);

  // Weight redistribution
  let wNum = 0.35, wTerm = 0.25, wSim = 0.20, wProx = 0.20;
  if (!hasNumbers) {
    // Redistribute number weight proportionally
    const total = wTerm + wSim + wProx;
    wTerm += wNum * (wTerm / total);
    wSim += wNum * (wSim / total);
    wProx += wNum * (wProx / total);
    wNum = 0;
  }

  const score = wNum * numberScore + wTerm * termScore + wSim * similarityScore + wProx * proximityScore;
  return { score, debug: { numberScore, termScore, similarityScore, proximityScore } };
}

function tryScoredMatch(
  claim: string, reportLine: number, lines: string[], lineWindow: number,
): { line: number; score: number; debug: MatchResult['debugScores'] } {
  let best = { line: 0, score: -1, debug: undefined as MatchResult['debugScores'] };

  // Search within window first
  const lo = Math.max(0, reportLine - 1 - lineWindow);
  const hi = Math.min(lines.length, reportLine - 1 + lineWindow + 1);
  for (let i = lo; i < hi; i++) {
    if (!lines[i].trim()) continue;
    const { score, debug } = scoreLine(claim, lines[i], i + 1, reportLine, lineWindow);
    if (score > best.score) {
      best = { line: i + 1, score, debug };
    }
  }

  // If no good match in window, search full report
  if (best.score < 0.50) {
    for (let i = 0; i < lines.length; i++) {
      if (i >= lo && i < hi) continue; // already checked
      if (!lines[i].trim()) continue;
      const { score, debug } = scoreLine(claim, lines[i], i + 1, reportLine, lines.length);
      if (score > best.score) {
        best = { line: i + 1, score, debug };
      }
    }
  }

  return best;
}

// ─── Compound Claim Handler ──────────────────────────────────────────────────

function isCompound(claim: string): boolean {
  if (claim.includes(';')) return true;
  // Multiple named entities with dollar amounts: "A $X, B $Y" or more
  const dollarGroups = claim.match(/\$[\d,.]+[BMK]?/g);
  if (dollarGroups && dollarGroups.length >= 2) {
    // 2+ dollar groups with commas separating them → likely compound
    const commaSegments = claim.split(',').map(s => s.trim());
    if (commaSegments.length >= 2 && commaSegments.every(s => extractNumbers(s).length > 0)) return true;
  }
  // Multiple comma-separated metric groups (3+)
  const commaSegments = claim.split(',').map(s => s.trim());
  if (commaSegments.length >= 3 && commaSegments.every(s => extractNumbers(s).length > 0)) return true;
  // Parallel structure: "X case ... Y case ..." pattern (e.g., "Bull case $X, Bear case $Y")
  if (/\b\w+\s+case\b.*,.*\b\w+\s+case\b/i.test(claim)) return true;
  return false;
}

function splitCompound(claim: string): string[] {
  if (claim.includes(';')) return claim.split(';').map(s => s.trim()).filter(Boolean);
  // Split at commas but keep context: each sub-claim should be meaningful
  const parts = claim.split(',').map(s => s.trim()).filter(Boolean);
  return parts.length >= 2 ? parts : [claim];
}

function tryCompoundMatch(
  claim: string, reportLine: number, lines: string[],
  lineWindow: number, threshold: number,
): { line: number; score: number; debug: MatchResult['debugScores']; lineSpan?: [number, number] } | null {
  if (!isCompound(claim)) return null;

  const subClaims = splitCompound(claim);
  if (subClaims.length < 2) return null;

  const subResults = subClaims.map(sc => tryScoredMatch(sc, reportLine, lines, lineWindow));
  const allAbove = subResults.every(r => r.score >= threshold);
  if (!allAbove) return null;

  const avgScore = subResults.reduce((sum, r) => sum + r.score, 0) / subResults.length;
  const matchedLines = subResults.map(r => r.line).sort((a, b) => a - b);
  const lineSpan: [number, number] = [matchedLines[0], matchedLines[matchedLines.length - 1]];

  return { line: subResults[0].line, score: avgScore, debug: subResults[0].debug, lineSpan };
}

// ─── Main Entry Point ────────────────────────────────────────────────────────

/**
 * Match all audit citations to their positions in the report markdown.
 *
 * Uses a four-phase cascade: exact substring, normalized, weighted scoring,
 * and compound claim splitting. Returns match results and aggregate statistics.
 *
 * @param citations - Array of audit citations with claim text and estimated line numbers
 * @param reportMarkdown - The full report as a markdown string
 * @param options - Optional threshold (default 0.50) and lineWindow (default 20)
 */
export function matchAllCitations(
  citations: Citation[],
  reportMarkdown: string,
  options?: { threshold?: number; lineWindow?: number },
): { results: MatchResult[]; stats: MatchStats } {
  const threshold = options?.threshold ?? 0.50;
  const lineWindow = options?.lineWindow ?? 20;
  // Normalize line endings (handle Windows \r\n and old Mac \r)
  const lines = reportMarkdown.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
  const results: MatchResult[] = [];

  const hasContent = lines.some(l => l.trim().length > 0);
  if (citations.length === 0 || !hasContent) {
    return { results: [], stats: { total: 0, matched: 0, unmatched: 0, byVerdict: {}, byMatchType: {} } };
  }

  // Safe accessor: lines are 1-indexed in our API, guard out-of-bounds
  const lineAt = (idx: number): string | undefined => lines[idx - 1];
  const charPosFor = (claim: string, lineIdx: number) => {
    const l = lineAt(lineIdx);
    return l ? findCharOffset(claim, l) : undefined;
  };

  for (const cit of citations) {
    let result: MatchResult | null = null;

    // Phase 0: Fast path via claim_in_report (verbatim report text from audit agent)
    if (cit.claim_in_report && cit.claim_in_report.length > 0) {
      const excerptExact = tryExactMatch(cit.claim_in_report, lines);
      if (excerptExact) {
        const charPos = findCharOffset(cit.claim_in_report, lineAt(excerptExact.line) ?? '');
        result = {
          citationId: cit.id, matchedLine: excerptExact.line, confidence: 1.0, matchType: 'exact',
          charOffset: charPos?.offset, charLength: charPos?.length,
        };
      }
      if (!result) {
        const excerptNorm = tryNormalizedMatch(cit.claim_in_report, lines);
        if (excerptNorm) {
          const charPos = findCharOffset(cit.claim_in_report, lineAt(excerptNorm.line) ?? '');
          result = {
            citationId: cit.id, matchedLine: excerptNorm.line, confidence: 0.98, matchType: 'normalized',
            charOffset: charPos?.offset, charLength: charPos?.length,
          };
        }
      }
    }

    // Phase 1: Exact substring
    if (!result) {
      const exact = tryExactMatch(cit.claim, lines);
      if (exact) {
        const charPos = charPosFor(cit.claim, exact.line);
        result = {
          citationId: cit.id, matchedLine: exact.line, confidence: 1.0, matchType: 'exact',
          charOffset: charPos?.offset, charLength: charPos?.length,
        };
      }
    }

    // Phase 2: Normalized (markdown-stripped)
    if (!result) {
      const norm = tryNormalizedMatch(cit.claim, lines);
      if (norm) {
        const charPos = charPosFor(cit.claim, norm.line);
        result = {
          citationId: cit.id, matchedLine: norm.line, confidence: 0.95, matchType: 'normalized',
          charOffset: charPos?.offset, charLength: charPos?.length,
        };
      }
    }

    // Phase 3: Weighted scoring (always run, store result for potential fallback)
    // Clamp report_line to valid range (LLM estimates can be off)
    const clampedLine = Math.max(1, Math.min(cit.report_line, lines.length));
    const scored = tryScoredMatch(cit.claim, clampedLine, lines, lineWindow);
    if (!result || result.confidence < threshold) {
      if (scored.line > 0 && scored.score >= threshold && (!result || scored.score > result.confidence)) {
        const charPos = charPosFor(cit.claim, scored.line);
        result = {
          citationId: cit.id, matchedLine: scored.line,
          confidence: scored.score, matchType: 'scored', debugScores: scored.debug,
          charOffset: charPos?.offset, charLength: charPos?.length,
        };
      }
    }

    // Phase 4: Compound — always try for compound claims (may beat earlier phases)
    if (isCompound(cit.claim)) {
      const compound = tryCompoundMatch(cit.claim, clampedLine, lines, lineWindow, threshold);
      if (compound && compound.line > 0 && compound.score >= threshold && (!result || compound.score > result.confidence)) {
        const charPos = charPosFor(cit.claim, compound.line);
        result = {
          citationId: cit.id, matchedLine: compound.line,
          confidence: compound.score, matchType: 'compound', debugScores: compound.debug,
          charOffset: charPos?.offset, charLength: charPos?.length,
          lineSpan: compound.lineSpan,
        };
      }
    }

    // Fallback: use best scored even if below threshold (always produce a result)
    if (!result) {
      const charPos = scored.line > 0 ? charPosFor(cit.claim, scored.line) : undefined;
      result = {
        citationId: cit.id, matchedLine: Math.max(scored.line, 1),
        confidence: scored.score, matchType: 'scored', debugScores: scored.debug,
        charOffset: charPos?.offset, charLength: charPos?.length,
      };
    }

    results.push(result);
  }

  // Compute stats
  const stats: MatchStats = {
    total: citations.length,
    matched: results.filter(r => r.confidence >= threshold).length,
    unmatched: results.filter(r => r.confidence < threshold).length,
    byVerdict: {},
    byMatchType: {},
  };

  for (let i = 0; i < citations.length; i++) {
    const v = citations[i].verdict;
    if (!stats.byVerdict[v]) stats.byVerdict[v] = { count: 0, avgConfidence: 0 };
    stats.byVerdict[v].count++;
    stats.byVerdict[v].avgConfidence += results[i].confidence;

    const mt = results[i].matchType;
    stats.byMatchType[mt] = (stats.byMatchType[mt] || 0) + 1;
  }
  for (const v of Object.keys(stats.byVerdict)) {
    stats.byVerdict[v].avgConfidence /= stats.byVerdict[v].count;
  }

  return { results, stats };
}
