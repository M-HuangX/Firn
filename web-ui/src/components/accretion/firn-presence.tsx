"use client";

import { useMemo } from "react";
import { useDigestTheaterStore } from "@/stores/digest-theater-store";
import type { FirnState, ToolBubble, ToolBubbleDirection } from "@/lib/digest-theater-types";

// ─── Layer style computation per Firn state ─────────────────────────────────

interface LayerStyles {
  core: React.CSSProperties;
  mantle: React.CSSProperties;
  firnLine: React.CSSProperties;
  scatter: React.CSSProperties;
}

function computeLayerStyles(state: FirnState): LayerStyles {
  switch (state) {
    case "idle":
      return {
        core: { opacity: 0.75 },
        mantle: {
          background: `radial-gradient(circle, rgba(217,168,83,0.4) 0%, rgba(217,168,83,0.1) 100%)`,
        },
        firnLine: {},
        scatter: { width: "180px", height: "180px" },
      };

    case "reading":
      return {
        core: { opacity: 0.92 },
        mantle: {
          background: `radial-gradient(circle, rgba(217,168,83,0.55) 0%, rgba(217,168,83,0.15) 100%)`,
        },
        firnLine: {},
        scatter: {},
      };

    case "thinking":
      return {
        core: { opacity: 0.92 },
        mantle: {},
        firnLine: {},
        scatter: {},
      };

    case "writing":
      return {
        core: { opacity: 1.0 },
        mantle: {
          background: `radial-gradient(circle, rgba(217,168,83,0.5) 0%, rgba(63,185,80,0.08) 50%, rgba(217,168,83,0.12) 100%)`,
        },
        firnLine: {},
        scatter: { left: "53%" },
      };

    case "complete":
      return {
        core: { opacity: 0.7 },
        mantle: { animation: "firnMantleBreathe 12s ease-in-out -2s infinite" },
        firnLine: {},
        scatter: { width: "180px", height: "180px" },
      };

    default:
      return {
        core: {},
        mantle: {},
        firnLine: {},
        scatter: {},
      };
  }
}

// ─── Tool bubble positioning ────────────────────────────────────────────────

function getBubblePosition(
  direction: ToolBubbleDirection,
  index: number,
): React.CSSProperties {
  const spacing = 28;

  switch (direction) {
    case "left":
      return {
        right: "calc(50% + 80px)",
        top: `calc(40% + ${20 + index * spacing}px)`,
      };
    case "right":
      return {
        left: "calc(50% + 80px)",
        top: `calc(40% + ${20 + index * spacing}px)`,
      };
    case "up":
      return {
        left: "50%",
        marginLeft: "-40px", // approximate half-width centering without transform
        top: `calc(40% - ${90 + index * spacing}px)`,
      };
  }
}

// ─── Component ──────────────────────────────────────────────────────────────

interface FirnPresenceProps {
  onTogglePlay?: () => void;
}

export function FirnPresence({ onTogglePlay }: FirnPresenceProps) {
  // Scalar selectors (React 19 safe)
  const firnState = useDigestTheaterStore((s) => s.firnState);
  const activeBatchNum = useDigestTheaterStore((s) => s.activeBatchNum);
  const activeArticleCount = useDigestTheaterStore((s) => s.activeArticleCount);
  const toolBubbleCount = useDigestTheaterStore((s) => s.toolBubbleCount);

  // Tool bubbles array via scalar trigger + getState()
  const toolBubbles = useMemo((): ToolBubble[] => {
    return useDigestTheaterStore.getState().toolBubbles;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toolBubbleCount]);

  // Layer style overrides per state
  const layerStyles = useMemo(() => computeLayerStyles(firnState), [firnState]);

  // Banner text
  const bannerText = useMemo((): string | null => {
    if (firnState === "complete") {
      return `Session complete \u2014 ${activeArticleCount} articles`;
    }
    if (activeBatchNum !== null) {
      return `Reading Batch ${activeBatchNum}`;
    }
    return null;
  }, [firnState, activeBatchNum, activeArticleCount]);

  return (
    <div
      className="relative h-full w-full overflow-hidden"
      style={{ minHeight: 0 }}
    >
      {/* Batch Context Banner */}
      {bannerText && (
        <div
          style={{
            position: "absolute",
            top: "25%",
            left: 0,
            right: 0,
            textAlign: "center",
            fontSize: "11px",
            fontFamily: "system-ui, sans-serif",
            color: "rgba(226, 235, 245, 0.5)",
            letterSpacing: "0.02em",
            zIndex: 10,
            pointerEvents: "none",
          }}
        >
          {bannerText}
        </div>
      )}

      {/* Layer 4: Scatter (outermost, 200px) */}
      <div
        className="firn-scatter"
        style={{
          position: "absolute",
          top: "40%",
          left: "50%",
          width: "200px",
          height: "200px",
          borderRadius: "50%",
          background: `radial-gradient(circle, rgba(96,165,250,0.04) 0%, transparent 100%)`,
          boxShadow: "0 0 60px rgba(217,168,83,0.08)",
          transform: "translate(-50%, -50%)",
          animation: "firnScatterBreathe 16s ease-in-out infinite",
          willChange: "opacity",
          pointerEvents: "none",
          ...layerStyles.scatter,
        }}
      />

      {/* Layer 3: Firn-line (140px) */}
      <div
        className="firn-line"
        style={{
          position: "absolute",
          top: "40%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: "140px",
          height: "140px",
          borderRadius: "50%",
          background: `radial-gradient(circle, rgba(217,168,83,0.08) 0%, rgba(139,166,204,0.06) 100%)`,
          animation: "firnLineBreathe 12s ease-in-out infinite",
          willChange: "transform, opacity",
          pointerEvents: "none",
          ...layerStyles.firnLine,
        }}
      />

      {/* Layer 2: Mantle (80px) */}
      <div
        className="firn-mantle"
        style={{
          position: "absolute",
          top: "40%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: "80px",
          height: "80px",
          borderRadius: "50%",
          background: `radial-gradient(circle, rgba(217,168,83,0.5) 0%, rgba(217,168,83,0.12) 100%)`,
          boxShadow: "0 0 30px rgba(217,168,83,0.15)",
          animation: "firnMantleBreathe 8s ease-in-out -2s infinite",
          willChange: "transform",
          pointerEvents: "none",
          ...layerStyles.mantle,
        }}
      />

      {/* Layer 1: Core (innermost, 24px) */}
      <div
        className="firn-core"
        data-firn-center
        onClick={onTogglePlay}
        style={{
          position: "absolute",
          top: "40%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: "24px",
          height: "24px",
          borderRadius: "50%",
          backgroundColor: "#FFF5E0",
          opacity: 0.85,
          animation: "firnCoreBreathe 8s ease-in-out infinite",
          willChange: "transform, opacity",
          cursor: onTogglePlay ? "pointer" : undefined,
          pointerEvents: onTogglePlay ? "auto" : "none",
          ...layerStyles.core,
        }}
      />

      {/* Tool Bubbles */}
      {toolBubbles.map((bubble, i) => {
        const isSearch = bubble.direction === "up";
        const bubbleColor = isSearch
          ? { bg: "rgba(120, 200, 230, 0.10)", text: "rgba(120, 200, 230, 0.75)", border: "rgba(120, 200, 230, 0.12)" }
          : { bg: "rgba(217, 168, 83, 0.12)", text: "rgba(217, 168, 83, 0.8)", border: "rgba(217, 168, 83, 0.15)" };
        const bubbleAnimation = isSearch
          ? "searchBubbleSublimate 3100ms ease-out forwards"
          : "toolBubbleLife 3100ms ease-out forwards";

        return (
          <div
            key={bubble.id}
            style={{
              position: "absolute",
              fontSize: "11px",
              fontFamily: '"JetBrains Mono", ui-monospace, monospace',
              padding: "2px 8px",
              borderRadius: "10px",
              background: bubbleColor.bg,
              color: bubbleColor.text,
              border: `1px solid ${bubbleColor.border}`,
              backdropFilter: "blur(4px)",
              WebkitBackdropFilter: "blur(4px)",
              whiteSpace: "nowrap",
              zIndex: 20,
              animation: bubbleAnimation,
              pointerEvents: "none",
              ...getBubblePosition(bubble.direction, i),
            }}
          >
            {bubble.tool_name}
          </div>
        );
      })}

      {/* All CSS animations in one <style> block */}
      <style
        dangerouslySetInnerHTML={{
          __html: `
            @keyframes firnCoreBreathe {
              0%, 100% { transform: translate(-50%, -50%) scale(1); opacity: 0.85; }
              50% { transform: translate(-50%, -50%) scale(1.06); opacity: 0.95; }
            }

            @keyframes firnMantleBreathe {
              0%, 100% { transform: translate(-50%, -50%) scale(1); box-shadow: 0 0 30px rgba(217,168,83,0.15); }
              50% { transform: translate(-50%, -50%) scale(1.025); box-shadow: 0 0 45px rgba(217,168,83,0.15); }
            }

            @keyframes firnLineBreathe {
              0%, 100% { transform: translate(-50%, -50%) scale(1); opacity: 1; }
              50% { transform: translate(-50%, -50%) scale(1.015); opacity: 0.92; }
            }

            @keyframes firnScatterBreathe {
              0%, 100% { opacity: 1; }
              50% { opacity: 0.85; }
            }

            @keyframes toolBubbleLife {
              0% { opacity: 0; transform: scale(0.8); }
              10% { opacity: 1; transform: scale(1); }
              80% { opacity: 1; transform: scale(1) translateY(0); }
              100% { opacity: 0; transform: scale(1) translateY(-6px); }
            }

            @keyframes searchBubbleSublimate {
              0% { opacity: 0; transform: scale(0.8) translateY(0); }
              10% { opacity: 1; transform: scale(1) translateY(0); }
              80% { opacity: 0.85; transform: scale(1) translateY(-2px); }
              100% { opacity: 0; transform: scale(1) translateY(-4px); }
            }
          `,
        }}
      />
    </div>
  );
}
