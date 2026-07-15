import "@testing-library/jest-dom/vitest";

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GraphDocument } from "../../src/data/contracts";
import GraphWorkspace from "../../src/features/graph/GraphWorkspace";
import type { GraphRepository } from "../../src/features/graph/GraphCanvas";
import type { GraphEngine } from "../../src/graph/graphEngine";
import type { LearningProfileSnapshot } from "../../src/state/profileStore";

const graphDocument: GraphDocument = {
  schema_version: "1.0.0",
  graph_id: "GRAPH-WORKSPACE-TEST",
  graph_version: "1.0.0",
  nodes: [
    {
      id: "CAP-WORKSPACE-001",
      label: "工作区能力",
      description: "验证同一图谱来源。",
      data_types: ["text"],
      type: "CAP",
      status: "published",
      source_refs: [],
    },
  ],
  edges: [],
};

const profileSnapshot: LearningProfileSnapshot = {
  version: 1,
  generalMastery: {},
  scenarioMastery: {},
  attempts: [],
  lastMode: null,
  lastScenario: null,
  lastUnit: null,
  lastNode: null,
};

describe("GraphWorkspace", () => {
  afterEach(cleanup);

  it("shares one graph document and engine across canvas and progress", () => {
    const graphEngine: GraphEngine = {
      neighborhood: vi.fn(() => ({
        nodes: graphDocument.nodes,
        edges: graphDocument.edges,
        nodeIds: new Set(["CAP-WORKSPACE-001"]),
      })),
      remediationPlan: vi.fn(() => ({
        targetNodeId: "CAP-WORKSPACE-001",
        cycleDetected: false,
        steps: [],
      })),
    };
    const repository: GraphRepository = {
      listConsumableUnits: () => [],
      getNode: (id) => graphDocument.nodes.find((node) => node.id === id),
    };

    render(
      <GraphWorkspace
        repository={repository}
        profileSnapshot={profileSnapshot}
        scenarioId={null}
        initialNodeId="CAP-WORKSPACE-001"
        graphDocument={graphDocument}
        graphEngine={graphEngine}
        onSelectNode={vi.fn()}
        onOpenUnit={vi.fn()}
      />,
    );

    expect(screen.getByText(/局部视图：2 跳 · 1 个节点/)).toBeVisible();
    expect(
      screen.getByLabelText("通用掌握度未学习数量"),
    ).toHaveTextContent("1");
    expect(graphEngine.neighborhood).toHaveBeenCalledWith(
      "CAP-WORKSPACE-001",
      2,
    );
    expect(graphEngine.remediationPlan).toHaveBeenCalledWith(
      "CAP-WORKSPACE-001",
      expect.any(Function),
    );
  });
});
