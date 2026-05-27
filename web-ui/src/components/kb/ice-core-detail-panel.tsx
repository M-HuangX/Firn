"use client";

import { useCallback, useState } from "react";
import {
  useKBInbox,
  useKBEvents,
  useKBEventDetail,
  useKBThemes,
  useKBThemeDetail,
  useKBStocks,
  useKBStockDetail,
  useKBCoreMind,
  useMaturation,
} from "@/hooks/use-api";
import { StockCard } from "./stock-card";
import { CoreMindDiff } from "./core-mind-diff";
import { EmptyState } from "@/components/ui/empty-state";
import type { MaturationItem } from "@/lib/types";

// ─── Props ────────────────────────────────────────────────────────────────────

interface IceCoreDetailPanelProps {
  selectedStratum: string; // "inbox" | "events" | "themes" | "stocks" | "core_mind"
  selectedItemId: string | null; // null = show list, non-null = show detail
  onSelectItem: (id: string | null) => void; // null to go back to list
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function getMaturationTier(
  maturationItems: MaturationItem[],
  itemType: string,
  itemId: string,
): "snow" | "firn" | "ice" {
  const item = maturationItems.find(
    (m) => m.item_type === itemType && m.item_id === `${itemType}:${itemId}`,
  );
  return item?.tier ?? "snow";
}

function maturationCssClass(tier: "snow" | "firn" | "ice"): string {
  return `firn-${tier}`;
}

function humanize(slug: string): string {
  return slug
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// ─── Maturation Badge ─────────────────────────────────────────────────────────

function MaturationBadge({ tier }: { tier: "snow" | "firn" | "ice" }) {
  const colors: Record<string, string> = {
    snow: "bg-slate-400",
    firn: "bg-cyan-400",
    ice: "bg-violet-400",
  };
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full shrink-0 ${colors[tier]}`}
      title={`Maturation: ${tier}`}
    />
  );
}

// ─── Back Breadcrumb ──────────────────────────────────────────────────────────

function BackBreadcrumb({
  stratumLabel,
  onBack,
}: {
  stratumLabel: string;
  onBack: () => void;
}) {
  return (
    <button
      onClick={onBack}
      className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors mb-4 group"
    >
      <svg
        className="w-3.5 h-3.5 group-hover:-translate-x-0.5 transition-transform duration-200"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2}
      >
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
      </svg>
      Back to {stratumLabel}
    </button>
  );
}

// ─── Loading / Empty ──────────────────────────────────────────────────────────

function LoadingState() {
  return (
    <div className="flex items-center justify-center py-12">
      <div className="text-text-secondary text-sm">Loading...</div>
    </div>
  );
}


// ─── Inbox Stratum ────────────────────────────────────────────────────────────

function InboxView() {
  const { data: inbox, isLoading } = useKBInbox();

  if (isLoading) return <LoadingState />;
  if (!inbox) return <EmptyState title="No library data yet" />;

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-text-primary">Library Status</h3>
      <div className="flex gap-4">
        {/* Unread — snow-styled */}
        <div className="firn-snow flex-1 rounded-xl border border-border p-5 transition-all duration-300">
          <div className="text-2xl font-mono font-semibold text-text-primary">
            {inbox.unread}
          </div>
          <div className="text-xs text-text-secondary mt-1">
            Unread articles
          </div>
          <div className="text-[10px] text-text-secondary/60 mt-2">
            Fresh, unprocessed snow
          </div>
        </div>
        {/* Read */}
        <div className="flex-1 bg-surface rounded-xl border border-border p-5 transition-all duration-300">
          <div className="text-2xl font-mono font-semibold text-text-primary">
            {inbox.read}
          </div>
          <div className="text-xs text-text-secondary mt-1">
            Read articles
          </div>
          <div className="text-[10px] text-text-secondary/60 mt-2">
            Compacted into knowledge
          </div>
        </div>
      </div>
      {inbox.unread === 0 && inbox.read === 0 && (
        <p className="text-xs text-text-secondary text-center mt-4">
          No articles in the library. Add sources and refresh to start collecting.
        </p>
      )}
    </div>
  );
}

// ─── Events Stratum ───────────────────────────────────────────────────────────

function EventsListView({
  maturationItems,
  onSelectItem,
}: {
  maturationItems: MaturationItem[];
  onSelectItem: (id: string) => void;
}) {
  const { data: events, isLoading } = useKBEvents();

  if (isLoading) return <LoadingState />;
  if (!events || events.length === 0)
    return <EmptyState title="No events yet" />;

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-text-primary">
        Events
        <span className="text-xs font-normal text-text-secondary ml-2">
          ({events.length})
        </span>
      </h3>
      <div className="space-y-2">
        {events.map((event) => {
          const tier = getMaturationTier(maturationItems, "event", event.slug);
          return (
            <button
              key={event.slug}
              onClick={() => onSelectItem(event.slug)}
              className={`w-full text-left rounded-xl border border-border p-4 hover:border-accent/30 transition-all duration-300 cursor-pointer ${maturationCssClass(tier)}`}
            >
              <div className="flex items-center gap-2 mb-1">
                <MaturationBadge tier={tier} />
                <span className="text-sm font-medium text-text-primary">
                  {humanize(event.slug)}
                </span>
              </div>
              {event.preview && (
                <p className="text-xs text-text-secondary line-clamp-2 ml-4">
                  {event.preview}
                </p>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function EventDetailView({
  slug,
  onBack,
}: {
  slug: string;
  onBack: () => void;
}) {
  const { data, isLoading } = useKBEventDetail(slug);

  return (
    <div>
      <BackBreadcrumb stratumLabel="Events" onBack={onBack} />
      <h3 className="text-sm font-semibold text-text-primary mb-3">
        {humanize(slug)}
      </h3>
      {isLoading ? (
        <LoadingState />
      ) : !data?.content ? (
        <EmptyState title="No event content." />
      ) : (
        <div className="bg-surface rounded-xl border border-border p-4">
          <pre className="text-xs font-mono text-text-primary whitespace-pre-wrap leading-relaxed max-h-[600px] overflow-y-auto scrollbar-thin">
            {data.content}
          </pre>
        </div>
      )}
    </div>
  );
}

// ─── Themes Stratum ───────────────────────────────────────────────────────────

function ThemesListView({
  maturationItems,
  onSelectItem,
}: {
  maturationItems: MaturationItem[];
  onSelectItem: (id: string) => void;
}) {
  const { data: themes, isLoading } = useKBThemes();

  if (isLoading) return <LoadingState />;
  if (!themes || themes.length === 0)
    return <EmptyState title="No themes yet" />;

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-text-primary">
        Themes
        <span className="text-xs font-normal text-text-secondary ml-2">
          ({themes.length})
        </span>
      </h3>
      <div className="space-y-2">
        {themes.map((theme) => {
          const tier = getMaturationTier(maturationItems, "theme", theme.slug);
          return (
            <button
              key={theme.slug}
              onClick={() => onSelectItem(theme.slug)}
              className={`w-full text-left rounded-xl border border-border p-4 hover:border-accent/30 transition-all duration-300 cursor-pointer ${maturationCssClass(tier)}`}
            >
              <div className="flex items-center gap-2 mb-1">
                <MaturationBadge tier={tier} />
                <span className="text-sm font-medium text-text-primary">
                  {humanize(theme.slug)}
                </span>
              </div>
              {theme.preview && (
                <p className="text-xs text-text-secondary line-clamp-2 ml-4">
                  {theme.preview}
                </p>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ThemeDetailView({
  slug,
  onBack,
}: {
  slug: string;
  onBack: () => void;
}) {
  const { data, isLoading } = useKBThemeDetail(slug);

  return (
    <div>
      <BackBreadcrumb stratumLabel="Themes" onBack={onBack} />
      <h3 className="text-sm font-semibold text-text-primary mb-3">
        {humanize(slug)}
      </h3>
      {isLoading ? (
        <LoadingState />
      ) : !data?.content ? (
        <EmptyState title="No theme content." />
      ) : (
        <div className="bg-surface rounded-xl border border-border p-4">
          <pre className="text-xs font-mono text-text-primary whitespace-pre-wrap leading-relaxed max-h-[600px] overflow-y-auto scrollbar-thin">
            {data.content}
          </pre>
        </div>
      )}
    </div>
  );
}

// ─── Stocks Stratum ───────────────────────────────────────────────────────────

function StocksListView({
  maturationItems,
  onSelectItem,
}: {
  maturationItems: MaturationItem[];
  onSelectItem: (id: string) => void;
}) {
  const { data: stocks, isLoading } = useKBStocks();

  if (isLoading) return <LoadingState />;
  if (!stocks || stocks.length === 0)
    return <EmptyState title="No tracked stocks yet" />;

  const maxTotalChars = Math.max(...stocks.map((s) => s.total_chars), 1);

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-text-primary">
        Tracked Stocks
        <span className="text-xs font-normal text-text-secondary ml-2">
          ({stocks.length})
        </span>
      </h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {stocks.map((stock) => {
          const tier = getMaturationTier(
            maturationItems,
            "stock",
            stock.ticker,
          );
          return (
            <button
              key={stock.ticker}
              onClick={() => onSelectItem(stock.ticker)}
              className={`text-left rounded-xl transition-all duration-300 cursor-pointer ${maturationCssClass(tier)}`}
              style={{ borderLeft: 'none' }}
            >
              <StockCard
                ticker={stock.ticker}
                file_chars={stock.file_chars}
                total_chars={stock.total_chars}
                connected_themes={stock.connected_themes}
                maxTotalChars={maxTotalChars}
              />
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StockDetailView({
  ticker,
  onBack,
}: {
  ticker: string;
  onBack: () => void;
}) {
  const { data, isLoading } = useKBStockDetail(ticker);
  const [expandedFile, setExpandedFile] = useState<string | null>(null);

  const toggleFile = useCallback(
    (fileName: string) => {
      setExpandedFile((prev) => (prev === fileName ? null : fileName));
    },
    [],
  );

  return (
    <div>
      <BackBreadcrumb stratumLabel="Stocks" onBack={onBack} />
      <h3 className="text-sm font-semibold text-text-primary mb-3 flex items-center gap-2">
        <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 shrink-0" />
        {ticker}
      </h3>
      {isLoading ? (
        <LoadingState />
      ) : !data?.files || Object.keys(data.files).length === 0 ? (
        <EmptyState title="No stock data files." />
      ) : (
        <div className="space-y-1">
          {Object.entries(data.files).map(([fileName, content]) => {
            const isExpanded = expandedFile === fileName;
            return (
              <div
                key={fileName}
                className="border border-border rounded-lg overflow-hidden"
              >
                <button
                  onClick={() => toggleFile(fileName)}
                  className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-white/[0.02] transition-colors"
                >
                  <span className="text-xs font-medium text-text-primary">
                    {humanize(fileName)}
                  </span>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-text-secondary font-mono">
                      {content.length >= 1000
                        ? `${(content.length / 1000).toFixed(1)}K`
                        : content.length}
                    </span>
                    <svg
                      className={`w-3.5 h-3.5 text-text-secondary transition-transform duration-200 ${
                        isExpanded ? "rotate-180" : ""
                      }`}
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M19 9l-7 7-7-7"
                      />
                    </svg>
                  </div>
                </button>
                {isExpanded && (
                  <div className="px-3 pb-3 border-t border-border">
                    <pre className="text-xs font-mono text-text-primary whitespace-pre-wrap leading-relaxed mt-2 max-h-[300px] overflow-y-auto scrollbar-thin">
                      {content}
                    </pre>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Core Mind Stratum ────────────────────────────────────────────────────────

function CoreMindView() {
  const { data: coreMind, isLoading } = useKBCoreMind();

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-text-primary">Core Mind</h3>
        {coreMind?.content && (
          <span className="text-[10px] text-text-secondary font-mono">
            {coreMind.content.length.toLocaleString()} chars
          </span>
        )}
      </div>

      {/* Current core mind content with violet/ice border */}
      <div className="firn-ice rounded-xl border border-violet-500/30 p-4">
        {isLoading ? (
          <LoadingState />
        ) : coreMind?.content ? (
          <pre className="text-xs font-mono text-text-primary whitespace-pre-wrap leading-relaxed max-h-[300px] overflow-y-auto scrollbar-thin">
            {coreMind.content}
          </pre>
        ) : (
          <p className="text-xs text-text-secondary">
            No core mind content yet. Core Mind will be synthesized after digesting articles.
          </p>
        )}
      </div>

      {/* Snapshot diff comparison */}
      <div className="pt-2">
        <h4 className="text-xs font-medium text-text-secondary mb-3">
          Snapshot History
        </h4>
        <CoreMindDiff />
      </div>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export function IceCoreDetailPanel({
  selectedStratum,
  selectedItemId,
  onSelectItem,
}: IceCoreDetailPanelProps) {
  const { data: maturationData } = useMaturation();
  const maturationItems = maturationData?.items ?? [];

  const handleBack = useCallback(() => {
    onSelectItem(null);
  }, [onSelectItem]);

  return (
    <div className="flex-1 min-w-0 overflow-y-auto transition-all duration-300">
      {/* Inbox */}
      {selectedStratum === "inbox" && <InboxView />}

      {/* Events */}
      {selectedStratum === "events" &&
        (selectedItemId ? (
          <EventDetailView slug={selectedItemId} onBack={handleBack} />
        ) : (
          <EventsListView
            maturationItems={maturationItems}
            onSelectItem={onSelectItem}
          />
        ))}

      {/* Themes */}
      {selectedStratum === "themes" &&
        (selectedItemId ? (
          <ThemeDetailView slug={selectedItemId} onBack={handleBack} />
        ) : (
          <ThemesListView
            maturationItems={maturationItems}
            onSelectItem={onSelectItem}
          />
        ))}

      {/* Stocks */}
      {selectedStratum === "stocks" &&
        (selectedItemId ? (
          <StockDetailView ticker={selectedItemId} onBack={handleBack} />
        ) : (
          <StocksListView
            maturationItems={maturationItems}
            onSelectItem={onSelectItem}
          />
        ))}

      {/* Core Mind */}
      {selectedStratum === "core_mind" && <CoreMindView />}
    </div>
  );
}
