"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";

interface ScanLineProps {
  /** Whether the scan animation is active */
  active: boolean;
  /** Total height of the report container in px */
  containerHeight: number;
  /** Line positions (y offset in px) where citations exist — used for non-uniform speed */
  citationPositions: number[];
  /** Called when scan is complete */
  onComplete: () => void;
  /** Total duration in ms */
  duration?: number;
}

/**
 * Translucent scan line that sweeps top→bottom.
 * Non-uniform speed: decelerates near citation positions, accelerates in gaps.
 *
 * Implementation: uses CSS animation with dynamically generated keyframes
 * based on citation positions (spec §23: per-segment easing).
 */
export function ScanLine({
  active,
  containerHeight,
  citationPositions,
  onComplete,
  duration = 4000,
}: ScanLineProps) {
  const [currentY, setCurrentY] = useState(0);
  const animRef = useRef<number>(0);
  const startTimeRef = useRef(0);

  useEffect(() => {
    if (!active || containerHeight <= 0) return;

    // Build speed profile: slower near citations, faster in empty areas
    // Uses integral-based remap for monotonic output
    const positions = [...citationPositions].sort((a, b) => a - b);

    // Build cumulative speed profile: low speed near citations, high elsewhere
    const SEGMENTS = 100;
    const speeds: number[] = [];
    for (let i = 0; i < SEGMENTS; i++) {
      const y = (i / SEGMENTS) * containerHeight;
      let speed = 1.0;
      for (const pos of positions) {
        const dist = Math.abs(y - pos);
        if (dist < 60) {
          // Decelerate near citations (spec §23: non-uniform)
          speed = Math.min(speed, 0.3 + 0.7 * (dist / 60));
        }
      }
      speeds.push(speed);
    }

    // Build cumulative time-to-position mapping (integral)
    const cumulative: number[] = [0];
    for (let i = 1; i <= SEGMENTS; i++) {
      // Time spent in segment = 1/speed (slower = more time)
      cumulative.push(cumulative[i - 1] + 1 / speeds[i - 1]);
    }
    const totalTime = cumulative[SEGMENTS];

    // Map normalized time (0-1) to normalized position (0-1), monotonically
    function getPosition(t: number): number {
      if (t <= 0) return 0;
      if (t >= 1) return 1;
      if (positions.length === 0) return t;

      // Find which segment corresponds to time t
      const targetCum = t * totalTime;
      let lo = 0, hi = SEGMENTS;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (cumulative[mid] < targetCum) lo = mid + 1;
        else hi = mid;
      }
      // Linear interpolation within segment
      const segIdx = Math.max(0, lo - 1);
      const segStart = cumulative[segIdx];
      const segEnd = cumulative[segIdx + 1] || totalTime;
      const frac = segEnd > segStart ? (targetCum - segStart) / (segEnd - segStart) : 0;
      return (segIdx + frac) / SEGMENTS;
    }

    startTimeRef.current = performance.now();

    function animate(now: number) {
      const elapsed = now - startTimeRef.current;
      const rawT = Math.min(elapsed / duration, 1);

      // Apply non-uniform easing
      const easedT = getPosition(rawT);
      const y = easedT * containerHeight;
      setCurrentY(y);

      if (rawT < 1) {
        animRef.current = requestAnimationFrame(animate);
      } else {
        onComplete();
      }
    }

    animRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animRef.current);
  }, [active, containerHeight, citationPositions, duration, onComplete]);

  if (!active) return null;

  return (
    <motion.div
      className="absolute left-0 right-0 pointer-events-none z-10"
      style={{ top: currentY }}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      {/* Main scan line */}
      <div className="h-px bg-gradient-to-r from-transparent via-accent to-transparent" />
      {/* Glow above */}
      <div
        className="absolute -top-8 left-0 right-0 h-8"
        style={{
          background: "linear-gradient(to bottom, transparent, rgba(0,212,170,0.06))",
        }}
      />
      {/* Glow below */}
      <div
        className="absolute top-0 left-0 right-0 h-12"
        style={{
          background: "linear-gradient(to bottom, rgba(0,212,170,0.04), transparent)",
        }}
      />
    </motion.div>
  );
}
