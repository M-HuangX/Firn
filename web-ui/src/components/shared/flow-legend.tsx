"use client";

import { cn } from "@/lib/utils";

interface FlowLegendProps {
  variant: "analysis" | "digest";
  className?: string;
}

interface LegendEntry {
  label: string;
  color: string;
  dashArray?: string;
}

const ANALYSIS_ENTRIES: LegendEntry[] = [
  { label: "Data Flow", color: "#5B9CF0" },
  { label: "Tool Call", color: "#E8A330", dashArray: "4 3" },
  { label: "KB Read/Write", color: "#3FB950", dashArray: "5 2.5 1 2.5" },
];

const DIGEST_ENTRIES: LegendEntry[] = [
  { label: "Read / Input", color: "#5B9CF0" },
  { label: "Write / Output", color: "#3FB950" },
  { label: "Search / Query", color: "#E8A330", dashArray: "4 3" },
];

function LineSample({
  color,
  dashArray,
}: {
  color: string;
  dashArray?: string;
}) {
  return (
    <svg width="30" height="8" className="shrink-0">
      <line
        x1="0"
        y1="4"
        x2="30"
        y2="4"
        stroke={color}
        strokeWidth="2"
        strokeDasharray={dashArray}
        strokeLinecap="round"
      />
    </svg>
  );
}

export function FlowLegend({ variant, className }: FlowLegendProps) {
  const entries = variant === "analysis" ? ANALYSIS_ENTRIES : DIGEST_ENTRIES;

  return (
    <div
      className={cn(
        "bg-background/80 backdrop-blur-sm border border-border rounded-lg p-2 flex flex-col gap-1.5",
        className
      )}
    >
      {entries.map((entry) => (
        <div key={entry.label} className="flex items-center gap-2">
          <LineSample color={entry.color} dashArray={entry.dashArray} />
          <span className="text-[10px] text-text-secondary whitespace-nowrap">
            {entry.label}
          </span>
        </div>
      ))}
    </div>
  );
}
