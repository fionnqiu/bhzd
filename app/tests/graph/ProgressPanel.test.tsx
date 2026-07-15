import "@testing-library/jest-dom/vitest";

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type {
  GraphDocument,
  GraphEdge,
  GraphNode,
} from "../../src/data/contracts";
import { createGraphEngine } from "../../src/graph/graphEngine";
import { ProgressPanel } from "../../src/features/graph/ProgressPanel";
import type { LearningProfileSnapshot } from "../../src/state/profileStore";

const makeNode = (
  id: string,
  label = id,
  status = "published",
  type: GraphNode["type"] = "CAP",
): GraphNode => ({
  id,
  label,
  description: `${label} description`,
  data_types: ["text"],
  type,
  status,
  source_refs: [],
});

const makeEdge = (
  id: string,
  source: string,
  target: string,
  relation = "PRE",
): GraphEdge => ({
  id,
  source,
  target,
  relation,
  label: relation,
  metadata: {},
});

const makeDocument = (
  nodes: GraphNode[],
  edges: GraphEdge[],
): GraphDocument => ({
  schema_version: "test",
  graph_id: "GRAPH-PROGRESS-TEST",
  graph_version: "1",
  nodes,
  edges,
});

const snapshot = (
  generalMastery: Readonly<Record<string, number>> = {},
  scenarioMastery: Readonly<Record<string, number>> = {},
): LearningProfileSnapshot => ({
  version: 1,
  generalMastery,
  scenarioMastery,
  attempts: [],
  lastMode: null,
  lastScenario: null,
  lastUnit: null,
  lastNode: null,
});

afterEach(() => {
  cleanup();
});

describe("ProgressPanel", () => {
  it("keeps general and selected-scenario bands separate at the mastery thresholds", () => {
    const nodes = [
      makeNode("CAP-BEGINNER", "Beginner capability"),
      makeNode("CAP-NEEDS", "Needs-work capability"),
      makeNode("CAP-CONSOLIDATING", "Consolidating capability"),
      makeNode("CAP-MASTERED", "Mastered capability"),
      makeNode("CAP-UNLEARNED", "Unlearned capability"),
    ];

    render(
      <ProgressPanel
        graphEngine={createGraphEngine(makeDocument(nodes, []))}
        profileSnapshot={snapshot(
          {
            "CAP-BEGINNER": 0.2,
            "CAP-NEEDS": 0.4,
            "CAP-CONSOLIDATING": 0.6,
            "CAP-MASTERED": 0.8,
          },
          {
            "CAP-BEGINNER::SCN-001": 0.8,
            "CAP-NEEDS::SCN-001": 0.2,
          },
        )}
        scenarioId="SCN-001"
        nodes={nodes}
      />,
    );

    expect(screen.getByRole("heading", { name: "通用掌握度" })).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "场景掌握度：SCN-001" }),
    ).toBeVisible();

    const general = screen.getByRole("group", { name: "通用掌握度" });
    const scenario = screen.getByRole("group", {
      name: "场景掌握度：SCN-001",
    });
    expect(within(general).getByText("需补强")).toBeVisible();
    expect(within(general).getByText("巩固中")).toBeVisible();
    expect(within(general).getByText("已掌握")).toBeVisible();
    expect(within(general).getByText("未学习")).toBeVisible();
    expect(within(scenario).getByText(/场景.*需补强/u)).toBeVisible();
    expect(within(scenario).getByText(/场景.*已掌握/u)).toBeVisible();
    expect(within(scenario).getByText(/场景.*未学习/u)).toBeVisible();
  });

  it("renders real PRE steps in engine order with labels, status, mastery, and skipPractice", () => {
    const nodes = [
      makeNode("CAP-PRE", "先修能力", "published"),
      makeNode("CAP-TARGET", "目标能力", "reviewed"),
    ];
    const engine = createGraphEngine(
      makeDocument(nodes, [makeEdge("EDGE-PRE", "CAP-PRE", "CAP-TARGET")]),
    );

    render(
      <ProgressPanel
        graphEngine={engine}
        profileSnapshot={snapshot({ "CAP-PRE": 0.8, "CAP-TARGET": 0.65 })}
        targetNodeId="CAP-TARGET"
        nodes={nodes}
      />,
    );

    expect(
      screen.getByRole("heading", {
        name: "按前置关系排序的补强计划",
      }),
    ).toBeVisible();
    const steps = screen.getByRole("list", { name: "补强步骤" });
    const items = within(steps).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("先修能力");
    expect(items[0]).toHaveTextContent("节点状态：published");
    expect(items[0]).toHaveTextContent("0.8");
    expect(items[0]).toHaveTextContent("跳过练习");
    expect(items[0]).toHaveTextContent("skipPractice=true");
    expect(items[1]).toHaveTextContent("目标能力");
    expect(items[1]).toHaveTextContent("节点状态：reviewed");
    expect(items[1]).toHaveTextContent("0.65");
    expect(items[1]).toHaveTextContent("需要练习");
    expect(items[1]).toHaveTextContent("skipPractice=false");
  });

  it("counts only CAP nodes while retaining non-CAP remediation metadata", () => {
    const capability = makeNode("CAP-PRE", "先修能力", "published");
    const knowledge = makeNode(
      "KNG-TARGET",
      "知识目标",
      "reviewed",
      "KNG",
    );
    const nodes = [capability, knowledge];
    const engine = createGraphEngine(
      makeDocument(nodes, [makeEdge("EDGE-PRE-KNG", capability.id, knowledge.id)]),
    );

    render(
      <ProgressPanel
        graphEngine={engine}
        profileSnapshot={snapshot()}
        targetNodeId={knowledge.id}
        nodes={nodes}
      />,
    );

    const general = screen.getByRole("group", { name: "通用掌握度" });
    expect(
      within(general).getByLabelText("通用掌握度未学习数量"),
    ).toHaveTextContent("1");
    expect(
      within(general).getByLabelText("通用掌握度需补强数量"),
    ).toHaveTextContent("0");
    expect(
      within(general).getByLabelText("通用掌握度巩固中数量"),
    ).toHaveTextContent("0");
    expect(
      within(general).getByLabelText("通用掌握度已掌握数量"),
    ).toHaveTextContent("0");

    const steps = screen.getByRole("list", { name: "补强步骤" });
    expect(within(steps).getByText("知识目标")).toBeVisible();
    expect(within(steps).getByText("节点状态：reviewed")).toBeVisible();
  });

  it("does not fall back to general mastery while a scenario is selected", () => {
    const nodes = [makeNode("CAP-TARGET", "目标能力")];
    const engine = createGraphEngine(makeDocument(nodes, []));

    render(
      <ProgressPanel
        graphEngine={engine}
        profileSnapshot={snapshot({ "CAP-TARGET": 0.95 })}
        targetNodeId="CAP-TARGET"
        scenarioId="SCN-ISOLATED"
        nodes={nodes}
      />,
    );

    const step = within(
      screen.getByRole("list", { name: "补强步骤" }),
    ).getByRole("listitem");
    expect(step).toHaveTextContent("目标能力");
    expect(step).toHaveTextContent("未学习");
    expect(step).toHaveTextContent("skipPractice=false");
    expect(step).not.toHaveTextContent("0.95");
    expect(step).not.toHaveTextContent("跳过练习");
  });

  it("uses general mastery only when no scenario is selected", () => {
    const nodes = [makeNode("CAP-TARGET", "目标能力")];
    const engine = createGraphEngine(makeDocument(nodes, []));

    render(
      <ProgressPanel
        graphEngine={engine}
        profileSnapshot={snapshot(
          {},
          { "CAP-TARGET::SCN-001": 0.95 },
        )}
        targetNodeId="CAP-TARGET"
        nodes={nodes}
      />,
    );

    const step = within(
      screen.getByRole("list", { name: "补强步骤" }),
    ).getByRole("listitem");
    expect(step).toHaveTextContent("目标能力");
    expect(step).toHaveTextContent("未学习");
    expect(step).not.toHaveTextContent("0.95");
  });

  it("shows a non-executable status and no steps when the real PRE graph contains a cycle", () => {
    const nodes = [
      makeNode("CAP-CYCLE-A", "环路 A"),
      makeNode("CAP-CYCLE-B", "环路 B"),
    ];
    const engine = createGraphEngine(
      makeDocument(nodes, [
        makeEdge("EDGE-CYCLE-A", "CAP-CYCLE-A", "CAP-CYCLE-B"),
        makeEdge("EDGE-CYCLE-B", "CAP-CYCLE-B", "CAP-CYCLE-A"),
      ]),
    );

    render(
      <ProgressPanel
        graphEngine={engine}
        profileSnapshot={snapshot()}
        targetNodeId="CAP-CYCLE-B"
        nodes={nodes}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("PRE");
    expect(screen.getByRole("status")).toHaveTextContent("不可执行");
    expect(
      screen.queryByRole("list", { name: "补强步骤" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "按前置关系排序的补强计划" }),
    ).not.toBeInTheDocument();
  });

  it("keeps a null target recoverable with an accessible empty status", () => {
    const nodes = [makeNode("CAP-TARGET", "目标能力")];
    const engine = createGraphEngine(makeDocument(nodes, []));

    render(
      <ProgressPanel
        graphEngine={engine}
        profileSnapshot={snapshot()}
        targetNodeId={null}
        nodes={nodes}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("选择节点");
    expect(
      screen.queryByRole("heading", { name: "按前置关系排序的补强计划" }),
    ).not.toBeInTheDocument();
  });

  it("keeps an unknown target recoverable instead of exposing an engine error", () => {
    const nodes = [makeNode("CAP-KNOWN", "已知能力")];
    const engine = createGraphEngine(makeDocument(nodes, []));

    render(
      <ProgressPanel
        graphEngine={engine}
        profileSnapshot={snapshot()}
        targetNodeId="CAP-MISSING"
        nodes={nodes}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("未找到");
    expect(screen.getByRole("status")).toHaveTextContent("重新选择");
    expect(screen.getByRole("status")).not.toHaveTextContent("Unknown graph node");
    expect(
      screen.queryByRole("list", { name: "补强步骤" }),
    ).not.toBeInTheDocument();
  });
});
