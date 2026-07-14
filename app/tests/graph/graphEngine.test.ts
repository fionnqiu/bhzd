// @vitest-environment node

import { describe, expect, it } from "vitest";

import type {
  GraphDocument,
  GraphEdge,
  GraphNode,
} from "../../src/data/contracts";
import { graph } from "../../src/data/rawData";
import { createGraphEngine } from "../../src/graph/graphEngine";

const makeNode = (id: string): GraphNode => ({
  id,
  label: id,
  description: `${id} test node`,
  data_types: ["text"],
  type: "CAP",
  status: "draft",
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

const makeGraph = (
  nodes: GraphNode[],
  edges: GraphEdge[],
): GraphDocument => ({
  schema_version: "test",
  graph_id: "GRAPH-TEST-001",
  graph_version: "test",
  nodes,
  edges,
});

const canonicalEngine = createGraphEngine(graph);

describe("graph engine neighborhoods", () => {
  it("returns the canonical one-hop induced neighborhood in graph order", () => {
    const view = canonicalEngine.neighborhood(
      "CAP-AUD-TRANSCRIBE-PUNCT-001",
      1,
    );
    const expectedNodeIds = [
      "CAP-AUD-CONFIG-VALIDATE-001",
      "CAP-AUD-EMOTION-PARALING-001",
      "CAP-AUD-LANGUAGE-DIALECT-001",
      "CAP-AUD-SEGMENT-ALIGN-001",
      "CAP-AUD-TRANSCRIBE-PUNCT-001",
      "CAP-AUD-WAKE-COMMAND-001",
      "CERT-AIT-L5-AUDIO-ANNOTATION-001",
      "KNG-AUD-PUNCTUATION-001",
      "KNG-AUD-TRANSCRIPT-ORTHOGRAPHY-001",
      "RES-AUD-TRANSCRIPT-STYLE-SHEET-001",
      "SCN-MEDICAL-001",
      "TSK-AUD-TRANSCRIPT-ALIGN-001",
    ];

    expect(view.nodes.map(({ id }) => id)).toEqual(expectedNodeIds);
    expect(view.nodeIds).toEqual(new Set(expectedNodeIds));
    expect(view.edges.map(({ id }) => id)).toEqual([
      "EDGE-0002",
      "EDGE-0005",
      "EDGE-0006",
      "EDGE-0007",
      "EDGE-0008",
      "EDGE-0046",
      "EDGE-0049",
      "EDGE-0084",
      "EDGE-0105",
      "EDGE-0133",
      "EDGE-0179",
      "EDGE-0204",
      "EDGE-0206",
      "EDGE-0208",
    ]);
    expect(
      view.edges.every(
        ({ source, target }) =>
          view.nodeIds.has(source) && view.nodeIds.has(target),
      ),
    ).toBe(true);
  });

  it("returns only the target node at depth zero", () => {
    const view = canonicalEngine.neighborhood(
      "CAP-AUD-TRANSCRIBE-PUNCT-001",
      0,
    );

    expect(view.nodes.map(({ id }) => id)).toEqual([
      "CAP-AUD-TRANSCRIBE-PUNCT-001",
    ]);
    expect(view.edges).toEqual([]);
    expect(view.nodeIds).toEqual(
      new Set(["CAP-AUD-TRANSCRIBE-PUNCT-001"]),
    );
  });

  it("reports an unknown neighborhood node with a stable error", () => {
    const readMissingNeighborhood = () =>
      canonicalEngine.neighborhood("CAP-MISSING-001", 1);

    expect(readMissingNeighborhood).toThrowError(
      new Error("Unknown graph node: CAP-MISSING-001"),
    );
    expect(readMissingNeighborhood).toThrowError(
      new Error("Unknown graph node: CAP-MISSING-001"),
    );
  });

  it.each([-1, 1.5, Number.NaN, Number.POSITIVE_INFINITY])(
    "rejects invalid neighborhood depth %s",
    (depth) => {
      expect(() =>
        canonicalEngine.neighborhood(
          "CAP-AUD-TRANSCRIBE-PUNCT-001",
          depth,
        ),
      ).toThrowError(
        new RangeError(
          "Graph neighborhood depth must be a non-negative integer.",
        ),
      );
    },
  );

  it("returns fresh neighborhood array and Set containers", () => {
    const first = canonicalEngine.neighborhood(
      "CAP-AUD-TRANSCRIBE-PUNCT-001",
      1,
    );
    const expectedNodeCount = first.nodes.length;
    const expectedEdgeCount = first.edges.length;
    first.nodes.pop();
    first.edges.length = 0;
    first.nodeIds.clear();

    const second = canonicalEngine.neighborhood(
      "CAP-AUD-TRANSCRIBE-PUNCT-001",
      1,
    );
    expect(second.nodes).toHaveLength(expectedNodeCount);
    expect(second.edges).toHaveLength(expectedEdgeCount);
    expect(second.nodeIds).toHaveLength(expectedNodeCount);
  });
});

describe("graph engine PRE remediation plans", () => {
  it("follows the real incoming PRE chain and puts wake-command last", () => {
    const plan = canonicalEngine.remediationPlan(
      "CAP-AUD-WAKE-COMMAND-001",
      () => 0,
    );

    expect(plan).toEqual({
      targetNodeId: "CAP-AUD-WAKE-COMMAND-001",
      cycleDetected: false,
      steps: [
        {
          nodeId: "CAP-CORE-TASK-SCOPE-001",
          prerequisiteIds: [],
          mastery: 0,
          skipPractice: false,
        },
        {
          nodeId: "CAP-CORE-ASSET-QUALITY-001",
          prerequisiteIds: ["CAP-CORE-TASK-SCOPE-001"],
          mastery: 0,
          skipPractice: false,
        },
        {
          nodeId: "CAP-AUD-CONFIG-VALIDATE-001",
          prerequisiteIds: ["CAP-CORE-ASSET-QUALITY-001"],
          mastery: 0,
          skipPractice: false,
        },
        {
          nodeId: "CAP-AUD-TRANSCRIBE-PUNCT-001",
          prerequisiteIds: ["CAP-AUD-CONFIG-VALIDATE-001"],
          mastery: 0,
          skipPractice: false,
        },
        {
          nodeId: "CAP-AUD-WAKE-COMMAND-001",
          prerequisiteIds: ["CAP-AUD-TRANSCRIBE-PUNCT-001"],
          mastery: 0,
          skipPractice: false,
        },
      ],
    });

    for (const [index, step] of plan.steps.entries()) {
      expect(
        step.prerequisiteIds.every(
          (prerequisiteId) =>
            plan.steps.findIndex(({ nodeId }) => nodeId === prerequisiteId) <
            index,
        ),
      ).toBe(true);
    }
  });

  it("retains mastered prerequisites as skipped explanatory steps", () => {
    const engine = createGraphEngine(
      makeGraph(
        [makeNode("CAP-PRE-001"), makeNode("CAP-TARGET-001")],
        [makeEdge("EDGE-PRE-001", "CAP-PRE-001", "CAP-TARGET-001")],
      ),
    );

    const plan = engine.remediationPlan("CAP-TARGET-001", (nodeId) =>
      nodeId === "CAP-PRE-001" ? 0.8 : 0.79,
    );

    expect(plan.steps).toEqual([
      {
        nodeId: "CAP-PRE-001",
        prerequisiteIds: [],
        mastery: 0.8,
        skipPractice: true,
      },
      {
        nodeId: "CAP-TARGET-001",
        prerequisiteIds: ["CAP-PRE-001"],
        mastery: 0.79,
        skipPractice: false,
      },
    ]);
  });

  it("keeps null mastery as practice-required", () => {
    const engine = createGraphEngine(
      makeGraph([makeNode("CAP-TARGET-001")], []),
    );

    expect(engine.remediationPlan("CAP-TARGET-001", () => null).steps).toEqual(
      [
        {
          nodeId: "CAP-TARGET-001",
          prerequisiteIds: [],
          mastery: null,
          skipPractice: false,
        },
      ],
    );
  });

  it("uses original graph-node order to break topological ties", () => {
    const engine = createGraphEngine(
      makeGraph(
        [
          makeNode("CAP-PRE-B"),
          makeNode("CAP-PRE-A"),
          makeNode("CAP-TARGET"),
        ],
        [
          makeEdge("EDGE-A", "CAP-PRE-A", "CAP-TARGET"),
          makeEdge("EDGE-B", "CAP-PRE-B", "CAP-TARGET"),
        ],
      ),
    );

    const plan = engine.remediationPlan("CAP-TARGET", () => 0);

    expect(plan.steps.map(({ nodeId }) => nodeId)).toEqual([
      "CAP-PRE-B",
      "CAP-PRE-A",
      "CAP-TARGET",
    ]);
    expect(plan.steps.at(-1)?.prerequisiteIds).toEqual([
      "CAP-PRE-B",
      "CAP-PRE-A",
    ]);
  });

  it("returns no partial executable steps when collected PRE nodes cycle", () => {
    const engine = createGraphEngine(
      makeGraph(
        [makeNode("CAP-CYCLE-A"), makeNode("CAP-CYCLE-B")],
        [
          makeEdge("EDGE-CYCLE-A", "CAP-CYCLE-A", "CAP-CYCLE-B"),
          makeEdge("EDGE-CYCLE-B", "CAP-CYCLE-B", "CAP-CYCLE-A"),
        ],
      ),
    );

    expect(engine.remediationPlan("CAP-CYCLE-B", () => 0)).toEqual({
      targetNodeId: "CAP-CYCLE-B",
      steps: [],
      cycleDetected: true,
    });
  });

  it("ignores non-PRE relations when collecting prerequisites", () => {
    const engine = createGraphEngine(
      makeGraph(
        [
          makeNode("CAP-RELATED"),
          makeNode("CAP-PREREQUISITE"),
          makeNode("CAP-TARGET"),
        ],
        [
          makeEdge("EDGE-RELATED", "CAP-RELATED", "CAP-TARGET", "REL"),
          makeEdge(
            "EDGE-PREREQUISITE",
            "CAP-PREREQUISITE",
            "CAP-TARGET",
          ),
        ],
      ),
    );

    const plan = engine.remediationPlan("CAP-TARGET", () => 0);

    expect(plan.steps.map(({ nodeId }) => nodeId)).toEqual([
      "CAP-PREREQUISITE",
      "CAP-TARGET",
    ]);
    expect(plan.steps.at(-1)?.prerequisiteIds).toEqual([
      "CAP-PREREQUISITE",
    ]);
  });

  it("calls the mastery callback exactly once for each collected node", () => {
    const calls = new Map<string, number>();

    const plan = canonicalEngine.remediationPlan(
      "CAP-AUD-WAKE-COMMAND-001",
      (nodeId) => {
        calls.set(nodeId, (calls.get(nodeId) ?? 0) + 1);
        return 0;
      },
    );

    expect(calls.size).toBe(plan.steps.length);
    expect([...calls.values()]).toEqual([1, 1, 1, 1, 1]);
  });

  it("reports an unknown remediation target with a stable error", () => {
    const readMissingPlan = () =>
      canonicalEngine.remediationPlan("CAP-MISSING-001", () => 0);

    expect(readMissingPlan).toThrowError(
      new Error("Unknown graph node: CAP-MISSING-001"),
    );
    expect(readMissingPlan).toThrowError(
      new Error("Unknown graph node: CAP-MISSING-001"),
    );
  });

  it("returns fresh remediation step and prerequisite containers", () => {
    const first = canonicalEngine.remediationPlan(
      "CAP-AUD-WAKE-COMMAND-001",
      () => 0,
    );
    const expectedStepIds = first.steps.map(({ nodeId }) => nodeId);
    const dependentStep = first.steps.at(-1);
    if (dependentStep === undefined) {
      throw new Error("Missing remediation-step isolation fixture.");
    }
    dependentStep.prerequisiteIds.push("CAP-POLLUTION-001");
    first.steps.shift();

    const second = canonicalEngine.remediationPlan(
      "CAP-AUD-WAKE-COMMAND-001",
      () => 0,
    );
    expect(second.steps.map(({ nodeId }) => nodeId)).toEqual(expectedStepIds);
    expect(second.steps.at(-1)?.prerequisiteIds).toEqual([
      "CAP-AUD-TRANSCRIBE-PUNCT-001",
    ]);
  });

  it("does not mutate the graph input while building or querying indexes", () => {
    const input = makeGraph(
      [makeNode("CAP-PRE-001"), makeNode("CAP-TARGET-001")],
      [makeEdge("EDGE-PRE-001", "CAP-PRE-001", "CAP-TARGET-001")],
    );
    const before = structuredClone(input);
    const engine = createGraphEngine(input);

    engine.neighborhood("CAP-TARGET-001", 1);
    engine.remediationPlan("CAP-TARGET-001", () => 0);

    expect(input).toEqual(before);
  });
});
