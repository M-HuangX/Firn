"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { StatusBadge } from "@/components/ui/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { AnalysisMeta } from "@/lib/types";

interface RecentAnalysesProps {
  analyses: AnalysisMeta[] | undefined;
  isLoading: boolean;
}

function formatDuration(startedAt: string | null, completedAt: string | null): string | null {
  if (!startedAt || !completedAt) return null;
  const durationS = Math.round(
    (new Date(completedAt).getTime() - new Date(startedAt).getTime()) / 1000
  );
  if (durationS < 0) return null;
  if (durationS > 120) {
    const m = Math.floor(durationS / 60);
    const s = durationS % 60;
    return `${m}m ${s}s`;
  }
  return `${durationS}s`;
}

function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return "";
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffMs = now - then;
  if (diffMs < 0) return "just now";
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function RecentAnalyses({ analyses, isLoading }: RecentAnalysesProps) {
  const router = useRouter();
  const recent = analyses?.slice(0, 5);

  return (
    <section>
      <h2 className="text-lg font-semibold text-text-primary mb-4">
        Recent Analyses
      </h2>

      {isLoading ? (
        <div className="divide-y divide-border">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex items-center gap-4 px-4 py-3">
              <Skeleton variant="text" className="w-16 h-5" />
              <Skeleton variant="text" className="w-20 h-5" />
              <Skeleton variant="text" className="w-14 h-4" />
              <Skeleton variant="text" className="w-10 h-4" />
              <Skeleton variant="text" className="w-12 h-4" />
            </div>
          ))}
        </div>
      ) : recent && recent.length > 0 ? (
        <div className="divide-y divide-border">
          {recent.map((a) => {
            const duration = formatDuration(a.started_at, a.completed_at);
            const relTime = formatRelativeTime(a.started_at);

            return (
              <div
                key={a.exec_id}
                onClick={() => router.push(`/analysis/${a.exec_id}`)}
                className="flex items-center gap-4 px-4 py-3 hover:bg-surface/50 cursor-pointer transition-colors rounded-lg"
              >
                {/* Ticker */}
                <span className="font-mono font-bold text-text-primary w-16 shrink-0">
                  {a.ticker ?? "\u2014"}
                </span>

                {/* Status */}
                <StatusBadge variant={a.status} />

                {/* Audit badge */}
                <span className="w-16 shrink-0">
                  {a.has_audit ? (
                    <span className="text-[10px] text-text-secondary bg-surface border border-border rounded px-1.5 py-0.5">
                      Audited
                    </span>
                  ) : null}
                </span>

                {/* Duration */}
                <span className="text-xs text-text-secondary font-mono w-14 shrink-0 text-right">
                  {duration ?? "\u2014"}
                </span>

                {/* Relative time */}
                <span className="text-xs text-text-secondary w-14 shrink-0 text-right">
                  {relTime}
                </span>

                {/* Chevron */}
                <svg
                  className="text-text-secondary w-4 h-4 shrink-0 ml-auto"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-sm text-text-secondary">
          No analyses yet. Run one from the quick analyze bar above.
        </p>
      )}

      {recent && recent.length > 0 && (
        <Link
          href="/analysis"
          className="text-sm text-accent hover:text-accent/80 mt-3 inline-block"
        >
          View all analyses &rarr;
        </Link>
      )}
    </section>
  );
}
