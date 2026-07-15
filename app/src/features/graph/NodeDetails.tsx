import type { GraphEdge, GraphNode, TeachingUnit } from "../../data/contracts";
import type { DeepReadonly, TeachingRepository } from "../../data/repository";

/**
 * The graph canvas normally supplies already-resolved relation and lesson
 * arrays.  Keeping the repository optional lets this panel also be used on
 * its own while still allowing it to enforce the canonical publication gate
 * when a repository is available.
 */
export interface NodeDetailsRepository {
  listConsumableUnits?(): DeepReadonly<TeachingUnit[]>;
  getConsumableUnitsForNode?(id: string): DeepReadonly<TeachingUnit[]>;
  getUnit?(id: string): DeepReadonly<TeachingUnit> | undefined;
  getNode?(id: string): DeepReadonly<GraphNode> | undefined;
  getIncomingEdges?(id: string): DeepReadonly<GraphEdge[]>;
  getOutgoingEdges?(id: string): DeepReadonly<GraphEdge[]>;
}

export interface NodeDetailsProps {
  node?: DeepReadonly<GraphNode> | null;
  incomingEdges?: DeepReadonly<GraphEdge[]>;
  outgoingEdges?: DeepReadonly<GraphEdge[]>;
  getNode?(nodeId: string): DeepReadonly<GraphNode> | undefined;
  /**
   * This array is the GraphCanvas compatibility path and is expected to be a
   * repository-gated, node-associated set.  When `repository` is supplied,
   * its consumable index is authoritative instead.
   */
  consumableUnits?: DeepReadonly<TeachingUnit[]>;
  repository?: NodeDetailsRepository | TeachingRepository;
  onOpenUnit?(unit: DeepReadonly<TeachingUnit>): void;
  /** Alias used by standalone consumers; `onOpenUnit` remains preferred. */
  onOpenLesson?(unit: DeepReadonly<TeachingUnit>): void;
}

type RelationDirection = "incoming" | "outgoing";

interface RelationItem {
  direction: RelationDirection;
  edge: DeepReadonly<GraphEdge>;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

const stringArray = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];

const teachingUnitRefsForNode = (node: DeepReadonly<GraphNode>): string[] => {
  const value = (node as Record<string, unknown>).teaching_unit_refs;
  const refs = stringArray(value);
  const links = (node as Record<string, unknown>).teaching_unit_links;

  if (Array.isArray(links)) {
    for (const link of links) {
      if (isRecord(link) && typeof link.unit_id === "string") {
        refs.push(link.unit_id);
      }
    }
  }

  return [...new Set(refs)];
};

const capabilityRefsForUnit = (
  unit: DeepReadonly<TeachingUnit>,
): readonly string[] => {
  const exercise = (unit as Record<string, unknown>).exercise;
  if (!isRecord(exercise)) {
    return [];
  }
  return stringArray(exercise.capability_refs);
};

const hasConsumableShape = (unit: DeepReadonly<TeachingUnit>): boolean =>
  unit.review_status === "published" && unit.student_visible === true;

const uniqueUnits = (
  units: readonly DeepReadonly<TeachingUnit>[],
): DeepReadonly<TeachingUnit>[] => {
  const byId = new Map<string, DeepReadonly<TeachingUnit>>();
  for (const unit of units) {
    if (!hasConsumableShape(unit) || byId.has(unit.id)) {
      continue;
    }
    byId.set(unit.id, unit);
  }
  return [...byId.values()];
};

/**
 * Resolve only units that are both linked to the selected node and present in
 * the repository's consumable index.  In particular, capability_refs are a
 * valid equivalent link when a CAP node has no direct teaching_unit_refs.
 */
const linkedRepositoryUnits = (
  repository: NodeDetailsRepository | TeachingRepository,
  node: DeepReadonly<GraphNode>,
): DeepReadonly<TeachingUnit>[] => {
  const indexed = repository.listConsumableUnits?.() ?? [];
  const indexedById = new Map(indexed.map((unit) => [unit.id, unit] as const));
  const linkedIds = new Set<string>(teachingUnitRefsForNode(node));

  for (const unit of indexed) {
    if (capabilityRefsForUnit(unit).includes(node.id)) {
      linkedIds.add(unit.id);
    }
  }

  // A narrow repository adapter may expose a direct-link query but not a
  // complete list.  Add those results, then re-gate through the index (or the
  // unit getter) so draft/non-visible/unindexed records cannot become launch
  // buttons.
  for (const unit of repository.getConsumableUnitsForNode?.(node.id) ?? []) {
    linkedIds.add(unit.id);
    if (!indexedById.has(unit.id) && repository.listConsumableUnits === undefined) {
      indexedById.set(unit.id, unit);
    }
  }

  const resolved: DeepReadonly<TeachingUnit>[] = [];
  for (const id of linkedIds) {
    const unit = indexedById.get(id) ?? repository.getUnit?.(id);
    if (unit !== undefined && hasConsumableShape(unit)) {
      // When a list index exists, it is the publication/index authority.  A
      // getter-only adapter is allowed to provide its direct consumable set.
      if (repository.listConsumableUnits !== undefined && !indexedById.has(id)) {
        continue;
      }
      resolved.push(unit);
    }
  }
  return uniqueUnits(resolved);
};

const resolveUnits = (
  repository: NodeDetailsProps["repository"],
  node: DeepReadonly<GraphNode>,
  supplied: readonly DeepReadonly<TeachingUnit>[],
): DeepReadonly<TeachingUnit>[] => {
  if (repository !== undefined) {
    return linkedRepositoryUnits(repository, node);
  }

  // GraphCanvas passes an already-associated consumable set.  Keep that
  // contract while defensively rejecting malformed publication state.
  return uniqueUnits(supplied);
};

const emptyState = (message: string) => (
  <section className="graph-node-details" aria-live="polite">
    <p role="status">{message}</p>
  </section>
);

interface RelationLineProps {
  item: RelationItem;
  relatedNode: DeepReadonly<GraphNode> | undefined;
}

function RelationLine({ item, relatedNode }: RelationLineProps) {
  const endpointId =
    item.direction === "incoming" ? item.edge.source : item.edge.target;
  const endpointLabel = relatedNode?.label ?? endpointId;
  const endpointStatus = relatedNode?.status ?? "未知";
  const endpointType = relatedNode?.type ?? "未知类型";

  return (
    <li>
      <span className="graph-node-details__relation-type">
        {item.edge.relation}
      </span>
      <span> · {item.edge.label} · </span>
      <span>{item.direction === "incoming" ? "来自" : "指向"} </span>
      <strong>{endpointLabel}</strong>
      <span>
        （{endpointType} · 状态：{endpointStatus} · ID：{endpointId}）
      </span>
    </li>
  );
}

const relationList = (
  direction: RelationDirection,
  edges: readonly DeepReadonly<GraphEdge>[],
): RelationItem[] =>
  edges.map((edge) => ({ direction, edge }));

export function NodeDetails({
  node,
  incomingEdges,
  outgoingEdges,
  getNode,
  consumableUnits = [],
  repository,
  onOpenUnit,
  onOpenLesson,
}: NodeDetailsProps) {
  if (node === null || node === undefined || typeof node.id !== "string") {
    return emptyState("请选择图谱节点以查看真实状态、关系和可学习课程。");
  }

  // A repository-backed selection must still exist in that repository.  This
  // turns stale/unknown selections into a recoverable state rather than
  // rendering a fabricated node.
  if (
    repository?.getNode !== undefined &&
    repository.getNode(node.id) === undefined
  ) {
    return emptyState("未找到该节点；请从图谱节点列表重新选择。");
  }

  const resolvedGetNode = getNode ?? repository?.getNode;
  const resolvedIncoming =
    incomingEdges ?? repository?.getIncomingEdges?.(node.id) ?? [];
  const resolvedOutgoing =
    outgoingEdges ?? repository?.getOutgoingEdges?.(node.id) ?? [];
  const incomingItems = relationList("incoming", resolvedIncoming);
  const outgoingItems = relationList("outgoing", resolvedOutgoing);
  const units = resolveUnits(repository, node, consumableUnits);
  const openUnit = onOpenUnit ?? onOpenLesson;

  const renderRelations = (
    heading: string,
    label: string,
    items: readonly RelationItem[],
  ) => (
    <section className="graph-node-details__relations" aria-labelledby={`${label}-title`}>
      <h3 id={`${label}-title`}>{heading}</h3>
      {items.length > 0 ? (
        <ul aria-label={heading}>
          {items.map((item) => (
            <RelationLine
              key={`${item.direction}-${item.edge.id}`}
              item={item}
              relatedNode={resolvedGetNode?.(
                item.direction === "incoming"
                  ? item.edge.source
                  : item.edge.target,
              )}
            />
          ))}
        </ul>
      ) : (
        <p>当前节点没有{heading}。</p>
      )}
    </section>
  );

  const prerequisiteItems = [...incomingItems, ...outgoingItems].filter(
    ({ edge }) => edge.relation === "PRE",
  );
  const relatedItems = [...incomingItems, ...outgoingItems].filter(
    ({ edge }) => edge.relation !== "PRE",
  );

  return (
    <section className="graph-node-details" aria-labelledby="graph-node-title">
      <p className="eyebrow eyebrow--ink">
        {node.type} / {node.id}
      </p>
      <h2 id="graph-node-title">{node.label}</h2>
      <p>{node.description}</p>
      <p className="graph-node-details__status">节点状态：{node.status}</p>

      {renderRelations("入向关系", "graph-node-incoming", incomingItems)}
      {renderRelations("出向关系", "graph-node-outgoing", outgoingItems)}

      {/* Keep the original graph-panel vocabulary as explicit, useful
          summaries while the directional lists above provide typed edges. */}
      <section className="graph-node-details__relations" aria-labelledby="graph-node-prerequisites-title">
        <h3 id="graph-node-prerequisites-title">前置关系</h3>
        {prerequisiteItems.length > 0 ? (
          <ul aria-label="前置关系">
            {prerequisiteItems.map((item) => (
              <RelationLine
                key={`prerequisite-${item.direction}-${item.edge.id}`}
                item={item}
                relatedNode={resolvedGetNode?.(
                  item.direction === "incoming" ? item.edge.source : item.edge.target,
                )}
              />
            ))}
          </ul>
        ) : (
          <p>当前节点没有 PRE 前置关系。</p>
        )}
      </section>

      <section className="graph-node-details__relations" aria-labelledby="graph-node-related-title">
        <h3 id="graph-node-related-title">关联关系</h3>
        {relatedItems.length > 0 ? (
          <ul aria-label="关联关系">
            {relatedItems.map((item) => (
              <RelationLine
                key={`related-${item.direction}-${item.edge.id}`}
                item={item}
                relatedNode={resolvedGetNode?.(
                  item.direction === "incoming" ? item.edge.source : item.edge.target,
                )}
              />
            ))}
          </ul>
        ) : (
          <p>当前节点没有其他关联关系。</p>
        )}
      </section>

      <section className="graph-node-details__lessons" aria-labelledby="graph-node-lessons-title">
        <h3 id="graph-node-lessons-title">可学习课程</h3>
        {units.length > 0 ? (
          <ul aria-label="可学习课程">
            {units.map((unit) => (
              <li key={unit.id}>
                <span>{unit.title}</span>
                <button
                  type="button"
                  aria-label={`开始课程：${unit.title}`}
                  onClick={() => openUnit?.(unit)}
                >
                  开始课程：{unit.title}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p>此节点暂时没有通过发布门槛的课程。</p>
        )}
      </section>
    </section>
  );
}
