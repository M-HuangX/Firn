"use client";

import { useMemo, useRef, useEffect, useCallback, useState } from "react";
import { useDigestTheaterStore } from "@/stores/digest-theater-store";
import type { KBModuleState, KBSectionType, FirnState } from "@/lib/digest-theater-types";
import { KBModuleCard } from "./kb-module-card";

// ─── Constants ───────────────────────────────────────────────────────────────

/** Compaction threshold: modules settled longer than this get compressed to header-only */
const COMPACTION_THRESHOLD_MS = 60_000;

/** How long after manual scroll before auto-scroll re-engages (ms) */
const SCROLL_DISENGAGE_MS = 8000;

/** Auto-scroll delay after new module appears (ms) */
const AUTO_SCROLL_DELAY_MS = 300;

/** Section grouping order per R5 spec */
const SECTION_ORDER: KBSectionType[] = [
  "core_mind",
  "themes",
  "events",
  "stocks",
  "sectors",
];

/** Human-readable labels for section group headers */
const SECTION_LABELS: Record<KBSectionType, string> = {
  core_mind: "CORE MIND",
  themes: "THEMES",
  events: "EVENTS",
  stocks: "STOCKS",
  sectors: "SECTORS",
};

// ─── Types ───────────────────────────────────────────────────────────────────

interface SectionGroup {
  section: KBSectionType;
  modules: KBModuleState[];
}

// ─── Compaction helper ────────────────────────────────────────────────────────

/**
 * Determine whether a KB module should be compacted (collapsed to header-only).
 * Core Mind is never compacted. Session complete removes all compaction.
 */
function isModuleCompacted(
  mod: KBModuleState,
  currentReplayTs: number,
  firnState: FirnState,
): boolean {
  if (mod.section === "core_mind") return false;
  if (firnState === "complete") return false;
  if (currentReplayTs <= 0) return false;
  return (currentReplayTs - mod.lastEditAt) > COMPACTION_THRESHOLD_MS;
}

// ─── Component ───────────────────────────────────────────────────────────────

export function KnowledgeStrata() {
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastManualScrollRef = useRef<number>(0);
  const prevModuleCountRef = useRef<number>(0);

  // Scalar selectors (React 19 safe)
  const kbModuleCount = useDigestTheaterStore((s) => s.kbModuleCount);
  const currentReplayTs = useDigestTheaterStore((s) => s.currentReplayTs);
  const firnState = useDigestTheaterStore((s) => s.firnState);

  // Track which modules have already been "born" to avoid re-animating on scrub
  const [seenModuleIds] = useState(() => new Set<string>());

  // Derive modules array from store using scalar trigger
  const kbModules = useMemo(() => {
    return useDigestTheaterStore.getState().kbModules;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kbModuleCount]);

  // Group modules by section type (already ordered by deriveState, but we need headers)
  const sectionGroups = useMemo((): SectionGroup[] => {
    const groups: SectionGroup[] = [];
    const seen = new Set<KBSectionType>();

    for (const mod of kbModules) {
      if (!seen.has(mod.section)) {
        seen.add(mod.section);
        groups.push({ section: mod.section, modules: [] });
      }
      const group = groups.find((g) => g.section === mod.section);
      if (group) {
        group.modules.push(mod);
      }
    }

    // Sort groups by the defined section order
    groups.sort(
      (a, b) => SECTION_ORDER.indexOf(a.section) - SECTION_ORDER.indexOf(b.section)
    );

    return groups;
  }, [kbModules]);

  // Track manual scrolling to temporarily disable auto-scroll
  const handleScroll = useCallback(() => {
    lastManualScrollRef.current = Date.now();
  }, []);

  // Auto-scroll to newest module when it appears
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const currentCount = kbModules.length;
    const prevCount = prevModuleCountRef.current;
    prevModuleCountRef.current = currentCount;

    // Only auto-scroll if a new module appeared
    if (currentCount <= prevCount) return;

    // Skip auto-scroll if user recently scrolled manually
    const timeSinceManual = Date.now() - lastManualScrollRef.current;
    if (timeSinceManual < SCROLL_DISENGAGE_MS && lastManualScrollRef.current > 0) return;

    // Scroll to bottom with delay
    const timer = setTimeout(() => {
      requestAnimationFrame(() => {
        el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
      });
    }, AUTO_SCROLL_DELAY_MS);

    return () => clearTimeout(timer);
  }, [kbModules.length]);

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      {/* Birth animation + ambient border breathing keyframes — rendered once at container level */}
      <style
        dangerouslySetInnerHTML={{
          __html: `
            @keyframes kbModuleBirth {
              0% {
                transform: scale(0.85) translateX(-20px);
                opacity: 0;
                filter: blur(6px);
              }
              40% {
                transform: scale(1) translateX(0);
                opacity: 1;
                filter: blur(0);
              }
              100% {
                transform: scale(1) translateX(0);
                opacity: 1;
                filter: blur(0);
              }
            }
            @keyframes kbBorderBreathe {
              0%, 100% { opacity: 1; }
              50% { opacity: 0.92; }
            }
          `,
        }}
      />
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto scrollbar-thin"
        style={{ padding: "12px 12px 12px 16px" }}
      >
        {kbModules.length === 0 ? (
          /* Empty state */
          <div
            className="flex items-center justify-center h-full"
            style={{
              color: "rgba(226, 235, 245, 0.25)",
              fontSize: "11px",
              fontFamily: "system-ui, sans-serif",
              letterSpacing: "0.02em",
            }}
          >
            Knowledge crystallizing...
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
            {sectionGroups.map((group) => (
              <div key={group.section}>
                {/* Section group header — only show for non-core_mind */}
                {group.section !== "core_mind" && (() => {
                  const settledCount = group.modules.filter(
                    (mod) => isModuleCompacted(mod, currentReplayTs, firnState)
                  ).length;
                  return (
                    <div
                      style={{
                        fontSize: "10px",
                        fontFamily: "system-ui, sans-serif",
                        fontWeight: 500,
                        textTransform: "uppercase",
                        letterSpacing: "0.05em",
                        color: "rgba(226, 235, 245, 0.35)",
                        padding: "10px 4px 4px",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        <span>{SECTION_LABELS[group.section]}</span>
                        {settledCount > 0 && (
                          <span style={{
                            fontSize: "10px",
                            fontFamily: "system-ui, sans-serif",
                            fontWeight: 400,
                            color: "rgba(226, 235, 245, 0.2)",
                            letterSpacing: "normal",
                            textTransform: "none",
                          }}>
                            {settledCount} settled
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })()}

                {/* Module cards */}
                <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                  {group.modules.map((mod, modIdx) => {
                    const shouldAnimate = !seenModuleIds.has(mod.id);
                    if (shouldAnimate) seenModuleIds.add(mod.id);
                    return (
                      <KBModuleCard
                        key={mod.id}
                        module={mod}
                        currentReplayTs={currentReplayTs}
                        shouldAnimate={shouldAnimate}
                        moduleIndex={modIdx}
                        isCompacted={isModuleCompacted(mod, currentReplayTs, firnState)}
                      />
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
