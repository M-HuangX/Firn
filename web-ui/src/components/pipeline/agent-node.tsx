"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/utils";
import type { NodeState } from "@/stores/pipeline-store";

export interface AgentNodeData extends Record<string, unknown> {
  label: string;
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

function AgentNodeComponent({ data }: NodeProps) {
  const { label, state, elapsed_s, tool_count } =
    data as unknown as AgentNodeData;

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`${label} agent — ${state}`}
      className={cn(
        "px-4 py-3 rounded-xl border-2 min-w-[130px] transition-all duration-500 cursor-pointer focus:outline-none focus:ring-2 focus:ring-interactive/50",
        stateStyles[state]
      )}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-slate-500 !w-2 !h-2 !border-0"
      />
      <div className="flex items-center gap-2">
        {stateIcons[state]}
        <span className="text-sm font-medium capitalize">{label}</span>
      </div>
      {(state === "active" || state === "complete") &&
        (elapsed_s != null || tool_count != null) && (
          <div className="mt-1.5 flex gap-2 text-[10px] opacity-80">
            {elapsed_s != null && <span>{elapsed_s.toFixed(1)}s</span>}
            {tool_count != null && <span>{tool_count} tools</span>}
          </div>
        )}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-slate-500 !w-2 !h-2 !border-0"
      />
    </div>
  );
}

export const AgentNode = memo(AgentNodeComponent);
