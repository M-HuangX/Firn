"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/utils";
import type { NodeState } from "@/stores/pipeline-store";

export interface InputNodeData extends Record<string, unknown> {
  label: string;
  state: NodeState;
  ticker?: string;
}

function InputNodeComponent({ data }: NodeProps) {
  const { label, state, ticker } = data as unknown as InputNodeData;

  return (
    <div
      className={cn(
        "px-4 py-3 rounded-xl border-2 min-w-[120px] transition-all duration-500",
        state === "complete"
          ? "border-emerald-400 bg-emerald-900/50 text-emerald-100 shadow-[0_0_12px_rgba(16,185,129,0.3)]"
          : "border-slate-600 bg-slate-800/70 text-slate-400"
      )}
    >
      <div className="flex items-center gap-2">
        {state === "complete" ? (
          <svg
            className="w-4 h-4 text-emerald-400"
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
        ) : (
          <svg
            className="w-4 h-4 text-slate-400"
            viewBox="0 0 16 16"
            fill="none"
          >
            <path
              d="M8 2v12M2 8h12"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
        )}
        <span className="text-sm font-medium">{ticker || label}</span>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-slate-500 !w-2 !h-2 !border-0"
      />
    </div>
  );
}

export const InputNode = memo(InputNodeComponent);
