import { describe, it, expect, beforeEach } from "vitest";
import { usePipelineStore } from "./pipeline-store";
import type { PipelineEvent } from "@/lib/types";

function makeEvent(event: string, data: Record<string, unknown> = {}): PipelineEvent {
  return { event, ts: "2026-05-16T17:05:56Z", data };
}

describe("pipeline-store", () => {
  beforeEach(() => {
    usePipelineStore.getState().reset();
  });

  it("initializes with all nodes idle", () => {
    const { nodes } = usePipelineStore.getState();
    expect(nodes.input.state).toBe("idle");
    expect(nodes.fundamental.state).toBe("idle");
    expect(nodes.core.state).toBe("idle");
    expect(nodes.audit.state).toBe("idle");
  });

  it("analysis.start marks input as complete and sets ticker", () => {
    const store = usePipelineStore.getState();
    store.processEvent(makeEvent("analysis.start", { ticker: "AAPL", execution_id: "test-123" }));

    const { nodes, ticker } = usePipelineStore.getState();
    expect(nodes.input.state).toBe("complete");
    expect(ticker).toBe("AAPL");
  });

  it("specialist.*.start marks agent as active", () => {
    const store = usePipelineStore.getState();
    store.processEvent(makeEvent("specialist.fundamental.start", { execution_id: "test-123", ticker: "AAPL" }));

    const { nodes } = usePipelineStore.getState();
    expect(nodes.fundamental.state).toBe("active");
    expect(nodes.technical.state).toBe("idle");
  });

  it("specialist.*.complete marks agent as complete with metadata", () => {
    const store = usePipelineStore.getState();
    store.processEvent(makeEvent("specialist.macro.start", { execution_id: "t" }));
    store.processEvent(makeEvent("specialist.macro.complete", {
      execution_id: "t",
      success: true,
      elapsed_s: 36.2,
      token_total: 21201,
      tool_count: 5,
    }));

    const { nodes } = usePipelineStore.getState();
    expect(nodes.macro.state).toBe("complete");
    expect(nodes.macro.elapsed_s).toBe(36.2);
    expect(nodes.macro.token_total).toBe(21201);
    expect(nodes.macro.tool_count).toBe(5);
  });

  it("specialist.*.complete with success=false marks as error", () => {
    const store = usePipelineStore.getState();
    store.processEvent(makeEvent("specialist.value.complete", {
      execution_id: "t",
      success: false,
    }));

    const { nodes } = usePipelineStore.getState();
    expect(nodes.value.state).toBe("error");
  });

  it("analysis.core_start / core_complete lifecycle", () => {
    const store = usePipelineStore.getState();
    store.processEvent(makeEvent("analysis.core_start", { execution_id: "t", ticker: "PFE" }));
    expect(usePipelineStore.getState().nodes.core.state).toBe("active");

    store.processEvent(makeEvent("analysis.core_complete", {
      execution_id: "t",
      ticker: "PFE",
      elapsed_s: 61.1,
      token_total: 39949,
      tool_count: 2,
    }));

    const { nodes } = usePipelineStore.getState();
    expect(nodes.core.state).toBe("complete");
    expect(nodes.core.elapsed_s).toBe(61.1);
    expect(nodes.report.state).toBe("complete");
  });

  it("analysis.end marks isComplete", () => {
    const store = usePipelineStore.getState();
    store.processEvent(makeEvent("analysis.end", { execution_id: "t", success: true, elapsed_s: 159.6 }));

    expect(usePipelineStore.getState().isComplete).toBe(true);
  });

  it("audit.start / audit.complete lifecycle", () => {
    const store = usePipelineStore.getState();
    store.processEvent(makeEvent("audit.start", { execution_id: "t", mode: "analysis" }));
    expect(usePipelineStore.getState().nodes.audit.state).toBe("active");

    store.processEvent(makeEvent("audit.complete", {
      execution_id: "t",
      duration_s: 147.6,
      claims: 35,
    }));

    const { nodes } = usePipelineStore.getState();
    expect(nodes.audit.state).toBe("complete");
    expect(nodes.audit.elapsed_s).toBe(147.6);
  });

  it("agent.tool_call.start appends to node toolCalls", () => {
    const store = usePipelineStore.getState();
    store.processEvent(makeEvent("agent.tool_call.start", {
      execution_id: "t",
      agent: "macro",
      tool_name: "get_yield_curve",
      input: "{'format': 'json'}",
    }));

    const { nodes } = usePipelineStore.getState();
    expect(nodes.macro.toolCalls).toHaveLength(1);
    expect(nodes.macro.toolCalls[0].tool_name).toBe("get_yield_curve");
    expect(nodes.macro.toolCalls[0].duration_s).toBeUndefined();
  });

  it("agent.tool_call.end updates matching tool call with duration", () => {
    const store = usePipelineStore.getState();
    store.processEvent(makeEvent("agent.tool_call.start", {
      execution_id: "t",
      agent: "macro",
      tool_name: "get_yield_curve",
    }));
    store.processEvent(makeEvent("agent.tool_call.end", {
      execution_id: "t",
      agent: "macro",
      tool_name: "get_yield_curve",
      duration_s: 2.487,
      success: true,
      output_length: 2334,
    }));

    const { nodes } = usePipelineStore.getState();
    expect(nodes.macro.toolCalls[0].duration_s).toBe(2.487);
    expect(nodes.macro.toolCalls[0].success).toBe(true);
  });

  it("selectNode sets and clears selectedNodeId", () => {
    const store = usePipelineStore.getState();
    store.selectNode("fundamental");
    expect(usePipelineStore.getState().selectedNodeId).toBe("fundamental");

    store.selectNode(null);
    expect(usePipelineStore.getState().selectedNodeId).toBeNull();
  });

  it("reset clears all state", () => {
    const store = usePipelineStore.getState();
    store.processEvent(makeEvent("analysis.start", { ticker: "AAPL", execution_id: "t" }));
    store.processEvent(makeEvent("specialist.fundamental.start", { execution_id: "t" }));
    store.selectNode("fundamental");

    store.reset();

    const state = usePipelineStore.getState();
    expect(state.nodes.input.state).toBe("idle");
    expect(state.nodes.fundamental.state).toBe("idle");
    expect(state.events).toHaveLength(0);
    expect(state.ticker).toBeNull();
    expect(state.selectedNodeId).toBeNull();
    expect(state.isComplete).toBe(false);
  });

  it("accumulates events in order", () => {
    const store = usePipelineStore.getState();
    store.processEvent(makeEvent("analysis.start", { ticker: "PFE", execution_id: "t" }));
    store.processEvent(makeEvent("specialist.fundamental.start", { execution_id: "t" }));
    store.processEvent(makeEvent("specialist.technical.start", { execution_id: "t" }));

    expect(usePipelineStore.getState().events).toHaveLength(3);
    expect(usePipelineStore.getState().events[0].event).toBe("analysis.start");
    expect(usePipelineStore.getState().events[2].event).toBe("specialist.technical.start");
  });

  it("full PFE-like lifecycle processes without error", () => {
    const store = usePipelineStore.getState();
    const events = [
      makeEvent("analysis.start", { execution_id: "t", ticker: "PFE" }),
      makeEvent("specialist.fundamental.start", { execution_id: "t", ticker: "PFE" }),
      makeEvent("specialist.macro.start", { execution_id: "t", ticker: "PFE" }),
      makeEvent("specialist.technical.start", { execution_id: "t", ticker: "PFE" }),
      makeEvent("specialist.value.start", { execution_id: "t", ticker: "PFE" }),
      makeEvent("specialist.macro.complete", { execution_id: "t", success: true, elapsed_s: 36, token_total: 21000, tool_count: 5 }),
      makeEvent("specialist.technical.complete", { execution_id: "t", success: true, elapsed_s: 50, token_total: 33000, tool_count: 11 }),
      makeEvent("specialist.fundamental.complete", { execution_id: "t", success: true, elapsed_s: 68, token_total: 67000, tool_count: 11 }),
      makeEvent("specialist.value.complete", { execution_id: "t", success: true, elapsed_s: 98, token_total: 80000, tool_count: 13 }),
      makeEvent("analysis.core_start", { execution_id: "t", ticker: "PFE" }),
      makeEvent("analysis.core_complete", { execution_id: "t", ticker: "PFE", elapsed_s: 61, token_total: 40000, tool_count: 2 }),
      makeEvent("analysis.end", { execution_id: "t", success: true, elapsed_s: 160 }),
    ];

    for (const evt of events) {
      store.processEvent(evt);
    }

    const { nodes, isComplete, ticker } = usePipelineStore.getState();
    expect(ticker).toBe("PFE");
    expect(isComplete).toBe(true);
    expect(nodes.input.state).toBe("complete");
    expect(nodes.fundamental.state).toBe("complete");
    expect(nodes.technical.state).toBe("complete");
    expect(nodes.value.state).toBe("complete");
    expect(nodes.macro.state).toBe("complete");
    expect(nodes.core.state).toBe("complete");
    expect(nodes.report.state).toBe("complete");
    // audit not triggered in this flow
    expect(nodes.audit.state).toBe("idle");
  });
});
