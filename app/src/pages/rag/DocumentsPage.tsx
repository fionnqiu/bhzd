/**
 * 系统管理 · 资料库（/admin/rag）——资料列表/筛选/按状态操作（PRD-03 §4）。
 *
 * 实现要点（为什么）：
 * - 处理状态直接来自后端 pipeline；上传完成后资料自动发布，页面不再提供
 *   送审、审核状态或台账入口，避免旧审核流程被重新激活。
 * - 更新时间排序：后端只支持"新→旧"，"旧→新"通过 total 换算从尾部取页再倒序，
 *   保证全局顺序正确而不是只倒当前页。
 * - 已发布资料不显示删除按钮（PRD-06 §5.2 只能归档）；删除 409 时透传后端
 *   中文提示（兜底并发情况：列表加载后他人发布了该资料）。
 * - 批量操作保留重新索引/归档；
 *   资格提示只做引导，守卫以后端逐项判定为准（批量端点允许部分成功），
 *   失败项的中文原因在结果弹窗逐项透传。
 */

import { useCallback, useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../../api/client";
import type { Paginated, RagDocument, RagJob } from "../../api/types";
import {
  Button,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorState,
  Modal,
  PageHeader,
  Pagination,
  SearchInput,
  Select,
  StatusBadge,
  Tag,
  useToast,
  type Column,
} from "../../components";
import {
  DATA_TYPE_OPTIONS,
  clamp,
  errText,
  fmtTime,
  IndexStatusBadge,
  safeRagReturnPath,
  SOURCE_TYPE_LABELS,
} from "./ragShared";

const DEFAULT_LIMIT = 20;

const INDEX_FILTER_OPTIONS = [
  { value: "indexed", label: "已索引" },
  { value: "pending", label: "未索引" },
];

/* ---------------------------------------------------------------- 批量操作 */

/** 批量动作（与后端 BatchBody.action 一一对应；rag_admin.py batch_documents） */
type BatchAction = "reindex" | "archive";

/** 批量结果项（POST /api/rag/documents/batch 响应；允许部分成功，失败项带守卫原因） */
interface BatchResultItem {
  id: string;
  ok: boolean;
  code?: string;
  message?: string;
}

/** 批量操作元信息：确认话术必须讲清后果（归档影响学生端召回，高危动作明示） */
const BATCH_META: Record<
  BatchAction,
  { label: string; confirmText: string; danger?: boolean; describe: (n: number) => string }
> = {
  reindex: {
    label: "批量重新索引",
    confirmText: "确认重建",
    describe: (n) =>
      `将按当前系统切片参数对已选 ${n} 项资料重建索引（同步执行，资料较多时需要等待）。「已归档」资料不可重建索引，将由后端逐项返回失败原因，不影响其余项执行。`,
  },
  archive: {
    label: "批量归档",
    confirmText: "确认归档",
    danger: true,
    describe: (n) =>
      `归档后已选 ${n} 项资料立即退出召回——学生端不再召回这些资料；切片与历史引用快照保留，可随时追溯（PRD-06 §12.2）。已归档的项由后端逐项返回失败原因，不影响其余项执行。`,
  },
};

/** 批量结果弹窗内容：成功/失败分组，失败项透传后端中文守卫话术 */
function BatchResultView({
  result,
}: {
  result: { titles: Record<string, string>; results: BatchResultItem[] };
}) {
  const okItems = result.results.filter((r) => r.ok);
  const failItems = result.results.filter((r) => !r.ok);
  // 标题取自操作瞬间的快照：结果弹窗展示时列表可能已刷新（状态已变更）
  const titleOf = (id: string) => result.titles[id] ?? id;
  return (
    <div>
      <p>
        共 {result.results.length} 项：成功 {okItems.length} 项，失败 {failItems.length} 项。
      </p>
      {failItems.length > 0 ? (
        <>
          <p className="text-sm mt-3 mb-2">
            <strong>失败项</strong>
          </p>
          <ul>
            {failItems.map((r) => (
              <li key={r.id} className="mb-2 text-sm">
                「{titleOf(r.id)}」：{r.message ?? "操作失败"}
                {r.code ? <span className="text-muted font-mono text-xs">（{r.code}）</span> : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {okItems.length > 0 ? (
        <>
          <p className="text-sm mt-3 mb-2">
            <strong>成功项</strong>
          </p>
          <ul>
            {okItems.map((r) => (
              <li key={r.id} className="mb-1 text-sm text-secondary">
                「{titleOf(r.id)}」
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

export default function DocumentsPage() {
  const location = useLocation();
  const returnTo = safeRagReturnPath(`${location.pathname}${location.search}`);
  const toast = useToast();
  const [items, setItems] = useState<RagDocument[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 筛选条件：数据类型、处理/索引状态与更新时间；审核 is no longer an active workflow.
  const [q, setQ] = useState("");
  const [dataType, setDataType] = useState("");
  const [indexStatus, setIndexStatus] = useState("");
  const [sortAsc, setSortAsc] = useState(false);

  // 行内操作状态
  const [deleteTarget, setDeleteTarget] = useState<RagDocument | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<RagDocument | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // 批量操作状态（PRD-03 §7）：选择跨页保留，便于筛选后凑齐一批再操作
  const [selected, setSelected] = useState<string[]>([]);
  const [batchAction, setBatchAction] = useState<BatchAction | null>(null);
  const [batchResult, setBatchResult] = useState<{
    action: BatchAction;
    titles: Record<string, string>;
    results: BatchResultItem[];
  } | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    const query = {
      limit,
      data_type: dataType || undefined,
      index_status: indexStatus || undefined,
      q: q.trim() || undefined,
    };
    try {
      if (!sortAsc) {
        // 默认：后端原生"更新时间 新→旧"
        const res = await api.get<Paginated<RagDocument>>("/api/rag/documents", {
          ...query,
          offset,
        }, { signal });
        if (signal?.aborted) return;
        setItems(res.items);
        setTotal(res.total);
      } else {
        // "旧→新"：后端只支持新→旧，先取 total 再从尾部换算窗口倒序，
        // 这样跨页的全局顺序依然正确（而不是只倒序当前页）
        const head = await api.get<Paginated<RagDocument>>("/api/rag/documents", {
          ...query,
          offset: 0,
          limit: 1,
        }, { signal });
        if (signal?.aborted) return;
        const start = Math.max(0, head.total - offset - limit);
        // 窗口大小必须是 total-offset-start：末页不足一页时若仍按当前页大小拉取，
        // 会把上一页的内容重复带进末页
        const size = Math.max(1, head.total - offset - start);
        const page = await api.get<Paginated<RagDocument>>("/api/rag/documents", {
          ...query,
          offset: start,
          limit: size,
        }, { signal });
        if (signal?.aborted) return;
        setItems([...page.items].reverse());
        setTotal(head.total);
      }
    } catch (err) {
      if (!signal?.aborted) setError(errText(err, "资料列表加载失败"));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [offset, limit, dataType, indexStatus, q, sortAsc]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  /** 变更筛选时回到第一页，避免 offset 落在空页 */
  const resetAnd = (fn: () => void) => {
    fn();
    setOffset(0);
  };

  /** 简单运营动作：POST → 提示 → 刷新；后端中文错误原样透传。 */
  const runAction = async (doc: RagDocument, path: string, okMsg: string) => {
    setBusyId(doc.id);
    try {
      await api.post(path);
      toast.success(okMsg);
      await load();
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setBusyId(null);
    }
  };

  /**
   * 失败重试：优先找该资料最近的失败任务从失败阶段续跑（PRD-06 §5.2）；
   * 找不到失败任务时退化为整条管线重跑。
   */
  const retryDocument = async (doc: RagDocument) => {
    setBusyId(doc.id);
    try {
      const jobs = await api.get<Paginated<RagJob>>("/api/rag/jobs", {
        document_id: doc.id,
        status: "failed",
        limit: 1,
      });
      if (jobs.items[0]) {
        await api.post(`/api/rag/jobs/${jobs.items[0].id}/retry`);
      } else {
        await api.post(`/api/rag/documents/${doc.id}/parse`);
      }
      toast.success("已重新触发处理");
      await load();
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setBusyId(null);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      await api.delete(`/api/rag/documents/${deleteTarget.id}`);
      toast.success("资料已删除（操作已记录审计日志）");
      setDeleteTarget(null);
      await load();
    } catch (err) {
      // 409 INVALID_STATE：已发布资料只能归档——后端中文消息直接透出
      toast.error(errText(err));
      setDeleteTarget(null);
    }
  };

  const confirmArchive = async () => {
    if (!archiveTarget) return;
    try {
      await api.post(`/api/rag/documents/${archiveTarget.id}/archive`);
      toast.success("已归档，学生端不再召回该资料");
      setArchiveTarget(null);
      await load();
    } catch (err) {
      toast.error(errText(err));
      setArchiveTarget(null);
    }
  };

  /**
   * 批量执行：前端不做资格预过滤（后端是唯一权威，逐项判定允许部分成功），
   * 只负责发送所选 id 并汇报逐项结果；完成后清空选择并刷新列表。
   */
  const runBatch = async () => {
    if (!batchAction || selected.length === 0) return;
    const action = batchAction;
    // 标题快照：结果弹窗展示时列表已刷新（归档后状态变更），标题取操作瞬间的值
    const titles = Object.fromEntries(items.map((d) => [d.id, d.title]));
    try {
      const res = await api.post<{ results: BatchResultItem[] }>("/api/rag/documents/batch", {
        ids: selected,
        action,
      });
      setBatchResult({ action, titles, results: res.results });
      setBatchAction(null);
      setSelected([]);
      await load();
    } catch (err) {
      // 整单失败（422 参数错误/403 等）：逐项结果不存在，直接 toast 后端原因
      toast.error(errText(err));
      setBatchAction(null);
    }
  };

  /** 按状态给出可用操作（PRD-03 §4 操作列 + PRD-06 §5.1 状态机） */
  const rowActions = (doc: RagDocument) => {
    const busy = busyId === doc.id;
    const buttons: React.ReactNode[] = [];
    if (doc.status === "indexed" || doc.status === "published") {
      buttons.push(
        <Button
          key="reindex"
          size="sm"
          variant="ghost"
          loading={busy}
          onClick={() =>
            void runAction(doc, `/api/rag/documents/${doc.id}/index`, "已重新索引")
          }
        >
          重新索引
        </Button>,
      );
    }
    if (doc.status === "published") {
      buttons.push(
        <Button key="archive" size="sm" variant="ghost" onClick={() => setArchiveTarget(doc)}>
          归档
        </Button>,
      );
    }
    if (doc.status === "failed") {
      buttons.push(
        <Button key="retry" size="sm" variant="secondary" loading={busy} onClick={() => void retryDocument(doc)}>
          重试
        </Button>,
      );
    }
    if (doc.status !== "published" && doc.status !== "archived") {
      buttons.push(
        <Button key="delete" size="sm" variant="ghost" onClick={() => setDeleteTarget(doc)}>
          删除
        </Button>,
      );
    }
    return <div className="flex gap-1" style={{ flexWrap: "wrap" }}>{buttons}</div>;
  };

  const columns: Column<RagDocument>[] = [
    {
      key: "select",
      // 表头复选框只作用当前页（全选/取消本页），跨页选择逐行勾选累积
      title: (
        <input
          type="checkbox"
          aria-label="全选本页"
          checked={items.length > 0 && items.every((d) => selected.includes(d.id))}
          onChange={(e) => {
            const pageIds = items.map((d) => d.id);
            setSelected((prev) =>
              e.target.checked
                ? [...new Set([...prev, ...pageIds])]
                : prev.filter((v) => !pageIds.includes(v)),
            );
          }}
        />
      ),
      width: "40px",
      render: (doc) => (
        <input
          type="checkbox"
          aria-label={`选择资料：${doc.title}`}
          checked={selected.includes(doc.id)}
          onChange={() =>
            setSelected((prev) =>
              prev.includes(doc.id) ? prev.filter((v) => v !== doc.id) : [...prev, doc.id],
            )
          }
        />
      ),
    },
    {
      key: "title",
      title: "标题",
      render: (doc) => (
        <Link
          to={`/admin/rag/documents/${doc.id}?returnTo=${encodeURIComponent(returnTo)}`}
          state={{ returnTo }}
        >
          {doc.title}
        </Link>
      ),
    },
    {
      key: "file_type",
      title: "文件类型",
      width: "90px",
      render: (doc) => <Tag>{doc.file_type.toUpperCase()}</Tag>,
    },
    { key: "version", title: "版本", width: "80px", render: (doc) => `v${doc.version}` },
    {
      key: "source",
      title: "来源",
      render: (doc) => (
        <span className="text-sm">
          {SOURCE_TYPE_LABELS[doc.source_type] ?? doc.source_type} · {doc.source_name}
        </span>
      ),
    },
    {
      key: "processing_status",
      title: "处理状态",
      width: "150px",
      // The list endpoint exposes the document's durable pipeline state, not a live job join.
      // Keep that state visible here so an upload can be followed without opening the legacy queue.
      render: (doc) => (
        <div className="flex items-center gap-1" style={{ flexWrap: "wrap" }}>
          <StatusBadge status={doc.status} />
          {doc.status === "failed" && (doc.error_message || doc.error_code) ? (
            <span className="text-xs text-danger" title={doc.error_message ?? doc.error_code ?? "处理失败"}>
              {clamp(doc.error_message ?? doc.error_code ?? "处理失败", 40)}
            </span>
          ) : null}
        </div>
      ),
    },
    {
      key: "chunk_count",
      title: "切片数",
      width: "80px",
      render: (doc) => doc.chunk_count ?? "—",
    },
    {
      key: "index",
      title: "索引状态",
      width: "100px",
      render: (doc) => <IndexStatusBadge doc={doc} />,
    },
    {
      key: "updated_at",
      title: "更新时间",
      width: "140px",
      render: (doc) => <span className="text-sm text-secondary">{fmtTime(doc.updated_at)}</span>,
    },
    { key: "actions", title: "操作", width: "220px", render: rowActions },
  ];

  return (
    <div>
      <PageHeader
        title="RAG 资料库"
        actions={
          <Link to="/admin/rag/upload" className="btn btn-primary">
            上传资料
          </Link>
        }
      />

      {/* 筛选区（PRD-03 §4.1） */}
      <div className="card card-padded mb-4">
        <div className="grid grid-cols-3">
          <SearchInput
            value={q}
            // SearchInput 的防抖设计：onChange 只同步组件内部态，父级值只在
            // onSearch（防抖后）更新——若 onChange 直接回写 value，防抖永远不触发
            onChange={() => {}}
            onSearch={(v) => resetAnd(() => setQ(v))}
            placeholder="搜索资料标题…"
          />
          <Select
            aria-label="数据类型"
            value={dataType}
            onChange={(e) => resetAnd(() => setDataType(e.target.value))}
            options={[...DATA_TYPE_OPTIONS]}
            placeholder="全部数据类型"
          />
          <Select
            aria-label="索引状态"
            value={indexStatus}
            onChange={(e) => resetAnd(() => setIndexStatus(e.target.value))}
            options={INDEX_FILTER_OPTIONS}
            placeholder="全部索引状态"
          />
          <Select
            aria-label="排序"
            value={sortAsc ? "asc" : "desc"}
            onChange={(e) => resetAnd(() => setSortAsc(e.target.value === "asc"))}
            options={[
              { value: "desc", label: "更新时间：新→旧" },
              { value: "asc", label: "更新时间：旧→新" },
            ]}
          />
        </div>
      </div>

      {error ? (
        <ErrorState message={error} onRetry={() => void load()} />
      ) : (
        <>
          {/* 批量操作条：选中后出现；资格提示只做引导，最终以后端逐项结果为准 */}
          {selected.length > 0 ? (
            <div className="card card-padded mb-4">
              <div className="flex items-center gap-2" style={{ flexWrap: "wrap" }}>
                <strong>已选 {selected.length} 项</strong>
                <Button size="sm" variant="secondary" onClick={() => setBatchAction("reindex")}>
                  批量重新索引
                </Button>
                <Button size="sm" variant="secondary" onClick={() => setBatchAction("archive")}>
                  批量归档
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setSelected([])}>
                  清除选择
                </Button>
              </div>
            </div>
          ) : null}
          <DataTable
            ariaLabel="资料列表"
            columns={columns}
            rows={items}
            loading={loading}
            empty={
              <EmptyState
                title="暂无资料"
                hint="上传第一份教学资料，处理完成后学生端即可召回"
                action={
                  <Link to="/admin/rag/upload" className="btn btn-primary">
                    上传资料
                  </Link>
                }
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

      <ConfirmDialog
        open={deleteTarget !== null}
        title="删除资料"
        danger
        confirmText="确认删除"
        description={`将物理删除「${deleteTarget?.title ?? ""}」及其全部切片与任务记录（操作会保留审计日志）。已发布资料只能归档，不能删除。`}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
      <ConfirmDialog
        open={archiveTarget !== null}
        title="归档资料"
        confirmText="确认归档"
        description={`归档后「${archiveTarget?.title ?? ""}」立即退出学生端召回；切片与历史引用快照保留，可随时追溯（PRD-06 §12.2）。`}
        onConfirm={confirmArchive}
        onCancel={() => setArchiveTarget(null)}
      />

      {/* 批量二次确认：归档等高危动作的话术必须讲清后果（BATCH_META） */}
      <ConfirmDialog
        open={batchAction !== null}
        title={batchAction ? BATCH_META[batchAction].label : ""}
        danger={batchAction ? (BATCH_META[batchAction].danger ?? false) : false}
        confirmText={batchAction ? BATCH_META[batchAction].confirmText : "确认"}
        description={batchAction ? BATCH_META[batchAction].describe(selected.length) : ""}
        onConfirm={runBatch}
        onCancel={() => setBatchAction(null)}
      />

      {/* 批量结果汇总：逐项展示成功/失败（部分成功是常态，不是异常） */}
      <Modal
        open={batchResult !== null}
        title={batchResult ? `${BATCH_META[batchResult.action].label}结果` : ""}
        onClose={() => setBatchResult(null)}
        footer={<Button onClick={() => setBatchResult(null)}>知道了</Button>}
      >
        {batchResult ? <BatchResultView result={batchResult} /> : null}
      </Modal>
    </div>
  );
}
