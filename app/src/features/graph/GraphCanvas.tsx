import { useEffect, useMemo, useRef, useState } from "react";
import { Network } from "vis-network";
import type { Data, MoveToOptions, Options } from "vis-network";
import "vis-network/styles/vis-network.css";

import type {
  GraphDocument,
  GraphEdge,
  GraphNode,
  TeachingUnit,
} from "../../data/contracts";
import {
  createRepository,
  type DeepReadonly,
} from "../../data/repository";
import {
  graph,
  scenarios,
  sourceRegistry,
  teachingUnits,
} from "../../data/rawData";
import {
  createGraphEngine,
  type GraphEngine,
  type GraphView,
} from "../../graph/graphEngine";
import type { LearningProfileSnapshot } from "../../state/profileStore";
import {
  createGraphVisualEdge,
  createGraphVisualNode,
  graphNetworkMoveOptions,
  graphNetworkOptions,
} from "./graphVisuals";
import type { GraphLessonRepository } from "./lessonLinks";
import { NodeDetails } from "./NodeDetails";

export interface NetworkSelection {
  nodes: Array<string | number>;
}

export type GraphNetworkEvent =
  | "selectNode"
  | "stabilized";

export interface NetworkNodeData {
  id: string;
  label: string;
  [key: string]: unknown;
}

export interface NetworkEdgeData {
  id: string;
  from: string;
  to: string;
  label: string;
  [key: string]: unknown;
}

export interface NetworkData {
  nodes: NetworkNodeData[];
  edges: NetworkEdgeData[];
}

export type NetworkOptions = Options;

export interface NetworkAdapter {
  destroy(): void;
  moveTo(options: MoveToOptions): void;
  on(
    event: GraphNetworkEvent,
    handler: (selection: NetworkSelection) => void,
  ): void;
  setData(data: NetworkData): void;
  setOptions(options: NetworkOptions): void;
}

export type NetworkFactory = (
  container: HTMLElement,
  data: NetworkData,
  options: NetworkOptions,
) => NetworkAdapter;

export type GraphRepository = GraphLessonRepository;

export interface GraphCanvasProps {
  networkFactory?: NetworkFactory;
  graphDocument?: DeepReadonly<GraphDocument>;
  graphEngine?: GraphEngine;
  repository?: GraphRepository;
  profileSnapshot?: LearningProfileSnapshot;
  scenarioId?: string | null;
  initialNodeId?: string | null;
  onSelectNode?(nodeId: string | null): void;
  onOpenUnit?(unit: DeepReadonly<TeachingUnit>): void;
}

const canonicalRepository = createRepository({
  graph,
  scenarios,
  sourceRegistry,
  teachingUnits,
});

const defaultNetworkFactory: NetworkFactory = (container, data, options) => {
  // vis-network requires a real canvas. A no-op adapter keeps the semantic
  // graph controls usable in SSR/jsdom while browsers always use Network.
  if (typeof navigator !== "undefined" && /jsdom/i.test(navigator.userAgent)) {
    return {
      destroy: () => undefined,
      moveTo: () => undefined,
      on: () => undefined,
      setData: () => undefined,
      setOptions: () => undefined,
    };
  }

  const network = new Network(
    container,
    data as unknown as Data,
    options as unknown as Options,
  );

  return {
    destroy: () => network.destroy(),
    moveTo: (nextOptions) => network.moveTo(nextOptions),
    on: (event, handler) => {
      network.on(event, (payload?: { nodes?: Array<string | number> }) => {
        handler({ nodes: payload?.nodes ?? [] });
      });
    },
    setData: (nextData) => network.setData(nextData as unknown as Data),
    setOptions: (nextOptions) => network.setOptions(nextOptions),
  };
};

const getMastery = (
  profileSnapshot: LearningProfileSnapshot | undefined,
  scenarioId: string | null,
  nodeId: string,
): number | null => {
  if (profileSnapshot === undefined) {
    return null;
  }

  if (scenarioId !== null) {
    const scenarioValue =
      profileSnapshot.scenarioMastery[`${nodeId}::${scenarioId}`];
    return scenarioValue ?? null;
  }

  return profileSnapshot.generalMastery[nodeId] ?? null;
};

const asNetworkData = (
  nodes: readonly DeepReadonly<GraphNode>[],
  edges: readonly DeepReadonly<GraphEdge>[],
  profileSnapshot: LearningProfileSnapshot | undefined,
  scenarioId: string | null,
): NetworkData => ({
  nodes: nodes.map((node) =>
    createGraphVisualNode(
      node as GraphNode,
      getMastery(profileSnapshot, scenarioId, node.id),
    ),
  ),
  edges: edges.map((edge) => createGraphVisualEdge(edge as GraphEdge)),
});

const readReducedMotion = (): boolean => {
  const matchMedia =
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia.bind(window)
      : typeof globalThis.matchMedia === "function"
        ? globalThis.matchMedia.bind(globalThis)
        : null;
  return matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
};

const useReducedMotion = (): boolean => {
  const [reduced, setReduced] = useState(readReducedMotion);

  useEffect(() => {
    const matchMedia =
      typeof window !== "undefined" && typeof window.matchMedia === "function"
        ? window.matchMedia.bind(window)
        : typeof globalThis.matchMedia === "function"
          ? globalThis.matchMedia.bind(globalThis)
          : null;
    if (matchMedia === null) {
      return;
    }

    const query = matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);

  return reduced;
};

const nodeMatches = (node: DeepReadonly<GraphNode>, query: string): boolean => {
  if (query.trim() === "") {
    return true;
  }
  const normalized = query.trim().toLocaleLowerCase();
  return [node.id, node.label, node.type, node.description].some((value) =>
    value.toLocaleLowerCase().includes(normalized),
  );
};

export function GraphCanvas({
  networkFactory = defaultNetworkFactory,
  graphDocument = graph,
  graphEngine,
  repository = canonicalRepository,
  profileSnapshot,
  scenarioId = null,
  initialNodeId = null,
  onSelectNode,
  onOpenUnit,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<NetworkAdapter | null>(null);
  const appliedDataRef = useRef<NetworkData | null>(null);
  const reducedMotion = useReducedMotion();
  const reducedMotionRef = useRef(reducedMotion);
  const stabilizedRef = useRef(false);
  const resolvedEngine = useMemo(
    () => graphEngine ?? createGraphEngine(graphDocument),
    [graphDocument, graphEngine],
  );
  const nodeIndex = useMemo(
    () => new Map(graphDocument.nodes.map((node) => [node.id, node] as const)),
    [graphDocument.nodes],
  );
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [localView, setLocalView] = useState<GraphView | null>(null);
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [networkError, setNetworkError] = useState<string | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const selectNodeRef = useRef<(nodeId: string) => void>(() => undefined);
  const initialNodeAppliedRef = useRef<string | null>(null);

  const selectedNode =
    selectedNodeId === null
      ? undefined
      : repository.getNode?.(selectedNodeId) ?? nodeIndex.get(selectedNodeId);
  const currentNodes = localView?.nodes ?? graphDocument.nodes;
  const currentEdges = localView?.edges ?? graphDocument.edges;
  const currentData = useMemo(
    () => asNetworkData(currentNodes, currentEdges, profileSnapshot, scenarioId),
    [currentEdges, currentNodes, profileSnapshot, scenarioId],
  );
  const currentDataRef = useRef(currentData);
  currentDataRef.current = currentData;
  const searchResults = useMemo(
    () => graphDocument.nodes.filter((node) => nodeMatches(node, query)),
    [graphDocument.nodes, query],
  );

  const getNode = (nodeId: string): DeepReadonly<GraphNode> | undefined =>
    repository.getNode?.(nodeId) ?? nodeIndex.get(nodeId);
  const getIncomingEdges = (nodeId: string): DeepReadonly<GraphEdge[]> =>
    repository.getIncomingEdges?.(nodeId) ??
    graphDocument.edges.filter((edge) => edge.target === nodeId);
  const getOutgoingEdges = (nodeId: string): DeepReadonly<GraphEdge[]> =>
    repository.getOutgoingEdges?.(nodeId) ??
    graphDocument.edges.filter((edge) => edge.source === nodeId);

  const selectNode = (nodeId: string) => {
    const node = getNode(nodeId);
    if (node === undefined) {
      setNotice("未找到该节点；请从图谱节点列表重新选择。 ");
      return;
    }

    try {
      setLocalView(resolvedEngine.neighborhood(nodeId, 2));
      setSelectedNodeId(nodeId);
      initialNodeAppliedRef.current = nodeId;
      onSelectNode?.(nodeId);
      networkRef.current?.moveTo(graphNetworkMoveOptions(reducedMotionRef.current));
      setNotice(null);
    } catch {
      setNotice("该节点暂时无法展开；请返回总览后重试。 ");
    }
  };

  selectNodeRef.current = selectNode;

  useEffect(() => {
    if (initialNodeId === null) {
      if (
        initialNodeAppliedRef.current === null &&
        selectedNodeId === null &&
        localView === null
      ) {
        return;
      }
      initialNodeAppliedRef.current = null;
      setSelectedNodeId(null);
      setLocalView(null);
      setNotice(null);
      return;
    }
    if (initialNodeAppliedRef.current === initialNodeId) {
      return;
    }
    initialNodeAppliedRef.current = initialNodeId;
    selectNodeRef.current(initialNodeId);
    // Selection state is controlled only when the external ID changes. A
    // user's local selection must remain usable while the prop stays null.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialNodeId]);

  useEffect(() => {
    const container = containerRef.current;
    if (container === null) {
      return;
    }

    stabilizedRef.current = false;
    setNetworkError(null);
    const initialData = currentDataRef.current;
    let network: NetworkAdapter;
    try {
      network = networkFactory(
        container,
        initialData,
        graphNetworkOptions(reducedMotionRef.current, stabilizedRef.current),
      );
    } catch {
      networkRef.current = null;
      appliedDataRef.current = null;
      setNetworkError(
        "图谱画布暂时无法加载；请使用节点列表继续浏览，稍后重试。",
      );
      return;
    }

    networkRef.current = network;
    appliedDataRef.current = initialData;
    network.on("selectNode", (selection) => {
      const nodeId = selection.nodes[0];
      if (typeof nodeId === "string") {
        selectNodeRef.current(nodeId);
      }
    });
    network.on("stabilized", () => {
      if (networkRef.current !== network) {
        return;
      }
      stabilizedRef.current = true;
      network.setOptions(
        graphNetworkOptions(reducedMotionRef.current, stabilizedRef.current),
      );
    });

    return () => {
      if (networkRef.current === network) {
        networkRef.current = null;
      }
      appliedDataRef.current = null;
      stabilizedRef.current = false;
      network.destroy();
    };
    // The adapter consumes currentData exactly once at construction. Later
    // view/profile changes use the guarded setData effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [networkFactory]);

  useEffect(() => {
    const network = networkRef.current;
    if (network === null || appliedDataRef.current === currentData) {
      return;
    }

    stabilizedRef.current = false;
    network.setOptions(
      graphNetworkOptions(reducedMotionRef.current, stabilizedRef.current),
    );
    network.setData(currentData);
    appliedDataRef.current = currentData;
  }, [currentData]);

  useEffect(() => {
    reducedMotionRef.current = reducedMotion;
    const network = networkRef.current;
    if (network === null) {
      return;
    }

    network.setOptions(graphNetworkOptions(reducedMotion, stabilizedRef.current));
    network.moveTo(graphNetworkMoveOptions(reducedMotion));
  }, [reducedMotion]);

  const handleSearchKeyDown = (
    event: React.KeyboardEvent<HTMLInputElement>,
  ) => {
    if (event.key === "Escape") {
      setQuery("");
      return;
    }
    if (event.key === "Enter" && searchResults[0] !== undefined) {
      event.preventDefault();
      selectNode(searchResults[0].id);
    }
  };

  return (
    <div className="graph-explorer">
      <div className="graph-explorer__toolbar">
        <label htmlFor="graph-node-search">搜索图谱节点</label>
        <input
          id="graph-node-search"
          ref={searchInputRef}
          type="search"
          role="searchbox"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setNotice(null);
          }}
          onKeyDown={handleSearchKeyDown}
          placeholder="输入节点名称、ID 或类型"
        />
        <button
          type="button"
          onClick={() => {
            setQuery("");
            searchInputRef.current?.focus();
          }}
          disabled={query === ""}
        >
          清空搜索
        </button>
      </div>

      <div className="graph-explorer__search-results">
        <p id="graph-node-list-label">节点列表（{searchResults.length}）</p>
        <ul
          role="listbox"
          aria-label="图谱节点列表"
        >
          {searchResults.map((node) => (
            <li key={node.id}>
              <button
                type="button"
                role="option"
                aria-selected={selectedNodeId === node.id}
                onClick={() => selectNode(node.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    selectNode(node.id);
                  }
                }}
              >
                <span>{node.label}</span>
                <small>{node.id} · {node.type}</small>
              </button>
            </li>
          ))}
        </ul>
        {searchResults.length === 0 ? (
          <p role="status">没有匹配节点；清空搜索后可恢复全部节点。</p>
        ) : null}
      </div>

      <p id="graph-canvas-description">
        画布展示当前能力图谱；如需键盘操作或画布不可用，请使用上方节点列表。
      </p>
      <div
        ref={containerRef}
        className="graph-explorer__canvas"
        role="img"
        aria-label="能力图谱可视化"
        aria-describedby="graph-canvas-description"
      />
      {networkError !== null ? <p role="alert">{networkError}</p> : null}

      <div className="graph-explorer__summary" aria-live="polite">
        {localView === null ? (
          <span>总览：{graphDocument.nodes.length} 个节点 · {graphDocument.edges.length} 条边</span>
        ) : (
          <span>局部视图：2 跳 · {localView.nodes.length} 个节点 · {localView.edges.length} 条边</span>
        )}
        {localView !== null ? (
          <button
            type="button"
            onClick={() => {
              initialNodeAppliedRef.current = null;
              setLocalView(null);
              setSelectedNodeId(null);
              onSelectNode?.(null);
              setNotice(null);
            }}
          >
            返回总览
          </button>
        ) : null}
      </div>

      {notice !== null ? <p role="status">{notice}</p> : null}

      {selectedNode === undefined ? (
        <p>选择节点以查看真实状态、关系和可学习课程。</p>
      ) : (
        <NodeDetails
          node={selectedNode}
          incomingEdges={getIncomingEdges(selectedNode.id)}
          outgoingEdges={getOutgoingEdges(selectedNode.id)}
          getNode={getNode}
          repository={repository}
          onOpenUnit={onOpenUnit}
        />
      )}
    </div>
  );
}
