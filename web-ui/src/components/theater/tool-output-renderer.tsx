"use client";

import { useState, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

// ─── Content extraction ─────────────────────────────────────────────────────

/**
 * Extract actual text content from the Python repr wrapper format:
 *   content=[{'type': 'text', 'text': '...'}] name='...' tool_call_id='...' artifact={...}
 *   content='...' name='...' tool_call_id='...'
 */
function extractContent(raw: string): string {
  // Pattern 1: content=[{'type': 'text', 'text': '...'}]
  const listMatch = raw.match(/^content=\[\{.*?'text':\s*'([\s\S]*?)'\s*(?:,\s*'id'.*?)?\}\]\s*name=/);
  if (listMatch) {
    return unescapePython(listMatch[1]);
  }

  // Pattern 2: try to find the text field more robustly using a greedy approach
  // Look for 'text': ' then grab everything until the closing pattern
  const textFieldMatch = raw.match(/^content=\[\{[^}]*'text':\s*'([\s\S]+)'\s*(?:,\s*'id':\s*'[^']*')?\s*\}\]\s*name=/);
  if (textFieldMatch) {
    return unescapePython(textFieldMatch[1]);
  }

  // Pattern 3: content='...' name='...'
  const strMatch = raw.match(/^content='([\s\S]*?)'\s*name=/);
  if (strMatch) {
    return unescapePython(strMatch[1]);
  }

  // Pattern 4: content="..." name='...' (double-quoted)
  const dblMatch = raw.match(/^content="([\s\S]*?)"\s*name=/);
  if (dblMatch) {
    return unescapePython(dblMatch[1]);
  }

  // Fallback: return as-is
  return raw;
}

function unescapePython(s: string): string {
  return s
    .replace(/\\n/g, "\n")
    .replace(/\\t/g, "\t")
    .replace(/\\'/g, "'")
    .replace(/\\"/g, '"')
    .replace(/\\\\/g, "\\");
}

// ─── Content type detection ─────────────────────────────────────────────────

type ContentType = "markdown" | "json" | "text";

function detectContentType(text: string): ContentType {
  const trimmed = text.trimStart();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      JSON.parse(trimmed);
      return "json";
    } catch {
      // might be truncated JSON, still try to render structured
      if (trimmed.startsWith("{")) return "json";
    }
  }
  // Markdown indicators: starts with # heading, or contains markdown tables
  if (/^#\s/m.test(trimmed) || /^\|.*\|.*\|/m.test(trimmed)) {
    return "markdown";
  }
  return "text";
}

// ─── JSON Structured Renderer ───────────────────────────────────────────────

/** Detect if JSON is a financial statement (has periods[] + data{}) */
function isFinancialStatement(obj: Record<string, unknown>): boolean {
  return Array.isArray(obj.periods) && typeof obj.data === "object" && obj.data !== null;
}

/** Render a financial statement as a time-series table */
function FinancialStatementTable({ obj }: { obj: Record<string, unknown> }) {
  const periods = obj.periods as string[];
  const data = obj.data as Record<string, (number | null)[]>;
  const ticker = obj._ticker as string | undefined;
  const periodType = obj.period_type as string | undefined;

  // Only show rows that have at least one non-null value
  const rows = Object.entries(data).filter(([, values]) =>
    values.some((v) => v !== null)
  );

  // Format period headers (show year or quarter)
  const formatPeriod = (p: string) => {
    if (!p) return p;
    const parts = p.split("-");
    if (periodType === "quarterly") return `${parts[0]}Q${Math.ceil(parseInt(parts[1]) / 3)}`;
    return parts[0]; // just year for annual
  };

  const formatValue = (v: number | null): string => {
    if (v === null) return "—";
    if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
    if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
    if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
    return v.toLocaleString();
  };

  return (
    <div className="space-y-2">
      {ticker && (
        <div className="text-xs text-text-secondary">
          {ticker} &middot; {periodType ?? "annual"}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="text-xs border-collapse">
          <thead>
            <tr className="border-b border-border/50">
              <th className="text-left py-1.5 pr-2 text-text-secondary font-medium sticky left-0 bg-background max-w-[120px] truncate">Metric</th>
              {periods.map((p) => (
                <th key={p} className="text-right py-1.5 px-1.5 text-text-secondary font-medium whitespace-nowrap">
                  {formatPeriod(p)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(([key, values]) => (
              <tr key={key} className="border-b border-border/20 hover:bg-white/[0.02]">
                <td className="py-1 pr-2 text-text-primary text-[11px] sticky left-0 bg-background max-w-[120px] truncate" title={formatMetricName(key)}>
                  {formatMetricName(key)}
                </td>
                {values.map((v, i) => (
                  <td key={i} className={cn(
                    "text-right py-1 px-1.5 font-mono text-[11px] whitespace-nowrap",
                    v === null ? "text-text-secondary" : v < 0 ? "text-red-400" : "text-text-primary"
                  )}>
                    {formatValue(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Convert camelCase/PascalCase metric names to readable form */
function formatMetricName(name: string): string {
  // Already spaced (e.g. "Total Revenue")
  if (name.includes(" ")) return name;
  // camelCase → spaced
  return name.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2");
}

/** Render grouped key-value JSON (e.g. financial metrics) */
function JsonKeyValueRenderer({ obj, depth = 0 }: { obj: Record<string, unknown>; depth?: number }) {
  const entries = Object.entries(obj).filter(([k]) => !k.startsWith("_"));

  // Separate scalar values from nested objects/arrays
  const scalars: [string, unknown][] = [];
  const nested: [string, unknown][] = [];

  for (const [k, v] of entries) {
    if (v === null || typeof v !== "object") {
      scalars.push([k, v]);
    } else if (Array.isArray(v)) {
      nested.push([k, v]);
    } else {
      nested.push([k, v]);
    }
  }

  return (
    <div className={cn("space-y-3", depth > 0 && "ml-2")}>
      {/* Scalar key-value pairs as a compact table */}
      {scalars.length > 0 && (
        <div className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-0.5 text-xs">
          {scalars.map(([k, v]) => (
            <KeyValueRow key={k} label={formatMetricName(k)} value={v} />
          ))}
        </div>
      )}

      {/* Nested sections */}
      {nested.map(([k, v]) => (
        <CollapsibleSection key={k} title={formatMetricName(k)} defaultOpen={depth < 1}>
          {Array.isArray(v) ? (
            <ArrayRenderer arr={v} />
          ) : (
            <JsonKeyValueRenderer obj={v as Record<string, unknown>} depth={depth + 1} />
          )}
        </CollapsibleSection>
      ))}
    </div>
  );
}

function KeyValueRow({ label, value }: { label: string; value: unknown }) {
  const formatted = formatScalar(value, label);
  return (
    <>
      <span className="text-text-secondary truncate">{label}</span>
      <span className={cn(
        "text-right font-mono",
        value === null ? "text-text-secondary" : typeof value === "number" && value < 0 ? "text-red-400" : "text-text-primary"
      )}>
        {formatted}
      </span>
    </>
  );
}

const PCT_KEYS = /margin|ratio|yield|growth|return|pct|change|coverage/i;

function formatScalar(v: unknown, key?: string): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
    if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
    // Only format as percentage when key name suggests it's a ratio/margin/yield
    if (key && PCT_KEYS.test(key) && Math.abs(v) <= 1 && v !== 0 && !Number.isInteger(v)) {
      return `${(v * 100).toFixed(2)}%`;
    }
    if (Number.isInteger(v)) return v.toLocaleString();
    return v.toFixed(4);
  }
  if (typeof v === "boolean") return v ? "Yes" : "No";
  return String(v);
}

/** Render arrays — detect if it's an array of objects (table) or primitives (list) */
function ArrayRenderer({ arr }: { arr: unknown[] }) {
  if (arr.length === 0) return <span className="text-xs text-text-secondary italic">Empty</span>;

  // Array of objects → table
  if (typeof arr[0] === "object" && arr[0] !== null && !Array.isArray(arr[0])) {
    const objects = arr as Record<string, unknown>[];
    const keys = Object.keys(objects[0]);
    // Limit to 20 rows for readability
    const displayRows = objects.slice(0, 20);
    const hasMore = objects.length > 20;

    return (
      <div className="space-y-1">
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="border-b border-border/50">
                {keys.map((k) => (
                  <th key={k} className="text-left py-1 px-2 text-text-secondary font-medium whitespace-nowrap">
                    {formatMetricName(k)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {displayRows.map((row, i) => (
                <tr key={i} className="border-b border-border/20 hover:bg-white/[0.02]">
                  {keys.map((k) => (
                    <td key={k} className="py-1 px-2 font-mono text-text-primary whitespace-nowrap">
                      {formatScalar(row[k])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {hasMore && (
          <div className="text-[10px] text-text-secondary italic">
            Showing 20 of {objects.length} rows
          </div>
        )}
      </div>
    );
  }

  // Array of primitives → simple list
  return (
    <div className="text-xs font-mono text-text-primary space-y-0.5">
      {arr.slice(0, 30).map((item, i) => (
        <div key={i}>{formatScalar(item)}</div>
      ))}
      {arr.length > 30 && (
        <div className="text-text-secondary italic">...and {arr.length - 30} more</div>
      )}
    </div>
  );
}

/** Collapsible section for nested JSON groups */
function CollapsibleSection({
  title,
  defaultOpen,
  children,
}: {
  title: string;
  defaultOpen: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-border/30 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-text-primary hover:bg-white/[0.02] transition-colors"
      >
        <svg
          className={cn("w-3 h-3 text-text-secondary transition-transform", open && "rotate-90")}
          viewBox="0 0 12 12"
          fill="none"
        >
          <path d="M4 2l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
        {title}
      </button>
      {open && <div className="px-3 pb-2">{children}</div>}
    </div>
  );
}

// ─── Markdown Renderer ──────────────────────────────────────────────────────

const mdComponents = {
  h1: ({ children, ...props }: React.ComponentProps<"h1">) => (
    <h1 className="text-sm font-bold text-text-primary mt-3 mb-1.5" {...props}>{children}</h1>
  ),
  h2: ({ children, ...props }: React.ComponentProps<"h2">) => (
    <h2 className="text-xs font-bold text-text-primary mt-2.5 mb-1" {...props}>{children}</h2>
  ),
  h3: ({ children, ...props }: React.ComponentProps<"h3">) => (
    <h3 className="text-xs font-semibold text-text-primary mt-2 mb-1" {...props}>{children}</h3>
  ),
  p: ({ children, ...props }: React.ComponentProps<"p">) => (
    <p className="text-xs text-text-primary mb-1.5 leading-relaxed" {...props}>{children}</p>
  ),
  strong: ({ children, ...props }: React.ComponentProps<"strong">) => (
    <strong className="font-semibold text-text-primary" {...props}>{children}</strong>
  ),
  ul: ({ children, ...props }: React.ComponentProps<"ul">) => (
    <ul className="text-xs text-text-primary ml-3 mb-1.5 list-disc space-y-0.5" {...props}>{children}</ul>
  ),
  li: ({ children, ...props }: React.ComponentProps<"li">) => (
    <li className="text-xs text-text-primary" {...props}>{children}</li>
  ),
  table: ({ children, ...props }: React.ComponentProps<"table">) => (
    <div className="overflow-x-auto my-2">
      <table className="w-full text-xs border-collapse" {...props}>{children}</table>
    </div>
  ),
  thead: ({ children, ...props }: React.ComponentProps<"thead">) => (
    <thead className="border-b border-border/50" {...props}>{children}</thead>
  ),
  th: ({ children, ...props }: React.ComponentProps<"th">) => (
    <th className="text-left py-1 px-2 text-text-secondary font-medium whitespace-nowrap" {...props}>{children}</th>
  ),
  td: ({ children, ...props }: React.ComponentProps<"td">) => (
    <td className="py-1 px-2 font-mono text-text-primary whitespace-nowrap border-b border-border/20" {...props}>{children}</td>
  ),
  tr: ({ children, ...props }: React.ComponentProps<"tr">) => (
    <tr className="hover:bg-white/[0.02]" {...props}>{children}</tr>
  ),
  em: ({ children, ...props }: React.ComponentProps<"em">) => (
    <em className="text-text-secondary" {...props}>{children}</em>
  ),
};

function MarkdownRenderer({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
      {text}
    </ReactMarkdown>
  );
}

// ─── Plain Text Renderer ────────────────────────────────────────────────────

function PlainTextRenderer({ text }: { text: string }) {
  // Detect numbered list pattern: "1. item\n2. item\n..."
  const isNumberedList = /^\d+\.\s/m.test(text);
  // Detect search results: "[1] Title\n    URL: ...\n    snippet"
  const isSearchResults = /^\[\d+\]\s/.test(text.trim());

  if (isSearchResults) {
    return <SearchResultsRenderer text={text} />;
  }

  if (isNumberedList) {
    const items = text.split(/\n/).filter(Boolean);
    return (
      <div className="space-y-0.5">
        {items.map((item, i) => {
          const match = item.match(/^(\d+)\.\s(.+)/);
          if (!match) return <div key={i} className="text-xs text-text-primary">{item}</div>;
          return (
            <div key={i} className="flex gap-2 text-xs">
              <span className="text-text-secondary font-mono w-5 text-right shrink-0">{match[1]}.</span>
              <span className="text-text-primary font-mono">{match[2]}</span>
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <pre className="text-xs font-mono text-text-primary whitespace-pre-wrap break-words leading-relaxed">
      {text}
    </pre>
  );
}

function SearchResultsRenderer({ text }: { text: string }) {
  // Parse "Search results for: query\n\n[1] Title\n    URL: ...\n    snippet"
  const lines = text.split("\n");
  const headerLine = lines[0];
  const results: { title: string; url: string; snippet: string }[] = [];

  let current: { title: string; url: string; snippet: string } | null = null;
  for (let i = 1; i < lines.length; i++) {
    const titleMatch = lines[i].match(/^\[(\d+)\]\s(.+)/);
    if (titleMatch) {
      if (current) results.push(current);
      current = { title: titleMatch[2], url: "", snippet: "" };
    } else if (current) {
      const urlMatch = lines[i].match(/^\s+URL:\s(.+)/);
      if (urlMatch) {
        current.url = urlMatch[1];
      } else if (lines[i].trim()) {
        current.snippet += (current.snippet ? " " : "") + lines[i].trim();
      }
    }
  }
  if (current) results.push(current);

  return (
    <div className="space-y-3">
      {headerLine && (
        <div className="text-xs text-text-secondary italic">{headerLine}</div>
      )}
      {results.map((r, i) => (
        <div key={i} className="space-y-0.5">
          <div className="text-xs font-medium text-text-primary flex items-center gap-1.5">
            <span className="text-text-secondary font-mono">[{i + 1}]</span>
            {r.title}
          </div>
          {r.url && (
            <div className="text-[10px] text-cyan-400/70 font-mono truncate">{r.url}</div>
          )}
          {r.snippet && (
            <div className="text-[11px] text-text-secondary leading-relaxed line-clamp-2">{r.snippet}</div>
          )}
        </div>
      ))}
    </div>
  );
}

// ─── Main Component ─────────────────────────────────────────────────────────

interface ToolOutputRendererProps {
  output: string;
  className?: string;
}

export function ToolOutputRenderer({ output, className }: ToolOutputRendererProps) {
  const [showRaw, setShowRaw] = useState(false);

  const { content, contentType } = useMemo(() => {
    const extracted = extractContent(output);
    const type = detectContentType(extracted);
    return { content: extracted, contentType: type };
  }, [output]);

  const structuredView = useMemo(() => {
    if (contentType === "markdown") {
      return <MarkdownRenderer text={content} />;
    }

    if (contentType === "json") {
      try {
        const parsed = JSON.parse(content);
        if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
          // Financial statement detection
          if (isFinancialStatement(parsed)) {
            return <FinancialStatementTable obj={parsed} />;
          }
          return <JsonKeyValueRenderer obj={parsed} />;
        }
        if (Array.isArray(parsed)) {
          return <ArrayRenderer arr={parsed} />;
        }
      } catch {
        // JSON parse failed — fall through to plain text
      }
    }

    return <PlainTextRenderer text={content} />;
  }, [content, contentType]);

  return (
    <div className={cn("space-y-3", className)}>
      {/* Structured view */}
      <div className="bg-background rounded-lg p-3 border border-border/50 max-h-[500px] overflow-auto scrollbar-thin">
        {structuredView}
      </div>

      {/* Raw output toggle */}
      <div>
        <button
          onClick={() => setShowRaw(!showRaw)}
          className="flex items-center gap-1.5 text-[10px] text-text-secondary hover:text-text-primary transition-colors"
        >
          <svg
            className={cn("w-3 h-3 transition-transform", showRaw && "rotate-90")}
            viewBox="0 0 12 12"
            fill="none"
          >
            <path d="M4 2l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          {showRaw ? "Hide" : "Show"} Raw Output
        </button>
        {showRaw && (
          <pre className="mt-2 text-[10px] font-mono text-text-secondary bg-background rounded-lg p-3 overflow-x-auto whitespace-pre-wrap break-words border border-border/30 max-h-[300px] overflow-y-auto">
            {output}
          </pre>
        )}
      </div>
    </div>
  );
}
