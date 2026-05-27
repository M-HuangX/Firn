"use client";

import { useCallback, useEffect, useState } from "react";
import {
  useKBCoreMind,
  useKBThemeDetail,
  useKBStockDetail,
  useKBEventDetail,
} from "@/hooks/use-api";
import type { KBGraphNode, KBGraphEdge } from "@/lib/types";
import { EmptyState } from "@/components/ui/empty-state";

// ─── Color Mapping ────────────────────────────────────────────────────────────

const NODE_COLORS: Record<string, string> = {
  core: "#8B5CF6",
  theme: "#06B6D4",
  stock: "#10B981",
  event: "#F59E0B",
};

// ─── Types ────────────────────────────────────────────────────────────────────

interface NodeDetailPanelProps {
  nodeId: string;
  kbNodes: KBGraphNode[];
  kbEdges: KBGraphEdge[];
  onClose: () => void;
}

type NodeKind = "core" | "theme" | "stock" | "event";

function deriveNodeKind(nodeId: string): NodeKind {
  if (nodeId === "core_mind") return "core";
  if (nodeId.startsWith("theme:")) return "theme";
  if (nodeId.startsWith("stock:")) return "stock";
  if (nodeId.startsWith("event:")) return "event";
  return "core";
}

function humanizeSlug(slug: string): string {
  return slug
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatChars(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

// ─── Sub-Panels ───────────────────────────────────────────────────────────────

function CoreMindPanel() {
  const { data, isLoading } = useKBCoreMind();

  if (isLoading) return <LoadingState />;
  if (!data?.content) return <EmptyState title="No core mind content." className="py-8" />;

  return (
    <pre className="text-xs font-mono text-text-primary whitespace-pre-wrap leading-relaxed">
      {data.content}
    </pre>
  );
}

function ThemePanel({
  slug,
  kbEdges,
}: {
  slug: string;
  kbEdges: KBGraphEdge[];
}) {
  const { data, isLoading } = useKBThemeDetail(slug);

  const connectedStocks = kbEdges
    .filter(
      (e) =>
        (e.source === `theme:${slug}` && e.target.startsWith("stock:")) ||
        (e.target === `theme:${slug}` && e.source.startsWith("stock:"))
    )
    .map((e) => {
      const stockId =
        e.source === `theme:${slug}` ? e.target : e.source;
      return stockId.slice(6); // remove "stock:" prefix
    });

  if (isLoading) return <LoadingState />;
  if (!data?.content) return <EmptyState title="No theme content." className="py-8" />;

  return (
    <div className="space-y-4">
      <pre className="text-xs font-mono text-text-primary whitespace-pre-wrap leading-relaxed">
        {data.content}
      </pre>
      {connectedStocks.length > 0 && (
        <div className="pt-3 border-t border-border">
          <div className="text-[11px] font-medium text-text-secondary uppercase tracking-wider mb-2">
            Connected Stocks
          </div>
          <div className="flex flex-wrap gap-1.5">
            {connectedStocks.map((ticker) => (
              <span
                key={ticker}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-medium"
                style={{
                  background: "rgba(16, 185, 129, 0.1)",
                  color: "#10B981",
                }}
              >
                {ticker}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StockPanel({ ticker }: { ticker: string }) {
  const { data, isLoading } = useKBStockDetail(ticker);
  const [expandedFile, setExpandedFile] = useState<string | null>(null);

  const toggleFile = useCallback(
    (fileName: string) => {
      setExpandedFile((prev) => (prev === fileName ? null : fileName));
    },
    []
  );

  if (isLoading) return <LoadingState />;
  if (!data?.files || Object.keys(data.files).length === 0) {
    return <EmptyState title="No stock data files." className="py-8" />;
  }

  const fileEntries = Object.entries(data.files);

  return (
    <div className="space-y-1">
      {fileEntries.map(([fileName, content]) => {
        const isExpanded = expandedFile === fileName;
        return (
          <div key={fileName} className="border border-border rounded-lg overflow-hidden">
            <button
              onClick={() => toggleFile(fileName)}
              className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-white/[0.02] transition-colors"
            >
              <span className="text-xs font-medium text-text-primary">
                {fileName}
              </span>
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-text-secondary font-mono">
                  {formatChars(content.length)}
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
                <pre className="text-xs font-mono text-text-primary whitespace-pre-wrap leading-relaxed mt-2 max-h-[300px] overflow-y-auto">
                  {content}
                </pre>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function EventPanel({ slug }: { slug: string }) {
  const { data, isLoading } = useKBEventDetail(slug);

  if (isLoading) return <LoadingState />;
  if (!data?.content) return <EmptyState title="No event content." className="py-8" />;

  return (
    <pre className="text-xs font-mono text-text-primary whitespace-pre-wrap leading-relaxed">
      {data.content}
    </pre>
  );
}

// ─── Shared Helpers ───────────────────────────────────────────────────────────

function LoadingState() {
  return (
    <div className="flex items-center justify-center py-8">
      <div className="text-text-secondary text-xs">Loading...</div>
    </div>
  );
}


// ─── Main Panel ───────────────────────────────────────────────────────────────

export function NodeDetailPanel({
  nodeId,
  kbNodes,
  kbEdges,
  onClose,
}: NodeDetailPanelProps) {
  const kind = deriveNodeKind(nodeId);
  const node = kbNodes.find((n) => n.id === nodeId);
  const color = NODE_COLORS[kind] ?? "#8B5CF6";
  const [mounted, setMounted] = useState(false);

  // Slide-in on mount
  useEffect(() => {
    // Trigger the transition on next frame
    const raf = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  // Escape key to close
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  // Derive label
  let label = node?.label ?? nodeId;
  if (kind === "theme") label = humanizeSlug(nodeId.slice(6));
  if (kind === "event") label = humanizeSlug(nodeId.slice(6));
  if (kind === "core") label = "Core Mind";

  // Use node label if available (it's already human-readable from the backend)
  if (node?.label) label = node.label;

  const chars = node?.chars ?? 0;

  // Derive slug/ticker for detail fetch
  const slug =
    kind === "theme"
      ? nodeId.slice(6)
      : kind === "event"
        ? nodeId.slice(6)
        : null;
  const ticker = kind === "stock" ? nodeId.slice(6) : null;

  return (
    <div
      className="absolute top-0 right-0 w-[400px] max-h-full overflow-y-auto bg-surface/95 backdrop-blur-sm border-l border-border z-50"
      style={{
        transform: mounted ? "translateX(0)" : "translateX(100%)",
        transition: "transform 300ms cubic-bezier(0.22, 1, 0.36, 1)",
      }}
    >
      {/* Header */}
      <div className="sticky top-0 bg-surface/95 backdrop-blur-sm border-b border-border px-4 py-3 flex items-center justify-between z-10">
        <div className="flex items-center gap-2.5 min-w-0">
          <span
            className="w-2.5 h-2.5 rounded-full shrink-0"
            style={{ background: color }}
          />
          <span className="text-sm font-semibold text-text-primary truncate">
            {label}
          </span>
          {chars > 0 && (
            <span className="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-mono text-text-secondary bg-white/[0.04] border border-border">
              {formatChars(chars)}
            </span>
          )}
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-white/[0.05] text-text-secondary hover:text-text-primary transition-colors shrink-0"
          aria-label="Close detail panel"
        >
          <svg
            className="w-4 h-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      </div>

      {/* Content */}
      <div className="p-4">
        {kind === "core" && <CoreMindPanel />}
        {kind === "theme" && slug && (
          <ThemePanel slug={slug} kbEdges={kbEdges} />
        )}
        {kind === "stock" && ticker && <StockPanel ticker={ticker} />}
        {kind === "event" && slug && <EventPanel slug={slug} />}
      </div>
    </div>
  );
}
