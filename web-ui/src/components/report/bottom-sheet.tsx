"use client";

import { motion, AnimatePresence, useDragControls } from "motion/react";
import { useRef } from "react";
import { cn } from "@/lib/utils";
import { VerdictBadge } from "./verdict-badge";
import { getVerdictStyle } from "./verdict-colors";
import type { MatchedCitation } from "./use-citations";

interface BottomSheetProps {
  citation: MatchedCitation | null;
  onClose: () => void;
}

/**
 * Mobile bottom sheet for citation details.
 * 40vh height, drag down to dismiss.
 * Triggered by tapping a badge on mobile.
 */
export function BottomSheet({ citation, onClose }: BottomSheetProps) {
  const dragControls = useDragControls();
  const sheetRef = useRef<HTMLDivElement>(null);

  return (
    <AnimatePresence>
      {citation && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/40 z-40 lg:hidden"
          />

          {/* Sheet */}
          <motion.div
            ref={sheetRef}
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            drag="y"
            dragControls={dragControls}
            dragConstraints={{ top: 0 }}
            dragElastic={0.2}
            onDragEnd={(_, info) => {
              if (info.offset.y > 100) onClose();
            }}
            className="fixed bottom-0 left-0 right-0 z-50 bg-surface border-t border-border rounded-t-2xl lg:hidden"
            style={{ height: "40vh", maxHeight: "400px" }}
          >
            {/* Drag handle */}
            <div className="flex justify-center pt-3 pb-2">
              <div className="w-10 h-1 rounded-full bg-border" />
            </div>

            {/* Content */}
            <div className="px-4 pb-4 overflow-y-auto h-full space-y-4">
              {/* Header */}
              <div className="flex items-center gap-2">
                <VerdictBadge
                  verdict={citation.verdict}
                  confidence={citation.confidence}
                  size="md"
                />
              </div>

              {/* Claim text */}
              <div>
                <h4 className="text-xs font-medium text-text-secondary mb-1">Claim</h4>
                <p className="text-sm text-text-primary leading-relaxed">
                  {citation.claim}
                </p>
              </div>

              {/* Evidence / Source */}
              {(citation.source || citation.specialist) && (
                <div>
                  <h4 className="text-xs font-medium text-text-secondary mb-1">Source</h4>
                  <div className="bg-background rounded-lg border border-border p-3 space-y-1">
                    {citation.source?.tool && (
                      <div className="flex items-center gap-2 text-xs">
                        <span className="text-text-secondary">Tool:</span>
                        <span className={cn("font-mono", getVerdictStyle(citation.verdict).text)}>
                          {citation.source.tool}
                        </span>
                      </div>
                    )}
                    {citation.source?.raw_value != null && (
                      <div className="flex items-center gap-2 text-xs">
                        <span className="text-text-secondary">Value:</span>
                        <span className="font-mono text-text-primary">{String(citation.source.raw_value)}</span>
                      </div>
                    )}
                    {!citation.source?.tool && citation.specialist?.agent && (
                      <div className="flex items-center gap-2 text-xs">
                        <span className="text-text-secondary">Specialist:</span>
                        <span className={cn("font-mono", getVerdictStyle(citation.verdict).text)}>
                          {citation.specialist.agent} analysis
                        </span>
                      </div>
                    )}
                    {citation.specialist?.excerpt && (
                      <div className="text-xs text-text-secondary italic border-l-2 border-white/10 pl-1.5 mt-1 line-clamp-3">
                        {citation.specialist.excerpt}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Section */}
              <div className="text-xs text-text-secondary">
                Section: {citation.section} | Line: {citation.matchedLine}
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

