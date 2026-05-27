"use client";

import { memo, useRef } from "react";
import { BaseEdge, getBezierPath, type EdgeProps } from "@xyflow/react";
import type { NodeState } from "@/stores/pipeline-store";

export interface DataFlowEdgeData extends Record<string, unknown> {
  sourceState: NodeState;
  targetState: NodeState;
}

const PARTICLE_COUNT = 6;
const PARTICLE_DURATION = 5;

let edgeIdCounter = 0;

function DataFlowEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps) {
  const { sourceState, targetState } = (data ?? {}) as DataFlowEdgeData;
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

  // Active: animated particles
  const pathId = `${stableId.current}-${id}`;
  return (
    <g>
      <path
        d={edgePath}
        fill="none"
        stroke="#5B9CF0"
        strokeWidth={2.5}
        opacity={0.5}
        filter="url(#legacy-edge-glow)"
      />
      <defs>
        <path id={pathId} d={edgePath} fill="none" />
        <filter id="legacy-edge-glow">
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
          <circle key={i} r="3.5" fill="#8BB8F0" opacity="0.9">
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

export const DataFlowEdge = memo(DataFlowEdgeComponent);
