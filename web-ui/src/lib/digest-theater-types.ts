// ─── Digest Theater Types ───────────────────────────────────────────────────
// Type definitions for the Digest Theater (R5 visual spec).
// Used by digest-theater-store and all theater zone components.

/** Normalized source type for article display */
export type ArticleSource = "wechat" | "bilibili" | "generic";

/** Visual state of an article card in the reading stack */
export type ArticleVisualState = "idle" | "active-batch" | "reading" | "processed";

/** Article state for the reading stack (Zone A) */
export interface ArticleState {
  slug: string;
  title: string;
  title_en: string;
  source: ArticleSource;
  published_date: string;
  char_count: number;
  batchNum: number;
  state: ArticleVisualState;
}

/** Directional semantics for tool call bubbles around Firn */
export type ToolBubbleDirection = "left" | "right" | "up";

/** A tool call bubble displayed near Firn's presence (Zone B) */
export interface ToolBubble {
  id: string;
  tool_name: string;
  direction: ToolBubbleDirection;
  createdAt: number;
}

/** KB section types matching the backend knowledge base structure */
export type KBSectionType = "core_mind" | "themes" | "events" | "stocks" | "sectors";

/** State of a Knowledge Base module card (Zone C) */
export interface KBModuleState {
  id: string;
  section: KBSectionType;
  slug: string;
  content: string;
  /** Actual unified diff strings from backend (evt.data.diff) */
  diffs: string[];
  /** Full file content for new files (kb.write with is_new=true) */
  fullContent?: string;
  is_new: boolean;
  createdAt: number;
  lastEditAt: number;
}

/** Firn's state drives visual appearance of the central presence */
export type FirnState = "idle" | "reading" | "thinking" | "writing" | "complete";

/** Connection type determines color and particle behavior */
export type ConnectionType = "reading" | "writing" | "core_mind";

/** Connection lifecycle phase (R5 §7) */
export type ConnectionPhase = "birth" | "active" | "linger" | "fade";

/** A visual connection line between zones */
export interface ConnectionState {
  id: string;
  type: ConnectionType;
  phase: ConnectionPhase;
  sourceSlug: string;  // article slug or "firn"
  targetSlug: string;  // "firn" or kb module id
  createdAt: number;      // replay timestamp (ms) — first creation, never reset
  lastActivityAt?: number; // last KB write/edit refresh (ms) — drives active/fade timing
  endedAt?: number;       // when connection started fading
}

// ─── Source Normalization ────────────────────────────────────────────────────

/**
 * Normalize backend source string to display category.
 * Backend sends e.g. "wechat_AccountName", "bilibili_CreatorName" — we extract the prefix.
 */
export function normalizeSource(raw: string | undefined | null): ArticleSource {
  if (!raw) return "generic";
  const lower = raw.toLowerCase();
  if (lower.startsWith("wechat")) return "wechat";
  if (lower.startsWith("bilibili")) return "bilibili";
  return "generic";
}

// ─── Section Color Map ──────────────────────────────────────────────────────

export const SECTION_COLORS: Record<KBSectionType, string> = {
  core_mind: "#8B5CF6",
  themes: "#06B6D4",
  events: "#F59E0B",
  stocks: "#3FB950",
  sectors: "#5BA3F5",
};

// ─── Source Dot Colors ──────────────────────────────────────────────────────

export const SOURCE_DOT_COLORS: Record<ArticleSource, string> = {
  wechat: "#07C160",
  bilibili: "#00A1D6",
  generic: "rgba(255,255,255,0.25)",
};

// ─── Tool Direction Mapping ─────────────────────────────────────────────────

/** Determine directional semantics for a tool call bubble */
export function getToolDirection(toolName: string): ToolBubbleDirection {
  if (
    toolName.includes("read") ||
    toolName === "read_inbox_item"
  ) {
    return "left"; // read = toward articles (left)
  }
  if (
    toolName.includes("write") ||
    toolName.includes("edit") ||
    toolName.includes("archive") ||
    toolName.includes("log")
  ) {
    return "right"; // write = toward KB (right)
  }
  if (toolName.includes("search")) {
    return "up"; // search = upward
  }
  return "right"; // default to right
}

// ─── KB Section Classification ──────────────────────────────────────────────

/**
 * Classify a KB event into its section type.
 * Maps backend section strings + special events to our KBSectionType.
 */
export function classifyKBSection(
  eventName: string,
  section?: string,
): KBSectionType {
  if (eventName === "kb.core_mind_updated") return "core_mind";
  if (!section) return "themes"; // fallback
  if (section === "stock_theses") return "stocks";
  if (section === "themes" || section === "events" || section === "stocks" || section === "sectors") {
    return section as KBSectionType;
  }
  // Map any unknown section to the closest match
  if (section.includes("stock")) return "stocks";
  if (section.includes("theme")) return "themes";
  if (section.includes("event")) return "events";
  if (section.includes("sector")) return "sectors";
  if (section.includes("core_mind")) return "core_mind";
  return "themes"; // final fallback
}
