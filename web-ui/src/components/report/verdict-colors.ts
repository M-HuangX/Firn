// Verdict color system — single source of truth for all verdict-related styling
// 7-verdict taxonomy (D43): verified, supported, specialist-judgment, computed, kb-sourced, web-sourced, unverified

export type Verdict =
  | "verified"
  | "supported"
  | "specialist-judgment"
  | "computed"
  | "kb-sourced"
  | "web-sourced"
  | "unverified";

export interface VerdictStyle {
  label: string;
  shortLabel: string;
  /** User-facing tooltip description */
  description: string;
  /** Tailwind text color class */
  text: string;
  /** Tailwind border color class */
  border: string;
  /** Tailwind bg class for badges */
  bg: string;
  /** rgba for persistent text highlight (5% opacity) */
  highlightBg: string;
  /** rgba for hover/bloom highlight (12% opacity) */
  highlightHover: string;
  /** Segmented bar color */
  barColor: string;
}

export const VERDICT_STYLES: Record<Verdict, VerdictStyle> = {
  "verified": {
    label: "Verified",
    shortLabel: "Verified",
    description: "Full audit trail confirmed: raw data → domain analysis → report, each link independently verified",
    text: "text-green-300",
    border: "border-green-400",
    bg: "bg-green-400/15",
    highlightBg: "rgba(74,222,128,0.05)",
    highlightHover: "rgba(74,222,128,0.12)",
    barColor: "#4ADE80",
  },
  "supported": {
    label: "Supported",
    shortLabel: "Supported",
    description: "Supporting evidence found, but full verification chain not confirmed",
    text: "text-teal-400",
    border: "border-teal-500",
    bg: "bg-teal-500/15",
    highlightBg: "rgba(45,212,191,0.05)",
    highlightHover: "rgba(45,212,191,0.12)",
    barColor: "#2DD4BF",
  },
  "specialist-judgment": {
    label: "Specialist Judgment",
    shortLabel: "Judgment",
    description: "Specialist's own analysis, assessment, or computation — not directly from raw data (e.g. scenario probabilities, scores, valuation estimates)",
    text: "text-sky-400",
    border: "border-sky-500",
    bg: "bg-sky-500/15",
    highlightBg: "rgba(56,189,248,0.05)",
    highlightHover: "rgba(56,189,248,0.12)",
    barColor: "#38BDF8",
  },
  "computed": {
    label: "Computed",
    shortLabel: "Computed",
    description: "Calculated or derived from verified data; computation performed by AI",
    text: "text-blue-400",
    border: "border-blue-500",
    bg: "bg-blue-500/15",
    highlightBg: "rgba(59,130,246,0.08)",
    highlightHover: "rgba(59,130,246,0.12)",
    barColor: "#3B82F6",
  },
  "kb-sourced": {
    label: "KB Sourced",
    shortLabel: "KB",
    description: "Sourced from knowledge base (research notes, industry analysis)",
    text: "text-violet-400",
    border: "border-violet-500",
    bg: "bg-violet-500/15",
    highlightBg: "rgba(139,92,246,0.05)",
    highlightHover: "rgba(139,92,246,0.12)",
    barColor: "#8B5CF6",
  },
  "web-sourced": {
    label: "Web Sourced",
    shortLabel: "Web",
    description: "Sourced from web search results",
    text: "text-amber-400",
    border: "border-amber-500",
    bg: "bg-amber-500/15",
    highlightBg: "rgba(245,158,11,0.05)",
    highlightHover: "rgba(245,158,11,0.12)",
    barColor: "#F59E0B",
  },
  "unverified": {
    label: "Unverified",
    shortLabel: "Unverified",
    description: "No supporting evidence found during audit; may still be accurate but treat with caution",
    text: "text-slate-400",
    border: "border-slate-500",
    bg: "bg-slate-500/15",
    highlightBg: "rgba(148,163,184,0.05)",
    highlightHover: "rgba(148,163,184,0.12)",
    barColor: "#94A3B8",
  },
};

// Backward compat: map old verdict names to new ones
const LEGACY_VERDICT_MAP: Record<string, Verdict> = {
  // v3 legacy
  "dual-verified": "verified",
  "cascade-verified": "verified",
  "source-verified": "supported",
  "tool-verified": "supported",
  "derived-from-verified": "supported",
  "computation-verified": "computed",
  "web-verified": "web-sourced",
  "llm-inferred": "unverified",
  // v4 R1 verdicts (internal, shouldn't appear in final citations but just in case)
  "found": "supported",
  "derived": "supported",
  "not-found": "unverified",
};

/** Get verdict style, with backward compat for old verdict names */
export function getVerdictStyle(verdict: string): VerdictStyle {
  const key = LEGACY_VERDICT_MAP[verdict] ?? verdict;
  return VERDICT_STYLES[key as Verdict] ?? VERDICT_STYLES["unverified"];
}

/** Normalize any verdict string (old or new) to the current Verdict type */
export function normalizeVerdict(verdict: string): Verdict {
  return (LEGACY_VERDICT_MAP[verdict] ?? verdict) as Verdict;
}

/** Order of verdicts from strongest to weakest (for summary bar) */
export const VERDICT_ORDER: Verdict[] = [
  "verified",
  "supported",
  "specialist-judgment",
  "computed",
  "kb-sourced",
  "web-sourced",
  "unverified",
];
