"use client";

import { useEffect, useMemo, useState } from "react";
import { diffLines } from "diff";
import { useCoreMindHistory, useCoreMindSnapshot } from "@/hooks/use-api";
import { SnapshotTimeline } from "./snapshot-timeline";
import { computeDiffLines, type DiffLine } from "@/components/shared/diff-viewer";

function DiffLineRow({ line }: { line: DiffLine }) {
  const bgColor =
    line.type === "added"
      ? "rgba(63, 185, 80, 0.15)"
      : line.type === "removed"
        ? "rgba(248, 81, 73, 0.15)"
        : "transparent";

  const borderColor =
    line.type === "added"
      ? "#3FB950"
      : line.type === "removed"
        ? "#F85149"
        : "transparent";

  const prefix =
    line.type === "added" ? "+" : line.type === "removed" ? "-" : " ";

  return (
    <div
      className="flex font-mono text-xs leading-5"
      style={{ background: bgColor, borderLeft: `3px solid ${borderColor}` }}
    >
      <span className="w-10 text-right pr-2 text-text-secondary select-none flex-shrink-0 opacity-60">
        {line.leftLineNo ?? ""}
      </span>
      <span className="w-10 text-right pr-2 text-text-secondary select-none flex-shrink-0 opacity-60">
        {line.rightLineNo ?? ""}
      </span>
      <span className="w-4 text-center text-text-secondary select-none flex-shrink-0 opacity-60">
        {prefix}
      </span>
      <span className="flex-1 whitespace-pre-wrap break-all text-text-primary pl-1">
        {line.content}
      </span>
    </div>
  );
}

// ─── Main Component ──────────────────────────────────────────────────────────

export function CoreMindDiff() {
  const { data: historyData, isLoading } = useCoreMindHistory();
  const snapshots = historyData?.snapshots ?? [];

  const [leftId, setLeftId] = useState<string | null>(null);
  const [rightId, setRightId] = useState<string | null>(null);

  // Auto-select latest two snapshots
  useEffect(() => {
    if (snapshots.length >= 2) {
      setLeftId(snapshots[snapshots.length - 2].id);
      setRightId(snapshots[snapshots.length - 1].id);
    } else if (snapshots.length === 1) {
      setRightId(snapshots[0].id);
      setLeftId(null);
    }
  }, [snapshots]);

  const { data: leftSnap } = useCoreMindSnapshot(leftId);
  const { data: rightSnap } = useCoreMindSnapshot(rightId);

  // Compute diff
  const diffResult = useMemo(() => {
    if (leftSnap?.content == null || rightSnap?.content == null) return null;
    const changes = diffLines(leftSnap.content, rightSnap.content);
    return computeDiffLines(changes);
  }, [leftSnap?.content, rightSnap?.content]);

  // Stats
  const stats = useMemo(() => {
    if (!diffResult) return null;
    const added = diffResult.filter((l) => l.type === "added").length;
    const removed = diffResult.filter((l) => l.type === "removed").length;
    const unchanged = diffResult.filter((l) => l.type === "unchanged").length;
    return { added, removed, unchanged };
  }, [diffResult]);

  // ─── Render States ────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="bg-surface rounded-xl border border-border p-6 min-h-[400px] flex items-center justify-center">
        <span className="text-text-secondary text-sm">Loading snapshots...</span>
      </div>
    );
  }

  if (snapshots.length === 0) {
    return (
      <div className="bg-surface rounded-xl border border-border p-6 min-h-[400px] flex items-center justify-center">
        <span className="text-text-secondary text-sm">
          No snapshots yet. Core Mind history will be saved after each digest.
        </span>
      </div>
    );
  }

  // Single snapshot — show full text
  if (snapshots.length === 1 && rightSnap?.content) {
    return (
      <div className="space-y-4">
        <SnapshotTimeline
          snapshots={snapshots}
          leftId={leftId}
          rightId={rightId}
          onSelectLeft={setLeftId}
          onSelectRight={setRightId}
        />
        <div className="bg-surface rounded-xl border border-border p-4">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-xs text-text-secondary">
              Only one snapshot available — showing full content
            </span>
          </div>
          <pre className="text-xs font-mono text-text-primary whitespace-pre-wrap leading-5 max-h-[500px] overflow-y-auto">
            {rightSnap.content}
          </pre>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <SnapshotTimeline
        snapshots={snapshots}
        leftId={leftId}
        rightId={rightId}
        onSelectLeft={setLeftId}
        onSelectRight={setRightId}
      />

      {/* Diff Stats */}
      {stats && (
        <div className="flex items-center gap-4 text-xs">
          <span className="text-text-secondary">Changes:</span>
          <span className="text-positive font-mono">+{stats.added} added</span>
          <span className="text-negative font-mono">-{stats.removed} removed</span>
          <span className="text-text-secondary font-mono">{stats.unchanged} unchanged</span>
        </div>
      )}

      {/* Diff View */}
      <div className="bg-surface rounded-xl border border-border overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-4 py-2">
          <div className="flex items-center gap-2 text-xs text-text-secondary">
            {leftId && (
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-amber-500" />
                {snapshots.find((s) => s.id === leftId)?.date ?? leftId}
              </span>
            )}
            <span>vs</span>
            {rightId && (
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-emerald-500" />
                {snapshots.find((s) => s.id === rightId)?.date ?? rightId}
              </span>
            )}
          </div>
        </div>

        {/* Diff Lines */}
        <div className="max-h-[500px] overflow-y-auto">
          {diffResult ? (
            diffResult.map((line, i) => <DiffLineRow key={i} line={line} />)
          ) : (
            <div className="p-6 text-center text-text-secondary text-sm">
              {leftId && rightId
                ? "Loading snapshot contents..."
                : "Select two snapshots to compare."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
