"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";

export interface MapNodeData extends Record<string, unknown> {
  nodeType: "core" | "theme" | "stock" | "event";
  label: string;
  chars: number;
  visible: boolean;
  dimmed: boolean;
}

/** Compute theme node size: 50-70px proportional to chars */
function themeSize(chars: number): number {
  // Clamp between 50 and 70
  const minChars = 500;
  const maxChars = 10000;
  const clamped = Math.max(minChars, Math.min(maxChars, chars));
  const ratio = (clamped - minChars) / (maxChars - minChars);
  return 50 + ratio * 20;
}

function MapNodeComponent({ data }: NodeProps) {
  const { nodeType, label, chars, visible, dimmed } = data as unknown as MapNodeData;

  const baseTransition = "opacity 0.4s ease, transform 0.5s ease";

  if (nodeType === "core") {
    return (
      <div
        className="flex items-center justify-center"
        style={{
          width: 80,
          height: 80,
          borderRadius: "50%",
          background: "#8B5CF6",
          boxShadow: "0 0 20px rgba(139, 92, 246, 0.5), 0 0 40px rgba(139, 92, 246, 0.2)",
          opacity: visible ? (dimmed ? 0.1 : 1) : 0,
          transform: visible ? "scale(1)" : "scale(0)",
          transition: baseTransition,
          animation: visible && !dimmed ? "corePulse 3s ease-in-out infinite" : "none",
        }}
      >
        <Handle type="source" position={Position.Bottom} className="!bg-transparent !border-0 !w-0 !h-0" />
        <div className="text-center pointer-events-none">
          <div className="text-xs font-semibold text-white">Core Mind</div>
          <div className="text-[9px] text-white/70">{chars.toLocaleString()}</div>
        </div>
      </div>
    );
  }

  if (nodeType === "theme") {
    const size = themeSize(chars);
    return (
      <div
        className="flex items-center justify-center"
        style={{
          width: size,
          height: size,
          borderRadius: "50%",
          background: "#06B6D4",
          boxShadow: "0 0 10px rgba(6, 182, 212, 0.3)",
          opacity: visible ? (dimmed ? 0.1 : 1) : 0,
          transform: visible ? "scale(1)" : "scale(0)",
          transition: baseTransition,
        }}
      >
        <Handle type="target" position={Position.Top} className="!bg-transparent !border-0 !w-0 !h-0" />
        <Handle type="source" position={Position.Bottom} className="!bg-transparent !border-0 !w-0 !h-0" />
        <div className="text-[9px] font-medium text-white text-center leading-tight px-1 pointer-events-none max-w-full overflow-hidden">
          {label.length > 12 ? label.slice(0, 11) + "\u2026" : label}
        </div>
      </div>
    );
  }

  if (nodeType === "stock") {
    return (
      <div
        className="flex items-center justify-center"
        style={{
          width: 40,
          height: 40,
          borderRadius: "50%",
          background: "#10B981",
          boxShadow: "0 0 8px rgba(16, 185, 129, 0.3)",
          opacity: visible ? (dimmed ? 0.1 : 1) : 0,
          transform: visible ? "scale(1)" : "scale(0)",
          transition: baseTransition,
        }}
      >
        <Handle type="target" position={Position.Top} className="!bg-transparent !border-0 !w-0 !h-0" />
        <div className="text-[9px] font-mono font-bold text-white pointer-events-none">{label}</div>
      </div>
    );
  }

  // Event: diamond shape
  return (
    <div
      className="flex items-center justify-center"
      style={{
        width: 45,
        height: 45,
        background: "#F59E0B",
        boxShadow: "0 0 8px rgba(245, 158, 11, 0.3)",
        transform: visible
          ? `rotate(45deg) scale(1)`
          : "rotate(45deg) scale(0)",
        opacity: visible ? (dimmed ? 0.1 : 1) : 0,
        transition: baseTransition,
        borderRadius: 4,
      }}
    >
      <Handle type="target" position={Position.Top} className="!bg-transparent !border-0 !w-0 !h-0" />
      <div
        className="text-[8px] font-medium text-white text-center pointer-events-none"
        style={{ transform: "rotate(-45deg)" }}
      >
        {label.length > 8 ? label.slice(0, 7) + "\u2026" : label}
      </div>
    </div>
  );
}

export const MapNode = memo(MapNodeComponent);
