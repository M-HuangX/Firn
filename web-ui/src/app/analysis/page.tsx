"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAnalysisList, useRunAnalysis } from "@/hooks/use-api";
import { StatusBadge } from "@/components/ui/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";

export default function AnalysisListPage() {
  const router = useRouter();
  const { data: analyses, isLoading, error } = useAnalysisList();
  const runAnalysis = useRunAnalysis();

  const [showDialog, setShowDialog] = useState(false);
  const [tickerInput, setTickerInput] = useState("");

  const TICKER_RE = /^[A-Z0-9.\-]{1,15}$/;

  const handleRunAnalysis = (e: React.FormEvent) => {
    e.preventDefault();
    const t = tickerInput.trim().toUpperCase();
    if (!t || !TICKER_RE.test(t)) return;
    runAnalysis.mutate({ ticker: t }, {
      onSuccess: (result) => {
        setShowDialog(false);
        setTickerInput("");
        router.push(`/analysis/${result.exec_id}`);
      },
    });
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-text-primary">
            Analysis History
          </h2>
          <p className="text-sm text-text-secondary mt-1">
            All stock analyses and their results
          </p>
        </div>
        <button
          onClick={() => setShowDialog(true)}
          className="h-9 px-4 rounded-lg bg-accent text-background font-medium text-sm hover:bg-accent/90 transition-colors"
        >
          Run Analysis
        </button>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} variant="card" className="h-32" />
          ))}
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="bg-surface rounded-xl border border-border p-6 text-center">
          <p className="text-sm text-negative">Failed to load analyses: {error.message}</p>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && analyses && analyses.length === 0 && (
        <div className="bg-surface rounded-xl border border-border">
          <EmptyState
            title="No analyses yet"
            description="Click &quot;Run Analysis&quot; to start your first stock analysis."
          />
        </div>
      )}

      {/* Grid of analysis cards */}
      {!isLoading && analyses && analyses.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {analyses.map((analysis) => (
            <div
              key={analysis.exec_id}
              onClick={() => router.push(`/analysis/${analysis.exec_id}`)}
              className="bg-surface rounded-xl border border-border p-4 hover:border-accent/30 transition-colors cursor-pointer group"
            >
              <div className="flex items-center justify-between mb-3">
                <span className="font-mono font-bold text-lg text-text-primary group-hover:text-accent transition-colors">
                  {analysis.ticker ?? "—"}
                </span>
                <StatusBadge variant={analysis.status} />
              </div>

              <div className="flex items-center justify-between">
                <span className="text-xs text-text-secondary">
                  {analysis.started_at
                    ? new Date(analysis.started_at).toLocaleString()
                    : "—"}
                </span>
                <div className="flex items-center gap-2">
                  {analysis.started_at && analysis.completed_at && (
                    <span className="text-xs text-text-secondary font-mono">
                      {Math.round((new Date(analysis.completed_at).getTime() - new Date(analysis.started_at).getTime()) / 1000)}s
                    </span>
                  )}
                  {analysis.has_audit && (
                    <span className="text-xs text-positive border border-positive/30 rounded px-1.5 py-0.5">
                      Audited
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Run Analysis Dialog */}
      {showDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setShowDialog(false)}
          />
          <div className="relative bg-surface border border-border rounded-xl p-6 w-full max-w-sm mx-4">
            <h3 className="text-lg font-semibold text-text-primary mb-4">
              Run Analysis
            </h3>
            <form onSubmit={handleRunAnalysis}>
              <input
                type="text"
                value={tickerInput}
                onChange={(e) => setTickerInput(e.target.value)}
                placeholder="Enter ticker symbol (e.g. AAPL)"
                autoFocus
                className="w-full h-11 px-4 rounded-lg bg-background border border-border text-text-primary placeholder:text-text-secondary text-sm outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/30 transition-colors"
              />
              {runAnalysis.isError && (
                <p className="text-xs text-negative mt-2">{runAnalysis.error.message}</p>
              )}
              <div className="flex gap-3 mt-4">
                <button
                  type="button"
                  onClick={() => setShowDialog(false)}
                  className="flex-1 h-10 rounded-lg border border-border text-text-secondary text-sm hover:text-text-primary hover:border-text-secondary/50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={runAnalysis.isPending}
                  className="flex-1 h-10 rounded-lg bg-accent text-background font-medium text-sm hover:bg-accent/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center justify-center gap-2"
                >
                  {runAnalysis.isPending && (
                    <span className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" />
                  )}
                  {runAnalysis.isPending ? "Starting..." : "Start"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
