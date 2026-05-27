"use client";

import { memo, useRef } from "react";
import { BaseEdge, getBezierPath, type EdgeProps } from "@xyflow/react";
import type { NodeState } from "@/stores/pipeline-store";

export interface FlowEdgeData extends Record<string, unknown> {
  sourceState: NodeState;
  targetState: NodeState;
  semanticType?: "data-flow" | "tool-call" | "kb-rw";
}

const PARTICLE_COUNT = 6;
const PARTICLE_DURATION = 5;

let edgeIdCounter = 0;

/** Color configs per semantic type (active state only) */
const SEMANTIC_STYLES: Record<
  string,
  { stroke: string; particleFill: string; dashArray?: string }
> = {
  "data-flow": {
    stroke: "#5B9CF0",
    particleFill: "#8BB8F0",
  },
  "tool-call": {
    stroke: "var(--color-tool-call)",
    particleFill: "#F0C855",
    dashArray: "8 6",
  },
  "kb-rw": {
    stroke: "var(--color-kb-write)",
    particleFill: "#6EE7B7",
    dashArray: "10 5 2 5",
  },
};

function FlowEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps) {
  const { sourceState, targetState, semanticType = "data-flow" } =
    (data ?? {}) as FlowEdgeData;
  const stableId = useRef(`rf-edge-${edgeIdCounter++}`);

  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });

  const isActive = sourceState === "complete" && targetState === "active";
  const isComplete = sourceState === "complete" && targetState === "complete";
  const isIdle = !isActive && !isComplete;

  // Idle: dashed gray for all types
  if (isIdle) {
    return (
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke: "#3B4D66",
          strokeWidth: 1.5,
          strokeDasharray: "6 4",
          opacity: 0.5,
        }}
      />
    );
  }

  // Complete: emerald glow for all types
  if (isComplete) {
    return (
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke: "#34D399",
          strokeWidth: 2.5,
          filter: "drop-shadow(0 0 6px rgba(52, 211, 153, 0.5))",
        }}
      />
    );
  }

  // Active: semantic styling with particles
  const style = SEMANTIC_STYLES[semanticType] ?? SEMANTIC_STYLES["data-flow"];
  const pathId = `${stableId.current}-${id}`;

  return (
    <g>
      <path
        d={edgePath}
        fill="none"
        stroke={style.stroke}
        strokeWidth={2.5}
        strokeDasharray={style.dashArray}
        opacity={0.5}
        filter="url(#semantic-edge-glow)"
      />
      <defs>
        <path id={pathId} d={edgePath} fill="none" />
        <filter id="semantic-edge-glow">
          <feGaussianBlur stdDeviation="2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {Array.from({ length: PARTICLE_COUNT }).map((_, i) => {
        const delay = -(PARTICLE_DURATION / PARTICLE_COUNT) * i;
        return (
          <circle key={i} r="3.5" fill={style.particleFill} opacity="0.9">
            <animateMotion
              dur={`${PARTICLE_DURATION}s`}
              begin={`${delay}s`}
              repeatCount="indefinite"
              calcMode="linear"
            >
              <mpath href={`#${pathId}`} />
            </animateMotion>
            <animate
              attributeName="opacity"
              values="0;1;1;0"
              keyTimes="0;0.1;0.85;1"
              dur={`${PARTICLE_DURATION}s`}
              begin={`${delay}s`}
              repeatCount="indefinite"
            />
            <animate
              attributeName="r"
              values="2;3.5;3.5;2"
              keyTimes="0;0.1;0.85;1"
              dur={`${PARTICLE_DURATION}s`}
              begin={`${delay}s`}
              repeatCount="indefinite"
            />
          </circle>
        );
      })}
    </g>
  );
}

export const FlowEdge = memo(FlowEdgeComponent);
