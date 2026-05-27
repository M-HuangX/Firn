"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  type Node,
  type Edge,
  type NodeTypes,
  useNodesState,
  useEdgesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useKBGraph } from "@/hooks/use-api";
import { MapNode, type MapNodeData } from "./map-node";
import { NodeDetailPanel } from "./node-detail-panel";
import type { KBGraphNode, KBGraphEdge } from "@/lib/types";

const nodeTypes: NodeTypes = { mapNode: MapNode };

// ─── Layout Algorithm ────────────────────────────────────────────────────────

export function computeConcentricPositions(
  nodes: KBGraphNode[]
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  const centerX = 400;
  const centerY = 400;

  // Core Mind at center
  positions.set("core_mind", { x: centerX, y: centerY });

  // Themes on inner ring (radius ~180)
  const themes = nodes.filter((n) => n.type === "theme");
  themes.forEach((t, i) => {
    const angle = (2 * Math.PI * i) / themes.length - Math.PI / 2;
    positions.set(t.id, {
      x: centerX + 180 * Math.cos(angle),
      y: centerY + 180 * Math.sin(angle),
    });
  });

  // Events on mid ring (radius ~280)
  const events = nodes.filter((n) => n.type === "event");
  events.forEach((e, i) => {
    const angle = (2 * Math.PI * i) / events.length;
    positions.set(e.id, {
      x: centerX + 280 * Math.cos(angle),
      y: centerY + 280 * Math.sin(angle),
    });
  });

  // Stocks on outer ring (radius ~360)
  const stocks = nodes.filter((n) => n.type === "stock");
  stocks.forEach((s, i) => {
    const angle =
      (2 * Math.PI * i) / stocks.length + Math.PI / (stocks.length * 2);
    positions.set(s.id, {
      x: centerX + 360 * Math.cos(angle),
      y: centerY + 360 * Math.sin(angle),
    });
  });

  return positions;
}

// ─── Build React Flow nodes/edges ────────────────────────────────────────────

function buildFlowNodes(
  kbNodes: KBGraphNode[],
  positions: Map<string, { x: number; y: number }>
): Node[] {
  return kbNodes.map((n) => {
    const pos = positions.get(n.id) ?? { x: 0, y: 0 };
    return {
      id: n.id,
      type: "mapNode",
      position: { x: pos.x, y: pos.y },
      data: {
        nodeType: n.type,
        label: n.label,
        chars: n.chars,
        visible: false,
        dimmed: false,
      } satisfies MapNodeData,
    };
  });
}

function buildFlowEdges(kbEdges: KBGraphEdge[]): Edge[] {
  return kbEdges.map((e, i) => ({
    id: `edge-${i}`,
    source: e.source,
    target: e.target,
    style: { stroke: "#1E2D42", strokeWidth: 1.5 },
    className: "",
    animated: false,
  }));
}

// ─── Animation Helpers ───────────────────────────────────────────────────────

type AnimPhase = "idle" | "core" | "themes" | "events" | "stocks" | "edges" | "done";

function getConnectedIds(nodeId: string, edges: KBGraphEdge[]): Set<string> {
  const connected = new Set<string>();
  connected.add(nodeId);
  for (const e of edges) {
    if (e.source === nodeId) connected.add(e.target);
    if (e.target === nodeId) connected.add(e.source);
  }
  return connected;
}

// ─── Component ───────────────────────────────────────────────────────────────

export function KnowledgeMap() {
  const { data: graphData, isLoading } = useKBGraph();
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [animPhase, setAnimPhase] = useState<AnimPhase>("idle");
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const kbNodes = graphData?.nodes ?? [];
  const kbEdges = graphData?.edges ?? [];

  const positions = useMemo(() => computeConcentricPositions(kbNodes), [kbNodes]);

  const initialFlowNodes = useMemo(
    () => buildFlowNodes(kbNodes, positions),
    [kbNodes, positions]
  );
  const initialFlowEdges = useMemo(() => buildFlowEdges(kbEdges), [kbEdges]);

  const [nodes, setNodes] = useNodesState(initialFlowNodes);
  const [edges, setEdges] = useEdgesState(initialFlowEdges);

  // Sync when data changes
  useEffect(() => {
    setNodes(buildFlowNodes(kbNodes, positions));
    setEdges(buildFlowEdges(kbEdges));
  }, [kbNodes, positions, kbEdges, setNodes, setEdges]);

  // ─── Formation Animation ────────────────────────────────────────────────

  const runAnimation = useCallback(() => {
    // Clear any pending timers
    for (const t of timersRef.current) clearTimeout(t);
    timersRef.current = [];

    // Reset all to hidden
    setNodes((nds) =>
      nds.map((n) => ({
        ...n,
        data: { ...n.data, visible: false, dimmed: false },
      }))
    );
    setEdges((eds) =>
      eds.map((e) => ({
        ...e,
        style: { ...e.style, opacity: 0 },
        className: "",
      }))
    );

    setAnimPhase("core");

    // Phase 1: Core (0-500ms)
    const t1 = setTimeout(() => {
      setNodes((nds) =>
        nds.map((n) =>
          (n.data as MapNodeData).nodeType === "core"
            ? { ...n, data: { ...n.data, visible: true } }
            : n
        )
      );
      setAnimPhase("themes");
    }, 100);
    timersRef.current.push(t1);

    // Phase 2: Themes (500-1500ms, staggered)
    const themes = kbNodes.filter((n) => n.type === "theme");
    themes.forEach((theme, i) => {
      const t = setTimeout(() => {
        setNodes((nds) =>
          nds.map((n) =>
            n.id === theme.id ? { ...n, data: { ...n.data, visible: true } } : n
          )
        );
      }, 500 + i * 100);
      timersRef.current.push(t);
    });

    // Phase 3: Events (after themes)
    const eventsStart = 500 + themes.length * 100 + 200;
    const events = kbNodes.filter((n) => n.type === "event");
    events.forEach((ev, i) => {
      const t = setTimeout(() => {
        setNodes((nds) =>
          nds.map((n) =>
            n.id === ev.id ? { ...n, data: { ...n.data, visible: true } } : n
          )
        );
      }, eventsStart + i * 80);
      timersRef.current.push(t);
    });

    // Phase 4: Stocks (after events)
    const stocksStart = eventsStart + events.length * 80 + 200;
    const stocks = kbNodes.filter((n) => n.type === "stock");
    stocks.forEach((stock, i) => {
      const t = setTimeout(() => {
        setNodes((nds) =>
          nds.map((n) =>
            n.id === stock.id
              ? { ...n, data: { ...n.data, visible: true } }
              : n
          )
        );
        setAnimPhase("stocks");
      }, stocksStart + i * 80);
      timersRef.current.push(t);
    });

    // Phase 5: Edges draw in with stroke-dashoffset animation
    const edgesStart = stocksStart + stocks.length * 80 + 200;
    const t5 = setTimeout(() => {
      setEdges((eds) =>
        eds.map((e) => ({
          ...e,
          style: { ...e.style, opacity: 1 },
          className: "edge-drawing",
        }))
      );
      setAnimPhase("edges");
    }, edgesStart);
    timersRef.current.push(t5);

    // Phase 5b: After drawing animation completes, switch to stable visible class
    const t5b = setTimeout(() => {
      setEdges((eds) =>
        eds.map((e) => ({
          ...e,
          className: "edge-visible",
        }))
      );
      setAnimPhase("done");
    }, edgesStart + 900);
    timersRef.current.push(t5b);
  }, [kbNodes, setNodes, setEdges]);

  // Auto-play on first data load
  const hasAnimated = useRef(false);
  useEffect(() => {
    if (kbNodes.length > 0 && !hasAnimated.current) {
      hasAnimated.current = true;
      runAnimation();
    }
  }, [kbNodes.length, runAnimation]);

  // Cleanup timers
  useEffect(() => {
    return () => {
      for (const t of timersRef.current) clearTimeout(t);
    };
  }, []);

  // ─── Hover Dimming ──────────────────────────────────────────────────────

  useEffect(() => {
    if (!hoveredNode) {
      // Un-dim all
      setNodes((nds) =>
        nds.map((n) => ({ ...n, data: { ...n.data, dimmed: false } }))
      );
      return;
    }
    const connected = getConnectedIds(hoveredNode, kbEdges);
    setNodes((nds) =>
      nds.map((n) => ({
        ...n,
        data: { ...n.data, dimmed: !connected.has(n.id) },
      }))
    );
  }, [hoveredNode, kbEdges, setNodes]);

  const onNodeMouseEnter = useCallback((_: React.MouseEvent, node: Node) => {
    setHoveredNode(node.id);
  }, []);

  const onNodeMouseLeave = useCallback(() => {
    setHoveredNode(null);
  }, []);

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
  }, []);

  const proOptions = useMemo(() => ({ hideAttribution: true }), []);

  // ─── Render ─────────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="bg-surface rounded-xl border border-border p-6 min-h-[500px] flex items-center justify-center">
        <div className="text-text-secondary text-sm">Loading knowledge graph...</div>
      </div>
    );
  }

  if (kbNodes.length === 0) {
    return (
      <div className="bg-surface rounded-xl border border-border p-6 min-h-[500px] flex items-center justify-center">
        <div className="text-center">
          <div className="text-text-secondary text-sm">
            No knowledge base data yet. Run a digest to start building.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4 text-xs text-text-secondary">
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full" style={{ background: "#8B5CF6" }} />
            Core Mind
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full" style={{ background: "#06B6D4" }} />
            Themes
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full" style={{ background: "#10B981" }} />
            Stocks
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded" style={{ background: "#F59E0B", transform: "rotate(45deg)", width: 8, height: 8 }} />
            Events
          </span>
        </div>
        <button
          onClick={() => {
            hasAnimated.current = false;
            runAnimation();
          }}
          className="px-3 py-1.5 text-xs font-medium rounded-lg bg-surface border border-border text-text-secondary hover:text-text-primary hover:border-accent/30 transition-colors"
        >
          Replay Growth
        </button>
      </div>
      <div className="relative w-full h-[600px] rounded-xl overflow-hidden bg-slate-950/50 border border-border">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodeMouseEnter={onNodeMouseEnter}
          onNodeMouseLeave={onNodeMouseLeave}
          onNodeClick={onNodeClick}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          proOptions={proOptions}
          panOnDrag
          zoomOnScroll
          zoomOnPinch
          zoomOnDoubleClick={false}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          minZoom={0.4}
          maxZoom={2}
        >
          <Background color="#1f2937" gap={20} size={1} />
        </ReactFlow>
        {selectedNodeId && (
          <NodeDetailPanel
            nodeId={selectedNodeId}
            kbNodes={kbNodes}
            kbEdges={kbEdges}
            onClose={() => setSelectedNodeId(null)}
          />
        )}
      </div>

      {/* Inject keyframes for core pulse */}
      <style>{`
        @keyframes corePulse {
          0%, 100% { box-shadow: 0 0 20px rgba(139, 92, 246, 0.5), 0 0 40px rgba(139, 92, 246, 0.2); }
          50% { box-shadow: 0 0 30px rgba(139, 92, 246, 0.7), 0 0 60px rgba(139, 92, 246, 0.3); }
        }
      `}</style>
    </div>
  );
}
