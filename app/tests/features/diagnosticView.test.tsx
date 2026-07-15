import "@testing-library/jest-dom/vitest";

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createGraphEngine } from "../../src/graph/graphEngine";
import {
  graph,
  scenarios,
  sourceRegistry,
  teachingUnits,
} from "../../src/data/rawData";
import { createRepository } from "../../src/data/repository";
import {
  DiagnosticReportView,
  DiagnosticView,
} from "../../src/features/diagnostics/DiagnosticView";
import type { DiagnosticReport } from "../../src/diagnostics/types";

afterEach(cleanup);

const repository = createRepository({
  graph,
  scenarios,
  sourceRegistry,
  teachingUnits,
});

const report = (overrides: Partial<DiagnosticReport> = {}): DiagnosticReport => ({
  status: "complete",
  format: "json",
  masteryImpact: true,
  score: 0.5,
  issues: [
    {
      code: "bbox_out_of_bounds",
      severity: "severe",
      message: "标注框超出图像边界",
      ruleRefs: ["RULE-IMG-001"],
      capabilityRefs: ["CAP-IMG-BOX-ANNOTATE-001"],
      remediation: ["检查边界坐标后重新导出。"],
    },
    {
      code: "field_format",
      severity: "minor",
      message: "字段格式需要复核",
      ruleRefs: ["RULE-FORMAT-001"],
      capabilityRefs: [],
      remediation: ["检查字段格式。"],
    },
  ],
  ...overrides,
});

describe("diagnostic workspace", () => {
  it("keeps PNG uploads in explanation-only mode without recording mastery", async () => {
    const onApplyMastery = vi.fn();
    const diagnose = vi.fn().mockResolvedValue(
      report({
        status: "explanation_only",
        format: "image",
        masteryImpact: false,
        score: null,
        issues: [],
      }),
    );

    render(
      <DiagnosticView
        dataType="image"
        targetUnitId={null}
        diagnose={diagnose}
        onApplyMastery={onApplyMastery}
      />,
    );

    fireEvent.change(screen.getByLabelText("上传标注导出文件"), {
      target: {
        files: [
          new File([new Uint8Array([137, 80, 78, 71])], "shot.png", {
            type: "image/png",
          }),
        ],
      },
    });

    expect(await screen.findByText("辅助讲解模式")).toBeVisible();
    expect(diagnose).not.toHaveBeenCalled();
    expect(onApplyMastery).not.toHaveBeenCalled();
  });

  it("records a passing diagnostic against the target unit capabilities when it has no issues", async () => {
    const onApplyMastery = vi.fn();
    const diagnose = vi.fn().mockResolvedValue(
      report({
        issues: [],
        masteryImpact: true,
        score: 1,
      }),
    );

    render(
      <DiagnosticView
        dataType="audio"
        targetUnitId="TU-AUDIO-EMOTION-PARALINGUISTICS-001"
        repository={repository}
        diagnose={diagnose}
        onApplyMastery={onApplyMastery}
      />,
    );

    fireEvent.change(screen.getByLabelText("上传标注导出文件"), {
      target: {
        files: [new File(["{}"], "valid.json", { type: "application/json" })],
      },
    });

    await waitFor(() => {
      expect(onApplyMastery).toHaveBeenCalledWith({
        kind: "exercise",
        capabilityIds: ["CAP-AUD-EMOTION-PARALING-001"],
        score: 1,
      });
    });
  });

  it.each(["manual_review", "rejected", "explanation_only"] as const)(
    "does not record mastery for a %s diagnostic report",
    async (status) => {
      const onApplyMastery = vi.fn();
      const diagnose = vi.fn().mockResolvedValue(
        report({ status, issues: [], masteryImpact: true, score: 1 }),
      );

      render(
        <DiagnosticView
          dataType="audio"
          targetUnitId="TU-AUDIO-EMOTION-PARALINGUISTICS-001"
          repository={repository}
          diagnose={diagnose}
          onApplyMastery={onApplyMastery}
        />,
      );

      fireEvent.change(screen.getByLabelText("上传标注导出文件"), {
        target: {
          files: [new File(["{}"], "valid.json", { type: "application/json" })],
        },
      });

      await waitFor(() => {
        expect(diagnose).toHaveBeenCalledTimes(1);
      });
      expect(onApplyMastery).not.toHaveBeenCalled();
    },
  );

  it("records issue severities against explicit or target capabilities", async () => {
    const onApplyMastery = vi.fn();
    const diagnose = vi.fn().mockResolvedValue(report());

    render(
      <DiagnosticView
        dataType="audio"
        targetUnitId="TU-AUDIO-EMOTION-PARALINGUISTICS-001"
        repository={repository}
        diagnose={diagnose}
        onApplyMastery={onApplyMastery}
      />,
    );

    fireEvent.change(screen.getByLabelText("上传标注导出文件"), {
      target: {
        files: [new File(["{}"], "valid.json", { type: "application/json" })],
      },
    });

    await waitFor(() => {
      expect(onApplyMastery).toHaveBeenCalledWith({
        kind: "diagnostic",
        entries: [
          { capabilityId: "CAP-IMG-BOX-ANNOTATE-001", severity: "severe" },
          { capabilityId: "CAP-AUD-EMOTION-PARALING-001", severity: "minor" },
        ],
      });
    });
    expect(onApplyMastery).toHaveBeenCalledTimes(1);
  });

  it("deduplicates matching diagnostic capability and severity pairs", async () => {
    const onApplyMastery = vi.fn();
    const diagnose = vi.fn().mockResolvedValue(
      report({
        issues: [
          {
            code: "duplicate_severe",
            severity: "severe",
            message: "重复严重问题",
            ruleRefs: [],
            capabilityRefs: ["CAP-IMG-BOX-ANNOTATE-001"],
            remediation: [],
          },
          {
            code: "same_severe",
            severity: "severe",
            message: "同一能力的重复严重问题",
            ruleRefs: [],
            capabilityRefs: ["CAP-IMG-BOX-ANNOTATE-001"],
            remediation: [],
          },
          {
            code: "distinct_minor",
            severity: "minor",
            message: "同一能力的轻微问题",
            ruleRefs: [],
            capabilityRefs: ["CAP-IMG-BOX-ANNOTATE-001"],
            remediation: [],
          },
        ],
      }),
    );

    render(
      <DiagnosticView
        dataType="image"
        targetUnitId={null}
        diagnose={diagnose}
        onApplyMastery={onApplyMastery}
      />,
    );

    fireEvent.change(screen.getByLabelText("上传标注导出文件"), {
      target: {
        files: [new File(["{}"], "valid.json", { type: "application/json" })],
      },
    });

    await waitFor(() => {
      expect(onApplyMastery).toHaveBeenCalledWith({
        kind: "diagnostic",
        entries: [
          { capabilityId: "CAP-IMG-BOX-ANNOTATE-001", severity: "severe" },
          { capabilityId: "CAP-IMG-BOX-ANNOTATE-001", severity: "minor" },
        ],
      });
    });
  });

  it("ignores a late diagnostic result after a newer upload completes", async () => {
    let resolveFirst: (value: DiagnosticReport) => void = () => undefined;
    let resolveSecond: (value: DiagnosticReport) => void = () => undefined;
    const first = new Promise<DiagnosticReport>((resolve) => {
      resolveFirst = resolve;
    });
    const second = new Promise<DiagnosticReport>((resolve) => {
      resolveSecond = resolve;
    });
    const onApplyMastery = vi.fn();
    const diagnose = vi.fn((file: { name?: string } | null | undefined) =>
      file?.name === "first.json" ? first : second,
    );

    render(
      <DiagnosticView
        dataType="audio"
        targetUnitId="TU-AUDIO-EMOTION-PARALINGUISTICS-001"
        repository={repository}
        diagnose={diagnose}
        onApplyMastery={onApplyMastery}
      />,
    );

    const upload = screen.getByLabelText("上传标注导出文件");
    fireEvent.change(upload, {
      target: {
        files: [new File(["first"], "first.json", { type: "application/json" })],
      },
    });
    fireEvent.change(upload, {
      target: {
        files: [new File(["second"], "second.json", { type: "application/json" })],
      },
    });

    await act(async () => {
      resolveSecond(
        report({
          masteryImpact: false,
          score: null,
          issues: [
            {
              code: "newer_upload",
              severity: "minor",
              message: "新文件诊断结果",
              ruleRefs: [],
              capabilityRefs: [],
              remediation: [],
            },
          ],
        }),
      );
    });
    expect(await screen.findByText("新文件诊断结果")).toBeVisible();

    await act(async () => {
      resolveFirst(report({ issues: [], masteryImpact: true, score: 1 }));
    });

    expect(screen.getByText("新文件诊断结果")).toBeVisible();
    expect(onApplyMastery).not.toHaveBeenCalled();
  });

  it("discards a delayed diagnostic after the selected context changes", async () => {
    let resolveDiagnostic: (value: DiagnosticReport) => void = () => undefined;
    const delayedDiagnostic = new Promise<DiagnosticReport>((resolve) => {
      resolveDiagnostic = resolve;
    });
    const onApplyMastery = vi.fn();
    const diagnose = vi.fn().mockReturnValue(delayedDiagnostic);
    const { rerender } = render(
      <DiagnosticView
        dataType="audio"
        targetUnitId="TU-AUDIO-EMOTION-PARALINGUISTICS-001"
        repository={repository}
        diagnose={diagnose}
        onApplyMastery={onApplyMastery}
      />,
    );

    fireEvent.change(screen.getByLabelText("上传标注导出文件"), {
      target: {
        files: [new File(["{}"], "delayed.json", { type: "application/json" })],
      },
    });

    rerender(
      <DiagnosticView
        dataType="image"
        targetUnitId="TU-IMAGE-BOX-ANNOTATION-001"
        repository={repository}
        diagnose={diagnose}
        onApplyMastery={onApplyMastery}
      />,
    );

    await act(async () => {
      resolveDiagnostic(report({ issues: [], score: 1 }));
    });

    expect(screen.queryByText("标注框超出图像边界")).not.toBeInTheDocument();
    expect(onApplyMastery).not.toHaveBeenCalled();
  });

  it("clears report and error state when the selected context changes", async () => {
    const diagnose = vi.fn().mockResolvedValue(report());
    const { rerender } = render(
      <DiagnosticView
        dataType="audio"
        targetUnitId="TU-AUDIO-EMOTION-PARALINGUISTICS-001"
        repository={repository}
        diagnose={diagnose}
      />,
    );

    const upload = screen.getByLabelText("上传标注导出文件");
    fireEvent.change(upload, {
      target: {
        files: [new File(["{}"], "valid.json", { type: "application/json" })],
      },
    });
    expect(await screen.findByText("标注框超出图像边界")).toBeVisible();

    fireEvent.change(upload, {
      target: { files: [new File(["x"], "unsupported.csv", { type: "text/csv" })] },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("仅支持");

    rerender(
      <DiagnosticView
        dataType="image"
        targetUnitId="TU-IMAGE-BOX-ANNOTATION-001"
        repository={repository}
        diagnose={diagnose}
      />,
    );

    await waitFor(() => {
      expect(screen.queryByText("标注框超出图像边界")).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });

  it("does not apply mastery when an in-flight diagnostic completes after unmount", async () => {
    let resolveDiagnostic: (value: DiagnosticReport) => void = () => undefined;
    const delayedDiagnostic = new Promise<DiagnosticReport>((resolve) => {
      resolveDiagnostic = resolve;
    });
    const onApplyMastery = vi.fn();
    const diagnose = vi.fn().mockReturnValue(delayedDiagnostic);
    const { unmount } = render(
      <DiagnosticView
        dataType="audio"
        targetUnitId="TU-AUDIO-EMOTION-PARALINGUISTICS-001"
        repository={repository}
        diagnose={diagnose}
        onApplyMastery={onApplyMastery}
      />,
    );

    fireEvent.change(screen.getByLabelText("上传标注导出文件"), {
      target: {
        files: [new File(["{}"], "delayed.json", { type: "application/json" })],
      },
    });
    unmount();

    await act(async () => {
      resolveDiagnostic(report({ issues: [], score: 1 }));
    });

    expect(onApplyMastery).not.toHaveBeenCalled();
  });

  it("keeps the previous report visible when an unsupported extension is selected", async () => {
    const diagnose = vi.fn().mockResolvedValue(report());

    render(
      <DiagnosticView
        dataType="image"
        targetUnitId={null}
        diagnose={diagnose}
      />,
    );

    const upload = screen.getByLabelText("上传标注导出文件");
    fireEvent.change(upload, {
      target: { files: [new File(["{}"], "valid.json", { type: "application/json" })] },
    });
    expect(await screen.findByText("标注框超出图像边界")).toBeVisible();

    fireEvent.change(upload, {
      target: { files: [new File(["x"], "unsupported.csv", { type: "text/csv" })] },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("仅支持");
    expect(screen.getByText("标注框超出图像边界")).toBeVisible();
    expect(diagnose).toHaveBeenCalledTimes(1);
  });

  it("uses node mastery when rendering the diagnostic PRE plan", async () => {
    const diagnose = vi.fn().mockResolvedValue(
      report({
        masteryImpact: false,
        score: null,
      }),
    );

    render(
      <DiagnosticView
        dataType="image"
        targetUnitId={null}
        repository={repository}
        graphEngine={createGraphEngine(graph)}
        masteryForNode={() => 0.9}
        diagnose={diagnose}
      />,
    );

    fireEvent.change(screen.getByLabelText("上传标注导出文件"), {
      target: {
        files: [new File(["{}"], "valid.json", { type: "application/json" })],
      },
    });

    expect((await screen.findAllByText("已掌握，可跳过练习")).length).toBeGreaterThan(0);
    expect(screen.queryByText("需要练习")).not.toBeInTheDocument();
  });

  it("groups diagnostic issues and renders a PRE remediation plan without raw file data", () => {
    render(
      <DiagnosticReportView
        report={report()}
        graphEngine={createGraphEngine(graph)}
        repository={repository}
      />,
    );

    expect(screen.getByRole("heading", { name: /严重问题/ })).toBeVisible();
    expect(screen.getByRole("heading", { name: /轻微问题/ })).toBeVisible();
    expect(screen.getByText("RULE-IMG-001")).toBeVisible();
    expect(screen.getByText("CAP-IMG-BOX-ANNOTATE-001")).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "按前置关系排序的补强计划" }),
    ).toBeVisible();
    expect(screen.queryByText("valid.json")).not.toBeInTheDocument();
  });

  it("keeps an unknown remediation target recoverable", async () => {
    render(
      <DiagnosticReportView
        report={
          report({
            issues: [
              {
                code: "unknown_capability",
                severity: "moderate",
                message: "能力引用需要复核",
                ruleRefs: [],
                capabilityRefs: ["CAP-MISSING-001"],
                remediation: ["选择有效能力后重试。"],
              },
            ],
          })
        }
        graphEngine={createGraphEngine(graph)}
        repository={repository}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText(/无法生成/)).toBeVisible();
    });
  });
});
