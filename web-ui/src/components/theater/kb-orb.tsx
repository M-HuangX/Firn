"use client";

import type { KBSectionOp } from "@/stores/pipeline-store";

// Each star has a unique drift pattern (px offsets) and timing
const KB_SECTIONS = [
  { id: "stocks",     label: "Stocks",    angle: 270, drifts: [4,-5,-4,6,-3,4,5,-3],  dur: 8,  delay: 0   },
  { id: "themes",     label: "Themes",    angle: 330, drifts: [-5,4,6,-3,3,5,-6,2],   dur: 11, delay: 1.5 },
  { id: "events",     label: "Events",    angle: 30,  drifts: [3,6,-5,-4,6,-2,-4,5],  dur: 9,  delay: 3   },
  { id: "core_mind",  label: "Core Mind", angle: 90,  drifts: [-4,-6,5,3,-6,4,3,-5],  dur: 13, delay: 0.5 },
  { id: "user_views", label: "User",      angle: 150, drifts: [6,3,-3,5,-5,-4,4,-6],  dur: 10, delay: 2   },
  { id: "forwarded",  label: "Fwd",       angle: 210, drifts: [-3,5,4,-6,2,6,-5,-2],  dur: 12, delay: 4   },
] as const;

const FIELD_SIZE = 110;
const CENTER = FIELD_SIZE / 2;
const RADIUS = 38;
const STAR_SIZE = 7;
const CENTER_SIZE = 14;

// Web search icon position (right side of field)
const WEB_X = FIELD_SIZE + 8;
const WEB_Y = CENTER;

interface KBOrbProps {
  reads: number;
  writes: number;
  activeOp: "read" | "write" | null;
  sectionOps?: Record<string, KBSectionOp>;
  activeSection?: string | null;
  webSearchActive?: boolean;
  webSearchCount?: number;
  /** When true, ambient float animation stops — "completed states are still" */
  pipelineComplete?: boolean;
}

export function KBOrb({
  reads, writes, activeOp, sectionOps = {}, activeSection,
  webSearchActive = false, webSearchCount = 0,
  pipelineComplete = false,
}: KBOrbProps) {
  const total = reads + writes;
  const hasActivity = total > 0 || activeOp !== null;
  const showWebSearch = webSearchActive || webSearchCount > 0;

  // Compute star positions for SVG lines
  const starPositions = KB_SECTIONS.map(({ angle }) => {
    const rad = (angle * Math.PI) / 180;
    return { x: CENTER + RADIUS * Math.cos(rad), y: CENTER + RADIUS * Math.sin(rad) };
  });

  return (
    <div className="flex flex-col items-center gap-1">
      <div
        className="relative"
        style={{ width: showWebSearch ? FIELD_SIZE + 40 : FIELD_SIZE, height: FIELD_SIZE }}
        aria-label={`Knowledge Base — ${reads} reads, ${writes} writes${activeOp ? `, ${activeOp}ing` : ""}`}
      >
        {/* SVG layer for connection lines */}
        <svg
          className="absolute inset-0 pointer-events-none"
          width={showWebSearch ? FIELD_SIZE + 40 : FIELD_SIZE}
          height={FIELD_SIZE}
          style={{ overflow: "visible" }}
        >
          {/* Lines from center to active/completed stars */}
          {KB_SECTIONS.map(({ id }, i) => {
            const op = sectionOps[id];
            const isActive = activeSection === id;
            if (!op && !isActive) return null;

            const pos = starPositions[i];
            const color = op === "write" || (isActive && activeOp === "write")
              ? "rgba(63, 185, 80, VAR)"
              : op === "read" || (isActive && activeOp === "read")
                ? "rgba(6, 182, 212, VAR)"
                : "rgba(139, 92, 246, VAR)";

            const lineOpacity = isActive ? 0.6 : op === "write" ? 0.4 : op === "read" ? 0.3 : 0.15;
            const strokeColor = color.replace("VAR", String(lineOpacity));
            const glowColor = color.replace("VAR", String(lineOpacity * 0.5));

            return (
              <g key={id}>
                {/* Glow line */}
                <line
                  x1={CENTER} y1={CENTER} x2={pos.x} y2={pos.y}
                  stroke={glowColor}
                  strokeWidth={isActive ? 3 : 1.5}
                  strokeLinecap="round"
                />
                {/* Core line */}
                <line
                  x1={CENTER} y1={CENTER} x2={pos.x} y2={pos.y}
                  stroke={strokeColor}
                  strokeWidth={isActive ? 1.5 : 0.75}
                  strokeLinecap="round"
                  strokeDasharray={isActive ? "4 3" : undefined}
                >
                  {isActive && (
                    <animate
                      attributeName="stroke-dashoffset"
                      from="0" to="-14"
                      dur="0.8s"
                      repeatCount="indefinite"
                    />
                  )}
                </line>
              </g>
            );
          })}

          {/* Web search line from center to cloud icon */}
          {showWebSearch && (
            <g>
              <line
                x1={CENTER} y1={CENTER} x2={WEB_X} y2={WEB_Y}
                stroke={webSearchActive
                  ? "rgba(251, 191, 36, 0.5)"
                  : "rgba(251, 191, 36, 0.2)"}
                strokeWidth={webSearchActive ? 1.5 : 0.75}
                strokeLinecap="round"
                strokeDasharray="3 4"
              >
                {webSearchActive && (
                  <animate
                    attributeName="stroke-dashoffset"
                    from="0" to="-14"
                    dur="0.6s"
                    repeatCount="indefinite"
                  />
                )}
              </line>
            </g>
          )}
        </svg>

        {/* Section stars (HTML layer for drift animation) */}
        {KB_SECTIONS.map(({ id, label, drifts, dur, delay }, i) => {
          const op = sectionOps[id];
          const isActive = activeSection === id || (activeSection === null && activeOp !== null);
          const isGlobal = activeSection === null && activeOp !== null;
          const pos = starPositions[i];

          const starStyle = getStarStyle(op, isActive, isGlobal);
          const driftVars: Record<string, string> = {
            "--drift-x1": `${drifts[0]}px`, "--drift-y1": `${drifts[1]}px`,
            "--drift-x2": `${drifts[2]}px`, "--drift-y2": `${drifts[3]}px`,
            "--drift-x3": `${drifts[4]}px`, "--drift-y3": `${drifts[5]}px`,
            "--drift-x4": `${drifts[6]}px`, "--drift-y4": `${drifts[7]}px`,
          };
          const floatAnim = pipelineComplete ? null : `kbStarFloat ${dur}s ease-in-out ${delay}s infinite`;
          const pulseAnim = starStyle.animation;
          const composedAnim = floatAnim && pulseAnim
            ? `${floatAnim}, ${pulseAnim}`
            : floatAnim ?? pulseAnim ?? "none";

          return (
            <div
              key={id}
              title={label}
              className="absolute rounded-full"
              style={{
                width: STAR_SIZE,
                height: STAR_SIZE,
                left: pos.x - STAR_SIZE / 2,
                top: pos.y - STAR_SIZE / 2,
                ...driftVars,
                ...starStyle,
                animation: composedAnim,
              } as React.CSSProperties}
            />
          );
        })}

        {/* Center core dot — bigger */}
        <div
          className="absolute rounded-full transition-all duration-300"
          style={{
            width: CENTER_SIZE,
            height: CENTER_SIZE,
            left: CENTER - CENTER_SIZE / 2,
            top: CENTER - CENTER_SIZE / 2,
            background: activeOp === "read"
              ? "radial-gradient(circle, rgba(6, 182, 212, 0.9) 0%, rgba(6, 182, 212, 0.3) 70%)"
              : activeOp === "write"
                ? "radial-gradient(circle, rgba(63, 185, 80, 0.9) 0%, rgba(63, 185, 80, 0.3) 70%)"
                : hasActivity
                  ? "radial-gradient(circle, rgba(139, 92, 246, 0.7) 0%, rgba(139, 92, 246, 0.2) 70%)"
                  : "radial-gradient(circle, rgba(139, 92, 246, 0.3) 0%, rgba(139, 92, 246, 0.08) 70%)",
            boxShadow: activeOp
              ? activeOp === "read"
                ? "0 0 12px rgba(6, 182, 212, 0.5), 0 0 4px rgba(6, 182, 212, 0.8)"
                : "0 0 12px rgba(63, 185, 80, 0.5), 0 0 4px rgba(63, 185, 80, 0.8)"
              : hasActivity
                ? "0 0 8px rgba(139, 92, 246, 0.3)"
                : "none",
            animation: activeOp ? "kbStarPulse 2s ease-in-out infinite" : undefined,
            ["--star-opacity" as string]: "0.7",
          } as React.CSSProperties}
        />

        {/* Web search cloud icon */}
        {showWebSearch && (
          <div
            className="absolute transition-all duration-300"
            title={`Web Search${webSearchCount > 0 ? ` (${webSearchCount})` : ""}`}
            style={{
              left: WEB_X - 10,
              top: WEB_Y - 10,
              width: 20,
              height: 20,
              opacity: webSearchActive ? 1 : 0.5,
              filter: webSearchActive ? "drop-shadow(0 0 4px rgba(251, 191, 36, 0.6))" : "none",
              animation: webSearchActive ? "kbStarPulse 1.2s ease-in-out infinite" : undefined,
              ["--star-opacity" as string]: "0.5",
            } as React.CSSProperties}
          >
            <svg viewBox="0 0 24 24" fill="none" className="w-full h-full">
              {/* Globe/internet icon */}
              <circle cx="12" cy="12" r="9" stroke="rgba(251, 191, 36, 0.7)" strokeWidth="1.5" />
              <ellipse cx="12" cy="12" rx="4" ry="9" stroke="rgba(251, 191, 36, 0.5)" strokeWidth="1" />
              <line x1="3" y1="12" x2="21" y2="12" stroke="rgba(251, 191, 36, 0.4)" strokeWidth="1" />
              <line x1="5" y1="7" x2="19" y2="7" stroke="rgba(251, 191, 36, 0.3)" strokeWidth="0.75" />
              <line x1="5" y1="17" x2="19" y2="17" stroke="rgba(251, 191, 36, 0.3)" strokeWidth="0.75" />
            </svg>
          </div>
        )}
      </div>

      {/* R/W/Web counters */}
      {(total > 0 || webSearchCount > 0) && (
        <div className="flex items-center gap-2 text-[9px] font-mono">
          {reads > 0 && <span className="text-cyan-400/80">R:{reads}</span>}
          {writes > 0 && <span className="text-emerald-400/80">W:{writes}</span>}
          {webSearchCount > 0 && <span className="text-amber-400/70">Web:{webSearchCount}</span>}
        </div>
      )}
    </div>
  );
}

function getStarStyle(
  op: KBSectionOp | undefined,
  isTargeted: boolean,
  isGlobalSearch: boolean,
): React.CSSProperties {
  if (isTargeted && !isGlobalSearch) {
    const color = op === "write" ? "rgba(63, 185, 80, 0.9)" : "rgba(6, 182, 212, 0.9)";
    const shadow = op === "write"
      ? "0 0 6px rgba(63, 185, 80, 0.8), 0 0 12px rgba(63, 185, 80, 0.4)"
      : "0 0 6px rgba(6, 182, 212, 0.8), 0 0 12px rgba(6, 182, 212, 0.4)";
    return {
      background: color,
      boxShadow: shadow,
      ["--star-opacity" as string]: "0.9",
      animation: "kbStarPulse 1s ease-in-out infinite",
    };
  }

  if (isGlobalSearch) {
    return {
      background: "rgba(6, 182, 212, 0.5)",
      boxShadow: "0 0 4px rgba(6, 182, 212, 0.4)",
      ["--star-opacity" as string]: "0.5",
      animation: "kbStarPulse 1.5s ease-in-out infinite",
    };
  }

  if (op === "write") {
    return {
      background: "rgba(63, 185, 80, 0.8)",
      boxShadow: "0 0 5px rgba(63, 185, 80, 0.5), 0 0 10px rgba(63, 185, 80, 0.2)",
    };
  }
  if (op === "read") {
    return {
      background: "rgba(6, 182, 212, 0.7)",
      boxShadow: "0 0 5px rgba(6, 182, 212, 0.4), 0 0 10px rgba(6, 182, 212, 0.15)",
    };
  }
  if (op === "list") {
    return {
      background: "rgba(139, 92, 246, 0.35)",
      boxShadow: "0 0 3px rgba(139, 92, 246, 0.2)",
    };
  }

  return {
    background: "rgba(139, 92, 246, 0.12)",
    boxShadow: "none",
  };
}
