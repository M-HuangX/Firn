"use client";

import { cn } from "@/lib/utils";
import { getVerdictStyle } from "./verdict-colors";

interface VerdictBadgeProps {
  verdict: string;
  confidence?: number;
  size?: "sm" | "md";
  className?: string;
  onClick?: () => void;
}

/**
 * Colored badge indicating verification verdict.
 * - >= 0.80: solid badge, full color
 * - 0.70-0.79: solid badge, slightly muted
 * - 0.50-0.69: badge with dashed border
 * - unverified: always dashed border (per spec §8)
 */
export function VerdictBadge({
  verdict,
  confidence,
  size = "sm",
  className,
  onClick,
}: VerdictBadgeProps) {
  const style = getVerdictStyle(verdict);
  const isUnverified = verdict === "unverified" || verdict === "llm-inferred";

  // Determine border style based on confidence
  const isDashed = isUnverified || (confidence !== undefined && confidence < 0.70);
  const isMuted = confidence !== undefined && confidence >= 0.70 && confidence < 0.80;

  return (
    <span
      role={onClick ? "button" : undefined}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1 rounded-full font-medium transition-all",
        size === "sm" ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-0.5 text-xs",
        style.text,
        style.bg,
        isDashed ? "border border-dashed" : "border border-solid",
        style.border,
        isMuted && "opacity-80",
        onClick && "cursor-pointer hover:scale-105 active:scale-95",
        className
      )}
      title={style.label}
    >
      <span className={cn(
        "w-1.5 h-1.5 rounded-full",
        isUnverified ? "bg-slate-400" : "bg-current"
      )} />
      {size === "md" && <span>{style.shortLabel}</span>}
    </span>
  );
}
