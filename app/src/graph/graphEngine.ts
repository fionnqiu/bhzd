import type { GraphDocument, GraphEdge, GraphNode } from "../data/contracts";
import type { DeepReadonly } from "../data/repository";

export interface GraphView {
  nodes: GraphNode[];
  edges: GraphEdge[];
  nodeIds: Set<string>;
}

export interface RemediationStep {
  nodeId: string;
  prerequisiteIds: string[];
  mastery: number | null;
  skipPractice: boolean;
}

export interface RemediationPlan {
  targetNodeId: string;
  steps: RemediationStep[];
  cycleDetected: boolean;
}

export interface GraphEngine {
  neighborhood(nodeId: string, depth: number): GraphView;
  remediationPlan(
    targetNodeId: string,
    getMastery: (nodeId: string) => number | null,
  ): RemediationPlan;
}

const cloneNode = (node: DeepReadonly<GraphNode>): GraphNode => ({
  ...node,
  data_types: [...node.data_types],
  source_refs: [...node.source_refs],
});

const cloneEdge = (edge: DeepReadonly<GraphEdge>): GraphEdge => ({
  ...edge,
  metadata: { ...edge.metadata },
});

const snapshotGraph = (
  graph: DeepReadonly<GraphDocument>,
): GraphDocument => {
  try {
    const snapshot = structuredClone(graph);
    return {
      ...snapshot,
      nodes: snapshot.nodes.map(cloneNode),
      edges: snapshot.edges.map(cloneEdge),
    };
  } catch {
    throw new TypeError("Failed to snapshot graph engine input.");
  }
};

const addEdge = (
  index: Map<string, GraphEdge[]>,
  nodeId: string,
  edge: GraphEdge,
): void => {
  const indexed = index.get(nodeId);
  if (indexed === undefined) {
    index.set(nodeId, [edge]);
    return;
  }

  indexed.push(edge);
};

export const createGraphEngine = (
  graph: DeepReadonly<GraphDocument>,
): GraphEngine => {
  const { nodes, edges } = snapshotGraph(graph);
  const nodeIndex = new Map<string, GraphNode>();
  const nodeOrder = new Map<string, number>();
  const orderedNodeIds: string[] = [];
  const incomingEdges = new Map<string, GraphEdge[]>();
  const outgoingEdges = new Map<string, GraphEdge[]>();

  for (const node of nodes) {
    if (!nodeOrder.has(node.id)) {
      nodeOrder.set(node.id, orderedNodeIds.length);
      orderedNodeIds.push(node.id);
    }
    nodeIndex.set(node.id, node);
  }

  for (const edge of edges) {
    addEdge(outgoingEdges, edge.source, edge);
    addEdge(incomingEdges, edge.target, edge);
  }

  const assertKnownNode = (nodeId: string): void => {
    if (!nodeIndex.has(nodeId)) {
      throw new Error(`Unknown graph node: ${nodeId}`);
    }
  };

  const orderOf = (nodeId: string): number =>
    nodeOrder.get(nodeId) ?? Number.MAX_SAFE_INTEGER;

  const sortByNodeOrder = (nodeIds: string[]): string[] =>
    nodeIds.sort((left, right) => orderOf(left) - orderOf(right));

  const neighborhood = (nodeId: string, depth: number): GraphView => {
    if (!Number.isInteger(depth) || depth < 0) {
      throw new RangeError(
        "Graph neighborhood depth must be a non-negative integer.",
      );
    }
    assertKnownNode(nodeId);

    const visited = new Set<string>([nodeId]);
    let frontier = [nodeId];

    for (let distance = 0; distance < depth && frontier.length > 0; distance += 1) {
      const nextFrontier: string[] = [];

      for (const currentNodeId of frontier) {
        const incidentEdges = [
          ...(incomingEdges.get(currentNodeId) ?? []),
          ...(outgoingEdges.get(currentNodeId) ?? []),
        ];

        for (const edge of incidentEdges) {
          const adjacentNodeId =
            edge.source === currentNodeId ? edge.target : edge.source;
          if (
            nodeIndex.has(adjacentNodeId) &&
            !visited.has(adjacentNodeId)
          ) {
            visited.add(adjacentNodeId);
            nextFrontier.push(adjacentNodeId);
          }
        }
      }

      frontier = nextFrontier;
    }

    const selectedNodes = nodes.filter((node) => visited.has(node.id));
    const nodeIds = new Set(selectedNodes.map((node) => node.id));
    const selectedEdges = edges.filter(
      (edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target),
    );
    const output = structuredClone({
      nodes: selectedNodes,
      edges: selectedEdges,
    });

    return {
      nodes: output.nodes,
      edges: output.edges,
      nodeIds,
    };
  };

  const remediationPlan = (
    targetNodeId: string,
    getMastery: (nodeId: string) => number | null,
  ): RemediationPlan => {
    assertKnownNode(targetNodeId);

    const collectedNodeIds = new Set<string>([targetNodeId]);
    const pending = [targetNodeId];

    while (pending.length > 0) {
      const currentNodeId = pending.pop();
      if (currentNodeId === undefined) {
        break;
      }

      for (const edge of incomingEdges.get(currentNodeId) ?? []) {
        if (
          edge.relation === "PRE" &&
          nodeIndex.has(edge.source) &&
          !collectedNodeIds.has(edge.source)
        ) {
          collectedNodeIds.add(edge.source);
          pending.push(edge.source);
        }
      }
    }

    const prerequisitesByNode = new Map<string, string[]>();
    const indegree = new Map<string, number>();

    for (const collectedNodeId of collectedNodeIds) {
      const prerequisiteIds = new Set<string>();
      for (const edge of incomingEdges.get(collectedNodeId) ?? []) {
        if (
          edge.relation === "PRE" &&
          collectedNodeIds.has(edge.source)
        ) {
          prerequisiteIds.add(edge.source);
        }
      }

      const orderedPrerequisiteIds = sortByNodeOrder([...prerequisiteIds]);
      prerequisitesByNode.set(collectedNodeId, orderedPrerequisiteIds);
      indegree.set(collectedNodeId, orderedPrerequisiteIds.length);
    }

    const ready = orderedNodeIds.filter(
      (candidateId) =>
        collectedNodeIds.has(candidateId) && indegree.get(candidateId) === 0,
    );
    const topologicalOrder: string[] = [];

    const insertReady = (nodeId: string): void => {
      const insertionIndex = ready.findIndex(
        (candidateId) => orderOf(candidateId) > orderOf(nodeId),
      );
      if (insertionIndex === -1) {
        ready.push(nodeId);
      } else {
        ready.splice(insertionIndex, 0, nodeId);
      }
    };

    while (ready.length > 0) {
      const currentNodeId = ready.shift();
      if (currentNodeId === undefined) {
        break;
      }
      topologicalOrder.push(currentNodeId);

      const dependentIds = new Set<string>();
      for (const edge of outgoingEdges.get(currentNodeId) ?? []) {
        if (
          edge.relation === "PRE" &&
          collectedNodeIds.has(edge.target)
        ) {
          dependentIds.add(edge.target);
        }
      }

      for (const dependentId of dependentIds) {
        const nextIndegree = (indegree.get(dependentId) ?? 0) - 1;
        indegree.set(dependentId, nextIndegree);
        if (nextIndegree === 0) {
          insertReady(dependentId);
        }
      }
    }

    if (topologicalOrder.length !== collectedNodeIds.size) {
      return {
        targetNodeId,
        steps: [],
        cycleDetected: true,
      };
    }

    const steps = topologicalOrder.map((nodeId): RemediationStep => {
      const mastery = getMastery(nodeId);
      return {
        nodeId,
        prerequisiteIds: [...(prerequisitesByNode.get(nodeId) ?? [])],
        mastery,
        skipPractice: mastery !== null && mastery >= 0.8,
      };
    });

    return {
      targetNodeId,
      steps,
      cycleDetected: false,
    };
  };

  return Object.freeze({ neighborhood, remediationPlan });
};
