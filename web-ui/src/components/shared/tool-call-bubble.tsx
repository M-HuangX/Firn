"use client";

import { m } from "motion/react";
import { cn } from "@/lib/utils";

interface AuditVerdictBadge {
  verdict: string;
  count: number;
}

interface ToolCallBubbleProps {
  toolName: string;
  status: "pending" | "success" | "error";
  durationS?: number;
  inputPreview?: string;
  compact?: boolean;
  animate?: boolean;
  onClick?: () => void;
  className?: string;
  /** v2: audit verdict badge for this tool call */
  auditVerdict?: AuditVerdictBadge;
  /** v2: true when this row is being audited (purple pulse) */
  auditActive?: boolean;
}

function getKBType(toolName: string): 'read' | 'write' | null {
  if (['kb_search', 'kb_read', 'kb_read_core_mind', 'kb_list', 'read_inbox_item'].includes(toolName)) return 'read';
  if (['kb_write', 'kb_write_core_mind', 'kb_edit', 'kb_archive', 'kb_log'].includes(toolName)) return 'write';
  return null;
}

function verdictBadge(v: AuditVerdictBadge) {
  const isBad = v.verdict === "misread" || v.verdict === "error";
  const isWeak = v.verdict === "unverified" || v.verdict === "llm-inferred"
    || v.verdict === "supported" || v.verdict === "derived-from-verified";
  const icon = isBad ? "\u2717" : "\u2713";
  const colorCls = isBad
    ? "bg-red-500/20 text-red-400"
    : isWeak
      ? "bg-amber-500/20 text-amber-400"
      : "bg-emerald-500/20 text-emerald-400";
  return (
    <span className={cn("inline-flex items-center gap-0.5 rounded-full px-1.5 py-0 text-[9px] font-medium shrink-0", colorCls)}>
      {icon}{v.count > 1 && v.count}
    </span>
  );
}

export function ToolCallBubble({
  toolName,
  status,
  durationS,
  inputPreview,
  compact = false,
  animate = true,
  onClick,
  className,
  auditVerdict,
  auditActive,
}: ToolCallBubbleProps) {
  const kbType = getKBType(toolName);

  const content = (
    <div
      onClick={onClick}
      className={cn(
        "flex items-center gap-2 rounded-lg bg-background border border-border",
        compact ? "px-2 py-1" : "px-3 py-2",
        onClick && "cursor-pointer hover:bg-white/5",
        kbType === 'read' && "border-l-2 border-l-cyan-500",
        kbType === 'write' && "border-l-2 border-l-emerald-500",
        auditActive && "!border-l-[3px] !border-l-violet-400 bg-violet-500/5 animate-[auditRowPulse_1.5s_ease-in-out_infinite]",
        className
      )}
    >
      {/* Status dot */}
      <div
        className={cn(
          "rounded-full shrink-0",
          compact ? "w-1.5 h-1.5" : "w-2 h-2",
          status === "pending" && "bg-blue-400 animate-pulse",
          status === "success" && "bg-emerald-400",
          status === "error" && "bg-red-400"
        )}
      />

      {/* Tool name and optional preview */}
      <div className="flex flex-col min-w-0 flex-1">
        <span
          className={cn(
            "font-mono text-text-primary truncate",
            compact ? "text-[10px]" : "text-xs"
          )}
        >
          {toolName}
        </span>
        {inputPreview && (
          <span
            className={cn(
              "text-text-secondary truncate",
              compact ? "text-[9px]" : "text-[10px]"
            )}
          >
            {inputPreview}
          </span>
        )}
      </div>

      {/* Duration */}
      {durationS != null && (
        <span
          className={cn(
            "text-slate-500 shrink-0",
            compact ? "text-[9px]" : "text-[10px]"
          )}
        >
          {durationS.toFixed(1)}s
        </span>
      )}

      {/* Audit verdict badge */}
      {auditVerdict && verdictBadge(auditVerdict)}
    </div>
  );

  if (animate) {
    return (
      <m.div
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
      >
        {content}
      </m.div>
    );
  }

  return content;
}
