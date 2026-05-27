"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useSystemStatus, useAnalysisList, useRunAnalysis, useEvolution, useKBInbox } from "@/hooks/use-api";
import { EvolutionTimeline } from "@/components/kb/evolution-timeline";
import { StrataHero } from "@/components/home/strata-hero";
import { SystemPulse } from "@/components/home/system-pulse";
import { RecentAnalyses } from "@/components/home/recent-analyses";

export default function OverviewPage() {
  const { data: status, isLoading } = useSystemStatus();
  const { data: analyses, isLoading: analysesLoading } = useAnalysisList();
  const { data: evolution } = useEvolution();
  const { data: inbox } = useKBInbox();
  const router = useRouter();
  const [ticker, setTicker] = useState("");
  const runAnalysis = useRunAnalysis();

  const handleQuickAnalyze = (e: React.FormEvent) => {
    e.preventDefault();
    const t = ticker.trim().toUpperCase();
    if (!t || !/^[A-Z0-9.\-]{1,15}$/.test(t)) return;
    runAnalysis.mutate({ ticker: t }, {
      onSuccess: (result) => {
        setTicker("");
        router.push(`/analysis/${result.exec_id}`);
      },
    });
  };

  // Relative time helper
  const relativeTime = (iso: string | null | undefined): string => {
    if (!iso) return "";
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  };

  return (
    <div className="space-y-8 max-w-6xl mx-auto">
      {/* Section A: Strata Hero */}
      <StrataHero
        status={status}
        evolution={evolution}
        isLoading={isLoading}
      />

      {/* Section B: Quick Actions + Last Activity */}
      <section className="bg-surface/30 rounded-lg border border-border px-5 py-3">
        <div className="flex flex-col sm:flex-row items-center gap-4">
          {/* Quick analyze form */}
          <form onSubmit={handleQuickAnalyze} className="flex items-center gap-3 flex-1 min-w-0 w-full sm:w-auto">
            <input
              type="text"
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              placeholder="Quick analyze — enter ticker (e.g. AAPL)"
              className="flex-1 h-10 px-4 rounded-lg bg-background border border-border text-text-primary placeholder:text-text-secondary text-sm outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/30 transition-colors"
            />
            <button
              type="submit"
              disabled={runAnalysis.isPending}
              className="h-10 px-5 rounded-lg bg-accent text-background font-medium text-sm hover:bg-accent/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-2 shrink-0"
            >
              {runAnalysis.isPending && (
                <span className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" />
              )}
              {runAnalysis.isPending ? "Starting..." : "Analyze"}
            </button>
          </form>

          {/* Activity chips */}
          <div className="flex items-center gap-3 text-xs text-text-secondary shrink-0">
            {status?.last_digest && (
              <span>Last accretion: {relativeTime(status.last_digest)}</span>
            )}
            {status?.last_analysis && (
              <span>Last analysis: {relativeTime(status.last_analysis)}</span>
            )}
          </div>
        </div>
      </section>

      {/* Section C: System Pulse */}
      <SystemPulse
        status={status}
        evolution={evolution}
        inboxPending={inbox?.unread ?? 0}
        isLoading={isLoading}
      />

      {/* Section D: Layer History */}
      <section>
        <h2 className="text-lg font-semibold text-text-primary mb-4">Layer History</h2>
        <EvolutionTimeline height={180} compact />
      </section>

      {/* Section E: Recent Analyses */}
      <RecentAnalyses analyses={analyses} isLoading={analysesLoading} />
    </div>
  );
}
