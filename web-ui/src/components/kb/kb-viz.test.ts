import { describe, it, expect } from "vitest";
import { diffLines } from "diff";
import { computeConcentricPositions } from "./knowledge-map";
import { buildDailyOption, buildCumulativeOption, buildStackedOption } from "./evolution-timeline";
import { computeDiffLines } from "@/components/shared/diff-viewer";
import {
  categorizeArticles,
  categorizeAgentActivity,
  categorizeKBMutations,
  computePlaybackDelay,
  formatElapsed,
} from "./digest-replay";
import type { KBGraphNode, PipelineEvent } from "@/lib/types";
import type { EvolutionDayData, EvolutionCumulativeData } from "@/lib/types";

// ─── Knowledge Map Layout ─────────────────────────────────────────────────────

describe("computeConcentricPositions", () => {
  it("places core_mind at center (400, 400)", () => {
    const nodes: KBGraphNode[] = [
      { id: "core_mind", type: "core", label: "Core Mind", chars: 5000 },
    ];
    const positions = computeConcentricPositions(nodes);
    expect(positions.get("core_mind")).toEqual({ x: 400, y: 400 });
  });

  it("places themes on inner ring (radius ~180)", () => {
    const nodes: KBGraphNode[] = [
      { id: "core_mind", type: "core", label: "Core Mind", chars: 5000 },
      { id: "t1", type: "theme", label: "AI", chars: 3000 },
      { id: "t2", type: "theme", label: "Energy", chars: 2000 },
    ];
    const positions = computeConcentricPositions(nodes);

    const t1 = positions.get("t1")!;
    const t2 = positions.get("t2")!;
    const center = positions.get("core_mind")!;

    // Distance from center should be ~180
    const dist1 = Math.sqrt((t1.x - center.x) ** 2 + (t1.y - center.y) ** 2);
    const dist2 = Math.sqrt((t2.x - center.x) ** 2 + (t2.y - center.y) ** 2);
    expect(dist1).toBeCloseTo(180, 0);
    expect(dist2).toBeCloseTo(180, 0);
  });

  it("places events on mid ring (radius ~280)", () => {
    const nodes: KBGraphNode[] = [
      { id: "core_mind", type: "core", label: "Core Mind", chars: 5000 },
      { id: "ev1", type: "event", label: "Fed Rate", chars: 1000 },
    ];
    const positions = computeConcentricPositions(nodes);
    const ev1 = positions.get("ev1")!;
    const center = positions.get("core_mind")!;
    const dist = Math.sqrt((ev1.x - center.x) ** 2 + (ev1.y - center.y) ** 2);
    expect(dist).toBeCloseTo(280, 0);
  });

  it("places stocks on outer ring (radius ~360)", () => {
    const nodes: KBGraphNode[] = [
      { id: "core_mind", type: "core", label: "Core Mind", chars: 5000 },
      { id: "s1", type: "stock", label: "AAPL", chars: 500 },
      { id: "s2", type: "stock", label: "MSFT", chars: 600 },
      { id: "s3", type: "stock", label: "GOOG", chars: 400 },
    ];
    const positions = computeConcentricPositions(nodes);
    const center = positions.get("core_mind")!;

    for (const id of ["s1", "s2", "s3"]) {
      const pos = positions.get(id)!;
      const dist = Math.sqrt((pos.x - center.x) ** 2 + (pos.y - center.y) ** 2);
      expect(dist).toBeCloseTo(360, 0);
    }
  });

  it("handles empty nodes array (only core_mind position)", () => {
    const nodes: KBGraphNode[] = [];
    const positions = computeConcentricPositions(nodes);
    expect(positions.get("core_mind")).toEqual({ x: 400, y: 400 });
    expect(positions.size).toBe(1);
  });

  it("distributes multiple themes evenly around inner ring", () => {
    const themes: KBGraphNode[] = Array.from({ length: 4 }, (_, i) => ({
      id: `t${i}`,
      type: "theme" as const,
      label: `Theme ${i}`,
      chars: 1000,
    }));
    const nodes: KBGraphNode[] = [
      { id: "core_mind", type: "core", label: "Core Mind", chars: 5000 },
      ...themes,
    ];
    const positions = computeConcentricPositions(nodes);

    // Angles between consecutive themes should be equal (~90 degrees)
    const center = positions.get("core_mind")!;
    const angles = themes.map((t) => {
      const pos = positions.get(t.id)!;
      return Math.atan2(pos.y - center.y, pos.x - center.x);
    });

    for (let i = 0; i < angles.length - 1; i++) {
      let diff = angles[i + 1] - angles[i];
      if (diff < 0) diff += 2 * Math.PI;
      expect(diff).toBeCloseTo(Math.PI / 2, 1);
    }
  });
});

// ─── Evolution Timeline Data Transformation ───────────────────────────────────

describe("buildDailyOption", () => {
  const dailyData: EvolutionDayData[] = [
    { date: "2025-05-10", articles_ingested: 5, kb_writes: 3, analyses: 1, digests: 1 },
    { date: "2025-05-11", articles_ingested: 8, kb_writes: 4, analyses: 2, digests: 1 },
    { date: "2025-05-12", articles_ingested: 3, kb_writes: 2, analyses: 0, digests: 0 },
  ];

  it("produces bar chart for articles in daily mode", () => {
    const option = buildDailyOption(dailyData, false) as {
      series: Array<{ name: string; type: string; data: number[] }>;
    };
    const articlesSeries = option.series.find((s) => s.name === "Articles");
    expect(articlesSeries).toBeDefined();
    expect(articlesSeries!.type).toBe("bar");
    expect(articlesSeries!.data).toEqual([5, 8, 3]);
  });

  it("produces line chart for KB Writes", () => {
    const option = buildDailyOption(dailyData, false) as {
      series: Array<{ name: string; type: string; data: number[] }>;
    };
    const kbSeries = option.series.find((s) => s.name === "KB Writes");
    expect(kbSeries).toBeDefined();
    expect(kbSeries!.type).toBe("line");
    expect(kbSeries!.data).toEqual([3, 4, 2]);
  });

  it("hides legend in compact mode", () => {
    const option = buildDailyOption(dailyData, true) as { legend: unknown };
    expect(option.legend).toBeUndefined();
  });

  it("shows legend in full mode", () => {
    const option = buildDailyOption(dailyData, false) as { legend: { data: string[] } };
    expect(option.legend).toBeDefined();
    expect(option.legend.data).toEqual(["Articles", "KB Writes", "Analyses"]);
  });

  it("includes correct x-axis dates", () => {
    const option = buildDailyOption(dailyData, false) as { xAxis: { data: string[] } };
    expect(option.xAxis.data).toEqual(["2025-05-10", "2025-05-11", "2025-05-12"]);
  });

  it("hides axis labels in compact mode", () => {
    const option = buildDailyOption(dailyData, true) as {
      xAxis: { axisLabel: { show: boolean } };
      yAxis: { axisLabel: { show: boolean } };
    };
    expect(option.xAxis.axisLabel.show).toBe(false);
    expect(option.yAxis.axisLabel.show).toBe(false);
  });
});

describe("buildCumulativeOption", () => {
  const cumulativeData: EvolutionCumulativeData[] = [
    { date: "2025-05-10", articles: 5, kb_writes: 3, analyses: 1 },
    { date: "2025-05-11", articles: 13, kb_writes: 7, analyses: 3 },
    { date: "2025-05-12", articles: 16, kb_writes: 9, analyses: 3 },
  ];

  it("uses line chart with area for articles in cumulative mode", () => {
    const option = buildCumulativeOption(cumulativeData, false) as {
      series: Array<{ name: string; type: string; areaStyle?: unknown; data: number[] }>;
    };
    const articlesSeries = option.series.find((s) => s.name === "Articles");
    expect(articlesSeries).toBeDefined();
    expect(articlesSeries!.type).toBe("line");
    expect(articlesSeries!.areaStyle).toBeDefined();
    expect(articlesSeries!.data).toEqual([5, 13, 16]);
  });

  it("uses cumulative data values (not daily)", () => {
    const option = buildCumulativeOption(cumulativeData, false) as {
      series: Array<{ name: string; data: number[] }>;
    };
    const kbSeries = option.series.find((s) => s.name === "KB Writes");
    expect(kbSeries!.data).toEqual([3, 7, 9]);
  });

  it("has transparent background", () => {
    const option = buildCumulativeOption(cumulativeData, false) as { backgroundColor: string };
    expect(option.backgroundColor).toBe("transparent");
  });
});

// ─── Stacked Area (Evolution Timeline) ────────────────────────────────────────

describe("buildStackedOption", () => {
  const dailyData: EvolutionDayData[] = [
    { date: "2025-05-10", articles_ingested: 5, kb_writes: 3, analyses: 1, digests: 1 },
    { date: "2025-05-11", articles_ingested: 8, kb_writes: 4, analyses: 2, digests: 1 },
    { date: "2025-05-12", articles_ingested: 3, kb_writes: 2, analyses: 0, digests: 0 },
  ];

  it("returns valid ECharts config with stack property on all series", () => {
    const option = buildStackedOption(dailyData, false) as {
      series: Array<{ name: string; type: string; stack: string; data: number[] }>;
    };
    expect(option.series).toHaveLength(3);
    for (const s of option.series) {
      expect(s.type).toBe("line");
      expect(s.stack).toBe("total");
    }
  });

  it("has correct areaStyle on each series", () => {
    const option = buildStackedOption(dailyData, false) as {
      series: Array<{ name: string; areaStyle: { color: string } }>;
    };
    const articles = option.series.find((s) => s.name === "Articles");
    const kbWrites = option.series.find((s) => s.name === "KB Writes");
    const analyses = option.series.find((s) => s.name === "Analyses");

    expect(articles!.areaStyle).toBeDefined();
    expect(articles!.areaStyle.color).toContain("16, 185, 129");
    expect(kbWrites!.areaStyle).toBeDefined();
    expect(kbWrites!.areaStyle.color).toContain("6, 182, 212");
    expect(analyses!.areaStyle).toBeDefined();
    expect(analyses!.areaStyle.color).toContain("139, 92, 246");
  });

  it("uses articles_ingested for Articles data", () => {
    const option = buildStackedOption(dailyData, false) as {
      series: Array<{ name: string; data: number[] }>;
    };
    const articles = option.series.find((s) => s.name === "Articles");
    expect(articles!.data).toEqual([5, 8, 3]);
  });

  it("uses kb_writes for KB Writes data", () => {
    const option = buildStackedOption(dailyData, false) as {
      series: Array<{ name: string; data: number[] }>;
    };
    const kbWrites = option.series.find((s) => s.name === "KB Writes");
    expect(kbWrites!.data).toEqual([3, 4, 2]);
  });

  it("uses analyses for Analyses data", () => {
    const option = buildStackedOption(dailyData, false) as {
      series: Array<{ name: string; data: number[] }>;
    };
    const analyses = option.series.find((s) => s.name === "Analyses");
    expect(analyses!.data).toEqual([1, 2, 0]);
  });

  it("sets boundaryGap to false on xAxis", () => {
    const option = buildStackedOption(dailyData, false) as {
      xAxis: { boundaryGap: boolean };
    };
    expect(option.xAxis.boundaryGap).toBe(false);
  });

  it("uses symbol none for all series", () => {
    const option = buildStackedOption(dailyData, false) as {
      series: Array<{ symbol: string }>;
    };
    for (const s of option.series) {
      expect(s.symbol).toBe("none");
    }
  });

  it("sets emphasis focus to series", () => {
    const option = buildStackedOption(dailyData, false) as {
      series: Array<{ emphasis: { focus: string } }>;
    };
    for (const s of option.series) {
      expect(s.emphasis.focus).toBe("series");
    }
  });

  it("hides legend in compact mode", () => {
    const option = buildStackedOption(dailyData, true) as { legend: unknown };
    expect(option.legend).toBeUndefined();
  });

  it("with empty data produces valid option structure", () => {
    const option = buildStackedOption([], false) as {
      series: Array<{ data: unknown[] }>;
      xAxis: { data: string[] };
    };
    expect(option.xAxis.data).toEqual([]);
    expect(option.series[0].data).toEqual([]);
  });
});

// ─── Core Mind Diff Computation ───────────────────────────────────────────────

describe("computeDiffLines", () => {
  it("computes diff with added lines", () => {
    const oldText = "line1\nline2\n";
    const newText = "line1\nline2\nline3\n";
    const changes = diffLines(oldText, newText);
    const result = computeDiffLines(changes);

    const addedLines = result.filter((l) => l.type === "added");
    expect(addedLines.length).toBe(1);
    expect(addedLines[0].content).toBe("line3");
    expect(addedLines[0].rightLineNo).toBe(3);
    expect(addedLines[0].leftLineNo).toBeNull();
  });

  it("computes diff with removed lines", () => {
    const oldText = "line1\nline2\nline3\n";
    const newText = "line1\nline3\n";
    const changes = diffLines(oldText, newText);
    const result = computeDiffLines(changes);

    const removedLines = result.filter((l) => l.type === "removed");
    expect(removedLines.length).toBe(1);
    expect(removedLines[0].content).toBe("line2");
    expect(removedLines[0].leftLineNo).toBeGreaterThan(0);
    expect(removedLines[0].rightLineNo).toBeNull();
  });

  it("marks unchanged lines correctly", () => {
    const oldText = "hello\nworld\n";
    const newText = "hello\nworld\n";
    const changes = diffLines(oldText, newText);
    const result = computeDiffLines(changes);

    expect(result.length).toBe(2);
    expect(result.every((l) => l.type === "unchanged")).toBe(true);
    expect(result[0].leftLineNo).toBe(1);
    expect(result[0].rightLineNo).toBe(1);
    expect(result[1].leftLineNo).toBe(2);
    expect(result[1].rightLineNo).toBe(2);
  });

  it("handles completely new content", () => {
    const oldText = "";
    const newText = "new line 1\nnew line 2\n";
    const changes = diffLines(oldText, newText);
    const result = computeDiffLines(changes);

    expect(result.every((l) => l.type === "added")).toBe(true);
    expect(result.length).toBe(2);
  });

  it("handles completely removed content", () => {
    const oldText = "old line 1\nold line 2\n";
    const newText = "";
    const changes = diffLines(oldText, newText);
    const result = computeDiffLines(changes);

    expect(result.every((l) => l.type === "removed")).toBe(true);
    expect(result.length).toBe(2);
  });

  it("handles mixed changes with correct line numbering", () => {
    const oldText = "alpha\nbeta\ngamma\n";
    const newText = "alpha\ndelta\ngamma\nepsilon\n";
    const changes = diffLines(oldText, newText);
    const result = computeDiffLines(changes);

    // alpha should be unchanged (L1, R1)
    const alpha = result.find((l) => l.content === "alpha");
    expect(alpha).toBeDefined();
    expect(alpha!.type).toBe("unchanged");
    expect(alpha!.leftLineNo).toBe(1);
    expect(alpha!.rightLineNo).toBe(1);

    // beta should be removed
    const beta = result.find((l) => l.content === "beta");
    expect(beta).toBeDefined();
    expect(beta!.type).toBe("removed");

    // delta should be added
    const delta = result.find((l) => l.content === "delta");
    expect(delta).toBeDefined();
    expect(delta!.type).toBe("added");

    // epsilon should be added
    const epsilon = result.find((l) => l.content === "epsilon");
    expect(epsilon).toBeDefined();
    expect(epsilon!.type).toBe("added");
  });

  it("returns empty array when both texts are empty", () => {
    const changes = diffLines("", "");
    const result = computeDiffLines(changes);
    expect(result.length).toBe(0);
  });
});

// ─── Empty State Handling ─────────────────────────────────────────────────────

describe("empty state data handling", () => {
  it("computeConcentricPositions with no nodes still has core_mind", () => {
    const positions = computeConcentricPositions([]);
    expect(positions.has("core_mind")).toBe(true);
    expect(positions.size).toBe(1);
  });

  it("buildDailyOption with empty data produces valid option structure", () => {
    const option = buildDailyOption([], false) as {
      series: Array<{ data: unknown[] }>;
      xAxis: { data: string[] };
    };
    expect(option.xAxis.data).toEqual([]);
    expect(option.series[0].data).toEqual([]);
  });

  it("buildCumulativeOption with empty data produces valid option structure", () => {
    const option = buildCumulativeOption([], false) as {
      series: Array<{ data: unknown[] }>;
      xAxis: { data: string[] };
    };
    expect(option.xAxis.data).toEqual([]);
    expect(option.series[0].data).toEqual([]);
  });

  it("computeDiffLines with identical texts has all unchanged", () => {
    const text = "same\ncontent\nhere\n";
    const changes = diffLines(text, text);
    const result = computeDiffLines(changes);
    expect(result.every((l) => l.type === "unchanged")).toBe(true);
    expect(result.length).toBe(3);
  });
});

// ─── Digest Replay Theater ───────────────────────────────────────────────────

describe("categorizeArticles", () => {
  const events: PipelineEvent[] = [
    { event: "digest.session_start", ts: "2025-05-10T10:00:00Z", data: { total_items: 10 } },
    { event: "digest.batch_start", ts: "2025-05-10T10:00:01Z", data: { batch_num: 1, item_count: 3, item_slugs: ["article-a", "article-b", "article-c"] } },
    { event: "agent.tool_call.start", ts: "2025-05-10T10:00:02Z", data: { tool_name: "kb_read" } },
    { event: "digest.batch_start", ts: "2025-05-10T10:01:00Z", data: { batch_num: 2, item_count: 2, item_slugs: ["article-d", "article-e"] } },
    { event: "kb.write", ts: "2025-05-10T10:01:30Z", data: { section: "themes", slug: "ai-hype", size: 500 } },
  ];

  it("extracts articles from batch_start events", () => {
    const articles = categorizeArticles(events);
    expect(articles.length).toBe(5);
    expect(articles[0]).toEqual({ slug: "article-a", batchNum: 1 });
    expect(articles[4]).toEqual({ slug: "article-e", batchNum: 2 });
  });

  it("returns empty array for no batch_start events", () => {
    const noArticles = events.filter((e) => e.event !== "digest.batch_start");
    expect(categorizeArticles(noArticles)).toEqual([]);
  });

  it("handles batch_start with no item_slugs", () => {
    const evt: PipelineEvent[] = [
      { event: "digest.batch_start", ts: "2025-05-10T10:00:00Z", data: { batch_num: 1, item_count: 0 } },
    ];
    expect(categorizeArticles(evt)).toEqual([]);
  });
});

describe("categorizeAgentActivity", () => {
  const events: PipelineEvent[] = [
    { event: "digest.session_start", ts: "2025-05-10T10:00:00Z", data: {} },
    { event: "digest.batch_start", ts: "2025-05-10T10:00:01Z", data: {} },
    { event: "agent.tool_call.start", ts: "2025-05-10T10:00:02Z", data: { tool_name: "kb_read" } },
    { event: "agent.tool_call.end", ts: "2025-05-10T10:00:03Z", data: { tool_name: "kb_read", success: true } },
    { event: "kb.write", ts: "2025-05-10T10:00:04Z", data: { section: "themes" } },
    { event: "digest.batch_complete", ts: "2025-05-10T10:00:05Z", data: {} },
    { event: "digest.session_end", ts: "2025-05-10T10:00:06Z", data: {} },
  ];

  it("includes tool calls, batch events, and session events", () => {
    const activity = categorizeAgentActivity(events);
    expect(activity.length).toBe(6); // session_start, batch_start, tool_call.start, tool_call.end, batch_complete, session_end
  });

  it("excludes kb.* events", () => {
    const activity = categorizeAgentActivity(events);
    const kbEvents = activity.filter((e) => e.event.startsWith("kb."));
    expect(kbEvents.length).toBe(0);
  });
});

describe("categorizeKBMutations", () => {
  const events: PipelineEvent[] = [
    { event: "digest.session_start", ts: "2025-05-10T10:00:00Z", data: {} },
    { event: "kb.write", ts: "2025-05-10T10:00:01Z", data: { section: "themes", slug: "ai", size: 200 } },
    { event: "kb.edit", ts: "2025-05-10T10:00:02Z", data: { section: "themes", slug: "ai", old_len: 200, new_len: 350 } },
    { event: "kb.core_mind_updated", ts: "2025-05-10T10:00:03Z", data: { size: 4000 } },
    { event: "agent.tool_call.end", ts: "2025-05-10T10:00:04Z", data: {} },
  ];

  it("includes only kb.* events", () => {
    const mutations = categorizeKBMutations(events);
    expect(mutations.length).toBe(3);
    expect(mutations[0].event).toBe("kb.write");
    expect(mutations[1].event).toBe("kb.edit");
    expect(mutations[2].event).toBe("kb.core_mind_updated");
  });

  it("returns empty for non-KB events", () => {
    const noKB = events.filter((e) => !e.event.startsWith("kb."));
    expect(categorizeKBMutations(noKB)).toEqual([]);
  });
});

describe("computePlaybackDelay", () => {
  it("returns default 500ms when next event is undefined", () => {
    const current: PipelineEvent = { event: "test", ts: "2025-05-10T10:00:00Z" };
    expect(computePlaybackDelay(current, undefined, 1)).toBe(500);
  });

  it("computes gap-based delay at 1x speed", () => {
    const current: PipelineEvent = { event: "a", ts: "2025-05-10T10:00:00.000Z" };
    const next: PipelineEvent = { event: "b", ts: "2025-05-10T10:00:01.000Z" }; // 1000ms gap
    const delay = computePlaybackDelay(current, next, 1);
    expect(delay).toBe(1000);
  });

  it("scales delay by speed factor", () => {
    const current: PipelineEvent = { event: "a", ts: "2025-05-10T10:00:00.000Z" };
    const next: PipelineEvent = { event: "b", ts: "2025-05-10T10:00:02.000Z" }; // 2000ms gap
    expect(computePlaybackDelay(current, next, 2)).toBe(1000);
    expect(computePlaybackDelay(current, next, 4)).toBe(500);
    expect(computePlaybackDelay(current, next, 8)).toBe(250);
  });

  it("clamps minimum delay to 50ms", () => {
    const current: PipelineEvent = { event: "a", ts: "2025-05-10T10:00:00.000Z" };
    const next: PipelineEvent = { event: "b", ts: "2025-05-10T10:00:00.100Z" }; // 100ms gap
    // At 8x speed: 100/8 = 12.5 -> clamped to 50
    expect(computePlaybackDelay(current, next, 8)).toBe(50);
  });

  it("clamps maximum delay to 2000ms", () => {
    const current: PipelineEvent = { event: "a", ts: "2025-05-10T10:00:00.000Z" };
    const next: PipelineEvent = { event: "b", ts: "2025-05-10T10:05:00.000Z" }; // 300000ms gap
    // At 1x speed: 300000/1 = 300000 -> clamped to 2000
    expect(computePlaybackDelay(current, next, 1)).toBe(2000);
  });

  it("handles zero or negative gap gracefully", () => {
    const current: PipelineEvent = { event: "a", ts: "2025-05-10T10:00:01.000Z" };
    const next: PipelineEvent = { event: "b", ts: "2025-05-10T10:00:00.000Z" }; // negative gap
    const delay = computePlaybackDelay(current, next, 1);
    // negative gap fallback
    expect(delay).toBeGreaterThanOrEqual(50);
    expect(delay).toBeLessThanOrEqual(2000);
  });
});

describe("formatElapsed", () => {
  it("formats zero as 0:00", () => {
    expect(formatElapsed(0)).toBe("0:00");
  });

  it("formats seconds correctly", () => {
    expect(formatElapsed(45000)).toBe("0:45");
  });

  it("formats minutes and seconds", () => {
    expect(formatElapsed(125000)).toBe("2:05");
  });

  it("formats large values", () => {
    expect(formatElapsed(600000)).toBe("10:00");
  });

  it("handles NaN/negative gracefully", () => {
    expect(formatElapsed(NaN)).toBe("0:00");
    expect(formatElapsed(-1000)).toBe("0:00");
  });
});
