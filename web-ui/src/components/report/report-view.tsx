"use client";

import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { motion, AnimatePresence } from "motion/react";
import { CitationOverlay } from "./citation-overlay";
import { TrustSummaryBar } from "./trust-summary-bar";
import { AuditToggle } from "./audit-toggle";
import { UnmatchedPanel } from "./unmatched-panel";
import { ScanLine } from "./scan-line";
import { Sidenotes } from "./sidenotes";
import { BottomSheet } from "./bottom-sheet";
import { useCitations } from "./use-citations";
import type { MatchedCitation } from "./use-citations";
import type { AuditCitation } from "@/lib/types";

interface ReportViewProps {
  markdown: string;
  auditCitations?: AuditCitation[];
  /** "loading" = fetching audit data, "in-progress" = audit actively running, "available" = audit ready, "none" = no audit exists */
  auditStatus?: "loading" | "in-progress" | "available" | "none";
  /** Execution ID — used for per-report scan animation tracking */
  execId?: string;
}

/**
 * Top-level report + audit orchestrator.
 * Manages: audit visibility state, animation mode, verdict filtering, responsive layout.
 */
export function ReportView({ markdown, auditCitations, auditStatus = "none", execId }: ReportViewProps) {
  const hasAudit = !!auditCitations && auditCitations.length > 0;

  // Audit visibility state — default ON when audit available
  const [auditVisible, setAuditVisible] = useState(false);
  const [activeFilter, setActiveFilter] = useState<string | null>(null);
  const [scanActive, setScanActive] = useState(false);
  const [hoveredCitationId, setHoveredCitationId] = useState<number | null>(null);
  const [mobileSheet, setMobileSheet] = useState<MatchedCitation | null>(null);
  const [clickedCitationId, setClickedCitationId] = useState<number | null>(null);

  // Refs
  const reportRef = useRef<HTMLDivElement>(null);
  const [containerHeight, setContainerHeight] = useState(0);
  const [citationYPositions, setCitationYPositions] = useState<number[]>([]);

  // Strip short preamble before first heading (e.g. "I have all the data...")
  const processedMarkdown = useMemo(() => {
    const match = markdown.match(/^# /m);
    if (!match || match.index === undefined || match.index === 0) return markdown;
    const preamble = markdown.substring(0, match.index).trim();
    if (preamble.length > 0 && preamble.length < 200) {
      return markdown.substring(match.index);
    }
    return markdown;
  }, [markdown]);

  // Citation matching
  const { matched, unmatched, stats, byLine } = useCitations(processedMarkdown, auditCitations);

  // Auto-enable audit when available (first time: with scan, subsequent: instant)
  const scanKey = execId ? `audit-scan-seen-${execId}` : "audit-scan-seen";
  const autoEnabled = useRef(false);
  useEffect(() => {
    if (!hasAudit || autoEnabled.current) return;
    autoEnabled.current = true;
    const hasSeen = localStorage.getItem(scanKey);
    if (!hasSeen) {
      setScanActive(true);
      localStorage.setItem(scanKey, "1");
    }
    setAuditVisible(true);
  }, [hasAudit, scanKey]);

  // Track container height for scan line
  useEffect(() => {
    if (!reportRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerHeight(entry.contentRect.height);
      }
    });
    observer.observe(reportRef.current);
    return () => observer.disconnect();
  }, []);

  // Calculate citation y-positions for non-uniform scan speed
  useEffect(() => {
    if (!reportRef.current || matched.length === 0) return;
    const reportEl = reportRef.current;
    const reportRect = reportEl.getBoundingClientRect();
    const positions: number[] = [];

    for (const c of matched) {
      const el = reportEl.querySelector(`[data-source-line="${c.matchedLine}"]`);
      if (el) {
        const rect = el.getBoundingClientRect();
        positions.push(rect.top - reportRect.top);
      }
    }
    setCitationYPositions(positions);
  }, [matched, auditVisible]);

  // Toggle audit visibility
  const handleToggle = useCallback(() => {
    if (!auditVisible) {
      setAuditVisible(true);
    } else {
      setAuditVisible(false);
      setActiveFilter(null);
    }
  }, [auditVisible]);

  const handleScanComplete = useCallback(() => {
    setScanActive(false);
  }, []);

  // Scroll to line (for unmatched citations click-to-scroll)
  const scrollToLine = useCallback((line: number) => {
    if (!reportRef.current) return;
    const el = reportRef.current.querySelector(`[data-source-line="${line}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      // Highlight pulse
      el.classList.add("ring-2", "ring-accent/50", "ring-offset-2", "ring-offset-background");
      setTimeout(() => {
        el.classList.remove("ring-2", "ring-accent/50", "ring-offset-2", "ring-offset-background");
      }, 2000);
    }
  }, []);

  // Filter sidenotes by active verdict
  const filteredSidenoteCitations = useMemo(() => {
    if (!activeFilter) return matched;
    return matched.filter(c => c.verdict === activeFilter);
  }, [matched, activeFilter]);

  // Handle sidenote click — scroll to inline mark + show tooltip
  const handleSidenoteClick = useCallback((citationId: number) => {
    setClickedCitationId(prev => prev === citationId ? null : citationId);
    if (reportRef.current) {
      const el = reportRef.current.querySelector(`[data-citation-id="${citationId}"]`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  }, []);

  // Dismiss clicked citation on escape or outside click
  useEffect(() => {
    if (clickedCitationId === null) return;
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setClickedCitationId(null);
    };
    const handleClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest(".citation-tooltip-floating") || target.closest("[aria-label=\"Citation sidenotes\"]") || target.closest(".citation-mark")) return;
      setClickedCitationId(null);
    };
    document.addEventListener("keydown", handleEscape);
    document.addEventListener("click", handleClick);
    return () => {
      document.removeEventListener("keydown", handleEscape);
      document.removeEventListener("click", handleClick);
    };
  }, [clickedCitationId]);

  // Auto-scroll to first matching citation when filter changes
  useEffect(() => {
    if (!activeFilter || !reportRef.current) return;
    const firstMatch = matched.find(c => c.verdict === activeFilter);
    if (firstMatch) {
      const el = reportRef.current.querySelector(`[data-citation-id="${firstMatch.id}"]`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  }, [activeFilter, matched]);

  return (
    <div className="space-y-4">
      {/* Audit toggle + trust summary */}
      <div className="space-y-3">
        <AuditToggle
          hasAudit={hasAudit}
          auditLoading={auditStatus === "loading"}
          auditInProgress={auditStatus === "in-progress"}
          auditVisible={auditVisible}
          onToggle={handleToggle}
          claimCount={matched.length + unmatched.length}
        />

        <AnimatePresence>
          {auditVisible && stats && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.7, ease: "easeOut" }}
            >
              <TrustSummaryBar
                citations={matched}
                unmatchedCount={unmatched.length}
                activeFilter={activeFilter}
                onFilterChange={setActiveFilter}
              />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Report content with overlay */}
      <div className="relative min-[1440px]:mr-72">
        {/* Scan line animation */}
        <ScanLine
          active={scanActive}
          containerHeight={containerHeight}
          citationPositions={citationYPositions}
          onComplete={handleScanComplete}
        />

        {/* Report + inline citation highlights */}
        <CitationOverlay
          markdown={processedMarkdown}
          citationsByLine={byLine}
          auditVisible={auditVisible}
          activeFilter={activeFilter}
          containerRef={reportRef}
          onBadgeTap={(c) => {
            setClickedCitationId(prev => prev === c.id ? null : c.id);
            setMobileSheet(c);
          }}
          hoveredCitationId={hoveredCitationId}
          onHoverCitation={setHoveredCitationId}
          clickedCitationId={clickedCitationId}
        />

        {/* Gwern sidenotes (>= 1440px) */}
        <Sidenotes
          citations={filteredSidenoteCitations}
          hoveredCitationId={hoveredCitationId}
          clickedCitationId={clickedCitationId}
          onHoverCitation={setHoveredCitationId}
          onClickCitation={handleSidenoteClick}
          reportRef={reportRef}
          visible={auditVisible}
        />
      </div>

      {/* Unmatched citations panel */}
      <AnimatePresence>
        {auditVisible && unmatched.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.3 }}
          >
            <UnmatchedPanel
              citations={unmatched}
              onClickCitation={scrollToLine}
            />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Mobile bottom sheet */}
      <BottomSheet
        citation={mobileSheet}
        onClose={() => setMobileSheet(null)}
      />
    </div>
  );
}
