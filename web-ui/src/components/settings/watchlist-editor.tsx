"use client";

import { useState, useEffect, useCallback } from "react";
import { useWatchlist, useUpdateWatchlist } from "@/hooks/use-api";
import { Skeleton } from "@/components/ui/skeleton";
import type { WatchlistCategory } from "@/lib/types";

export function WatchlistEditor() {
  const { data, isLoading, error } = useWatchlist();
  const updateMutation = useUpdateWatchlist();

  const [draft, setDraft] = useState<Record<string, WatchlistCategory>>({});
  const [hasChanges, setHasChanges] = useState(false);
  const [tickerInputs, setTickerInputs] = useState<Record<string, string>>({});
  const [newCategoryKey, setNewCategoryKey] = useState("");
  const [newCategoryLabel, setNewCategoryLabel] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  useEffect(() => {
    if (data?.categories && !hasChanges) {
      setDraft(structuredClone(data.categories));
    }
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps -- intentionally skip hasChanges to avoid loop

  const markChanged = useCallback(() => setHasChanges(true), []);

  const TICKER_RE = /^[A-Z0-9.\-]{1,15}$/;

  const addTicker = (categoryKey: string) => {
    const input = (tickerInputs[categoryKey] ?? "").trim().toUpperCase();
    if (!input || !TICKER_RE.test(input)) return;
    setDraft((prev) => {
      const cat = prev[categoryKey];
      if (!cat || cat.tickers.includes(input)) return prev;
      return { ...prev, [categoryKey]: { ...cat, tickers: [...cat.tickers, input] } };
    });
    setTickerInputs((prev) => ({ ...prev, [categoryKey]: "" }));
    markChanged();
  };

  const removeTicker = (categoryKey: string, ticker: string) => {
    setDraft((prev) => {
      const cat = prev[categoryKey];
      if (!cat) return prev;
      return { ...prev, [categoryKey]: { ...cat, tickers: cat.tickers.filter((t) => t !== ticker) } };
    });
    markChanged();
  };

  const CATEGORY_KEY_RE = /^[a-z0-9_]{1,30}$/;

  const addCategory = () => {
    const key = newCategoryKey.trim().toLowerCase().replace(/\s+/g, "_");
    const label = newCategoryLabel.trim();
    if (!key || !label || draft[key] || !CATEGORY_KEY_RE.test(key)) return;
    setDraft((prev) => ({ ...prev, [key]: { label, tickers: [] } }));
    setNewCategoryKey("");
    setNewCategoryLabel("");
    markChanged();
  };

  useEffect(() => {
    if (deleteConfirm) {
      const timer = setTimeout(() => setDeleteConfirm(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [deleteConfirm]);

  const deleteCategory = (key: string) => {
    if (deleteConfirm !== key) {
      setDeleteConfirm(key);
      return;
    }
    setDraft((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
    setDeleteConfirm(null);
    markChanged();
  };

  const handleSave = () => {
    updateMutation.mutate({ categories: draft }, {
      onSuccess: () => setHasChanges(false),
    });
  };

  if (isLoading) {
    return <Skeleton variant="card" className="h-48" />;
  }

  if (error) {
    return (
      <div className="bg-surface rounded-xl border border-border p-6">
        <p className="text-sm text-negative">Failed to load watchlist: {error.message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Category Cards */}
      {Object.entries(draft).map(([key, cat]) => (
        <div key={key} className="bg-surface rounded-xl border border-border p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <span className="text-sm font-medium text-text-primary">{cat.label}</span>
              <span className="text-xs text-text-secondary ml-2 font-mono">({key})</span>
            </div>
            <button
              onClick={() => deleteCategory(key)}
              className="text-xs px-2 py-1 rounded border border-border text-text-secondary hover:text-negative hover:border-negative/50 transition-colors"
            >
              {deleteConfirm === key ? "Confirm Delete" : "Delete"}
            </button>
          </div>

          {/* Ticker chips */}
          <div className="flex flex-wrap gap-2 mb-3">
            {cat.tickers.map((ticker) => (
              <span
                key={ticker}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-background border border-border text-xs font-mono text-text-primary"
              >
                {ticker}
                <button
                  onClick={() => removeTicker(key, ticker)}
                  className="text-text-secondary hover:text-negative transition-colors ml-0.5"
                  aria-label={`Remove ${ticker}`}
                >
                  x
                </button>
              </span>
            ))}
            {cat.tickers.length === 0 && (
              <span className="text-xs text-text-secondary italic">No tickers</span>
            )}
          </div>

          {/* Add ticker input */}
          <div className="flex gap-2">
            <input
              type="text"
              value={tickerInputs[key] ?? ""}
              onChange={(e) => setTickerInputs((prev) => ({ ...prev, [key]: e.target.value }))}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTicker(key); } }}
              placeholder="Add ticker..."
              className="flex-1 h-8 px-3 rounded-lg bg-background border border-border text-text-primary placeholder:text-text-secondary text-xs outline-none focus:border-accent/50 transition-colors"
            />
            <button
              onClick={() => addTicker(key)}
              className="h-8 px-3 rounded-lg border border-border text-xs text-text-secondary hover:text-accent hover:border-accent/50 transition-colors"
            >
              Add
            </button>
          </div>
        </div>
      ))}

      {/* Add new category */}
      <div className="bg-surface rounded-xl border border-dashed border-border p-4">
        <p className="text-xs text-text-secondary mb-2">Add New Category</p>
        <div className="flex gap-2">
          <input
            type="text"
            value={newCategoryKey}
            onChange={(e) => setNewCategoryKey(e.target.value)}
            placeholder="Key (e.g. tech)"
            className="flex-1 h-8 px-3 rounded-lg bg-background border border-border text-text-primary placeholder:text-text-secondary text-xs outline-none focus:border-accent/50 transition-colors"
          />
          <input
            type="text"
            value={newCategoryLabel}
            onChange={(e) => setNewCategoryLabel(e.target.value)}
            placeholder="Label (e.g. Technology)"
            className="flex-1 h-8 px-3 rounded-lg bg-background border border-border text-text-primary placeholder:text-text-secondary text-xs outline-none focus:border-accent/50 transition-colors"
          />
          <button
            onClick={addCategory}
            className="h-8 px-3 rounded-lg border border-border text-xs text-text-secondary hover:text-accent hover:border-accent/50 transition-colors"
          >
            Add
          </button>
        </div>
      </div>

      {/* Save button */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={!hasChanges || updateMutation.isPending}
          className="h-9 px-5 rounded-lg bg-accent text-background font-medium text-sm hover:bg-accent/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {updateMutation.isPending ? "Saving..." : "Save Changes"}
        </button>
        {hasChanges && (
          <span className="text-xs text-interactive">Unsaved changes</span>
        )}
        {updateMutation.isError && (
          <span className="text-xs text-negative">Save failed: {updateMutation.error.message}</span>
        )}
      </div>
    </div>
  );
}
