// ─── Auth ──────────────────────────────────────────────────────────────────

export interface AuthUser {
  role: "admin" | "visitor";
  exp: number;
}

// ─── System ────────────────────────────────────────────────────────────────

export interface SystemStatus {
  day_n: number;
  total_articles: number;
  total_themes: number;
  total_stocks: number;
  total_events: number;
  core_mind_chars: number;
  library_unread: number;
  library_read: number;
  last_digest?: string | null;
  last_analysis?: string | null;
  llm_provider?: string;
}

// ─── Analysis ──────────────────────────────────────────────────────────────

export interface AnalysisMeta {
  exec_id: string;
  ticker: string | null;
  status: "running" | "complete" | "failed";
  started_at: string | null;
  completed_at: string | null;
  has_audit: boolean;
}

export interface AnalysisDetail {
  exec_id: string;
  ticker: string | null;
  status: "running" | "complete" | "failed";
  started_at: string | null;
  completed_at: string | null;
  report: string | null;
  report_length: number | null;
  agent_timings: Record<string, number>;
  token_usage: Record<string, number>;
  has_audit: boolean;
}

// ─── Audit ─────────────────────────────────────────────────────────────────

export interface AuditCitation {
  id: number;
  claim: string;
  claim_in_report?: string;    // EXACT text from report for positioning
  verdict: string;
  source: {
    agent?: string;
    tool?: string;
    index?: number;
    raw_value?: unknown;
  };
  specialist?: {
    agent?: string;
    excerpt?: string;
  };
  evidence?: {
    source_grep?: string;
    specialist_grep?: string;
  };
  r1_match?: {
    agent?: string;
    claim_id?: number;
    verdict?: string;
  };
}

export interface AuditResult {
  total_claims: number;
  verdicts: Record<string, number>;
  citations: AuditCitation[];
  audit_report: string;
  duration_seconds?: number;
}

// ─── Digest ────────────────────────────────────────────────────────────────

export interface DigestMeta {
  exec_id: string;
  status: "running" | "complete" | "failed" | "unknown";
  started_at: string | null;
  completed_at: string | null;
  articles_processed: number;
  batches_total: number | null;
  themes_added: number;
  themes_updated: number;
  stocks_added: number;
  stocks_updated: number;
  events_added: number;
  core_mind_updated: boolean;
  total_kb_chars_written: number;
  duration_s: number | null;
}

export interface DigestDetail {
  exec_id: string;
  status: "running" | "complete" | "failed" | "unknown";
  started_at: string | null;
  completed_at: string | null;
  articles_processed: number;
  batches_total: number | null;
  batches_complete: number;
  kb_mutations: { type: string; path: string }[];
  themes_added: number;
  themes_updated: number;
  stocks_added: number;
  stocks_updated: number;
  events_added: number;
  core_mind_updated: boolean;
  total_kb_chars_written: number;
  duration_s: number | null;
}

// ─── Knowledge Base ────────────────────────────────────────────────────────

export interface KBTheme {
  slug: string;
  preview: string;
}

export interface KBStock {
  ticker: string;
  files: string[];
  file_chars: Record<string, number>;
  total_chars: number;
  connected_themes: string[];
}

export interface KBEvent {
  slug: string;
  preview: string;
}

export interface KBEventDetail {
  slug: string;
  content: string;
}

// ─── Market ────────────────────────────────────────────────────────────────

export interface MarketTickerData {
  price: number;
  currency: string;
  change_1d: number;
  change_1w: number;
  change_1m: number;
  week52_pos: number;
  short_name: string;
}

export interface MarketSnapshotResponse {
  tickers: Record<string, MarketTickerData>;
  categories: Record<string, string[]>;
}

// ─── Pipeline Events (SSE) ─────────────────────────────────────────────────

export interface PipelineEvent {
  event: string;
  ts: string;
  stage?: string;
  sid?: string;
  data?: Record<string, unknown>;
}

// ─── KB Graph ─────────────────────────────────────────────────────────────

export interface KBGraphNode {
  id: string;
  type: "core" | "theme" | "stock" | "event";
  label: string;
  chars: number;
}

export interface KBGraphEdge {
  source: string;
  target: string;
}

export interface KBGraphData {
  nodes: KBGraphNode[];
  edges: KBGraphEdge[];
}

// ─── Core Mind Snapshots ──────────────────────────────────────────────────

export interface CoreMindSnapshot {
  id: string;
  date: string;
  exec_id_short: string;
  char_count: number;
}

// ─── Evolution Timeline ───────────────────────────────────────────────────

export interface EvolutionDayData {
  date: string;
  articles_ingested: number;
  kb_writes: number;
  analyses: number;
  digests: number;
}

export interface EvolutionCumulativeData {
  date: string;
  articles: number;
  kb_writes: number;
  analyses: number;
}

export interface EvolutionData {
  daily: EvolutionDayData[];
  cumulative: EvolutionCumulativeData[];
}

// ─── KB Detail Types ──────────────────────────────────────────────────────

export interface KBThemeDetail {
  slug: string;
  content: string;
}

export interface KBStockDetail {
  ticker: string;
  files: Record<string, string>;
}

// ─── Maturation (Phase F: Ice Core Navigator) ────────────────────────────────

export interface MaturationItem {
  item_id: string;
  item_type: 'theme' | 'stock' | 'event' | 'core_mind';
  write_count: number;
  tier: 'snow' | 'firn' | 'ice';
  last_updated: string;
}

export interface MaturationResponse {
  items: MaturationItem[];
  total_sessions: number;
}

export interface PulsePoint {
  date: string;
  char_count: number;
  snapshot_id: string;
}

export interface PulseResponse {
  points: PulsePoint[];
}

// ─── Config ───────────────────────────────────────────────────────────────────

export interface SourceInfo {
  name: string;
  tier: number | null;
  bias: string | null;
  last_updated: string | null;
  new_count: number;
}

export interface WatchlistCategory {
  label: string;
  tickers: string[];
}

export type WatchlistData = Record<string, WatchlistCategory>;
