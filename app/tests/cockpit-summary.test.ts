import { describe, expect, it } from "vitest";
import { compactRunSummary } from "../src/pages/student/cockpit/summary";

describe("compactRunSummary", () => {
  it("removes plan marker rows and keeps a compact first/last projection", () => {
    const summary = compactRunSummary(
      "✓ 召回资料\n命中 4 条相关内容。\n✓ 生成任务\n已生成学习任务。\n✓ 完成\n请继续练习。",
    );

    expect(summary).toBe("命中 4 条相关内容。\n请继续练习。");
    expect(summary.split("\n")).toHaveLength(2);
  });

  it("bounds a long single-line answer without losing the sentence boundary", () => {
    const summary = compactRunSummary("这是一个很长的回答。".repeat(40), 3, 40);

    expect(summary.length).toBeLessThanOrEqual(43);
    expect(summary.endsWith("...")).toBe(true);
  });
});
