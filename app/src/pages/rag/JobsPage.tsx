/**
 * 已合并的解析任务组件：生产入口已收敛到 /admin/rag 的处理状态与失败重试。
 *
 * 关键决策（为什么）：
 * - 概览四卡（待处理/处理中/成功/失败）用 limit=1 的 count 查询取 total，
 *   精确且便宜——后端没有聚合端点，客户端数当前页会随分页失真。
 * - 阶段筛选是客户端过滤：后端 list_jobs 只支持 status/document_id。
 *   为避免"当前页内过滤"的误导，启用阶段筛选时拉最近 200 条做客户端分页，
 *   超过则如实标注；不启用时保持服务端分页。
 * - 有排队/运行中任务时每 5s 静默轮询（不清空列表不闪屏），组件卸载
 *   clearInterval——任务可能由其他页面/用户触发，状态必须自己长出来。
 * - 资料名通过资料列表映射（job DTO 只有 document_id），映射不到显示 id 前 8 位。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../../api/client";
import type { Paginated, RagDocument, RagJob } from "../../api/types";
import {
  Button,
  Card,
  DataTable,
  EmptyState,
  ErrorState,
  PageHeader,
  Pagination,
  ProgressBar,
  Select,
  StatusBadge,
  useToast,
  type Column,
} from "../../components";
import { errText, fmtDuration, fmtTime, hasActiveJobs, safeRagReturnPath, STAGE_LABELS } from "./ragShared";

const DEFAULT_LIMIT = 20;
/** 阶段筛选生效时的拉取上限（客户端过滤），超出如实标注 */
const STAGE_FILTER_SCAN = 200;

const STATUS_OPTIONS = [
  { value: "queued", label: "排队中" },
  { value: "running", label: "运行中" },
  { value: "succeeded", label: "成功" },
  { value: "failed", label: "失败" },
  { value: "cancelled", label: "已取消" },
];

const STAGE_OPTIONS = [
  { value: "parse", label: "解析" },
  { value: "chunk", label: "切片" },
  { value: "index", label: "索引" },
];

interface StatusCounts {
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
}

export default function JobsPage() {
  const location = useLocation();
  // Preserve the queue location through refreshes so detail pages can return to the
  // exact filtered/paginated view that initiated the navigation.
  const returnTo = safeRagReturnPath(`${location.pathname}${location.search}`);
  const toast = useToast();
  const [items, setItems] = useState<RagJob[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [counts, setCounts] = useState<StatusCounts | null>(null);
  const [docTitles, setDocTitles] = useState<Record<string, string>>({});
  const [status, setStatus] = useState("");
  const [stage, setStage] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scanTruncated, setScanTruncated] = useState(false);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  // 轮询期间避免重复入栈的锁（静默刷新不打断用户操作）
  const refreshing = useRef(false);

  const load = useCallback(
    async (quiet = false, signal?: AbortSignal) => {
      // Only silent polling may skip an in-flight request. Lifecycle loads can be aborted
      // during Strict Mode setup and must immediately re-enter so the page cannot stay loading.
      if (quiet && refreshing.current) return;
      if (quiet) refreshing.current = true;
      if (!quiet) {
        setLoading(true);
        setError(null);
      }
      try {
        if (!stage) {
          // 服务端分页（无阶段筛选时最省事且 total 精确）
          const res = await api.get<Paginated<RagJob>>("/api/rag/jobs", {
            status: status || undefined,
            limit,
            offset,
          }, { signal });
          if (signal?.aborted) return;
          setItems(res.items);
          setTotal(res.total);
          setScanTruncated(false);
        } else {
          // 阶段筛选：拉最近一批做客户端过滤 + 客户端分页
          const res = await api.get<Paginated<RagJob>>("/api/rag/jobs", {
            status: status || undefined,
            limit: STAGE_FILTER_SCAN,
            offset: 0,
          }, { signal });
          if (signal?.aborted) return;
          const filtered = res.items.filter((j) => j.stage === stage);
          setItems(filtered.slice(offset, offset + limit));
          setTotal(filtered.length);
          setScanTruncated(res.total > STAGE_FILTER_SCAN);
        }
        // 概览计数：四个状态各取 total（精确、轻量）
        const [queued, running, succeeded, failed] = await Promise.all(
          (["queued", "running", "succeeded", "failed"] as const).map((s) =>
            api.get<Paginated<RagJob>>("/api/rag/jobs", { status: s, limit: 1 }, { signal }),
          ),
        );
        if (signal?.aborted) return;
        setCounts({
          queued: queued.total,
          running: running.total,
          succeeded: succeeded.total,
          failed: failed.total,
        });
      } catch (err) {
        if (!quiet && !signal?.aborted) setError(errText(err, "任务队列加载失败"));
      } finally {
        if (!signal?.aborted) setLoading(false);
        if (quiet) refreshing.current = false;
      }
    },
    [status, stage, offset, limit],
  );

  // 资料 id → 标题映射（任务 DTO 不带标题）
  useEffect(() => {
    const controller = new AbortController();
    api
      .get<Paginated<RagDocument>>("/api/rag/documents", { limit: 200 }, { signal: controller.signal })
      .then((res) => {
        if (!controller.signal.aborted) {
          setDocTitles(Object.fromEntries(res.items.map((d) => [d.id, d.title])));
        }
      })
      .catch(() => {
        // 标题映射失败不阻断队列主流程（回退显示 id）
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(false, controller.signal);
    return () => controller.abort();
  }, [load]);

  // Keep the controller alive while the queue remains active; using the boolean avoids aborting
  // a poll merely because that poll refreshed `items` with a new array identity.
  const shouldPoll = hasActiveJobs(items);

  // 有活动任务时 5s 轮询；卸载清理（PRD-03 §7 队列"自己长状态"）
  useEffect(() => {
    if (!shouldPoll) return;
    const controller = new AbortController();
    const timer = setInterval(() => void load(true, controller.signal), 5000);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [shouldPoll, load]);

  const retry = async (job: RagJob) => {
    setRetryingId(job.id);
    try {
      await api.post(`/api/rag/jobs/${job.id}/retry`);
      toast.success("已从失败阶段重新触发");
      await load();
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setRetryingId(null);
    }
  };

  const docName = (job: RagJob) => docTitles[job.document_id] ?? `${job.document_id.slice(0, 8)}…`;

  const columns: Column<RagJob>[] = [
    {
      key: "document",
      title: "资料名",
      render: (job) => (
        <Link
          to={`/admin/rag/documents/${job.document_id}?returnTo=${encodeURIComponent(returnTo)}`}
          state={{ returnTo }}
        >
          {docName(job)}
        </Link>
      ),
    },
    { key: "stage", title: "阶段", width: "80px", render: (job) => STAGE_LABELS[job.stage] ?? job.stage },
    { key: "status", title: "状态", width: "100px", render: (job) => <StatusBadge status={job.status} /> },
    {
      key: "progress",
      title: "进度",
      width: "140px",
      render: (job) => (
        <div className="flex items-center gap-2">
          <ProgressBar
            value={job.progress}
            tone={job.status === "failed" ? "danger" : job.status === "succeeded" ? "success" : "primary"}
          />
          <span className="text-xs text-muted">{Math.round(job.progress * 100)}%</span>
        </div>
      ),
    },
    { key: "duration", title: "耗时", width: "100px", render: (job) => fmtDuration(job.started_at, job.finished_at) },
    {
      key: "error",
      title: "错误信息",
      render: (job) =>
        job.error_code ? (
          <span className="text-danger text-sm">
            {job.error_code}：{job.error_message}
          </span>
        ) : (
          <span className="text-muted">—</span>
        ),
    },
    { key: "created_at", title: "创建时间", width: "140px", render: (job) => <span className="text-sm text-secondary">{fmtTime(job.created_at)}</span> },
    {
      key: "actions",
      title: "操作",
      width: "90px",
      render: (job) =>
        job.status === "failed" ? (
          <Button size="sm" variant="secondary" loading={retryingId === job.id} onClick={() => void retry(job)}>
            重试
          </Button>
        ) : (
          <span className="text-muted">—</span>
        ),
    },
  ];

  const statCards: { label: string; value: number | undefined; tone: string }[] = [
    { label: "待处理", value: counts?.queued, tone: "var(--color-text-secondary)" },
    { label: "处理中", value: counts?.running, tone: "var(--color-info)" },
    { label: "成功", value: counts?.succeeded, tone: "var(--color-success)" },
    { label: "失败", value: counts?.failed, tone: "var(--color-danger)" },
  ];

  return (
    <div>
      <PageHeader title="解析与切片任务" />

      {/* 队列概览（PRD-03 §7） */}
      <div className="grid grid-cols-4 mb-4">
        {statCards.map((card) => (
          <Card key={card.label}>
            <p className="text-sm text-muted">{card.label}</p>
            <p style={{ fontSize: "var(--font-size-2xl)", fontWeight: 700, color: card.tone }}>
              {card.value ?? "—"}
            </p>
          </Card>
        ))}
      </div>

      <div className="card card-padded mb-4">
        <div className="flex gap-3" style={{ flexWrap: "wrap" }}>
          <div style={{ width: 200 }}>
            <Select
              aria-label="任务状态"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setOffset(0);
              }}
              options={STATUS_OPTIONS}
              placeholder="全部状态"
            />
          </div>
          <div style={{ width: 200 }}>
            <Select
              aria-label="处理阶段"
              value={stage}
              onChange={(e) => {
                setStage(e.target.value);
                setOffset(0);
              }}
              options={STAGE_OPTIONS}
              placeholder="全部阶段"
            />
          </div>
          <Button variant="ghost" size="sm" onClick={() => void load()}>
            刷新
          </Button>
        </div>
        {scanTruncated ? (
          <p className="text-xs text-muted mt-2">
            阶段筛选作用于最近 {STAGE_FILTER_SCAN} 条任务（更早任务请按状态筛选查看）。
          </p>
        ) : null}
      </div>

      {error ? (
        <ErrorState message={error} onRetry={() => void load()} />
      ) : (
        <>
          <DataTable
            ariaLabel="处理任务列表"
            columns={columns}
            rows={items}
            loading={loading}
            empty={<EmptyState title="暂无任务" hint="上传资料或触发重新解析后，任务会出现在这里" />}
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
    </div>
  );
}
