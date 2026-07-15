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
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  App,
  applyDiagnosticMastery,
  masteryForScenario,
} from "../../src/app/App";
import { AppProvider, useAppContext } from "../../src/app/AppContext";
import { teachingUnits } from "../../src/data/rawData";
import type {
  LearningProfileSnapshot,
  ProfileStore,
} from "../../src/state/profileStore";

const createSnapshot = (
  lastMode: string | null = null,
  lastNode: string | null = null,
  lastScenario: string | null = null,
): LearningProfileSnapshot => ({
  version: 1,
  generalMastery: {},
  scenarioMastery: {},
  attempts: [],
  lastMode,
  lastScenario,
  lastUnit: null,
  lastNode,
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

const createForbiddenPayloadRepository = () => ({
  listConsumableUnits: () =>
    teachingUnits.units.map((unit) =>
      unit.id === "TU-AUDIO-TRANSCRIPTION-PUNCTUATION-001"
        ? {
            ...unit,
            exercise: {
              ...unit.exercise,
              input: {
                ...unit.exercise.input,
                grading: "GRAPH_INPUT_GRADING_SENTINEL",
                pass_score: "GRAPH_INPUT_SCORE_SENTINEL",
              },
              allowed_answers: ["GRAPH_ALLOWED_ANSWER_SENTINEL"],
              diagnostic: "GRAPH_DIAGNOSTIC_SENTINEL",
              grading: "GRAPH_GRADING_SENTINEL",
              pass_score: "GRAPH_PASS_SCORE_SENTINEL",
              evaluation: {
                ...unit.exercise.evaluation,
                allowed_answers: ["GRAPH_EVALUATION_ANSWER_SENTINEL"],
                diagnostic: "GRAPH_EVALUATION_DIAGNOSTIC_SENTINEL",
                grading: "GRAPH_EVALUATION_GRADING_SENTINEL",
                pass_score: "GRAPH_EVALUATION_SCORE_SENTINEL",
              },
            },
          }
        : unit,
    ),
});

interface RgbaColor {
  red: number;
  green: number;
  blue: number;
  alpha: number;
}

const extractCustomProperty = (css: string, property: string): string => {
  const escaped = property.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
  const match = css.match(new RegExp(`${escaped}\\s*:\\s*([^;]+);`, "u"));
  if (match?.[1] === undefined) {
    throw new Error(`Missing CSS custom property ${property}.`);
  }
  return match[1].trim();
};

const extractSelectorColor = (css: string, selector: string): string => {
  const rulePattern = /([^{}]+)\{([^{}]*)\}/gu;
  for (const match of css.matchAll(rulePattern)) {
    const selectors = (match[1] ?? "")
      .split(",")
      .map((candidate) => candidate.trim());
    if (!selectors.includes(selector)) {
      continue;
    }

    const declaration = (match[2] ?? "").match(
      /(?:^|\n)\s*color\s*:\s*([^;]+);/u,
    );
    if (declaration?.[1] !== undefined) {
      return declaration[1].trim();
    }
  }

  throw new Error(`Missing color declaration for ${selector}.`);
};

const parseCssColor = (css: string, source: string): RgbaColor => {
  const value = source.trim();
  const variable = value.match(/^var\((--[a-z0-9-]+)\)$/u);
  if (variable?.[1] !== undefined) {
    return parseCssColor(css, extractCustomProperty(css, variable[1]));
  }

  const hex = value.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/iu)?.[1];
  if (hex !== undefined) {
    const expanded =
      hex.length === 3
        ? [...hex].map((digit) => `${digit}${digit}`).join("")
        : hex;
    return {
      red: Number.parseInt(expanded.slice(0, 2), 16),
      green: Number.parseInt(expanded.slice(2, 4), 16),
      blue: Number.parseInt(expanded.slice(4, 6), 16),
      alpha: 1,
    };
  }

  const rgb = value.match(
    /^rgb\(\s*(\d+)\s+(\d+)\s+(\d+)(?:\s*\/\s*([\d.]+)%)?\s*\)$/u,
  );
  if (rgb !== null) {
    return {
      red: Number(rgb[1]),
      green: Number(rgb[2]),
      blue: Number(rgb[3]),
      alpha: rgb[4] === undefined ? 1 : Number(rgb[4]) / 100,
    };
  }

  throw new Error(`Unsupported CSS color ${source}.`);
};

const compositeOver = (
  foreground: RgbaColor,
  background: RgbaColor,
): RgbaColor => ({
  red:
    foreground.red * foreground.alpha +
    background.red * (1 - foreground.alpha),
  green:
    foreground.green * foreground.alpha +
    background.green * (1 - foreground.alpha),
  blue:
    foreground.blue * foreground.alpha +
    background.blue * (1 - foreground.alpha),
  alpha: 1,
});

const relativeLuminance = (color: RgbaColor): number => {
  const linearize = (channel: number): number => {
    const normalized = channel / 255;
    return normalized <= 0.04045
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4;
  };

  return (
    0.2126 * linearize(color.red) +
    0.7152 * linearize(color.green) +
    0.0722 * linearize(color.blue)
  );
};

const contrastRatio = (
  foreground: RgbaColor,
  background: RgbaColor,
): number => {
  const foregroundLuminance = relativeLuminance(
    compositeOver(foreground, background),
  );
  const backgroundLuminance = relativeLuminance(background);
  return (
    (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) /
    (Math.min(foregroundLuminance, backgroundLuminance) + 0.05)
  );
};

afterEach(() => {
  cleanup();
});

describe("application shell", () => {
  it("keeps small course metadata at WCAG AA contrast on light surfaces", () => {
    const css = readAppCss();
    const backgrounds = [
      parseCssColor(css, "#fff"),
      parseCssColor(css, extractCustomProperty(css, "--paper-white")),
    ];
    const selectors = [
      ".course-browser__count",
      ".course-browser__count strong",
      ".course-card__id",
      ".course-card__facts dt",
      ".lesson-view__id",
      ".lesson-view__status dt",
      ".reference-grid dt",
      ".lesson-section__heading dt",
      ".asset-panel__facts dt",
      ".feedback-panel__facts dt",
      ".feedback-panel__score",
      ".mastery-panel__grid > section > p",
      ".eyebrow--ink",
      ".route-briefing dt",
    ];

    for (const selector of selectors) {
      const foreground = parseCssColor(
        css,
        extractSelectorColor(css, selector),
      );
      for (const background of backgrounds) {
        expect(
          contrastRatio(foreground, background),
          `${selector} must meet 4.5:1 on rgb(${background.red} ${background.green} ${background.blue})`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

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

  it("clears an unsupported scenario when the selected domain changes", () => {
    const setContext = vi.fn();
    render(
      <App
        profileStore={createTestStore({
          snapshot: () =>
            createSnapshot("task", null, "SCN-CUSTOMER-SERVICE-001"),
          setContext,
        })}
      />,
    );

    expect(
      screen.getByRole("button", { name: "智能客服标注" }),
    ).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(
      screen.getByRole("button", { name: "视频课程，3 个可学习单元" }),
    );

    expect(
      screen.getByRole("button", { name: "通用场景" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(setContext).toHaveBeenCalledWith({ lastScenario: null });
  });

  it("clears an initially restored scenario that is unsupported by the default domain", () => {
    const setContext = vi.fn();
    render(
      <App
        profileStore={createTestStore({
          snapshot: () => createSnapshot("task", null, "SCN-IN-VEHICLE-001"),
          setContext,
        })}
      />,
    );

    expect(
      screen.getByRole("button", { name: "通用场景" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(setContext).toHaveBeenCalledWith({ lastScenario: null });
  });

  it("keeps diagnostic remediation mastery isolated by the active scenario", () => {
    const snapshot: LearningProfileSnapshot = {
      ...createSnapshot(),
      generalMastery: { "CAP-TEST-001": 0.9 },
      scenarioMastery: {
        "CAP-TEST-001::SCN-CUSTOMER-SERVICE-001": 0.2,
      },
    };

    expect(masteryForScenario(snapshot, null, "CAP-TEST-001")).toBe(0.9);
    expect(
      masteryForScenario(
        snapshot,
        "SCN-CUSTOMER-SERVICE-001",
        "CAP-TEST-001",
      ),
    ).toBe(0.2);
    expect(
      masteryForScenario(snapshot, "SCN-MEDICAL-001", "CAP-TEST-001"),
    ).toBeNull();
  });

  it("routes diagnostic severities separately from exercise scores", () => {
    const recordExercises = vi.fn(() => true);
    const recordDiagnostics = vi.fn(() => true);

    expect(
      applyDiagnosticMastery(
        {
          kind: "diagnostic",
          entries: [
            { capabilityId: "CAP-TEST-001", severity: "severe" },
          ],
        },
        "SCN-CUSTOMER-SERVICE-001",
        recordExercises,
        recordDiagnostics,
      ),
    ).toBe(true);
    expect(recordExercises).not.toHaveBeenCalled();
    expect(recordDiagnostics).toHaveBeenCalledWith([
      {
        capabilityId: "CAP-TEST-001",
        severity: "severe",
        scenarioId: "SCN-CUSTOMER-SERVICE-001",
        evaluationVersion: "diagnostic-v1",
      },
    ]);

    expect(
      applyDiagnosticMastery(
        {
          kind: "exercise",
          capabilityIds: ["CAP-TEST-002"],
          score: 0.75,
        },
        null,
        recordExercises,
        recordDiagnostics,
      ),
    ).toBe(true);
    expect(recordExercises).toHaveBeenCalledWith([
      {
        capabilityId: "CAP-TEST-002",
        score: 0.75,
        scenarioId: null,
        evaluationVersion: "diagnostic-v1",
      },
    ]);
    expect(recordDiagnostics).toHaveBeenCalledTimes(1);
  });

  it("persists every diagnostic entry and refreshes the profile snapshot", () => {
    const initialSnapshot = createSnapshot();
    const refreshedSnapshot = createSnapshot(null, "CAP-REFRESHED-001");
    const snapshot = vi
      .fn<ProfileStore["snapshot"]>()
      .mockReturnValueOnce(initialSnapshot)
      .mockReturnValue(refreshedSnapshot);
    const recordDiagnostic = vi.fn();
    const inputs = [
      {
        capabilityId: "CAP-TEST-001",
        severity: "severe" as const,
        scenarioId: "SCN-CUSTOMER-SERVICE-001",
        evaluationVersion: "diagnostic-v1",
      },
      {
        capabilityId: "CAP-TEST-002",
        severity: "minor" as const,
        scenarioId: null,
        evaluationVersion: "diagnostic-v1",
      },
    ];

    function DiagnosticPersistenceProbe() {
      const { profileSnapshot, recordDiagnostics } = useAppContext();
      return (
        <>
          <button type="button" onClick={() => recordDiagnostics(inputs)}>
            保存诊断
          </button>
          <output aria-label="诊断刷新节点">
            {profileSnapshot.lastNode ?? "未刷新"}
          </output>
        </>
      );
    }

    render(
      <AppProvider
        profileStore={createTestStore({ snapshot, recordDiagnostic })}
      >
        <DiagnosticPersistenceProbe />
      </AppProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "保存诊断" }));

    expect(recordDiagnostic).toHaveBeenNthCalledWith(1, inputs[0]);
    expect(recordDiagnostic).toHaveBeenNthCalledWith(2, inputs[1]);
    expect(snapshot).toHaveBeenCalledTimes(2);
    expect(screen.getByLabelText("诊断刷新节点")).toHaveTextContent(
      "CAP-REFRESHED-001",
    );
  });

  it("focuses a work-mode tab when it is selected by pointer", () => {
    render(<App profileStore={createTestStore()} />);

    const graphTab = screen.getByRole("tab", { name: "图谱" });
    fireEvent.click(graphTab);

    expect(graphTab).toHaveFocus();
    expect(graphTab).toHaveAttribute("aria-selected", "true");
  });

  it("announces graph workspace loading before graph panels become interactive", async () => {
    render(<App profileStore={createTestStore()} />);

    fireEvent.click(screen.getByRole("tab", { name: "图谱" }));

    expect(
      screen.getByRole("status", { name: "正在加载图谱工作区…" }),
    ).toBeVisible();
    expect(
      await screen.findByRole("option", { name: /转写并添加标点/ }),
    ).toBeVisible();
  });

  it("counts only capability nodes in the graph progress summary", async () => {
    render(<App profileStore={createTestStore()} />);

    fireEvent.click(screen.getByRole("tab", { name: "图谱" }));

    const summary = await screen.findByRole("group", {
      name: "通用掌握度",
    });
    expect(
      within(summary).getByRole("strong", {
        name: "通用掌握度未学习数量",
      }),
    ).toHaveTextContent("40");
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

  it("keeps the graph workspace usable at a 390px viewport", () => {
    const appCss = readAppCss();
    const mobileRules = appCss.match(
      /@media \(max-width: 620px\) {([\s\S]*?)(?=\n@media|$)/,
    )?.[1];

    expect(mobileRules).toBeDefined();
    expect(mobileRules ?? "").toMatch(
      /\.mode-tabs\s*\{[^}]*min-width:\s*0;[^}]*width:\s*100%;[^}]*overflow-x:\s*auto;/su,
    );
    expect(mobileRules ?? "").toMatch(
      /\.graph-explorer__toolbar input,[\s\S]*?\.graph-explorer__summary button,[\s\S]*?width:\s*100%;/su,
    );
    expect(mobileRules ?? "").toMatch(
      /\.graph-explorer__canvas\s*\{[^}]*height:\s*20rem;/su,
    );
    expect(appCss).toMatch(
      /\.graph-workspace\s*\{[^}]*min-width:\s*0;/su,
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

  it("launches a repository-consumable graph lesson through the learner-safe course flow", async () => {
    const setContext = vi.fn();
    render(<App profileStore={createTestStore({ setContext })} />);

    fireEvent.click(screen.getByRole("tab", { name: "图谱" }));
    fireEvent.click(
      await screen.findByRole("option", { name: /转写并添加标点/ }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: /开始课程：按项目正字法完成转写与标点/,
      }),
    );

    const lessonHeading = await screen.findByRole("heading", {
      name: "按项目正字法完成转写与标点",
    });
    expect(lessonHeading).toBeVisible();
    expect(lessonHeading).toHaveFocus();
    expect(setContext).toHaveBeenCalledWith({ lastMode: "course" });
    expect(setContext).toHaveBeenCalledWith({ lastUnit: "TU-AUDIO-TRANSCRIPTION-PUNCTUATION-001" });
  });

  it("keeps injected grading and diagnostic payloads out of a graph-launched lesson", async () => {
    render(
      <App
        repository={createForbiddenPayloadRepository()}
        profileStore={createTestStore()}
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "图谱" }));
    fireEvent.click(
      await screen.findByRole("option", { name: /转写并添加标点/ }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: /开始课程：按项目正字法完成转写与标点/,
      }),
    );
    await screen.findByRole("heading", {
      name: "按项目正字法完成转写与标点",
    });

    for (const sentinel of [
      "GRAPH_ALLOWED_ANSWER_SENTINEL",
      "GRAPH_DIAGNOSTIC_SENTINEL",
      "GRAPH_GRADING_SENTINEL",
      "GRAPH_PASS_SCORE_SENTINEL",
      "GRAPH_EVALUATION_ANSWER_SENTINEL",
      "GRAPH_EVALUATION_DIAGNOSTIC_SENTINEL",
      "GRAPH_EVALUATION_GRADING_SENTINEL",
      "GRAPH_EVALUATION_SCORE_SENTINEL",
      "GRAPH_INPUT_GRADING_SENTINEL",
      "GRAPH_INPUT_SCORE_SENTINEL",
    ]) {
      expect(document.body).not.toHaveTextContent(sentinel);
    }
  });

  it("persists the selected graph node as learner context and clears it on overview", async () => {
    const setContext = vi.fn();
    render(<App profileStore={createTestStore({ setContext })} />);

    fireEvent.click(screen.getByRole("tab", { name: "图谱" }));
    fireEvent.click(
      await screen.findByRole("option", { name: /转写并添加标点/ }),
    );

    expect(setContext).toHaveBeenCalledWith({
      lastNode: "CAP-AUD-TRANSCRIBE-PUNCT-001",
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "返回总览" }),
    );
    expect(setContext).toHaveBeenCalledWith({ lastNode: null });
  });

  it("restores a valid persisted graph node while ignoring an unknown node", async () => {
    const validSetContext = vi.fn();
    const validStore = createTestStore({
      snapshot: () =>
        createSnapshot("graph", "CAP-AUD-TRANSCRIBE-PUNCT-001"),
      setContext: validSetContext,
    });
    render(<App profileStore={validStore} />);

    expect(
      await screen.findByRole("heading", { name: "转写并添加标点" }),
    ).toBeVisible();
    expect(await screen.findByText(/局部视图：2 跳/)).toBeVisible();
    expect(validSetContext).not.toHaveBeenCalledWith({ lastNode: null });
    cleanup();

    const unknownStore = createTestStore({
      snapshot: () => createSnapshot("graph", "CAP-DELETED-999"),
    });
    render(<App profileStore={unknownStore} />);

    expect(
      screen.queryByRole("heading", { name: "转写并添加标点" }),
    ).not.toBeInTheDocument();
    expect(await screen.findByText(/总览：166 个节点/)).toBeVisible();
  });

  it("clears an unknown persisted graph node from the profile", async () => {
    const setContext = vi.fn();
    const store = createTestStore({
      snapshot: () => createSnapshot("graph", "CAP-DELETED-999"),
      setContext,
    });

    render(<App profileStore={store} />);

    await waitFor(() => {
      expect(setContext).toHaveBeenCalledWith({ lastNode: null });
    });
  });
});
