import "@testing-library/jest-dom/vitest";

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { StrictMode } from "react";

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

const readAppCss = (): string =>
  readFileSync(resolve(process.cwd(), "src/app/app.css"), "utf8");

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

  it("focuses a work-mode tab when it is selected by pointer", () => {
    render(<App profileStore={createTestStore()} />);

    const graphTab = screen.getByRole("tab", { name: "图谱" });
    fireEvent.click(graphTab);

    expect(graphTab).toHaveFocus();
    expect(graphTab).toHaveAttribute("aria-selected", "true");
  });

  it("wraps forward Tab from the last reset action to the first", () => {
    render(<App profileStore={createTestStore()} />);

    fireEvent.click(screen.getByRole("button", { name: "重置学习档案" }));
    const dialog = screen.getByRole("alertdialog", {
      name: "确认重置学习档案",
    });
    const cancelButton = within(dialog).getByRole("button", { name: "取消" });
    const confirmButton = within(dialog).getByRole("button", {
      name: "确认重置",
    });

    expect(cancelButton).toHaveFocus();
    confirmButton.focus();
    fireEvent.keyDown(confirmButton, { key: "Tab" });

    expect(cancelButton).toHaveFocus();
  });

  it("wraps reverse Shift+Tab from the first reset action to the last", () => {
    render(<App profileStore={createTestStore()} />);

    fireEvent.click(screen.getByRole("button", { name: "重置学习档案" }));
    const dialog = screen.getByRole("alertdialog", {
      name: "确认重置学习档案",
    });
    const cancelButton = within(dialog).getByRole("button", { name: "取消" });
    const confirmButton = within(dialog).getByRole("button", {
      name: "确认重置",
    });

    expect(cancelButton).toHaveFocus();
    fireEvent.keyDown(cancelButton, { key: "Tab", shiftKey: true });

    expect(confirmButton).toHaveFocus();
  });

  it("makes background content inert and restores it with opener focus on Escape", () => {
    render(<App profileStore={createTestStore()} />);

    const resetButton = screen.getByRole("button", {
      name: "重置学习档案",
    });
    fireEvent.click(resetButton);

    const applicationContent = resetButton.closest(".app-content");
    expect(applicationContent).not.toBeNull();
    expect(applicationContent).toHaveAttribute("inert");
    expect(applicationContent).toHaveAttribute("aria-hidden", "true");
    expect(
      screen.queryByRole("button", { name: "重置学习档案" }),
    ).not.toBeInTheDocument();

    const dialog = screen.getByRole("alertdialog", {
      name: "确认重置学习档案",
    });
    fireEvent.keyDown(dialog, { key: "Escape" });

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(applicationContent).not.toHaveAttribute("inert");
    expect(applicationContent).not.toHaveAttribute("aria-hidden");
    expect(resetButton).toHaveFocus();
  });

  it("keeps reset confirmation reachable in constrained-height viewports", () => {
    const appCss = readAppCss();
    const backdropRule = appCss.match(/\.dialog-backdrop\s*{([^}]*)}/)?.[1];
    const dialogRule = appCss.match(/\.reset-dialog\s*{([^}]*)}/)?.[1];

    expect(backdropRule).toContain("overflow-y: auto;");
    expect(backdropRule).toContain("align-items: flex-start;");
    expect(dialogRule).toContain("max-height: calc(100dvh - 2rem);");
    expect(dialogRule).toContain("overflow-y: auto;");
  });

  it("locks background scroll while the reset modal is mounted and restores it safely", () => {
    const previousDocumentOverflow = document.documentElement.style.overflow;
    const previousBodyOverflow = document.body.style.overflow;
    document.documentElement.style.overflow = "auto";
    document.body.style.overflow = "scroll";

    try {
      const { unmount } = render(
        <StrictMode>
          <App profileStore={createTestStore()} />
        </StrictMode>,
      );

      fireEvent.click(screen.getByRole("button", { name: "重置学习档案" }));
      expect(document.documentElement.style.overflow).toBe("hidden");
      expect(document.body.style.overflow).toBe("hidden");

      fireEvent.click(
        within(
          screen.getByRole("alertdialog", { name: "确认重置学习档案" }),
        ).getByRole("button", { name: "取消" }),
      );
      expect(document.documentElement.style.overflow).toBe("auto");
      expect(document.body.style.overflow).toBe("scroll");

      fireEvent.click(screen.getByRole("button", { name: "重置学习档案" }));
      expect(document.documentElement.style.overflow).toBe("hidden");
      expect(document.body.style.overflow).toBe("hidden");
      unmount();

      expect(document.documentElement.style.overflow).toBe("auto");
      expect(document.body.style.overflow).toBe("scroll");
    } finally {
      document.documentElement.style.overflow = previousDocumentOverflow;
      document.body.style.overflow = previousBodyOverflow;
    }
  });

  it("contains modal overscroll and keeps reset guidance comfortably readable", () => {
    const appCss = readAppCss();
    const backdropRule = appCss.match(/\.dialog-backdrop\s*{([^}]*)}/)?.[1];
    const resetNoteRule = appCss.match(/\.reset-note\s*{([^}]*)}/)?.[1];

    expect(backdropRule).toContain("overscroll-behavior: contain;");
    expect(resetNoteRule).toContain("color: rgb(247 248 250 / 68%);");
  });

  it("reflows before three-column tracks can clip intermediate viewports", () => {
    const appCss = readAppCss();
    const minimumTrackWidthRem = 18 + 30 + 18;
    const reflowBreakpointRem = 68;
    const intermediateViewportWidths = [961, 1024, 1055];
    const reflowRules = appCss.match(
      /@media \(max-width: 68rem\) {([\s\S]*?)(?=\n@media|$)/,
    )?.[1];

    expect(minimumTrackWidthRem).toBe(66);
    expect(reflowBreakpointRem).toBeGreaterThan(minimumTrackWidthRem);
    for (const viewportWidth of intermediateViewportWidths) {
      expect(viewportWidth).toBeLessThanOrEqual(reflowBreakpointRem * 16);
    }
    expect(reflowRules).toBeDefined();
    expect(reflowRules ?? "").toMatch(
      /\.workspace\s*{[^}]*grid-template-columns:\s*1fr;/,
    );
  });

  it("gates profile writes until a warned load failure is explicitly reset", () => {
    const setContext = vi.fn();
    const reset = vi.fn();
    const store = createTestStore({
      getLoadError: () => ({
        code: "malformed_profile",
        message: "Stored learning profile is malformed.",
      }),
      setContext,
      reset,
    });
    render(<App profileStore={store} />);

    const warning = screen.getByRole("alert");
    expect(warning).toHaveTextContent("本地学习档案无法读取");
    expect(warning).toHaveTextContent("确认重置");

    fireEvent.click(screen.getByRole("tab", { name: "图谱" }));
    expect(screen.getByRole("main")).toHaveTextContent("图谱");
    expect(setContext).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "重置学习档案" }));
    fireEvent.click(
      within(
        screen.getByRole("alertdialog", { name: "确认重置学习档案" }),
      ).getByRole("button", { name: "取消" }),
    );
    fireEvent.click(screen.getByRole("tab", { name: "任务转化" }));

    expect(reset).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "本地学习档案无法读取",
    );
    expect(setContext).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "重置学习档案" }));
    fireEvent.click(
      within(
        screen.getByRole("alertdialog", { name: "确认重置学习档案" }),
      ).getByRole("button", { name: "确认重置" }),
    );

    expect(reset).toHaveBeenCalledOnce();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "图谱" }));
    expect(setContext).toHaveBeenCalledOnce();
    expect(setContext).toHaveBeenCalledWith({ lastMode: "graph" });
  });

  it("keeps the recovery gate and in-memory state when reset fails", () => {
    const setContext = vi.fn();
    const store = createTestStore({
      getLoadError: () => ({
        code: "unsupported_version",
        message: "Stored learning profile uses an unsupported version.",
      }),
      setContext,
      reset: vi.fn(() => {
        throw new Error("storage unavailable");
      }),
    });
    render(<App profileStore={store} />);

    fireEvent.click(screen.getByRole("tab", { name: "图谱" }));
    fireEvent.click(screen.getByRole("button", { name: "重置学习档案" }));
    fireEvent.click(
      within(
        screen.getByRole("alertdialog", { name: "确认重置学习档案" }),
      ).getByRole("button", { name: "确认重置" }),
    );

    expect(screen.getByRole("main")).toHaveTextContent("图谱");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "本地学习档案无法读取",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("重置失败");
    fireEvent.click(screen.getByRole("tab", { name: "任务转化" }));
    expect(setContext).not.toHaveBeenCalled();
  });

  it.each(["snapshot", "getLoadError"] as const)(
    "uses safe defaults and gates writes when profile %s throws",
    (failingMethod) => {
      const setContext = vi.fn();
      const store = createTestStore({
        snapshot:
          failingMethod === "snapshot"
            ? () => {
                throw new Error("snapshot unavailable");
              }
            : () => createSnapshot("graph"),
        getLoadError:
          failingMethod === "getLoadError"
            ? () => {
                throw new Error("load status unavailable");
              }
            : () => null,
        setContext,
      });

      expect(() => render(<App profileStore={store} />)).not.toThrow();
      expect(screen.getByRole("main")).toHaveTextContent("课程");
      expect(screen.getByRole("main")).toHaveTextContent("文本");
      expect(screen.getByRole("alert")).toHaveTextContent(
        "本地学习档案无法读取",
      );

      fireEvent.click(screen.getByRole("tab", { name: "图谱" }));
      expect(screen.getByRole("main")).toHaveTextContent("图谱");
      expect(setContext).not.toHaveBeenCalled();
    },
  );

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
    const resetButton = screen.getByRole("button", {
      name: "重置学习档案",
    });
    fireEvent.click(resetButton);

    const dialog = screen.getByRole("alertdialog", {
      name: "确认重置学习档案",
    });
    expect(dialog).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));

    expect(reset).not.toHaveBeenCalled();
    expect(resetButton).toHaveFocus();
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
    expect(resetButton).toHaveFocus();
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
