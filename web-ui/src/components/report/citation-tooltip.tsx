"use client";

import { useFloating, offset, flip, shift, arrow, autoUpdate } from "@floating-ui/react";
import { createPortal } from "react-dom";
import { useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { VerdictBadge } from "./verdict-badge";
import { getVerdictStyle } from "./verdict-colors";
import type { MatchedCitation } from "./use-citations";

// ─── Expandable raw value display ────────────────────────────────────────────

function RawValueDisplay({ rawValue }: { rawValue: unknown }) {
  const [expanded, setExpanded] = useState(false);
  const rawStr = typeof rawValue === "object"
    ? JSON.stringify(rawValue, null, 2)
    : String(rawValue);
  const isLong = rawStr.length > 80;

  return (
    <>
      <p className={cn(
        "font-mono text-text-secondary text-[10px]",
        isLong && !expanded ? "truncate" : "whitespace-pre-wrap break-all max-h-48 overflow-y-auto",
      )}>
        = {rawStr}
      </p>
      {isLong && (
        <button
          onClick={(e) => { e.stopPropagation(); setExpanded(prev => !prev); }}
          className="text-interactive text-[10px] hover:underline mt-0.5"
        >
          {expanded ? "▲ Collapse" : "▼ Expand full value"}
        </button>
      )}
    </>
  );
}

// ─── Expandable specialist excerpt ──────────────────────────────────────────

function SpecialistExcerpt({ excerpt }: { excerpt: string }) {
  const [expanded, setExpanded] = useState(false);
  const isLong = excerpt.length > 100;

  return (
    <div className="mt-1">
      <p className={cn(
        "text-text-secondary text-[10px] italic border-l-2 border-white/10 pl-1.5",
        isLong && !expanded ? "line-clamp-2" : "whitespace-pre-wrap break-all max-h-48 overflow-y-auto",
      )}>
        {excerpt}
      </p>
      {isLong && (
        <button
          onClick={(e) => { e.stopPropagation(); setExpanded(prev => !prev); }}
          className="text-interactive text-[10px] hover:underline mt-0.5"
        >
          {expanded ? "▲ Collapse" : "▼ Show full excerpt"}
        </button>
      )}
    </div>
  );
}

// ─── Main tooltip component ─────────────────────────────────────────────────

interface CitationTooltipProps {
  citation: MatchedCitation;
  children: React.ReactNode;
  forceOpen?: boolean;
}

/**
 * Glassmorphism tooltip showing verdict, confidence, claim text, and source chain.
 * Triggers on hover (desktop) with a delay.
 */
export function CitationTooltip({ citation, children, forceOpen }: CitationTooltipProps) {
  const [isOpen, setIsOpen] = useState(false);
  const arrowRef = useRef<HTMLDivElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>(null);
  const showTooltip = forceOpen || isOpen;

  const { refs, floatingStyles, middlewareData, placement } = useFloating({
    open: isOpen,
    placement: "top",
    middleware: [
      offset(8),
      flip({ fallbackPlacements: ["bottom", "right", "left"] }),
      shift({ padding: 8 }),
      arrow({ element: arrowRef }),
    ],
    whileElementsMounted: autoUpdate,
  });

  const handleMouseEnter = () => {
    timeoutRef.current = setTimeout(() => setIsOpen(true), 200);
  };

  const handleMouseLeave = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    setIsOpen(false);
  };

  const style = getVerdictStyle(citation.verdict);

  return (
    <>
      <span
        ref={refs.setReference}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        onFocus={handleMouseEnter}
        onBlur={handleMouseLeave}
        tabIndex={0}
        role="button"
        aria-label={`Citation: ${citation.verdict}, ${citation.claim.slice(0, 60)}`}
        className="inline"
      >
        {children}
      </span>

      {showTooltip && typeof document !== "undefined" && createPortal(
        <div
          ref={refs.setFloating}
          style={floatingStyles}
          onMouseEnter={() => { if (timeoutRef.current) clearTimeout(timeoutRef.current); }}
          onMouseLeave={handleMouseLeave}
          className="citation-tooltip-floating z-50 max-w-sm rounded-lg border border-white/10 bg-surface/80 backdrop-blur-xl shadow-xl p-3 space-y-2 text-xs"
        >
          {/* Header: verdict badge */}
          <div className="flex items-center gap-3">
            <VerdictBadge
              verdict={citation.verdict}
              confidence={citation.confidence}
              size="md"
            />
          </div>

          {/* Claim text */}
          <p className="text-text-primary leading-relaxed line-clamp-3">
            {citation.claim}
          </p>

          {/* Compound claim line span indicator */}
          {citation.lineSpan && citation.lineSpan[0] !== citation.lineSpan[1] && (
            <p className="text-[10px] text-text-secondary italic">
              Spans lines {citation.lineSpan[0]}–{citation.lineSpan[1]}
            </p>
          )}

          {/* Source chain */}
          {(citation.source || citation.specialist) && (
            <div className="pt-1 border-t border-white/5 space-y-1">
              <div className="flex items-center gap-1.5 text-text-secondary">
                <span className={style.text}>Source:</span>
                <span className="font-mono truncate">
                  {citation.source?.tool
                    ? citation.source.tool
                    : citation.specialist?.agent
                      ? `${citation.specialist.agent} specialist analysis`
                      : "—"}
                </span>
              </div>
              {citation.source?.raw_value != null && (
                <RawValueDisplay rawValue={citation.source.raw_value} />
              )}
              {citation.specialist?.excerpt && (
                <SpecialistExcerpt excerpt={citation.specialist.excerpt} />
              )}
            </div>
          )}

          {/* Arrow */}
          <div
            ref={arrowRef}
            className="absolute w-2 h-2 bg-surface/80 rotate-45 border-b border-r border-white/10"
            style={{
              left: middlewareData.arrow?.x != null ? `${middlewareData.arrow.x}px` : "",
              top: placement.startsWith("bottom") ? "-4px" : undefined,
              bottom: placement.startsWith("top") ? "-4px" : undefined,
            }}
          />
        </div>,
        document.body,
      )}
    </>
  );
}
