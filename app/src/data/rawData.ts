import graphJson from "../../../data/graph/annotation-capability-graph.json";
import teachingUnitsJson from "../../../data/curriculum/teaching-units.json";
import sourceRegistryJson from "../../../data/sources/source-registry.json";
import medicalJson from "../../../data/scenarios/medical.json";
import customerServiceJson from "../../../data/scenarios/customer-service.json";
import inVehicleJson from "../../../data/scenarios/in-vehicle.json";
import contentSafetyJson from "../../../data/scenarios/content-safety.json";

import type {
  Exercise,
  ExtensibleFields,
  GraphDocument,
  GraphEdge,
  GraphNode,
  Scenario,
  ScenarioDocument,
  ScenarioDocumentCollection,
  SourceRegistry,
  SourceRegistryDocument,
  TeachingUnit,
  TeachingUnitDocument,
} from "./contracts";

const isRecord = (value: unknown): value is ExtensibleFields =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isString = (value: unknown): value is string => typeof value === "string";

const isBoolean = (value: unknown): value is boolean => typeof value === "boolean";

const isArrayOf = <T>(
  value: unknown,
  predicate: (item: unknown) => item is T,
): value is T[] => Array.isArray(value) && value.every(predicate);

const isStringArray = (value: unknown): value is string[] =>
  isArrayOf(value, isString);

const isOptionalString = (value: unknown): value is string | undefined =>
  value === undefined || isString(value);

const isOptionalStringArray = (value: unknown): value is string[] | undefined =>
  value === undefined || isStringArray(value);

const isExercise = (value: unknown): value is Exercise =>
  isRecord(value) &&
  isOptionalString(value.exercise_id) &&
  isOptionalString(value.exercise_type) &&
  isString(value.data_version) &&
  isRecord(value.input) &&
  isString(value.student_action) &&
  isRecord(value.answer) &&
  isRecord(value.evaluation);

const isTeachingUnit = (value: unknown): value is TeachingUnit =>
  isRecord(value) &&
  isString(value.id) &&
  isString(value.data_type) &&
  isString(value.title) &&
  isOptionalString(value.capability_key) &&
  isOptionalStringArray(value.goals) &&
  isStringArray(value.learning_objectives) &&
  isStringArray(value.prerequisites) &&
  isStringArray(value.rule_refs) &&
  isStringArray(value.source_refs) &&
  isExercise(value.exercise) &&
  isString(value.review_status) &&
  isBoolean(value.student_visible);

const isGraphNode = (value: unknown): value is GraphNode =>
  isRecord(value) &&
  isString(value.id) &&
  isString(value.label) &&
  isString(value.description) &&
  isStringArray(value.data_types) &&
  isString(value.type) &&
  isString(value.status) &&
  isStringArray(value.source_refs);

const isGraphEdge = (value: unknown): value is GraphEdge =>
  isRecord(value) &&
  isString(value.id) &&
  isString(value.source) &&
  isString(value.target) &&
  isString(value.relation) &&
  isString(value.label) &&
  isRecord(value.metadata);

const isScenario = (value: unknown): value is Scenario =>
  isRecord(value) &&
  isString(value.id) &&
  isString(value.name) &&
  isString(value.description) &&
  isStringArray(value.supported_data_types) &&
  isStringArray(value.source_refs) &&
  isStringArray(value.applicable_capability_refs) &&
  isString(value.review_status) &&
  isBoolean(value.student_visible);

const isSourceRegistry = (value: unknown): value is SourceRegistry =>
  isRecord(value) &&
  isString(value.source_id) &&
  isString(value.data_type) &&
  isString(value.source_kind) &&
  isStringArray(value.supported_claim_types) &&
  isString(value.name) &&
  isString(value.original_url_or_local_archive) &&
  isString(value.status);

const isTeachingUnitDocument = (value: unknown): value is TeachingUnitDocument =>
  isRecord(value) &&
  isString(value.schema_version) &&
  isStringArray(value.student_visible_unit_ids) &&
  isArrayOf(value.units, isTeachingUnit);

const isGraphDocument = (value: unknown): value is GraphDocument =>
  isRecord(value) &&
  isString(value.schema_version) &&
  isString(value.graph_id) &&
  isString(value.graph_version) &&
  isArrayOf(value.nodes, isGraphNode) &&
  isArrayOf(value.edges, isGraphEdge);

const isSourceRegistryDocument = (value: unknown): value is SourceRegistryDocument =>
  isRecord(value) &&
  isString(value.schema_version) &&
  isArrayOf(value.sources, isSourceRegistry);

const isScenarioDocument = (value: unknown): value is ScenarioDocument =>
  isRecord(value) &&
  isString(value.schema_version) &&
  isScenario(value.scenario);

const parseDocument = <T>(
  value: unknown,
  documentName: string,
  predicate: (candidate: unknown) => candidate is T,
): T => {
  if (!predicate(value)) {
    throw new TypeError(
      `Invalid ${documentName}: canonical data does not match the required structure.`,
    );
  }

  return value;
};

export const parseTeachingUnitDocument = (value: unknown): TeachingUnitDocument =>
  parseDocument(value, "TeachingUnitDocument", isTeachingUnitDocument);

export const parseGraphDocument = (value: unknown): GraphDocument =>
  parseDocument(value, "GraphDocument", isGraphDocument);

export const parseSourceRegistryDocument = (value: unknown): SourceRegistryDocument =>
  parseDocument(value, "SourceRegistryDocument", isSourceRegistryDocument);

export const parseScenarioDocument = (value: unknown): ScenarioDocument =>
  parseDocument(value, "ScenarioDocument", isScenarioDocument);

export const graph: GraphDocument = parseGraphDocument(graphJson);
export const teachingUnits: TeachingUnitDocument =
  parseTeachingUnitDocument(teachingUnitsJson);
export const sourceRegistry: SourceRegistryDocument =
  parseSourceRegistryDocument(sourceRegistryJson);
export const scenarios: ScenarioDocumentCollection = [
  parseScenarioDocument(medicalJson),
  parseScenarioDocument(customerServiceJson),
  parseScenarioDocument(inVehicleJson),
  parseScenarioDocument(contentSafetyJson),
];
