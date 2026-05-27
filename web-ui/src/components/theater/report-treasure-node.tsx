"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { ReportTreasure } from "@/components/shared";
import { useTheaterStore, type NodeState } from "@/stores/pipeline-store";
import { AuditHalo } from "./audit-halo";

export interface ReportTreasureNodeData extends Record<string, unknown> {
  state: NodeState;
  hasAudit?: boolean;
}

const STATE_TO_STATUS: Record<NodeState, "idle" | "generating" | "ready"> = {
  idle: "idle",
  active: "generating",
  complete: "ready",
  error: "idle",
};

function CheckBadge() {
  return (
    <div className="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-emerald-500 border-2 border-surface flex items-center justify-center shadow-md">
      <svg
        className="w-3.5 h-3.5 text-white"
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
    </div>
  );
}

function ReportTreasureNodeComponent({ data }: NodeProps) {
  const { state, hasAudit } = data as unknown as ReportTreasureNodeData;
  const openReportOverlay = useTheaterStore((s) => s.openReportOverlay);
  const auditNode = useTheaterStore((s) => s.nodes.audit);

  const status = STATE_TO_STATUS[state];
  const isReady = state === "complete";

  const auditState = auditNode?.state ?? "idle";
  const auditToolCalls = auditNode?.toolCalls ?? [];

  // Show check badge when audit is complete (from SSE) or pre-existing (from API)
  const showBadge = (hasAudit && isReady) || auditState === "complete";

  return (
    <div className="relative p-2">
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-slate-500 !w-2 !h-2 !border-0"
      />

      <ReportTreasure
        status={status}
        onClick={isReady ? openReportOverlay : undefined}
        className="min-w-[160px]"
      />

      {showBadge && <CheckBadge />}

      {/* Audit halo: shows during and after audit */}
      {isReady && auditState !== "idle" && (
        <AuditHalo
          auditState={auditState}
          toolCalls={auditToolCalls}
          claimCount={auditNode?.tool_count}
        />
      )}
    </div>
  );
}

export const ReportTreasureNode = memo(ReportTreasureNodeComponent);
