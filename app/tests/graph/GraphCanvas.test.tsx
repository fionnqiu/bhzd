import "@testing-library/jest-dom/vitest";

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach } from "vitest";
import { describe, expect, it, vi } from "vitest";

import {
  GraphCanvas,
  type NetworkFactory,
  type NetworkSelection,
} from "../../src/features/graph/GraphCanvas";
import {
  createGraphVisualNode,
  graphNodeShape,
} from "../../src/features/graph/graphVisuals";
import type { GraphNode } from "../../src/data/contracts";
import { ProgressPanel } from "../../src/features/graph/ProgressPanel";
import type { LearningProfileSnapshot } from "../../src/state/profileStore";
import type { GraphEngine } from "../../src/graph/graphEngine";

const createFakeNetworkFactory = () => {
  let selectHandler: ((selection: NetworkSelection) => void) | undefined;
  let stabilizationHandler: (() => void) | undefined;
  let latestNetwork: {
    destroy: ReturnType<typeof vi.fn>;
    setData: ReturnType<typeof vi.fn>;
    setOptions: ReturnType<typeof vi.fn>;
  } | undefined;

  const factory = vi.fn<NetworkFactory>(() => {
    const adapter = {
      destroy: vi.fn(),
      setData: vi.fn(),
      setOptions: vi.fn(),
    };
    latestNetwork = adapter;
    return {
      destroy: adapter.destroy,
      on: (event, handler) => {
        if (event === "selectNode") {
          selectHandler = handler;
        } else {
          stabilizationHandler = () => handler({ nodes: [] });
        }
      },
      setData: adapter.setData,
      setOptions: adapter.setOptions,
    };
  });

  return {
    factory,
    get latestNetwork() {
      return latestNetwork;
    },
    emitSelect(nodeId: string) {
      act(() => {
        selectHandler?.({ nodes: [nodeId] });
      });
    },
    emitStabilized() {
      act(() => {
        stabilizationHandler?.();
      });
    },
  };
};

describe("GraphCanvas", () => {
  afterEach(() => {
    cleanup();
  });
  it("maps every canonical node type to the specified shape without changing status", () => {
    expect(
      Object.fromEntries(
        ["CAP", "KNG", "TSK", "SCN", "RES", "CERT"].map((type) => [
          type,
          graphNodeShape(type),
        ]),
      ),
    ).toEqual({
      CAP: "circle",
      KNG: "diamond",
      TSK: "hexagon",
      SCN: "box",
      RES: "dot",
      CERT: "star",
    });

    const node: GraphNode = {
      id: "CAP-TEST-001",
      label: "测试能力",
      description: "保持 canonical status。",
      data_types: ["text"],
      type: "CAP",
      status: "draft",
      source_refs: [],
    };
    const unlearned = createGraphVisualNode(node, null);
    const mastered = createGraphVisualNode(node, 0.9);

    expect(unlearned.color).not.toEqual(mastered.color);
    expect(unlearned.borderWidth).not.toBe(mastered.borderWidth);
    expect(node.status).toBe("draft");
    expect(unlearned).not.toHaveProperty("status");
  });

  it("opens node relations and only repository-consumable linked lessons", async () => {
    const network = createFakeNetworkFactory();

    render(<GraphCanvas networkFactory={network.factory} />);
    network.emitSelect("CAP-AUD-TRANSCRIBE-PUNCT-001");

    expect(
      await screen.findByRole("heading", { name: "转写并添加标点" }),
    ).toBeVisible();
    expect(screen.getByText("前置关系")).toBeVisible();
    expect(screen.getByText("关联关系")).toBeVisible();
    expect(
      screen.getByRole("button", {
        name: /开始课程：按项目正字法完成转写与标点/,
      }),
    ).toBeEnabled();
    expect(screen.getByText(/节点状态：draft/)).toBeVisible();
  });

  it("starts with the complete canonical graph totals", () => {
    const network = createFakeNetworkFactory();

    render(<GraphCanvas networkFactory={network.factory} />);

    const [, data] = network.factory.mock.calls[0] ?? [];
    expect(data?.nodes).toHaveLength(166);
    expect(data?.edges).toHaveLength(240);
    expect(screen.getByText(/166 个节点/)).toBeVisible();
    expect(screen.getByText(/240 条边/)).toBeVisible();
  });

  it("shows a two-hop neighborhood, returns to overview, and destroys the adapter", () => {
    const network = createFakeNetworkFactory();
    const { unmount } = render(<GraphCanvas networkFactory={network.factory} />);

    network.emitSelect("CAP-AUD-TRANSCRIBE-PUNCT-001");
    expect(screen.getByRole("button", { name: "返回总览" })).toBeVisible();
    expect(screen.getByText(/局部视图：2 跳/)).toBeVisible();
    expect(network.latestNetwork?.setData).toHaveBeenCalled();

    act(() => {
      screen.getByRole("button", { name: "返回总览" }).click();
    });
    expect(screen.getByText(/166 个节点/)).toBeVisible();
    unmount();
    expect(network.latestNetwork?.destroy).toHaveBeenCalledTimes(1);
  });

  it("does not repeat a user selection when the parent echoes it as initialNodeId", () => {
    const network = createFakeNetworkFactory();
    const graphEngine: GraphEngine = {
      neighborhood: vi.fn(() => ({
        nodes: [],
        edges: [],
        nodeIds: new Set<string>(),
      })),
      remediationPlan: vi.fn(),
    };
    let echoedNodeId: string | null = null;
    const onSelectNode = vi.fn((nodeId: string | null) => {
      echoedNodeId = nodeId;
    });
    const view = render(
      <GraphCanvas
        networkFactory={network.factory}
        graphEngine={graphEngine}
        onSelectNode={onSelectNode}
        initialNodeId={echoedNodeId}
      />,
    );

    network.emitSelect("CAP-AUD-TRANSCRIBE-PUNCT-001");
    view.rerender(
      <GraphCanvas
        networkFactory={network.factory}
        graphEngine={graphEngine}
        onSelectNode={onSelectNode}
        initialNodeId={echoedNodeId}
      />,
    );

    expect(graphEngine.neighborhood).toHaveBeenCalledTimes(1);
    expect(onSelectNode).toHaveBeenCalledTimes(1);
  });

  it("keeps unknown selections recoverable and exposes keyboard-searchable truth", () => {
    const network = createFakeNetworkFactory();
    render(<GraphCanvas networkFactory={network.factory} />);

    network.emitSelect("UNKNOWN-NODE");
    expect(screen.getByRole("status")).toHaveTextContent("未找到该节点");

    const search = screen.getByRole("searchbox", { name: "搜索图谱节点" });
    fireEvent.change(search, { target: { value: "不存在的节点" } });
    expect(screen.getByRole("status")).toHaveTextContent("没有匹配节点");
    expect(screen.queryByRole("option")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "清空搜索" }));
    expect(search).toHaveValue("");
    expect(search).toHaveFocus();
    expect(screen.getByRole("listbox", { name: "图谱节点列表" })).toBeVisible();
    expect(screen.getByRole("option", { name: /转写并添加标点/ })).toBeVisible();

    fireEvent.change(search, { target: { value: "转写并添加标点" } });
    fireEvent.keyDown(search, { key: "Enter" });
    expect(screen.getByRole("heading", { name: "转写并添加标点" })).toBeVisible();
  });

  it("turns physics off after stabilization and disables smooth motion when reduced", () => {
    const network = createFakeNetworkFactory();
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })));

    render(<GraphCanvas networkFactory={network.factory} />);
    const [, , options] = network.factory.mock.calls[0] ?? [];
    expect(options?.edges?.smooth).toBe(false);
    network.emitStabilized();
    expect(network.latestNetwork?.setOptions).toHaveBeenCalledWith({
      physics: { enabled: false },
    });
    vi.unstubAllGlobals();
  });

  it("derives general/scenario mastery bands and a PRE remediation plan without writes", () => {
    const profile: LearningProfileSnapshot = {
      version: 1,
      generalMastery: {
        "CAP-TARGET": 0.65,
        "CAP-MASTERED": 0.9,
      },
      scenarioMastery: {
        "CAP-UNLEARNED::SCN-001": 0.2,
      },
      attempts: [],
      lastMode: null,
      lastScenario: "SCN-001",
      lastUnit: null,
      lastNode: null,
    };
    const graphEngine: GraphEngine = {
      neighborhood: vi.fn(),
      remediationPlan: vi.fn(() => ({
        targetNodeId: "CAP-TARGET",
        cycleDetected: false,
        steps: [
          {
            nodeId: "CAP-UNLEARNED",
            prerequisiteIds: [],
            mastery: null,
            skipPractice: false,
          },
          {
            nodeId: "CAP-TARGET",
            prerequisiteIds: ["CAP-UNLEARNED"],
            mastery: 0.65,
            skipPractice: false,
          },
          {
            nodeId: "CAP-MASTERED",
            prerequisiteIds: [],
            mastery: 0.9,
            skipPractice: true,
          },
        ],
      })),
    };

    render(
      <ProgressPanel
        graphEngine={graphEngine}
        profileSnapshot={profile}
        targetNodeId="CAP-TARGET"
        scenarioId="SCN-001"
      />,
    );

    expect(screen.getByText("未学习")).toBeVisible();
    expect(screen.getByText("需补强")).toBeVisible();
    expect(screen.getByText("巩固中")).toBeVisible();
    expect(screen.getByText("已掌握")).toBeVisible();
    expect(screen.getByText("按前置关系排序的补强计划")).toBeVisible();
    expect(graphEngine.remediationPlan).toHaveBeenCalledWith(
      "CAP-TARGET",
      expect.any(Function),
    );
  });

  it("does not execute a cyclic PRE plan and gives a recoverable notice", () => {
    const graphEngine: GraphEngine = {
      neighborhood: vi.fn(),
      remediationPlan: vi.fn(() => ({
        targetNodeId: "CAP-TARGET",
        cycleDetected: true,
        steps: [],
      })),
    };

    render(
      <ProgressPanel
        graphEngine={graphEngine}
        profileSnapshot={{
          version: 1,
          generalMastery: {},
          scenarioMastery: {},
          attempts: [],
          lastMode: null,
          lastScenario: null,
          lastUnit: null,
          lastNode: null,
        }}
        targetNodeId="CAP-TARGET"
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("PRE");
    expect(
      screen.queryByText("按前置关系排序的补强计划"),
    ).not.toBeInTheDocument();
  });
});
