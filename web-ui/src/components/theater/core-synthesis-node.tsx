"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/utils";
import { useTheaterStore, type NodeState } from "@/stores/pipeline-store";
import { SpecialistWorkspace } from "./specialist-workspace";
import { KBOrb } from "./kb-orb";

export interface CoreNodeData extends Record<string, unknown> {
  label: string;
  state: NodeState;
  elapsed_s?: number;
  token_total?: number;
  tool_count?: number;
}

const stateStyles: Record<NodeState, string> = {
  idle: "border-slate-600 bg-slate-800/70 text-slate-400",
  active:
    "border-violet-400 bg-violet-900/40 text-violet-100 shadow-[0_0_15px_rgba(139,92,246,0.4)] animate-pulse",
  complete:
    "border-violet-400/70 bg-violet-900/30 text-violet-100 shadow-[0_0_12px_rgba(139,92,246,0.25)]",
  error:
    "border-red-400 bg-red-900/50 text-red-200 shadow-[0_0_12px_rgba(248,81,73,0.3)] animate-pulse",
};

function CoreSynthesisNodeComponent({ data }: NodeProps) {
  const { label, state, elapsed_s, token_total } =
    data as unknown as CoreNodeData;

  const node = useTheaterStore((s) => s.nodes.core);
  const isComplete = useTheaterStore((s) => s.isComplete);
  const hasToolCalls = (node?.toolCalls?.length ?? 0) > 0;
  const showWorkspace = hasToolCalls || state === "active" || state === "complete";
  const auditHighlight = node?.auditHighlight ?? false;
  const auditHighlightSource = node?.auditHighlightSource;
  const kbReads = node?.kbReads ?? 0;
  const kbWrites = node?.kbWrites ?? 0;
  const kbActiveOp = node?.kbActiveOp ?? null;
  const kbSectionOps = node?.kbSectionOps;
  const kbActiveSection = node?.kbActiveSection;
  const webSearchActive = node?.webSearchActive ?? false;
  const webSearchCount = node?.webSearchCount ?? 0;

  return (
    <div
      aria-label={`${label} — ${state}`}
      className={cn(
        "rounded-xl border-2 transition-all duration-500",
        stateStyles[state],
        auditHighlight && auditHighlightSource === "r2a" && "!border-indigo-400 !shadow-[0_0_20px_rgba(99,102,241,0.5),0_0_40px_rgba(99,102,241,0.2)]",
        auditHighlight && auditHighlightSource === "r2b" && "!border-cyan-400 !shadow-[0_0_20px_rgba(34,211,238,0.4),0_0_40px_rgba(34,211,238,0.15)]",
        auditHighlight && (!auditHighlightSource || auditHighlightSource === "r1") && "!border-violet-400 !shadow-[0_0_20px_rgba(139,92,246,0.5),0_0_40px_rgba(139,92,246,0.2)]",
        showWorkspace
          ? "p-3 w-[300px]"
          : "px-5 py-4 min-w-[150px] min-h-[90px] flex flex-col justify-center"
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-slate-500 !w-2 !h-2 !border-0"
      />

      {/* Label */}
      <div className="flex items-center gap-2">
        {state === "active" ? (
          <div className="w-3 h-3 rounded-full border-2 border-violet-400 border-t-transparent animate-spin" />
        ) : state === "complete" ? (
          <svg
            className="w-3.5 h-3.5 text-violet-300"
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
        ) : state === "error" ? (
          <svg
            className="w-3.5 h-3.5 text-red-400"
            viewBox="0 0 16 16"
            fill="none"
          >
            <path
              d="M4 4l8 8M12 4l-8 8"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
        ) : (
          <div className="w-2.5 h-2.5 rounded-full bg-slate-500" />
        )}
        <span className="text-sm font-semibold">{label}</span>
      </div>

      {/* KB Constellation */}
      {(state !== "idle" || kbReads > 0 || kbWrites > 0) && (
        <div className="flex justify-center mt-2">
          <KBOrb
            reads={kbReads}
            writes={kbWrites}
            activeOp={kbActiveOp}
            sectionOps={kbSectionOps}
            activeSection={kbActiveSection}
            webSearchActive={webSearchActive}
            webSearchCount={webSearchCount}
            pipelineComplete={isComplete}
          />
        </div>
      )}

      {/* Tool calls workspace */}
      {showWorkspace && (
        <div className="mt-2">
          <SpecialistWorkspace agentId="core" />
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

export const CoreSynthesisNode = memo(CoreSynthesisNodeComponent);
