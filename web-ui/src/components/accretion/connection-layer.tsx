"use client";

import { useRef, useEffect, useState, useCallback } from "react";
import { useDigestTheaterStore } from "@/stores/digest-theater-store";
import type { ConnectionState, ConnectionType } from "@/lib/digest-theater-types";

// ─── Color Semantics (R5 ss7) ──────────────────────────────────────────────

const CONNECTION_COLORS: Record<ConnectionType, { r: number; g: number; b: number }> = {
  reading: { r: 96, g: 165, b: 250 },   // blue
  writing: { r: 52, g: 211, b: 153 },    // emerald
  core_mind: { r: 139, g: 92, b: 246 },  // violet
};

function rgba(type: ConnectionType, a: number): string {
  const c = CONNECTION_COLORS[type];
  return `rgba(${c.r},${c.g},${c.b},${a})`;
}

// ─── Bezier Path Construction (R5 ss7) ──────────────────────────────────────

/**
 * Reading path: horizontal-dominant bezier with downward sag (gravity).
 * "Cable carrying weight" feel.
 */
function buildReadingPath(
  sx: number, sy: number, tx: number, ty: number,
): string {
  const spanX = tx - sx;
  const sag = Math.max(12, Math.abs(spanX) * 0.04);
  const c1x = sx + spanX * 0.33;
  const c1y = sy + sag * 0.6;
  const c2x = sx + spanX * 0.66;
  const c2y = ty + sag * 0.4;
  return `M ${sx} ${sy} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${tx} ${ty}`;
}

/**
 * Writing path: slight upward arc first half (Firn reaching up), then settling.
 */
function buildWritingPath(
  sx: number, sy: number, tx: number, ty: number,
): string {
  const spanX = tx - sx;
  const c1x = sx + spanX * 0.33;
  const c1y = sy - 12;
  const c2x = sx + spanX * 0.66;
  const c2y = ty + 8;
  return `M ${sx} ${sy} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${tx} ${ty}`;
}

// ─── Position Computation ───────────────────────────────────────────────────

/**
 * Proportional fallback: compute positions from container dimensions.
 * Grid is 1fr 1.6fr 1.4fr = total 4fr.
 *   Zone A right edge: width * (1/4) = 0.25
 *   Firn center: width * (1 + 0.8) / 4 = 0.45, height * 0.40
 *   Zone C left edge: width * (1 + 1.6) / 4 = 0.65
 */
function getEndpointsFallback(
  conn: ConnectionState,
  w: number,
  h: number,
  moduleIndex: number,
): { sx: number; sy: number; tx: number; ty: number } {
  const firnX = w * 0.45;
  const firnY = h * 0.40;
  const zoneARight = w * 0.25;
  const zoneCLeft = w * 0.65;

  if (conn.type === "reading") {
    // Source: right edge of Zone A, vertically centered
    return {
      sx: zoneARight,
      sy: h * 0.40,
      tx: firnX - 30, // approach Firn from left
      ty: firnY,
    };
  }

  // Writing/core_mind: Firn to KB module
  // Spread targets vertically based on module index to avoid overlap
  const baseY = h * 0.20;
  const ySpacing = Math.min(60, (h * 0.6) / Math.max(moduleIndex + 1, 1));
  const targetY = baseY + moduleIndex * ySpacing;

  return {
    sx: firnX + 30, // depart Firn from right
    sy: firnY,
    tx: zoneCLeft,
    ty: Math.min(targetY, h * 0.85),
  };
}

/**
 * DOM-based position computation: query actual element positions via
 * getBoundingClientRect() and data-* attributes on article cards,
 * KB module cards, and the Firn core.
 *
 * The connection layer div is `absolute inset-0` overlaying the grid.
 * Article/Firn/KB elements are siblings in the parent grid, so we
 * query from `containerEl.parentElement` and compute positions relative
 * to containerEl's own rect (which matches the grid).
 *
 * Returns null when DOM elements are not found (fallback to proportional).
 */
function getEndpointsFromDOM(
  conn: ConnectionState,
  containerEl: HTMLElement,
): { sx: number; sy: number; tx: number; ty: number } | null {
  const parentEl = containerEl.parentElement;
  if (!parentEl) return null;

  const containerRect = containerEl.getBoundingClientRect();

  if (conn.type === "reading") {
    // Source: right edge center of the article card being read
    const articleEl = parentEl.querySelector(
      `[data-article-slug="${CSS.escape(conn.sourceSlug)}"]`
    );
    // Target: Firn center (approach from left side)
    const firnEl = parentEl.querySelector("[data-firn-center]");
    if (!articleEl || !firnEl) return null;

    const articleRect = articleEl.getBoundingClientRect();
    const firnRect = firnEl.getBoundingClientRect();

    return {
      sx: articleRect.right - containerRect.left,
      sy: articleRect.top + articleRect.height / 2 - containerRect.top,
      tx: firnRect.left - containerRect.left,
      ty: firnRect.top + firnRect.height / 2 - containerRect.top,
    };
  }

  // Writing / core_mind: Firn → KB module
  const firnEl = parentEl.querySelector("[data-firn-center]");
  const moduleEl = parentEl.querySelector(
    `[data-kb-module-id="${CSS.escape(conn.targetSlug)}"]`
  );
  if (!firnEl || !moduleEl) return null;

  const firnRect = firnEl.getBoundingClientRect();
  const moduleRect = moduleEl.getBoundingClientRect();

  return {
    sx: firnRect.right - containerRect.left,
    sy: firnRect.top + firnRect.height / 2 - containerRect.top,
    tx: moduleRect.left - containerRect.left,
    ty: moduleRect.top + moduleRect.height / 2 - containerRect.top,
  };
}

// ─── Unique ID counter for SVG defs (avoid collisions across mounts) ────────

let _layerMountId = 0;

// ─── Component ──────────────────────────────────────────────────────────────

export function ConnectionLayer() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: 0, h: 0 });
  // useState with lazy initializer: stable ID, no ref access during render
  const [idPrefix] = useState(() => `cl_${++_layerMountId}`);

  // Scalar selectors to trigger re-renders on connection state changes
  const connectionCount = useDigestTheaterStore((s) => s.connectionCount);
  const readingArticleSlug = useDigestTheaterStore((s) => s.readingArticleSlug);

  // Position tick: RAF loop at ~30fps for smooth endpoint tracking
  // (follows module compaction, insertion, scroll — all DOM position changes)
  const [positionTick, setPositionTick] = useState(0);
  const hasConnections = connectionCount > 0;

  // ResizeObserver for container dimensions
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        setDims((prev) => {
          if (prev.w === Math.round(width) && prev.h === Math.round(height)) return prev;
          return { w: Math.round(width), h: Math.round(height) };
        });
      }
    });

    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // RAF loop: re-render at ~30fps while connections exist so endpoints
  // track DOM position changes (module compaction, scroll, insertion)
  useEffect(() => {
    if (!hasConnections) return;

    let rafId: number;
    let lastTime = 0;
    const loop = (now: number) => {
      if (now - lastTime >= 33) {
        setPositionTick((t) => (t + 1) & 0x7fff);
        lastTime = now;
      }
      rafId = requestAnimationFrame(loop);
    };
    rafId = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(rafId);
  }, [hasConnections]);

  // Get connections from store (via getState to avoid array selector)
  const getConnections = useCallback((): ConnectionState[] => {
    return useDigestTheaterStore.getState().connections;
  }, []);

  const connections = getConnections();
  // Track scalar selectors to ensure this component re-renders
  void connectionCount;
  void readingArticleSlug;
  void positionTick;

  const { w, h } = dims;
  if (w === 0 || h === 0 || connections.length === 0) {
    return (
      <div
        ref={containerRef}
        className="absolute inset-0 pointer-events-none"
        style={{ zIndex: 20 }}
      />
    );
  }

  // Opacity scaling when >3 connections (anti-spaghetti, R5 ss7)
  const opacityScale = connections.length > 3
    ? Math.max(0.25, 0.5 - (connections.length - 3) * 0.08)
    : 1;

  // Pre-compute write target indices for vertical spread (avoid mutation in render)
  const moduleIndexMap = new Map<string, number>();
  let writeIdx = 0;
  for (const conn of connections) {
    if (conn.type !== "reading" && !moduleIndexMap.has(conn.targetSlug)) {
      moduleIndexMap.set(conn.targetSlug, writeIdx++);
    }
  }

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 pointer-events-none"
      style={{ zIndex: 20 }}
    >
      <svg
        width={w}
        height={h}
        viewBox={`0 0 ${w} ${h}`}
        className="absolute inset-0"
        style={{ overflow: "visible" }}
      >
        {/* SVG filter for glow blur */}
        <defs>
          <filter id={`${idPrefix}_blur`}>
            <feGaussianBlur stdDeviation="3" />
          </filter>
        </defs>

        {/* Inline styles for CSS animations */}
        <style>{`
          @keyframes ${idPrefix}_glowBreathe {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.85; }
          }
          @keyframes ${idPrefix}_birthDraw {
            from { stroke-dashoffset: 1; }
            to { stroke-dashoffset: 0; }
          }
          @keyframes ${idPrefix}_fadeOut {
            from { opacity: 1; }
            to { opacity: 0; }
          }
          @keyframes ${idPrefix}_particleTravel {
            0% { offset-distance: 0%; opacity: 0; }
            10% { opacity: 1; }
            85% { opacity: 1; }
            100% { offset-distance: 100%; opacity: 0; }
          }
        `}</style>

        {connections.map((conn) => {
          const moduleIndex = conn.type !== "reading"
            ? (moduleIndexMap.get(conn.targetSlug) ?? 0)
            : 0;

          // Prefer DOM-based positions; fall back to proportional
          const domEndpoints = containerRef.current
            ? getEndpointsFromDOM(conn, containerRef.current)
            : null;
          const { sx, sy, tx, ty } = domEndpoints ?? getEndpointsFallback(conn, w, h, moduleIndex);
          const pathD = conn.type === "reading"
            ? buildReadingPath(sx, sy, tx, ty)
            : buildWritingPath(sx, sy, tx, ty);

          const connOpacity = conn.type === "core_mind" ? 1 : opacityScale;

          // Phase-based animation styles
          const isBirth = conn.phase === "birth";
          const isFade = conn.phase === "fade";
          const isActive = conn.phase === "active";
          const isLinger = conn.phase === "linger";

          // Birth: stroke-dashoffset animation
          const birthStyle: React.CSSProperties = isBirth ? {
            strokeDasharray: 1,
            strokeDashoffset: 1,
            animation: `${idPrefix}_birthDraw 600ms ease-out forwards`,
          } : {};

          // Fade: opacity transition
          const fadeStyle: React.CSSProperties = isFade ? {
            animation: `${idPrefix}_fadeOut 2000ms ease-out forwards`,
          } : {};

          // Active glow breathing (4s cycle, R5 ss8)
          const glowBreathStyle: React.CSSProperties = isActive ? {
            animation: `${idPrefix}_glowBreathe 4s ease-in-out infinite`,
          } : {};

          const pathId = `${idPrefix}_path_${conn.id}`;

          return (
            <g key={conn.id} style={{ opacity: connOpacity, ...fadeStyle }}>
              {/* Glow path: wide, blurred, low opacity */}
              <path
                d={pathD}
                fill="none"
                stroke={rgba(conn.type, 0.08)}
                strokeWidth={6}
                pathLength={1}
                filter={`url(#${idPrefix}_blur)`}
                style={{
                  willChange: "transform, opacity",
                  ...birthStyle,
                  ...glowBreathStyle,
                }}
              />

              {/* Core path: thin, visible line */}
              <path
                id={pathId}
                d={pathD}
                fill="none"
                stroke={rgba(conn.type, 0.4)}
                strokeWidth={1.5}
                pathLength={1}
                style={{
                  willChange: "transform, opacity",
                  ...birthStyle,
                }}
              />

              {/* Particles: 3 per active connection, traveling along the path */}
              {(isActive || isBirth) && [0, 1, 2].map((pi) => (
                <ellipse
                  key={`${conn.id}_p${pi}`}
                  rx={2.5}
                  ry={1.5}
                  fill={rgba(conn.type, 0.7)}
                  style={{
                    offsetPath: `path("${pathD}")`,
                    offsetRotate: "0deg",
                    animation: `${idPrefix}_particleTravel 8s linear infinite`,
                    animationDelay: `${pi * 0.6}s`,
                    willChange: "transform, opacity",
                    filter: `drop-shadow(0 0 ${conn.type === "core_mind" ? 8 : 6}px ${rgba(conn.type, 0.3)})`,
                  } as React.CSSProperties}
                />
              ))}

              {/* Linger phase: existing particles complete but no new ones spawn.
                  We keep particles visible briefly for visual continuity. */}
              {isLinger && [0, 1, 2].map((pi) => (
                <ellipse
                  key={`${conn.id}_lp${pi}`}
                  rx={2.5}
                  ry={1.5}
                  fill={rgba(conn.type, 0.7)}
                  style={{
                    offsetPath: `path("${pathD}")`,
                    offsetRotate: "0deg",
                    animation: `${idPrefix}_particleTravel 8s linear forwards`,
                    animationDelay: `${pi * 0.6}s`,
                    animationIterationCount: 1,
                    willChange: "transform, opacity",
                    filter: `drop-shadow(0 0 ${conn.type === "core_mind" ? 8 : 6}px ${rgba(conn.type, 0.3)})`,
                  } as React.CSSProperties}
                />
              ))}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
