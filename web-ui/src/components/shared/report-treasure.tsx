"use client";

import { m } from "motion/react";
import { cn } from "@/lib/utils";

interface ReportTreasureProps {
  status: "idle" | "generating" | "ready";
  onClick?: () => void;
  className?: string;
  children?: React.ReactNode;
}

function SparkleIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
    >
      <path
        d="M8 0L9.79 5.53h5.81l-4.7 3.42 1.8 5.53L8 11.06l-4.7 3.42 1.8-5.53-4.7-3.42h5.81L8 0z"
        fill="currentColor"
        opacity="0.8"
      />
    </svg>
  );
}

function Spinner() {
  return (
    <svg
      className="w-4 h-4 animate-spin text-accent"
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="3"
        strokeDasharray="31.4 31.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function ReportTreasure({
  status,
  onClick,
  className,
  children,
}: ReportTreasureProps) {
  if (status === "idle") {
    return (
      <div
        className={cn(
          "rounded-xl border border-border p-6 opacity-50",
          className
        )}
      >
        <div className="flex items-center justify-center gap-2 text-text-secondary">
          <SparkleIcon className="text-text-secondary opacity-40" />
          <span className="text-sm">Report</span>
        </div>
        {children}
      </div>
    );
  }

  if (status === "generating") {
    return (
      <div
        className={cn(
          "rounded-xl border border-border p-6 animate-pulse",
          className
        )}
        style={{
          borderColor: "rgba(0, 212, 170, 0.3)",
        }}
      >
        <div className="flex items-center justify-center gap-2 text-text-secondary">
          <Spinner />
          <span className="text-sm">Generating report...</span>
        </div>
        {children}
      </div>
    );
  }

  // Ready state — full treasure effect
  return (
    <m.div
      className={cn(
        "rounded-xl border-2 p-8 cursor-pointer animate-treasureGlow",
        className
      )}
      style={{
        borderColor: "var(--color-treasure-glow)",
        background:
          "radial-gradient(ellipse at center, rgba(0,212,170,0.1) 0%, transparent 70%)",
      }}
      whileHover={{ scale: 1.05 }}
      transition={{ type: "spring", stiffness: 300, damping: 20 }}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onClick?.();
      }}
    >
      <div className="flex items-center justify-center gap-2 text-accent">
        <SparkleIcon className="text-accent" />
        <span className="text-base font-semibold">Report</span>
        <SparkleIcon className="text-accent" />
      </div>
      {children}
    </m.div>
  );
}
