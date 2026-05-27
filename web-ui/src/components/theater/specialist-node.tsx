"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/utils";
import { useTheaterStore, type NodeState } from "@/stores/pipeline-store";
import { SpecialistWorkspace } from "./specialist-workspace";

export interface SpecialistNodeData extends Record<string, unknown> {
  label: string;
  agentId: string; // e.g. "fundamental", "technical"
  state: NodeState;
  elapsed_s?: number;
  token_total?: number;
  tool_count?: number;
}

const stateStyles: Record<NodeState, string> = {
  idle: "border-slate-600 bg-slate-800/70 text-slate-400",
  active:
    "border-blue-400 bg-blue-900/60 text-blue-100 shadow-[0_0_15px_rgba(59,130,246,0.4)] animate-pulse",
  complete:
    "border-emerald-400 bg-emerald-900/50 text-emerald-100 shadow-[0_0_12px_rgba(16,185,129,0.3)]",
  error:
    "border-red-400 bg-red-900/50 text-red-200 shadow-[0_0_12px_rgba(248,81,73,0.3)] animate-pulse",
};

const stateIcons: Record<NodeState, React.ReactNode> = {
  idle: <div className="w-2.5 h-2.5 rounded-full bg-slate-500" />,
  active: (
    <div className="w-3 h-3 rounded-full border-2 border-blue-400 border-t-transparent animate-spin" />
  ),
  complete: (
    <svg
      className="w-3.5 h-3.5 text-emerald-400"
      viewBox="0 0 16 16"
      fill="none"
    >
      <path
        d="M3 8.5l3.5 3.5 6.5-7"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  ),
  error: (
    <svg className="w-3.5 h-3.5 text-red-400" viewBox="0 0 16 16" fill="none">
      <path
        d="M4 4l8 8M12 4l-8 8"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  ),
};

function SpecialistNodeComponent({ data }: NodeProps) {
  const { label, agentId, state, elapsed_s, tool_count } =
    data as unknown as SpecialistNodeData;

  const node = useTheaterStore((s) => s.nodes[agentId]);
  const hasToolCalls = (node?.toolCalls?.length ?? 0) > 0;
  const showWorkspace = hasToolCalls || state === "active" || state === "complete";
  const auditHighlight = node?.auditHighlight ?? false;
  const auditScanning = node?.auditScanning ?? false;
  const auditProgress = node?.auditProgress;
  const auditHighlightSource = node?.auditHighlightSource;

  return (
    <div
      aria-label={`${label} specialist — ${state}`}
      className={cn(
        "rounded-xl border-2 transition-all duration-500 relative overflow-hidden",
        stateStyles[state],
        auditHighlight && auditHighlightSource === "r2a" && "!border-indigo-400 !shadow-[0_0_20px_rgba(99,102,241,0.5),0_0_40px_rgba(99,102,241,0.2)]",
        auditHighlight && auditHighlightSource === "r2b" && "!border-cyan-400 !shadow-[0_0_20px_rgba(34,211,238,0.4),0_0_40px_rgba(34,211,238,0.15)]",
        auditHighlight && (!auditHighlightSource || auditHighlightSource === "r1") && "!border-violet-400 !shadow-[0_0_20px_rgba(139,92,246,0.5),0_0_40px_rgba(139,92,246,0.2)]",
        auditScanning && (
          auditHighlightSource === "r2a" ? "audit-scanning-indigo" :
          auditHighlightSource === "r2b" ? "audit-scanning-cyan" :
          "audit-scanning"
        ),
        showWorkspace ? "p-3 w-[300px]" : "px-4 py-3 min-w-[130px]"
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-slate-500 !w-2 !h-2 !border-0"
      />

      {/* Header row */}
      <div className="flex items-center gap-2">
        {stateIcons[state]}
        <span className="text-sm font-medium capitalize flex-1">{label}</span>
      </div>

      {/* Workspace (tool calls + stats) */}
      {showWorkspace && (
        <div className="mt-2">
          <SpecialistWorkspace agentId={agentId} />
        </div>
      )}

      {/* Audit progress footer (Round 1) */}
      {auditProgress && (auditProgress.total > 0 || auditProgress.current > 0) && (
        <div className={cn("mt-1.5 pt-1.5 border-t",
          auditHighlightSource === "r2a" ? "border-indigo-500/20" :
          auditHighlightSource === "r2b" ? "border-cyan-500/20" :
          "border-violet-500/20"
        )}>
          <div className="flex items-center gap-2 text-[10px]">
            {auditScanning && (
              <span className={cn(
                "animate-pulse",
                auditHighlightSource === "r2a" ? "text-indigo-400" :
                auditHighlightSource === "r2b" ? "text-cyan-400" :
                "text-violet-400"
              )}>{"\u25C8"}</span>
            )}
            <span className={cn(
              auditScanning
                ? (auditHighlightSource === "r2a" ? "text-indigo-300" :
                   auditHighlightSource === "r2b" ? "text-cyan-300" :
                   "text-violet-300")
                : "text-emerald-300"
            )}>
              {auditProgress.total > 0
                ? (auditProgress.currentClaim ?? `${auditProgress.current}/${auditProgress.total}`)
                : `${auditProgress.current} claims`}
            </span>
          </div>
          {/* Mini progress bar */}
          <div className="mt-1 h-1 rounded-full bg-slate-700/50 overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-300",
                auditScanning
                  ? (auditHighlightSource === "r2a" ? "bg-indigo-500" :
                     auditHighlightSource === "r2b" ? "bg-cyan-500" :
                     "bg-violet-500")
                  : "bg-emerald-500",
              )}
              style={{ width: `${auditProgress.total > 0
                ? (auditProgress.current / auditProgress.total) * 100
                : auditProgress.current > 0
                  ? (auditProgress.current / (auditProgress.current + 12)) * 85
                  : 0}%` }}
            />
          </div>
        </div>
      )}

      <Handle
        type="source"
        position={Position.Right}
        className="!bg-slate-500 !w-2 !h-2 !border-0"
      />
    </div>
  );
}

export const SpecialistNode = memo(SpecialistNodeComponent);
