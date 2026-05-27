"use client";

import { useState, useMemo, useEffect } from "react";
import { SECTION_COLORS } from "@/lib/digest-theater-types";
import type { KBModuleState } from "@/lib/digest-theater-types";

// ─── Constants ───────────────────────────────────────────────────────────────

/** Default visible diff lines for regular modules */
const DEFAULT_VISIBLE_LINES = 6;

/** Default visible lines for new file content preview */
const NEW_FILE_PREVIEW_LINES = 5;

/** Freshness thresholds in ms (based on replay elapsed time) */
const FRESH_THRESHOLD_MS = 10_000;
const SETTLING_THRESHOLD_MS = 30_000;

// ─── Diff parsing ────────────────────────────────────────────────────────────

interface DiffLine {
  type: "added" | "removed" | "context" | "hunk-separator";
  text: string;
}

/**
 * Parse a unified diff string into renderable lines.
 * Strips header lines (---/+++/@@) and shows only changes + minimal context.
 * Between hunks, insert a thin "..." separator.
 */
function parseUnifiedDiff(diffStr: string): DiffLine[] {
  if (!diffStr || !diffStr.trim()) return [];

  const rawLines = diffStr.split("\n");
  const result: DiffLine[] = [];
  let inHunk = false;
  let hunkCount = 0;

  for (const line of rawLines) {
    // Skip diff headers
    if (line.startsWith("---") || line.startsWith("+++")) continue;

    // Hunk header — marks start of a new hunk
    if (line.startsWith("@@")) {
      if (hunkCount > 0 && result.length > 0) {
        // Insert separator between hunks
        result.push({ type: "hunk-separator", text: "..." });
      }
      hunkCount++;
      inHunk = true;
      continue;
    }

    if (!inHunk) continue;

    if (line.startsWith("+")) {
      result.push({ type: "added", text: line.substring(1) });
    } else if (line.startsWith("-")) {
      result.push({ type: "removed", text: line.substring(1) });
    } else if (line.startsWith(" ")) {
      result.push({ type: "context", text: line.substring(1) });
    } else if (line === "") {
      // Empty line within a hunk — treat as context
      result.push({ type: "context", text: "" });
    }
  }

  return result;
}

/**
 * Parse full file content into preview lines for new files.
 * Shows first N lines without the green "wall of additions" style.
 */
function parseNewFileContent(content: string): string[] {
  if (!content) return [];
  return content.split("\n").filter((line) => line.trim() !== "");
}

// ─── Freshness computation ───────────────────────────────────────────────────

/**
 * Compute freshness-based opacity and glow for a KB module.
 * Freshness = how long ago the module was last edited relative to
 * the current replay timestamp. Recently edited modules appear brighter
 * with an inner glow; older ones gradually fade — "cooling" from active to frozen.
 */
function computeFreshness(
  lastEditAt: number,
  currentReplayTs: number,
): { opacity: number; showGlow: boolean } {
  if (currentReplayTs <= 0 || lastEditAt <= 0) {
    return { opacity: 1.0, showGlow: false };
  }
  const timeSinceEdit = currentReplayTs - lastEditAt;

  if (timeSinceEdit < FRESH_THRESHOLD_MS) {
    return { opacity: 1.0, showGlow: true };
  }
  if (timeSinceEdit < SETTLING_THRESHOLD_MS) {
    return { opacity: 0.85, showGlow: false };
  }
  return { opacity: 0.75, showGlow: false };
}

// ─── Component ───────────────────────────────────────────────────────────────

interface KBModuleCardProps {
  module: KBModuleState;
  currentReplayTs: number;
  shouldAnimate: boolean;
  moduleIndex?: number;
  isCompacted: boolean;
}

export function KBModuleCard({ module, currentReplayTs, shouldAnimate, moduleIndex = 0, isCompacted }: KBModuleCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [forceExpanded, setForceExpanded] = useState(false);

  // Reset forceExpanded when the module gets new edits
  useEffect(() => {
    setForceExpanded(false);
  }, [module.lastEditAt]);

  // The effective compaction state: compacted unless user force-expanded
  const effectivelyCompacted = isCompacted && !forceExpanded;

  const isCoreMind = module.section === "core_mind";
  const sectionColor = SECTION_COLORS[module.section];

  // Compute freshness-based styling
  const { opacity, showGlow } = computeFreshness(
    module.lastEditAt,
    currentReplayTs,
  );

  // Settled = freshness > 30s (no glow, lowest opacity tier)
  const isSettled = !showGlow && opacity <= 0.75 && currentReplayTs > 0;

  // Parse all diffs into renderable lines
  const diffLines = useMemo(() => {
    // Combine all diff entries for this module (session-level cumulative)
    const allDiffs = module.diffs.filter((d) => d.trim() !== "");
    if (allDiffs.length === 0) return [];
    // Use the last (most recent) diff for display — it represents the cumulative state
    // If there are multiple diffs, show the latest one
    const latestDiff = allDiffs[allDiffs.length - 1];
    return parseUnifiedDiff(latestDiff);
  }, [module.diffs]);

  // For new files, parse content preview
  const newFileLines = useMemo(() => {
    if (!module.is_new || !module.fullContent) return [];
    return parseNewFileContent(module.fullContent);
  }, [module.is_new, module.fullContent]);

  // Determine what to render in the diff area
  const hasDiff = diffLines.length > 0;
  const hasNewContent = newFileLines.length > 0;

  // Line limiting (core_mind: unlimited; regular: 6 lines default)
  const visibleDiffLines = useMemo(() => {
    if (isCoreMind || isExpanded) return diffLines;
    return diffLines.slice(0, DEFAULT_VISIBLE_LINES);
  }, [diffLines, isCoreMind, isExpanded]);

  const hiddenDiffCount = diffLines.length - visibleDiffLines.length;

  const visibleNewFileLines = useMemo(() => {
    if (isExpanded) return newFileLines;
    return newFileLines.slice(0, NEW_FILE_PREVIEW_LINES);
  }, [newFileLines, isExpanded]);

  const hiddenNewFileCount = newFileLines.length - visibleNewFileLines.length;

  // Card styling
  const cardBg = isCoreMind
    ? "rgba(139, 92, 246, 0.04)"
    : module.is_new
      ? "rgba(63, 185, 80, 0.03)"
      : "rgba(255, 255, 255, 0.03)";

  const leftBorderWidth = isCoreMind ? "6px" : "4px";
  const leftBorderColor = sectionColor;

  const glowShadow = showGlow
    ? `inset 0 0 20px rgba(${hexToRgb(sectionColor)}, 0.08)`
    : "none";

  return (
      <div
        data-kb-module-id={module.id}
        onClick={effectivelyCompacted ? () => setForceExpanded(true) : undefined}
        style={{
          background: cardBg,
          backdropFilter: "blur(4px)",
          WebkitBackdropFilter: "blur(4px)",
          boxShadow: `inset 0 1px 0 rgba(255, 255, 255, 0.05)${glowShadow !== "none" ? `, ${glowShadow}` : ""}`,
          border: "1px solid rgba(255, 255, 255, 0.06)",
          borderLeft: `${leftBorderWidth} solid ${leftBorderColor}`,
          borderRadius: "10px",
          padding: effectivelyCompacted ? "6px 14px" : "12px 14px",
          opacity,
          minHeight: isCoreMind && !effectivelyCompacted ? "200px" : undefined,
          cursor: effectivelyCompacted ? "pointer" : undefined,
          transition: "opacity 800ms ease-out, box-shadow 600ms ease-out, padding 400ms ease-out",
          // Birth animation — only on first appearance, not on scrub/re-render
          // Settled modules get subtle border breathing (12s, sub-perceptual)
          animation: shouldAnimate
            ? "kbModuleBirth 2.5s cubic-bezier(0.22, 1, 0.36, 1) both"
            : isSettled
              ? `kbBorderBreathe 12s ease-in-out ${(moduleIndex * 2.3) % 7}s infinite`
              : "none",
        }}
      >
        {/* Header row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            marginBottom: effectivelyCompacted ? "0" : (hasDiff || hasNewContent ? "8px" : "0"),
          }}
        >
          {/* Section color dot */}
          <span
            style={{
              width: "6px",
              height: "6px",
              borderRadius: "50%",
              backgroundColor: sectionColor,
              flexShrink: 0,
            }}
          />

          {/* Section label */}
          <span
            style={{
              fontSize: "10px",
              fontFamily: "system-ui, sans-serif",
              fontWeight: 500,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              color: "rgba(226, 235, 245, 0.5)",
              flexShrink: 0,
            }}
          >
            {module.section === "core_mind"
              ? "CORE MIND"
              : module.section.toUpperCase()}
          </span>

          {/* Slug — hidden for core_mind (redundant with section label) */}
          {!isCoreMind && (
            <span
              style={{
                fontSize: "11px",
                fontFamily: '"JetBrains Mono", ui-monospace, monospace',
                color: "rgba(226, 235, 245, 0.7)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                flex: 1,
                minWidth: 0,
              }}
              title={module.slug}
            >
              {module.slug}
            </span>
          )}
          {isCoreMind && <span style={{ flex: 1 }} />}

          {/* NEW badge */}
          {module.is_new && (
            <span
              style={{
                fontSize: "10px",
                fontWeight: 600,
                backgroundColor: "rgba(245, 196, 66, 0.15)",
                color: "#F5C442",
                borderRadius: "4px",
                padding: "1px 6px",
                flexShrink: 0,
              }}
            >
              NEW
            </span>
          )}

          {/* Compacted indicator — sediment dots */}
          {effectivelyCompacted && (
            <span style={{
              fontSize: "10px",
              color: "rgba(226, 235, 245, 0.25)",
              marginLeft: "auto",
              flexShrink: 0,
            }}>
              ···
            </span>
          )}
        </div>

        {/* Content area — collapses when compacted (geological settling) */}
        <div
          style={{
            maxHeight: effectivelyCompacted ? 0 : 500,
            overflow: "hidden",
            opacity: effectivelyCompacted ? 0 : 1,
            transition: "max-height 600ms cubic-bezier(0.22, 1, 0.36, 1), opacity 400ms ease-out",
          }}
        >
          {/* Diff rendering area */}
          {hasDiff && (
            <div style={{ marginTop: "4px" }}>
              <div
                style={{
                  fontFamily: 'Georgia, "Noto Serif SC", serif',
                  fontSize: "12px",
                  lineHeight: 1.65,
                }}
              >
                {visibleDiffLines.map((line, i) => (
                  <DiffLineRow key={`${module.id}-diff-${i}`} line={line} />
                ))}
              </div>

              {/* "+N more lines" expander */}
              {hiddenDiffCount > 0 && (
                <button
                  onClick={() => setIsExpanded(true)}
                  style={{
                    display: "block",
                    marginTop: "4px",
                    fontSize: "11px",
                    color: "rgba(226, 235, 245, 0.35)",
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    fontFamily: "system-ui, sans-serif",
                    padding: 0,
                  }}
                >
                  +{hiddenDiffCount} more line{hiddenDiffCount !== 1 ? "s" : ""}
                </button>
              )}
            </div>
          )}

          {/* New file content preview (not a wall of green) */}
          {!hasDiff && hasNewContent && (
            <div style={{ marginTop: "4px" }}>
              <div
                style={{
                  fontFamily: 'Georgia, "Noto Serif SC", serif',
                  fontSize: "12px",
                  lineHeight: 1.65,
                  color: "rgba(226, 235, 245, 0.6)",
                }}
              >
                {visibleNewFileLines.map((line, i) => (
                  <div
                    key={`${module.id}-new-${i}`}
                    style={{
                      padding: "1px 4px",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {line}
                  </div>
                ))}
              </div>

              {hiddenNewFileCount > 0 && (
                <button
                  onClick={() => setIsExpanded(true)}
                  style={{
                    display: "block",
                    marginTop: "4px",
                    fontSize: "11px",
                    color: "rgba(226, 235, 245, 0.35)",
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    fontFamily: "system-ui, sans-serif",
                    padding: 0,
                  }}
                >
                  +{hiddenNewFileCount} more line{hiddenNewFileCount !== 1 ? "s" : ""}
                </button>
              )}
            </div>
          )}

          {/* Fallback: no diff and no content — show size info */}
          {!hasDiff && !hasNewContent && (
            <div
              style={{
                fontSize: "11px",
                fontFamily: '"JetBrains Mono", ui-monospace, monospace',
                color: "rgba(226, 235, 245, 0.35)",
                marginTop: "2px",
              }}
            >
              {module.content}
            </div>
          )}
        </div>
      </div>
  );
}

// ─── Diff Line Row ───────────────────────────────────────────────────────────

function DiffLineRow({ line }: { line: DiffLine }) {
  if (line.type === "hunk-separator") {
    return (
      <div
        style={{
          padding: "2px 4px",
          color: "rgba(226, 235, 245, 0.25)",
          fontSize: "10px",
          fontFamily: "system-ui, sans-serif",
          borderTop: "1px solid rgba(255, 255, 255, 0.04)",
          marginTop: "2px",
          marginBottom: "2px",
        }}
      >
        {line.text}
      </div>
    );
  }

  if (line.type === "added") {
    return (
      <div
        style={{
          background: "rgba(63, 185, 80, 0.12)",
          borderLeft: "2px solid rgba(63, 185, 80, 0.5)",
          color: "#C4EDCC",
          padding: "1px 4px 1px 6px",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {line.text}
      </div>
    );
  }

  if (line.type === "removed") {
    return (
      <div
        style={{
          background: "rgba(248, 81, 73, 0.08)",
          textDecoration: "line-through",
          color: "rgba(248, 81, 73, 0.55)",
          padding: "1px 4px 1px 6px",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {line.text}
      </div>
    );
  }

  // Context line
  return (
    <div
      style={{
        color: "rgba(226, 235, 245, 0.4)",
        padding: "1px 4px 1px 6px",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
      }}
    >
      {line.text}
    </div>
  );
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Convert hex color to r,g,b string for use in rgba() */
function hexToRgb(hex: string): string {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!result) return "255, 255, 255";
  return `${parseInt(result[1], 16)}, ${parseInt(result[2], 16)}, ${parseInt(result[3], 16)}`;
}
