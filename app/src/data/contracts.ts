export interface ExtensibleFields {
  [key: string]: unknown;
}

export interface Exercise extends ExtensibleFields {
  exercise_id?: string;
  exercise_type?: string;
  data_version: string;
  input: ExtensibleFields;
  student_action: string;
  answer: ExtensibleFields;
  evaluation: ExtensibleFields;
}

export interface TeachingUnit extends ExtensibleFields {
  id: string;
  data_type: string;
  title: string;
  capability_key?: string;
  goals?: string[];
  learning_objectives: string[];
  prerequisites: string[];
  rule_refs: string[];
  source_refs: string[];
  exercise: Exercise;
  review_status: string;
  student_visible: boolean;
}

export interface TeachingUnitDocument extends ExtensibleFields {
  schema_version: string;
  student_visible_unit_ids: string[];
  units: TeachingUnit[];
}

export interface GraphNode extends ExtensibleFields {
  id: string;
  label: string;
  description: string;
  data_types: string[];
  type: string;
  status: string;
  source_refs: string[];
}

export interface GraphEdge extends ExtensibleFields {
  id: string;
  source: string;
  target: string;
  relation: string;
  label: string;
  metadata: ExtensibleFields;
}

export interface GraphDocument extends ExtensibleFields {
  schema_version: string;
  graph_id: string;
  graph_version: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Scenario extends ExtensibleFields {
  id: string;
  name: string;
  description: string;
  supported_data_types: string[];
  source_refs: string[];
  applicable_capability_refs: string[];
  review_status: string;
  student_visible: boolean;
}

export interface ScenarioDocument extends ExtensibleFields {
  schema_version: string;
  scenario: Scenario;
}

export type ScenarioDocumentCollection = ScenarioDocument[];

export interface SourceRegistry extends ExtensibleFields {
  source_id: string;
  data_type: string;
  source_kind: string;
  supported_claim_types: string[];
  name: string;
  original_url_or_local_archive: string;
  status: string;
}

export interface SourceRegistryDocument extends ExtensibleFields {
  schema_version: string;
  sources: SourceRegistry[];
}
