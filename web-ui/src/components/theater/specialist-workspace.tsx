"use client";

import { useEffect, useRef } from "react";
import { useTheaterStore } from "@/stores/pipeline-store";
import { ToolCallBubble } from "@/components/shared";

interface SpecialistWorkspaceProps {
  agentId: string;
}

export function SpecialistWorkspace({ agentId }: SpecialistWorkspaceProps) {
  const node = useTheaterStore((s) => s.nodes[agentId]);
  const selectToolCall = useTheaterStore((s) => s.selectToolCall);

  const scrollRef = useRef<HTMLDivElement>(null);

  if (!node) return null;

  const { toolCalls, state, elapsed_s, token_total, tool_count, auditVerdicts, auditActiveIndex } = node;

  // Auto-scroll to bottom when new tool calls arrive (during normal analysis)
  useEffect(() => {
    if (auditActiveIndex != null) return; // Audit scroll takes priority
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [toolCalls.length, auditActiveIndex]);

  // Auto-scroll to the tool call being audited
  useEffect(() => {
    if (auditActiveIndex == null) return;
    const el = scrollRef.current?.querySelector(`[data-tc-index="${auditActiveIndex}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [auditActiveIndex]);

  return (
    <div className="flex flex-col gap-2">
      {/* Tool calls list */}
      <div ref={scrollRef} className="overflow-y-auto max-h-[150px] flex flex-col gap-1 scrollbar-thin">
        {toolCalls.length === 0 && state === "active" && (
          <div className="text-[10px] text-slate-500 italic py-1">
            Waiting for tool calls...
          </div>
        )}
        {toolCalls.map((tc, i) => (
          <div key={`${tc.tool_name}-${i}`} data-tc-index={i}>
            <ToolCallBubble
              toolName={tc.tool_name}
              status={
                tc.success === undefined
                  ? "pending"
                  : tc.success
                    ? "success"
                    : "error"
              }
              durationS={tc.duration_s}
              inputPreview={tc.input}
              compact
              animate={state === "active"}
              onClick={() => selectToolCall(agentId, i)}
              auditVerdict={auditVerdicts?.[i]}
              auditActive={auditActiveIndex === i}
            />
          </div>
        ))}
      </div>

      {/* Stats footer */}
      {state === "complete" && (
        <div className="flex items-center gap-3 pt-1.5 border-t border-white/10 text-[10px] text-slate-400">
          {elapsed_s != null && <span>{elapsed_s.toFixed(1)}s</span>}
          {token_total != null && (
            <span>{token_total.toLocaleString()} tokens</span>
          )}
          {tool_count != null && (
            <span>
              {tool_count} tool{tool_count !== 1 ? "s" : ""}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
