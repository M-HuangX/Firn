"use client";

import { useEffect, useRef, useMemo } from "react";
import { motion, AnimatePresence } from "motion/react";
import { cn } from "@/lib/utils";
import {
  useTheaterStore,
  type ToolCallEntry,
  type NodeState,
  type AuditCitationEntry,
  type AuditProgress,
} from "@/stores/pipeline-store";

interface AuditHaloProps {
  auditState: NodeState;
  toolCalls: ToolCallEntry[];
  claimCount?: number;
}

/** Human-readable description for audit tool calls (v1 + v2) */
function formatAuditAction(toolName: string, input?: string): string {
  // v2 tools
  if (toolName === "read_tool_call") {
    const m = input?.match(/['"]?agent['"]?\s*[:=]\s*['"](\w+)['"]/);
    const agent = m?.[1];
    return agent ? `Reading ${agent} tool call...` : "Reading tool call...";
  }
  if (toolName === "read_trace_section") {
    const m = input?.match(/['"]?path['"]?\s*[:=]\s*['"]([^'"]+)['"]/);
    return m ? `Reading ${m[1]}...` : "Reading trace section...";
  }
  if (toolName === "record_specialist_claim") {
    return "Recording specialist claim...";
  }
  if (toolName === "record_citation") {
    return "Recording report citation...";
  }

  // v1 tools
  if (toolName === "list_trace_files") {
    if (input?.includes("verification")) return "Scanning verification files...";
    return "Scanning execution trace...";
  }
  if (toolName === "read_trace_file") {
    if (!input) return "Reading trace file...";
    if (input.includes("report.md") || input.includes("'report'"))
      return "Reading the final report...";
    if (input.includes("fundamental"))
      return "Reviewing Fundamental data...";
    if (input.includes("technical"))
      return "Reviewing Technical data...";
    if (input.includes("value")) return "Reviewing Value analysis...";
    if (input.includes("macro")) return "Reviewing Macro data...";
    if (input.includes("core_analysis"))
      return "Reviewing Firn analysis data...";
    if (input.includes("specialist_outputs"))
      return "Reading specialist output...";
    if (input.includes("verification"))
      return "Checking computation proofs...";
    const match = input.match(/['"]([^'"]+)['"]/);
    return match ? `Reading ${match[1]}...` : "Reading trace file...";
  }
  if (toolName === "grep_trace") {
    const match = input?.match(/['"]pattern['"]:\s*['"]([^'"]+)['"]/);
    if (match) return `Verifying: "${match[1]}"`;
    const simple = input?.match(/['"]([^'"]+)['"]/);
    if (simple) return `Verifying: "${simple[1]}"`;
    return "Searching trace data...";
  }
  return `${toolName}...`;
}

/** Verdict icon for citation entries */
function verdictIcon(verdict: string, cascade: boolean): string {
  if (verdict === "misread" || verdict === "error") return "\u2717";
  if (cascade) return "\uD83D\uDD17"; // 🔗 cascade
  return "\u26A1"; // ⚡ direct
}

function verdictColor(verdict: string): string {
  if (verdict === "misread" || verdict === "error") return "text-red-400";
  if (verdict === "unverified" || verdict === "llm-inferred" || verdict === "not-found") return "text-amber-400";
  return "text-emerald-400";
}

/** Per-specialist mini progress bar for Round 1 */
function SpecialistMiniProgress({
  name,
  progress,
  scanning,
}: {
  name: string;
  progress?: AuditProgress;
  scanning?: boolean;
}) {
  const label = name.charAt(0).toUpperCase();
  const current = progress?.current ?? 0;
  const total = progress?.total ?? 0;
  // Asymptotic curve: current/(current+K) — grows fast then slows, never reaches 100%
  // When total is known (specialist_end fired), snap to real ratio
  const K = 12;
  const pct = total > 0
    ? (current / total) * 100
    : current > 0 ? (current / (current + K)) * 85 : 0; // cap at 85% during scanning

  return (
    <div className="flex items-center gap-1.5">
      <span className={cn(
        "text-[9px] font-mono w-3 text-center",
        scanning ? "text-violet-400" : total > 0 || current > 0 ? "text-emerald-400" : "text-slate-600"
      )}>
        {label}
      </span>
      <div className="flex-1 h-1 rounded-full bg-slate-700/50 overflow-hidden min-w-[28px]">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-300",
            scanning ? "bg-violet-500" : "bg-emerald-500",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      {(current > 0 || total > 0) && (
        <span className="text-[8px] text-slate-500 w-5 text-right">{current}</span>
      )}
    </div>
  );
}

/**
 * Audit visualization v2: round-aware display below Report node.
 * Round 1: per-specialist progress bars
 * Round 2: claim-level mini-log with cascade/direct icons
 */
export function AuditHalo({ auditState, toolCalls, claimCount }: AuditHaloProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const isActive = auditState === "active";
  const isComplete = auditState === "complete";

  // Read audit phase + per-specialist data from store — select scalars to avoid re-render loops
  const auditPhase = useTheaterStore((s) => s.nodes.audit?.auditPhase ?? null);
  const citations = useTheaterStore((s) => s.nodes.audit?.auditCitations) ?? [];
  const r2EvidenceCount = useTheaterStore((s) => s.nodes.audit?.auditProgress?.current ?? 0);
  const r2CurrentClaim = useTheaterStore((s) => s.nodes.audit?.auditProgress?.currentClaim ?? "");
  const r2aCount = useTheaterStore((s) => s.nodes.audit?.r2aCount ?? 0);
  const r2bCount = useTheaterStore((s) => s.nodes.audit?.r2bCount ?? 0);
  const fProg = useTheaterStore((s) => s.nodes.fundamental?.auditProgress);
  const fScan = useTheaterStore((s) => s.nodes.fundamental?.auditScanning ?? false);
  const tProg = useTheaterStore((s) => s.nodes.technical?.auditProgress);
  const tScan = useTheaterStore((s) => s.nodes.technical?.auditScanning ?? false);
  const vProg = useTheaterStore((s) => s.nodes.value?.auditProgress);
  const vScan = useTheaterStore((s) => s.nodes.value?.auditScanning ?? false);
  const mProg = useTheaterStore((s) => s.nodes.macro?.auditProgress);
  const mScan = useTheaterStore((s) => s.nodes.macro?.auditScanning ?? false);
  const specialistData = useMemo(() => [
    { name: "fundamental" as const, progress: fProg, scanning: fScan },
    { name: "technical" as const, progress: tProg, scanning: tScan },
    { name: "value" as const, progress: vProg, scanning: vScan },
    { name: "macro" as const, progress: mProg, scanning: mScan },
  ], [fProg, fScan, tProg, tScan, vProg, vScan, mProg, mScan]);

  // Auto-scroll
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [toolCalls.length, citations.length]);

  if (auditState === "idle") return null;

  const isRound1 = isActive && auditPhase === "round1";
  const isRound2 = isActive && auditPhase === "round2";

  // Compute Round 1 summary for display after Round 1 completes
  // Use current (claims found) as fallback when total not yet known (total set by specialist_end)
  const r1Summary = specialistData.filter((s) => (s.progress?.total ?? 0) > 0 || (s.progress?.current ?? 0) > 0);
  const r1Total = r1Summary.reduce((sum, s) => sum + (s.progress?.total || s.progress?.current || 0), 0);
  const r1Verified = r1Summary.reduce((sum, s) => sum + (s.progress?.current ?? 0), 0);

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.4 }}
        className="mt-2 w-[220px]"
      >
        {/* Header: scanning ring + label */}
        <div className="flex items-center gap-2 mb-1.5">
          {isActive ? (
            <div className="relative w-5 h-5 shrink-0">
              <motion.div
                className={cn(
                  "absolute inset-0 rounded-full border-2 border-t-transparent",
                  "border-violet-400/30 border-t-violet-400"
                )}
                animate={{ rotate: 360 }}
                transition={{ duration: 1.5, repeat: Infinity, ease: "linear" }}
              />
              <div className="absolute inset-[3px] rounded-full bg-violet-500/20" />
            </div>
          ) : (
            <div className="w-5 h-5 shrink-0 rounded-full bg-emerald-500/20 flex items-center justify-center">
              <svg className="w-3 h-3 text-emerald-400" viewBox="0 0 16 16" fill="none">
                <path
                  d="M3 8.5l3.5 3.5 6.5-7"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
          )}
          <span
            className={cn(
              "text-[11px] font-medium",
              isActive ? "text-violet-300" : "text-emerald-300",
            )}
          >
            {isRound1
              ? "Round 1: Specialist Fidelity"
              : isRound2
                ? citations.length > 0
                  ? `Round 2: ${citations.length} citations`
                  : <>Round 2: <span className="text-indigo-300">R2a {r2aCount}</span>{" | "}<span className="text-cyan-300">R2b {r2bCount}</span></>
                : isActive
                  ? "Audit in progress..."
                  : `${claimCount ?? 0} claims verified`}
          </span>
        </div>

        {/* Round 1: Per-specialist progress bars */}
        {(isRound1 || (isRound2 && r1Total > 0)) && (
          <div className={cn(
            "rounded-md border border-violet-500/20 bg-slate-900/60 px-2 py-1.5 mb-1",
            !isRound1 && "opacity-60",
          )}>
            <div className="flex flex-col gap-1">
              {specialistData.map((s) => (
                <SpecialistMiniProgress key={s.name} {...s} />
              ))}
            </div>
            {!isRound1 && r1Total > 0 && (
              <div className="text-[9px] text-emerald-400 mt-1 text-center">
                Round 1: {r1Verified}/{r1Total} verified
              </div>
            )}
          </div>
        )}

        {/* Round 2: Evidence collection progress (before merge produces citations) */}
        {isRound2 && citations.length === 0 && r2EvidenceCount > 0 && (
          <div className="rounded-md border border-violet-500/20 bg-slate-900/60 px-2 py-1.5">
            <div className="flex items-center gap-1.5">
              <motion.span
                className="text-violet-400 text-[10px]"
                animate={{ opacity: [1, 0.4, 1] }}
                transition={{ duration: 1.2, repeat: Infinity }}
              >
                {"\u25C8"}
              </motion.span>
              <span className="text-[10px] text-violet-300">
                {r2EvidenceCount} evidence collected
              </span>
            </div>
            <div className="flex items-center gap-2 mt-0.5 pl-4">
              <span className="text-indigo-300 text-[9px]">R2a: {r2aCount}</span>
              <span className="text-cyan-300 text-[9px]">R2b: {r2bCount}</span>
            </div>
            {r2CurrentClaim && (
              <div className="text-[9px] text-slate-500 truncate mt-0.5 pl-4">
                {r2CurrentClaim}
              </div>
            )}
          </div>
        )}

        {/* Round 2: Citation mini-log (after merge) */}
        {isRound2 && citations.length > 0 && (
          <div
            ref={scrollRef}
            className="overflow-y-auto max-h-[100px] flex flex-col gap-0.5 scrollbar-thin rounded-md border border-violet-500/20 bg-slate-900/60 px-2 py-1.5"
          >
            {citations.map((c, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, x: -4 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.15 }}
                className="flex items-start gap-1.5 text-[10px] leading-relaxed"
              >
                <span className={cn("shrink-0", verdictColor(c.verdict))}>
                  {verdictIcon(c.verdict, c.cascade)}
                </span>
                <span className={cn(
                  "shrink-0 text-[8px] font-mono rounded px-0.5",
                  c.cascade ? "text-indigo-300 bg-indigo-500/15" : "text-cyan-300 bg-cyan-500/15"
                )}>
                  {c.cascade ? "S" : "D"}
                </span>
                <span className="flex-1 text-slate-400 truncate">
                  {c.claim}
                </span>
              </motion.div>
            ))}
          </div>
        )}

        {/* v1 fallback / generic tool call log (no v2 phase detected) */}
        {!auditPhase && (isActive || toolCalls.length > 0) && (
          <div
            ref={scrollRef}
            className={cn(
              "overflow-y-auto flex flex-col gap-0.5 scrollbar-thin",
              "rounded-md border border-violet-500/20 bg-slate-900/60 px-2 py-1.5",
              isActive ? "max-h-[120px]" : "max-h-[60px]",
            )}
          >
            {toolCalls.map((tc, i) => {
              const text = formatAuditAction(tc.tool_name, tc.input);
              const isDone = tc.duration_s !== undefined;
              const isSuccess = tc.success !== false;

              return (
                <motion.div
                  key={`${tc.tool_name}-${i}`}
                  initial={{ opacity: 0, x: -4 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.2 }}
                  className="flex items-start gap-1.5 text-[10px] leading-relaxed"
                >
                  <span className="shrink-0 mt-[2px]">
                    {!isDone ? (
                      <span className="text-violet-400 animate-pulse">{"\u25B6"}</span>
                    ) : isSuccess ? (
                      <span className="text-emerald-400">{"\u2713"}</span>
                    ) : (
                      <span className="text-red-400">{"\u2717"}</span>
                    )}
                  </span>
                  <span className={cn("flex-1", isDone ? "text-slate-500" : "text-slate-300")}>
                    {text}
                  </span>
                </motion.div>
              );
            })}

            {isActive && toolCalls.length === 0 && (
              <div className="text-[10px] text-slate-500 italic py-0.5">
                Preparing audit...
              </div>
            )}
          </div>
        )}

        {/* Complete state with score */}
        {isComplete && r1Total > 0 && (
          <div className="rounded-md border border-emerald-500/20 bg-slate-900/60 px-2 py-1.5 mt-1">
            <div className="text-[10px] text-emerald-300 text-center">
              Audit Complete: {claimCount ?? citations.length} claims verified
            </div>
            <div className="text-[9px] text-slate-400 text-center mt-0.5">
              {r2aCount} specialist + {r2bCount} source
            </div>
            <div className="flex items-center gap-1 mt-1 justify-center">
              {r1Summary.map((s) => {
                const c = s.progress?.current ?? 0;
                const t = s.progress?.total ?? 0;
                return (
                  <span key={s.name} className="text-[8px] text-slate-400">
                    {s.name.charAt(0).toUpperCase()}:{c}/{t}
                  </span>
                );
              })}
            </div>
          </div>
        )}
      </motion.div>
    </AnimatePresence>
  );
}
