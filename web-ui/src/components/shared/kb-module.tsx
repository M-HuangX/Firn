"use client";

import { cn } from "@/lib/utils";
import { DiffViewer } from "./diff-viewer";

interface KBModuleProps {
  section: string;
  slug: string;
  isNew: boolean;
  diff?: string;
  before?: string;
  after?: string;
  content?: string;
  oldLen?: number;
  newLen?: number;
  className?: string;
}

const SECTION_COLORS: Record<string, string> = {
  core_mind: "var(--color-core-mind)",
  themes: "var(--color-kb-read)",
  stocks: "#10B981",
  events: "var(--color-tool-call)",
  sectors: "var(--color-interactive)",
};

function getSectionColor(section: string): string {
  return SECTION_COLORS[section] ?? "var(--color-border)";
}

export function KBModule({
  section,
  slug,
  isNew,
  before,
  after,
  content,
  oldLen,
  newLen,
  className,
}: KBModuleProps) {
  const borderColor = getSectionColor(section);
  const sectionPath = `${section}/${slug}`;

  // For new files, use content as the after text
  const effectiveAfter = after ?? content;

  return (
    <div
      className={cn(
        "bg-surface rounded-lg border border-border overflow-hidden",
        className
      )}
      style={{ borderLeftWidth: "3px", borderLeftColor: borderColor }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-text-primary">
            {sectionPath}
          </span>
          {isNew && (
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400">
              NEW
            </span>
          )}
        </div>
        {(oldLen != null || newLen != null) && (
          <span className="text-[10px] text-text-secondary font-mono">
            {oldLen != null && newLen != null
              ? `${oldLen} → ${newLen} chars`
              : newLen != null
                ? `${newLen} chars`
                : `${oldLen} chars`}
          </span>
        )}
      </div>

      {/* Diff content */}
      <DiffViewer
        before={isNew ? undefined : before}
        after={effectiveAfter}
        isNew={isNew}
        showStats={!isNew}
        showLineNumbers={false}
        maxHeight={300}
      />
    </div>
  );
}
