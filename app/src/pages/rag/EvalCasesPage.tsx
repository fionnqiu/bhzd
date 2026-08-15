/**
 * 已合并的评测集组件：生产用例入口已并入 /admin/rag/search-test。
 *
 * 关键决策（为什么）：
 * - 评测指标卡严格按 PRD-03 §11 五项展示并附中文说明；无样本的指标后端给
 *   null，页面如实显示"—"而不是 0（0 和无数据是两回事）。
 * - 后端评测是同步执行的（run_eval 循环跑完才返回），但保留 running 轮询
 *   兜底：未来改异步后前端不用改契约。
 * - 历史对比来自 GET /api/rag/eval-runs（服务端评测历史，最新在前）；
 *   列表不携带逐用例结果（体积大），展开某次运行时按需拉详情端点，
 *   详情失败则退化为"仅指标"视图。
 */

import { Pencil, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type {
  EvalCase,
  EvalMetrics,
  EvalRun,
  Paginated,
  RagDocument,
} from "../../api/types";
import {
  Button,
  Card,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageHeader,
  Pagination,
  Select,
  StatusBadge,
  Tag,
  Textarea,
  useToast,
  type Column,
} from "../../components";
import {
  clamp,
  DATA_TYPE_OPTIONS,
  errText,
  fmtTime,
} from "./ragShared";
import RagDocumentMultiSelect from "./RagDocumentMultiSelect";

const DEFAULT_LIMIT = 20;
/** 历史对比展示的最近运行条数（服务端列表，最新在前） */
const HISTORY_LIMIT = 10;
/** running 状态轮询兜底：2s × 15 = 30s 上限 */
const POLL_LIMIT = 15;

/** 历史列表项（GET /api/rag/eval-runs；列表不携带 case_results，展开时按需拉详情） */
interface EvalRunListItem {
  id: string;
  status: "running" | "completed" | "failed";
  metrics: EvalMetrics | null;
  created_at?: string;
  finished_at?: string | null;
}

/** PRD-03 §11 五项核心指标（顺序即展示顺序） */
const METRIC_DEFS = [
  { key: "recall_at_k", label: "Recall@K", desc: "TopK 中是否召回目标资料", isLatency: false },
  { key: "citation_accuracy", label: "Citation Accuracy", desc: "引用是否准确", isLatency: false },
  { key: "answer_faithfulness", label: "Answer Faithfulness", desc: "答案是否忠于资料", isLatency: false },
  { key: "refusal_accuracy", label: "Refusal Accuracy", desc: "资料不足时是否拒答", isLatency: false },
  { key: "latency_ms_avg", label: "Latency", desc: "召回与生成耗时（越低越好）", isLatency: true },
] as const;

/** 指标格式化：无样本 → "—"（0 和无数据是两回事）；延迟 → ms；比率 → 百分比 */
function fmtMetric(def: (typeof METRIC_DEFS)[number], metrics: EvalMetrics | null): string {
  const value = metrics ? (metrics[def.key] as number | null) : null;
  if (value === null || value === undefined) return "—";
  return def.isLatency ? `${Math.round(value)}ms` : `${Math.round(value * 100)}%`;
}

/** ✓/✗/— 三态标记（null = 该用例不参与此指标） */
function TriMark({ value }: { value: boolean | null }) {
  if (value === null) return <span className="text-muted">—</span>;
  return value ? <span className="text-success">✓</span> : <span className="text-danger">✗</span>;
}

export default function EvalCasesPage() {
  const toast = useToast();
  const [cases, setCases] = useState<EvalCase[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState<string[]>([]);

  // 新建用例
  const [createOpen, setCreateOpen] = useState(false);
  const [editingCase, setEditingCase] = useState<EvalCase | null>(null);
  const [deletingCase, setDeletingCase] = useState<EvalCase | null>(null);
  const [question, setQuestion] = useState("");
  const [expected, setExpected] = useState("");
  const [mustDocs, setMustDocs] = useState<string[]>([]);
  const [filterDataType, setFilterDataType] = useState("");
  const [docOptions, setDocOptions] = useState<RagDocument[]>([]);
  const [creating, setCreating] = useState(false);

  // 评测运行
  const [running, setRunning] = useState(false);
  const [currentRun, setCurrentRun] = useState<EvalRun | null>(null);
  // 历史对比（服务端数据源）；expanded* 为"点击展开逐用例结果"的按需加载态
  const [history, setHistory] = useState<EvalRunListItem[]>([]);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [expandedRun, setExpandedRun] = useState<EvalRun | null>(null);
  const [expandedLoading, setExpandedLoading] = useState(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<Paginated<EvalCase>>("/api/rag/eval-cases", {
        limit,
        offset,
      }, { signal });
      if (signal?.aborted) return;
      setCases(res.items);
      setTotal(res.total);
    } catch (err) {
      if (!signal?.aborted) setError(errText(err, "评测用例加载失败"));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [offset, limit]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  /** 历史评测列表（服务端数据源，取代旧 localStorage 方案）；失败不阻断主流程 */
  const loadHistory = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await api.get<Paginated<EvalRunListItem>>("/api/rag/eval-runs", {
        limit: HISTORY_LIMIT,
      }, { signal });
      if (signal?.aborted) return;
      setHistory(res.items);
    } catch {
      // 历史对比是辅助面板：加载失败不影响用例管理与评测运行
    }
  }, []);

  // 资料选项（新建用例选必须命中文档）+ 历史评测列表
  useEffect(() => {
    const controller = new AbortController();
    api
      .get<Paginated<RagDocument>>("/api/rag/documents", { limit: 100 }, { signal: controller.signal })
      .then((res) => {
        if (!controller.signal.aborted) setDocOptions(res.items);
      })
      .catch(() => {
        /* 选项加载失败时仍可手建无必须命中的用例 */
      });
    void loadHistory(controller.signal);
    return () => controller.abort();
  }, [loadHistory]);

  /** 展开/收起某次运行的逐用例结果：列表不携带 case_results（体积大），按需拉详情 */
  const toggleRun = async (runId: string) => {
    if (expandedRunId === runId) {
      setExpandedRunId(null);
      setExpandedRun(null);
      return;
    }
    setExpandedRunId(runId);
    setExpandedRun(null);
    setExpandedLoading(true);
    try {
      setExpandedRun(await api.get<EvalRun>(`/api/rag/eval-runs/${runId}`));
    } catch {
      // 详情拉取失败退化为"仅指标"视图（列表项本身已有五项指标可读）
      setExpandedRun(null);
    } finally {
      setExpandedLoading(false);
    }
  };

  // Create and edit share one form so document/filter snapshots remain identical across both flows.
  const saveCase = async () => {
    if (!question.trim()) {
      toast.error("请填写问题");
      return;
    }
    setCreating(true);
    try {
      const payload = {
        question: question.trim(),
        expected_answer: expected.trim() || null,
        must_hit_document_ids: mustDocs,
        must_hit_chunk_ids: [],
        filters: {
          data_type: filterDataType || null,
          published_only: true,
        },
      };
      if (editingCase) {
        await api.patch(`/api/rag/eval-cases/${editingCase.id}`, payload);
        toast.success("评测用例已更新");
      } else {
        await api.post("/api/rag/eval-cases", payload);
        toast.success("评测用例已创建");
      }
      setCreateOpen(false);
      setEditingCase(null);
      setQuestion("");
      setExpected("");
      setMustDocs([]);
      await load();
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setCreating(false);
    }
  };

  /** Prepare a complete local draft so an edit does not accidentally erase existing filters. */
  const openEditCase = (caseItem: EvalCase) => {
    setEditingCase(caseItem);
    setQuestion(caseItem.question);
    setExpected(caseItem.expected_answer ?? "");
    setMustDocs(caseItem.must_hit_document_ids);
    setFilterDataType(String(caseItem.filters.data_type ?? ""));
    setCreateOpen(true);
  };

  const openCreateCase = () => {
    setEditingCase(null);
    setQuestion("");
    setExpected("");
    setMustDocs([]);
    setFilterDataType("");
    setCreateOpen(true);
  };

  const deleteCase = async () => {
    if (!deletingCase) return;
    try {
      await api.delete(`/api/rag/eval-cases/${deletingCase.id}`);
      setChecked((current) => current.filter((id) => id !== deletingCase.id));
      setDeletingCase(null);
      toast.success("评测用例已删除");
      await load();
    } catch (err) {
      toast.error(errText(err, "删除评测用例失败"));
    }
  };

  /** 运行评测：caseIds 为 null 跑全部；同步返回 completed，running 则 2s 轮询兜底 */
  const runEval = async (caseIds: string[] | null) => {
    setRunning(true);
    try {
      let run = await api.post<EvalRun>("/api/rag/eval-runs", {
        case_ids: caseIds && caseIds.length > 0 ? caseIds : null,
      });
      for (let i = 0; run.status === "running" && i < POLL_LIMIT; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        run = await api.get<EvalRun>(`/api/rag/eval-runs/${run.id}`);
      }
      setCurrentRun(run);
      if (run.status === "completed") {
        toast.success(`评测完成（${run.metrics?.case_count ?? 0} 条用例）`);
        // 新运行入库后刷新服务端历史列表（历史对比的数据源）
        void loadHistory();
      } else {
        toast.error(run.status === "failed" ? "评测运行失败" : "评测超时，请稍后查看结果");
      }
    } catch (err) {
      toast.error(errText(err, "评测运行失败"));
    } finally {
      setRunning(false);
    }
  };

  const caseColumns: Column<EvalCase>[] = [
    {
      key: "check",
      title: "",
      width: "40px",
      render: (c) => (
        <input
          type="checkbox"
          aria-label={`选择用例：${clamp(c.question, 20)}`}
          checked={checked.includes(c.id)}
          onChange={() =>
            setChecked((prev) =>
              prev.includes(c.id) ? prev.filter((v) => v !== c.id) : [...prev, c.id],
            )
          }
        />
      ),
    },
    { key: "question", title: "问题", render: (c) => c.question },
    {
      key: "expected_answer",
      title: "标准答案",
      render: (c) => (c.expected_answer ? clamp(c.expected_answer, 80) : <span className="text-muted">—</span>),
    },
    {
      key: "must_hit",
      title: "必须命中",
      width: "110px",
      render: (c) => (
        <Tag>
          {c.must_hit_document_ids.length + c.must_hit_chunk_ids.length > 0
            ? `${c.must_hit_document_ids.length} 文档 / ${c.must_hit_chunk_ids.length} 切片`
            : "验证拒答"}
        </Tag>
      ),
    },
    {
      key: "created_at",
      title: "创建时间",
      width: "140px",
      render: (c) => <span className="text-sm text-secondary">{fmtTime(c.created_at)}</span>,
    },
    {
      key: "actions",
      title: "操作",
      width: "116px",
      render: (c) => (
        <span className="flex items-center gap-1">
          <Button size="sm" variant="ghost" aria-label={`编辑用例：${clamp(c.question, 20)}`} title="编辑" onClick={() => openEditCase(c)}>
            <Pencil size={15} aria-hidden="true" />
          </Button>
          <Button size="sm" variant="ghost" aria-label={`删除用例：${clamp(c.question, 20)}`} title="删除" onClick={() => setDeletingCase(c)}>
            <Trash2 size={15} aria-hidden="true" />
          </Button>
        </span>
      ),
    },
  ];

  // DataTable 泛型要求行上有可选 id：用 case_id 补一个（仅前端行类型，不改 DTO）
  type CaseResultRow = EvalRun["case_results"][number] & { id: string };

  const resultColumns: Column<CaseResultRow>[] = [
    { key: "question", title: "问题", render: (r) => clamp(r.question, 60) },
    { key: "recall_hit", title: "召回命中", width: "90px", render: (r) => <TriMark value={r.recall_hit} /> },
    { key: "citation_ok", title: "引用准确", width: "90px", render: (r) => <TriMark value={r.citation_ok} /> },
    { key: "refusal_ok", title: "拒答正确", width: "90px", render: (r) => <TriMark value={r.refusal_ok} /> },
    {
      key: "faithfulness",
      title: "忠实度",
      width: "90px",
      render: (r) => (r.faithfulness !== null ? r.faithfulness.toFixed(2) : "—"),
    },
    { key: "latency_ms", title: "耗时", width: "90px", render: (r) => `${r.latency_ms}ms` },
    {
      key: "refused",
      title: "是否拒答",
      width: "90px",
      render: (r) => (r.refused ? <Tag>拒答</Tag> : <span className="text-muted">已作答</span>),
    },
  ];

  const metricValue = (key: (typeof METRIC_DEFS)[number]["key"], run: EvalRun): number | null =>
    run.metrics ? (run.metrics[key] as number | null) : null;

  return (
    <div>
      <PageHeader
        title="召回评测集"
        sub="维护标准问题与必须命中资料，定期运行评测回归 RAG 参数与资料质量"
        actions={
          <>
            <Button
              variant="secondary"
              disabled={checked.length === 0}
              loading={running}
              onClick={() => void runEval(checked)}
            >
              运行所选（{checked.length}）
            </Button>
            <Button loading={running} onClick={() => void runEval(null)}>
              运行全部评测
            </Button>
            <Button variant="secondary" onClick={openCreateCase}>
              新建用例
            </Button>
          </>
        }
      />

      {error ? (
        <ErrorState message={error} onRetry={() => void load()} />
      ) : (
        <>
          <DataTable
            ariaLabel="评测用例列表"
            columns={caseColumns}
            rows={cases}
            loading={loading}
            empty={
              <EmptyState
                title="暂无评测用例"
                hint="可在召回测试台保存测试问题为用例，或直接新建"
              />
            }
          />
          <Pagination
            offset={offset}
            limit={limit}
            total={total}
            onChange={setOffset}
            onLimitChange={(nextLimit) => {
              setLimit(nextLimit);
              setOffset(0);
            }}
          />
        </>
      )}

      {/* 评测结果（最近一次运行） */}
      {currentRun?.metrics ? (
        <>
          <div className="grid grid-cols-3 mt-4">
            {METRIC_DEFS.map((def) => {
              const value = metricValue(def.key, currentRun);
              return (
                <Card key={def.key}>
                  <p className="text-sm text-muted">{def.label}</p>
                  <p style={{ fontSize: "var(--font-size-2xl)", fontWeight: 700 }}>
                    {value === null
                      ? "—"
                      : def.isLatency
                        ? `${Math.round(value)}ms`
                        : `${Math.round(value * 100)}%`}
                  </p>
                  <p className="text-xs text-secondary">{def.desc}{value === null ? "（本次无样本）" : ""}</p>
                </Card>
              );
            })}
            <Card>
              <p className="text-sm text-muted">用例数</p>
              <p style={{ fontSize: "var(--font-size-2xl)", fontWeight: 700 }}>
                {currentRun.metrics.case_count}
              </p>
              <p className="text-xs text-secondary">完成于 {fmtTime(currentRun.finished_at)}</p>
            </Card>
          </div>
          <Card title="逐用例结果" className="mt-4">
            <DataTable
              ariaLabel="评测逐用例结果"
              columns={resultColumns}
              rows={currentRun.case_results.map((r) => ({ ...r, id: r.case_id }))}
              empty="无用例结果"
            />
          </Card>
        </>
      ) : null}

      {/* 历史对比（服务端最近 N 次运行；点击展开逐用例结果） */}
      {history.length > 0 ? (
        <Card title={`历史对比（最近 ${history.length} 次运行）`} className="mt-4">
          <p className="text-xs text-muted mb-3">
            运行记录来自服务端评测历史（最新在前）；点击「逐用例结果」展开该次运行的明细。
          </p>
          {history.map((run) => (
            <div key={run.id} className="card card-padded mb-2">
              <div className="flex items-center justify-between gap-2" style={{ flexWrap: "wrap" }}>
                <span className="flex items-center gap-2 text-sm">
                  <strong>{fmtTime(run.finished_at ?? run.created_at ?? null)}</strong>
                  <StatusBadge status={run.status} />
                  <span className="text-muted">用例 {run.metrics?.case_count ?? "—"}</span>
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-expanded={expandedRunId === run.id}
                  onClick={() => void toggleRun(run.id)}
                >
                  {expandedRunId === run.id ? "收起" : "逐用例结果"}
                </Button>
              </div>
              {/* 五项指标 mini-row：与指标卡同一格式化口径，无样本显示 — */}
              <div className="flex gap-4 mt-2" style={{ flexWrap: "wrap" }}>
                {METRIC_DEFS.map((def) => (
                  <span key={def.key} className="text-xs">
                    <span className="text-muted">{def.label} </span>
                    <strong>{fmtMetric(def, run.metrics)}</strong>
                  </span>
                ))}
              </div>
              {expandedRunId === run.id ? (
                <div className="mt-3">
                  {expandedLoading ? (
                    <p className="text-sm text-muted">加载逐用例结果…</p>
                  ) : expandedRun && expandedRun.case_results.length > 0 ? (
                    <DataTable
                      ariaLabel="历史运行逐用例结果"
                      columns={resultColumns}
                      rows={expandedRun.case_results.map((r) => ({ ...r, id: r.case_id }))}
                      empty="无用例结果"
                    />
                  ) : (
                    <p className="text-sm text-muted">该次运行无逐用例结果，仅展示指标。</p>
                  )}
                </div>
              ) : null}
            </div>
          ))}
        </Card>
      ) : null}

      {/* 新建用例弹窗 */}
      <Modal
        open={createOpen}
        title={editingCase ? "编辑评测用例" : "新建评测用例"}
        onClose={() => {
          if (!creating) setCreateOpen(false);
        }}
        footer={
          <>
            <Button variant="ghost" disabled={creating} onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <Button loading={creating} onClick={() => void saveCase()}>
              {editingCase ? "保存修改" : "创建用例"}
            </Button>
          </>
        }
      >
        <Field label="问题" required>
          <Textarea value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="标准测试问题" />
        </Field>
        <Field label="标准答案（可选）">
          <Textarea value={expected} onChange={(e) => setExpected(e.target.value)} placeholder="期望回答的要点…" />
        </Field>
        <Field label="必须命中文档（不选则该用例用于验证拒答）">
          <RagDocumentMultiSelect
            label="必须命中文档"
            documents={docOptions}
            value={mustDocs}
            onChange={setMustDocs}
          />
        </Field>
        <div>
          <Field label="限定数据类型（可选）">
            <Select
              value={filterDataType}
              onChange={(e) => setFilterDataType(e.target.value)}
              options={[...DATA_TYPE_OPTIONS]}
              placeholder="不限"
            />
          </Field>
        </div>
      </Modal>

      <ConfirmDialog
        open={deletingCase !== null}
        title="删除评测用例"
        description={deletingCase ? `确认删除「${clamp(deletingCase.question, 50)}」吗？历史评测结果会保留。` : undefined}
        confirmText="删除"
        danger
        onConfirm={deleteCase}
        onCancel={() => setDeletingCase(null)}
      />
    </div>
  );
}
