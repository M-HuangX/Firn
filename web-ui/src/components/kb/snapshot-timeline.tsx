"use client";

import { useMemo, useState } from "react";
import type { CoreMindSnapshot } from "@/lib/types";

interface SnapshotTimelineProps {
  snapshots: CoreMindSnapshot[];
  leftId: string | null;
  rightId: string | null;
  onSelectLeft: (id: string) => void;
  onSelectRight: (id: string) => void;
}

/** Interpolate opacity from 0.8 (oldest/densest) to 0.2 (newest/lightest) */
function strataColor(index: number, total: number): string {
  if (total <= 1) return "rgba(139,92,246,0.5)";
  const t = index / (total - 1); // 0 = oldest, 1 = newest
  const opacity = 0.8 - t * 0.6; // 0.8 → 0.2
  return `rgba(139,92,246,${opacity.toFixed(2)})`;
}

/** Brighten opacity on hover */
function strataColorHover(index: number, total: number): string {
  if (total <= 1) return "rgba(139,92,246,0.65)";
  const t = index / (total - 1);
  const opacity = Math.min(0.9, 0.8 - t * 0.6 + 0.15);
  return `rgba(139,92,246,${opacity.toFixed(2)})`;
}

/** Format date to MM-DD */
function formatDateShort(dateStr: string): string {
  const parts = dateStr.split("-");
  if (parts.length >= 3) return `${parts[1]}-${parts[2]}`;
  return dateStr;
}

/** Format char count with K suffix */
function formatChars(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

export function SnapshotTimeline({
  snapshots,
  leftId,
  rightId,
  onSelectLeft,
  onSelectRight,
}: SnapshotTimelineProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  // Compute widths proportional to char_count, with min-width 40px
  const segmentWidths = useMemo(() => {
    if (snapshots.length === 0) return [];
    const maxChars = Math.max(...snapshots.map((s) => s.char_count), 1);
    // Scale so the largest segment is ~200px, smallest >= 40px
    return snapshots.map((s) => {
      const ratio = s.char_count / maxChars;
      return Math.max(40, Math.round(ratio * 200));
    });
  }, [snapshots]);

  // Compute deltas from previous snapshot
  const deltas = useMemo(() => {
    return snapshots.map((snap, i) => {
      if (i === 0) return snap.char_count;
      return snap.char_count - snapshots[i - 1].char_count;
    });
  }, [snapshots]);

  if (snapshots.length === 0) return null;

  return (
    <div className="space-y-3">
      {/* Legend */}
      <div className="flex items-center gap-2 text-xs text-text-secondary">
        <span>Click to select:</span>
        <span className="flex items-center gap-1">
          <span className="w-2.5 h-2.5 rounded-sm border-2 border-amber-500 bg-amber-500/20" />
          Left (older)
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2.5 h-2.5 rounded-sm border-2 border-emerald-500 bg-emerald-500/20" />
          Right (newer)
        </span>
      </div>

      {/* Strata bar row */}
      <div className="flex items-end gap-[2px] overflow-x-auto py-2 px-1">
        {snapshots.map((snap, i) => {
          const isLeft = snap.id === leftId;
          const isRight = snap.id === rightId;
          const isHovered = snap.id === hoveredId;
          const width = segmentWidths[i];
          const delta = deltas[i];
          const deltaLabel = i === 0 ? `${formatChars(delta)}` : `${delta >= 0 ? "+" : ""}${formatChars(delta)}`;
          const bgColor = isHovered
            ? strataColorHover(i, snapshots.length)
            : strataColor(i, snapshots.length);

          return (
            <div
              key={snap.id}
              className="relative flex flex-col items-center flex-shrink-0"
              style={{ width }}
            >
              {/* Strata segment */}
              <button
                onClick={() => {
                  if (!leftId || isRight) {
                    onSelectLeft(snap.id);
                  } else if (!rightId || isLeft) {
                    onSelectRight(snap.id);
                  } else {
                    // Both set: clicking replaces the closest
                    const leftIdx = snapshots.findIndex((s) => s.id === leftId);
                    const rightIdx = snapshots.findIndex((s) => s.id === rightId);
                    if (Math.abs(i - leftIdx) <= Math.abs(i - rightIdx)) {
                      onSelectLeft(snap.id);
                    } else {
                      onSelectRight(snap.id);
                    }
                  }
                }}
                onMouseEnter={() => setHoveredId(snap.id)}
                onMouseLeave={() => setHoveredId(null)}
                className="relative w-full rounded-sm cursor-pointer"
                style={{
                  height: 48,
                  backgroundColor: bgColor,
                  borderTop: isLeft
                    ? "3px solid rgb(245, 158, 11)"
                    : isRight
                      ? "3px solid rgb(16, 185, 129)"
                      : "3px solid transparent",
                  transform: isHovered ? "scale(1.02)" : "scale(1)",
                  transition: "transform 150ms cubic-bezier(0.22, 1, 0.36, 1), border-color 150ms cubic-bezier(0.22, 1, 0.36, 1), background-color 150ms cubic-bezier(0.22, 1, 0.36, 1)",
                }}
                title={`${snap.date} | ${snap.char_count.toLocaleString()} chars | ${deltaLabel} chars`}
              >
                {/* Delta label inside bar */}
                <span className="absolute inset-0 flex items-center justify-center text-[10px] font-medium text-white/80 select-none pointer-events-none">
                  {deltaLabel}
                </span>
              </button>

              {/* Date label below */}
              <span
                className={`mt-1 text-[10px] whitespace-nowrap ${
                  isLeft || isRight ? "text-text-primary font-medium" : "text-text-secondary"
                }`}
              >
                {formatDateShort(snap.date)}
              </span>

              {/* Hover tooltip */}
              {isHovered && (
                <div
                  className="absolute z-20 -top-14 px-2 py-1 rounded bg-[#131B2E] border border-border text-[10px] text-text-primary whitespace-nowrap shadow-lg pointer-events-none"
                  style={{ transform: "translateX(-50%)", left: "50%" }}
                >
                  <div>{snap.date}</div>
                  <div>{snap.char_count.toLocaleString()} chars</div>
                  <div className={delta >= 0 ? "text-emerald-400" : "text-red-400"}>
                    {deltaLabel} chars
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
