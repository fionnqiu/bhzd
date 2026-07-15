import "@testing-library/jest-dom/vitest";

import { useState } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createRepository } from "../../src/data/repository";
import {
  graph,
  scenarios,
  sourceRegistry,
  teachingUnits,
} from "../../src/data/rawData";
import { ScenarioSwitcher } from "../../src/features/scenarios/ScenarioSwitcher";
import { TaskConverterView } from "../../src/features/tasks/TaskConverterView";
import { createGraphEngine } from "../../src/graph/graphEngine";

const repository = createRepository({
  graph,
  scenarios,
  sourceRegistry,
  teachingUnits,
});
const graphEngine = createGraphEngine(graph);

afterEach(() => {
  cleanup();
});

describe("TaskConverterView", () => {
  it("rebuilds task cards in the confirmed scenario", () => {
    function ControlledConverter() {
      const [scenarioId, setScenarioId] = useState<string | null>(
        "SCN-CUSTOMER-SERVICE-001",
      );

      return (
        <TaskConverterView
          repository={repository}
          graphEngine={graphEngine}
          currentScenarioId={scenarioId}
          dataType="text"
          onApplyScenario={setScenarioId}
        />
      );
    }

    render(<ControlledConverter />);

    fireEvent.change(screen.getByLabelText("企业任务描述"), {
      target: { value: "医疗文本实体标注" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成学习任务卡" }));

    const firstCard = screen.getAllByRole("article", { name: /任务卡/u })[0];
    expect(firstCard).toBeDefined();
    expect(within(firstCard!).getByText("智能客服标注")).toBeVisible();

    fireEvent.click(
      screen.getByRole("button", { name: "确认应用场景：医疗数据标注" }),
    );

    expect(
      within(screen.getAllByRole("article", { name: /任务卡/u })[0]!).getByText(
        "医疗数据标注",
      ),
    ).toBeVisible();
  });

  it("rebuilds task cards when a user manually changes the scenario", () => {
    function ControlledConverter() {
      const [scenarioId, setScenarioId] = useState<string | null>(
        "SCN-CUSTOMER-SERVICE-001",
      );

      return (
        <TaskConverterView
          repository={repository}
          graphEngine={graphEngine}
          currentScenarioId={scenarioId}
          dataType="text"
          onSelectScenario={setScenarioId}
        />
      );
    }

    render(<ControlledConverter />);

    fireEvent.change(screen.getByLabelText("企业任务描述"), {
      target: { value: "医疗文本实体标注" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成学习任务卡" }));

    expect(
      within(screen.getAllByRole("article", { name: /任务卡/u })[0]!).getByText(
        "智能客服标注",
      ),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "通用场景" }));

    expect(
      within(screen.getAllByRole("article", { name: /任务卡/u })[0]!).getByText(
        "通用标注规则",
      ),
    ).toBeVisible();
  });

  it("rebuilds task cards when a parent clears the current scenario", () => {
    function ParentControlledConverter() {
      const [scenarioId, setScenarioId] = useState<string | null>(
        "SCN-CUSTOMER-SERVICE-001",
      );

      return (
        <>
          <button type="button" onClick={() => setScenarioId(null)}>
            外部清除场景
          </button>
          <TaskConverterView
            repository={repository}
            graphEngine={graphEngine}
            currentScenarioId={scenarioId}
            dataType="text"
          />
        </>
      );
    }

    render(<ParentControlledConverter />);

    fireEvent.change(screen.getByLabelText("企业任务描述"), {
      target: { value: "医疗文本实体标注" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成学习任务卡" }));

    expect(
      within(screen.getAllByRole("article", { name: /任务卡/u })[0]!).getByText(
        "智能客服标注",
      ),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "外部清除场景" }));

    expect(
      within(screen.getAllByRole("article", { name: /任务卡/u })[0]!).getByText(
        "通用标注规则",
      ),
    ).toBeVisible();
  });

  it("names the suggested scene instead of hardcoding a medical label", () => {
    render(
      <TaskConverterView
        repository={repository}
        graphEngine={graphEngine}
        currentScenarioId="SCN-MEDICAL-001"
        dataType="text"
        onApplyScenario={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("企业任务描述"), {
      target: { value: "客服文本意图标注" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成学习任务卡" }));

    expect(screen.getByRole("status")).toHaveTextContent(
      "建议切换到智能客服标注场景",
    );
    expect(screen.getByRole("status")).not.toHaveTextContent(
      "建议切换到医疗场景",
    );
  });

  it("does not render an executable suggestion confirmation without an apply callback", () => {
    render(
      <TaskConverterView
        repository={repository}
        graphEngine={graphEngine}
        currentScenarioId="SCN-CUSTOMER-SERVICE-001"
        dataType="text"
      />,
    );

    fireEvent.change(screen.getByLabelText("企业任务描述"), {
      target: { value: "医疗文本实体标注" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成学习任务卡" }));

    expect(screen.getByRole("status")).toHaveTextContent("医疗数据标注");
    expect(
      screen.queryByRole("button", { name: "确认应用场景：医疗数据标注" }),
    ).not.toBeInTheDocument();
  });

  it("does not offer an incompatible suggested scenario for confirmation", () => {
    render(
      <TaskConverterView
        repository={repository}
        graphEngine={graphEngine}
        currentScenarioId={null}
        dataType="text"
        onApplyScenario={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("企业任务描述"), {
      target: { value: "医疗视频行为事件标注" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成学习任务卡" }));

    expect(screen.getByRole("status")).toHaveTextContent("医疗数据标注");
    expect(
      screen.queryByRole("button", { name: "确认应用场景：医疗数据标注" }),
    ).not.toBeInTheDocument();
  });

  it.each([
    ["draft", true],
    ["published", false],
  ])(
    "does not expose a %s suggested scenario",
    (reviewStatus, studentVisible) => {
      const gatedScenarioDocuments = structuredClone(scenarios);
      const medicalScenario = gatedScenarioDocuments.find(
        (document) => document.scenario.id === "SCN-MEDICAL-001",
      )?.scenario;
      if (medicalScenario === undefined) {
        throw new Error("canonical medical scenario missing");
      }
      medicalScenario.review_status = reviewStatus;
      medicalScenario.student_visible = studentVisible;
      const gatedRepository = createRepository({
        graph,
        scenarios: gatedScenarioDocuments,
        sourceRegistry,
        teachingUnits,
      });

      render(
        <TaskConverterView
          repository={gatedRepository}
          graphEngine={graphEngine}
          currentScenarioId="SCN-CUSTOMER-SERVICE-001"
          dataType="text"
          onApplyScenario={vi.fn()}
        />,
      );

      fireEvent.change(screen.getByLabelText("企业任务描述"), {
        target: { value: "医疗文本实体标注" },
      });
      fireEvent.click(screen.getByRole("button", { name: "生成学习任务卡" }));

      expect(
        screen.queryByRole("region", { name: "场景建议" }),
      ).not.toBeInTheDocument();
      expect(screen.queryByText("医疗数据标注")).not.toBeInTheDocument();
      expect(document.body).not.toHaveTextContent("SCN-MEDICAL-001");
    },
  );

  it("only suggests a medical scenario from a customer-service context until confirmation", () => {
    const applyScenario = vi.fn();
    const selectScenario = vi.fn();

    render(
      <TaskConverterView
        repository={repository}
        graphEngine={graphEngine}
        currentScenarioId="SCN-CUSTOMER-SERVICE-001"
        dataType="text"
        onSelectScenario={selectScenario}
        onApplyScenario={applyScenario}
      />,
    );

    fireEvent.change(screen.getByLabelText("企业任务描述"), {
      target: { value: "医疗文本实体标注" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成学习任务卡" }));

    expect(screen.getByRole("status")).toHaveTextContent("医疗数据标注");
    expect(screen.getByRole("status")).toHaveTextContent(
      "建议切换到医疗数据标注场景",
    );
    expect(screen.getByRole("status")).toHaveTextContent("仍保持当前场景");
    expect(applyScenario).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "取消场景建议" }));
    expect(applyScenario).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "生成学习任务卡" }));
    fireEvent.click(
      screen.getByRole("button", { name: "确认应用场景：医疗数据标注" }),
    );
    expect(applyScenario).toHaveBeenCalledOnce();
    expect(applyScenario).toHaveBeenCalledWith("SCN-MEDICAL-001");
    expect(selectScenario).not.toHaveBeenCalled();
  });

  it("asks for the data type for an ambiguous business task", () => {
    render(
      <TaskConverterView
        repository={repository}
        graphEngine={graphEngine}
        currentScenarioId={null}
        dataType={null}
      />,
    );

    fireEvent.change(screen.getByLabelText("企业任务描述"), {
      target: { value: "请帮我完成一项标注工作" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成学习任务卡" }));

    expect(screen.getByRole("heading", { name: "需要补充信息" })).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("数据类型");
    expect(screen.getByRole("list", { name: "可选匹配项" })).not.toBeEmptyDOMElement();
  });

  it("renders SUP and scenario evidence with PRE-ordered cards that keep 3-9 steps", () => {
    render(
      <TaskConverterView
        repository={repository}
        graphEngine={graphEngine}
        currentScenarioId="SCN-CUSTOMER-SERVICE-001"
        dataType="text"
      />,
    );

    fireEvent.change(screen.getByLabelText("企业任务描述"), {
      target: { value: "医疗文本实体标注" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成学习任务卡" }));

    const evidence = screen.getByRole("list", { name: "匹配证据" });
    expect(within(evidence).getByText(/capability_selection:SUP:/u)).toBeVisible();
    expect(
      within(evidence).getByText("scenario:suggested:SCN-MEDICAL-001:keywords=医疗"),
    ).toBeVisible();

    const cards = screen.getAllByRole("article", { name: /任务卡/u });
    expect(cards.length).toBeGreaterThan(0);
    for (const card of cards) {
      const steps = within(card).getByRole("list", { name: "操作步骤" });
      expect(within(steps).getAllByRole("listitem").length).toBeGreaterThanOrEqual(3);
      expect(within(steps).getAllByRole("listitem").length).toBeLessThanOrEqual(9);
      const selfCheckItems = within(card).getByRole("list", {
        name: "自检清单",
      });
      expect(within(selfCheckItems).getAllByRole("listitem")).not.toHaveLength(0);
    }
  });
});

describe("ScenarioSwitcher", () => {
  it("shows general plus all four scenarios and disables unsupported scenarios", () => {
    const selectScenario = vi.fn();

    render(
      <ScenarioSwitcher
        repository={repository}
        currentScenarioId={null}
        dataType="video"
        onSelectScenario={selectScenario}
      />,
    );

    const switcher = screen.getByRole("group", { name: "场景切换" });
    expect(within(switcher).getByRole("button", { name: "通用场景" })).toBeEnabled();
    expect(
      within(switcher).getByRole("button", { name: /^医疗数据标注/u }),
    ).toBeDisabled();
    expect(
      within(switcher).getByRole("button", { name: /^智能客服标注/u }),
    ).toBeDisabled();
    expect(
      within(switcher).getByRole("button", { name: /^车载语音标注/u }),
    ).toBeDisabled();

    fireEvent.click(
      within(switcher).getByRole("button", { name: "内容安全审核" }),
    );
    expect(selectScenario).toHaveBeenCalledWith("SCN-CONTENT-SAFETY-001");
  });
});
