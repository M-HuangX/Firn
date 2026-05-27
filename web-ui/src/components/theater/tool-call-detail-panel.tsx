"use client";

import { useEffect } from "react";
import { m, AnimatePresence } from "motion/react";
import { cn } from "@/lib/utils";
import { useTheaterStore } from "@/stores/pipeline-store";
import { useAnalysisToolCalls } from "@/hooks/use-api";
import { ToolOutputRenderer } from "./tool-output-renderer";

// KB tool classification for visual styling
const KB_READ_TOOLS = new Set([
  "kb_search", "kb_read", "kb_read_core_mind", "kb_list", "read_inbox_item",
]);
const KB_WRITE_TOOLS = new Set([
  "kb_write", "kb_write_core_mind", "kb_edit", "kb_archive", "kb_log",
]);

function getToolCategory(name: string): "kb-read" | "kb-write" | "tool" {
  if (KB_READ_TOOLS.has(name)) return "kb-read";
  if (KB_WRITE_TOOLS.has(name)) return "kb-write";
  return "tool";
}

const categoryLabel: Record<string, string> = {
  "kb-read": "KB Read",
  "kb-write": "KB Write",
  "tool": "Tool",
};

const categoryColor: Record<string, string> = {
  "kb-read": "text-cyan-400",
  "kb-write": "text-emerald-400",
  "tool": "text-amber-400",
};

interface ToolCallDetailPanelProps {
  execId: string;
}

export function ToolCallDetailPanel({ execId }: ToolCallDetailPanelProps) {
  const selectedToolCall = useTheaterStore((s) => s.selectedToolCall);
  const clearSelection = useTheaterStore((s) => s.clearToolCallSelection);
  const storeNodes = useTheaterStore((s) => s.nodes);

  // Fetch tool call trace data (lazy — only when panel would open)
  const { data: traceData } = useAnalysisToolCalls(selectedToolCall ? execId : null);

  // ESC key to close
  useEffect(() => {
    if (!selectedToolCall) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") clearSelection();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selectedToolCall, clearSelection]);

  // Get the SSE-derived tool call entry
  const sseEntry = selectedToolCall
    ? storeNodes[selectedToolCall.agent]?.toolCalls[selectedToolCall.index]
    : null;

  // Get the trace-derived full data (matched by tool_name occurrence)
  // Backend returns { "fundamental": [...], "core_analysis": [...] }
  // Store maps core_analysis -> core, so we need to reverse-map
  const traceAgentKey = selectedToolCall?.agent === "core" ? "core_analysis" : selectedToolCall?.agent;
  const traceEntry = (() => {
    if (!traceData || !traceAgentKey || !selectedToolCall || !sseEntry) return null;
    const traceCalls = traceData[traceAgentKey];
    if (!traceCalls) return null;
    // Count how many times this tool_name appears before the selected index
    const agentCalls = storeNodes[selectedToolCall.agent]?.toolCalls ?? [];
    let occurrence = 0;
    for (let i = 0; i < selectedToolCall.index; i++) {
      if (agentCalls[i].tool_name === sseEntry.tool_name) occurrence++;
    }
    // Find the same occurrence in trace data
    let count = 0;
    for (const tc of traceCalls) {
      if (tc.tool_name === sseEntry.tool_name) {
        if (count === occurrence) return tc;
        count++;
      }
    }
    return null;
  })();

  // Use trace data when available, fall back to SSE data
  const toolName = sseEntry?.tool_name ?? traceEntry?.tool_name ?? "Unknown";
  const category = getToolCategory(toolName);
  const status = sseEntry?.success === undefined ? "pending" : sseEntry.success ? "success" : "error";
  const duration = sseEntry?.duration_s ?? traceEntry?.duration_seconds;

  // Input: prefer trace (full), fall back to SSE (truncated)
  const input = traceEntry?.input ?? sseEntry?.input;
  // Output: only from trace
  const output = traceEntry?.output;
  const error = traceEntry?.error;

  return (
    <AnimatePresence>
      {selectedToolCall && sseEntry && (
        <div key={`${selectedToolCall.agent}-${selectedToolCall.index}`}>
          {/* Backdrop */}
          <div
            className="absolute inset-0 z-40"
            onClick={clearSelection}
            aria-hidden="true"
          />
          {/* Panel */}
          <m.div
            initial={{ x: "100%", opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: "100%", opacity: 0 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="absolute top-0 right-0 bottom-0 z-50 w-[400px] bg-surface border-l border-border flex flex-col shadow-2xl"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <div className="flex items-center gap-2 min-w-0">
                <span className={cn("text-[10px] font-medium uppercase tracking-wider", categoryColor[category])}>
                  {categoryLabel[category]}
                </span>
                <span className="font-mono text-sm text-text-primary truncate">
                  {toolName}
                </span>
              </div>
              <button
                onClick={clearSelection}
                className="text-text-secondary hover:text-text-primary transition-colors p-1"
                aria-label="Close panel"
              >
                <svg className="w-4 h-4" viewBox="0 0 16 16" fill="none">
                  <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
              </button>
            </div>

            {/* Meta row */}
            <div className="flex items-center gap-4 px-4 py-2 text-xs text-text-secondary border-b border-border/50">
              <span className="capitalize">{selectedToolCall.agent}</span>
              <div className="flex items-center gap-1.5">
                <div className={cn(
                  "w-2 h-2 rounded-full",
                  status === "pending" && "bg-blue-400 animate-pulse",
                  status === "success" && "bg-emerald-400",
                  status === "error" && "bg-red-400",
                )} />
                <span className="capitalize">{status}</span>
              </div>
              {duration != null && <span>{duration.toFixed(2)}s</span>}
              {sseEntry.output_length != null && (
                <span>{sseEntry.output_length.toLocaleString()} chars</span>
              )}
            </div>

            {/* Scrollable content */}
            <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4 scrollbar-thin">
              {/* Input section */}
              <section>
                <h3 className="text-[10px] uppercase tracking-wider text-text-secondary mb-2 font-medium">Input</h3>
                <pre className="text-xs font-mono text-text-primary bg-background rounded-lg p-3 overflow-x-auto whitespace-pre-wrap break-words border border-border/50 max-h-[300px] overflow-y-auto">
                  {input ?? "\u2014"}
                </pre>
              </section>

              {/* Output section */}
              {(output || error) && (
                <section>
                  <h3 className={cn(
                    "text-[10px] uppercase tracking-wider mb-2 font-medium",
                    error ? "text-red-400" : "text-text-secondary"
                  )}>
                    {error ? "Error" : "Output"}
                  </h3>
                  {error ? (
                    <pre className="text-xs font-mono rounded-lg p-3 overflow-x-auto whitespace-pre-wrap break-words border max-h-[400px] overflow-y-auto text-red-300 bg-red-950/30 border-red-900/50">
                      {error}
                    </pre>
                  ) : (
                    <ToolOutputRenderer output={output!} />
                  )}
                </section>
              )}

              {/* Loading state for trace data */}
              {!traceData && selectedToolCall && (
                <div className="text-xs text-text-secondary italic">
                  Loading full tool call data...
                </div>
              )}

              {/* No trace data available */}
              {traceData && !traceEntry && (
                <div className="text-xs text-text-secondary italic">
                  Detailed trace data not available for this tool call.
                </div>
              )}
            </div>
          </m.div>
        </div>
      )}
    </AnimatePresence>
  );
}
