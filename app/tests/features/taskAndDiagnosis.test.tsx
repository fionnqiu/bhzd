import "@testing-library/jest-dom/vitest";

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/app/App";
import type {
  LearningProfileSnapshot,
  ProfileStore,
} from "../../src/state/profileStore";

const createSnapshot = (): LearningProfileSnapshot => ({
  version: 1,
  generalMastery: {},
  scenarioMastery: {},
  attempts: [],
  lastMode: null,
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

describe("task conversion and diagnosis workspaces", () => {
  it("keeps the current scenario until a medical suggestion is confirmed", async () => {
    render(<App profileStore={createTestStore()} />);

    fireEvent.click(screen.getByRole("tab", { name: "任务转化" }));
    fireEvent.change(screen.getByLabelText("企业任务描述"), {
      target: { value: "医疗文本实体标注" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成学习任务卡" }));

    expect(await screen.findByText(/建议切换到医疗数据标注场景/)).toBeVisible();
    expect(
      screen.getByRole("button", { name: "通用场景" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("keeps png uploads in explanation-only mode without writing mastery", async () => {
    const recordExercise = vi.fn();
    render(<App profileStore={createTestStore({ recordExercise })} />);

    fireEvent.click(screen.getByRole("tab", { name: "标注诊断" }));
    const screenshot = new File(["png"], "explanation.png", {
      type: "image/png",
    });
    fireEvent.change(screen.getByLabelText("上传标注导出文件"), {
      target: { files: [screenshot] },
    });

    expect(await screen.findByText("辅助讲解模式", { exact: true })).toBeVisible();
    expect(screen.queryByText(/掌握度已更新/)).not.toBeInTheDocument();
    expect(recordExercise).not.toHaveBeenCalled();
  });
});
