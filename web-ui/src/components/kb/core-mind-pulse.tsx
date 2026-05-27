"use client";

import { useState, useCallback, useMemo, useRef } from "react";
import { useCoreMindPulse } from "@/hooks/use-api";
import type { PulsePoint } from "@/lib/types";

interface CoreMindPulseProps {
  className?: string;
}

// ── SVG Layout Constants ───────────────────────────────────────────────────

const SVG_WIDTH = 280;
const SVG_HEIGHT = 60;
const PADDING = { top: 8, bottom: 8, left: 4, right: 4 };
const PLOT_WIDTH = SVG_WIDTH - PADDING.left - PADDING.right;
const PLOT_HEIGHT = SVG_HEIGHT - PADDING.top - PADDING.bottom;

// ── Helpers ────────────────────────────────────────────────────────────────

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatChars(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function buildPaths(points: PulsePoint[]) {
  if (points.length === 0) return { linePath: "", areaPath: "", pathPoints: [] };

  const charCounts = points.map((p) => p.char_count);
  const maxChars = Math.max(...charCounts);
  const minChars = Math.min(...charCounts);
  const range = maxChars - minChars || 1;

  const pathPoints = points.map((p, i) => {
    const x =
      points.length === 1
        ? PADDING.left + PLOT_WIDTH / 2
        : PADDING.left + (i / (points.length - 1)) * PLOT_WIDTH;
    const y =
      PADDING.top +
      PLOT_HEIGHT -
      ((p.char_count - minChars) / range) * PLOT_HEIGHT;
    return { x, y };
  });

  const linePath = pathPoints
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(" ");

  const lastPt = pathPoints[pathPoints.length - 1];
  const firstPt = pathPoints[0];
  const areaPath =
    linePath +
    ` L ${lastPt.x.toFixed(1)} ${(SVG_HEIGHT - PADDING.bottom).toFixed(1)}` +
    ` L ${firstPt.x.toFixed(1)} ${(SVG_HEIGHT - PADDING.bottom).toFixed(1)} Z`;

  return { linePath, areaPath, pathPoints };
}

// ── Component ──────────────────────────────────────────────────────────────

export function CoreMindPulse({ className }: CoreMindPulseProps) {
  const { data, isLoading } = useCoreMindPulse();
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const points = useMemo(() => data?.points ?? [], [data?.points]);

  const { linePath, areaPath, pathPoints } = useMemo(
    () => buildPaths(points),
    [points],
  );

  const latestPoint = points.length > 0 ? points[points.length - 1] : null;

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (points.length === 0 || !svgRef.current) return;

      const rect = svgRef.current.getBoundingClientRect();
      const mouseX =
        ((e.clientX - rect.left) / rect.width) * SVG_WIDTH;

      // Find nearest point by x distance
      let nearest = 0;
      let minDist = Infinity;
      for (let i = 0; i < pathPoints.length; i++) {
        const dist = Math.abs(pathPoints[i].x - mouseX);
        if (dist < minDist) {
          minDist = dist;
          nearest = i;
        }
      }
      setHoveredIndex(nearest);
    },
    [points.length, pathPoints],
  );

  const handleMouseLeave = useCallback(() => {
    setHoveredIndex(null);
  }, []);

  // ── Empty / Loading States ─────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className={`border-t border-white/[0.06] pt-3 ${className ?? ""}`}>
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs text-white/40">Core Mind Pulse</span>
        </div>
        <div className="h-[60px] rounded bg-white/[0.03] animate-pulse" />
      </div>
    );
  }

  if (points.length === 0) {
    return (
      <div className={`border-t border-white/[0.06] pt-3 ${className ?? ""}`}>
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs text-white/40">Core Mind Pulse</span>
        </div>
        <div className="h-[60px] flex items-center justify-center">
          <span className="text-xs text-text-secondary">No snapshots yet</span>
        </div>
      </div>
    );
  }

  // ── Single Point ───────────────────────────────────────────────────────

  if (points.length === 1) {
    const pt = points[0];
    const cx = PADDING.left + PLOT_WIDTH / 2;
    const cy = PADDING.top + PLOT_HEIGHT / 2;

    return (
      <div className={`border-t border-white/[0.06] pt-3 ${className ?? ""}`}>
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs text-white/40">Core Mind Pulse</span>
          <span className="text-xs text-violet-400 font-mono">
            {formatChars(pt.char_count)} chars
          </span>
        </div>
        <svg
          width="100%"
          height={SVG_HEIGHT}
          viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
          preserveAspectRatio="none"
          className="w-full"
        >
          {/* Pulsing single dot */}
          <circle cx={cx} cy={cy} r={6} fill="rgba(139,92,246,0.15)">
            <animate
              attributeName="r"
              values="4;8;4"
              dur="2s"
              repeatCount="indefinite"
            />
            <animate
              attributeName="opacity"
              values="0.4;0.15;0.4"
              dur="2s"
              repeatCount="indefinite"
            />
          </circle>
          <circle cx={cx} cy={cy} r={3} fill="#8B5CF6" />
        </svg>
      </div>
    );
  }

  // ── Sparkline ──────────────────────────────────────────────────────────

  const hoveredPt =
    hoveredIndex !== null ? points[hoveredIndex] : null;
  const hoveredCoord =
    hoveredIndex !== null ? pathPoints[hoveredIndex] : null;

  const lastCoord = pathPoints[pathPoints.length - 1];

  return (
    <div className={`border-t border-white/[0.06] pt-3 ${className ?? ""}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs text-white/40">Core Mind Pulse</span>
        <span className="text-xs text-violet-400 font-mono">
          {latestPoint ? `${formatChars(latestPoint.char_count)} chars` : ""}
        </span>
      </div>

      {/* Sparkline container */}
      <div className="relative">
        <svg
          ref={svgRef}
          width="100%"
          height={SVG_HEIGHT}
          viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
          preserveAspectRatio="none"
          className="w-full cursor-crosshair"
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
        >
          {/* Area fill */}
          <path d={areaPath} fill="rgba(139,92,246,0.1)" />

          {/* Line */}
          <path
            d={linePath}
            fill="none"
            stroke="#8B5CF6"
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
          />

          {/* Pulsing dot at latest point */}
          <circle
            cx={lastCoord.x}
            cy={lastCoord.y}
            r={6}
            fill="rgba(139,92,246,0.2)"
          >
            <animate
              attributeName="r"
              values="4;8;4"
              dur="2s"
              repeatCount="indefinite"
            />
            <animate
              attributeName="opacity"
              values="0.4;0.1;0.4"
              dur="2s"
              repeatCount="indefinite"
            />
          </circle>
          <circle
            cx={lastCoord.x}
            cy={lastCoord.y}
            r={2.5}
            fill="#8B5CF6"
          />

          {/* Hover indicator */}
          {hoveredCoord && (
            <>
              {/* Vertical guide line */}
              <line
                x1={hoveredCoord.x}
                y1={PADDING.top}
                x2={hoveredCoord.x}
                y2={SVG_HEIGHT - PADDING.bottom}
                stroke="rgba(139,92,246,0.3)"
                strokeWidth={1}
                strokeDasharray="3 2"
                vectorEffect="non-scaling-stroke"
              />
              {/* Hover dot */}
              <circle
                cx={hoveredCoord.x}
                cy={hoveredCoord.y}
                r={3.5}
                fill="#8B5CF6"
                stroke="rgba(139,92,246,0.4)"
                strokeWidth={2}
                vectorEffect="non-scaling-stroke"
              />
            </>
          )}
        </svg>

        {/* Tooltip */}
        {hoveredPt && hoveredCoord && (
          <div
            className="absolute pointer-events-none z-10 px-2 py-1 rounded bg-surface/95 border border-violet-500/30 backdrop-blur-sm shadow-lg"
            style={{
              left: `${(hoveredCoord.x / SVG_WIDTH) * 100}%`,
              top: -4,
              transform: "translate(-50%, -100%)",
            }}
          >
            <span className="text-[11px] text-white/80 whitespace-nowrap">
              {formatDate(hoveredPt.date)}{" "}
              <span className="text-violet-400 font-mono">
                {hoveredPt.char_count.toLocaleString()} chars
              </span>
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
