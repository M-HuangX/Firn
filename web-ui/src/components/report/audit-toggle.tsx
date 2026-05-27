"use client";

import { cn } from "@/lib/utils";

interface AuditToggleProps {
  hasAudit: boolean;
  auditLoading?: boolean;
  auditInProgress?: boolean;
  auditVisible: boolean;
  onToggle: () => void;
  claimCount: number;
}

/**
 * "View Audit" / "Hide Audit" toggle button.
 * Audit is shown by default — this lets users hide/re-show it.
 */
export function AuditToggle({
  hasAudit,
  auditLoading,
  auditInProgress,
  auditVisible,
  onToggle,
  claimCount,
}: AuditToggleProps) {
  if (auditInProgress) {
    return (
      <div className="flex items-center gap-2 text-xs text-amber-400/80 bg-amber-950/20 border border-amber-500/20 rounded-lg px-3 py-2">
        <span className="w-3 h-3 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
        Audit in progress — annotations will appear when complete
      </div>
    );
  }

  if (auditLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-text-secondary bg-background border border-border rounded-lg px-3 py-2">
        <span className="w-3 h-3 border-2 border-accent border-t-transparent rounded-full animate-spin" />
        Loading audit data...
      </div>
    );
  }

  if (!hasAudit) {
    return null; // No audit exists — don't show anything misleading
  }

  return (
    <button
      onClick={onToggle}
      className={cn(
        "flex items-center gap-2 text-xs font-medium rounded-lg px-3 py-2 transition-all",
        auditVisible
          ? "bg-accent/10 text-accent border border-accent/30 hover:bg-accent/15"
          : "bg-surface border border-border text-text-secondary hover:text-text-primary hover:border-accent/30"
      )}
    >
      <svg
        className="w-3.5 h-3.5"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2}
      >
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z" />
      </svg>
      {auditVisible ? "Hide Audit" : `View Audit (${claimCount} claims)`}
    </button>
  );
}
