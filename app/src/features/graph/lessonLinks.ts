import type { GraphEdge, GraphNode, TeachingUnit } from "../../data/contracts";
import type { DeepReadonly } from "../../data/repository";

/**
 * Minimal graph repository surface needed to resolve safe lesson links.
 * `listConsumableUnits` is deliberately required: it is the authoritative
 * published + student-visible + visible-index gate.
 */
export interface GraphLessonRepository {
  listConsumableUnits(): DeepReadonly<TeachingUnit[]>;
  getNode?(id: string): DeepReadonly<GraphNode> | undefined;
  getIncomingEdges?(id: string): DeepReadonly<GraphEdge[]>;
  getOutgoingEdges?(id: string): DeepReadonly<GraphEdge[]>;
  getConsumableUnitsForNode?(id: string): DeepReadonly<TeachingUnit[]>;
}

export interface ResolveLinkedConsumableUnitsInput {
  repository: GraphLessonRepository;
  nodeId: string;
  incomingEdges?: readonly DeepReadonly<GraphEdge>[];
  outgoingEdges?: readonly DeepReadonly<GraphEdge>[];
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const stringArray = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];

const nodeTeachingUnitRefs = (
  node: DeepReadonly<GraphNode> | undefined,
): string[] => {
  if (node === undefined) {
    return [];
  }

  const record = node as Record<string, unknown>;
  const refs = stringArray(record.teaching_unit_refs);
  const links = record.teaching_unit_links;
  if (Array.isArray(links)) {
    for (const link of links) {
      if (isRecord(link) && typeof link.unit_id === "string") {
        refs.push(link.unit_id);
      }
    }
  }

  return [...new Set(refs)];
};

const unitCapabilityRefs = (
  unit: DeepReadonly<TeachingUnit>,
): readonly string[] => {
  const exercise = (unit as Record<string, unknown>).exercise;
  return isRecord(exercise) ? stringArray(exercise.capability_refs) : [];
};

const isConsumableShape = (unit: DeepReadonly<TeachingUnit>): boolean =>
  unit.review_status === "published" && unit.student_visible === true;

const addSupNeighbor = (
  candidateNodeIds: Set<string>,
  selectedNodeId: string,
  edge: DeepReadonly<GraphEdge>,
): void => {
  if (edge.relation !== "SUP") {
    return;
  }
  if (edge.source === selectedNodeId) {
    candidateNodeIds.add(edge.target);
  } else if (edge.target === selectedNodeId) {
    candidateNodeIds.add(edge.source);
  }
};

/**
 * Returns linked lessons in authoritative repository order.
 *
 * Every candidate ID—whether discovered from a graph-node link, a direct
 * repository query, exercise capability_refs, or a SUP-neighbor node—is
 * intersected with `listConsumableUnits()` before a unit can be returned.
 * Cached graph-link flags and good-looking unindexed records are never a
 * substitute for that index.
 */
export function resolveLinkedConsumableUnits({
  repository,
  nodeId,
  incomingEdges,
  outgoingEdges,
}: ResolveLinkedConsumableUnitsInput): DeepReadonly<TeachingUnit>[] {
  const authoritativeById = new Map<
    string,
    DeepReadonly<TeachingUnit>
  >();
  const authoritativeOrder: string[] = [];

  for (const unit of repository.listConsumableUnits()) {
    if (!isConsumableShape(unit) || authoritativeById.has(unit.id)) {
      continue;
    }
    authoritativeById.set(unit.id, unit);
    authoritativeOrder.push(unit.id);
  }

  const resolvedIncoming =
    incomingEdges ?? repository.getIncomingEdges?.(nodeId) ?? [];
  const resolvedOutgoing =
    outgoingEdges ?? repository.getOutgoingEdges?.(nodeId) ?? [];
  const candidateNodeIds = new Set<string>([nodeId]);
  for (const edge of resolvedIncoming) {
    addSupNeighbor(candidateNodeIds, nodeId, edge);
  }
  for (const edge of resolvedOutgoing) {
    addSupNeighbor(candidateNodeIds, nodeId, edge);
  }

  const linkedUnitIds = new Set<string>();
  for (const candidateNodeId of candidateNodeIds) {
    for (const unitId of nodeTeachingUnitRefs(
      repository.getNode?.(candidateNodeId),
    )) {
      if (authoritativeById.has(unitId)) {
        linkedUnitIds.add(unitId);
      }
    }

    for (const unit of
      repository.getConsumableUnitsForNode?.(candidateNodeId) ?? []) {
      if (authoritativeById.has(unit.id)) {
        linkedUnitIds.add(unit.id);
      }
    }
  }

  for (const [unitId, unit] of authoritativeById) {
    if (
      unitCapabilityRefs(unit).some((capabilityRef) =>
        candidateNodeIds.has(capabilityRef),
      )
    ) {
      linkedUnitIds.add(unitId);
    }
  }

  const resolved: DeepReadonly<TeachingUnit>[] = [];
  for (const unitId of authoritativeOrder) {
    if (!linkedUnitIds.has(unitId)) {
      continue;
    }
    const unit = authoritativeById.get(unitId);
    if (unit !== undefined) {
      resolved.push(unit);
    }
  }
  return resolved;
}
