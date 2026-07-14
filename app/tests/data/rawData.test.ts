import { describe, expect, it } from "vitest";

import { graph, teachingUnits } from "../../src/data/rawData";

describe("canonical project data", () => {
  it("loads the reviewed Task 1-5 baseline", () => {
    expect(teachingUnits.units).toHaveLength(19);
    expect(teachingUnits.student_visible_unit_ids).toHaveLength(19);
    expect(graph.nodes).toHaveLength(166);
    expect(graph.edges).toHaveLength(240);
  });
});
