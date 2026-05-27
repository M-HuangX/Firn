"use client";

import NumberFlow from "@number-flow/react";
import { Skeleton } from "@/components/ui/skeleton";
import type { SystemStatus, EvolutionData, EvolutionDayData } from "@/lib/types";

interface StrataHeroProps {
  status: SystemStatus | undefined;
  evolution: EvolutionData | undefined;
  isLoading: boolean;
}

const MAX_BARS = 30;

function formatKBChars(chars: number): string {
  if (chars >= 1000) {
    return `${(chars / 1000).toFixed(1)}k`;
  }
  return String(chars);
}

function dayActivity(day: EvolutionDayData): number {
  return day.articles_ingested + day.kb_writes + day.analyses + day.digests;
}

// ── Strata Visualization ────────────────────────────────────────────────────

function StrataViz({ daily }: { daily: EvolutionDayData[] }) {
  if (!daily || daily.length === 0) {
    return (
      <div className="w-48 h-[200px] flex flex-col justify-end items-end md:w-48 max-md:w-full max-md:max-w-[200px] max-md:mx-auto">
        <div
          className="w-[30%] rounded-[1.5px]"
          style={{
            height: 3,
            backgroundColor: "#00D4AA",
            opacity: 0.6,
          }}
        />
        <p className="text-text-secondary text-xs italic mt-3">
          Layer 1 forming...
        </p>
      </div>
    );
  }

  // Cap to MAX_BARS, take the most recent days
  const recentDays = daily.slice(-MAX_BARS);

  // Reverse so newest is at top (first rendered)
  const reversed = [...recentDays].reverse();

  const maxAct = Math.max(...reversed.map(dayActivity), 1);
  const totalBars = reversed.length;

  return (
    <div className="w-48 h-[200px] flex flex-col justify-end items-end md:w-48 max-md:w-full max-md:max-w-[200px] max-md:mx-auto">
      {reversed.map((day, index) => {
        const act = dayActivity(day);
        const widthPct = Math.max(12, (act / maxAct) * 100);
        // index 0 = newest (top) = full opacity, last = oldest = 0.15
        const ageOpacity =
          totalBars === 1
            ? 1
            : 1 - (index / (totalBars - 1)) * 0.85;

        return (
          <div
            key={day.date}
            style={{
              width: `${widthPct}%`,
              opacity: ageOpacity,
              marginBottom: 2,
            }}
          >
            <div
              style={{
                width: "100%",
                height: 3,
                borderRadius: 1.5,
                backgroundColor: "#00D4AA",
                opacity: 0,
                animation: `strataAppear 0.4s cubic-bezier(0.22, 1, 0.36, 1) ${index * 40}ms forwards`,
              }}
            />
          </div>
        );
      })}
    </div>
  );
}

// ── Main Component ──────────────────────────────────────────────────────────

export function StrataHero({ status, evolution, isLoading }: StrataHeroProps) {
  const dayN = status?.day_n ?? 0;
  const articles = status?.total_articles ?? 0;
  const themes = status?.total_themes ?? 0;
  const stocks = status?.total_stocks ?? 0;
  const kbChars = status?.core_mind_chars ?? 0;

  return (
    <section className="flex flex-col md:flex-row items-center gap-8">
      {/* Left Column: Text Info */}
      <div className="flex-1 min-w-0">
        {/* Brand */}
        <div className="text-2xl font-semibold text-accent mb-2">Firn</div>

        {/* Day N counter */}
        {isLoading ? (
          <Skeleton className="h-14 w-48 rounded-lg mb-3" />
        ) : (
          <div className="flex items-baseline gap-3 mb-3">
            <span className="text-text-secondary text-lg font-medium">Day</span>
            <NumberFlow
              value={dayN}
              className="text-[56px] font-bold font-mono tabular-nums text-accent"
              style={{
                textShadow:
                  "0 0 20px rgba(0, 212, 170, 0.4), 0 0 40px rgba(0, 212, 170, 0.15)",
              }}
            />
          </div>
        )}

        {/* Metadata line */}
        {isLoading ? (
          <Skeleton className="h-4 w-72 rounded" />
        ) : (
          <p className="text-xs text-text-secondary">
            4 specialists &middot; {articles} articles &middot; {themes} themes &middot; {stocks} stocks &middot; {formatKBChars(kbChars)} KB chars
          </p>
        )}
      </div>

      {/* Right Column: Strata Visualization */}
      <div className="flex-shrink-0">
        {isLoading ? (
          <Skeleton className="w-48 h-[200px] rounded-lg max-md:w-full max-md:max-w-[200px] max-md:mx-auto" />
        ) : (
          <StrataViz daily={evolution?.daily ?? []} />
        )}
      </div>
    </section>
  );
}
