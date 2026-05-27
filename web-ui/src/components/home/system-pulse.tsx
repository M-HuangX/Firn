"use client";

import NumberFlow from "@number-flow/react";
import { Skeleton } from "@/components/ui/skeleton";
import type { SystemStatus, EvolutionData } from "@/lib/types";

interface SystemPulseProps {
  status: SystemStatus | undefined;
  evolution: EvolutionData | undefined;
  inboxPending: number;
  isLoading: boolean;
}

export function SystemPulse({ status, evolution, inboxPending, isLoading }: SystemPulseProps) {
  const lastDay = evolution?.daily[evolution.daily.length - 1];

  const metrics = [
    {
      label: "Articles Accreted",
      value: status?.total_articles ?? 0,
      delta: lastDay?.articles_ingested ?? 0,
      showAmberDot: inboxPending > 0,
      compact: false,
    },
    {
      label: "Themes Tracked",
      value: status?.total_themes ?? 0,
      delta: 0,
      showAmberDot: false,
      compact: false,
    },
    {
      label: "Stocks Covered",
      value: status?.total_stocks ?? 0,
      delta: 0,
      showAmberDot: false,
      compact: false,
    },
    {
      label: "KB Characters",
      value: status?.core_mind_chars ?? 0,
      delta: lastDay?.kb_writes ?? 0,
      showAmberDot: false,
      compact: true,
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {metrics.map((m) => (
        <div
          key={m.label}
          className="bg-surface/50 rounded-lg border border-border p-4"
        >
          {isLoading ? (
            <Skeleton variant="text" className="w-20 h-7 mb-1" />
          ) : (
            <div className="flex items-baseline justify-between">
              <NumberFlow
                value={m.value}
                format={{
                  notation: m.compact && m.value >= 10000 ? "compact" : "standard",
                }}
                className="text-2xl font-bold font-mono tabular-nums text-text-primary"
              />
              {m.delta > 0 && (
                <span className="text-xs text-positive font-mono">
                  +{m.delta}
                </span>
              )}
            </div>
          )}
          <div className="flex items-center gap-1.5 mt-1">
            <span className="text-xs text-text-secondary">{m.label}</span>
            {m.showAmberDot && (
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
