import { describe, expect, it } from "vitest";

import type {
  GraphEdge,
  GraphNode,
  TeachingUnit,
} from "../../src/data/contracts";
import {
  resolveLinkedConsumableUnits,
  type GraphLessonRepository,
} from "../../src/features/graph/lessonLinks";

const makeNode = (
  id: string,
  additions: Record<string, unknown> = {},
): GraphNode => ({
  id,
  label: id,
  description: `${id} description`,
  data_types: ["text"],
  type: id.startsWith("TSK") ? "TSK" : "CAP",
  status: "draft",
  source_refs: [],
  ...additions,
});

const makeUnit = (
  id: string,
  capabilityRefs: string[] = [],
): TeachingUnit => ({
  id,
  data_type: "text",
  title: id,
  learning_objectives: ["objective"],
  prerequisites: [],
  rule_refs: [],
  source_refs: [],
  exercise: {
    data_version: "1.0.0",
    input: {},
    student_action: "submit",
    answer: {},
    evaluation: {},
    capability_refs: capabilityRefs,
  },
  review_status: "published",
  student_visible: true,
});

const supEdge: GraphEdge = {
  id: "EDGE-SUP",
  source: "CAP-TARGET",
  target: "TSK-NEIGHBOR",
  relation: "SUP",
  label: "支撑",
  metadata: {},
};

describe("resolveLinkedConsumableUnits", () => {
  it("resolves indexed direct node links and capability_refs without trusting cached link flags", () => {
    const direct = makeUnit("TU-DIRECT");
    const capability = makeUnit("TU-CAPABILITY", ["CAP-TARGET"]);
    const unrelated = makeUnit("TU-UNRELATED", ["CAP-OTHER"]);
    const target = makeNode("CAP-TARGET", {
      teaching_unit_refs: [direct.id],
      teaching_unit_links: [
        {
          unit_id: direct.id,
          consumable: false,
          review_status: "draft",
          student_visible: false,
          in_student_visible_index: false,
        },
      ],
    });
    const repository: GraphLessonRepository = {
      listConsumableUnits: () => [direct, capability, unrelated],
      getNode: (id) => (id === target.id ? target : undefined),
    };

    expect(
      resolveLinkedConsumableUnits({ repository, nodeId: target.id }).map(
        ({ id }) => id,
      ),
    ).toEqual([direct.id, capability.id]);
  });

  it("treats SUP-neighbor nodes as candidates for indexed task lesson links", () => {
    const taskLesson = makeUnit("TU-SUP-TASK");
    const target = makeNode("CAP-TARGET");
    const task = makeNode("TSK-NEIGHBOR", {
      teaching_unit_links: [{ unit_id: taskLesson.id }],
    });
    const nodes = new Map([target, task].map((node) => [node.id, node]));
    const repository: GraphLessonRepository = {
      listConsumableUnits: () => [taskLesson],
      getNode: (id) => nodes.get(id),
      getOutgoingEdges: (id) => (id === target.id ? [supEdge] : []),
    };

    expect(
      resolveLinkedConsumableUnits({ repository, nodeId: target.id }).map(
        ({ id }) => id,
      ),
    ).toEqual([taskLesson.id]);
  });

  it("intersects a malicious narrow direct query with the authoritative consumable index", () => {
    const indexed = makeUnit("TU-INDEXED");
    const unindexed = makeUnit("TU-PUBLISHED-VISIBLE-BUT-UNINDEXED");
    const target = makeNode("CAP-TARGET", {
      teaching_unit_refs: [indexed.id, unindexed.id],
    });
    const repository: GraphLessonRepository = {
      listConsumableUnits: () => [indexed],
      getNode: (id) => (id === target.id ? target : undefined),
      getConsumableUnitsForNode: () => [indexed, unindexed],
    };

    const result = resolveLinkedConsumableUnits({
      repository,
      nodeId: target.id,
      incomingEdges: [],
      outgoingEdges: [],
    });

    expect(result.map(({ id }) => id)).toEqual([indexed.id]);
    expect(result).not.toContain(unindexed);
  });

  it("ignores unrelated and non-SUP edges when deriving neighboring candidates", () => {
    const unrelated = makeUnit("TU-UNRELATED");
    const unrelatedNode = makeNode("TSK-UNRELATED", {
      teaching_unit_refs: [unrelated.id],
    });
    const repository: GraphLessonRepository = {
      listConsumableUnits: () => [unrelated],
      getNode: (id) => (id === unrelatedNode.id ? unrelatedNode : undefined),
    };

    expect(
      resolveLinkedConsumableUnits({
        repository,
        nodeId: "CAP-TARGET",
        outgoingEdges: [
          { ...supEdge, relation: "REL", target: unrelatedNode.id },
          { ...supEdge, id: "EDGE-OTHER", source: "CAP-OTHER", target: unrelatedNode.id },
        ],
      }),
    ).toEqual([]);
  });
});
