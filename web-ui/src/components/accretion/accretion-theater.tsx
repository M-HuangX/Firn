"use client";

import { useEffect, useCallback, useRef, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { PipelineEvent } from "@/lib/types";
import { API_BASE } from "@/lib/api-client";
import { useDigest } from "@/hooks/use-api";
import { useDigestTheaterStore, computeDigestPlaybackDelay } from "@/stores/digest-theater-store";
import { ReadingStack } from "./reading-stack";
import { FirnPresence } from "./firn-presence";
import { KnowledgeStrata } from "./knowledge-strata";
import { ConnectionLayer } from "./connection-layer";
import { PlaybackControls } from "./playback-controls";

const EXEC_ID_RE = /^[a-zA-Z0-9_-]+$/;

interface AccretionTheaterProps {
  execId: string;
}

export function AccretionTheater({ execId }: AccretionTheaterProps) {
  const router = useRouter();
  const { data: detail } = useDigest(execId);

  // ─── Store selectors (scalars only for React 19 safety) ─────────
  const isLoaded = useDigestTheaterStore((s) => s.isLoaded);
  const currentIndex = useDigestTheaterStore((s) => s.currentIndex);
  const isPlaying = useDigestTheaterStore((s) => s.isPlaying);
  const speed = useDigestTheaterStore((s) => s.speed);
  const totalEvents = useDigestTheaterStore((s) => s.totalEvents);
  const sseLoading = useDigestTheaterStore((s) => s.sseLoading);
  const loadError = useDigestTheaterStore((s) => s.loadError);
  const batchMarkerCount = useDigestTheaterStore((s) => s.batchMarkerCount);

  // Timeline metadata arrays (safe via scalar dep — only re-read when batchMarkerCount changes)
  const batchMarkers = useMemo(
    () => useDigestTheaterStore.getState().batchMarkers,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [batchMarkerCount],
  );
  const eventDotTypes = useMemo(
    () => useDigestTheaterStore.getState().eventDotTypes,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [batchMarkerCount],
  );

  // Store actions (stable references from Zustand)
  const loadEvents = useDigestTheaterStore((s) => s.loadEvents);
  const tick = useDigestTheaterStore((s) => s.tick);
  const storePlay = useDigestTheaterStore((s) => s.play);
  const storePause = useDigestTheaterStore((s) => s.pause);
  const storeScrub = useDigestTheaterStore((s) => s.scrub);
  const storeSetSpeed = useDigestTheaterStore((s) => s.setSpeed);
  const storeReset = useDigestTheaterStore((s) => s.reset);
  const setSseLoading = useDigestTheaterStore((s) => s.setSseLoading);
  const setLoadError = useDigestTheaterStore((s) => s.setLoadError);

  // Keep a ref to events for the playback timer
  const eventsRef = useRef<PipelineEvent[]>([]);

  // Sync events ref when store updates
  useEffect(() => {
    eventsRef.current = useDigestTheaterStore.getState().events;
    return useDigestTheaterStore.subscribe((state) => {
      eventsRef.current = state.events;
    });
  }, []);

  // ─── Load events via SSE ────────────────────────────────────────
  useEffect(() => {
    if (!execId || !EXEC_ID_RE.test(execId)) return;

    // Reset store for new session (all state changes happen via store actions,
    // not via local setState, to satisfy the set-state-in-effect lint rule).
    storeReset();
    setSseLoading(true);

    const collected: PipelineEvent[] = [];
    const es = new EventSource(`${API_BASE}/api/events/${execId}`, {
      withCredentials: true,
    });

    es.addEventListener("pipeline", (e: MessageEvent) => {
      try {
        const evt = JSON.parse(e.data) as PipelineEvent;
        collected.push(evt);
      } catch {
        // skip malformed
      }
    });

    es.addEventListener("complete", () => {
      es.close();
      loadEvents([...collected]);
      setSseLoading(false);
    });

    es.onerror = () => {
      es.close();
      if (collected.length > 0) {
        loadEvents([...collected]);
      } else {
        setLoadError("Failed to load events for this session.");
      }
      setSseLoading(false);
    };

    return () => {
      es.close();
    };
  }, [execId, loadEvents, storeReset, setSseLoading, setLoadError]);

  // ─── Playback timer ─────────────────────────────────────────────
  useEffect(() => {
    if (!isPlaying || currentIndex >= totalEvents - 1) {
      if (currentIndex >= totalEvents - 1 && totalEvents > 0 && isPlaying) {
        storePause();
      }
      return;
    }

    const events = eventsRef.current;
    const delay = computeDigestPlaybackDelay(
      events[currentIndex],
      events[currentIndex + 1],
      speed,
    );

    const timer = setTimeout(() => {
      tick();
    }, delay);

    return () => clearTimeout(timer);
  }, [isPlaying, currentIndex, totalEvents, speed, tick, storePause]);

  // ─── Callbacks for PlaybackControls ─────────────────────────────
  const handleTogglePlay = useCallback(() => {
    if (isPlaying) {
      storePause();
    } else {
      storePlay();
    }
  }, [isPlaying, storePlay, storePause]);

  const handleScrub = useCallback(
    (index: number) => {
      storeScrub(index);
    },
    [storeScrub],
  );

  const handleSetSpeed = useCallback(
    (s: number) => {
      storeSetSpeed(s);
    },
    [storeSetSpeed],
  );

  // ─── Header info ────────────────────────────────────────────────
  const layerDate = detail?.started_at
    ? new Date(detail.started_at).toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
      })
    : "Unknown date";

  const showLoading = sseLoading && !isLoaded;
  const showError = !!loadError && !isLoaded;
  const showEmpty = isLoaded && totalEvents === 0 && !loadError;
  const showTheater = isLoaded && totalEvents > 0;

  // ─── Opening animation state ──────────────────────────────────────
  const [openingDone, setOpeningDone] = useState(false);

  useEffect(() => {
    if (!showTheater) {
      setOpeningDone(false);
      return;
    }
    const timer = setTimeout(() => setOpeningDone(true), 2200);
    return () => clearTimeout(timer);
  }, [showTheater]);

  // ─── Global keyboard shortcuts ──────────────────────────────────
  useEffect(() => {
    if (!showTheater) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

      switch (e.key) {
        case " ":
          e.preventDefault();
          if (useDigestTheaterStore.getState().isPlaying) storePause(); else storePlay();
          break;
        case "ArrowLeft":
          e.preventDefault();
          storeScrub(Math.max(0, useDigestTheaterStore.getState().currentIndex - 1));
          break;
        case "ArrowRight": {
          e.preventDefault();
          const s = useDigestTheaterStore.getState();
          storeScrub(Math.min(s.events.length - 1, s.currentIndex + 1));
          break;
        }
        case "1": storeSetSpeed(1); break;
        case "2": storeSetSpeed(2); break;
        case "4": storeSetSpeed(4); break;
        case "8": storeSetSpeed(8); break;
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [showTheater, storePlay, storePause, storeScrub, storeSetSpeed]);

  return (
    <div
      className="h-screen flex flex-col relative overflow-hidden"
      style={{
        // Layer 1: Base gradient (static) — deep glacial interior
        background: `radial-gradient(
          ellipse 70% 80% at 50% 45%,
          #131B2E 0%,
          #0E1628 35%,
          #070D18 100%
        )`,
      }}
    >
      {/* Layer 2: Warm Firn glow (animated, centered on stage) */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: `radial-gradient(
            circle 200px at 50% 45%,
            rgba(217, 168, 83, 0.04) 0%,
            rgba(217, 168, 83, 0.02) 40%,
            transparent 100%
          )`,
          animation: showTheater && !openingDone
            ? "glowIgnite 700ms ease-out 500ms forwards"
            : "firnGlowBreathe 8s ease-in-out infinite",
          ...(showTheater && !openingDone ? { opacity: 0 } : {}),
        }}
      />

      {/* Layer 3: Edge vignette (static) */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: `radial-gradient(
            ellipse 90% 90% at 50% 50%,
            transparent 60%,
            rgba(0, 0, 0, 0.3) 100%
          )`,
        }}
      />

      {/* Inline keyframes for the warm glow breathing + opening animation */}
      <style
        dangerouslySetInnerHTML={{
          __html: `
            @keyframes firnGlowBreathe {
              0%, 100% { opacity: 1; }
              50% { opacity: 0.85; }
            }
            @keyframes glowIgnite {
              from { opacity: 0; }
              to { opacity: 1; }
            }
            @keyframes accretionSlideInLeft {
              from { transform: translateX(-30px); opacity: 0; }
              to { transform: translateX(0); opacity: 1; }
            }
            @keyframes accretionSlideInRight {
              from { transform: translateX(20px); opacity: 0; }
              to { transform: translateX(0); opacity: 1; }
            }
          `,
        }}
      />

      {/* Header */}
      <div className="relative z-10 flex items-center justify-between px-6 py-4 border-b border-white/[0.06] flex-shrink-0">
        <div className="flex items-center gap-4">
          <button
            onClick={() => router.push("/accretion")}
            className="flex items-center gap-1.5 text-sm text-text-secondary hover:text-text-primary transition-colors cursor-pointer"
            style={{
              transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
            }}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M19 12H5M12 19l-7-7 7-7" />
            </svg>
            History
          </button>
          <div className="w-px h-5 bg-white/[0.06]" />
          <div>
            <h1 className="text-base font-semibold text-text-primary">
              Digest Theater
            </h1>
            <p className="text-xs text-text-secondary">
              {layerDate}
              {detail?.articles_processed != null && (
                <span className="ml-2">
                  {detail.articles_processed} articles
                </span>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {detail?.status && (
            <span
              className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                detail.status === "complete"
                  ? "bg-positive/15 text-positive"
                  : detail.status === "running"
                    ? "bg-amber-400/15 text-amber-400"
                    : detail.status === "failed"
                      ? "bg-negative/15 text-negative"
                      : "bg-border/30 text-text-secondary"
              }`}
            >
              {detail.status}
            </span>
          )}
        </div>
      </div>

      {/* Loading state */}
      {showLoading && (
        <div className="relative z-10 flex-1 flex items-center justify-center text-text-secondary text-sm">
          <span className="flex items-center gap-2">
            <svg
              className="animate-spin h-4 w-4 text-accent"
              viewBox="0 0 24 24"
            >
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

      {/* Error state */}
      {showError && (
        <div className="relative z-10 flex-1 flex items-center justify-center text-text-secondary text-sm">
          {loadError}
        </div>
      )}

      {/* Empty state */}
      {showEmpty && (
        <div className="relative z-10 flex-1 flex items-center justify-center text-text-secondary text-sm">
          No events found for this session.
        </div>
      )}

      {/* Theater content */}
      {showTheater && (
        <>
          {/* Asymmetric 3-zone layout: 1fr 1.6fr 1.4fr */}
          <div
            className="relative z-10 flex-1 min-h-0"
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1.6fr 1.4fr",
              gridTemplateRows: "minmax(0, 1fr)",
            }}
          >
            {/* Connection Layer — SVG overlay between zones */}
            <ConnectionLayer />

            {/* Zone A: Reading Stack (left, ~25%) */}
            <div
              className="overflow-hidden"
              style={
                showTheater && !openingDone
                  ? {
                      opacity: 0,
                      transform: "translateX(-30px)",
                      animation: "accretionSlideInLeft 600ms ease-out 1200ms forwards",
                    }
                  : undefined
              }
            >
              <ReadingStack />
            </div>

            {/* Zone B: Firn's Presence (center, ~40%) */}
            <div className="overflow-hidden">
              <FirnPresence onTogglePlay={handleTogglePlay} />
            </div>

            {/* Zone C: Knowledge Strata (right, ~35%) */}
            <div
              className="overflow-hidden"
              style={
                showTheater && !openingDone
                  ? {
                      opacity: 0,
                      transform: "translateX(20px)",
                      animation: "accretionSlideInRight 400ms ease-out 1800ms forwards",
                    }
                  : undefined
              }
            >
              <KnowledgeStrata />
            </div>
          </div>

          {/* Playback Controls */}
          <div className="relative z-10">
            <PlaybackControls
              isPlaying={isPlaying}
              onTogglePlay={handleTogglePlay}
              speed={speed}
              onSetSpeed={handleSetSpeed}
              currentIndex={currentIndex}
              totalEvents={totalEvents}
              onScrub={handleScrub}
              isLoaded={isLoaded}
              batchMarkers={batchMarkers}
              eventDotTypes={eventDotTypes}
            />
          </div>
        </>
      )}
    </div>
  );
}
