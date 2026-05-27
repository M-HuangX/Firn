"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  ReactFlow,
  Background,
  type Node,
  type Edge,
  type NodeTypes,
  type EdgeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { usePipelineStore } from "@/stores/pipeline-store";
import { useSSE } from "@/hooks/use-sse";
import { useAnalysis } from "@/hooks/use-api";
import { AgentNode } from "./agent-node";
import { InputNode } from "./input-node";
import { DataFlowEdge } from "./data-flow-edge";
import type { PipelineEvent } from "@/lib/types";

const nodeTypes: NodeTypes = {
  agentNode: AgentNode,
  inputNode: InputNode,
};

const edgeTypes: EdgeTypes = {
  dataFlow: DataFlowEdge,
};

const BASE_NODES: Node[] = [
  { id: "input", type: "inputNode", position: { x: 400, y: 0 }, data: { label: "Input", state: "idle" } },
  { id: "fundamental", type: "agentNode", position: { x: 50, y: 150 }, data: { label: "Fundamental", state: "idle" } },
  { id: "technical", type: "agentNode", position: { x: 230, y: 150 }, data: { label: "Technical", state: "idle" } },
  { id: "value", type: "agentNode", position: { x: 410, y: 150 }, data: { label: "Value", state: "idle" } },
  { id: "macro", type: "agentNode", position: { x: 590, y: 150 }, data: { label: "Macro", state: "idle" } },
  { id: "core", type: "agentNode", position: { x: 310, y: 330 }, data: { label: "Firn", state: "idle" } },
  { id: "report", type: "agentNode", position: { x: 310, y: 480 }, data: { label: "Report", state: "idle" } },
  { id: "audit", type: "agentNode", position: { x: 310, y: 630 }, data: { label: "Audit", state: "idle" } },
];

const BASE_EDGES: Edge[] = [
  { id: "e-input-fund", source: "input", target: "fundamental", type: "dataFlow" },
  { id: "e-input-tech", source: "input", target: "technical", type: "dataFlow" },
  { id: "e-input-val", source: "input", target: "value", type: "dataFlow" },
  { id: "e-input-mac", source: "input", target: "macro", type: "dataFlow" },
  { id: "e-fund-core", source: "fundamental", target: "core", type: "dataFlow" },
  { id: "e-tech-core", source: "technical", target: "core", type: "dataFlow" },
  { id: "e-val-core", source: "value", target: "core", type: "dataFlow" },
  { id: "e-mac-core", source: "macro", target: "core", type: "dataFlow" },
  { id: "e-core-rep", source: "core", target: "report", type: "dataFlow" },
  { id: "e-rep-audit", source: "report", target: "audit", type: "dataFlow" },
];

interface AnalysisDAGProps {
  execId: string;
}

export function AnalysisDAG({ execId }: AnalysisDAGProps) {
  const storeNodes = usePipelineStore((s) => s.nodes);
  const ticker = usePipelineStore((s) => s.ticker);
  const isReplaying = usePipelineStore((s) => s.isReplaying);
  const replayProgress = usePipelineStore((s) => s.replayProgress);
  const processEvent = usePipelineStore((s) => s.processEvent);
  const replayEvents = usePipelineStore((s) => s.replayEvents);
  const reset = usePipelineStore((s) => s.reset);
  const selectNode = usePipelineStore((s) => s.selectNode);

  const { data: detail, isLoading: detailLoading } = useAnalysis(execId);
  const isCompleted = detail?.status === "complete" || detail?.status === "failed";
  const statusKnown = !detailLoading && !!detail;

  const hasReplayedRef = useRef(false);
  const eventsBufferRef = useRef<PipelineEvent[]>([]);

  // Buffer all events for completed analyses
  const handleBufferEvent = useCallback((event: PipelineEvent) => {
    eventsBufferRef.current.push(event);
  }, []);

  // Don't connect SSE until we know the status
  const sseExecId = statusKnown ? execId : null;
  const { isDone } = useSSE(sseExecId, {
    onEvent: isCompleted ? handleBufferEvent : processEvent,
  });

  // Reset store when execId changes
  useEffect(() => {
    hasReplayedRef.current = false;
    eventsBufferRef.current = [];
    reset();
  }, [execId, reset]);

  // Trigger replay once SSE is done and we have buffered events
  useEffect(() => {
    if (isCompleted && isDone && !hasReplayedRef.current && eventsBufferRef.current.length > 0) {
      hasReplayedRef.current = true;
      replayEvents(eventsBufferRef.current);
    }
  }, [isCompleted, isDone, replayEvents]);

  // Derive React Flow nodes directly from store state (no RAF, no stale closures)
  const nodes = useMemo<Node[]>(() => {
    return BASE_NODES.map((node) => {
      const storeData = storeNodes[node.id];
      if (!storeData) return node;

      const newData: Record<string, unknown> = {
        ...node.data,
        state: storeData.state,
        elapsed_s: storeData.elapsed_s,
        token_total: storeData.token_total,
        tool_count: storeData.tool_count,
      };

      if (node.id === "input" && ticker) {
        newData.ticker = ticker;
      }

      return { ...node, data: newData };
    });
  }, [storeNodes, ticker]);

  // Derive React Flow edges directly from store state
  const edges = useMemo<Edge[]>(() => {
    return BASE_EDGES.map((edge) => {
      const sourceState = storeNodes[edge.source]?.state ?? "idle";
      const targetState = storeNodes[edge.target]?.state ?? "idle";
      return {
        ...edge,
        data: { sourceState, targetState },
      };
    });
  }, [storeNodes]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      selectNode(node.id);
    },
    [selectNode]
  );

  const proOptions = useMemo(() => ({ hideAttribution: true }), []);

  // Manual replay trigger
  const handleReplay = useCallback(() => {
    reset();
    hasReplayedRef.current = false;
    setTimeout(() => {
      if (eventsBufferRef.current.length > 0) {
        hasReplayedRef.current = true;
        replayEvents(eventsBufferRef.current);
      }
    }, 100);
  }, [reset, replayEvents]);

  return (
    <div className="w-full h-[700px] rounded-xl overflow-hidden bg-slate-950/50 border border-border relative">
      {/* Replay indicator */}
      {isReplaying && (
        <div className="absolute top-3 left-3 z-10 flex items-center gap-2 bg-background/80 backdrop-blur-sm border border-border rounded-lg px-3 py-1.5">
          <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
          <span className="text-xs text-text-secondary">
            Replaying... {Math.round(replayProgress * 100)}%
          </span>
        </div>
      )}
      {/* Replay button */}
      {isCompleted && !isReplaying && replayProgress >= 1 && (
        <button
          onClick={handleReplay}
          className="absolute top-3 right-3 z-10 flex items-center gap-1.5 bg-background/80 backdrop-blur-sm border border-border rounded-lg px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Replay
        </button>
      )}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={onNodeClick}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        proOptions={proOptions}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        minZoom={0.8}
        maxZoom={1.2}
      >
        <Background color="#1f2937" gap={20} size={1} />
      </ReactFlow>
    </div>
  );
}
