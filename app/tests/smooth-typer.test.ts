/**
 * smoothTyper 单测：假定时器驱动帧节奏，验证平滑缓冲的核心契约——
 * 匀速吐字、突发积压有界追平、终态冲刷零丢失、dispose 后不残留定时器。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createSmoothTyper } from "../src/pages/student/cockpit/smoothTyper";

describe("smoothTyper 平滑打字机", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("缓冲模式按帧匀速渲染，而不是 delta 到达即整块出现", () => {
    const frames: string[] = [];
    const typer = createSmoothTyper({
      onRender: (text) => frames.push(text),
      // 低速便于断言：24ms × 10 字符/秒 → 每帧 1 字符（有最小值 1）
      charsPerSecond: 10,
      frameMs: 100,
    });

    typer.push("标注规范");
    // 未到第一帧时不渲染
    expect(frames).toHaveLength(0);

    vi.advanceTimersByTime(100);
    // 每帧吐积压的一半（向上取整）：4 字 → 2 → 1 → 1
    expect(frames.at(-1)).toBe("标注");
    vi.advanceTimersByTime(100);
    expect(frames.at(-1)).toBe("标注规");
    vi.advanceTimersByTime(100);
    expect(frames.at(-1)).toBe("标注规范");

    // 第二段 delta 追加进同一缓冲，不重新开始
    typer.push("要点");
    while (typer.pendingCount > 0) {
      vi.advanceTimersByTime(100);
    }
    expect(frames.at(-1)).toBe("标注规范要点");
  });

  it("突发大 delta 在少量帧内追平，延迟有界", () => {
    const frames: string[] = [];
    const typer = createSmoothTyper({ onRender: (text) => frames.push(text) });

    typer.push("文".repeat(400));
    // 每帧至少吐积压的一半：400 → 200 → 100 → …，十余帧（约 250ms）内清空
    for (let i = 0; i < 16 && typer.pendingCount > 0; i += 1) {
      vi.advanceTimersByTime(24);
    }
    expect(typer.pendingCount).toBe(0);
    expect(frames.at(-1)).toBe("文".repeat(400));
  });

  it("英文切点顺延到词边界，不渲染半个单词", () => {
    const frames: string[] = [];
    const typer = createSmoothTyper({
      onRender: (text) => frames.push(text),
      // 每帧 3 字符：无词边界保护时第一帧会切成 "hel"
      charsPerSecond: 125,
      frameMs: 24,
    });

    typer.push("hello wonderful world");
    vi.advanceTimersByTime(24);
    // 积压 21 字 → 本帧切点 11（"hello wonde" 的词中），顺延到词尾
    expect(frames.at(-1)).toBe("hello wonderful");
  });

  it("flush 立即渲染全部剩余内容并停表（终态零丢失）", () => {
    const frames: string[] = [];
    const typer = createSmoothTyper({ onRender: (text) => frames.push(text) });

    typer.push("第一段");
    typer.push("第二段");
    typer.flush();

    expect(typer.pendingCount).toBe(0);
    expect(frames.at(-1)).toBe("第一段第二段");
    const renderCount = frames.length;
    // 冲刷后不再有后续帧
    vi.advanceTimersByTime(500);
    expect(frames).toHaveLength(renderCount);
  });

  it("dispose 丢弃缓冲并清空已渲染计数，新 run 从空开始", () => {
    const frames: string[] = [];
    const typer = createSmoothTyper({ onRender: (text) => frames.push(text) });

    typer.push("旧 run 的内容");
    vi.advanceTimersByTime(24);
    typer.push("还没到完");
    typer.dispose();

    expect(typer.pendingCount).toBe(0);
    const renderCount = frames.length;
    vi.advanceTimersByTime(500);
    // dispose 后残留定时器不再触发渲染
    expect(frames).toHaveLength(renderCount);

    typer.push("新");
    vi.advanceTimersByTime(24);
    // rendered 已清零：不会把上一轮的残留拼到新一轮前面
    expect(frames.at(-1)).not.toContain("旧 run");
  });

  it("instant 模式 delta 到达即整块渲染，不经过帧缓冲", () => {
    const frames: string[] = [];
    const typer = createSmoothTyper({
      onRender: (text) => frames.push(text),
      instant: true,
    });

    typer.push("第一段");
    typer.push("第二段");
    expect(frames).toEqual(["第一段", "第一段第二段"]);
    expect(typer.pendingCount).toBe(0);
  });

  it("忽略空 delta", () => {
    const render = vi.fn();
    const typer = createSmoothTyper({ onRender: render });

    typer.push("");
    vi.advanceTimersByTime(500);
    expect(render).not.toHaveBeenCalled();
  });
});
