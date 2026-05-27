"use client";

import { useEffect } from "react";
import { usePipelineStore } from "@/stores/pipeline-store";
import { cn } from "@/lib/utils";
import type { NodeData, ToolCallEntry } from "@/stores/pipeline-store";

const stateLabels: Record<string, string> = {
  idle: "Waiting",
  active: "Running",
  complete: "Complete",
  error: "Failed",
};

const stateColors: Record<string, string> = {
  idle: "text-slate-400",
  active: "text-blue-400",
  complete: "text-emerald-400",
  error: "text-red-400",
};

export function AgentDetailPanel() {
  const { selectedNodeId, nodes, selectNode } = usePipelineStore();

  // ESC to close
  useEffect(() => {
    if (!selectedNodeId) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") selectNode(null);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [selectedNodeId, selectNode]);

  if (!selectedNodeId) return null;

  const nodeData: NodeData | undefined = nodes[selectedNodeId];
  if (!nodeData) return null;

  return (
    <>
    {/* Backdrop */}
    <div
      className="fixed inset-0 z-40"
      onClick={() => selectNode(null)}
      aria-hidden="true"
    />
    <div className="fixed right-0 top-0 h-full w-[min(380px,90vw)] bg-surface border-l border-border z-50 shadow-2xl flex flex-col animate-[slideInRight_200ms_ease-out]">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-border">
        <div className="flex items-center gap-3">
          <h3 className="text-base font-semibold capitalize text-text-primary">
            {selectedNodeId}
          </h3>
          <span className={cn("text-xs font-medium", stateColors[nodeData.state])}>
            {stateLabels[nodeData.state]}
          </span>
        </div>
        <button
          onClick={() => selectNode(null)}
          className="w-7 h-7 flex items-center justify-center rounded-md hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
          aria-label="Close panel"
        >
          <svg className="w-4 h-4" viewBox="0 0 16 16" fill="none">
            <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      {/* Stats */}
      {nodeData.state === "complete" && (
        <div className="grid grid-cols-3 gap-3 p-4 border-b border-border">
          {nodeData.elapsed_s != null && (
            <StatCard label="Duration" value={`${nodeData.elapsed_s.toFixed(1)}s`} />
          )}
          {nodeData.token_total != null && (
            <StatCard label="Tokens" value={formatNumber(nodeData.token_total)} />
          )}
          {nodeData.tool_count != null && (
            <StatCard label="Tool Calls" value={String(nodeData.tool_count)} />
          )}
        </div>
      )}

      {/* Tool Calls List */}
      <div className="flex-1 overflow-y-auto scrollbar-thin p-4 pb-8">
        <h4 className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-3">
          Tool Calls ({nodeData.toolCalls.length})
        </h4>
        {nodeData.toolCalls.length === 0 ? (
          <p className="text-sm text-slate-500">
            {nodeData.state === "idle"
              ? "Agent has not started yet"
              : nodeData.state === "active"
              ? "Waiting for tool call events..."
              : "No tool calls recorded"}
          </p>
        ) : (
          <div className="space-y-2">
            {nodeData.toolCalls.map((call, i) => (
              <ToolCallRow key={i} call={call} />
            ))}
          </div>
        )}
      </div>
    </div>
    </>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-background rounded-lg p-2.5 text-center">
      <div className="text-sm font-mono font-semibold text-text-primary">{value}</div>
      <div className="text-[10px] text-slate-500 mt-0.5">{label}</div>
    </div>
  );
}

function ToolCallRow({ call }: { call: ToolCallEntry }) {
  const success = call.success;
  const isDone = call.duration_s !== undefined;

  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-background border border-border">
      {/* Status dot */}
      <div
        className={cn(
          "w-2 h-2 rounded-full shrink-0",
          !isDone
            ? "bg-blue-400 animate-pulse"
            : success
            ? "bg-emerald-400"
            : "bg-red-400"
        )}
      />
      {/* Tool name */}
      <span className="text-xs font-mono text-text-primary truncate flex-1">
        {call.tool_name}
      </span>
      {/* Duration */}
      {call.duration_s != null && (
        <span className="text-[10px] text-slate-500 shrink-0">
          {call.duration_s.toFixed(1)}s
        </span>
      )}
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}
