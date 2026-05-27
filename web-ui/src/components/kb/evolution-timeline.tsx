"use client";

import { useCallback, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useEvolution } from "@/hooks/use-api";
import type { EvolutionDayData, EvolutionCumulativeData } from "@/lib/types";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

export interface EvolutionTimelineProps {
  height?: number;
  compact?: boolean;
  onDayClick?: (date: string) => void;
}

export type ViewMode = "daily" | "cumulative" | "stacked";

/** Build ECharts option from daily data */
export function buildDailyOption(
  data: EvolutionDayData[],
  compact: boolean
): Record<string, unknown> {
  return {
    backgroundColor: "transparent",
    tooltip: compact
      ? undefined
      : {
          trigger: "axis",
          backgroundColor: "#131B2E",
          borderColor: "#1E2D42",
          textStyle: { color: "#E2EBF5", fontSize: 12 },
        },
    legend: compact
      ? undefined
      : {
          data: ["Articles", "KB Writes", "Analyses"],
          textStyle: { color: "#7B8FA8" },
          top: 0,
        },
    grid: {
      left: compact ? 0 : 50,
      right: compact ? 0 : 20,
      top: compact ? 5 : 40,
      bottom: compact ? 0 : 30,
      containLabel: !compact,
    },
    xAxis: {
      type: "category",
      data: data.map((d) => d.date),
      axisLine: { lineStyle: { color: "#1A2538" } },
      axisLabel: compact ? { show: false } : { color: "#7B8FA8", fontSize: 11 },
    },
    yAxis: {
      type: "value",
      axisLine: { lineStyle: { color: "#1A2538" } },
      splitLine: { lineStyle: { color: "#1A2538" } },
      axisLabel: compact ? { show: false } : { color: "#7B8FA8", fontSize: 11 },
    },
    series: [
      {
        name: "Articles",
        type: "bar",
        data: data.map((d) => d.articles_ingested),
        itemStyle: { color: "#10B981" },
        barMaxWidth: 20,
      },
      {
        name: "KB Writes",
        type: "line",
        data: data.map((d) => d.kb_writes),
        itemStyle: { color: "#06B6D4" },
        lineStyle: { width: 2 },
        symbol: compact ? "none" : "circle",
        symbolSize: 4,
      },
      {
        name: "Analyses",
        type: "line",
        data: data.map((d) => d.analyses),
        itemStyle: { color: "#8B5CF6" },
        lineStyle: { width: 2 },
        symbol: compact ? "none" : "circle",
        symbolSize: 4,
      },
    ],
  };
}

/** Build ECharts option from cumulative data */
export function buildCumulativeOption(
  data: EvolutionCumulativeData[],
  compact: boolean
): Record<string, unknown> {
  return {
    backgroundColor: "transparent",
    tooltip: compact
      ? undefined
      : {
          trigger: "axis",
          backgroundColor: "#131B2E",
          borderColor: "#1E2D42",
          textStyle: { color: "#E2EBF5", fontSize: 12 },
        },
    legend: compact
      ? undefined
      : {
          data: ["Articles", "KB Writes", "Analyses"],
          textStyle: { color: "#7B8FA8" },
          top: 0,
        },
    grid: {
      left: compact ? 0 : 50,
      right: compact ? 0 : 20,
      top: compact ? 5 : 40,
      bottom: compact ? 0 : 30,
      containLabel: !compact,
    },
    xAxis: {
      type: "category",
      data: data.map((d) => d.date),
      axisLine: { lineStyle: { color: "#1A2538" } },
      axisLabel: compact ? { show: false } : { color: "#7B8FA8", fontSize: 11 },
    },
    yAxis: {
      type: "value",
      axisLine: { lineStyle: { color: "#1A2538" } },
      splitLine: { lineStyle: { color: "#1A2538" } },
      axisLabel: compact ? { show: false } : { color: "#7B8FA8", fontSize: 11 },
    },
    series: [
      {
        name: "Articles",
        type: "line",
        data: data.map((d) => d.articles),
        itemStyle: { color: "#10B981" },
        areaStyle: { color: "rgba(16, 185, 129, 0.15)" },
        lineStyle: { width: 2 },
        symbol: compact ? "none" : "circle",
        symbolSize: 4,
      },
      {
        name: "KB Writes",
        type: "line",
        data: data.map((d) => d.kb_writes),
        itemStyle: { color: "#06B6D4" },
        lineStyle: { width: 2 },
        symbol: compact ? "none" : "circle",
        symbolSize: 4,
      },
      {
        name: "Analyses",
        type: "line",
        data: data.map((d) => d.analyses),
        itemStyle: { color: "#8B5CF6" },
        lineStyle: { width: 2 },
        symbol: compact ? "none" : "circle",
        symbolSize: 4,
      },
    ],
  };
}

/** Build ECharts option for stacked area view */
export function buildStackedOption(
  data: EvolutionDayData[],
  compact: boolean
): Record<string, unknown> {
  return {
    backgroundColor: "transparent",
    tooltip: compact
      ? undefined
      : {
          trigger: "axis",
          backgroundColor: "#131B2E",
          borderColor: "#1E2D42",
          textStyle: { color: "#E2EBF5", fontSize: 12 },
        },
    legend: compact
      ? undefined
      : {
          data: ["Articles", "KB Writes", "Analyses"],
          textStyle: { color: "#7B8FA8" },
          top: 0,
        },
    grid: {
      left: compact ? 0 : 50,
      right: compact ? 0 : 20,
      top: compact ? 5 : 40,
      bottom: compact ? 0 : 30,
      containLabel: !compact,
    },
    xAxis: {
      type: "category",
      data: data.map((d) => d.date),
      boundaryGap: false,
      axisLine: { lineStyle: { color: "#1A2538" } },
      axisLabel: compact ? { show: false } : { color: "#7B8FA8", fontSize: 11 },
    },
    yAxis: {
      type: "value",
      axisLine: { lineStyle: { color: "#1A2538" } },
      splitLine: { lineStyle: { color: "#1A2538" } },
      axisLabel: compact ? { show: false } : { color: "#7B8FA8", fontSize: 11 },
    },
    series: [
      {
        name: "Articles",
        type: "line",
        stack: "total",
        data: data.map((d) => d.articles_ingested),
        areaStyle: { color: "rgba(16, 185, 129, 0.4)" },
        lineStyle: { width: 1, color: "#10B981" },
        itemStyle: { color: "#10B981" },
        symbol: "none",
        emphasis: { focus: "series" },
      },
      {
        name: "KB Writes",
        type: "line",
        stack: "total",
        data: data.map((d) => d.kb_writes),
        areaStyle: { color: "rgba(6, 182, 212, 0.4)" },
        lineStyle: { width: 1, color: "#06B6D4" },
        itemStyle: { color: "#06B6D4" },
        symbol: "none",
        emphasis: { focus: "series" },
      },
      {
        name: "Analyses",
        type: "line",
        stack: "total",
        data: data.map((d) => d.analyses),
        areaStyle: { color: "rgba(139, 92, 246, 0.4)" },
        lineStyle: { width: 1, color: "#8B5CF6" },
        itemStyle: { color: "#8B5CF6" },
        symbol: "none",
        emphasis: { focus: "series" },
      },
    ],
  };
}

export function EvolutionTimeline({ height = 300, compact = false, onDayClick }: EvolutionTimelineProps) {
  const { data: evolutionData, isLoading } = useEvolution();
  const [viewMode, setViewMode] = useState<ViewMode>("daily");

  const onChartClick = useCallback((params: { name: string }) => {
    onDayClick?.(params.name);
  }, [onDayClick]);

  const chartEvents = useMemo(
    (): Record<string, Function> => (onDayClick ? { click: onChartClick } : ({})),
    [onDayClick, onChartClick]
  );

  const option = useMemo(() => {
    if (!evolutionData) return null;
    if (viewMode === "daily") {
      return buildDailyOption(evolutionData.daily, compact);
    }
    if (viewMode === "stacked") {
      return buildStackedOption(evolutionData.daily, compact);
    }
    return buildCumulativeOption(evolutionData.cumulative, compact);
  }, [evolutionData, viewMode, compact]);

  if (isLoading) {
    return (
      <div
        className="bg-surface rounded-xl border border-border flex items-center justify-center"
        style={{ height }}
      >
        <span className="text-text-secondary text-sm">Loading evolution data...</span>
      </div>
    );
  }

  const hasData =
    evolutionData &&
    (evolutionData.daily.length > 0 || evolutionData.cumulative.length > 0);

  if (!hasData) {
    return (
      <div
        className="bg-surface rounded-xl border border-border flex items-center justify-center"
        style={{ height }}
      >
        <span className="text-text-secondary text-sm">
          No evolution data yet. Start digesting articles to see growth.
        </span>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {!compact && (
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-text-primary">Activity Over Time</h3>
          <div className="flex items-center gap-1 bg-surface border border-border rounded-lg p-0.5">
            <button
              onClick={() => setViewMode("daily")}
              className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                viewMode === "daily"
                  ? "bg-accent/15 text-accent"
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              Daily
            </button>
            <button
              onClick={() => setViewMode("cumulative")}
              className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                viewMode === "cumulative"
                  ? "bg-accent/15 text-accent"
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              Cumulative
            </button>
            <button
              onClick={() => setViewMode("stacked")}
              className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                viewMode === "stacked"
                  ? "bg-accent/15 text-accent"
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              Stacked
            </button>
          </div>
        </div>
      )}
      <div
        className={compact ? "" : "bg-surface rounded-xl border border-border p-4"}
        style={{ height }}
      >
        {option && (
          <ReactECharts
            option={option}
            style={{ height: "100%", width: "100%" }}
            opts={{ renderer: "svg" }}
            notMerge
            onEvents={chartEvents}
          />
        )}
      </div>
    </div>
  );
}
