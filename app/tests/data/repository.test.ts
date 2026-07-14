// @vitest-environment node

import { describe, expect, it } from "vitest";

import type { RepositoryInput } from "../../src/data/repository";
import { createRepository } from "../../src/data/repository";
import {
  graph,
  scenarios,
  sourceRegistry,
  teachingUnits,
} from "../../src/data/rawData";

const canonicalRepository = createRepository({
  graph,
  scenarios,
  sourceRegistry,
  teachingUnits,
});

const minimalFixture: RepositoryInput = {
  graph: {
    schema_version: "test",
    graph_id: "GRAPH-TEST-001",
    graph_version: "test",
    nodes: [
      {
        id: "CAP-TEST-001",
        label: "Test capability",
        description: "A prerequisite capability used by repository tests.",
        data_types: ["text"],
        type: "CAP",
        status: "published",
        source_refs: ["SRC-TEST-001"],
      },
      {
        id: "KNG-TEST-001",
        label: "Test rule",
        description: "A rule used by repository tests.",
        data_types: ["text"],
        type: "KNG",
        status: "published",
        source_refs: ["SRC-TEST-001"],
        teaching_unit_refs: ["TU-TEST-001"],
      },
    ],
    edges: [
      {
        id: "EDGE-TEST-001",
        source: "CAP-TEST-001",
        target: "KNG-TEST-001",
        relation: "REL",
        label: "Test relation",
        metadata: {},
      },
    ],
  },
  scenarios: [
    {
      schema_version: "test",
      scenario: {
        id: "SCN-TEST-001",
        name: "Test scenario",
        description: "A scenario used by repository tests.",
        supported_data_types: ["text"],
        source_refs: ["SRC-TEST-001"],
        applicable_capability_refs: ["CAP-TEST-001"],
        review_status: "published",
        student_visible: true,
        overrides: [
          {
            base_rule_ref: "KNG-TEST-001",
            source_refs: ["SRC-TEST-001"],
            teaching_unit_ref: "TU-TEST-001",
          },
        ],
      },
    },
  ],
  sourceRegistry: {
    schema_version: "test",
    sources: [
      {
        source_id: "SRC-TEST-001",
        data_type: "text",
        source_kind: "test",
        supported_claim_types: ["test"],
        name: "Test source",
        original_url_or_local_archive: "local://test-source",
        status: "verified",
      },
    ],
  },
  teachingUnits: {
    schema_version: "test",
    student_visible_unit_ids: ["TU-TEST-001"],
    units: [
      {
        id: "TU-TEST-001",
        data_type: "text",
        title: "Test unit",
        learning_objectives: ["Exercise the repository contract."],
        prerequisites: ["CAP-TEST-001"],
        rule_refs: ["KNG-TEST-001"],
        source_refs: ["SRC-TEST-001"],
        exercise: {
          data_version: "test",
          input: {},
          student_action: "Submit a test answer.",
          answer: {},
          evaluation: {},
        },
        review_status: "published",
        student_visible: true,
      },
    ],
  },
};

const makeFixture = (): RepositoryInput => structuredClone(minimalFixture);

const firstOrThrow = <T>(items: T[], label: string): T => {
  const item = items[0];

  if (item === undefined) {
    throw new Error(`Missing ${label} test fixture.`);
  }

  return item;
};

describe("published teaching repository", () => {
  it("exposes exactly the indexed published student-visible units", () => {
    const visibleIds = new Set(teachingUnits.student_visible_unit_ids);
    const consumableUnits = canonicalRepository.listConsumableUnits();

    expect(consumableUnits).toHaveLength(19);
    expect(
      consumableUnits.every(
        (unit) =>
          unit.review_status === "published" &&
          unit.student_visible === true &&
          visibleIds.has(unit.id),
      ),
    ).toBe(true);

    consumableUnits.pop();
    expect(canonicalRepository.listConsumableUnits()).toHaveLength(19);
  });

  it("preserves draft graph state without treating the node as a published course", () => {
    const draft = graph.nodes.find(
      (node) =>
        node.status === "draft" &&
        canonicalRepository.getConsumableUnitsForNode(node.id).length > 0,
    );

    if (draft === undefined) {
      throw new Error("Expected a draft graph node linked to a teaching unit.");
    }

    const linkedUnits = canonicalRepository.getConsumableUnitsForNode(draft.id);

    expect(canonicalRepository.getNode(draft.id)?.status).toBe("draft");
    expect(linkedUnits.length).toBeGreaterThan(0);
    expect(
      linkedUnits.every(
        (unit) =>
          unit.review_status === "published" &&
          unit.student_visible === true &&
          teachingUnits.student_visible_unit_ids.includes(unit.id),
      ),
    ).toBe(true);
  });

  it("validates the canonical visible index and real references", () => {
    expect(canonicalRepository.validate().errors).toEqual([]);
  });

  it("reports a visible-index ID that has no teaching unit", () => {
    const fixture = makeFixture();
    fixture.teachingUnits.student_visible_unit_ids.push("TU-MISSING-001");

    expect(createRepository(fixture).validate().errors).toContain(
      "visible-index: missing teaching-unit TU-MISSING-001",
    );
  });

  it("does not expose a published visible unit omitted from the visible index", () => {
    const fixture = makeFixture();
    fixture.teachingUnits.student_visible_unit_ids = [];
    const repository = createRepository(fixture);

    expect(repository.listConsumableUnits()).toEqual([]);
    expect(repository.getConsumableUnitsForNode("KNG-TEST-001")).toEqual([]);
    expect(repository.validate().errors).toContain(
      "teaching-unit TU-TEST-001: published and student-visible but missing from visible index",
    );
  });

  it("reports duplicate unit, node, source, scenario, and edge IDs", () => {
    const fixture = makeFixture();
    fixture.teachingUnits.units.push(
      structuredClone(firstOrThrow(fixture.teachingUnits.units, "teaching unit")),
    );
    fixture.graph.nodes.push(
      structuredClone(firstOrThrow(fixture.graph.nodes, "graph node")),
    );
    fixture.sourceRegistry.sources.push(
      structuredClone(firstOrThrow(fixture.sourceRegistry.sources, "source")),
    );
    fixture.scenarios.push(
      structuredClone(firstOrThrow(fixture.scenarios, "scenario")),
    );
    fixture.graph.edges.push(
      structuredClone(firstOrThrow(fixture.graph.edges, "graph edge")),
    );

    expect(createRepository(fixture).validate().errors).toEqual(
      expect.arrayContaining([
        "duplicate teaching-unit ID TU-TEST-001",
        "duplicate graph-node ID CAP-TEST-001",
        "duplicate source ID SRC-TEST-001",
        "duplicate scenario ID SCN-TEST-001",
        "duplicate graph-edge ID EDGE-TEST-001",
      ]),
    );
  });

  it("reports missing edge endpoints", () => {
    const fixture = makeFixture();
    const edge = firstOrThrow(fixture.graph.edges, "graph edge");
    edge.source = "CAP-MISSING-001";
    edge.target = "KNG-MISSING-001";

    expect(createRepository(fixture).validate().errors).toEqual(
      expect.arrayContaining([
        "graph-edge EDGE-TEST-001: missing source node CAP-MISSING-001",
        "graph-edge EDGE-TEST-001: missing target node KNG-MISSING-001",
      ]),
    );
  });

  it("reports missing source, rule, and prerequisite references", () => {
    const fixture = makeFixture();
    const unit = firstOrThrow(fixture.teachingUnits.units, "teaching unit");
    unit.source_refs = ["SRC-MISSING-001"];
    unit.rule_refs = ["KNG-MISSING-001"];
    unit.prerequisites = ["CAP-MISSING-001"];

    expect(createRepository(fixture).validate().errors).toEqual(
      expect.arrayContaining([
        "teaching-unit TU-TEST-001: missing source ref SRC-MISSING-001",
        "teaching-unit TU-TEST-001: missing rule ref KNG-MISSING-001",
        "teaching-unit TU-TEST-001: missing prerequisite node CAP-MISSING-001",
      ]),
    );
  });

  it("reports missing source and rule references in extended unit fields", () => {
    const fixture = makeFixture();
    const unit = firstOrThrow(fixture.teachingUnits.units, "teaching unit");
    unit.exercise.reference_audit = {
      source_ref: "SRC-MISSING-NESTED-001",
      rule_refs: ["KNG-MISSING-NESTED-001"],
    };

    expect(createRepository(fixture).validate().errors).toEqual(
      expect.arrayContaining([
        "teaching-unit TU-TEST-001: missing source ref SRC-MISSING-NESTED-001",
        "teaching-unit TU-TEST-001: missing rule ref KNG-MISSING-NESTED-001",
      ]),
    );
  });

  it("reports missing graph teaching-unit references", () => {
    const fixture = makeFixture();
    const ruleNode = fixture.graph.nodes.find((node) => node.id === "KNG-TEST-001");

    if (ruleNode === undefined) {
      throw new Error("Missing graph rule-node test fixture.");
    }

    ruleNode.teaching_unit_refs = ["TU-MISSING-001"];

    expect(createRepository(fixture).validate().errors).toContain(
      "graph-node KNG-TEST-001: missing teaching-unit ref TU-MISSING-001",
    );
  });

  it("reports missing scenario base-rule and teaching-unit references", () => {
    const fixture = makeFixture();
    const scenario = firstOrThrow(fixture.scenarios, "scenario").scenario;
    scenario.overrides = [
      {
        base_rule_ref: "KNG-MISSING-001",
        source_refs: ["SRC-TEST-001"],
        teaching_unit_ref: "TU-MISSING-001",
      },
    ];

    expect(createRepository(fixture).validate().errors).toEqual(
      expect.arrayContaining([
        "scenario SCN-TEST-001: missing base-rule ref KNG-MISSING-001",
        "scenario SCN-TEST-001: missing teaching-unit ref TU-MISSING-001",
      ]),
    );
  });

  it("returns lookup results while keeping edge arrays isolated from callers", () => {
    const repository = createRepository(makeFixture());

    expect(repository.getUnit("TU-TEST-001")?.title).toBe("Test unit");
    expect(repository.getSource("SRC-TEST-001")?.name).toBe("Test source");
    expect(repository.getScenario("SCN-TEST-001")?.name).toBe("Test scenario");

    const outgoing = repository.getOutgoingEdges("CAP-TEST-001");
    const incoming = repository.getIncomingEdges("KNG-TEST-001");
    expect(outgoing).toHaveLength(1);
    expect(incoming).toHaveLength(1);

    outgoing.pop();
    incoming.pop();
    expect(repository.getOutgoingEdges("CAP-TEST-001")).toHaveLength(1);
    expect(repository.getIncomingEdges("KNG-TEST-001")).toHaveLength(1);
  });
});
