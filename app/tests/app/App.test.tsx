import "@testing-library/jest-dom/vitest";

import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/app/App";
import type {
  LearningProfileSnapshot,
  ProfileStore,
} from "../../src/state/profileStore";

const createSnapshot = (
  lastMode: string | null = null,
): LearningProfileSnapshot => ({
  version: 1,
  generalMastery: {},
  scenarioMastery: {},
  attempts: [],
  lastMode,
  lastScenario: null,
  lastUnit: null,
  lastNode: null,
});

const createTestStore = (
  overrides: Partial<ProfileStore> = {},
): ProfileStore => ({
  snapshot: () => createSnapshot(),
  getLoadError: () => null,
  recordExercise: vi.fn(),
  recordDiagnostic: vi.fn(),
  setContext: vi.fn(),
  reset: vi.fn(),
  ...overrides,
});

afterEach(() => {
  cleanup();
});

describe("application shell", () => {
  it("exposes the product landmarks and opens every repository-backed course domain", () => {
    render(<App profileStore={createTestStore()} />);

    expect(screen.getByRole("banner")).toHaveTextContent("标航智导");
    expect(screen.getByText("开发预览")).toBeVisible();
    expect(
      screen.getByRole("navigation", { name: "工作模式" }),
    ).toBeVisible();
    expect(
      screen.getByRole("complementary", { name: "课程域导航" }),
    ).toBeVisible();
    expect(
      screen.getByRole("complementary", { name: "航线状态" }),
    ).toHaveTextContent("通用场景");

    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("id", "main-content");
    expect(screen.getByRole("link", { name: "跳到主要内容" })).toHaveAttribute(
      "href",
      "#main-content",
    );

    const domainCounts = [
      ["文本", 5],
      ["图像", 5],
      ["语音", 6],
      ["视频", 3],
    ] as const;

    for (const [name, count] of domainCounts) {
      expect(
        screen.getByRole("button", {
          name: `${name}课程，${count} 个可学习单元`,
        }),
      ).toBeEnabled();
    }

    const audioDomain = screen.getByRole("button", {
      name: "语音课程，6 个可学习单元",
    });
    fireEvent.click(audioDomain);

    expect(audioDomain).toHaveAttribute("aria-pressed", "true");
    expect(main).toHaveTextContent("语音");
  });

  it("derives card totals from the supplied consumable units", () => {
    const repository = {
      listConsumableUnits: () => [
        { data_type: "text" },
        { data_type: "video" },
        { data_type: "video" },
      ],
    };

    render(
      <App repository={repository} profileStore={createTestStore()} />,
    );

    expect(
      screen.getByRole("button", {
        name: "文本课程，1 个可学习单元",
      }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", {
        name: "图像课程，0 个可学习单元",
      }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", {
        name: "语音课程，0 个可学习单元",
      }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", {
        name: "视频课程，2 个可学习单元",
      }),
    ).toBeEnabled();
  });

  it("uses automatic-activation roving tabs while preserving the selected domain", () => {
    render(<App profileStore={createTestStore()} />);

    fireEvent.click(
      screen.getByRole("button", {
        name: "语音课程，6 个可学习单元",
      }),
    );

    const modeTabs = screen.getAllByRole("tab");
    const courseTab = screen.getByRole("tab", { name: "课程" });
    const graphTab = screen.getByRole("tab", { name: "图谱" });
    const diagnosticsTab = screen.getByRole("tab", { name: "标注诊断" });

    expect(modeTabs.filter((tab) => tab.tabIndex === 0)).toHaveLength(1);
    expect(courseTab).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(courseTab, { key: "ArrowRight" });

    expect(graphTab).toHaveFocus();
    expect(graphTab).toHaveAttribute("aria-selected", "true");
    expect(courseTab).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("main")).toHaveTextContent("图谱");
    expect(screen.getByRole("main")).toHaveTextContent("语音");

    fireEvent.keyDown(graphTab, { key: "End" });
    expect(diagnosticsTab).toHaveFocus();
    expect(diagnosticsTab).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(diagnosticsTab, { key: "Home" });
    expect(courseTab).toHaveFocus();
    expect(courseTab).toHaveAttribute("aria-selected", "true");
    expect(modeTabs.filter((tab) => tab.tabIndex === 0)).toHaveLength(1);
  });

  it("requires confirmation, keeps state on cancel, and resets context on confirm", () => {
    const reset = vi.fn();
    const store = createTestStore({ reset });
    render(<App profileStore={store} />);

    fireEvent.click(
      screen.getByRole("button", {
        name: "语音课程，6 个可学习单元",
      }),
    );
    fireEvent.click(screen.getByRole("tab", { name: "图谱" }));
    fireEvent.click(screen.getByRole("button", { name: "重置学习档案" }));

    const dialog = screen.getByRole("alertdialog", {
      name: "确认重置学习档案",
    });
    expect(dialog).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));

    expect(reset).not.toHaveBeenCalled();
    expect(screen.getByRole("main")).toHaveTextContent("图谱");
    expect(screen.getByRole("main")).toHaveTextContent("语音");

    fireEvent.click(screen.getByRole("button", { name: "重置学习档案" }));
    fireEvent.click(
      within(
        screen.getByRole("alertdialog", { name: "确认重置学习档案" }),
      ).getByRole("button", { name: "确认重置" }),
    );

    expect(reset).toHaveBeenCalledOnce();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveTextContent("课程");
    expect(screen.getByRole("main")).toHaveTextContent("文本");
  });

  it("retains UI state and exposes a recoverable alert when profile reset fails", () => {
    const store = createTestStore({
      reset: vi.fn(() => {
        throw new Error("storage unavailable");
      }),
    });
    render(<App profileStore={store} />);

    fireEvent.click(
      screen.getByRole("button", {
        name: "语音课程，6 个可学习单元",
      }),
    );
    fireEvent.click(screen.getByRole("tab", { name: "图谱" }));
    fireEvent.click(screen.getByRole("button", { name: "重置学习档案" }));
    fireEvent.click(
      within(
        screen.getByRole("alertdialog", { name: "确认重置学习档案" }),
      ).getByRole("button", { name: "确认重置" }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent("学习档案重置失败");
    expect(screen.getByRole("main")).toHaveTextContent("图谱");
    expect(screen.getByRole("main")).toHaveTextContent("语音");
    expect(
      screen.getByRole("button", { name: "重置学习档案" }),
    ).toBeEnabled();
  });
});
