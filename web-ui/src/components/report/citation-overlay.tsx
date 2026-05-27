"use client";

import React, { memo, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { CitationTooltip } from "./citation-tooltip";
import { getVerdictStyle } from "./verdict-colors";
import type { MatchedCitation } from "./use-citations";
import type { Components } from "react-markdown";

// Context for clicked citation (avoids threading through function params)
const ClickedCitationContext = React.createContext<number | null>(null);

// ─── Rehype plugin: inject data-source-line on block elements ─────────────────

function rehypeSourceLines() {
  return (tree: { type: string; children: HastNode[] }) => {
    visitBlock(tree);
  };
}

interface HastNode {
  type: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  position?: { start: { line: number } };
  children?: HastNode[];
}

const BLOCK_TAGS = new Set([
  "p", "h1", "h2", "h3", "h4", "h5", "h6",
  "li", "tr", "blockquote", "pre", "table",
]);

function visitBlock(node: HastNode) {
  if (
    node.type === "element" &&
    node.tagName &&
    BLOCK_TAGS.has(node.tagName) &&
    node.position?.start.line
  ) {
    node.properties = node.properties || {};
    node.properties["data-source-line"] = node.position.start.line;
  }
  if (node.children) {
    for (const child of node.children) {
      visitBlock(child);
    }
  }
}

// ─── Highlight anchor extraction ─────────────────────────────────────────────

const NUMBER_RE = /[-+]?\$?~?\d[\d,]*\.?\d*[%xBMKbmk]?/g;

function stripMarkdownInline(text: string): string {
  return text
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/~~([^~]+)~~/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\|/g, " ")
    .replace(/#+\s*/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Extract a short anchor string from a citation for inline highlighting.
 * Short excerpts are used directly; long ones extract the key number.
 * Returns [primaryAnchor, fallbackAnchor?] for retry on cross-element misses.
 */
function extractHighlightAnchors(citation: MatchedCitation): [string, string | undefined] {
  const excerpt = stripMarkdownInline(citation.claimInReport || citation.claim);

  if (excerpt.length <= 30) {
    const numbers = excerpt.match(NUMBER_RE);
    const fallback = numbers?.[0] && numbers[0].length < excerpt.length ? numbers[0] : undefined;
    return [excerpt, fallback];
  }

  const numbers = excerpt.match(NUMBER_RE);
  if (numbers && numbers.length > 0) {
    return [numbers[0], undefined];
  }

  return [excerpt.slice(0, 25), undefined];
}

// ─── Inline citation mark component ─────────────────────────────────────────

interface InlineCitationMarkProps {
  citation: MatchedCitation;
  children: React.ReactNode;
  isHovered: boolean;
  onHover: (id: number | null) => void;
  onTap?: (citation: MatchedCitation) => void;
}

function InlineCitationMark({
  citation,
  children,
  isHovered,
  onHover,
  onTap,
}: InlineCitationMarkProps) {
  const clickedId = React.useContext(ClickedCitationContext);
  const isClicked = clickedId === citation.id;
  const style = getVerdictStyle(citation.verdict);
  const isUnverified = citation.verdict === "unverified" || citation.verdict === "llm-inferred";
  const active = isHovered || isClicked;

  return (
    <CitationTooltip citation={citation} forceOpen={isClicked}>
      <span
        className={cn(
          "citation-mark relative rounded-sm transition-all duration-200 cursor-default",
          active && "ring-1 ring-current/30",
          isClicked && "ring-2",
        )}
        style={{
          backgroundColor: active ? style.highlightHover : style.highlightBg,
          borderBottom: `2px ${isUnverified ? "dashed" : "solid"} ${style.barColor}70`,
          ...(isClicked && { boxShadow: `0 0 8px ${style.barColor}40` }),
        }}
        data-citation-id={citation.id}
        onMouseEnter={() => onHover(citation.id)}
        onMouseLeave={() => onHover(null)}
        onClick={onTap ? () => onTap(citation) : undefined}
      >
        {children}
        <sup
          className="citation-num ml-px font-mono select-none opacity-70 hover:opacity-100"
          style={{
            fontSize: "9px",
            color: style.barColor,
            lineHeight: 1,
            verticalAlign: "super",
          }}
        >
          {citation.displayNumber}
        </sup>
      </span>
    </CitationTooltip>
  );
}

// ─── Fallback: superscript number at end of block ───────────────────────────

interface FallbackSupProps {
  citation: MatchedCitation;
  isHovered: boolean;
  onHover: (id: number | null) => void;
  onTap?: (citation: MatchedCitation) => void;
}

function FallbackSup({ citation, isHovered, onHover, onTap }: FallbackSupProps) {
  const clickedId = React.useContext(ClickedCitationContext);
  const isClicked = clickedId === citation.id;
  const active = isHovered || isClicked;
  const style = getVerdictStyle(citation.verdict);
  return (
    <CitationTooltip citation={citation} forceOpen={isClicked}>
      <sup
        className={cn(
          "citation-fallback ml-0.5 font-mono cursor-default transition-opacity",
          active ? "opacity-100" : "opacity-60",
        )}
        style={{ fontSize: "9px", color: style.barColor }}
        data-citation-id={citation.id}
        onMouseEnter={() => onHover(citation.id)}
        onMouseLeave={() => onHover(null)}
        onClick={onTap ? () => onTap(citation) : undefined}
      >
        {citation.displayNumber}
      </sup>
    </CitationTooltip>
  );
}

// ─── React children processing ──────────────────────────────────────────────

interface AnchorMatch {
  anchor: string;
  fallbackAnchor?: string;
  citation: MatchedCitation;
  consumed: boolean;
}

/**
 * Walk a React children tree, find text strings containing citation anchors,
 * and split them to inject InlineCitationMark wrappers.
 */
function processChildren(
  children: React.ReactNode,
  anchors: AnchorMatch[],
  hoveredCitationId: number | null,
  onHover: (id: number | null) => void,
  onTap?: (citation: MatchedCitation) => void,
): React.ReactNode {
  const remaining = anchors.filter((a) => !a.consumed);
  if (remaining.length === 0) return children;

  return React.Children.map(children, (child) => {
    if (typeof child === "string") {
      return applyHighlights(child, remaining, hoveredCitationId, onHover, onTap);
    }
    if (React.isValidElement<{ children?: React.ReactNode }>(child) && child.props.children != null) {
      const newChildren = processChildren(
        child.props.children,
        anchors,
        hoveredCitationId,
        onHover,
        onTap,
      );
      return React.cloneElement(child, {}, newChildren);
    }
    return child;
  });
}

/**
 * Find anchor texts within a string and split into fragments with highlight wrappers.
 */
function applyHighlights(
  text: string,
  anchors: AnchorMatch[],
  hoveredCitationId: number | null,
  onHover: (id: number | null) => void,
  onTap?: (citation: MatchedCitation) => void,
): React.ReactNode {
  const textLower = text.toLowerCase();
  const matches: { start: number; end: number; anchor: AnchorMatch }[] = [];

  for (const a of anchors) {
    if (a.consumed) continue;
    const idx = textLower.indexOf(a.anchor);
    if (idx >= 0) {
      matches.push({ start: idx, end: idx + a.anchor.length, anchor: a });
    }
  }

  if (matches.length === 0) return text;

  // Sort by position, resolve overlaps (keep earlier)
  matches.sort((a, b) => a.start - b.start);
  const filtered: typeof matches = [];
  let lastEnd = 0;
  for (const m of matches) {
    if (m.start >= lastEnd) {
      filtered.push(m);
      lastEnd = m.end;
    }
  }

  for (const m of filtered) {
    m.anchor.consumed = true;
  }

  const parts: React.ReactNode[] = [];
  let cursor = 0;
  for (const m of filtered) {
    if (m.start > cursor) {
      parts.push(text.slice(cursor, m.start));
    }
    parts.push(
      <InlineCitationMark
        key={`cite-${m.anchor.citation.id}`}
        citation={m.anchor.citation}
        isHovered={hoveredCitationId === m.anchor.citation.id}
        onHover={onHover}
        onTap={onTap}
      >
        {text.slice(m.start, m.end)}
      </InlineCitationMark>,
    );
    cursor = m.end;
  }
  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }

  return <>{parts}</>;
}

// ─── Highlight application helper ────────────────────────────────────────────

/**
 * Build anchors and apply inline citation highlights to block-level children.
 * Pure function — no mutable shared state. Safe for React Strict Mode.
 */
function applyCitationHighlights(
  children: React.ReactNode,
  line: number | undefined,
  auditVisible: boolean,
  filteredByLine: Map<number, MatchedCitation[]>,
  hoveredCitationId: number | null,
  onHover: (id: number | null) => void,
  onTap?: (citation: MatchedCitation) => void,
  skipFallbacks = false,
): React.ReactNode {
  if (!line || !auditVisible) return children;
  const cits = filteredByLine.get(line);
  if (!cits || cits.length === 0) return children;

  const anchors: AnchorMatch[] = cits.map((c) => {
    const [primary, fallback] = extractHighlightAnchors(c);
    return { anchor: primary.toLowerCase(), fallbackAnchor: fallback?.toLowerCase(), citation: c, consumed: false };
  });

  // Pass 1: try primary anchors
  let result = processChildren(children, anchors, hoveredCitationId, onHover, onTap);

  // Pass 2: retry unconsumed with fallback anchors (shorter, number-only)
  const unconsumedWithFallback = anchors.filter((a) => !a.consumed && a.fallbackAnchor);
  if (unconsumedWithFallback.length > 0) {
    const retryAnchors: AnchorMatch[] = unconsumedWithFallback.map((a) => ({
      anchor: a.fallbackAnchor!,
      citation: a.citation,
      consumed: false,
    }));
    result = processChildren(result, retryAnchors, hoveredCitationId, onHover, onTap);
    for (const ra of retryAnchors) {
      if (ra.consumed) {
        const orig = anchors.find((a) => a.citation.id === ra.citation.id);
        if (orig) orig.consumed = true;
      }
    }
  }

  // Add fallback superscripts for anchors that couldn't be matched to text
  const unconsumed = anchors.filter((a) => !a.consumed);
  if (unconsumed.length === 0 || skipFallbacks) return result;

  return (
    <>
      {result}
      {unconsumed.map((a) => (
        <FallbackSup
          key={`fb-${a.citation.id}`}
          citation={a.citation}
          isHovered={hoveredCitationId === a.citation.id}
          onHover={onHover}
          onTap={onTap}
        />
      ))}
    </>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

interface CitationOverlayProps {
  markdown: string;
  citationsByLine: Map<number, MatchedCitation[]>;
  auditVisible: boolean;
  activeFilter: string | null;
  className?: string;
  containerRef?: React.RefObject<HTMLDivElement | null>;
  onBadgeTap?: (citation: MatchedCitation) => void;
  hoveredCitationId?: number | null;
  onHoverCitation?: (id: number | null) => void;
  clickedCitationId?: number | null;
}

export const CitationOverlay = memo(function CitationOverlay({
  markdown,
  citationsByLine,
  auditVisible,
  activeFilter,
  className,
  containerRef,
  onBadgeTap,
  hoveredCitationId: externalHoveredId,
  onHoverCitation,
  clickedCitationId,
}: CitationOverlayProps) {
  const [internalHoveredId, setInternalHoveredId] = useState<number | null>(null);
  const hoveredCitationId = externalHoveredId ?? internalHoveredId;
  const setHoveredCitationId = onHoverCitation ?? setInternalHoveredId;

  // Filter citations by verdict if active
  const filteredByLine = useMemo<Map<number, MatchedCitation[]>>(() => {
    if (!activeFilter) return citationsByLine;
    const filtered = new Map<number, MatchedCitation[]>();
    for (const [line, cits] of citationsByLine) {
      const matching = cits.filter((c) => c.verdict === activeFilter);
      if (matching.length > 0) filtered.set(line, matching);
    }
    return filtered;
  }, [citationsByLine, activeFilter]);

  // Shared args for applyCitationHighlights closures
  const highlight = (children: React.ReactNode, line: number | undefined, skipFallbacks = false) =>
    applyCitationHighlights(children, line, auditVisible, filteredByLine, hoveredCitationId, setHoveredCitationId, onBadgeTap, skipFallbacks);

  const components: Components = {
    h1: ({ children, node, ...props }) => {
      const line = node?.position?.start.line;
      return (
        <h1
          className="text-2xl font-bold text-text-primary mt-8 mb-4 pb-2 border-b border-border"
          data-source-line={line}
          {...props}
        >
          {highlight(children, line)}
        </h1>
      );
    },
    h2: ({ children, node, ...props }) => {
      const line = node?.position?.start.line;
      return (
        <h2
          className="text-xl font-semibold text-text-primary mt-6 mb-3"
          data-source-line={line}
          {...props}
        >
          {highlight(children, line)}
        </h2>
      );
    },
    h3: ({ children, node, ...props }) => {
      const line = node?.position?.start.line;
      return (
        <h3
          className="text-lg font-medium text-text-primary mt-5 mb-2"
          data-source-line={line}
          {...props}
        >
          {highlight(children, line)}
        </h3>
      );
    },
    h4: ({ children, node, ...props }) => {
      const line = node?.position?.start.line;
      return (
        <h4
          className="text-base font-medium text-text-secondary mt-4 mb-2"
          data-source-line={line}
          {...props}
        >
          {highlight(children, line)}
        </h4>
      );
    },
    p: ({ children, node, ...props }) => {
      const line = node?.position?.start.line;
      return (
        <p
          className="text-text-primary leading-7 mb-4"
          data-source-line={line}
          {...props}
        >
          {highlight(children, line)}
        </p>
      );
    },
    li: ({ children, node, ...props }) => {
      const line = node?.position?.start.line;
      // Only highlight if li has NO nested <p> child (which handles its own citations).
      // When li wraps a <p>, both share the same source line — let <p> handle it.
      const hasNestedP = node?.children?.some((c: HastNode) => c.tagName === "p");
      return (
        <li
          className="text-text-primary leading-7"
          data-source-line={line}
          {...props}
        >
          {hasNestedP ? children : highlight(children, line, true)}
        </li>
      );
    },
    ul: ({ children, ...props }) => (
      <ul className="list-disc list-outside ml-6 mb-4 space-y-1 text-text-primary" {...props}>
        {children}
      </ul>
    ),
    ol: ({ children, ...props }) => (
      <ol className="list-decimal list-outside ml-6 mb-4 space-y-1 text-text-primary" {...props}>
        {children}
      </ol>
    ),
    blockquote: ({ children, node, ...props }) => {
      const line = node?.position?.start.line;
      return (
        <blockquote
          className="border-l-4 border-accent/40 pl-4 my-4 text-text-secondary italic"
          data-source-line={line}
          {...props}
        >
          {children}
        </blockquote>
      );
    },
    code: ({ className: codeClassName, children, ...props }) => {
      const isBlock = codeClassName?.includes("language-");
      if (isBlock) {
        return (
          <code className={`${codeClassName} block`} {...props}>
            {children}
          </code>
        );
      }
      return (
        <code className="bg-surface px-1.5 py-0.5 rounded text-sm font-mono text-accent" {...props}>
          {children}
        </code>
      );
    },
    pre: ({ children, ...props }) => (
      <pre className="bg-background border border-border rounded-lg p-4 overflow-x-auto mb-4 text-sm font-mono" {...props}>
        {children}
      </pre>
    ),
    table: ({ children, ...props }) => (
      <div className="overflow-x-auto mb-4">
        <table className="w-full text-sm border-collapse" {...props}>
          {children}
        </table>
      </div>
    ),
    thead: ({ children, ...props }) => (
      <thead className="border-b border-border" {...props}>{children}</thead>
    ),
    th: ({ children, ...props }) => (
      <th className="text-left px-3 py-2 font-medium text-text-secondary" {...props}>{children}</th>
    ),
    td: ({ children, node, ...props }) => {
      const line = node?.position?.start.line;
      return (
        <td
          className="px-3 py-2 text-text-primary border-t border-border/50"
          data-source-line={line}
          {...props}
        >
          {highlight(children, line, true)}
        </td>
      );
    },
    tr: ({ children, node, ...props }) => {
      const line = node?.position?.start.line;
      return (
        <tr data-source-line={line} {...props}>{children}</tr>
      );
    },
    a: ({ children, href, ...props }) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-interactive hover:underline"
        {...props}
      >
        {children}
      </a>
    ),
    hr: (props) => <hr className="border-border my-6" {...props} />,
    strong: ({ children, ...props }) => (
      <strong className="font-semibold text-text-primary" {...props}>{children}</strong>
    ),
    em: ({ children, ...props }) => (
      <em className="italic text-text-secondary" {...props}>{children}</em>
    ),
  };

  return (
    <div
      ref={containerRef}
      className={cn("report-content relative", className)}
      data-testid="report-content"
    >
      <ClickedCitationContext.Provider value={clickedCitationId ?? null}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeSourceLines]}
          components={components}
        >
          {markdown}
        </ReactMarkdown>
      </ClickedCitationContext.Provider>
    </div>
  );
});
