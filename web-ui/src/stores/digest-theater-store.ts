import { create } from "zustand";
import type { PipelineEvent } from "@/lib/types";
import type {
  ArticleState,
  ToolBubble,
  KBModuleState,
  FirnState,
  ConnectionState,
  ConnectionPhase,
  KBSectionType,
} from "@/lib/digest-theater-types";
import {
  normalizeSource,
  getToolDirection,
  classifyKBSection,
} from "@/lib/digest-theater-types";

// ─── Timeline metadata types (exported for component props) ─────────────────

/** Batch marker for the glacial timeline */
export interface BatchMarker {
  index: number;
  batchNum: number;
  articleCount: number;
}

/** Event dot type for timeline density visualization */
export type EventDotType = "digest" | "kb" | "tool";

// ─── Store Interface ────────────────────────────────────────────────────────

interface DigestTheaterStore {
  // Raw event data
  events: PipelineEvent[];
  isLoaded: boolean;

  // SSE loading state
  sseLoading: boolean;
  loadError: string | null;

  // Playback control (scalars only for React 19 safety)
  currentIndex: number;
  isPlaying: boolean;
  speed: number;

  // Derived state — recomputed on each processEvent / scrub
  // These are mutable arrays stored in Zustand; components must use
  // scalar selectors or useMemo patterns to avoid infinite re-renders.
  activeArticles: ArticleState[];
  activeBatchNum: number | null;
  firnState: FirnState;
  toolBubbles: ToolBubble[];
  kbModules: KBModuleState[];
  connections: ConnectionState[];

  // Timeline metadata (computed once in loadEvents, not per tick)
  batchMarkers: BatchMarker[];
  eventDotTypes: EventDotType[];
  batchMarkerCount: number;

  // Per-article reading tracking (scalar, React 19 safe)
  readingArticleSlug: string | null;

  // Counters for scalar selectors
  activeArticleCount: number;
  kbModuleCount: number;
  toolBubbleCount: number;
  connectionCount: number;
  totalEvents: number;

  // Time tracking
  elapsedMs: number;
  totalMs: number;
  currentReplayTs: number; // absolute timestamp of current replay position

  // Actions
  loadEvents: (events: PipelineEvent[]) => void;
  processEvent: () => void;
  tick: () => void;
  play: () => void;
  pause: () => void;
  scrub: (index: number) => void;
  setSpeed: (speed: number) => void;
  setSseLoading: (loading: boolean) => void;
  setLoadError: (error: string | null) => void;
  reset: () => void;
}

// ─── Constants ──────────────────────────────────────────────────────────────

/** Max tool bubbles visible at once */
const MAX_TOOL_BUBBLES = 4;
/** Tool bubble lifetime in ms */
const TOOL_BUBBLE_LIFETIME_MS = 3100; // 300ms appear + 2200ms hold + 600ms fade

/** Max visible connections (anti-spaghetti, R5 §7) */
const MAX_CONNECTIONS = 6;
/** Connection lifecycle thresholds in ms */
const CONN_BIRTH_END = 600;
const CONN_ACTIVE_END = 2100;   // birth + active
const CONN_LINGER_END = 2900;   // birth + active + linger
const CONN_PRUNE_AGE = 4900;    // fully faded, remove from array

// ─── Internal helpers ───────────────────────────────────────────────────────

let _bubbleIdCounter = 0;
let _connIdCounter = 0;

function nextBubbleId(): string {
  _bubbleIdCounter += 1;
  return `tb_${_bubbleIdCounter}`;
}

function nextConnId(): string {
  _connIdCounter += 1;
  return `conn_${_connIdCounter}`;
}

/** Determine connection phase from age in ms */
function connPhaseFromAge(age: number): ConnectionPhase {
  if (age < CONN_BIRTH_END) return "birth";
  if (age < CONN_ACTIVE_END) return "active";
  if (age < CONN_LINGER_END) return "linger";
  return "fade";
}

/**
 * Derive all state from events[0..currentIndex].
 * This is the core state machine — called on each tick, scrub, or bulk load.
 */
function deriveState(events: PipelineEvent[], upToIndex: number) {
  const articles: ArticleState[] = [];
  const toolBubbles: ToolBubble[] = [];
  const rawConnections: ConnectionState[] = [];
  let activeBatchNum: number | null = null;
  let firnState: FirnState = "idle";

  // Track state for incremental building
  const kbModuleMap = new Map<string, KBModuleState>();
  let lastEventType = "";
  let sessionEnded = false;
  // Track active reading connection per batch (only 1 at a time)
  let activeReadingConnId: string | null = null;
  // Track which article is currently being read
  let currentReadingSlug: string | null = null;
  // Track active writing connection (reused across consecutive KB mutations
  // to prevent rapid-fire connections from "jumping" between modules)
  let activeWritingConnId: string | null = null;

  for (let i = 0; i <= upToIndex && i < events.length; i++) {
    const evt = events[i];
    const eventName = evt.event;
    const data = evt.data ?? {};

    // ── Session lifecycle ────────────────────────────────────────────
    if (eventName === "digest.session_end") {
      sessionEnded = true;
      firnState = "complete";
      const eventTs = new Date(evt.ts).getTime();
      // End active connections so they fade out
      for (const connId of [activeReadingConnId, activeWritingConnId]) {
        if (connId) {
          const conn = rawConnections.find((c) => c.id === connId);
          if (conn && !conn.endedAt) conn.endedAt = eventTs;
        }
      }
      activeReadingConnId = null;
      activeWritingConnId = null;
      continue;
    }

    if (eventName === "digest.session_start") {
      firnState = "idle";
      continue;
    }

    // ── Batch start: create articles from items[] ────────────────────
    if (eventName === "digest.batch_start") {
      const batchNum = (data.batch_num as number) ?? 0;
      activeBatchNum = batchNum;
      firnState = "reading";
      const eventTs = new Date(evt.ts).getTime();

      // Extract items array (enriched batch_start events)
      const items = (data.items as Array<Record<string, unknown>>) ?? [];
      const slugs = (data.item_slugs as string[]) ?? [];

      let firstSlug = "";
      if (items.length > 0) {
        for (const item of items) {
          const slug = (item.slug as string) ?? "";
          if (!firstSlug) firstSlug = slug;
          articles.push({
            slug,
            title: (item.title as string) ?? slug,
            title_en: (item.title_en as string) ?? "",
            source: normalizeSource(item.source as string | undefined),
            published_date: (item.published_date as string) ?? "",
            char_count: (item.char_count as number) ?? 0,
            batchNum,
            state: "active-batch",
          });
        }
      } else {
        // Fallback: only slugs available (older events)
        for (const slug of slugs) {
          if (!firstSlug) firstSlug = slug;
          articles.push({
            slug,
            title: slug,
            title_en: "",
            source: "generic",
            published_date: "",
            char_count: 0,
            batchNum,
            state: "active-batch",
          });
        }
      }

      // Reading connection is deferred to the first read_inbox_item call
      // (creating it here causes a visual glitch: the connection renders
      // before the article card DOM elements exist, falling back to
      // proportional coordinates that point at empty space)
      continue;
    }

    // ── Batch complete: mark articles as processed ───────────────────
    if (eventName === "digest.batch_complete") {
      const batchNum = (data.batch_num as number) ?? 0;
      const eventTs = new Date(evt.ts).getTime();
      // Mark all articles from this batch as processed
      for (const art of articles) {
        if (art.batchNum === batchNum) {
          art.state = "processed";
        }
      }
      // End the reading connection for this batch
      if (activeReadingConnId) {
        const readConn = rawConnections.find((c) => c.id === activeReadingConnId);
        if (readConn && !readConn.endedAt) {
          readConn.endedAt = eventTs;
        }
        activeReadingConnId = null;
      }
      // End the writing connection for this batch
      if (activeWritingConnId) {
        const writeConn = rawConnections.find((c) => c.id === activeWritingConnId);
        if (writeConn && !writeConn.endedAt) {
          writeConn.endedAt = eventTs;
        }
        activeWritingConnId = null;
      }
      continue;
    }

    // ── Tool calls → tool bubbles + Firn state ──────────────────────
    if (eventName === "agent.tool_call.start") {
      const toolName = (data.tool_name as string) ?? "";
      const direction = getToolDirection(toolName);

      toolBubbles.push({
        id: nextBubbleId(),
        tool_name: toolName,
        direction,
        createdAt: new Date(evt.ts).getTime(),
      });

      // Per-article reading state: track which article is currently being read
      if (toolName === "read_inbox_item") {
        const input = (data.input as string) ?? "";
        const itemIdMatch = input.match(/item_id['":\s]+['"]?([^'"}\s]+)/);
        if (itemIdMatch) {
          const itemId = itemIdMatch[1];
          // Reset previous reading article to active-batch
          for (const art of articles) {
            if (art.state === "reading") {
              art.state = "active-batch";
            }
          }
          // Set the matched article to reading
          for (const art of articles) {
            if (art.slug === itemId && art.batchNum === activeBatchNum) {
              art.state = "reading";
              currentReadingSlug = art.slug;
              break;
            }
          }
          // Create or transition the reading connection
          if (currentReadingSlug) {
            if (activeReadingConnId) {
              const readConn = rawConnections.find((c) => c.id === activeReadingConnId);
              if (readConn && readConn.sourceSlug !== currentReadingSlug) {
                // Source changed: end old connection (linger→fade), create new
                readConn.endedAt = new Date(evt.ts).getTime();
                const connId = nextConnId();
                activeReadingConnId = connId;
                rawConnections.push({
                  id: connId,
                  type: "reading",
                  phase: "birth",
                  sourceSlug: currentReadingSlug,
                  targetSlug: "firn",
                  createdAt: new Date(evt.ts).getTime(),
                });
              }
              // Same source: no change needed
            } else {
              // Create reading connection on first read_inbox_item
              // (deferred from batch_start so article DOM elements exist)
              const connId = nextConnId();
              activeReadingConnId = connId;
              rawConnections.push({
                id: connId,
                type: "reading",
                phase: "birth",
                sourceSlug: currentReadingSlug,
                targetSlug: "firn",
                createdAt: new Date(evt.ts).getTime(),
              });
            }
          }
        }
      }

      // Determine Firn state from tool type
      if (toolName.includes("read") || toolName === "read_inbox_item") {
        firnState = "reading";
      } else if (
        toolName.includes("write") ||
        toolName.includes("edit") ||
        toolName.includes("core_mind")
      ) {
        firnState = "writing";
      } else {
        firnState = "thinking";
      }
      lastEventType = "tool_start";
      continue;
    }

    if (eventName === "agent.tool_call.end") {
      lastEventType = "tool_end";
      // Firn returns to thinking between tool calls
      if (!sessionEnded) {
        firnState = "thinking";
      }
      continue;
    }

    // ── KB mutations → kbModules ────────────────────────────────────
    if (eventName === "kb.write" || eventName === "kb.edit" || eventName === "kb.core_mind_updated") {
      const section = classifyKBSection(eventName, data.section as string | undefined);
      const slug = (data.slug as string) ?? (section === "core_mind" ? "core_mind" : "unknown");
      const moduleId = `${section}:${slug}`;
      const eventTs = new Date(evt.ts).getTime();

      const existing = kbModuleMap.get(moduleId);
      if (existing) {
        // Coalescence: update existing module
        existing.lastEditAt = eventTs;
        existing.diffs.push(buildDiffEntry(evt));
        // Update content length info
        if (eventName === "kb.edit") {
          existing.content = `${data.new_len ?? 0} chars`;
        } else {
          existing.content = `${data.size ?? 0} chars`;
        }
      } else {
        // New module
        const isNew = eventName === "kb.write" && (data.is_new as boolean | undefined) !== false;
        const newModule: KBModuleState = {
          id: moduleId,
          section,
          slug,
          content: eventName === "kb.edit"
            ? `${data.new_len ?? 0} chars`
            : `${data.size ?? 0} chars`,
          diffs: [buildDiffEntry(evt)],
          fullContent: isNew ? ((data.content as string) ?? undefined) : undefined,
          is_new: isNew,
          createdAt: eventTs,
          lastEditAt: eventTs,
        };
        kbModuleMap.set(moduleId, newModule);
      }

      // Create, refresh, or transition writing connection from Firn to KB module.
      const connType = section === "core_mind" ? "core_mind" as const : "writing" as const;
      const existingWriteConn = activeWritingConnId
        ? rawConnections.find((c) => c.id === activeWritingConnId)
        : null;
      if (existingWriteConn && !existingWriteConn.endedAt) {
        if (existingWriteConn.targetSlug === moduleId) {
          // Same target: refresh activity (keeps connection active, no visual change)
          existingWriteConn.lastActivityAt = eventTs;
        } else {
          // Different target: end old (linger→fade), create new (birth→active)
          existingWriteConn.endedAt = eventTs;
          const connId = nextConnId();
          activeWritingConnId = connId;
          rawConnections.push({
            id: connId,
            type: connType,
            phase: "birth",
            sourceSlug: "firn",
            targetSlug: moduleId,
            createdAt: eventTs,
            lastActivityAt: eventTs,
          });
        }
      } else {
        // Create new writing connection
        const connId = nextConnId();
        activeWritingConnId = connId;
        rawConnections.push({
          id: connId,
          type: connType,
          phase: "birth",
          sourceSlug: "firn",
          targetSlug: moduleId,
          createdAt: eventTs,
          lastActivityAt: eventTs,
        });
      }

      firnState = "writing";
      lastEventType = "kb_mutation";
      continue;
    }
  }

  // Collect KB modules in thematic order: core_mind > themes > events > stocks > sectors
  const sectionOrder: KBSectionType[] = ["core_mind", "themes", "events", "stocks", "sectors"];
  const sortedModules: KBModuleState[] = [];
  for (const section of sectionOrder) {
    for (const mod of kbModuleMap.values()) {
      if (mod.section === section) {
        sortedModules.push(mod);
      }
    }
  }

  // Prune old tool bubbles (keep only recent ones up to MAX_TOOL_BUBBLES)
  // When replaying, we use the last event's timestamp as "now"
  const refTime = new Date(events[Math.min(upToIndex, events.length - 1)].ts).getTime();
  const recentBubbles = toolBubbles
    .filter((b) => refTime - b.createdAt < TOOL_BUBBLE_LIFETIME_MS)
    .slice(-MAX_TOOL_BUBBLES);

  // ── Connection lifecycle: compute phases, prune fully faded ──────
  const connections: ConnectionState[] = [];
  for (const c of rawConnections) {
    if (c.type === "reading" && !c.endedAt) {
      // Active reading connection: stays active until batch completes
      const age = refTime - c.createdAt;
      if (age < CONN_BIRTH_END) {
        c.phase = "birth";
      } else {
        c.phase = "active";
      }
    } else if (c.endedAt) {
      // Connection has ended — compute phase from endedAt
      const ageFromEnd = refTime - c.endedAt;
      if (ageFromEnd < 800) {
        c.phase = "linger";
      } else if (ageFromEnd < 2800) {
        c.phase = "fade";
      } else {
        continue; // fully faded, prune
      }
    } else {
      // KB write connections: birth from createdAt, active/fade from lastActivityAt
      const age = refTime - c.createdAt;
      const sinceActivity = refTime - (c.lastActivityAt ?? c.createdAt);
      if (age < CONN_BIRTH_END) {
        c.phase = "birth";
      } else if (sinceActivity < 1500) {
        c.phase = "active";
      } else if (sinceActivity < 2300) {
        c.phase = "linger";
      } else if (sinceActivity < 4300) {
        c.phase = "fade";
      } else {
        continue; // prune
      }
    }
    connections.push(c);
  }

  // Anti-spaghetti: max 6 connections, core_mind gets priority
  let finalConnections: ConnectionState[];
  if (connections.length > MAX_CONNECTIONS) {
    const coreMind = connections.filter((c) => c.type === "core_mind");
    const others = connections.filter((c) => c.type !== "core_mind");
    const remaining = MAX_CONNECTIONS - coreMind.length;
    const keptOthers = others.slice(-Math.max(0, remaining));
    finalConnections = [...coreMind, ...keptOthers];
  } else {
    finalConnections = connections;
  }

  // Ensure only 1 active reading connection (keep most recent, allow fading/lingering ones)
  let foundActiveReading = false;
  for (let ci = finalConnections.length - 1; ci >= 0; ci--) {
    const conn = finalConnections[ci];
    if (conn.type === "reading" && conn.phase !== "fade" && conn.phase !== "linger") {
      if (foundActiveReading) {
        finalConnections.splice(ci, 1);
      } else {
        foundActiveReading = true;
      }
    }
  }

  // If session ended and no recent activity, set firnState to complete
  if (sessionEnded) {
    firnState = "complete";
  } else if (lastEventType === "" && articles.length === 0) {
    firnState = "idle";
  }

  // Compute time tracking
  let elapsedMs = 0;
  let totalMs = 0;
  let currentReplayTs = 0;
  if (events.length >= 1) {
    currentReplayTs = upToIndex < events.length
      ? new Date(events[upToIndex].ts).getTime()
      : new Date(events[events.length - 1].ts).getTime();
  }
  if (events.length >= 2) {
    const firstTs = new Date(events[0].ts).getTime();
    const lastTs = new Date(events[events.length - 1].ts).getTime();
    elapsedMs = Math.max(0, currentReplayTs - firstTs);
    totalMs = Math.max(0, lastTs - firstTs);
  }

  return {
    activeArticles: articles,
    activeBatchNum,
    firnState,
    toolBubbles: recentBubbles,
    kbModules: sortedModules,
    connections: finalConnections,
    readingArticleSlug: currentReadingSlug,
    activeArticleCount: articles.length,
    kbModuleCount: sortedModules.length,
    toolBubbleCount: recentBubbles.length,
    connectionCount: finalConnections.length,
    elapsedMs,
    totalMs,
    currentReplayTs,
  };
}

/**
 * Extract the actual unified diff string from a KB event.
 * Returns the raw diff from evt.data.diff, or an empty string if unavailable.
 */
function buildDiffEntry(evt: PipelineEvent): string {
  const data = evt.data ?? {};
  const diff = (data.diff as string) ?? "";
  return diff;
}

// ─── Playback delay computation ─────────────────────────────────────────────

/**
 * Compute playback delay for a pair of consecutive events, scaled by speed.
 * Returns delay in ms, clamped to [50, 2000].
 */
function computeDelay(
  current: PipelineEvent,
  next: PipelineEvent | undefined,
  speed: number,
): number {
  const DEFAULT_DELAY = 500;
  if (!next) return DEFAULT_DELAY;
  const gap = new Date(next.ts).getTime() - new Date(current.ts).getTime();
  if (isNaN(gap) || gap <= 0) return Math.max(50, Math.min(DEFAULT_DELAY / speed, 2000));
  return Math.max(50, Math.min(gap / speed, 2000));
}

// ─── Store ──────────────────────────────────────────────────────────────────

export const useDigestTheaterStore = create<DigestTheaterStore>((set, get) => ({
  // Initial state
  events: [],
  isLoaded: false,
  sseLoading: false,
  loadError: null,
  currentIndex: 0,
  isPlaying: false,
  speed: 1,

  // Derived state (empty initial)
  activeArticles: [],
  activeBatchNum: null,
  firnState: "idle",
  toolBubbles: [],
  kbModules: [],
  connections: [],
  readingArticleSlug: null,

  // Timeline metadata (computed once in loadEvents)
  batchMarkers: [],
  eventDotTypes: [],
  batchMarkerCount: 0,

  // Scalar counters
  activeArticleCount: 0,
  kbModuleCount: 0,
  toolBubbleCount: 0,
  connectionCount: 0,
  totalEvents: 0,

  // Time
  elapsedMs: 0,
  totalMs: 0,
  currentReplayTs: 0,

  loadEvents(newEvents: PipelineEvent[]) {
    // Reset counters on new session
    _bubbleIdCounter = 0;
    _connIdCounter = 0;

    if (newEvents.length === 0) {
      set({
        events: [],
        isLoaded: true,
        currentIndex: 0,
        isPlaying: false,
        totalEvents: 0,
        activeArticles: [],
        activeBatchNum: null,
        firnState: "idle",
        toolBubbles: [],
        kbModules: [],
        connections: [],
        readingArticleSlug: null,
        batchMarkers: [],
        eventDotTypes: [],
        batchMarkerCount: 0,
        activeArticleCount: 0,
        kbModuleCount: 0,
        toolBubbleCount: 0,
        connectionCount: 0,
        elapsedMs: 0,
        totalMs: 0,
        currentReplayTs: 0,
      });
      return;
    }

    // Pre-compute timeline metadata (computed once, not per tick)
    const batchMarkers: BatchMarker[] = [];
    const eventDotTypes: EventDotType[] = [];
    for (let i = 0; i < newEvents.length; i++) {
      const evt = newEvents[i];
      const name = evt.event;
      if (name === "digest.batch_start") {
        const evtData = evt.data ?? {};
        const items = (evtData.items as Array<Record<string, unknown>>) ?? [];
        const slugs = (evtData.item_slugs as string[]) ?? [];
        batchMarkers.push({
          index: i,
          batchNum: (evtData.batch_num as number) ?? 0,
          articleCount: items.length > 0 ? items.length : slugs.length,
        });
        eventDotTypes.push("digest");
      } else if (name.startsWith("kb.")) {
        eventDotTypes.push("kb");
      } else if (name.startsWith("digest.")) {
        eventDotTypes.push("digest");
      } else {
        eventDotTypes.push("tool");
      }
    }

    // Derive state at index 0 (first event only)
    const derived = deriveState(newEvents, 0);

    set({
      events: newEvents,
      isLoaded: true,
      currentIndex: 0,
      totalEvents: newEvents.length,
      batchMarkers,
      eventDotTypes,
      batchMarkerCount: batchMarkers.length,
      ...derived,
    });
  },

  processEvent() {
    // In this store design, processEvent is not used for incremental SSE.
    // Events are bulk-loaded via loadEvents(), and playback advances via tick().
    // This method exists to match the pipeline-store pattern but is a no-op.
    // The state machine runs in deriveState() which replays events[0..currentIndex].
  },

  tick() {
    const { events, currentIndex, isPlaying } = get();
    if (!isPlaying || currentIndex >= events.length - 1) {
      if (currentIndex >= events.length - 1 && events.length > 0) {
        set({ isPlaying: false });
      }
      return;
    }

    const newIndex = currentIndex + 1;
    _bubbleIdCounter = 0;
    _connIdCounter = 0;
    const derived = deriveState(events, newIndex);

    set({
      currentIndex: newIndex,
      ...derived,
    });
  },

  play() {
    const { currentIndex, events } = get();
    if (currentIndex >= events.length - 1 && events.length > 0) {
      // Restart from beginning
      _bubbleIdCounter = 0;
      _connIdCounter = 0;
      const derived = deriveState(events, 0);
      set({
        currentIndex: 0,
        isPlaying: true,
        ...derived,
      });
    } else {
      set({ isPlaying: true });
    }
  },

  pause() {
    set({ isPlaying: false });
  },

  scrub(index: number) {
    const { events } = get();
    const clamped = Math.max(0, Math.min(index, events.length - 1));

    _bubbleIdCounter = 0; // Reset for deterministic replay
    _connIdCounter = 0;
    const derived = deriveState(events, clamped);

    set({
      isPlaying: false,
      currentIndex: clamped,
      ...derived,
    });
  },

  setSpeed(speed: number) {
    set({ speed });
  },

  setSseLoading(loading: boolean) {
    set({ sseLoading: loading });
  },

  setLoadError(error: string | null) {
    set({ loadError: error });
  },

  reset() {
    _bubbleIdCounter = 0;
    _connIdCounter = 0;
    set({
      events: [],
      isLoaded: false,
      sseLoading: false,
      loadError: null,
      currentIndex: 0,
      isPlaying: false,
      speed: 1,
      activeArticles: [],
      activeBatchNum: null,
      firnState: "idle",
      toolBubbles: [],
      kbModules: [],
      connections: [],
      readingArticleSlug: null,
      batchMarkers: [],
      eventDotTypes: [],
      batchMarkerCount: 0,
      activeArticleCount: 0,
      kbModuleCount: 0,
      toolBubbleCount: 0,
      connectionCount: 0,
      totalEvents: 0,
      elapsedMs: 0,
      totalMs: 0,
      currentReplayTs: 0,
    });
  },
}));

// ─── Playback delay export (used by the theater component) ──────────────────

export { computeDelay as computeDigestPlaybackDelay };
