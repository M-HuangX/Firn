"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { cn } from "@/lib/utils";
import { VerdictBadge } from "./verdict-badge";
import { getVerdictStyle } from "./verdict-colors";
import type { MatchedCitation } from "./use-citations";

interface SidenotesProps {
  citations: MatchedCitation[];
  hoveredCitationId: number | null;
  clickedCitationId?: number | null;
  onHoverCitation: (id: number | null) => void;
  onClickCitation?: (id: number) => void;
  reportRef: React.RefObject<HTMLDivElement | null>;
  visible: boolean;
}

/**
 * Gwern-style right margin sidenotes (>= 1440px screens only).
 * Shows numbered citations positioned near their source line.
 * Two-pass collision avoidance: render -> measure actual heights -> reposition.
 */
export function Sidenotes({
  citations,
  hoveredCitationId,
  clickedCitationId,
  onHoverCitation,
  onClickCitation,
  reportRef,
  visible,
}: SidenotesProps) {
  const [positions, setPositions] = useState<Map<number, number>>(new Map());
  const cardHeights = useRef<Map<number, number>>(new Map());
  const [measurePass, setMeasurePass] = useState(0);

  const calculatePositions = useCallback(() => {
    if (!reportRef.current || citations.length === 0) return;

    const reportEl = reportRef.current;
    const newPositions = new Map<number, number>();
    const minGap = 8;

    const rawPositions: { id: number; y: number }[] = [];
    for (const c of citations) {
      // Try positioning by specific citation mark first, fall back to line
      const citEl = reportEl.querySelector(`[data-citation-id="${c.id}"]`);
      const lineEl = reportEl.querySelector(`[data-source-line="${c.matchedLine}"]`);
      const el = citEl || lineEl;
      if (el) {
        const rect = el.getBoundingClientRect();
        const reportRect = reportEl.getBoundingClientRect();
        rawPositions.push({ id: c.id, y: rect.top - reportRect.top });
      }
    }

    rawPositions.sort((a, b) => a.y - b.y);
    let lastBottom = -Infinity;
    for (const pos of rawPositions) {
      const adjustedY = Math.max(pos.y, lastBottom + minGap);
      newPositions.set(pos.id, adjustedY);
      const cardH = cardHeights.current.get(pos.id) ?? 76;
      lastBottom = adjustedY + cardH;
    }

    setPositions(newPositions);
  }, [citations, reportRef]);

  useEffect(() => {
    if (!visible) return;
    calculatePositions();
  }, [visible, calculatePositions]);

  useEffect(() => {
    if (!visible || measurePass === 0) return;
    calculatePositions();
  }, [visible, measurePass, calculatePositions]);

  const cardRef = useCallback((id: number, el: HTMLDivElement | null) => {
    if (!el) return;
    const h = el.getBoundingClientRect().height;
    const prev = cardHeights.current.get(id);
    if (prev !== h) {
      cardHeights.current.set(id, h);
      setMeasurePass((p) => p + 1);
    }
  }, []);

  if (!visible) return null;

  const sortedCitations = [...citations].sort(
    (a, b) => a.matchedLine - b.matchedLine || (a.charOffset ?? 0) - (b.charOffset ?? 0),
  );

  return (
    <div
      className="hidden min-[1440px]:block absolute -right-72 top-0 w-64"
      aria-label="Citation sidenotes"
    >
      {sortedCitations.map((c) => {
        const y = positions.get(c.id);
        if (y === undefined) return null;
        const style = getVerdictStyle(c.verdict);
        const isHovered = hoveredCitationId === c.id;
        const isClicked = clickedCitationId === c.id;
        const isActive = isHovered || isClicked;

        return (
          <div
            key={c.id}
            ref={(el) => cardRef(c.id, el)}
            className={cn(
              "absolute left-0 right-0 p-2 rounded-lg border text-xs transition-all duration-200 cursor-pointer",
              isActive
                ? "border-accent/30 bg-surface shadow-md scale-[1.02]"
                : "border-border/50 bg-surface/60 hover:border-border",
            )}
            style={{ top: y }}
            onMouseEnter={() => onHoverCitation(c.id)}
            onMouseLeave={() => onHoverCitation(null)}
            onClick={() => onClickCitation?.(c.id)}
          >
            <div className="flex items-start gap-1.5">
              <span
                className="shrink-0 font-mono font-bold text-[10px] leading-4 min-w-[1.25rem]"
                style={{ color: style.barColor }}
              >
                #{c.displayNumber}
              </span>
              <VerdictBadge verdict={c.verdict} confidence={c.confidence} size="sm" />
              <p className="text-text-secondary leading-tight line-clamp-2 flex-1">
                {c.claim}
              </p>
            </div>
            {c.source?.tool && (
              <p className={cn("mt-1 ml-5 font-mono text-[10px] truncate", style.text)}>
                {c.source.tool}
                {c.specialist?.agent ? ` (${c.specialist.agent})` : ""}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
