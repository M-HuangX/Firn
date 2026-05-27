"use client";

// ─── Stock Knowledge Card ───────────────────────────────────────────────────
// Renders a rich card for a tracked stock showing knowledge depth,
// per-file breakdown, and connected theme tags.

interface StockCardProps {
  ticker: string;
  file_chars: Record<string, number>;
  total_chars: number;
  connected_themes: string[];
  maxTotalChars: number;
}

function formatChars(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

function humanize(slug: string): string {
  return slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function StockCard({
  ticker,
  file_chars,
  total_chars,
  connected_themes,
  maxTotalChars,
}: StockCardProps) {
  // Sort files by char count descending
  const sortedFiles = Object.entries(file_chars ?? {}).sort(([, a], [, b]) => b - a);
  const maxFileChars = sortedFiles.length > 0 ? sortedFiles[0][1] : 1;
  const depthPct = maxTotalChars > 0 ? (total_chars / maxTotalChars) * 100 : 0;

  return (
    <div className="bg-surface rounded-xl border border-border p-4 hover:border-accent/30 transition-colors"
      style={{ borderLeftWidth: 3, borderLeftColor: "#10B981" }}
    >
      {/* Header: green dot + ticker + total chars */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" />
          <span className="font-mono font-semibold text-text-primary text-sm">
            {ticker}
          </span>
        </div>
        <span className="text-xs font-mono text-text-secondary">
          {formatChars(total_chars)}
        </span>
      </div>

      {/* Knowledge Depth bar */}
      <div className="h-1.5 rounded-full bg-slate-800 mb-3">
        <div
          className="h-full rounded-full"
          style={{
            width: `${depthPct}%`,
            background: "linear-gradient(90deg, #10B981, #059669)",
          }}
        />
      </div>

      {/* Per-file breakdown */}
      {sortedFiles.length > 0 && (
        <div className="space-y-1.5 mb-3">
          {sortedFiles.map(([file, chars]) => {
            const filePct =
              maxFileChars > 0 ? (chars / maxFileChars) * 100 : 0;
            return (
              <div key={file} className="flex items-center gap-2">
                <span className="text-[11px] text-text-secondary truncate min-w-0 w-24 shrink-0">
                  {humanize(file)}
                </span>
                <div className="flex-1 h-1 rounded-full bg-slate-800">
                  <div
                    className="h-full rounded-full bg-slate-500"
                    style={{ width: `${filePct}%` }}
                  />
                </div>
                <span className="text-[10px] text-text-secondary font-mono shrink-0 w-10 text-right">
                  {formatChars(chars)}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Connected theme tags */}
      {connected_themes.length > 0 && (
        <div className="flex flex-wrap gap-1 pt-1 border-t border-border/50">
          {connected_themes.map((slug) => (
            <span
              key={slug}
              className="inline-flex bg-cyan-500/10 text-cyan-400 text-[10px] rounded-md px-1.5 py-0.5"
            >
              {humanize(slug)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
