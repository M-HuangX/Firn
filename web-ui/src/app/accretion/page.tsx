"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { useDigestList } from "@/hooks/use-api";
import { Skeleton } from "@/components/ui/skeleton";
import type { DigestMeta } from "@/lib/types";

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || isNaN(seconds)) return "--";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "Unknown date";
  return new Date(dateStr).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function StatusDot({ status }: { status: DigestMeta["status"] }) {
  const colors = {
    complete: "bg-positive",
    running: "bg-amber-400",
    failed: "bg-negative",
    unknown: "bg-text-secondary",
  };
  return (
    <span
      className={`w-2 h-2 rounded-full inline-block ${colors[status] ?? colors.unknown}`}
    />
  );
}

export default function AccretionPage() {
  const router = useRouter();
  const { data: digests, isLoading } = useDigestList();

  // Compute max KB chars for density bar scaling
  const maxChars = useMemo(() => {
    if (!digests || digests.length === 0) return 1;
    return Math.max(...digests.map((d) => d.total_kb_chars_written ?? 0), 1);
  }, [digests]);

  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto space-y-4">
        <div className="mb-6">
          <Skeleton variant="text" className="w-48 h-7" />
          <Skeleton variant="text" className="w-72 h-4 mt-2" />
        </div>
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} variant="card" className="h-28" />
        ))}
      </div>
    );
  }

  if (!digests || digests.length === 0) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="mb-6">
          <h1 className="text-lg font-semibold text-text-primary">
            Accretion History
          </h1>
          <p className="text-sm text-text-secondary mt-1">
            No layers yet. Run an accretion session to begin building knowledge.
          </p>
        </div>
        <div className="bg-surface rounded-xl border border-border p-12 flex items-center justify-center text-text-secondary text-sm">
          Layer 1 forming...
        </div>
      </div>
    );
  }

  const totalLayers = digests.length;

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-lg font-semibold text-text-primary">
          Accretion History
        </h1>
        <p className="text-sm text-text-secondary mt-1">
          {totalLayers} layer{totalLayers !== 1 ? "s" : ""} of accumulated
          knowledge
        </p>
      </div>

      <div className="space-y-3">
        {digests.map((digest, index) => {
          const layerNum = totalLayers - index;
          const opacity = Math.max(0.6, 1 - index * 0.04);
          const densityWidth =
            maxChars > 0
              ? ((digest.total_kb_chars_written ?? 0) / maxChars) * 100
              : 0;

          // Summarize changes
          const changes: string[] = [];
          const themeCount = (digest.themes_added ?? 0) + (digest.themes_updated ?? 0);
          if (themeCount > 0) changes.push(`+${themeCount} themes`);
          const stockCount = (digest.stocks_added ?? 0) + (digest.stocks_updated ?? 0);
          if (stockCount > 0) changes.push(`+${stockCount} stocks`);
          const ea = digest.events_added ?? 0;
          if (ea > 0) changes.push(`+${ea} events`);
          if (digest.core_mind_updated) changes.push("core mind");

          return (
            <button
              key={digest.exec_id}
              onClick={() => router.push(`/accretion/${digest.exec_id}`)}
              className="w-full text-left bg-surface rounded-xl border border-border hover:border-accent/30 p-5 cursor-pointer group"
              style={{
                opacity,
                transition: "all 350ms cubic-bezier(0.22, 1, 0.36, 1)",
              }}
            >
              {/* Top row: layer + date + status */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-3">
                  <span className="text-base font-semibold text-text-primary">
                    Layer {layerNum}
                  </span>
                  <span className="text-xs text-text-secondary">
                    {formatDate(digest.started_at)}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <StatusDot status={digest.status} />
                  <span className="text-xs text-text-secondary capitalize">
                    {digest.status}
                  </span>
                </div>
              </div>

              {/* Stats row */}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-secondary mb-3">
                <span className="font-mono">
                  {digest.articles_processed} articles
                </span>
                {changes.map((c, ci) => (
                  <span key={ci} className="font-mono">
                    {c}
                  </span>
                ))}
                {(digest.total_kb_chars_written ?? 0) > 0 && (
                  <span className="font-mono">
                    +{(digest.total_kb_chars_written ?? 0).toLocaleString()} chars
                  </span>
                )}
                <span className="font-mono">
                  {formatDuration(digest.duration_s)}
                </span>
              </div>

              {/* Density bar */}
              <div className="h-1 bg-border/30 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full bg-accent/40 group-hover:bg-accent/60"
                  style={{
                    width: `${densityWidth}%`,
                    transition: "width 500ms cubic-bezier(0.22, 1, 0.36, 1)",
                  }}
                />
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
