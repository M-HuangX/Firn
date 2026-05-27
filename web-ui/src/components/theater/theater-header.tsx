"use client";

import { useTheaterStore } from "@/stores/pipeline-store";
import { StatusBadge } from "@/components/ui/status-badge";
import { m } from "motion/react";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";

const SPEED_OPTIONS = [1, 3, 5, 10] as const;

interface TheaterHeaderProps {
  ticker: string;
  status: string; // "running" | "complete" | "failed"
  startedAt?: string | null;
  completedAt?: string | null;
  execId: string;
}

function formatDuration(startedAt: string, completedAt: string): string {
  const start = new Date(startedAt).getTime();
  const end = new Date(completedAt).getTime();
  const diffMs = end - start;
  if (diffMs < 0) return "0s";
  const totalSeconds = Math.floor(diffMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

export function TheaterHeader({
  ticker,
  status,
  startedAt,
  completedAt,
  execId,
}: TheaterHeaderProps) {
  const router = useRouter();
  const lifecycleReplayActive = useTheaterStore(
    (s) => s.lifecycleReplayActive
  );
  const isReplaying = useTheaterStore((s) => s.isReplaying);
  const replayProgress = useTheaterStore((s) => s.replayProgress);
  const replaySpeed = useTheaterStore((s) => s.replaySpeed);
  const startLifecycleReplay = useTheaterStore(
    (s) => s.startLifecycleReplay
  );
  const stopLifecycleReplay = useTheaterStore(
    (s) => s.stopLifecycleReplay
  );
  const seekToPosition = useTheaterStore((s) => s.seekToPosition);
  const setReplaySpeed = useTheaterStore((s) => s.setReplaySpeed);

  const formattedStartTime = useMemo(() => {
    if (!startedAt) return null;
    return new Date(startedAt).toLocaleTimeString();
  }, [startedAt]);

  const duration = useMemo(() => {
    if (!startedAt || !completedAt) return null;
    return formatDuration(startedAt, completedAt);
  }, [startedAt, completedAt]);

  const truncatedExecId = execId.length > 20 ? execId.slice(0, 20) : execId;

  // Audit progress data — select scalars to avoid infinite re-renders
  const auditPhase = useTheaterStore((s) => s.nodes.audit?.auditPhase ?? null);
  const auditState = useTheaterStore((s) => s.nodes.audit?.state ?? "idle");
  const auditCitationCount = useTheaterStore((s) => s.nodes.audit?.auditCitations?.length ?? 0);
  const auditToolCount = useTheaterStore((s) => s.nodes.audit?.tool_count ?? 0);
  const r2aCount = useTheaterStore((s) => s.nodes.audit?.r2aCount ?? 0);
  const r2bCount = useTheaterStore((s) => s.nodes.audit?.r2bCount ?? 0);

  // Per-specialist progress — read individual scalars
  const fCur = useTheaterStore((s) => s.nodes.fundamental?.auditProgress?.current ?? 0);
  const fTot = useTheaterStore((s) => s.nodes.fundamental?.auditProgress?.total ?? 0);
  const fScan = useTheaterStore((s) => s.nodes.fundamental?.auditScanning ?? false);
  const tCur = useTheaterStore((s) => s.nodes.technical?.auditProgress?.current ?? 0);
  const tTot = useTheaterStore((s) => s.nodes.technical?.auditProgress?.total ?? 0);
  const tScan = useTheaterStore((s) => s.nodes.technical?.auditScanning ?? false);
  const vCur = useTheaterStore((s) => s.nodes.value?.auditProgress?.current ?? 0);
  const vTot = useTheaterStore((s) => s.nodes.value?.auditProgress?.total ?? 0);
  const vScan = useTheaterStore((s) => s.nodes.value?.auditScanning ?? false);
  const mCur = useTheaterStore((s) => s.nodes.macro?.auditProgress?.current ?? 0);
  const mTot = useTheaterStore((s) => s.nodes.macro?.auditProgress?.total ?? 0);
  const mScan = useTheaterStore((s) => s.nodes.macro?.auditScanning ?? false);

  const specialistProgress = useMemo(() => [
    { name: "fundamental", current: fCur, total: fTot, scanning: fScan },
    { name: "technical", current: tCur, total: tTot, scanning: tScan },
    { name: "value", current: vCur, total: vTot, scanning: vScan },
    { name: "macro", current: mCur, total: mTot, scanning: mScan },
  ], [fCur, fTot, fScan, tCur, tTot, tScan, vCur, vTot, vScan, mCur, mTot, mScan]);

  const showAuditBar = auditState === "active" || auditState === "complete";

  // Seekable progress bar state
  const progressBarRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isHovering, setIsHovering] = useState(false);

  const computeFraction = useCallback((clientX: number): number => {
    const bar = progressBarRef.current;
    if (!bar) return 0;
    const rect = bar.getBoundingClientRect();
    return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
  }, []);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      setIsDragging(true);
      seekToPosition(computeFraction(e.clientX));

      const handleMouseMove = (ev: MouseEvent) => {
        seekToPosition(computeFraction(ev.clientX));
      };
      const handleMouseUp = () => {
        setIsDragging(false);
        setIsHovering(false);
        window.removeEventListener("mousemove", handleMouseMove);
        window.removeEventListener("mouseup", handleMouseUp);
      };
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
    },
    [seekToPosition, computeFraction]
  );

  return (
    <m.header
      initial={{ y: -20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ type: "spring", stiffness: 400, damping: 30 }}
      className="relative w-full bg-[#0E1628]/80 backdrop-blur-md border-b border-border px-6 py-3"
    >
      {/* Primary row */}
      <div className="flex items-center justify-between">
        {/* Left: Back button */}
        <button
          onClick={() => router.push("/analysis")}
          className="flex items-center gap-1.5 text-sm text-text-secondary hover:text-text-primary transition-colors"
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            className="shrink-0"
          >
            <path
              d="M10 12L6 8L10 4"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          Back
        </button>

        {/* Center: Ticker + Status */}
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold font-mono text-text-primary">
            {ticker}
          </span>
          <span className="text-sm text-text-secondary">Analysis</span>
          <StatusBadge variant={status} />
        </div>

        {/* Right: Speed controls + Lifecycle replay button */}
        <div className="min-w-[220px] flex items-center justify-end gap-2">
          {/* Speed multiplier buttons — only visible during replay */}
          {isReplaying && (
            <div className="flex items-center gap-0.5">
              {SPEED_OPTIONS.map((speed) => (
                <button
                  key={speed}
                  onClick={() => setReplaySpeed(speed)}
                  className={cn(
                    "px-1.5 py-0.5 text-xs rounded transition-colors",
                    speed === replaySpeed
                      ? "text-text-secondary bg-border/20"
                      : "text-text-secondary/40 hover:text-text-secondary/70"
                  )}
                >
                  {speed}x
                </button>
              ))}
            </div>
          )}
          {(status === "complete" || isReplaying) && (
            <button
              onClick={() => {
                if (isReplaying || lifecycleReplayActive) {
                  stopLifecycleReplay();
                } else {
                  startLifecycleReplay();
                }
              }}
              className={`px-3 py-1.5 text-sm rounded-md border transition-colors ${
                isReplaying || lifecycleReplayActive
                  ? "border-interactive text-interactive bg-interactive/10 hover:bg-interactive/20"
                  : "border-border text-text-secondary hover:text-text-primary hover:border-text-secondary"
              }`}
            >
              {isReplaying || lifecycleReplayActive
                ? "Skip to End"
                : "View Full Lifecycle"}
            </button>
          )}
        </div>
      </div>

      {/* Subtitle row */}
      <div className="flex items-center justify-center gap-3 mt-1 text-xs text-text-secondary">
        {formattedStartTime && <span>Started {formattedStartTime}</span>}
        {formattedStartTime && duration && (
          <span className="text-text-secondary/50">|</span>
        )}
        {duration && <span>Duration {duration}</span>}
        {(formattedStartTime || duration) && (
          <span className="text-text-secondary/50">|</span>
        )}
        <span className="text-text-secondary/70 font-mono">
          {truncatedExecId}
        </span>
      </div>

      {/* Audit progress bar */}
      {showAuditBar && !isReplaying && (
        <m.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          transition={{ duration: 0.3 }}
          className="mt-2 flex items-center gap-3 text-[11px]"
        >
          {/* Audit icon */}
          <span className={cn(
            "shrink-0",
            auditState === "active" ? "text-violet-400 animate-pulse" : "text-emerald-400"
          )}>
            {auditState === "active" ? "\u25C8" : "\u2713"}
          </span>

          {/* Round 1 specialist scores */}
          {(auditPhase === "round1" || auditPhase === "round2" || auditState === "complete") && (
            <div className="flex items-center gap-2">
              <span className={cn(
                "text-[10px] font-medium",
                auditPhase === "round1" ? "text-violet-300" : "text-slate-400"
              )}>
                {auditPhase === "round1" ? "R1: Specialist Fidelity" : "R1"}
              </span>
              {specialistProgress.map((s) => {
                const done = s.total > 0 && !s.scanning;
                return (
                  <span key={s.name} className={cn(
                    "text-[10px] font-mono",
                    s.scanning ? "text-violet-400" : done ? "text-emerald-400" : "text-slate-600"
                  )}>
                    {s.name.charAt(0).toUpperCase()}:{s.current}/{s.total || "?"}
                  </span>
                );
              })}
            </div>
          )}

          {/* Divider */}
          {(auditPhase === "round2" || auditState === "complete") && (
            <span className="text-slate-600">|</span>
          )}

          {/* Round 2 progress */}
          {auditPhase === "round2" && auditState === "active" && (
            <div className="flex items-center gap-1.5">
              <span className="text-indigo-300 text-[10px] font-medium">
                R2a: {r2aCount}
              </span>
              <span className="text-slate-600 text-[9px]">|</span>
              <span className="text-cyan-300 text-[10px] font-medium">
                R2b: {r2bCount}
              </span>
            </div>
          )}

          {/* Complete summary */}
          {auditState === "complete" && (
            <span className="text-emerald-400 text-[10px] font-medium">
              R2: {r2aCount + r2bCount} claims verified ({r2aCount} specialist + {r2bCount} source)
            </span>
          )}
        </m.div>
      )}

      {/* Replay progress bar — seekable */}
      {isReplaying && (
        <m.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="absolute bottom-0 left-0 w-full"
        >
          {/* Visible bar */}
          <div
            className={cn(
              "w-full bg-transparent transition-[height] duration-150",
              isHovering || isDragging ? "h-1" : "h-0.5"
            )}
          >
            <m.div
              className="h-full bg-interactive relative"
              style={{ width: `${replayProgress * 100}%` }}
              transition={{ duration: 0.15, ease: "linear" }}
            >
              {/* Thumb indicator — visible on drag */}
              {isDragging && (
                <div className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-1/2 w-2.5 h-2.5 rounded-full bg-interactive shadow-sm" />
              )}
            </m.div>
          </div>
          {/* Transparent hit area for easy clicking/dragging */}
          <div
            ref={progressBarRef}
            className="absolute bottom-0 left-0 w-full h-4 cursor-pointer"
            onMouseDown={handleMouseDown}
            onMouseEnter={() => setIsHovering(true)}
            onMouseLeave={() => { if (!isDragging) setIsHovering(false); }}
          />
        </m.div>
      )}
    </m.header>
  );
}
