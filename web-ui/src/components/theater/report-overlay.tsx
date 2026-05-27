"use client";

import { useEffect, useCallback } from "react";
import { AnimatePresence, m } from "motion/react";
import { useTheaterStore } from "@/stores/pipeline-store";
import { ReportView } from "@/components/report/report-view";
import type { AuditCitation } from "@/lib/types";

interface ReportOverlayProps {
  execId: string;
  markdown: string;
  auditCitations?: AuditCitation[];
  auditStatus: "loading" | "in-progress" | "available" | "none";
}

const springTransition = { type: "spring" as const, stiffness: 300, damping: 25 };

export function ReportOverlay({
  execId,
  markdown,
  auditCitations,
  auditStatus,
}: ReportOverlayProps) {
  const reportOverlayOpen = useTheaterStore((s) => s.reportOverlayOpen);
  const closeReportOverlay = useTheaterStore((s) => s.closeReportOverlay);

  const handleEsc = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") closeReportOverlay();
    },
    [closeReportOverlay]
  );

  useEffect(() => {
    if (!reportOverlayOpen) return;
    document.addEventListener("keydown", handleEsc);
    return () => document.removeEventListener("keydown", handleEsc);
  }, [reportOverlayOpen, handleEsc]);

  return (
    <AnimatePresence>
      {reportOverlayOpen && (
        <m.div
          role="dialog"
          aria-modal="true"
          aria-label="Analysis Report"
          className="fixed inset-0 z-50 flex items-center justify-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            onClick={closeReportOverlay}
            aria-hidden="true"
          />

          {/* Content panel */}
          <m.div
            className="relative w-[90vw] max-w-[1400px] max-h-[90vh] bg-surface rounded-2xl border border-border shadow-2xl flex flex-col"
            initial={{ opacity: 0, scale: 0.92 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.92 }}
            transition={springTransition}
          >
            {/* Close button */}
            <button
              onClick={closeReportOverlay}
              className="absolute top-4 right-4 z-10 w-8 h-8 flex items-center justify-center rounded-lg text-text-secondary hover:text-text-primary hover:bg-white/10 transition-colors"
              aria-label="Close report overlay"
            >
              <svg
                className="w-5 h-5"
                viewBox="0 0 20 20"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              >
                <path d="M5 5l10 10M15 5l-10 10" />
              </svg>
            </button>

            {/* Report content — scrollable */}
            <div className="overflow-y-auto max-h-[calc(90vh-60px)] p-6 pt-14">
              <ReportView
                markdown={markdown}
                auditCitations={auditCitations}
                auditStatus={auditStatus}
                execId={execId}
              />
            </div>
          </m.div>
        </m.div>
      )}
    </AnimatePresence>
  );
}
