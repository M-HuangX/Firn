"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  ReactFlow,
  Panel,
  useReactFlow,
  type Node,
  type Edge,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useTheaterStore } from "@/stores/pipeline-store";
import { useSSE } from "@/hooks/use-sse";
import type { PipelineEvent } from "@/lib/types";

import { TheaterInputNode } from "./input-node";
import { SpecialistNode } from "./specialist-node";
import { CoreSynthesisNode } from "./core-synthesis-node";
import { ReportTreasureNode } from "./report-treasure-node";
import { FlowEdge, FlowLegend } from "@/components/shared";

/* ------------------------------------------------------------------ */
/*  Node & edge type registrations                                     */
/* ------------------------------------------------------------------ */

const nodeTypes = {
  theaterInput: TheaterInputNode,
  specialist: SpecialistNode,
  coreSynthesis: CoreSynthesisNode,
  reportTreasure: ReportTreasureNode,
};

const edgeTypes = {
  semantic: FlowEdge,
};

/* ------------------------------------------------------------------ */
/*  Layout constants                                                   */
/* ------------------------------------------------------------------ */

const SPECIALIST_IDS = ["fundamental", "technical", "value", "macro"] as const;

const SPECIALIST_LABELS: Record<string, string> = {
  fundamental: "Fundamental",
  technical: "Technical",
  value: "Value",
  macro: "Macro",
};

// Layout dimensions
const COLLAPSED_H = 70;
const EXPANDED_H = 250; // header + 150px workspace + stats footer + padding
const CORE_EXPANDED_H = 380; // header + KB constellation (~130px) + workspace + padding
const NODE_GAP_V = 20; // vertical gap between specialist nodes
const COL_GAP = 50; // horizontal gap between columns

const SPECIALIST_COLLAPSED_W = 130;
const SPECIALIST_EXPANDED_W = 300;
const CORE_COLLAPSED_W = 150;
const CORE_EXPANDED_W = 300;
const INPUT_W = 110;
const REPORT_W = 140;

function isNodeExpanded(nd?: { state?: string; toolCalls?: unknown[] }) {
  return (
    ((nd?.toolCalls as unknown[] | undefined)?.length ?? 0) > 0 ||
    nd?.state === "active" ||
    nd?.state === "complete"
  );
}

function computePositions(storeNodes: Record<string, { state?: string; toolCalls?: unknown[] }>) {
  const positions: Record<string, { x: number; y: number }> = {};

  // --- Vertical layout for specialist column ---
  let y = 0;
  const anySpecialistExpanded = SPECIALIST_IDS.some((sid) => isNodeExpanded(storeNodes[sid]));

  for (const sid of SPECIALIST_IDS) {
    const expanded = isNodeExpanded(storeNodes[sid]);
    positions[sid] = { x: 0, y }; // x set below after horizontal calc
    y += (expanded ? EXPANDED_H : COLLAPSED_H) + NODE_GAP_V;
  }
  const totalH = y - NODE_GAP_V;
  const centerY = totalH / 2 - 30;

  // --- Horizontal layout: each column's x depends on previous column's width ---
  const specialistW = anySpecialistExpanded ? SPECIALIST_EXPANDED_W : SPECIALIST_COLLAPSED_W;

  const coreExpanded = isNodeExpanded(storeNodes.core);
  const coreW = coreExpanded ? CORE_EXPANDED_W : CORE_COLLAPSED_W;
  const coreH = coreExpanded ? CORE_EXPANDED_H : 90;

  // Column x positions
  const inputX = 0;
  const specialistX = inputX + INPUT_W + COL_GAP;
  const coreX = specialistX + specialistW + COL_GAP;
  const reportX = coreX + coreW + COL_GAP;

  // Apply x to specialists
  for (const sid of SPECIALIST_IDS) {
    positions[sid] = { ...positions[sid], x: specialistX };
  }

  positions.input = { x: inputX, y: centerY };
  positions.core = { x: coreX, y: centerY - coreH / 2 + 30 };
  positions.report = { x: reportX, y: centerY };

  return positions;
}

/* ------------------------------------------------------------------ */
/*  Edge definitions                                                   */
/* ------------------------------------------------------------------ */

function buildEdges(): Edge[] {
  const edges: Edge[] = [];

  for (const sid of SPECIALIST_IDS) {
    edges.push({
      id: `input-${sid}`,
      source: "input",
      target: sid,
      type: "semantic",
      data: { sourceState: "idle", targetState: "idle", semanticType: "data-flow" },
    });
  }

  for (const sid of SPECIALIST_IDS) {
    edges.push({
      id: `${sid}-core`,
      source: sid,
      target: "core",
      type: "semantic",
      data: { sourceState: "idle", targetState: "idle", semanticType: "data-flow" },
    });
  }

  edges.push({
    id: "core-report",
    source: "core",
    target: "report",
    type: "semantic",
    data: { sourceState: "idle", targetState: "idle", semanticType: "data-flow" },
  });

  return edges;
}

/* ------------------------------------------------------------------ */
/*  Auto-fit helper (must be a child of ReactFlow)                     */
/* ------------------------------------------------------------------ */

function AutoFitView({ nodeFingerprint }: { nodeFingerprint: string }) {
  const { fitView } = useReactFlow();
  const prevFingerprint = useRef(nodeFingerprint);

  useEffect(() => {
    if (prevFingerprint.current === nodeFingerprint) return;
    prevFingerprint.current = nodeFingerprint;
    // Delay to let DOM nodes resize before measuring (CSS transition is 500ms)
    const t1 = setTimeout(() => fitView({ padding: 0.15, duration: 300 }), 250);
    // Second pass: after CSS transitions fully complete
    const t2 = setTimeout(() => fitView({ padding: 0.15, duration: 200 }), 800);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [nodeFingerprint, fitView]);

  return null;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

interface AnalysisTheaterProps {
  execId: string;
  isComplete: boolean;
  hasAudit: boolean;
  ticker: string;
}

export function AnalysisTheater({
  execId,
  isComplete: detailComplete,
  hasAudit,
  ticker,
}: AnalysisTheaterProps) {
  const storeNodes = useTheaterStore((s) => s.nodes);
  const processEvent = useTheaterStore((s) => s.processEvent);
  const replayEvents = useTheaterStore((s) => s.replayEvents);
  const reset = useTheaterStore((s) => s.reset);
  const openReportOverlay = useTheaterStore((s) => s.openReportOverlay);

  // Refs for SSE callback stability
  const processEventRef = useRef(processEvent);
  processEventRef.current = processEvent;
  const eventBuffer = useRef<PipelineEvent[]>([]);
  const hasReplayed = useRef(false);
  // Track whether execution was already complete when page loaded
  // (true → buffer+replay; false → process immediately including audit)
  const wasCompleteOnMount = useRef<boolean | null>(null);

  // Reset store + refs when execId changes
  useEffect(() => {
    reset();
    hasReplayed.current = false;
    eventBuffer.current = [];
    wasCompleteOnMount.current = null;
  }, [execId, reset]);

  // Capture initial completion state once detail loads
  useEffect(() => {
    if (wasCompleteOnMount.current === null && detailComplete !== undefined) {
      wasCompleteOnMount.current = detailComplete;
    }
  }, [detailComplete]);

  const onSSEEvent = useCallback((event: PipelineEvent) => {
    // Only buffer for replay if execution was already done when page loaded
    if (wasCompleteOnMount.current && !hasReplayed.current) {
      eventBuffer.current.push(event);
    } else {
      processEventRef.current(event);
    }
  }, []);

  // Gate SSE on detail status being known
  const statusKnown = detailComplete !== undefined;
  const sseExecId = statusKnown ? execId : null;
  const { isDone } = useSSE(sseExecId, { onEvent: onSSEEvent });

  // When SSE finishes for a completed analysis, replay buffered events
  useEffect(() => {
    if (isDone && wasCompleteOnMount.current && !hasReplayed.current && eventBuffer.current.length > 0) {
      hasReplayed.current = true;
      replayEvents(eventBuffer.current);
      eventBuffer.current = [];
    }
  }, [isDone, replayEvents]);

  /* ---- Node click: only for report overlay ---- */

  const handleNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      if (node.id === "report" && storeNodes.report?.state === "complete") {
        openReportOverlay();
      }
    },
    [openReportOverlay, storeNodes.report?.state]
  );

  /* ---- Compute dynamic positions ---- */

  const positions = useMemo(() => computePositions(storeNodes), [storeNodes]);

  /* ---- Build React Flow nodes from store ---- */

  const rfNodes = useMemo((): Node[] => {
    const nodes: Node[] = [];

    nodes.push({
      id: "input",
      type: "theaterInput",
      position: positions.input,
      data: {
        label: "Input",
        state: storeNodes.input?.state ?? "idle",
        ticker,
      },
      draggable: false,
      selectable: false,
    });

    for (const sid of SPECIALIST_IDS) {
      const nd = storeNodes[sid];
      nodes.push({
        id: sid,
        type: "specialist",
        position: positions[sid],
        data: {
          label: SPECIALIST_LABELS[sid],
          agentId: sid,
          state: nd?.state ?? "idle",
          elapsed_s: nd?.elapsed_s,
          token_total: nd?.token_total,
          tool_count: nd?.tool_count,
        },
        draggable: false,
        selectable: false,
      });
    }

    const coreNd = storeNodes.core;
    nodes.push({
      id: "core",
      type: "coreSynthesis",
      position: positions.core,
      data: {
        label: "Firn",
        state: coreNd?.state ?? "idle",
        elapsed_s: coreNd?.elapsed_s,
        token_total: coreNd?.token_total,
        tool_count: coreNd?.tool_count,
      },
      draggable: false,
      selectable: false,
    });

    const reportNd = storeNodes.report;
    nodes.push({
      id: "report",
      type: "reportTreasure",
      position: positions.report,
      data: {
        state: reportNd?.state ?? "idle",
        hasAudit,
      },
      draggable: false,
      selectable: false,
    });

    return nodes;
  }, [storeNodes, positions, ticker, hasAudit]);

  /* ---- Fingerprint for auto-fit (changes when nodes expand/collapse) ---- */

  const nodeFingerprint = useMemo(() => {
    const parts = [...SPECIALIST_IDS, "core" as const]
      .map((id) => {
        const nd = storeNodes[id];
        const expanded =
          (nd?.toolCalls?.length ?? 0) > 0 ||
          nd?.state === "active" ||
          nd?.state === "complete";
        return `${id}:${expanded ? "e" : "c"}`;
      });
    // Include audit state — report node grows when audit is active
    const auditState = storeNodes.audit?.state ?? "idle";
    parts.push(`audit:${auditState}`);
    return parts.join(",");
  }, [storeNodes]);

  /* ---- Build edges with live state ---- */

  const rfEdges = useMemo((): Edge[] => {
    return buildEdges().map((edge) => {
      const sourceNode = storeNodes[edge.source];
      const targetNode = storeNodes[edge.target];
      return {
        ...edge,
        data: {
          ...edge.data,
          sourceState: sourceNode?.state ?? "idle",
          targetState: targetNode?.state ?? "idle",
        },
      };
    });
  }, [storeNodes]);

  return (
    <div className="w-full h-full">
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={handleNodeClick}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.3}
        maxZoom={1.3}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        preventScrolling={false}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <AutoFitView nodeFingerprint={nodeFingerprint} />
        <Panel position="bottom-right">
          <FlowLegend variant="analysis" />
        </Panel>
      </ReactFlow>
    </div>
  );
}
