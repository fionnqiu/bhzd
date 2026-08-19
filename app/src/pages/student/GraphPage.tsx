/**
 * 能力图谱页（PRD-01 §5 + v3.0 §7.3.3 配色）。
 *
 * 关键决策（为什么）：
 * - 搜索/数据类型筛选在前端作用于已加载的全图：筛选若每次回源会
 *   反复触发 166 节点重布局，既慢又闪；overview 单请求后本地过滤可满足
 *   局部渲染 ≤500ms 的预算（PRD-01 §5.2）。局部模式走 /api/graph/subgraph
 *   限制节点规模，路径模式走 /api/graph/pre-path。
 * - 布局稳定一次后关闭物理引擎：持续力导向模拟既耗 CPU 又让节点飘移，
 *   读图体验差；后续 setData 用同步 stabilize 补一次布局即可。
 * - CAP 节点颜色只由 mastery_status 决定（绿实心=已掌握/橙描边=待加强/
 *   红描边=初学），与 MasteryBadge 同一口径，
 *   学生跨页看到的颜色语义必须一致。
 * - 支持 ?node= 深链（对话页/诊断页跳转）：图数据就绪后自动打开节点抽屉。
 */
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Network } from "vis-network/standalone";
import { api } from "../../api/client";
import type {
  GraphNode,
  GraphNodeDetail,
  GraphOverview,
  PrePathResponse,
} from "../../api/types";
import {
  Button,
  Card,
  Drawer,
  EmptyState,
  ErrorState,
  MasteryBadge,
  PageHeader,
  SearchInput,
  Select,
  Spinner,
  Tabs,
  Tag,
  useToast,
} from "../../components";
import { dataTypeLabel, errMsg, nodeLabel } from "./shared";

type ViewMode = "full" | "local" | "path";

const TYPE_LABELS: Record<string, string> = { CAP: "能力" };

/** CAP 节点掌握度配色（v3.0 §7.3.3：已掌握=绿实心，待加强=橙描边，初学=红描边） */
function masteryNodeStyle(node: GraphNode): {
  background: string;
  border: string;
  borderWidth: number;
  fontColor: string;
} {
  if (node.mastery_status === "mastered") {
    return { background: "#16a34a", border: "#15803d", borderWidth: 1, fontColor: "#ffffff" };
  }
  if (node.mastery_status === "weak") {
    return { background: "#fff7ed", border: "#ea580c", borderWidth: 3, fontColor: "#0f172a" };
  }
  // 初学（含无记录，后端 overview 对无记录 CAP 同样给 beginner）
  return { background: "#fef2f2", border: "#dc2626", borderWidth: 3, fontColor: "#0f172a" };
}

interface VisNodeShape {
  id: string;
  label: string;
  title: string;
  color: { background: string; border: string };
  borderWidth: number;
  font: { color: string; size: number };
}

interface VisEdgeShape {
  id: string;
  from: string;
  to: string;
  color: string;
  width: number;
  arrows?: string;
}

/**
 * Server graph data stays compatible while learner-facing views omit every
 * non-CAP record and relation without a reachable student workflow.
 */
function hideLazyScenarioData(graph: GraphOverview): GraphOverview {
  // The student graph keeps only actionable capabilities and prerequisite links.
  const nodes = graph.nodes.filter((node) => node.type === "CAP");
  const ids = new Set(nodes.map((node) => node.id));
  return {
    nodes,
    edges: graph.edges.filter(
      (edge) => edge.relation === "PRE" && ids.has(edge.source) && ids.has(edge.target),
    ),
  };
}

/** 组装 vis-network 数据；highlight 为路径模式需强调的节点集合 */
function toVisData(
  nodes: GraphNode[],
  edges: GraphOverview["edges"],
  highlight: Set<string> | null,
): { nodes: VisNodeShape[]; edges: VisEdgeShape[] } {
  const visNodes = nodes.map((node) => {
    const base =
      node.type === "CAP"
        ? masteryNodeStyle(node)
        : {
            background: "#ffffff",
            border: "#94a3b8",
            borderWidth: 2,
            fontColor: "#0f172a",
          };
    const isHl = highlight?.has(node.id) ?? false;
    return {
      id: node.id,
      label: nodeLabel(node),
      title: nodeLabel(node),
      color: isHl
        ? { background: "#4f46e5", border: "#3730a3" }
        : { background: base.background, border: base.border },
      borderWidth: isHl ? 3 : base.borderWidth,
      font: { color: isHl ? "#ffffff" : base.fontColor, size: 12 },
    };
  });
  const visEdges = edges.map((edge) => {
    // 路径模式只强调路径上的 PRE 边（前置链才是学习顺序的依据）
    const isHl =
      highlight !== null &&
      highlight.has(edge.source) &&
      highlight.has(edge.target) &&
      edge.relation === "PRE";
    return {
      id: edge.id,
      from: edge.source,
      to: edge.target,
      color: isHl ? "#dc2626" : edge.relation === "PRE" ? "#f59e0b" : "#cbd5e1",
      width: isHl ? 3 : 1,
      arrows: edge.relation === "PRE" ? "to" : undefined,
    };
  });
  return { nodes: visNodes, edges: visEdges };
}

/** vis 的 Node/Edge 类型苛刻，数据是我们自己构造的结构子集，集中做一次断言 */
function asVisPayload(data: { nodes: VisNodeShape[]; edges: VisEdgeShape[] }) {
  return data as unknown as Parameters<Network["setData"]>[0];
}

const DATA_TYPE_OPTIONS = [
  { value: "", label: "全部类型" },
  { value: "text", label: "文本" },
  { value: "image", label: "图像" },
  { value: "audio", label: "语音" },
  { value: "video", label: "视频" },
];

export default function GraphPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const [searchParams] = useSearchParams();

  const [q, setQ] = useState("");
  const [dataType, setDataType] = useState("");
  const [mode, setMode] = useState<ViewMode>("full");

  const [overview, setOverview] = useState<GraphOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 局部模式：中心节点 + 子图数据
  const [centerId, setCenterId] = useState("");
  const [subgraphData, setSubgraphData] = useState<GraphOverview | null>(null);
  // 路径模式：目标能力 + 跳过已掌握开关 + 路径结果
  const [targetId, setTargetId] = useState("");
  const [skipMastered, setSkipMastered] = useState(true);
  const [pathData, setPathData] = useState<PrePathResponse | null>(null);
  const [pathLoading, setPathLoading] = useState(false);

  // 节点抽屉
  const [drawerNodeId, setDrawerNodeId] = useState<string | null>(null);
  const [detail, setDetail] = useState<GraphNodeDetail | null>(null);
  const [creating, setCreating] = useState(false);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const networkRef = useRef<Network | null>(null);
  const [netReady, setNetReady] = useState(false);
  const deepLinkHandled = useRef(false);

  /** 全图拉取（登录后 CAP 节点叠加 mastery_status/mastery_score） */
  const loadOverview = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.get<GraphOverview>("/api/graph/overview", undefined, { signal });
      if (!signal?.aborted) setOverview(response);
    } catch (err) {
      if (!signal?.aborted) setError(errMsg(err));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadOverview(controller.signal);
    return () => controller.abort();
  }, [loadOverview]);

  /** 打开节点抽屉（点击画布节点 / 前置 chips / ?node= 深链共用） */
  const openNode = useCallback(
    async (nodeId: string, signal?: AbortSignal) => {
      setDrawerNodeId(nodeId);
      setDetail(null);
      try {
        const response = await api.get<GraphNodeDetail>(`/api/graph/nodes/${nodeId}`, undefined, {
          signal,
        });
        if (!signal?.aborted) setDetail(response);
      } catch (err) {
        if (!signal?.aborted) {
          toast.error(errMsg(err));
          setDrawerNodeId(null);
        }
      }
    },
    [toast],
  );
  // 画布 click 回调挂在 Network 实例上（只注册一次），经 ref 取最新 openNode 防闭包过期
  const openNodeRef = useRef(openNode);
  openNodeRef.current = openNode;

  // 画布生命周期：容器挂载后才创建（首帧 loading 态容器未渲染，[] 依赖会错过），
  // 卸载/重试时销毁；首次布局稳定后关闭物理引擎（见文件头注释）
  const canvasVisible = !loading && !error;
  useEffect(() => {
    if (!canvasVisible || !containerRef.current) return;
    const network = new Network(
      containerRef.current,
      { nodes: [], edges: [] },
      {
        nodes: { shape: "dot", size: 14 },
        edges: { smooth: { enabled: true, type: "continuous", roundness: 0.4 } },
        physics: {
          stabilization: { iterations: 150 },
          barnesHut: { gravitationalConstant: -2800, springLength: 120 },
        },
        interaction: { hover: true },
      },
    );
    networkRef.current = network;
    network.once("stabilizationIterationsDone", () => {
      network.setOptions({ physics: { enabled: false } });
    });
    network.on("click", (params?: { nodes?: (string | number)[] }) => {
      const nodeId = params?.nodes?.[0];
      if (typeof nodeId === "string") openNodeRef.current(nodeId);
    });
    setNetReady(true);
    return () => {
      network.destroy();
      networkRef.current = null;
      setNetReady(false);
    };
  }, [canvasVisible]);

  /** Full graph search is limited to learner-relevant dimensions. */
  const filtered = useMemo(() => {
    if (!overview) return { nodes: [] as GraphNode[], edges: [] as GraphOverview["edges"] };
    let nodes = hideLazyScenarioData(overview).nodes;
    const visibleGraph = hideLazyScenarioData(overview);
    const keyword = q.trim().toLowerCase();
    if (keyword) {
      nodes = nodes.filter((node) =>
        `${node.id} ${nodeLabel(node)} ${node.description ?? ""}`.toLowerCase().includes(keyword),
      );
    }
    if (dataType) {
      nodes = nodes.filter((node) => (node.data_types ?? []).includes(dataType));
    }
    const ids = new Set(nodes.map((n) => n.id));
    return {
      nodes,
      edges: visibleGraph.edges.filter((e) => ids.has(e.source) && ids.has(e.target)),
    };
  }, [overview, q, dataType]);

  // 局部模式：中心节点变化 → 拉子图（depth=2，控制节点规模保 500ms 预算）
  useEffect(() => {
    if (mode !== "local" || !centerId) return;
    const controller = new AbortController();
    api
      .get<GraphOverview>(
        "/api/graph/subgraph",
        { node_id: centerId, depth: 2 },
        { signal: controller.signal },
      )
      .then((res) => {
        if (!controller.signal.aborted) setSubgraphData(res);
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          toast.error(errMsg(err));
          setSubgraphData({ nodes: [], edges: [] });
        }
      });
    return () => controller.abort();
  }, [mode, centerId, toast]);

  // 路径模式：目标/开关变化 → 拉 PRE 补强路径（后端拓扑排序，无环保证）
  useEffect(() => {
    if (mode !== "path" || !targetId) return;
    const controller = new AbortController();
    setPathLoading(true);
    api
      .get<PrePathResponse>(
        "/api/graph/pre-path",
        {
          target_id: targetId,
          skip_mastered: skipMastered ? 1 : 0,
        },
        { signal: controller.signal },
      )
      .then((res) => {
        if (!controller.signal.aborted) setPathData(res);
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          toast.error(errMsg(err));
          setPathData(null);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setPathLoading(false);
      });
    return () => controller.abort();
  }, [mode, targetId, skipMastered, toast]);

  const pathHighlight = useMemo(
    () => (mode === "path" && pathData ? new Set(pathData.path.map((p) => p.id)) : null),
    [mode, pathData],
  );

  /** 当前画布数据：全图=筛选结果；局部=子图；路径=全图+高亮 */
  const canvasData = useMemo(() => {
    if (mode === "local") return subgraphData ? hideLazyScenarioData(subgraphData) : { nodes: [], edges: [] };
    if (mode === "path") return overview ? hideLazyScenarioData(overview) : { nodes: [], edges: [] };
    return filtered;
  }, [mode, filtered, subgraphData, overview]);

  // 数据/高亮变化 → 同步画布；同步 stabilize 一次让新节点落位（不重启持续模拟）
  useEffect(() => {
    const network = networkRef.current;
    if (!netReady || !network) return;
    network.setData(asVisPayload(toVisData(canvasData.nodes, canvasData.edges, pathHighlight)));
    try {
      network.stabilize(80);
    } catch {
      /* stabilize 在物理已关闭+空数据时可能抛错，忽略即可（首帧已稳定） */
    }
  }, [netReady, canvasData, pathHighlight]);

  // ?node= 深链：图数据就绪后打开一次（对话页/诊断页跳入口径）
  useEffect(() => {
    const nodeParam = searchParams.get("node");
    if (nodeParam && overview && !deepLinkHandled.current) {
      const controller = new AbortController();
      deepLinkHandled.current = true;
      void openNode(nodeParam, controller.signal);
      return () => controller.abort();
    }
  }, [overview, searchParams, openNode]);

  // 进入局部模式时给一个合理默认中心：优先薄弱 CAP，其次任意 CAP
  useEffect(() => {
    if (mode === "local" && !centerId && overview) {
      const weak = overview.nodes.find((n) => n.type === "CAP" && n.mastery_status === "weak");
      const anyCap = overview.nodes.find((n) => n.type === "CAP");
      const fallback = weak ?? anyCap ?? overview.nodes[0];
      if (fallback) setCenterId(fallback.id);
    }
  }, [mode, centerId, overview]);

  const capOptions = useMemo(
    () =>
      (overview?.nodes ?? [])
        .filter((n) => n.type === "CAP")
        .map((n) => ({ value: n.id, label: nodeLabel(n) })),
    [overview],
  );

  const overviewNodeById = useMemo(
    () => new Map((overview?.nodes ?? []).map((n) => [n.id, n])),
    [overview],
  );

  /** 节点抽屉「生成练习」：以该能力快速建任务（学生手动动作，无需确认门） */
  const quickCreateTask = async () => {
    if (!detail) return;
    setCreating(true);
    try {
      // Creation and content generation are separate server-side operations;
      // the graph action only needs to return a task id quickly.
      const task = await api.post<{ task_id: string }>("/api/tasks/start-learning", {
        cap_node_id: detail.id,
        generate_content: true,
      });
      toast.success("学习任务已创建");
      navigate(`/tasks/${task.task_id}`);
    } catch (err) {
      toast.error(errMsg(err));
      setCreating(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="能力图谱"
      />

      {/* 工具栏：搜索 + 筛选 + 视图模式（PRD-01 §5.1） */}
      <Card className="mb-4">
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-3">
            <SearchInput
              value={q}
              onChange={setQ}
              placeholder="搜索能力 / 知识 / 任务"
              aria-label="图谱搜索"
            />
            <Select
              aria-label="数据类型筛选"
              value={dataType}
              options={DATA_TYPE_OPTIONS}
              onChange={(e) => setDataType(e.target.value)}
            />
          </div>
          <div className="flex items-center justify-between flex-wrap gap-3">
            {/* Scope the scrollbar treatment to graph view tabs; the shared Tabs
                component is also used by teacher and RAG workflows. */}
            <div className="graph-view-mode-tabs">
              <Tabs
                tabs={[
                  { key: "full", label: "全图" },
                  { key: "local", label: "局部" },
                  { key: "path", label: "路径" },
                ]}
                active={mode}
                onChange={(key) => setMode(key as ViewMode)}
              />
            </div>
            {mode === "local" ? (
              <Select
                aria-label="局部中心节点"
                style={{ width: 260 }}
                value={centerId}
                options={capOptions}
                placeholder="选择中心能力"
                onChange={(e) => setCenterId(e.target.value)}
              />
            ) : null}
            {mode === "path" ? (
              <div className="flex items-center gap-3">
                <Select
                  aria-label="目标能力"
                  style={{ width: 260 }}
                  value={targetId}
                  options={capOptions}
                  placeholder="选择目标能力"
                  onChange={(e) => setTargetId(e.target.value)}
                />
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={skipMastered}
                    onChange={(e) => setSkipMastered(e.target.checked)}
                  />
                  跳过已掌握
                </label>
              </div>
            ) : null}
          </div>
        </div>
      </Card>

      {/* 图例：类型色板 + 掌握度三色（v3.0 §7.3.3） */}
      <div className="flex items-center gap-3 flex-wrap text-xs text-secondary mb-3">
        <span className="flex items-center gap-1">
          <i style={dotStyle("#16a34a")} /> 已掌握
        </span>
        <span className="flex items-center gap-1">
          <i style={dotStyle("#fff7ed", "#ea580c")} /> 待加强
        </span>
        <span className="flex items-center gap-1">
          <i style={dotStyle("#fef2f2", "#dc2626")} /> 初学
        </span>
        <span className="text-muted">|</span>
        <span className="flex items-center gap-1">
          <i style={dotStyle("#ffffff", "#94a3b8")} /> 能力
        </span>
        <span className="text-muted">|</span>
        <span style={{ color: "#f59e0b" }}>→ 前置关系</span>
      </div>

      {error ? (
        <ErrorState message={error} onRetry={loadOverview} />
      ) : loading ? (
        <div className="loading-block">
          <Spinner large /> 正在加载图谱…
        </div>
      ) : (
        <>
          <div
            ref={containerRef}
            className="card"
            style={{ height: 560, overflow: "hidden" }}
            aria-label="能力图谱画布"
          />
          {canvasData.nodes.length === 0 ? (
            <EmptyState title="没有匹配的节点" hint="试试更换关键词或放宽筛选条件" />
          ) : null}
        </>
      )}

      {/* 路径面板：拓扑序（基础在前）+ 跳过清单 */}
      {mode === "path" ? (
        <Card title="前置学习路径" className="mt-4">
          {pathLoading ? (
            <div className="loading-block">
              <Spinner /> 正在计算路径…
            </div>
          ) : !targetId ? (
            <p className="text-sm text-secondary">
              先选择一个目标能力，系统会给出从基础到目标的学习顺序。
            </p>
          ) : !pathData || pathData.path.length === 0 ? (
            <EmptyState title="暂无可展示的路径" hint="该能力可能没有前置要求，或已全部被跳过" />
          ) : (
            <>
              <ol className="flex flex-col gap-2">
                {pathData.path.map((step, index) => {
                  const node = overviewNodeById.get(step.id);
                  return (
                    <li key={step.id} className="flex items-center gap-3">
                      <span className="badge badge-primary">{index + 1}</span>
                      <button
                        type="button"
                        className="text-sm"
                        style={{
                          background: "none",
                          border: "none",
                          padding: 0,
                          color: "var(--color-primary)",
                        }}
                        onClick={() => openNode(step.id)}
                      >
                        {step.name}
                      </button>
                      {node?.type === "CAP" ? (
                        <MasteryBadge score={node.mastery_score ?? null} />
                      ) : (
                        <Tag>{TYPE_LABELS[step.type ?? ""] ?? step.type}</Tag>
                      )}
                    </li>
                  );
                })}
              </ol>
              {pathData.skipped_mastered.length > 0 ? (
                <p className="text-xs text-muted mt-3">
                  已跳过 {pathData.skipped_mastered.length} 项已掌握能力
                </p>
              ) : null}
            </>
          )}
        </Card>
      ) : null}

      {/* 能力详情只保留说明、掌握度、前置关系和可达的练习入口。 */}
      <Drawer
        open={drawerNodeId !== null}
        title={detail ? nodeLabel(detail) : "节点详情"}
        onClose={() => setDrawerNodeId(null)}
      >
        {detail === null ? (
          <div className="loading-block">
            <Spinner /> 加载中…
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2 flex-wrap">
              <Tag>{TYPE_LABELS[detail.type] ?? detail.type}</Tag>
              {(detail.data_types ?? []).map((dt) => (
                <Tag key={dt}>{dataTypeLabel(dt)}</Tag>
              ))}
            </div>
            <div>
              <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                节点说明
              </h3>
              <p className="text-sm text-secondary">{detail.description ?? "暂无说明"}</p>
            </div>
            {detail.type === "CAP" ? (
              <div>
                <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                  我的掌握度
                </h3>
                {detail.mastery && detail.mastery.length > 0 ? (
                  <div className="flex flex-col gap-2">
                    {detail.mastery.map((record) => (
                      <span
                        key={`${record.score}-${record.updated_at}`}
                        className="flex items-center justify-between gap-2"
                      >
                        <span className="text-sm text-secondary">当前掌握度</span>
                        <MasteryBadge score={record.score} />
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-secondary">暂无掌握度记录，完成相关练习后生成。</p>
                )}
              </div>
            ) : null}
            {detail.prerequisites.length > 0 ? (
              <div>
                <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                  前置能力
                </h3>
                <div className="flex items-center gap-2 flex-wrap">
                  {detail.prerequisites.map((node) => (
                    <Button
                      key={node.id}
                      variant="secondary"
                      size="sm"
                      onClick={() => openNode(node.id)}
                    >
                      {nodeLabel(node)}
                    </Button>
                  ))}
                </div>
              </div>
            ) : null}
            {detail.type === "CAP" ? (
              <Button block loading={creating} onClick={quickCreateTask}>
                生成练习
              </Button>
            ) : null}
          </div>
        )}
      </Drawer>
    </div>
  );
}

/** 图例小圆点样式（掌握度三色与类型色板共用） */
function dotStyle(background: string, border?: string): CSSProperties {
  return {
    display: "inline-block",
    width: 10,
    height: 10,
    borderRadius: "50%",
    background,
    border: `2px solid ${border ?? background}`,
  };
}
