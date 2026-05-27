"use client";

import { useMemo } from "react";
import { diffLines, type Change } from "diff";
import { cn } from "@/lib/utils";

// ─── Diff Rendering Helpers ──────────────────────────────────────────────────

export interface DiffLine {
  type: "added" | "removed" | "unchanged";
  content: string;
  leftLineNo: number | null;
  rightLineNo: number | null;
}

/** Convert diff Change[] into a flat array of DiffLines with line numbers */
export function computeDiffLines(changes: Change[]): DiffLine[] {
  const lines: DiffLine[] = [];
  let leftLine = 1;
  let rightLine = 1;

  for (const change of changes) {
    // Split the value into individual lines (remove trailing empty from split)
    const rawLines = change.value.split("\n");
    // diffLines produces values ending with \n, so last split element is empty
    const contentLines =
      rawLines[rawLines.length - 1] === "" ? rawLines.slice(0, -1) : rawLines;

    for (const line of contentLines) {
      if (change.added) {
        lines.push({
          type: "added",
          content: line,
          leftLineNo: null,
          rightLineNo: rightLine++,
        });
      } else if (change.removed) {
        lines.push({
          type: "removed",
          content: line,
          leftLineNo: leftLine++,
          rightLineNo: null,
        });
      } else {
        lines.push({
          type: "unchanged",
          content: line,
          leftLineNo: leftLine++,
          rightLineNo: rightLine++,
        });
      }
    }
  }

  return lines;
}

// ─── DiffLineRow ─────────────────────────────────────────────────────────────

function DiffLineRow({
  line,
  showLineNumbers,
}: {
  line: DiffLine;
  showLineNumbers: boolean;
}) {
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
      {showLineNumbers && (
        <>
          <span className="w-10 text-right pr-2 text-text-secondary select-none flex-shrink-0 opacity-60">
            {line.leftLineNo ?? ""}
          </span>
          <span className="w-10 text-right pr-2 text-text-secondary select-none flex-shrink-0 opacity-60">
            {line.rightLineNo ?? ""}
          </span>
        </>
      )}
      <span className="w-4 text-center text-text-secondary select-none flex-shrink-0 opacity-60">
        {prefix}
      </span>
      <span className="flex-1 whitespace-pre-wrap break-all text-text-primary pl-1">
        {line.content}
      </span>
    </div>
  );
}

// ─── DiffViewer Component ────────────────────────────────────────────────────

interface DiffViewerProps {
  before?: string;
  after?: string;
  unifiedDiff?: string;
  maxHeight?: number;
  showLineNumbers?: boolean;
  showStats?: boolean;
  label?: string;
  isNew?: boolean;
  className?: string;
}

export function DiffViewer({
  before,
  after,
  maxHeight = 300,
  showLineNumbers = false,
  showStats = true,
  label,
  isNew = false,
  className,
}: DiffViewerProps) {
  const diffResult = useMemo(() => {
    if (isNew && after) {
      // For new files, show all lines as added
      const lines = after.split("\n");
      return lines.map(
        (content, i): DiffLine => ({
          type: "added",
          content,
          leftLineNo: null,
          rightLineNo: i + 1,
        })
      );
    }

    if (before != null && after != null) {
      const changes = diffLines(before, after);
      return computeDiffLines(changes);
    }

    return null;
  }, [before, after, isNew]);

  const stats = useMemo(() => {
    if (!diffResult) return null;
    const added = diffResult.filter((l) => l.type === "added").length;
    const removed = diffResult.filter((l) => l.type === "removed").length;
    return { added, removed };
  }, [diffResult]);

  if (!diffResult) {
    return (
      <div
        className={cn(
          "bg-surface rounded-lg border border-border p-4 text-center text-text-secondary text-xs",
          className
        )}
      >
        No diff data available
      </div>
    );
  }

  return (
    <div className={cn("bg-surface rounded-lg border border-border overflow-hidden", className)}>
      {/* Header with label and stats */}
      {(label || (showStats && stats)) && (
        <div className="flex items-center justify-between px-3 py-1.5 border-b border-border">
          <div className="flex items-center gap-2">
            {label && (
              <span className="text-xs font-mono text-text-secondary">
                {label}
              </span>
            )}
            {isNew && (
              <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400">
                NEW
              </span>
            )}
          </div>
          {showStats && stats && (
            <div className="flex items-center gap-3 text-[10px] font-mono">
              <span className="text-positive">+{stats.added} added</span>
              <span className="text-negative">-{stats.removed} removed</span>
            </div>
          )}
        </div>
      )}

      {/* Diff Lines */}
      <div
        className="overflow-y-auto scrollbar-thin"
        style={{ maxHeight: `${maxHeight}px` }}
      >
        {diffResult.map((line, i) => (
          <DiffLineRow
            key={i}
            line={line}
            showLineNumbers={showLineNumbers}
          />
        ))}
      </div>
    </div>
  );
}
