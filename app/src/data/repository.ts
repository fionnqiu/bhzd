import type {
  GraphDocument,
  GraphEdge,
  GraphNode,
  Scenario,
  ScenarioDocumentCollection,
  SourceRegistry,
  SourceRegistryDocument,
  TeachingUnit,
  TeachingUnitDocument,
} from "./contracts";

export interface RepositoryInput {
  graph: GraphDocument;
  scenarios: ScenarioDocumentCollection;
  sourceRegistry: SourceRegistryDocument;
  teachingUnits: TeachingUnitDocument;
}

export interface RepositoryValidationResult {
  errors: string[];
}

export interface TeachingRepository {
  listConsumableUnits(): TeachingUnit[];
  getNode(id: string): GraphNode | undefined;
  getUnit(id: string): TeachingUnit | undefined;
  getSource(id: string): SourceRegistry | undefined;
  getScenario(id: string): Scenario | undefined;
  getIncomingEdges(id: string): GraphEdge[];
  getOutgoingEdges(id: string): GraphEdge[];
  getConsumableUnitsForNode(id: string): TeachingUnit[];
  validate(): RepositoryValidationResult;
}

interface IndexResult<T> {
  byId: Map<string, T>;
  duplicateErrors: string[];
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const walkRecords = (
  root: unknown,
  visit: (record: Record<string, unknown>) => void,
): void => {
  const seen = new WeakSet<object>();

  const walk = (value: unknown): void => {
    if (Array.isArray(value)) {
      for (const item of value) {
        walk(item);
      }
      return;
    }

    if (!isRecord(value) || seen.has(value)) {
      return;
    }

    seen.add(value);
    visit(value);

    for (const nested of Object.values(value)) {
      walk(nested);
    }
  };

  walk(root);
};

const collectStringPropertyValues = (
  root: unknown,
  propertyName: string,
): string[] => {
  const values: string[] = [];

  walkRecords(root, (record) => {
    const candidate = record[propertyName];

    if (typeof candidate === "string") {
      values.push(candidate);
      return;
    }

    if (Array.isArray(candidate)) {
      for (const item of candidate) {
        if (typeof item === "string") {
          values.push(item);
        }
      }
    }
  });

  return values;
};

const unique = (values: string[]): string[] => [...new Set(values)];

const collectReferences = (root: unknown, propertyNames: string[]): string[] =>
  unique(
    propertyNames.flatMap((propertyName) =>
      collectStringPropertyValues(root, propertyName),
    ),
  );

const getTeachingUnitRefs = (node: GraphNode): string[] => {
  const references = collectStringPropertyValues(node, "teaching_unit_refs");
  const links = node.teaching_unit_links;

  if (Array.isArray(links)) {
    for (const link of links) {
      if (isRecord(link) && typeof link.unit_id === "string") {
        references.push(link.unit_id);
      }
    }
  }

  return unique(references);
};

const createIndex = <T>(
  items: T[],
  getId: (item: T) => string,
  entityType: string,
): IndexResult<T> => {
  const byId = new Map<string, T>();
  const duplicateErrors: string[] = [];

  for (const item of items) {
    const id = getId(item);

    if (byId.has(id)) {
      duplicateErrors.push(`duplicate ${entityType} ID ${id}`);
      continue;
    }

    byId.set(id, item);
  }

  return { byId, duplicateErrors };
};

const findDuplicateStrings = (values: string[], entityType: string): string[] => {
  const seen = new Set<string>();
  const reported = new Set<string>();
  const errors: string[] = [];

  for (const value of values) {
    if (seen.has(value) && !reported.has(value)) {
      errors.push(`duplicate ${entityType} ID ${value}`);
      reported.add(value);
    }
    seen.add(value);
  }

  return errors;
};

const addEdge = (
  index: Map<string, GraphEdge[]>,
  nodeId: string,
  edge: GraphEdge,
): void => {
  const existing = index.get(nodeId);

  if (existing === undefined) {
    index.set(nodeId, [edge]);
    return;
  }

  existing.push(edge);
};

export const createRepository = ({
  graph,
  scenarios,
  sourceRegistry,
  teachingUnits,
}: RepositoryInput): TeachingRepository => {
  const unitIndex = createIndex(teachingUnits.units, (unit) => unit.id, "teaching-unit");
  const nodeIndex = createIndex(graph.nodes, (node) => node.id, "graph-node");
  const sourceIndex = createIndex(
    sourceRegistry.sources,
    (source) => source.source_id,
    "source",
  );
  const scenarioIndex = createIndex(
    scenarios.map((document) => document.scenario),
    (scenario) => scenario.id,
    "scenario",
  );
  const edgeIndex = createIndex(graph.edges, (edge) => edge.id, "graph-edge");
  const visibleIds = new Set(teachingUnits.student_visible_unit_ids);
  const outgoingEdges = new Map<string, GraphEdge[]>();
  const incomingEdges = new Map<string, GraphEdge[]>();
  const teachingUnitRefs = new Map<string, string[]>();

  const isConsumable = (unit: TeachingUnit): boolean =>
    unit.review_status === "published" &&
    unit.student_visible === true &&
    visibleIds.has(unit.id);

  for (const edge of graph.edges) {
    addEdge(outgoingEdges, edge.source, edge);
    addEdge(incomingEdges, edge.target, edge);
  }

  for (const node of graph.nodes) {
    if (!teachingUnitRefs.has(node.id)) {
      teachingUnitRefs.set(node.id, getTeachingUnitRefs(node));
    }
  }

  const consumableUnits = [...unitIndex.byId.values()].filter(isConsumable);
  const validationErrors: string[] = [
    ...unitIndex.duplicateErrors,
    ...nodeIndex.duplicateErrors,
    ...sourceIndex.duplicateErrors,
    ...scenarioIndex.duplicateErrors,
    ...edgeIndex.duplicateErrors,
    ...findDuplicateStrings(
      teachingUnits.student_visible_unit_ids,
      "visible-index teaching-unit",
    ),
  ];

  for (const visibleId of visibleIds) {
    const unit = unitIndex.byId.get(visibleId);

    if (unit === undefined) {
      validationErrors.push(`visible-index: missing teaching-unit ${visibleId}`);
    } else if (!isConsumable(unit)) {
      validationErrors.push(
        `visible-index: teaching-unit ${visibleId} is not published and student-visible`,
      );
    }
  }

  for (const unit of unitIndex.byId.values()) {
    if (
      unit.review_status === "published" &&
      unit.student_visible === true &&
      !visibleIds.has(unit.id)
    ) {
      validationErrors.push(
        `teaching-unit ${unit.id}: published and student-visible but missing from visible index`,
      );
    }

    for (const sourceRef of collectReferences(unit, ["source_ref", "source_refs"])) {
      if (!sourceIndex.byId.has(sourceRef)) {
        validationErrors.push(
          `teaching-unit ${unit.id}: missing source ref ${sourceRef}`,
        );
      }
    }

    for (const ruleRef of collectReferences(unit, ["rule_ref", "rule_refs"])) {
      if (!nodeIndex.byId.has(ruleRef)) {
        validationErrors.push(`teaching-unit ${unit.id}: missing rule ref ${ruleRef}`);
      }
    }

    for (const prerequisite of collectReferences(unit, [
      "prerequisite",
      "prerequisites",
    ])) {
      if (!nodeIndex.byId.has(prerequisite)) {
        validationErrors.push(
          `teaching-unit ${unit.id}: missing prerequisite node ${prerequisite}`,
        );
      }
    }
  }

  for (const node of nodeIndex.byId.values()) {
    for (const sourceRef of collectReferences(node, ["source_ref", "source_refs"])) {
      if (!sourceIndex.byId.has(sourceRef)) {
        validationErrors.push(`graph-node ${node.id}: missing source ref ${sourceRef}`);
      }
    }

    const primaryCapabilityRef = node.primary_capability_ref;
    if (
      typeof primaryCapabilityRef === "string" &&
      !nodeIndex.byId.has(primaryCapabilityRef)
    ) {
      validationErrors.push(
        `graph-node ${node.id}: missing node ref ${primaryCapabilityRef} (primary_capability_ref)`,
      );
    }

    const primaryKnowledgeRef = node.primary_knowledge_ref;
    if (
      typeof primaryKnowledgeRef === "string" &&
      !nodeIndex.byId.has(primaryKnowledgeRef)
    ) {
      validationErrors.push(
        `graph-node ${node.id}: missing node ref ${primaryKnowledgeRef} (primary_knowledge_ref)`,
      );
    }

    for (const unitRef of teachingUnitRefs.get(node.id) ?? []) {
      if (!unitIndex.byId.has(unitRef)) {
        validationErrors.push(
          `graph-node ${node.id}: missing teaching-unit ref ${unitRef}`,
        );
      }
    }
  }

  for (const edge of graph.edges) {
    if (!nodeIndex.byId.has(edge.source)) {
      validationErrors.push(
        `graph-edge ${edge.id}: missing source node ${edge.source}`,
      );
    }
    if (!nodeIndex.byId.has(edge.target)) {
      validationErrors.push(
        `graph-edge ${edge.id}: missing target node ${edge.target}`,
      );
    }
  }

  for (const scenario of scenarioIndex.byId.values()) {
    for (const sourceRef of collectReferences(scenario, ["source_ref", "source_refs"])) {
      if (!sourceIndex.byId.has(sourceRef)) {
        validationErrors.push(`scenario ${scenario.id}: missing source ref ${sourceRef}`);
      }
    }

    for (const capabilityRef of scenario.applicable_capability_refs) {
      if (!nodeIndex.byId.has(capabilityRef)) {
        validationErrors.push(
          `scenario ${scenario.id}: missing capability node ${capabilityRef}`,
        );
      }
    }

    for (const baseRuleRef of collectReferences(scenario, ["base_rule_ref"])) {
      if (!nodeIndex.byId.has(baseRuleRef)) {
        validationErrors.push(
          `scenario ${scenario.id}: missing base-rule ref ${baseRuleRef}`,
        );
      }
    }

    const scenarioTeachingUnitRefs = collectReferences(scenario, [
      "teaching_unit_ref",
      "teaching_unit_refs",
    ]);
    for (const unitRef of scenarioTeachingUnitRefs) {
      if (!unitIndex.byId.has(unitRef)) {
        validationErrors.push(
          `scenario ${scenario.id}: missing teaching-unit ref ${unitRef}`,
        );
      }
    }
  }

  return Object.freeze({
    listConsumableUnits: (): TeachingUnit[] => [...consumableUnits],
    getNode: (id: string): GraphNode | undefined => nodeIndex.byId.get(id),
    getUnit: (id: string): TeachingUnit | undefined => unitIndex.byId.get(id),
    getSource: (id: string): SourceRegistry | undefined => sourceIndex.byId.get(id),
    getScenario: (id: string): Scenario | undefined => scenarioIndex.byId.get(id),
    getIncomingEdges: (id: string): GraphEdge[] => [...(incomingEdges.get(id) ?? [])],
    getOutgoingEdges: (id: string): GraphEdge[] => [...(outgoingEdges.get(id) ?? [])],
    getConsumableUnitsForNode: (id: string): TeachingUnit[] =>
      (teachingUnitRefs.get(id) ?? [])
        .map((unitId) => unitIndex.byId.get(unitId))
        .filter((unit): unit is TeachingUnit => unit !== undefined && isConsumable(unit)),
    validate: (): RepositoryValidationResult => ({ errors: [...validationErrors] }),
  });
};
