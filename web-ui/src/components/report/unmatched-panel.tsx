"use client";

import { VerdictBadge } from "./verdict-badge";
import type { UnmatchedCitation } from "./use-citations";

interface UnmatchedPanelProps {
  citations: UnmatchedCitation[];
  onClickCitation: (estimatedLine: number) => void;
}

/**
 * Panel below report showing citations that couldn't be matched (confidence < 0.50).
 * Shows claim text, verdict badge, and "Estimated location: near line X" hint.
 */
export function UnmatchedPanel({ citations, onClickCitation }: UnmatchedPanelProps) {
  if (citations.length === 0) return null;

  return (
    <div className="mt-6 border-t border-border pt-4">
      <h4 className="text-sm font-medium text-text-secondary mb-3">
        Unmatched Citations ({citations.length})
      </h4>
      <div className="space-y-2">
        {citations.map((c) => (
          <button
            key={c.id}
            onClick={() => onClickCitation(c.estimatedLine)}
            className="w-full text-left p-3 rounded-lg bg-background border border-border hover:border-border/80 transition-colors group"
          >
            <div className="flex items-start gap-2">
              <VerdictBadge verdict={c.verdict} size="sm" />
              <div className="flex-1 min-w-0">
                <p className="text-xs text-text-primary line-clamp-2 leading-relaxed">
                  {c.claim}
                </p>
                <p className="text-[10px] text-text-secondary mt-1 group-hover:text-interactive transition-colors">
                  Estimated location: near line {c.estimatedLine}
                </p>
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
