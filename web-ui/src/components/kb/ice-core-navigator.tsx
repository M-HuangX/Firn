"use client";

import { useMemo } from "react";
import {
  useKBInbox,
  useKBThemes,
  useKBStocks,
  useKBCoreMind,
  useMaturation,
} from "@/hooks/use-api";

// ─── Types ──────────────────────────────────────────────────────────────────

interface IceCoreNavigatorProps {
  selectedStratum: string;
  onSelectStratum: (stratum: string) => void;
}

// ─── Strata Configuration ───────────────────────────────────────────────────

const STRATA = [
  { id: "inbox",     label: "Inbox",     icon: "\u2744", color: "rgb(224,242,254)", bgClass: "from-sky-950/20 to-sky-900/10" },
  { id: "events",    label: "Events",    icon: "\u26A1", color: "rgb(245,158,11)",  bgClass: "from-amber-950/20 to-amber-900/10" },
  { id: "themes",    label: "Themes",    icon: "\u25C6", color: "rgb(6,182,212)",   bgClass: "from-cyan-950/20 to-cyan-900/10" },
  { id: "stocks",    label: "Stocks",    icon: "\u258A", color: "rgb(16,185,129)",  bgClass: "from-emerald-950/20 to-emerald-900/10" },
  { id: "core_mind", label: "Core Mind", icon: "\u25C8", color: "rgb(139,92,246)",  bgClass: "from-violet-950/20 to-violet-900/10" },
] as const;

// ─── Helpers ────────────────────────────────────────────────────────────────

function formatCount(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

// ─── Component ──────────────────────────────────────────────────────────────

export function IceCoreNavigator({
  selectedStratum,
  onSelectStratum,
}: IceCoreNavigatorProps) {
  // Fetch data from all relevant hooks
  const { data: inbox } = useKBInbox();
  const { data: themes } = useKBThemes();
  const { data: stocks } = useKBStocks();
  const { data: coreMind } = useKBCoreMind();
  const { data: maturation } = useMaturation();

  // Derive counts and character volumes per stratum
  const strataMeta = useMemo(() => {
    const inboxCount = (inbox?.unread ?? 0) + (inbox?.read ?? 0);
    // Rough chars proxy: ~500 chars per article on average
    const inboxChars = inboxCount * 500;

    const eventsCount = maturation?.items.filter(
      (it) => it.item_type === "event"
    ).length ?? 0;
    // Rough chars proxy: ~300 chars per event
    const eventsChars = eventsCount * 300;

    const themesCount = themes?.length ?? 0;
    // Rough chars proxy: ~800 chars per theme
    const themesChars = themesCount * 800;

    const stocksCount = stocks?.length ?? 0;
    const stocksChars = stocks?.reduce((sum, s) => sum + (s.total_chars ?? 0), 0) ?? 0;

    const coreMindCount = 1; // always one core mind doc
    const coreMindChars = coreMind?.content?.length ?? 0;

    return {
      inbox:     { count: inboxCount,    chars: inboxChars },
      events:    { count: eventsCount,   chars: eventsChars },
      themes:    { count: themesCount,   chars: themesChars },
      stocks:    { count: stocksCount,   chars: stocksChars },
      core_mind: { count: coreMindCount, chars: coreMindChars },
    } as Record<string, { count: number; chars: number }>;
  }, [inbox, themes, stocks, coreMind, maturation]);

  // Max chars across all strata (for proportional volume bar)
  const maxChars = useMemo(() => {
    return Math.max(
      ...Object.values(strataMeta).map((m) => m.chars),
      1, // avoid division by zero
    );
  }, [strataMeta]);

  return (
    <div className="w-full lg:w-72 shrink-0">
      <nav
        className="rounded-xl border border-border bg-surface/60 backdrop-blur-sm overflow-hidden"
        role="tablist"
        aria-label="Knowledge strata"
      >
        {STRATA.map((stratum, index) => {
          const isSelected = selectedStratum === stratum.id;
          const meta = strataMeta[stratum.id] ?? { count: 0, chars: 0 };
          const barWidthPct = maxChars > 0 ? (meta.chars / maxChars) * 100 : 0;

          return (
            <button
              key={stratum.id}
              role="tab"
              aria-selected={isSelected}
              onClick={() => onSelectStratum(stratum.id)}
              className={`
                relative w-full text-left px-4 py-3 cursor-pointer
                transition-all duration-300
                bg-gradient-to-r ${stratum.bgClass}
                ${index < STRATA.length - 1 ? "border-b border-white/5" : ""}
                ${isSelected ? "scale-[1.02] z-10" : "hover:bg-white/[0.03]"}
              `}
              style={{
                transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
                borderLeftWidth: isSelected ? 3 : 0,
                borderLeftColor: isSelected ? stratum.color : "transparent",
                backgroundColor: isSelected ? "rgba(255,255,255,0.04)" : undefined,
              }}
            >
              {/* Main row: icon + label ... count badge */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 min-w-0">
                  <span
                    className="text-sm shrink-0"
                    style={{ color: stratum.color }}
                    aria-hidden
                  >
                    {stratum.icon}
                  </span>
                  <span
                    className={`text-sm font-medium truncate transition-colors duration-300 ${
                      isSelected ? "text-text-primary" : "text-text-secondary"
                    }`}
                  >
                    {stratum.label}
                  </span>
                </div>

                {/* Count badge */}
                <span
                  className={`
                    text-xs font-mono tabular-nums px-1.5 py-0.5 rounded-md shrink-0
                    transition-colors duration-300
                    ${isSelected
                      ? "text-text-primary bg-white/10"
                      : "text-text-secondary bg-white/5"
                    }
                  `}
                >
                  {meta.count > 0 ? formatCount(meta.count) : "\u2014"}
                </span>
              </div>

              {/* Volume bar — subtle horizontal indicator at bottom */}
              <div className="mt-2 h-[3px] rounded-full bg-white/[0.03] overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${barWidthPct}%`,
                    backgroundColor: stratum.color,
                    opacity: isSelected ? 0.35 : 0.2,
                    transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
                  }}
                />
              </div>
            </button>
          );
        })}
      </nav>
    </div>
  );
}
