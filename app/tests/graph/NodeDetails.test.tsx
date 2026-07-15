import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  GraphDocument,
  GraphEdge,
  GraphNode,
  ScenarioDocumentCollection,
  SourceRegistryDocument,
  TeachingUnit,
  TeachingUnitDocument,
} from "../../src/data/contracts";
import { createRepository, type TeachingRepository } from "../../src/data/repository";
import { NodeDetails, type NodeDetailsProps } from "../../src/features/graph/NodeDetails";

const makeNode = (
  id: string,
  label: string,
  type: string,
  status: string,
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
  relation: string,
  label: string,
): GraphEdge => ({
  id,
  source,
  target,
  relation,
  label,
  metadata: {},
});

const makeUnit = (
  id: string,
  title: string,
  capabilityRefs: string[],
  reviewStatus = "published",
  studentVisible = true,
): TeachingUnit => ({
  id,
  data_type: "text",
  title,
  learning_objectives: ["objective"],
  prerequisites: [],
  rule_refs: [],
  source_refs: [],
  exercise: {
    exercise_id: `${id}-EX`,
    exercise_type: "structured",
    data_version: "1.0.0",
    input: { prompt: "learner prompt" },
    student_action: "submit",
    answer: { secretAnswer: "must not render" },
    evaluation: { secretPolicy: "must not render" },
    capability_refs: capabilityRefs,
  },
  review_status: reviewStatus,
  student_visible: studentVisible,
});

const makeRepository = (): TeachingRepository => {
  const nodes = [
    makeNode("CAP-TARGET", "目标能力", "CAP", "draft"),
    makeNode("KNG-PRE", "前置知识", "KNG", "published"),
    makeNode("TSK-LINK", "关联任务", "TSK", "reviewed"),
  ];
  const graph: GraphDocument = {
    schema_version: "1.0.0",
    graph_id: "test-graph",
    graph_version: "1.0.0",
    nodes,
    edges: [
      makeEdge("EDGE-PRE", "KNG-PRE", "CAP-TARGET", "PRE", "前置"),
      makeEdge("EDGE-SUP", "CAP-TARGET", "TSK-LINK", "SUP", "支撑"),
    ],
  };
  const consumable = makeUnit(
    "TU-CAPABILITY",
    "通过能力引用关联的课程",
    ["CAP-TARGET"],
  );
  const direct = makeUnit(
    "TU-DIRECT",
    "通过节点引用关联的课程",
    [],
  );
  (nodes[0] as GraphNode & { teaching_unit_refs: string[] }).teaching_unit_refs = [
    direct.id,
  ];
  const draft = makeUnit(
    "TU-DRAFT",
    "草稿课程不可见",
    ["CAP-TARGET"],
    "draft",
  );
  const hidden = makeUnit(
    "TU-HIDDEN",
    "隐藏课程不可见",
    ["CAP-TARGET"],
    "published",
    false,
  );
  const unindexed = makeUnit(
    "TU-UNINDEXED",
    "未索引课程不可见",
    ["CAP-TARGET"],
  );
  const teachingUnits: TeachingUnitDocument = {
    schema_version: "1.0.0",
    student_visible_unit_ids: [consumable.id, direct.id, draft.id, hidden.id],
    units: [consumable, direct, draft, hidden, unindexed],
  };
  const scenarios: ScenarioDocumentCollection = [];
  const sourceRegistry: SourceRegistryDocument = {
    schema_version: "1.0.0",
    sources: [],
  };
  return createRepository({ graph, scenarios, sourceRegistry, teachingUnits });
};

const baseProps = (repository: TeachingRepository): NodeDetailsProps => ({
  node: repository.getNode("CAP-TARGET")!,
  incomingEdges: repository.getIncomingEdges("CAP-TARGET"),
  outgoingEdges: repository.getOutgoingEdges("CAP-TARGET"),
  getNode: repository.getNode,
  consumableUnits: [],
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("NodeDetails", () => {
  it("shows canonical node identity/status and typed incoming/outgoing endpoint truth", () => {
    const repository = makeRepository();

    render(<NodeDetails {...baseProps(repository)} repository={repository} />);

    expect(screen.getByRole("heading", { level: 2, name: "目标能力" })).toBeVisible();
    expect(screen.getByText("CAP / CAP-TARGET")).toBeVisible();
    expect(screen.getByText("节点状态：draft")).toBeVisible();
    expect(screen.getByRole("heading", { name: "入向关系" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "出向关系" })).toBeVisible();
    expect(screen.getByRole("list", { name: "入向关系" })).toHaveTextContent(
      "PRE · 前置 · 来自 前置知识（KNG · 状态：published",
    );
    expect(screen.getByRole("list", { name: "出向关系" })).toHaveTextContent(
      "SUP · 支撑 · 指向 关联任务（TSK · 状态：reviewed",
    );
    expect(screen.queryByText("已掌握")).not.toBeInTheDocument();
  });

  it("uses repository-gated direct and capability_refs links and rejects draft/hidden/unindexed units", () => {
    const repository = makeRepository();

    render(<NodeDetails {...baseProps(repository)} repository={repository} />);

    expect(
      screen.getByRole("button", { name: "开始课程：通过能力引用关联的课程" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "开始课程：通过节点引用关联的课程" }),
    ).toBeEnabled();
    expect(screen.queryByText("草稿课程不可见")).not.toBeInTheDocument();
    expect(screen.queryByText("隐藏课程不可见")).not.toBeInTheDocument();
    expect(screen.queryByText("未索引课程不可见")).not.toBeInTheDocument();
  });

  it("invokes the lesson callback with the selected consumable unit without exposing answer/evaluation payloads", () => {
    const repository = makeRepository();
    const onOpenLesson = vi.fn();

    render(
      <NodeDetails
        {...baseProps(repository)}
        repository={repository}
        onOpenLesson={onOpenLesson}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "开始课程：通过能力引用关联的课程" }),
    );

    expect(onOpenLesson).toHaveBeenCalledTimes(1);
    expect(onOpenLesson.mock.calls[0]?.[0]).toMatchObject({ id: "TU-CAPABILITY" });
    expect(screen.queryByText("must not render")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("secretAnswer");
    expect(document.body.textContent).not.toContain("secretPolicy");
  });

  it("renders a recoverable empty state and can be rerendered with a selected node", () => {
    const repository = makeRepository();
    const emptyProps = {
      ...baseProps(repository),
      node: undefined,
    } as unknown as NodeDetailsProps;
    const view = render(<NodeDetails {...emptyProps} repository={repository} />);

    expect(screen.getByRole("status")).toHaveTextContent("请选择图谱节点");
    expect(screen.queryByRole("heading", { level: 2 })).not.toBeInTheDocument();

    view.rerender(<NodeDetails {...baseProps(repository)} repository={repository} />);
    expect(screen.getByRole("heading", { level: 2, name: "目标能力" })).toBeVisible();
  });
});
