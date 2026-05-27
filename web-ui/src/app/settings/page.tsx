"use client";

import { useAuth } from "@/hooks/use-auth";
import { useSystemStatus } from "@/hooks/use-api";
import { Skeleton } from "@/components/ui/skeleton";
import { WatchlistEditor } from "@/components/settings/watchlist-editor";
import { SourceStatus } from "@/components/settings/source-status";
import { OperationsPanel } from "@/components/settings/operations-panel";

function SystemInfo() {
  const { data, isLoading } = useSystemStatus();

  if (isLoading || !data) {
    return <Skeleton variant="card" className="h-48" />;
  }

  const rows: [string, string][] = [
    ["Day", `Day ${data.day_n}`],
    ["LLM Provider", data.llm_provider ?? "N/A"],
    ["Total Articles", String(data.total_articles)],
    ["Total Themes", String(data.total_themes)],
    ["Total Stocks", String(data.total_stocks)],
    ["Total Events", String(data.total_events)],
    ["Core Mind", `${data.core_mind_chars.toLocaleString()} chars`],
    ["Library Unread", String(data.library_unread)],
    ["Library Read", String(data.library_read)],
    ["Last Digest", data.last_digest ?? "Never"],
    ["Last Analysis", data.last_analysis ?? "Never"],
  ];

  return (
    <div className="bg-surface rounded-xl border border-border p-6 space-y-1">
      {rows.map(([label, value]) => (
        <div key={label} className="flex items-center justify-between py-2 border-b border-border last:border-b-0">
          <span className="text-sm text-text-secondary">{label}</span>
          <span className="text-sm font-mono text-text-primary">{value}</span>
        </div>
      ))}
    </div>
  );
}

export default function SettingsPage() {
  const { isAdmin, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="space-y-8 max-w-7xl mx-auto">
        <Skeleton variant="card" className="h-48" />
        <Skeleton variant="card" className="h-48" />
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center space-y-3">
          <div className="w-12 h-12 rounded-xl bg-negative/10 flex items-center justify-center mx-auto">
            <svg className="w-6 h-6 text-negative" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
            </svg>
          </div>
          <p className="text-text-secondary text-sm">
            Admin access required
          </p>
          <p className="text-text-secondary text-xs">
            Please sign in as admin to access settings.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 max-w-7xl mx-auto">
      {/* Watchlist Editor */}
      <section>
        <h2 className="text-xl font-semibold text-text-primary mb-4">
          Watchlist
        </h2>
        <p className="text-sm text-text-secondary mb-4">
          Manage tracked tickers for automatic analysis and digest
        </p>
        <WatchlistEditor />
      </section>

      {/* Source Status */}
      <section>
        <h2 className="text-xl font-semibold text-text-primary mb-4">
          Data Sources
        </h2>
        <SourceStatus />
      </section>

      {/* Operations */}
      <section>
        <h2 className="text-xl font-semibold text-text-primary mb-4">
          Operations
        </h2>
        <OperationsPanel />
      </section>

      {/* System Info */}
      <section>
        <h2 className="text-xl font-semibold text-text-primary mb-4">
          System Info
        </h2>
        <SystemInfo />
      </section>
    </div>
  );
}
