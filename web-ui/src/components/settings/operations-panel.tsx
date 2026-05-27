"use client";

import { useRouter } from "next/navigation";
import { useRunDigest, useRunAnalysis } from "@/hooks/use-api";
import { useState } from "react";

export function OperationsPanel() {
  const router = useRouter();
  const digestMutation = useRunDigest();
  const analysisMutation = useRunAnalysis();
  const [ticker, setTicker] = useState("");

  const TICKER_RE = /^[A-Z0-9.\-]{1,15}$/;

  const handleRunDigest = () => {
    digestMutation.mutate(undefined, {
      onSuccess: (data) => {
        // Navigate to KB page where digest replay can be viewed
        router.push("/kb");
      },
    });
  };

  const handleRunAnalysis = (e: React.FormEvent) => {
    e.preventDefault();
    const t = ticker.trim().toUpperCase();
    if (!t || !TICKER_RE.test(t)) return;
    analysisMutation.mutate({ ticker: t }, {
      onSuccess: (result) => {
        setTicker("");
        router.push(`/analysis/${result.exec_id}`);
      },
    });
  };

  return (
    <div className="bg-surface rounded-xl border border-border p-6 space-y-6">
      <h3 className="text-sm font-medium text-text-primary">Operations</h3>

      {/* Run Analysis */}
      <div className="space-y-3">
        <label className="text-xs text-text-secondary">Run Stock Analysis</label>
        <form onSubmit={handleRunAnalysis} className="flex gap-2">
          <input
            type="text"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="TICKER (e.g. AAPL)"
            className="flex-1 h-9 px-3 rounded-lg bg-background border border-border text-text-primary placeholder:text-text-secondary text-sm outline-none focus:border-accent/50 transition-colors font-mono"
          />
          <button
            type="submit"
            disabled={analysisMutation.isPending || !ticker.trim()}
            className="h-9 px-4 rounded-lg bg-accent text-background font-medium text-sm hover:bg-accent/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-2"
          >
            {analysisMutation.isPending && (
              <span className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" />
            )}
            {analysisMutation.isPending ? "Starting..." : "Analyze"}
          </button>
        </form>
        {analysisMutation.isSuccess && (
          <p className="text-xs text-positive">
            Analysis started — redirecting to pipeline view...
          </p>
        )}
        {analysisMutation.isError && (
          <p className="text-xs text-negative">
            Failed: {analysisMutation.error.message}
          </p>
        )}
      </div>

      {/* Run Digest */}
      <div className="space-y-3">
        <label className="text-xs text-text-secondary">Run Knowledge Digest</label>
        <div className="flex items-center gap-3">
          <button
            onClick={handleRunDigest}
            disabled={digestMutation.isPending}
            className="h-9 px-4 rounded-lg bg-emerald-600 text-white font-medium text-sm hover:bg-emerald-500 transition-colors disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-2"
          >
            {digestMutation.isPending && (
              <span className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" />
            )}
            {digestMutation.isPending ? "Processing..." : "Run Digest"}
          </button>
          {digestMutation.isPending && (
            <span className="text-xs text-text-secondary animate-pulse">
              Processing inbox articles into knowledge base...
            </span>
          )}
        </div>
        {digestMutation.isSuccess && (
          <p className="text-xs text-positive">
            Digest started — redirecting to Knowledge Base...
          </p>
        )}
        {digestMutation.isError && (
          <p className="text-xs text-negative">
            Digest failed: {digestMutation.error.message}
          </p>
        )}
      </div>
    </div>
  );
}
