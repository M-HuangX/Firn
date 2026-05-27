"use client";

import { cn } from "@/lib/utils";
import { VERDICT_ORDER, getVerdictStyle } from "./verdict-colors";
import type { Verdict } from "./verdict-colors";
import type { MatchedCitation } from "./use-citations";

interface TrustSummaryBarProps {
  citations: MatchedCitation[];
  unmatchedCount: number;
  activeFilter: string | null;
  onFilterChange: (verdict: string | null) => void;
  className?: string;
}

/**
 * Segmented horizontal bar showing verdict distribution.
 * Click a segment to filter citations by that verdict type.
 */
export function TrustSummaryBar({
  citations,
  unmatchedCount,
  activeFilter,
  onFilterChange,
  className,
}: TrustSummaryBarProps) {
  // Count per verdict
  const counts = new Map<string, number>();
  for (const c of citations) {
    counts.set(c.verdict, (counts.get(c.verdict) ?? 0) + 1);
  }

  const total = citations.length + unmatchedCount;
  if (total === 0) return null;

  return (
    <div className={cn("space-y-2", className)}>
      {/* Segmented bar */}
      <div className="flex h-2 rounded-full overflow-hidden bg-background border border-border">
        {VERDICT_ORDER.map((verdict) => {
          const count = counts.get(verdict) ?? 0;
          if (count === 0) return null;
          const pct = (count / total) * 100;
          const style = getVerdictStyle(verdict);
          const isActive = activeFilter === null || activeFilter === verdict;

          return (
            <button
              key={verdict}
              onClick={() => onFilterChange(activeFilter === verdict ? null : verdict)}
              aria-label={`${style.label}: ${count} claims (${Math.round(pct)}%)`}
              aria-pressed={activeFilter === verdict}
              className={cn(
                "h-full transition-opacity",
                !isActive && "opacity-30"
              )}
              style={{
                width: `${pct}%`,
                backgroundColor: style.barColor,
                minWidth: count > 0 ? "4px" : "0",
              }}
              title={`${style.label}: ${count} (${Math.round(pct)}%)`}
            />
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {VERDICT_ORDER.map((verdict) => {
          const count = counts.get(verdict) ?? 0;
          if (count === 0) return null;
          const style = getVerdictStyle(verdict);
          const isActive = activeFilter === null || activeFilter === verdict;

          return (
            <button
              key={verdict}
              onClick={() => onFilterChange(activeFilter === verdict ? null : verdict)}
              aria-label={`Filter by ${style.label}`}
              aria-pressed={activeFilter === verdict}
              className={cn(
                "flex items-center gap-1.5 transition-opacity",
                !isActive && "opacity-40"
              )}
            >
              <span
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: style.barColor }}
              />
              <span className={cn(style.text, "font-medium")}>{count}</span>
              <span className="text-text-secondary">{style.shortLabel}</span>
            </button>
          );
        })}
        {unmatchedCount > 0 && (
          <span className="flex items-center gap-1.5 text-text-secondary">
            <span className="w-2 h-2 rounded-full bg-slate-600" />
            <span>{unmatchedCount}</span>
            <span>Unmatched</span>
          </span>
        )}
      </div>

      {/* Active filter indicator */}
      {activeFilter && (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-text-secondary">Filtering:</span>
          <span className={getVerdictStyle(activeFilter as Verdict).text}>
            {getVerdictStyle(activeFilter).label}
          </span>
          <button
            onClick={() => onFilterChange(null)}
            className="text-text-secondary hover:text-text-primary ml-1"
          >
            Clear
          </button>
        </div>
      )}
    </div>
  );
}
