"use client";

import { useCallback, useRef, useState } from "react";
import type { BatchMarker, EventDotType } from "@/stores/digest-theater-store";

const SPEED_OPTIONS = [1, 2, 4, 8] as const;
const GLACIAL_EASE = "cubic-bezier(0.22, 1, 0.36, 1)";

const DOT_COLORS: Record<EventDotType, string> = {
  digest: "rgba(96,165,250,0.6)",
  kb: "rgba(52,211,153,0.6)",
  tool: "rgba(255,255,255,0.2)",
};

interface PlaybackControlsProps {
  isPlaying: boolean;
  onTogglePlay: () => void;
  speed: number;
  onSetSpeed: (s: number) => void;
  currentIndex: number;
  totalEvents: number;
  onScrub: (index: number) => void;
  isLoaded: boolean;
  batchMarkers: BatchMarker[];
  eventDotTypes: EventDotType[];
}

export function PlaybackControls({
  isPlaying,
  onTogglePlay,
  speed,
  onSetSpeed,
  currentIndex,
  totalEvents,
  onScrub,
  isLoaded,
  batchMarkers,
  eventDotTypes,
}: PlaybackControlsProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [hoveredBatch, setHoveredBatch] = useState<BatchMarker | null>(null);
  const [tooltipX, setTooltipX] = useState(0);
  const [isHovered, setIsHovered] = useState(false);

  const progress = totalEvents > 1 ? currentIndex / (totalEvents - 1) : 0;
  const disabled = !isLoaded || totalEvents === 0;

  const clientXToIndex = useCallback(
    (clientX: number): number => {
      const track = trackRef.current;
      if (!track || totalEvents <= 1) return 0;
      const rect = track.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      return Math.round(ratio * (totalEvents - 1));
    },
    [totalEvents],
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (disabled) return;
      e.preventDefault();
      setIsDragging(true);
      const idx = clientXToIndex(e.clientX);
      onScrub(idx);

      const handleMouseMove = (ev: MouseEvent) => {
        const newIdx = clientXToIndex(ev.clientX);
        onScrub(newIdx);
      };

      const handleMouseUp = () => {
        setIsDragging(false);
        window.removeEventListener("mousemove", handleMouseMove);
        window.removeEventListener("mouseup", handleMouseUp);
      };

      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
    },
    [disabled, clientXToIndex, onScrub],
  );

  const handleTouchStart = useCallback(
    (e: React.TouchEvent) => {
      if (disabled) return;
      setIsDragging(true);
      const touch = e.touches[0];
      const idx = clientXToIndex(touch.clientX);
      onScrub(idx);

      const handleTouchMove = (ev: TouchEvent) => {
        const t = ev.touches[0];
        if (t) {
          const newIdx = clientXToIndex(t.clientX);
          onScrub(newIdx);
        }
      };

      const handleTouchEnd = () => {
        setIsDragging(false);
        window.removeEventListener("touchmove", handleTouchMove);
        window.removeEventListener("touchend", handleTouchEnd);
      };

      window.addEventListener("touchmove", handleTouchMove, { passive: true });
      window.addEventListener("touchend", handleTouchEnd);
    },
    [disabled, clientXToIndex, onScrub],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (disabled) return;
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        onScrub(Math.max(0, currentIndex - 1));
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        onScrub(Math.min(totalEvents - 1, currentIndex + 1));
      } else if (e.key === "Home") {
        e.preventDefault();
        onScrub(0);
      } else if (e.key === "End") {
        e.preventDefault();
        onScrub(totalEvents - 1);
      }
    },
    [disabled, currentIndex, totalEvents, onScrub],
  );

  const handleBatchHover = useCallback(
    (marker: BatchMarker) => {
      const track = trackRef.current;
      if (!track) return;
      const rect = track.getBoundingClientRect();
      const xPos =
        totalEvents > 1
          ? (marker.index / (totalEvents - 1)) * rect.width
          : 0;
      setTooltipX(xPos);
      setHoveredBatch(marker);
    },
    [totalEvents],
  );

  const handleBatchLeave = useCallback(() => {
    setHoveredBatch(null);
  }, []);

  const revealed = isHovered || isDragging;

  return (
    <div
      className="flex items-center gap-3 px-4 flex-shrink-0"
      style={{
        height: 28,
        background: revealed
          ? "linear-gradient(to top, rgba(7, 13, 24, 0.6), transparent)"
          : "transparent",
        borderTop: `1px solid rgba(255, 255, 255, ${revealed ? "0.04" : "0.02"})`,
        transition: `background 400ms ${GLACIAL_EASE}, border-color 400ms ${GLACIAL_EASE}`,
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Play/pause dot */}
      <button
        onClick={onTogglePlay}
        disabled={disabled}
        className="flex-shrink-0 cursor-pointer disabled:cursor-not-allowed"
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: isPlaying
            ? "rgba(217, 168, 83, 0.9)"
            : "rgba(226, 235, 245, 0.25)",
          boxShadow: isPlaying
            ? "0 0 8px rgba(217, 168, 83, 0.5)"
            : "none",
          animation: isPlaying ? "playDotPulse 2s ease-in-out infinite" : "none",
          border: "none",
          padding: 0,
          transition: `background 300ms ${GLACIAL_EASE}, box-shadow 300ms ${GLACIAL_EASE}`,
        }}
        aria-label={isPlaying ? "Pause" : "Play"}
      />

      {/* Timeline track area */}
      <div
        className="relative flex-1"
        style={{
          height: 20,
          opacity: revealed ? 1 : 0.35,
          transition: `opacity 400ms ${GLACIAL_EASE}`,
        }}
      >
        {/* Batch boundary ticks */}
        <div className="absolute left-0 right-0" style={{ top: 0, height: 8 }}>
          {batchMarkers.map((marker) => {
            const x =
              totalEvents > 1
                ? `${(marker.index / (totalEvents - 1)) * 100}%`
                : "0%";
            return (
              <div
                key={`batch-${marker.batchNum}`}
                className="absolute"
                style={{
                  left: x,
                  top: 0,
                  width: 1,
                  height: 8,
                  background: `rgba(255, 255, 255, ${revealed ? "0.15" : "0.08"})`,
                  transform: "translateX(-0.5px)",
                  transition: `background 400ms ${GLACIAL_EASE}`,
                }}
                onMouseEnter={() => handleBatchHover(marker)}
                onMouseLeave={handleBatchLeave}
              />
            );
          })}
        </div>

        {/* Event density dots */}
        <div className="absolute left-0 right-0" style={{ top: 8, height: 6 }}>
          {eventDotTypes.map((dotType, i) => {
            const x =
              totalEvents > 1
                ? `${(i / (totalEvents - 1)) * 100}%`
                : "0%";
            return (
              <div
                key={i}
                className="absolute rounded-full"
                style={{
                  left: x,
                  top: "50%",
                  width: 1.5,
                  height: 1.5,
                  background: DOT_COLORS[dotType],
                  transform: "translate(-0.75px, -0.75px)",
                }}
              />
            );
          })}
        </div>

        {/* Progress track */}
        <div
          ref={trackRef}
          className="absolute left-0 right-0"
          style={{
            top: 15,
            height: 5,
            cursor: disabled ? "not-allowed" : "pointer",
            touchAction: "none",
          }}
          onMouseDown={handleMouseDown}
          onTouchStart={handleTouchStart}
          onKeyDown={handleKeyDown}
          tabIndex={disabled ? -1 : 0}
          role="slider"
          aria-label="Scrub through events"
          aria-valuemin={0}
          aria-valuemax={Math.max(0, totalEvents - 1)}
          aria-valuenow={currentIndex}
          aria-disabled={disabled}
        >
          <div
            className="absolute rounded-full"
            style={{
              left: 0,
              right: 0,
              top: 1,
              height: 2,
              background: "rgba(255, 255, 255, 0.08)",
            }}
          />
          <div
            className="absolute rounded-full"
            style={{
              left: 0,
              top: 1,
              height: 2,
              width: `${progress * 100}%`,
              background: "rgba(96, 165, 250, 0.5)",
              boxShadow: "0 0 8px rgba(96, 165, 250, 0.2)",
              transition: isDragging ? "none" : `width 120ms ${GLACIAL_EASE}`,
            }}
          />
          <div
            className="absolute"
            style={{
              left: `${progress * 100}%`,
              top: -1,
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: "rgba(96, 165, 250, 0.9)",
              boxShadow: isDragging
                ? "0 0 16px rgba(96, 165, 250, 0.6)"
                : "0 0 12px rgba(96, 165, 250, 0.4)",
              transform: `translateX(-4px) ${isDragging ? "scale(1.25)" : "scale(1)"}`,
              transition: isDragging
                ? "box-shadow 150ms ease, transform 150ms ease"
                : `left 120ms ${GLACIAL_EASE}, box-shadow 150ms ease, transform 150ms ease`,
              opacity: disabled ? 0.3 : revealed ? 1 : 0.4,
            }}
          />
        </div>

        {/* Batch tooltip */}
        {hoveredBatch && (
          <div
            className="absolute z-50 pointer-events-none"
            style={{
              left: tooltipX,
              top: -6,
              transform: "translateX(-50%) translateY(-100%)",
            }}
          >
            <div
              className="px-2 py-1 rounded text-[10px] font-mono whitespace-nowrap"
              style={{
                background: "rgba(19, 27, 46, 0.95)",
                border: "1px solid rgba(255, 255, 255, 0.1)",
                color: "rgba(226, 235, 245, 0.7)",
                backdropFilter: "blur(4px)",
              }}
            >
              Batch {hoveredBatch.batchNum}: {hoveredBatch.articleCount} article
              {hoveredBatch.articleCount !== 1 ? "s" : ""}
            </div>
          </div>
        )}
      </div>

      {/* Speed pills (hover-revealed, right-aligned) */}
      <div
        className="flex items-center gap-0.5 flex-shrink-0"
        style={{
          opacity: revealed ? 1 : 0,
          transition: `opacity 400ms ${GLACIAL_EASE}`,
          pointerEvents: revealed ? "auto" : "none",
        }}
      >
        {SPEED_OPTIONS.map((s) => (
          <button
            key={s}
            onClick={() => onSetSpeed(s)}
            className={`px-1.5 py-0.5 text-[10px] font-medium rounded cursor-pointer ${
              speed === s
                ? "bg-accent/15 text-accent"
                : "text-text-secondary hover:text-text-primary hover:bg-white/5"
            }`}
            style={{ transition: `all 150ms ${GLACIAL_EASE}` }}
            aria-label={`${s}x speed`}
            aria-pressed={speed === s}
          >
            {s}x
          </button>
        ))}
      </div>

      <style
        dangerouslySetInnerHTML={{
          __html: `
            @keyframes playDotPulse {
              0%, 100% { box-shadow: 0 0 8px rgba(217, 168, 83, 0.5); }
              50% { box-shadow: 0 0 14px rgba(217, 168, 83, 0.7); }
            }
          `,
        }}
      />
    </div>
  );
}
