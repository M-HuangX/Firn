"use client";

import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { useDigestList } from "@/hooks/use-api";
import type { PipelineEvent, DigestMeta } from "@/lib/types";
import { API_BASE } from "@/lib/api-client";

const EXEC_ID_RE = /^[a-zA-Z0-9_-]+$/;

// ─── Pure Helpers (exported for tests) ───────────────────────────────────────

export interface ArticleEntry {
  slug: string;
  batchNum: number;
}

export function categorizeArticles(events: PipelineEvent[]): ArticleEntry[] {
  return events
    .filter((e) => e.event === "digest.batch_start")
    .flatMap((e) => {
      const slugs = (e.data?.item_slugs as string[]) ?? [];
      return slugs.map((slug) => ({
        slug,
        batchNum: (e.data?.batch_num as number) ?? 0,
      }));
    });
}

export function categorizeAgentActivity(events: PipelineEvent[]): PipelineEvent[] {
  return events.filter(
    (e) =>
      e.event.startsWith("agent.tool_call") ||
      e.event.startsWith("digest.batch") ||
      e.event === "digest.session_start" ||
      e.event === "digest.session_end"
  );
}

export function categorizeKBMutations(events: PipelineEvent[]): PipelineEvent[] {
  return events.filter((e) => e.event.startsWith("kb."));
}

/**
 * Compute playback delay for a pair of consecutive events, scaled by speed.
 * Returns delay in ms, clamped to [50, 2000].
 */
export function computePlaybackDelay(
  current: PipelineEvent,
  next: PipelineEvent | undefined,
  speed: number
): number {
  const DEFAULT_DELAY = 500;
  if (!next) return DEFAULT_DELAY;
  const gap = new Date(next.ts).getTime() - new Date(current.ts).getTime();
  if (isNaN(gap) || gap <= 0) return Math.max(50, Math.min(DEFAULT_DELAY / speed, 2000));
  return Math.max(50, Math.min(gap / speed, 2000));
}

/**
 * Format elapsed time from ms to "M:SS".
 */
export function formatElapsed(ms: number): string {
  if (!ms || ms < 0 || isNaN(ms)) return "0:00";
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function SessionSelector({
  digests,
  selectedId,
  onSelect,
}: {
  digests: DigestMeta[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="flex items-center gap-3">
      <label htmlFor="digest-select" className="text-sm font-medium text-text-primary whitespace-nowrap">
        Session:
      </label>
      <select
        id="digest-select"
        value={selectedId ?? ""}
        onChange={(e) => onSelect(e.target.value)}
        className="flex-1 max-w-md h-9 px-3 rounded-lg bg-surface border border-border text-text-primary text-sm outline-none focus:border-accent/50 cursor-pointer"
      >
        <option value="" disabled>
          Select a digest session...
        </option>
        {digests.map((d) => (
          <option key={d.exec_id} value={d.exec_id}>
            {d.exec_id.length > 16 ? d.exec_id.slice(0, 16) + "..." : d.exec_id}
            {" "}-- {d.started_at ? new Date(d.started_at).toLocaleDateString() : "unknown"}{" "}
            ({d.articles_processed} articles, {d.status})
          </option>
        ))}
      </select>
    </div>
  );
}

function ArticlePanel({ articles }: { articles: ArticleEntry[] }) {
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [articles.length]);

  return (
    <div className="flex flex-col h-full">
      <h3 className="text-sm font-medium text-text-primary px-3 py-2 border-b border-border flex-shrink-0">
        Article Stream
        <span className="ml-2 text-xs text-text-secondary font-normal">({articles.length})</span>
      </h3>
      <div ref={listRef} className="flex-1 overflow-y-auto scrollbar-thin p-2 space-y-1.5">
        {articles.length === 0 ? (
          <div className="text-xs text-text-secondary text-center py-4">
            Waiting for articles...
          </div>
        ) : (
          articles.map((article, i) => (
            <div
              key={`${article.slug}-${i}`}
              className="px-3 py-2 rounded-lg bg-background border border-border/50 text-xs animate-fadeIn"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-text-primary truncate font-mono" title={article.slug}>
                  {article.slug}
                </span>
                <span className="flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium bg-accent/15 text-accent">
                  B{article.batchNum}
                </span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function EventTypeBadge({ event }: { event: string }) {
  let color = "text-text-secondary bg-border/30";
  if (event === "digest.session_start" || event === "digest.session_end") {
    color = "text-interactive bg-interactive/15";
  } else if (event.startsWith("digest.batch")) {
    color = "text-accent bg-accent/15";
  } else if (event === "agent.tool_call.start") {
    color = "text-amber-400 bg-amber-400/15";
  } else if (event === "agent.tool_call.end") {
    color = "text-positive bg-positive/15";
  }
  const shortName = event
    .replace("digest.", "")
    .replace("agent.", "")
    .replace("_", " ");

  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium whitespace-nowrap ${color}`}>
      {shortName}
    </span>
  );
}

function AgentActivityPanel({ events }: { events: PipelineEvent[] }) {
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [events.length]);

  return (
    <div className="flex flex-col h-full">
      <h3 className="text-sm font-medium text-text-primary px-3 py-2 border-b border-border flex-shrink-0">
        Agent Activity
        <span className="ml-2 text-xs text-text-secondary font-normal">({events.length})</span>
      </h3>
      <div ref={listRef} className="flex-1 overflow-y-auto scrollbar-thin p-2 space-y-1">
        {events.length === 0 ? (
          <div className="text-xs text-text-secondary text-center py-4">
            No activity yet...
          </div>
        ) : (
          events.map((evt, i) => (
            <div
              key={`${evt.event}-${evt.ts}-${i}`}
              className="px-2 py-1.5 rounded-md bg-background border border-border/30 text-xs flex items-start gap-2 animate-fadeIn"
            >
              <span className="text-text-secondary font-mono flex-shrink-0 text-[10px] mt-0.5">
                {evt.ts ? new Date(evt.ts).toLocaleTimeString() : "--:--"}
              </span>
              <EventTypeBadge event={evt.event} />
              <span className="text-text-primary truncate flex-1">
                {renderActivityDetail(evt)}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function renderActivityDetail(evt: PipelineEvent): string {
  const d = evt.data;
  if (!d) return "";
  switch (evt.event) {
    case "digest.session_start":
      return `${d.total_items ?? "?"} items, batch size ${d.batch_size ?? "?"}`;
    case "digest.session_end":
      return `${d.batches ?? "?"} batches, ${d.items_processed ?? "?"} items in ${Number(d.elapsed_s ?? 0).toFixed(1)}s`;
    case "digest.batch_start":
      return `Batch #${d.batch_num ?? "?"} (${d.item_count ?? "?"} items)`;
    case "digest.batch_complete":
      return `Batch #${d.batch_num ?? "?"} done (${Number(d.elapsed_s ?? 0).toFixed(1)}s)`;
    case "agent.tool_call.start":
      return `${d.tool_name ?? "unknown tool"}`;
    case "agent.tool_call.end": {
      const ok = d.success ? "ok" : "FAIL";
      return `${d.tool_name ?? "unknown"} [${ok}] ${Number(d.duration_s ?? 0).toFixed(2)}s`;
    }
    default:
      return "";
  }
}

function KBMutationBadge({ event }: { event: string }) {
  let label = "write";
  let color = "text-positive bg-positive/15";
  if (event === "kb.edit") {
    label = "edit";
    color = "text-amber-400 bg-amber-400/15";
  } else if (event === "kb.core_mind_updated") {
    label = "core mind";
    color = "text-interactive bg-interactive/15";
  }
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium whitespace-nowrap ${color}`}>
      {label}
    </span>
  );
}

function KBStatePanel({ mutations }: { mutations: PipelineEvent[] }) {
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [mutations.length]);

  return (
    <div className="flex flex-col h-full">
      <h3 className="text-sm font-medium text-text-primary px-3 py-2 border-b border-border flex-shrink-0">
        KB State
        <span className="ml-2 text-xs text-text-secondary font-normal">({mutations.length})</span>
      </h3>
      <div ref={listRef} className="flex-1 overflow-y-auto scrollbar-thin p-2 space-y-1.5">
        {mutations.length === 0 ? (
          <div className="text-xs text-text-secondary text-center py-4">
            No KB mutations yet...
          </div>
        ) : (
          mutations.map((evt, i) => (
            <div
              key={`${evt.event}-${evt.ts}-${i}`}
              className="px-3 py-2 rounded-lg bg-background border border-border/50 text-xs animate-kbFlash"
            >
              <div className="flex items-center gap-2 mb-1">
                <KBMutationBadge event={evt.event} />
                {evt.data?.section ? (
                  <span className="text-text-secondary">{String(evt.data.section)}</span>
                ) : null}
              </div>
              {evt.data?.slug ? (
                <div className="font-mono text-text-primary truncate" title={String(evt.data.slug)}>
                  {String(evt.data.slug)}
                </div>
              ) : null}
              <div className="text-text-secondary mt-0.5">
                {evt.event === "kb.edit"
                  ? evt.data?.old_len != null
                    ? `${evt.data.old_len} → ${evt.data.new_len} chars`
                    : "edited"
                  : evt.data?.size != null
                    ? `${evt.data.size} chars`
                    : "written"}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

const SPEED_OPTIONS = [1, 2, 4, 8] as const;

function PlaybackControls({
  isPlaying,
  onTogglePlay,
  onPrev,
  onNext,
  speed,
  onSetSpeed,
  currentIndex,
  totalEvents,
  elapsedMs,
  totalMs,
  onScrub,
  isLoaded,
}: {
  isPlaying: boolean;
  onTogglePlay: () => void;
  onPrev: () => void;
  onNext: () => void;
  speed: number;
  onSetSpeed: (s: number) => void;
  currentIndex: number;
  totalEvents: number;
  elapsedMs: number;
  totalMs: number;
  onScrub: (index: number) => void;
  isLoaded: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 px-4 py-3 bg-surface border-t border-border rounded-b-xl">
      {/* Transport controls */}
      <div className="flex items-center gap-1">
        <button
          onClick={onPrev}
          disabled={!isLoaded || currentIndex <= 0}
          className="w-8 h-8 rounded-md flex items-center justify-center text-text-secondary hover:text-text-primary hover:bg-border/30 disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
          aria-label="Previous event"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="M6 6h2v12H6zm3.5 6 8.5 6V6z" />
          </svg>
        </button>
        <button
          onClick={onTogglePlay}
          disabled={!isLoaded || totalEvents === 0}
          className="w-9 h-9 rounded-lg flex items-center justify-center bg-accent/15 text-accent hover:bg-accent/25 disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
          aria-label={isPlaying ? "Pause" : "Play"}
        >
          {isPlaying ? (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M8 5v14l11-7z" />
            </svg>
          )}
        </button>
        <button
          onClick={onNext}
          disabled={!isLoaded || currentIndex >= totalEvents - 1}
          className="w-8 h-8 rounded-md flex items-center justify-center text-text-secondary hover:text-text-primary hover:bg-border/30 disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
          aria-label="Next event"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" />
          </svg>
        </button>
      </div>

      {/* Separator */}
      <div className="w-px h-6 bg-border" />

      {/* Speed controls */}
      <div className="flex items-center gap-1">
        {SPEED_OPTIONS.map((s) => (
          <button
            key={s}
            onClick={() => onSetSpeed(s)}
            className={`px-2 py-1 text-xs font-medium rounded-md transition-colors cursor-pointer ${
              speed === s
                ? "bg-accent/15 text-accent"
                : "text-text-secondary hover:text-text-primary hover:bg-border/30"
            }`}
            aria-label={`${s}x speed`}
            aria-pressed={speed === s}
          >
            {s}x
          </button>
        ))}
      </div>

      {/* Separator */}
      <div className="w-px h-6 bg-border" />

      {/* Scrub bar */}
      <div className="flex items-center gap-3 flex-1 min-w-0">
        <input
          type="range"
          min={0}
          max={Math.max(0, totalEvents - 1)}
          value={currentIndex}
          onChange={(e) => onScrub(Number(e.target.value))}
          disabled={!isLoaded || totalEvents === 0}
          className="flex-1 min-w-[80px] h-1.5 rounded-full appearance-none bg-border cursor-pointer accent-accent disabled:opacity-30 disabled:cursor-not-allowed"
          aria-label="Scrub through events"
        />
        <span className="text-xs text-text-secondary font-mono whitespace-nowrap flex-shrink-0">
          {totalEvents > 0 ? currentIndex + 1 : 0} / {totalEvents}
        </span>
      </div>

      {/* Elapsed time */}
      <span className="text-xs text-text-secondary font-mono whitespace-nowrap">
        {formatElapsed(elapsedMs)} / {formatElapsed(totalMs)}
      </span>
    </div>
  );
}

// ─── Main Component ──────────────────────────────────────────────────────────

export function DigestReplay() {
  const { data: digests, isLoading: digestsLoading } = useDigestList();
  const [selectedExecId, setSelectedExecId] = useState<string | null>(null);
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isLoaded, setIsLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Auto-select most recent digest
  useEffect(() => {
    if (digests && digests.length > 0 && !selectedExecId) {
      setSelectedExecId(digests[0].exec_id);
    }
  }, [digests, selectedExecId]);

  // Load events for selected digest via SSE replay
  useEffect(() => {
    if (!selectedExecId || !EXEC_ID_RE.test(selectedExecId)) return;
    setEvents([]);
    setCurrentIndex(0);
    setIsLoaded(false);
    setIsPlaying(false);
    setLoadError(null);

    const collected: PipelineEvent[] = [];
    const es = new EventSource(`${API_BASE}/api/events/${selectedExecId}`, {
      withCredentials: true,
    });

    es.addEventListener("pipeline", (e: MessageEvent) => {
      try {
        const evt = JSON.parse(e.data) as PipelineEvent;
        collected.push(evt);
      } catch {
        // skip malformed events
      }
    });

    es.addEventListener("complete", () => {
      es.close();
      setEvents([...collected]);
      setIsLoaded(true);
    });

    es.onerror = () => {
      es.close();
      if (collected.length > 0) {
        setEvents([...collected]);
        setIsLoaded(true);
      } else {
        setLoadError("Failed to load events for this session.");
        setIsLoaded(true);
      }
    };

    return () => es.close();
  }, [selectedExecId]);

  // Playback timer — advances currentIndex using time-scaled delays
  useEffect(() => {
    if (!isPlaying || currentIndex >= events.length - 1) {
      if (currentIndex >= events.length - 1 && events.length > 0) {
        setIsPlaying(false);
      }
      return;
    }

    const delay = computePlaybackDelay(events[currentIndex], events[currentIndex + 1], speed);

    const timer = setTimeout(() => {
      setCurrentIndex((prev) => prev + 1);
    }, delay);

    return () => clearTimeout(timer);
  }, [isPlaying, currentIndex, events, speed]);

  // Derive visible events
  const visibleEvents = useMemo(
    () => events.slice(0, currentIndex + 1),
    [events, currentIndex]
  );

  // Categorize into 3 panels
  const articles = useMemo(() => categorizeArticles(visibleEvents), [visibleEvents]);
  const agentActivity = useMemo(() => categorizeAgentActivity(visibleEvents), [visibleEvents]);
  const kbMutations = useMemo(() => categorizeKBMutations(visibleEvents), [visibleEvents]);

  // Compute elapsed/total time
  const { elapsedMs, totalMs } = useMemo(() => {
    if (events.length < 2) return { elapsedMs: 0, totalMs: 0 };
    const firstTs = new Date(events[0].ts).getTime();
    const lastTs = new Date(events[events.length - 1].ts).getTime();
    const currentTs =
      currentIndex < events.length ? new Date(events[currentIndex].ts).getTime() : lastTs;
    return {
      elapsedMs: Math.max(0, currentTs - firstTs),
      totalMs: Math.max(0, lastTs - firstTs),
    };
  }, [events, currentIndex]);

  // Callbacks
  const handleTogglePlay = useCallback(() => {
    if (currentIndex >= events.length - 1 && !isPlaying) {
      // Restart from beginning
      setCurrentIndex(0);
      setIsPlaying(true);
    } else {
      setIsPlaying((prev) => !prev);
    }
  }, [currentIndex, events.length, isPlaying]);

  const handlePrev = useCallback(() => {
    setIsPlaying(false);
    setCurrentIndex((prev) => Math.max(0, prev - 1));
  }, []);

  const handleNext = useCallback(() => {
    setCurrentIndex((prev) => Math.min(events.length - 1, prev + 1));
  }, [events.length]);

  const handleScrub = useCallback(
    (index: number) => {
      setIsPlaying(false);
      setCurrentIndex(Math.max(0, Math.min(index, events.length - 1)));
    },
    [events.length]
  );

  const handleSetSpeed = useCallback((s: number) => {
    setSpeed(s);
  }, []);

  const handleSelectSession = useCallback((id: string) => {
    setSelectedExecId(id);
  }, []);

  // ─── Render ──────────────────────────────────────────────────────────────

  // No digests
  if (!digestsLoading && (!digests || digests.length === 0)) {
    return (
      <div className="bg-surface rounded-xl border border-border p-6 min-h-[400px] flex items-center justify-center text-text-secondary text-sm">
        No digest sessions found. Run a digest to see replay.
      </div>
    );
  }

  // Loading digests list
  if (digestsLoading) {
    return (
      <div className="bg-surface rounded-xl border border-border p-6 min-h-[400px] flex items-center justify-center text-text-secondary text-sm">
        Loading digest sessions...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Session Selector */}
      <SessionSelector
        digests={digests ?? []}
        selectedId={selectedExecId}
        onSelect={handleSelectSession}
      />

      {/* Theater */}
      <div className="bg-surface rounded-xl border border-border overflow-hidden">
        {/* Loading / Error / Empty states inside the theater */}
        {!isLoaded && selectedExecId && !loadError && (
          <div className="min-h-[400px] flex items-center justify-center text-text-secondary text-sm">
            <span className="flex items-center gap-2">
              <svg className="animate-spin h-4 w-4 text-accent" viewBox="0 0 24 24">
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                  fill="none"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
              Loading events...
            </span>
          </div>
        )}

        {loadError && (
          <div className="min-h-[400px] flex items-center justify-center text-text-secondary text-sm">
            {loadError}
          </div>
        )}

        {isLoaded && events.length === 0 && !loadError && (
          <div className="min-h-[400px] flex items-center justify-center text-text-secondary text-sm">
            No events found for this session.
          </div>
        )}

        {isLoaded && events.length > 0 && (
          <>
            {/* 3-column panels */}
            <div className="grid grid-cols-1 lg:grid-cols-3 h-[500px] divide-y lg:divide-y-0 lg:divide-x divide-border">
              {/* Left: Article Stream */}
              <div className="overflow-hidden">
                <ArticlePanel articles={articles} />
              </div>

              {/* Center: Agent Activity */}
              <div className="overflow-hidden">
                <AgentActivityPanel events={agentActivity} />
              </div>

              {/* Right: KB State */}
              <div className="overflow-hidden">
                <KBStatePanel mutations={kbMutations} />
              </div>
            </div>

            {/* Playback Controls */}
            <PlaybackControls
              isPlaying={isPlaying}
              onTogglePlay={handleTogglePlay}
              onPrev={handlePrev}
              onNext={handleNext}
              speed={speed}
              onSetSpeed={handleSetSpeed}
              currentIndex={currentIndex}
              totalEvents={events.length}
              elapsedMs={elapsedMs}
              totalMs={totalMs}
              onScrub={handleScrub}
              isLoaded={isLoaded}
            />
          </>
        )}
      </div>
    </div>
  );
}
