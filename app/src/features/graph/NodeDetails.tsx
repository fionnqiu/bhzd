import type { GraphEdge, GraphNode, TeachingUnit } from "../../data/contracts";
import type { DeepReadonly } from "../../data/repository";
import {
  resolveLinkedConsumableUnits,
  type GraphLessonRepository,
} from "./lessonLinks";

/**
 * The graph canvas normally supplies already-resolved relation and lesson
 * arrays.  Keeping the repository optional lets this panel also be used on
 * its own while still allowing it to enforce the canonical publication gate
 * when a repository is available.
 */
export interface NodeDetailsRepository extends GraphLessonRepository {}

export interface NodeDetailsProps {
  node?: DeepReadonly<GraphNode> | null;
  incomingEdges?: DeepReadonly<GraphEdge[]>;
  outgoingEdges?: DeepReadonly<GraphEdge[]>;
  getNode?(nodeId: string): DeepReadonly<GraphNode> | undefined;
  /**
   * Legacy compatibility input. It is intentionally never trusted for lesson
   * launch because it cannot prove membership in the repository's visible
   * index. Pass `repository` to enable verified lesson buttons.
   */
  consumableUnits?: DeepReadonly<TeachingUnit[]>;
  repository?: NodeDetailsRepository;
  onOpenUnit?(unit: DeepReadonly<TeachingUnit>): void;
  /** Alias used by standalone consumers; `onOpenUnit` remains preferred. */
  onOpenLesson?(unit: DeepReadonly<TeachingUnit>): void;
}

type RelationDirection = "incoming" | "outgoing";

interface RelationItem {
  direction: RelationDirection;
  edge: DeepReadonly<GraphEdge>;
}

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
  repository,
  onOpenUnit,
  onOpenLesson,
}: NodeDetailsProps) {
  if (node === null || node === undefined || typeof node.id !== "string") {
    return emptyState("请选择图谱节点以查看真实状态、关系和可学习课程。");
  }

  const explicitNode = getNode?.(node.id);
  const repositoryNode = repository?.getNode?.(node.id);

  // A repository-backed selection must be resolved by either its repository
  // or the explicit graph-document resolver. This keeps stale selections
  // recoverable while supporting injected graph fixtures/documents.
  if (
    repository?.getNode !== undefined &&
    repositoryNode === undefined &&
    explicitNode === undefined
  ) {
    return emptyState("未找到该节点；请从图谱节点列表重新选择。");
  }

  const resolvedGetNode = (
    nodeId: string,
  ): DeepReadonly<GraphNode> | undefined =>
    getNode?.(nodeId) ??
    repository?.getNode?.(nodeId) ??
    (nodeId === node.id ? node : undefined);
  const resolvedIncoming =
    incomingEdges ?? repository?.getIncomingEdges?.(node.id) ?? [];
  const resolvedOutgoing =
    outgoingEdges ?? repository?.getOutgoingEdges?.(node.id) ?? [];
  const incomingItems = relationList("incoming", resolvedIncoming);
  const outgoingItems = relationList("outgoing", resolvedOutgoing);
  const lessonRepository: GraphLessonRepository | undefined =
    repository === undefined
      ? undefined
      : {
          listConsumableUnits: () => repository.listConsumableUnits(),
          getNode: resolvedGetNode,
          getIncomingEdges:
            repository.getIncomingEdges === undefined
              ? undefined
              : (nodeId) => repository.getIncomingEdges?.(nodeId) ?? [],
          getOutgoingEdges:
            repository.getOutgoingEdges === undefined
              ? undefined
              : (nodeId) => repository.getOutgoingEdges?.(nodeId) ?? [],
          getConsumableUnitsForNode:
            repository.getConsumableUnitsForNode === undefined
              ? undefined
              : (nodeId) =>
                  repository.getConsumableUnitsForNode?.(nodeId) ?? [],
        };
  const units =
    lessonRepository === undefined
      ? []
      : resolveLinkedConsumableUnits({
          repository: lessonRepository,
          nodeId: node.id,
          incomingEdges: resolvedIncoming,
          outgoingEdges: resolvedOutgoing,
        });
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
      <h2 id="graph-node-title" aria-live="polite">
        {node.label}
      </h2>
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
          <p>
            {repository === undefined
              ? "无法验证课程发布索引，暂不开放课程。"
              : "此节点暂时没有通过发布门槛的课程。"}
          </p>
        )}
      </section>
    </section>
  );
}
