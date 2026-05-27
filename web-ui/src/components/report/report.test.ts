import { describe, it, expect } from "vitest";
import { getVerdictStyle, normalizeVerdict, VERDICT_ORDER, VERDICT_STYLES } from "./verdict-colors";
import type { Verdict } from "./verdict-colors";

describe("verdict-colors", () => {
  it("defines styles for all 7 verdicts", () => {
    expect(Object.keys(VERDICT_STYLES)).toHaveLength(7);
  });

  it("VERDICT_ORDER contains all verdict keys", () => {
    expect(VERDICT_ORDER).toHaveLength(7);
    for (const v of VERDICT_ORDER) {
      expect(VERDICT_STYLES[v]).toBeDefined();
    }
  });

  it("getVerdictStyle returns correct style for known verdict", () => {
    const style = getVerdictStyle("verified");
    expect(style.label).toBe("Verified");
    expect(style.barColor).toBe("#4ADE80");
    expect(style.highlightBg).toContain("0.05");
  });

  it("getVerdictStyle falls back to unverified for unknown verdict", () => {
    const style = getVerdictStyle("unknown-verdict");
    expect(style.label).toBe("Unverified");
    expect(style.barColor).toBe("#94A3B8");
  });

  it("backward compat: old verdict names map correctly", () => {
    expect(getVerdictStyle("dual-verified").label).toBe("Verified");
    expect(getVerdictStyle("cascade-verified").label).toBe("Verified");
    expect(getVerdictStyle("source-verified").label).toBe("Supported");
    expect(getVerdictStyle("tool-verified").label).toBe("Supported");
    expect(getVerdictStyle("derived-from-verified").label).toBe("Supported");
    expect(getVerdictStyle("computation-verified").label).toBe("Computed");
    expect(getVerdictStyle("web-verified").label).toBe("Web Sourced");
    expect(getVerdictStyle("llm-inferred").label).toBe("Unverified");
  });

  it("normalizeVerdict maps old names to new", () => {
    expect(normalizeVerdict("dual-verified")).toBe("verified");
    expect(normalizeVerdict("cascade-verified")).toBe("verified");
    expect(normalizeVerdict("source-verified")).toBe("supported");
    expect(normalizeVerdict("computation-verified")).toBe("computed");
    expect(normalizeVerdict("llm-inferred")).toBe("unverified");
    expect(normalizeVerdict("verified")).toBe("verified");
  });

  it("all highlight colors have 0.05 opacity (persistent layer), except computed (0.08)", () => {
    for (const v of VERDICT_ORDER) {
      if (v === "computed") {
        expect(VERDICT_STYLES[v].highlightBg).toMatch(/0\.08\)/);
      } else {
        expect(VERDICT_STYLES[v].highlightBg).toMatch(/0\.05\)/);
      }
    }
  });

  it("all hover colors have 0.12 opacity (bloom/hover layer)", () => {
    for (const v of VERDICT_ORDER) {
      expect(VERDICT_STYLES[v].highlightHover).toMatch(/0\.12\)/);
    }
  });

  it("VERDICT_ORDER is strongest to weakest", () => {
    expect(VERDICT_ORDER[0]).toBe("verified");
    expect(VERDICT_ORDER[VERDICT_ORDER.length - 1]).toBe("unverified");
  });

  it("all verdicts have description field", () => {
    for (const v of VERDICT_ORDER) {
      expect(VERDICT_STYLES[v].description).toBeTruthy();
    }
  });
});
