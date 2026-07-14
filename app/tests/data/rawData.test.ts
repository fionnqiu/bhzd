// @vitest-environment node

import { describe, expect, it } from "vitest";

import type { TeachingUnit } from "../../src/data/contracts";
import {
  graph,
  parseGraphDocument,
  parseScenarioDocument,
  parseSourceRegistryDocument,
  parseTeachingUnitDocument,
  scenarios,
  sourceRegistry,
  teachingUnits,
} from "../../src/data/rawData";

const sharedShapeTeachingUnit: TeachingUnit = {
  id: "TU-TEST-SHARED-SHAPE-001",
  data_type: "text",
  title: "Shared teaching-unit shape",
  learning_objectives: [],
  prerequisites: [],
  rule_refs: [],
  source_refs: [],
  exercise: {
    data_version: "test",
    input: {},
    student_action: "Submit a test answer.",
    answer: {},
    evaluation: {},
  },
  review_status: "draft",
  student_visible: false,
};

const expectUniqueIds = (ids: string[]) => {
  expect(ids).toHaveLength(new Set(ids).size);
};

describe("canonical project data", () => {
  it("loads the reviewed Task 1-5 baseline", () => {
    expect(teachingUnits.units).toHaveLength(19);
    expect(teachingUnits.student_visible_unit_ids).toHaveLength(19);
    expect(graph.nodes).toHaveLength(166);
    expect(graph.edges).toHaveLength(240);
  });

  it("preserves required teaching-unit structure and unique identifiers", () => {
    expectUniqueIds(teachingUnits.units.map((unit) => unit.id));

    for (const unit of teachingUnits.units) {
      expect(unit.id).toMatch(/^TU-/);
      expect(unit.data_type).toEqual(expect.any(String));
      expect(unit.title).toEqual(expect.any(String));
      expect(unit.rule_refs).toEqual(expect.any(Array));
      expect(unit.source_refs).toEqual(expect.any(Array));
      expect(unit.exercise).toEqual(
        expect.objectContaining({
          evaluation: expect.any(Object),
          input: expect.any(Object),
        }),
      );
    }
  });

  it("accepts the shared unit shape without optional legacy identifiers", () => {
    const document = parseTeachingUnitDocument({
      schema_version: "test",
      student_visible_unit_ids: [],
      units: [sharedShapeTeachingUnit],
    });

    expect(document.units[0]?.id).toBe(sharedShapeTeachingUnit.id);
  });

  it("preserves required graph structure and unique identifiers", () => {
    expectUniqueIds(graph.nodes.map((node) => node.id));
    expectUniqueIds(graph.edges.map((edge) => edge.id));

    for (const node of graph.nodes) {
      expect(node).toEqual(
        expect.objectContaining({
          data_types: expect.any(Array),
          description: expect.any(String),
          id: expect.any(String),
          label: expect.any(String),
          source_refs: expect.any(Array),
          type: expect.any(String),
          status: expect.any(String),
        }),
      );
    }

    for (const edge of graph.edges) {
      expect(edge).toEqual(
        expect.objectContaining({
          id: expect.any(String),
          label: expect.any(String),
          metadata: expect.any(Object),
          relation: expect.any(String),
          source: expect.any(String),
          target: expect.any(String),
        }),
      );
    }
  });

  it("loads the source registry and all four canonical scenarios", () => {
    expect(sourceRegistry.schema_version).toEqual(expect.any(String));
    expect(sourceRegistry.sources.length).toBeGreaterThan(0);
    expectUniqueIds(sourceRegistry.sources.map((source) => source.source_id));

    for (const source of sourceRegistry.sources) {
      expect(source.source_id).toMatch(/^SRC-/);
    }

    expect(scenarios).toHaveLength(4);
    expect(scenarios.map(({ scenario }) => scenario.id).sort()).toEqual([
      "SCN-CONTENT-SAFETY-001",
      "SCN-CUSTOMER-SERVICE-001",
      "SCN-IN-VEHICLE-001",
      "SCN-MEDICAL-001",
    ]);
    expectUniqueIds(scenarios.map(({ scenario }) => scenario.id));

    for (const document of scenarios) {
      expect(document.schema_version).toEqual(expect.any(String));
      expect(document.scenario.id).toMatch(/^SCN-/);
    }
  });

  it("rejects malformed canonical documents instead of trusting type casts", () => {
    expect(parseTeachingUnitDocument).toEqual(expect.any(Function));
    expect(parseGraphDocument).toEqual(expect.any(Function));
    expect(parseSourceRegistryDocument).toEqual(expect.any(Function));
    expect(parseScenarioDocument).toEqual(expect.any(Function));

    expect(() => parseTeachingUnitDocument({})).toThrow(/TeachingUnitDocument/);
    expect(() => parseGraphDocument({})).toThrow(/GraphDocument/);
    expect(() => parseSourceRegistryDocument({})).toThrow(/SourceRegistryDocument/);
    expect(() => parseScenarioDocument({})).toThrow(/ScenarioDocument/);
    expect(() =>
      parseTeachingUnitDocument({
        schema_version: "test",
        student_visible_unit_ids: [],
        units: [
          {
            ...sharedShapeTeachingUnit,
            exercise: {
              data_version: "test",
              input: {},
              student_action: "Submit a test answer.",
              answer: {},
            },
          },
        ],
      }),
    ).toThrow(/TeachingUnitDocument/);
  });
});
