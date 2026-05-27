import { create } from "zustand";
import type { PipelineEvent } from "@/lib/types";

export type NodeState = "idle" | "active" | "complete" | "error";

export type KBSectionOp = 'read' | 'write' | 'list';

export interface AuditVerdictEntry {
  verdict: string;
  count: number;
  claims: string[];
}

export interface AuditProgress {
  current: number;
  total: number;
  currentClaim?: string;
}

export interface AuditCitationEntry {
  claim: string;
  verdict: string;
  sourceAgent: string;
  cascade: boolean;
}

export interface NodeData {
  state: NodeState;
  elapsed_s?: number;
  token_total?: number;
  tool_count?: number;
  output_length?: number;
  toolCalls: ToolCallEntry[];
  kbReads?: number;
  kbWrites?: number;
  kbActiveOp?: 'read' | 'write' | null;
  kbSectionOps?: Record<string, KBSectionOp>;
  kbActiveSection?: string | null;
  webSearchActive?: boolean;
  webSearchCount?: number;
  /** True when audit agent is currently reading this node's data */
  auditHighlight?: boolean;
  /** v2: per-tool-call verdict badges (key = tool call index) */
  auditVerdicts?: Record<number, AuditVerdictEntry>;
  /** v2: Round 1 scan animation active */
  auditScanning?: boolean;
  /** v2: Round 1 progress for this specialist */
  auditProgress?: AuditProgress;
  /** v2: tool call index currently being audited (for auto-scroll) */
  auditActiveIndex?: number;
  /** v2: current audit phase (audit node only) */
  auditPhase?: "round1" | "round2" | null;
  /** v2: Round 2 citation entries for mini-log display (audit node only) */
  auditCitations?: AuditCitationEntry[];
  /** R2a evidence count (audit node only) */
  r2aCount?: number;
  /** R2b evidence count (audit node only) */
  r2bCount?: number;
  /** Which audit round is highlighting this node — determines halo color */
  auditHighlightSource?: "r1" | "r2a" | "r2b";
}

export interface ToolCallEntry {
  tool_name: string;
  agent: string;
  duration_s?: number;
  success?: boolean;
  output_length?: number;
  input?: string;
  startedAt?: string;
}

interface PipelineStore {
  nodes: Record<string, NodeData>;
  events: PipelineEvent[];
  isComplete: boolean;
  isReplaying: boolean;
  replayProgress: number; // 0-1
  replaySpeed: number; // speed multiplier (default 3)
  ticker: string | null;
  selectedNodeId: string | null;
  selectedToolCall: { agent: string; index: number } | null;

  // Theater-specific state (Phase 6B)
  expandedNodeId: string | null;
  reportOverlayOpen: boolean;
  lifecycleReplayActive: boolean;
  activeSpecialist: string | null; // Currently running specialist (for auto-expand)

  processEvent(event: PipelineEvent): void;
  replayEvents(events: PipelineEvent[]): void;
  stopReplay(): void;
  seekToPosition(fraction: number): void;
  setReplaySpeed(speed: number): void;
  selectNode(id: string | null): void;
  selectToolCall(agent: string, index: number): void;
  clearToolCallSelection(): void;
  expandNode(id: string | null): void;
  toggleExpandNode(id: string | null): void;
  openReportOverlay(): void;
  closeReportOverlay(): void;
  startLifecycleReplay(): void;
  stopLifecycleReplay(): void;
  reset(): void;
}

/** Internal handle for cancelling replay */
let replayTimers: ReturnType<typeof setTimeout>[] = [];
/** Saved events for lifecycle replay restoration */
let savedLifecycleEvents: PipelineEvent[] = [];

/**
 * Compute cumulative replay delays for a list of events.
 * Shared by replayEvents, seekToPosition, and setReplaySpeed.
 */
function computeReplayDelays(events: PipelineEvent[], speed: number): number[] {
  const MAX_GAP_MS = 5 * 60_000;
  const COLLAPSED_GAP_MS = 1_500;
  const timestamps = events.map((e) => new Date(e.ts).getTime());
  const delays: number[] = [0];
  for (let i = 1; i < timestamps.length; i++) {
    const rawGap = timestamps[i] - timestamps[i - 1];
    const scaledGap = rawGap > MAX_GAP_MS ? COLLAPSED_GAP_MS : rawGap / speed;
    delays.push(delays[i - 1] + scaledGap);
  }
  return delays;
}

const INITIAL_NODES: Record<string, NodeData> = {
  input: { state: "idle", toolCalls: [] },
  fundamental: { state: "idle", toolCalls: [] },
  technical: { state: "idle", toolCalls: [] },
  value: { state: "idle", toolCalls: [] },
  macro: { state: "idle", toolCalls: [] },
  core: { state: "idle", toolCalls: [] },
  report: { state: "idle", toolCalls: [] },
  audit: { state: "idle", toolCalls: [] },
};

function cloneInitialNodes(): Record<string, NodeData> {
  const result: Record<string, NodeData> = {};
  for (const [k, v] of Object.entries(INITIAL_NODES)) {
    result[k] = { ...v, toolCalls: [] };
  }
  return result;
}

const KB_READ_TOOLS = new Set([
  "kb_search", "kb_read", "kb_read_core_mind", "kb_list", "read_inbox_item",
]);
const KB_WRITE_TOOLS = new Set([
  "kb_write", "kb_write_core_mind", "kb_edit", "kb_archive", "kb_log",
]);

/** Map SSE agent names to store node IDs */
function resolveAgentId(rawAgent: string): string {
  if (rawAgent === "core_analysis") return "core";
  if (rawAgent === "audit_analysis") return "audit";
  // v2 round agents map to audit node
  if (rawAgent.startsWith("audit_r1_") || rawAgent === "audit_r2_report") return "audit";
  return rawAgent;
}

/** Extract which specialist node an audit tool call is inspecting */
function getAuditTarget(toolName: string, input?: string): string | null {
  if (toolName !== "read_trace_file" || !input) return null;
  if (input.includes("fundamental")) return "fundamental";
  if (input.includes("technical")) return "technical";
  if (input.includes("value")) return "value";
  if (input.includes("macro")) return "macro";
  if (input.includes("core_analysis")) return "core";
  if (input.includes("report.md") || input.includes("report")) return "report";
  return null;
}

/** Extract which KB section a tool call targets */
function extractKBSection(toolName: string, input?: string): string | null {
  if (toolName === "kb_read_core_mind" || toolName === "kb_write_core_mind") return "core_mind";
  if (toolName === "kb_search") return null; // global operation
  if (!input) return null;
  const match = input.match(/['"]section['"]:\s*['"]([^'"]+)['"]/);
  return match?.[1] ?? null;
}

export const usePipelineStore = create<PipelineStore>((set, get) => ({
  nodes: cloneInitialNodes(),
  events: [],
  isComplete: false,
  isReplaying: false,
  replayProgress: 0,
  replaySpeed: 3,
  ticker: null,
  selectedNodeId: null,
  selectedToolCall: null,

  // Theater state
  expandedNodeId: null,
  reportOverlayOpen: false,
  lifecycleReplayActive: false,
  activeSpecialist: null,

  processEvent(event: PipelineEvent) {
    set((state) => {
      const nodes = { ...state.nodes };
      const eventName = event.event;
      const data = event.data ?? {};

      // analysis.start
      if (eventName === "analysis.start") {
        // Mark input as complete (ticker received)
        nodes.input = { ...nodes.input, state: "complete" };
        return {
          events: [...state.events, event],
          nodes,
          ticker: (data.ticker as string) ?? state.ticker,
        };
      }

      // specialist.{name}.start
      if (eventName.startsWith("specialist.") && eventName.endsWith(".start")) {
        const agent = eventName.split(".")[1];
        if (nodes[agent]) {
          nodes[agent] = { ...nodes[agent], state: "active" };
        }
        return { events: [...state.events, event], nodes, activeSpecialist: agent };
      }

      // specialist.{name}.complete
      if (eventName.startsWith("specialist.") && eventName.endsWith(".complete")) {
        const agent = eventName.split(".")[1];
        if (nodes[agent]) {
          const failed = data.success === false;
          nodes[agent] = {
            ...nodes[agent],
            state: failed ? "error" : "complete",
            elapsed_s: data.elapsed_s as number | undefined,
            token_total: data.token_total as number | undefined,
            tool_count: data.tool_count as number | undefined,
            output_length: data.output_length as number | undefined,
          };
        }
        return {
          events: [...state.events, event],
          nodes,
          activeSpecialist: state.activeSpecialist === agent ? null : state.activeSpecialist,
        };
      }

      // analysis.core_start
      if (eventName === "analysis.core_start") {
        nodes.core = { ...nodes.core, state: "active" };
        return { events: [...state.events, event], nodes };
      }

      // analysis.core_complete
      if (eventName === "analysis.core_complete") {
        nodes.core = {
          ...nodes.core,
          state: "complete",
          elapsed_s: data.elapsed_s as number | undefined,
          token_total: data.token_total as number | undefined,
          tool_count: data.tool_count as number | undefined,
          output_length: data.output_length as number | undefined,
        };
        nodes.report = { ...nodes.report, state: "complete" };
        return { events: [...state.events, event], nodes };
      }

      // analysis.end
      if (eventName === "analysis.end") {
        return { events: [...state.events, event], nodes, isComplete: true };
      }

      // audit.start
      if (eventName === "audit.start") {
        nodes.audit = { ...nodes.audit, state: "active" };
        return { events: [...state.events, event], nodes };
      }

      // audit.complete
      if (eventName === "audit.complete") {
        const failed = data.success === false;
        nodes.audit = {
          ...nodes.audit,
          state: failed ? "error" : "complete",
          elapsed_s: data.duration_s as number | undefined,
          tool_count: data.total_claims as number | undefined,
        };
        // Clear any lingering audit highlights/scanning/active-index on all nodes
        for (const key of Object.keys(nodes)) {
          if (nodes[key].auditHighlight || nodes[key].auditScanning || nodes[key].auditActiveIndex != null) {
            nodes[key] = { ...nodes[key], auditHighlight: false, auditScanning: false, auditActiveIndex: undefined, auditHighlightSource: undefined };
          }
        }
        return { events: [...state.events, event], nodes };
      }

      // v2: audit.round1.specialist_start — begin scan animation on specialist
      if (eventName === "audit.round1.specialist_start") {
        const agent = data.agent as string;
        if (nodes[agent]) {
          nodes[agent] = {
            ...nodes[agent],
            auditScanning: true,
            auditHighlight: true,
            auditHighlightSource: "r1",
            auditProgress: { current: 0, total: 0 },
          };
        }
        return { events: [...state.events, event], nodes };
      }

      // v2: audit.claim_recorded — add verdict badge to specialist tool call row
      if (eventName === "audit.claim_recorded") {
        const agent = data.agent as string;
        const sourceIndex = data.source_index as number;
        const verdict = data.verdict as string;
        const claim = (data.claim as string) ?? "";
        if (nodes[agent] && sourceIndex >= 0) {
          const prev = nodes[agent].auditVerdicts ?? {};
          const existing = prev[sourceIndex];
          const entry: AuditVerdictEntry = existing
            ? { verdict: existing.verdict === verdict ? verdict : "mixed", count: existing.count + 1, claims: [...existing.claims, claim] }
            : { verdict, count: 1, claims: [claim] };
          const progress = nodes[agent].auditProgress ?? { current: 0, total: 0 };
          nodes[agent] = {
            ...nodes[agent],
            auditVerdicts: { ...prev, [sourceIndex]: entry },
            // Only increment current (total unknown until specialist_end)
            auditProgress: { current: progress.current + 1, total: progress.total, currentClaim: claim },
            auditActiveIndex: sourceIndex,
          };
        }
        return { events: [...state.events, event], nodes };
      }

      // v2: audit.round1.specialist_end — finalize specialist scan
      if (eventName === "audit.round1.specialist_end") {
        const agent = data.agent as string;
        if (nodes[agent]) {
          const hasError = !!data.error;
          const total = (data.total_claims as number) ?? 0;
          const verified = (data.tool_verified as number) ?? 0;
          // On error, use accumulated claim count (total=0 during scanning, use current as fallback)
          const prev = nodes[agent].auditProgress ?? { current: 0, total: 0 };
          const displayTotal = total > 0 ? total : prev.current; // fallback to claims found
          const displayCurrent = total > 0 ? total : prev.current;
          const label = hasError && displayTotal === 0
            ? "error"
            : `${verified || displayCurrent}/${displayTotal} verified`;
          nodes[agent] = {
            ...nodes[agent],
            auditScanning: false,
            auditActiveIndex: undefined,
            auditProgress: { current: displayCurrent, total: displayTotal, currentClaim: label },
          };
        }
        return { events: [...state.events, event], nodes };
      }

      // v2: audit.round1.start — set audit phase
      if (eventName === "audit.round1.start") {
        nodes.audit = { ...nodes.audit, auditPhase: "round1" };
        return { events: [...state.events, event], nodes };
      }

      // v2: audit.round1.end — clear phase (will be set to round2 shortly)
      if (eventName === "audit.round1.end") {
        return { events: [...state.events, event], nodes };
      }

      // v2: audit.citation_recorded — update audit node with Round 2 progress + citation entry
      if (eventName === "audit.citation_recorded") {
        const claimId = data.claim_id as number;
        const prevCitations = nodes.audit.auditCitations ?? [];
        const entry: AuditCitationEntry = {
          claim: (data.claim as string) ?? "",
          verdict: (data.verdict as string) ?? "",
          sourceAgent: (data.source_agent as string) ?? "",
          cascade: (data.cascade_verified as boolean) ?? false,
        };
        nodes.audit = {
          ...nodes.audit,
          tool_count: claimId,
          auditCitations: [...prevCitations, entry],
        };
        // Flash the source specialist node + scroll to audited tool call
        const sourceAgent = data.source_agent as string;
        const sourceIndex = data.source_index as number;
        if (sourceAgent && nodes[sourceAgent]) {
          const cascadeVerified = (data.cascade_verified as boolean) ?? false;
          nodes[sourceAgent] = {
            ...nodes[sourceAgent],
            auditHighlight: true,
            auditHighlightSource: cascadeVerified ? "r2a" : "r2b",
            ...(sourceIndex >= 0 ? { auditActiveIndex: sourceIndex } : {}),
          };
        }
        return { events: [...state.events, event], nodes };
      }

      // v2: audit.round2.start — set phase to round2
      if (eventName === "audit.round2.start") {
        nodes.audit = {
          ...nodes.audit,
          auditPhase: "round2",
          auditCitations: [],
          auditProgress: { current: 0, total: 0 },
          r2aCount: 0,
          r2bCount: 0,
        };
        return { events: [...state.events, event], nodes };
      }

      // v4: audit.round2.r2a_start
      if (eventName === "audit.round2.r2a_start") {
        return { events: [...state.events, event], nodes };
      }

      // v4: audit.round2.r2b_start
      if (eventName === "audit.round2.r2b_start") {
        return { events: [...state.events, event], nodes };
      }

      // v4: audit.round2.r2a_end
      if (eventName === "audit.round2.r2a_end") {
        return { events: [...state.events, event], nodes };
      }

      // v4: audit.round2.r2b_end
      if (eventName === "audit.round2.r2b_end") {
        return { events: [...state.events, event], nodes };
      }

      // v3: audit.evidence_recorded — real-time R2 progress (emitted by R2a/R2b agents)
      if (eventName === "audit.evidence_recorded") {
        const claim = (data.claim as string) ?? "";
        const evidenceType = data.evidence_type as string; // "specialist" or "source"
        const sourceAgent = (data.specialist_agent ?? data.source_agent ?? "") as string;
        const sourceIndex = typeof data.source_index === "number" ? data.source_index : -1;
        const progress = nodes.audit.auditProgress ?? { current: 0, total: 0 };
        const prevR2a = nodes.audit.r2aCount ?? 0;
        const prevR2b = nodes.audit.r2bCount ?? 0;
        nodes.audit = {
          ...nodes.audit,
          auditProgress: {
            current: progress.current + 1,
            total: progress.total,
            currentClaim: claim,
          },
          ...(evidenceType === "specialist"
            ? { r2aCount: prevR2a + 1 }
            : { r2bCount: prevR2b + 1 }),
        };
        // Moving spotlight + tool call highlight
        for (const key of ["fundamental", "technical", "value", "macro"]) {
          if (key !== sourceAgent) {
            if (nodes[key]?.auditHighlight || nodes[key]?.auditActiveIndex != null) {
              nodes[key] = {
                ...nodes[key],
                auditHighlight: false,
                auditActiveIndex: undefined,
                auditHighlightSource: undefined,
              };
            }
          }
        }
        if (sourceAgent && nodes[sourceAgent]) {
          nodes[sourceAgent] = {
            ...nodes[sourceAgent],
            auditHighlight: true,
            auditHighlightSource: evidenceType === "specialist" ? "r2a" : "r2b",
            ...(sourceIndex >= 0 ? { auditActiveIndex: sourceIndex } : {}),
          };
        }
        return { events: [...state.events, event], nodes };
      }

      // v2: audit.round2.end
      if (eventName === "audit.round2.end") {
        const r2aFinal = (data.specialist_evidence as number) ?? nodes.audit.r2aCount ?? 0;
        const r2bFinal = (data.source_evidence as number) ?? nodes.audit.r2bCount ?? 0;
        nodes.audit = { ...nodes.audit, r2aCount: r2aFinal, r2bCount: r2bFinal };
        return { events: [...state.events, event], nodes };
      }

      // agent.tool_call.start
      if (eventName === "agent.tool_call.start") {
        const agent = resolveAgentId(data.agent as string);
        if (nodes[agent]) {
          const toolName = data.tool_name as string;
          const inputStr = data.input as string | undefined;
          const entry: ToolCallEntry = {
            tool_name: toolName,
            agent,
            input: inputStr,
            startedAt: event.ts,
          };
          const updatedNode = {
            ...nodes[agent],
            toolCalls: [...nodes[agent].toolCalls, entry],
          };
          // Track KB activity
          if (KB_READ_TOOLS.has(toolName)) {
            updatedNode.kbActiveOp = 'read';
            const section = extractKBSection(toolName, inputStr);
            updatedNode.kbActiveSection = section; // null for kb_search (global)
          } else if (KB_WRITE_TOOLS.has(toolName)) {
            updatedNode.kbActiveOp = 'write';
            const section = extractKBSection(toolName, inputStr);
            updatedNode.kbActiveSection = section;
          }
          // Track web search
          if (toolName === 'web_search') {
            updatedNode.webSearchActive = true;
          }
          nodes[agent] = updatedNode;
          // Audit cross-reference: highlight the specialist being inspected
          // Highlights accumulate — all inspected nodes stay lit until audit.complete
          if (agent === "audit") {
            const target = getAuditTarget(toolName, inputStr);
            if (target && nodes[target]) {
              nodes[target] = { ...nodes[target], auditHighlight: true };
            }
          }
        }
        return { events: [...state.events, event], nodes };
      }

      // agent.tool_call.end
      if (eventName === "agent.tool_call.end") {
        const agent = resolveAgentId(data.agent as string);
        const toolName = data.tool_name as string;
        if (nodes[agent]) {
          const calls = [...nodes[agent].toolCalls];
          // Find last unfinished call for this tool — also grab its input for section parsing
          let matchedInput: string | undefined;
          for (let i = calls.length - 1; i >= 0; i--) {
            if (calls[i].tool_name === toolName && calls[i].duration_s === undefined) {
              matchedInput = calls[i].input;
              calls[i] = {
                ...calls[i],
                duration_s: data.duration_s as number | undefined,
                success: data.success as boolean | undefined,
                output_length: data.output_length as number | undefined,
              };
              break;
            }
          }
          const updatedNode = {
            ...nodes[agent],
            toolCalls: calls,
            kbActiveOp: null as 'read' | 'write' | null,
            kbActiveSection: null as string | null,
          };
          // Increment KB counters + track section ops
          if (KB_READ_TOOLS.has(toolName)) {
            updatedNode.kbReads = (nodes[agent].kbReads ?? 0) + 1;
            const section = extractKBSection(toolName, matchedInput);
            if (section) {
              const prevOps = nodes[agent].kbSectionOps ?? {};
              const opType: KBSectionOp = toolName === "kb_list" ? "list" : "read";
              // Escalate: list < read < write
              const prev = prevOps[section];
              const shouldUpdate = !prev || prev === "list" || (prev === "read" && opType === "read");
              updatedNode.kbSectionOps = {
                ...prevOps,
                ...(shouldUpdate || !prev ? { [section]: opType } : {}),
              };
            } else if (toolName === "kb_search") {
              // Global search — mark all known sections as 'list' if not already higher
              const prevOps = nodes[agent].kbSectionOps ?? {};
              const allSections = ["stocks", "themes", "events", "core_mind", "user_views", "forwarded"];
              const updated = { ...prevOps };
              for (const s of allSections) {
                if (!updated[s]) updated[s] = "list";
              }
              updatedNode.kbSectionOps = updated;
            }
          } else if (KB_WRITE_TOOLS.has(toolName)) {
            updatedNode.kbWrites = (nodes[agent].kbWrites ?? 0) + 1;
            const section = extractKBSection(toolName, matchedInput);
            if (section) {
              const prevOps = nodes[agent].kbSectionOps ?? {};
              // Write always wins (highest priority)
              updatedNode.kbSectionOps = { ...prevOps, [section]: "write" };
            }
          }
          // Track web search completion
          if (toolName === 'web_search') {
            updatedNode.webSearchActive = false;
            updatedNode.webSearchCount = (nodes[agent].webSearchCount ?? 0) + 1;
          }
          nodes[agent] = updatedNode;
          // Audit highlight is NOT cleared on tool_call.end — it persists
          // until audit moves to a different specialist (on next start) or audit.complete
        }
        return { events: [...state.events, event], nodes };
      }

      // Default: just append event
      return { events: [...state.events, event] };
    });
  },

  replayEvents(events: PipelineEvent[]) {
    // Cancel any existing replay
    replayTimers.forEach(clearTimeout);
    replayTimers = [];

    if (events.length === 0) return;

    // Save for skip-to-end (works for both SSE auto-replay and lifecycle replay)
    savedLifecycleEvents = [...events];

    set({ isReplaying: true, replayProgress: 0 });

    const delays = computeReplayDelays(events, get().replaySpeed);
    const processEvent = get().processEvent;
    let processedCount = 0;

    events.forEach((event, i) => {
      const timer = setTimeout(() => {
        processEvent(event);
        processedCount++;
        set({ replayProgress: processedCount / events.length });
        if (processedCount === events.length) {
          set({ isReplaying: false, replayProgress: 1, lifecycleReplayActive: false });
        }
      }, delays[i]);

      replayTimers.push(timer);
    });
  },

  stopReplay() {
    replayTimers.forEach(clearTimeout);
    replayTimers = [];
    set({ isReplaying: false });
  },

  seekToPosition(fraction: number) {
    if (savedLifecycleEvents.length === 0) return;

    // Clamp fraction
    const f = Math.max(0, Math.min(1, fraction));

    // Edge case: seek to 0% = reset + replay from start
    if (f === 0) {
      replayTimers.forEach(clearTimeout);
      replayTimers = [];
      set({
        nodes: cloneInitialNodes(),
        events: [],
        isComplete: false,
        isReplaying: true,
        replayProgress: 0,
        activeSpecialist: null,
      });
      // Re-schedule all events
      const allEvents = savedLifecycleEvents;
      const delays = computeReplayDelays(allEvents, get().replaySpeed);
      const processEvent = get().processEvent;
      let processedCount = 0;
      allEvents.forEach((event, i) => {
        const timer = setTimeout(() => {
          processEvent(event);
          processedCount++;
          set({ replayProgress: processedCount / allEvents.length });
          if (processedCount === allEvents.length) {
            set({ isReplaying: false, replayProgress: 1, lifecycleReplayActive: false });
          }
        }, delays[i]);
        replayTimers.push(timer);
      });
      return;
    }

    const targetIndex = Math.round(f * (savedLifecycleEvents.length - 1));

    // Clear all pending timers
    replayTimers.forEach(clearTimeout);
    replayTimers = [];

    // Reset nodes and process events[0..targetIndex] synchronously
    set({ nodes: cloneInitialNodes(), events: [], isComplete: false, activeSpecialist: null });
    const processEvent = get().processEvent;
    for (let i = 0; i <= targetIndex; i++) {
      processEvent(savedLifecycleEvents[i]);
    }

    const totalEvents = savedLifecycleEvents.length;
    set({ replayProgress: (targetIndex + 1) / totalEvents });

    // Edge case: seek to last event
    if (targetIndex >= totalEvents - 1) {
      set({ isReplaying: false, replayProgress: 1, lifecycleReplayActive: false });
      return;
    }

    // Re-schedule remaining events
    set({ isReplaying: true });
    const remainingEvents = savedLifecycleEvents.slice(targetIndex + 1);
    const delays = computeReplayDelays(remainingEvents, get().replaySpeed);
    let processedCount = targetIndex + 1;

    remainingEvents.forEach((event, i) => {
      const timer = setTimeout(() => {
        processEvent(event);
        processedCount++;
        set({ replayProgress: processedCount / totalEvents });
        if (processedCount === totalEvents) {
          set({ isReplaying: false, replayProgress: 1, lifecycleReplayActive: false });
        }
      }, delays[i]);
      replayTimers.push(timer);
    });
  },

  setReplaySpeed(speed: number) {
    set({ replaySpeed: speed });

    // If currently replaying, re-schedule remaining events at new speed
    if (!get().isReplaying || savedLifecycleEvents.length === 0) return;

    // Determine current progress index from replayProgress
    const totalEvents = savedLifecycleEvents.length;
    const currentIndex = Math.round(get().replayProgress * totalEvents) - 1;

    // Use seekToPosition to re-schedule from current position
    // (seekToPosition uses get().replaySpeed which we just updated)
    if (currentIndex >= 0 && currentIndex < totalEvents) {
      get().seekToPosition((currentIndex + 1) / totalEvents);
    }
  },

  selectNode(id: string | null) {
    set({ selectedNodeId: id });
  },

  selectToolCall(agent: string, index: number) {
    set({ selectedToolCall: { agent, index } });
  },
  clearToolCallSelection() {
    set({ selectedToolCall: null });
  },

  expandNode(id: string | null) {
    set({ expandedNodeId: id });
  },

  toggleExpandNode(id: string | null) {
    set((state) => ({
      expandedNodeId: state.expandedNodeId === id ? null : id,
    }));
  },

  openReportOverlay() {
    set({ reportOverlayOpen: true });
  },

  closeReportOverlay() {
    set({ reportOverlayOpen: false });
  },

  startLifecycleReplay() {
    const { events } = get();
    savedLifecycleEvents = [...events];
    // Reset nodes to initial state, then replay
    set({
      nodes: cloneInitialNodes(),
      events: [],
      isComplete: false,
      lifecycleReplayActive: true,
      expandedNodeId: null,
      activeSpecialist: null,
    });
    // Small delay to let UI settle before replay starts
    const t = setTimeout(() => {
      get().replayEvents(savedLifecycleEvents);
    }, 300);
    replayTimers.push(t);
  },

  stopLifecycleReplay() {
    replayTimers.forEach(clearTimeout);
    replayTimers = [];
    // Fast-forward: process all remaining events to reach final state
    if (savedLifecycleEvents.length > 0) {
      const processEvent = get().processEvent;
      set({ nodes: cloneInitialNodes(), events: [], isComplete: false });
      for (const event of savedLifecycleEvents) {
        processEvent(event);
      }
    }
    savedLifecycleEvents = [];
    set({ lifecycleReplayActive: false, isReplaying: false, replayProgress: 1 });
  },

  reset() {
    replayTimers.forEach(clearTimeout);
    replayTimers = [];
    savedLifecycleEvents = [];
    set({
      nodes: cloneInitialNodes(),
      events: [],
      isComplete: false,
      isReplaying: false,
      replayProgress: 0,
      replaySpeed: 3,
      ticker: null,
      selectedNodeId: null,
      selectedToolCall: null,
      expandedNodeId: null,
      reportOverlayOpen: false,
      lifecycleReplayActive: false,
      activeSpecialist: null,
    });
  },
}));

/** Alias for theater components */
export { usePipelineStore as useTheaterStore };
