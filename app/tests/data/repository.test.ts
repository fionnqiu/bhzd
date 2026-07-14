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

const firstOrThrow = <T>(items: readonly T[], label: string): T => {
  const item = items[0];

  if (item === undefined) {
    throw new Error(`Missing ${label} test fixture.`);
  }

  return item;
};

const appendTwoCopies = <T>(items: T[], label: string): void => {
  const original = firstOrThrow(items, label);
  items.push(structuredClone(original), structuredClone(original));
};

const unsupportedRepositoryValues: Array<{
  label: string;
  create: () => unknown;
}> = [
  { label: "Map", create: () => new Map([["key", "value"]]) },
  { label: "Set", create: () => new Set(["value"]) },
  { label: "Date", create: () => new Date("2026-07-14T00:00:00.000Z") },
  { label: "Uint8Array", create: () => new Uint8Array([1]) },
  { label: "function", create: () => () => "unsupported" },
];

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

    expect(Object.isFrozen(consumableUnits)).toBe(true);
    expect(Reflect.set(consumableUnits, "length", 0)).toBe(false);
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
    appendTwoCopies(fixture.teachingUnits.units, "teaching unit");
    appendTwoCopies(fixture.graph.nodes, "graph node");
    appendTwoCopies(fixture.sourceRegistry.sources, "source");
    appendTwoCopies(fixture.scenarios, "scenario");
    appendTwoCopies(fixture.graph.edges, "graph edge");
    fixture.teachingUnits.student_visible_unit_ids.push(
      "TU-TEST-001",
      "TU-TEST-001",
    );

    const errors = createRepository(fixture).validate().errors;
    const expectedErrors = [
      "duplicate teaching-unit ID TU-TEST-001",
      "duplicate graph-node ID CAP-TEST-001",
      "duplicate source ID SRC-TEST-001",
      "duplicate scenario ID SCN-TEST-001",
      "duplicate graph-edge ID EDGE-TEST-001",
      "duplicate visible-index teaching-unit ID TU-TEST-001",
    ];

    for (const expectedError of expectedErrors) {
      expect(errors.filter((error) => error === expectedError)).toHaveLength(1);
    }
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
    unit.exercise.asset_authorization = {
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

  it("ignores repository-like names inside learner payloads", () => {
    const fixture = makeFixture();
    const unit = firstOrThrow(fixture.teachingUnits.units, "teaching unit");
    unit.exercise.input = {
      source_ref: "SRC-LEARNER-PAYLOAD-001",
      rule_refs: ["KNG-LEARNER-PAYLOAD-001"],
      prerequisites: ["CAP-LEARNER-PAYLOAD-001"],
    };
    unit.exercise.answer = {
      source_refs: ["SRC-ANSWER-PAYLOAD-001"],
      rule_ref: "KNG-ANSWER-PAYLOAD-001",
    };
    unit.exercise.evaluation.diagnostic_rules = [
      {
        submission: {
          prerequisite: "CAP-SUBMISSION-PAYLOAD-001",
        },
      },
    ];

    expect(createRepository(fixture).validate().errors).toEqual([]);
  });

  it("does not skip learner-like paths nested below provenance metadata", () => {
    const fixture = makeFixture();
    const unit = firstOrThrow(fixture.teachingUnits.units, "teaching unit");
    unit.provenance_metadata = {
      exercise: {
        input: {
          source_ref: "SRC-MISSING-METADATA-INPUT-001",
        },
        evaluation: {
          diagnostic_rules: [
            {
              submission: {
                source_ref: "SRC-MISSING-METADATA-SUBMISSION-001",
              },
            },
          ],
        },
      },
    };

    expect(createRepository(fixture).validate().errors).toEqual(
      expect.arrayContaining([
        "teaching-unit TU-TEST-001: missing source ref SRC-MISSING-METADATA-INPUT-001",
        "teaching-unit TU-TEST-001: missing source ref SRC-MISSING-METADATA-SUBMISSION-001",
      ]),
    );
  });

  it("handles self-referential and mutually referential arrays", () => {
    const fixture = makeFixture();
    const unit = firstOrThrow(fixture.teachingUnits.units, "teaching unit");
    const selfReferential: unknown[] = [];
    const left: unknown[] = [];
    const right: unknown[] = [];
    selfReferential.push(selfReferential);
    left.push(right);
    right.push(left);
    unit.exercise.cyclic_metadata = [selfReferential, left, right];

    const repository = createRepository(fixture);

    expect(repository.validate().errors).toEqual([]);
  });

  it.each(unsupportedRepositoryValues)(
    "rejects unsupported $label values with a stable path and type",
    ({ label, create }) => {
      const fixture = makeFixture();
      const unit = firstOrThrow(fixture.teachingUnits.units, "teaching unit");
      unit.exercise.unsupported_value = create();

      expect(() => createRepository(fixture)).toThrowError(
        new TypeError(
          `Unsupported repository input at $.teachingUnits.units[0].exercise.unsupported_value: ${label}`,
        ),
      );
    },
  );

  it("rejects an unsupported value stored in an enumerable array property", () => {
    const fixture = makeFixture();
    const unit = firstOrThrow(fixture.teachingUnits.units, "teaching unit");
    const metadata: unknown[] = [];
    Object.defineProperty(metadata, "extra", {
      configurable: true,
      enumerable: true,
      value: new Map([["key", "value"]]),
      writable: true,
    });
    unit.exercise.array_metadata = metadata;

    expect(() => createRepository(fixture)).toThrowError(
      new TypeError(
        "Unsupported repository input at $.teachingUnits.units[0].exercise.array_metadata.extra: Map",
      ),
    );
  });

  it("rejects enumerable plain-object accessors without evaluating them", () => {
    const fixture = makeFixture();
    const unit = firstOrThrow(fixture.teachingUnits.units, "teaching unit");
    const metadata: Record<string, unknown> = {};
    let getterCalls = 0;
    Object.defineProperty(metadata, "secret", {
      configurable: true,
      enumerable: true,
      get: () => {
        getterCalls += 1;
        return new Map([["key", "value"]]);
      },
    });
    unit.exercise.object_accessor = metadata;

    expect(() => createRepository(fixture)).toThrowError(
      new TypeError(
        "Unsupported repository input at $.teachingUnits.units[0].exercise.object_accessor.secret: accessor",
      ),
    );
    expect(getterCalls).toBe(0);
  });

  it("rejects enumerable array accessors without evaluating them", () => {
    const fixture = makeFixture();
    const unit = firstOrThrow(fixture.teachingUnits.units, "teaching unit");
    const metadata: unknown[] = [];
    let getterCalls = 0;
    Object.defineProperty(metadata, "extra", {
      configurable: true,
      enumerable: true,
      get: () => {
        getterCalls += 1;
        return "secret";
      },
    });
    unit.exercise.array_accessor = metadata;

    expect(() => createRepository(fixture)).toThrowError(
      new TypeError(
        "Unsupported repository input at $.teachingUnits.units[0].exercise.array_accessor.extra: accessor",
      ),
    );
    expect(getterCalls).toBe(0);
  });

  it.each([
    {
      label: "throwing ownKeys trap",
      create: () =>
        new Proxy(
          {},
          {
            ownKeys: () => {
              throw new Error("proxy trap leaked");
            },
          },
        ),
    },
    {
      label: "revoked proxy",
      create: () => {
        const revocable = Proxy.revocable({}, {});
        revocable.revoke();
        return revocable.proxy;
      },
    },
  ])("wraps a $label inspection failure with its repository path", ({ create }) => {
    const fixture = makeFixture();
    const unit = firstOrThrow(fixture.teachingUnits.units, "teaching unit");
    unit.exercise.proxy_failure = create();

    expect(() => createRepository(fixture)).toThrowError(
      new TypeError(
        "Failed to inspect repository input at $.teachingUnits.units[0].exercise.proxy_failure.",
      ),
    );
  });

  it("documents that structuredClone drops enumerable symbol-keyed properties", () => {
    const fixture = makeFixture();
    const unit = firstOrThrow(fixture.teachingUnits.units, "teaching unit");
    const metadata: Record<string, unknown> = {};
    Object.defineProperty(metadata, Symbol("ignored"), {
      enumerable: true,
      value: new Map([["key", "value"]]),
    });
    unit.exercise.symbol_metadata = metadata;

    expect(createRepository(fixture).validate().errors).toEqual([]);
  });

  it("wraps structured-clone failures in a stable repository TypeError", () => {
    const fixture = makeFixture();
    const unit = firstOrThrow(fixture.teachingUnits.units, "teaching unit");
    unit.exercise.clone_failure = new Proxy({ safe: true }, {});

    expect(() => createRepository(fixture)).toThrowError(
      new TypeError("Failed to clone repository input after plain-data validation."),
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

  it("snapshots input before building indexes and validation", () => {
    const fixture = makeFixture();
    const repository = createRepository(fixture);
    const capability = firstOrThrow(fixture.graph.nodes, "graph node");
    const unit = firstOrThrow(fixture.teachingUnits.units, "teaching unit");
    const source = firstOrThrow(fixture.sourceRegistry.sources, "source");
    const scenario = firstOrThrow(fixture.scenarios, "scenario").scenario;
    const edge = firstOrThrow(fixture.graph.edges, "graph edge");
    capability.id = "CAP-MUTATED-001";
    unit.id = "TU-MUTATED-001";
    unit.review_status = "draft";
    source.source_id = "SRC-MUTATED-001";
    scenario.id = "SCN-MUTATED-001";
    edge.target = "CAP-MUTATED-001";
    fixture.teachingUnits.student_visible_unit_ids.length = 0;

    expect(repository.getNode("CAP-TEST-001")?.id).toBe("CAP-TEST-001");
    expect(repository.getUnit("TU-TEST-001")?.id).toBe("TU-TEST-001");
    expect(repository.getSource("SRC-TEST-001")?.source_id).toBe("SRC-TEST-001");
    expect(repository.getScenario("SCN-TEST-001")?.id).toBe("SCN-TEST-001");
    expect(repository.getOutgoingEdges("CAP-TEST-001")[0]?.target).toBe(
      "KNG-TEST-001",
    );
    expect(repository.listConsumableUnits().map(({ id }) => id)).toEqual([
      "TU-TEST-001",
    ]);
    expect(repository.getConsumableUnitsForNode("KNG-TEST-001")).toHaveLength(1);
    expect(repository.validate().errors).toEqual([]);
  });

  it("deep-freezes objects returned by direct getters", () => {
    const repository = createRepository(makeFixture());
    const node = repository.getNode("CAP-TEST-001");
    const unit = repository.getUnit("TU-TEST-001");
    const source = repository.getSource("SRC-TEST-001");
    const scenario = repository.getScenario("SCN-TEST-001");

    if (
      node === undefined ||
      unit === undefined ||
      source === undefined ||
      scenario === undefined
    ) {
      throw new Error("Missing immutable getter fixture.");
    }

    expect(Object.isFrozen(node)).toBe(true);
    expect(Object.isFrozen(node.source_refs)).toBe(true);
    expect(Object.isFrozen(unit)).toBe(true);
    expect(Object.isFrozen(unit.exercise)).toBe(true);
    expect(Object.isFrozen(unit.exercise.input)).toBe(true);
    expect(Object.isFrozen(source)).toBe(true);
    expect(Object.isFrozen(source.supported_claim_types)).toBe(true);
    expect(Object.isFrozen(scenario)).toBe(true);
    expect(Object.isFrozen(scenario.source_refs)).toBe(true);
    expect(Reflect.set(node, "id", "CAP-MUTATED-001")).toBe(false);
    expect(Reflect.set(unit, "review_status", "draft")).toBe(false);
    expect(Reflect.set(source, "source_id", "SRC-MUTATED-001")).toBe(false);
    expect(Reflect.set(scenario, "id", "SCN-MUTATED-001")).toBe(false);
  });

  it("deep-freezes collection containers and their edge and unit elements", () => {
    const repository = createRepository(makeFixture());

    expect(repository.getUnit("TU-TEST-001")?.title).toBe("Test unit");
    expect(repository.getSource("SRC-TEST-001")?.name).toBe("Test source");
    expect(repository.getScenario("SCN-TEST-001")?.name).toBe("Test scenario");

    const outgoing = repository.getOutgoingEdges("CAP-TEST-001");
    const incoming = repository.getIncomingEdges("KNG-TEST-001");
    const units = repository.listConsumableUnits();
    const linkedUnits = repository.getConsumableUnitsForNode("KNG-TEST-001");
    expect(outgoing).toHaveLength(1);
    expect(incoming).toHaveLength(1);
    expect(Object.isFrozen(outgoing)).toBe(true);
    expect(Object.isFrozen(incoming)).toBe(true);
    expect(Object.isFrozen(units)).toBe(true);
    expect(Object.isFrozen(linkedUnits)).toBe(true);

    const edge = firstOrThrow(outgoing, "outgoing edge");
    const unit = firstOrThrow(units, "consumable unit");
    expect(Object.isFrozen(edge)).toBe(true);
    expect(Object.isFrozen(edge.metadata)).toBe(true);
    expect(Object.isFrozen(unit)).toBe(true);
    expect(Reflect.set(edge, "target", "CAP-MUTATED-001")).toBe(false);
    expect(Reflect.set(unit, "review_status", "draft")).toBe(false);
    expect(Reflect.set(outgoing, "length", 0)).toBe(false);
    expect(Reflect.set(units, "length", 0)).toBe(false);
    expect(repository.getOutgoingEdges("CAP-TEST-001")).toHaveLength(1);
    expect(repository.getIncomingEdges("KNG-TEST-001")).toHaveLength(1);
    expect(repository.listConsumableUnits()).toHaveLength(1);
    expect(repository.getConsumableUnitsForNode("KNG-TEST-001")).toHaveLength(1);
    expect(repository.validate().errors).toEqual([]);
  });
});
