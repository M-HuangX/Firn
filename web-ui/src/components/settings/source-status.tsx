"use client";

import { useSources, useRefreshSources } from "@/hooks/use-api";
import { Skeleton } from "@/components/ui/skeleton";

const TIER_COLORS: Record<number, string> = {
  1: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  2: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  3: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  4: "bg-orange-500/15 text-orange-400 border-orange-500/30",
  5: "bg-red-500/15 text-red-400 border-red-500/30",
};

function TierBadge({ tier }: { tier: number | null }) {
  if (tier === null) {
    return <span className="text-xs text-text-secondary">--</span>;
  }
  const colorClass = TIER_COLORS[tier] ?? "bg-surface text-text-secondary border-border";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${colorClass}`}>
      T{tier}
    </span>
  );
}

export function SourceStatus() {
  const { data, isLoading, error } = useSources();
  const refreshMutation = useRefreshSources();

  if (isLoading) {
    return <Skeleton variant="card" className="h-48" />;
  }

  if (error) {
    return (
      <div className="bg-surface rounded-xl border border-border p-6">
        <p className="text-sm text-negative">Failed to load sources: {error.message}</p>
      </div>
    );
  }

  const sources = data?.sources ?? [];

  return (
    <div className="space-y-3">
      <div className="bg-surface rounded-xl border border-border overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left px-4 py-3 text-text-secondary font-medium">Source</th>
              <th className="text-left px-4 py-3 text-text-secondary font-medium">Tier</th>
              <th className="text-left px-4 py-3 text-text-secondary font-medium">Bias</th>
              <th className="text-left px-4 py-3 text-text-secondary font-medium">Last Updated</th>
              <th className="text-right px-4 py-3 text-text-secondary font-medium">New Articles</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
              <tr key={source.name} className="border-b border-border last:border-b-0">
                <td className="px-4 py-3 text-text-primary">{source.name}</td>
                <td className="px-4 py-3">
                  <TierBadge tier={source.tier} />
                </td>
                <td className="px-4 py-3 text-text-secondary">{source.bias ?? "--"}</td>
                <td className="px-4 py-3 text-text-secondary">
                  {source.last_updated
                    ? new Date(source.last_updated).toLocaleString()
                    : "--"}
                </td>
                <td className="px-4 py-3 text-right font-mono text-text-primary">
                  {source.new_count}
                </td>
              </tr>
            ))}
            {sources.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-text-secondary text-sm">
                  No sources configured
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <button
        onClick={() => refreshMutation.mutate()}
        disabled={refreshMutation.isPending}
        className="h-9 px-4 rounded-lg border border-border text-sm text-text-secondary hover:text-accent hover:border-accent/50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-2"
      >
        {refreshMutation.isPending && (
          <span className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" />
        )}
        {refreshMutation.isPending ? "Refreshing..." : "Refresh Sources"}
      </button>

      {refreshMutation.isSuccess && (
        <p className="text-xs text-positive">
          Refresh started (exec_id: {refreshMutation.data?.exec_id})
        </p>
      )}
      {refreshMutation.isError && (
        <p className="text-xs text-negative">
          Refresh failed: {refreshMutation.error.message}
        </p>
      )}
    </div>
  );
}
