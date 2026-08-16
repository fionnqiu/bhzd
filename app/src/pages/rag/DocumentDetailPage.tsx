/**
 * 系统管理 · 资料详情（/admin/rag/documents/:id）——元数据/切片/索引/版本 + 状态操作。
 *
 * 关键决策（为什么）：
 * - 新上传由后端在索引完成后自动进入学生召回范围；详情页只提供处理与归档操作。
 * - 历史来源台账/审核字段仍由兼容 DTO 返回，但不再作为活动详情内容展示。
 * - 敏感信息标志来自最近一次解析任务 params.sensitive_flags（pipeline.py
 *   scan_sensitive_info：phone/id_card/email/block_publish），身份证命中
 *   会阻止发布，这里必须醒目前置，而不是等发布失败才发现。
 * - 召回记录来自 GET /documents/{id}/recall-records（recall_logs：学生问答
 *   与历史管理检索两条渠道命中日志），独立分页加载，失败不影响详情主数据。
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type {
  DocumentDetailResponse,
  GraphNodeDetail,
  Paginated,
  RagChunk,
} from "../../api/types";
import {
  Button,
  Card,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorState,
  PageHeader,
  Pagination,
  Spinner,
  StatusBadge,
  Tag,
  useToast,
  type Column,
} from "../../components";
import {
  clamp,
  DATA_TYPE_LABELS,
  errText,
  fmtDuration,
  fmtTime,
  LicenseBadge,
  safeRagReturnPath,
  SOURCE_TYPE_LABELS,
  STAGE_LABELS,
  VISIBILITY_LABELS,
} from "./ragShared";

/** 向量统计拉取上限：超出时如实标注"仅统计前 N 条" */
const CHUNK_STATS_LIMIT = 200;
/** Keep the detail page useful as a read-only replacement for the old chunk editor. */
const CHUNK_PREVIEW_COUNT = 20;
/** 召回记录默认分页大小（recall_logs 按时间倒序，详情页只看最近命中） */
const DEFAULT_RECALL_LIMIT = 10;

/** 敏感信息标志的结构（pipeline.py scan_sensitive_info） */
interface SensitiveFlags {
  phone?: number;
  id_card?: number;
  email?: number;
  block_publish?: boolean;
}

/** 召回记录项（GET /api/rag/documents/{id}/recall-records；user 允许为空——历史数据/账号已删） */
interface RecallRecord {
  id: string;
  query: string;
  score: number;
  channel: string;
  user_name: string | null;
  created_at: string;
}

/**
 * 召回渠道 → 中文（recall_logs.channel；未知渠道原样显示兜底）。
 *
 * ``search_test`` 是保留的历史/API 渠道名；界面使用中性名称，避免已删除
 * 的管理端板块继续出现在资料详情中。
 */
const RECALL_CHANNEL_LABELS: Record<string, string> = {
  student_query: "学生问答",
  search_test: "历史管理检索",
};

export default function DocumentDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const returnTo = safeRagReturnPath(
    (location.state as { returnTo?: unknown } | null)?.returnTo ??
      new URLSearchParams(location.search).get("returnTo"),
  );

  const [detail, setDetail] = useState<DocumentDetailResponse | null>(null);
  const [chunks, setChunks] = useState<RagChunk[]>([]);
  const [chunkTotal, setChunkTotal] = useState(0);
  const [capNames, setCapNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [busy, setBusy] = useState<string | null>(null);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  // 召回记录：独立于详情主数据的分页加载（辅助面板失败不拖垮整页）
  const [recallItems, setRecallItems] = useState<RecallRecord[]>([]);
  const [recallTotal, setRecallTotal] = useState(0);
  const [recallOffset, setRecallOffset] = useState(0);
  const [recallLimit, setRecallLimit] = useState(DEFAULT_RECALL_LIMIT);
  const [recallLoading, setRecallLoading] = useState(false);
  const [recallError, setRecallError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<DocumentDetailResponse>(`/api/rag/documents/${id}`, undefined, { signal });
      if (signal?.aborted) return;
      setDetail(res);
      // 切片：一次拉取同时服务"前 N 条预览"与"向量索引统计"
      const chunkRes = await api.get<Paginated<RagChunk>>(
        `/api/rag/documents/${id}/chunks`,
        { limit: CHUNK_STATS_LIMIT },
        { signal },
      );
      if (signal?.aborted) return;
      setChunks(chunkRes.items);
      setChunkTotal(chunkRes.total);
      // 能力节点名称解析（best-effort：失败则回退显示 id）
      const names: Record<string, string> = {};
      await Promise.all(
        res.document.cap_ids.map(async (capId) => {
          try {
            const node = await api.get<GraphNodeDetail>(`/api/graph/nodes/${capId}`, undefined, { signal });
            names[capId] = node.label;
          } catch {
            names[capId] = capId;
          }
        }),
      );
      if (signal?.aborted) return;
      setCapNames(names);
    } catch (err) {
      if (!signal?.aborted) setError(errText(err, "资料详情加载失败"));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  /** 召回记录加载：跟随 recallOffset 翻页；错误就地展示，不动详情主数据的 error 态 */
  const loadRecall = useCallback(async (signal?: AbortSignal) => {
    setRecallLoading(true);
    setRecallError(null);
    try {
      const res = await api.get<{ items: RecallRecord[]; total: number }>(
        `/api/rag/documents/${id}/recall-records`,
        { limit: recallLimit, offset: recallOffset },
        { signal },
      );
      if (signal?.aborted) return;
      setRecallItems(res.items);
      setRecallTotal(res.total);
    } catch (err) {
      if (!signal?.aborted) setRecallError(errText(err, "召回记录加载失败"));
    } finally {
      if (!signal?.aborted) setRecallLoading(false);
    }
  }, [id, recallOffset, recallLimit]);

  useEffect(() => {
    const controller = new AbortController();
    void loadRecall(controller.signal);
    return () => controller.abort();
  }, [loadRecall]);

  /** 管线/状态操作统一入口：成功后刷新详情，失败透传后端守卫话术 */
  const runAction = async (key: string, path: string, okMsg: string, body?: unknown) => {
    setBusy(key);
    try {
      await api.post(path, body);
      toast.success(okMsg);
      await load();
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setBusy(null);
    }
  };

  const doDelete = async () => {
    try {
      await api.delete(`/api/rag/documents/${id}`);
      toast.success("资料已删除");
      navigate(returnTo, { replace: true });
    } catch (err) {
      toast.error(errText(err));
      setDeleteOpen(false);
    }
  };

  if (loading && !detail) {
    return (
      <div className="loading-block">
        <Spinner large /> 正在加载资料详情…
      </div>
    );
  }
  if (error || !detail) {
    return <ErrorState message={error ?? "资料不存在"} onRetry={() => void load()} />;
  }

  const doc = detail.document;
  const flags = (detail.sensitive_flags ?? null) as SensitiveFlags | null;
  const hasFlags = !!flags && ((flags.phone ?? 0) > 0 || (flags.id_card ?? 0) > 0 || (flags.email ?? 0) > 0);
  const embedded = chunks.filter((c) => c.embedding_model).length;
  const embedModels = [...new Set(chunks.map((c) => c.embedding_model).filter(Boolean))] as string[];
  const canArchive = doc.status !== "archived";
  const canDelete = doc.status !== "published";

  const jobColumns: Column<(typeof detail.jobs)[number]>[] = [
    { key: "stage", title: "阶段", width: "80px", render: (j) => STAGE_LABELS[j.stage] ?? j.stage },
    { key: "status", title: "状态", width: "100px", render: (j) => <StatusBadge status={j.status} /> },
    {
      key: "duration",
      title: "耗时",
      width: "100px",
      render: (j) => fmtDuration(j.started_at, j.finished_at),
    },
    { key: "attempt", title: "尝试", width: "60px" },
    {
      key: "error",
      title: "错误信息",
      render: (j) =>
        j.error_code ? (
          <span className="text-danger text-sm" title={j.error_message ?? ""}>
            {j.error_code}：{j.error_message}
          </span>
        ) : (
          "—"
        ),
    },
    {
      key: "created_at",
      title: "创建时间",
      width: "140px",
      render: (j) => <span className="text-sm text-secondary">{fmtTime(j.created_at)}</span>,
    },
  ];

  /** 召回记录列：查询内容截断防撑表，渠道/相似度/用户/时间按 PRD-03 §6 展示 */
  const recallColumns: Column<RecallRecord>[] = [
    {
      key: "query",
      title: "查询内容",
      render: (r) => (
        <span className="text-sm" title={r.query}>
          {clamp(r.query, 60)}
        </span>
      ),
    },
    {
      key: "channel",
      title: "渠道",
      width: "100px",
      render: (r) => <Tag>{RECALL_CHANNEL_LABELS[r.channel] ?? r.channel}</Tag>,
    },
    {
      key: "score",
      title: "相似度",
      width: "90px",
      render: (r) => r.score.toFixed(3),
    },
    {
      key: "user",
      title: "用户",
      width: "110px",
      render: (r) => r.user_name ?? <span className="text-muted">—</span>,
    },
    {
      key: "created_at",
      title: "时间",
      width: "140px",
      render: (r) => <span className="text-sm text-secondary">{fmtTime(r.created_at)}</span>,
    },
  ];

  /** 基本信息行：label + 值的两列展示 */
  const infoRow = (label: string, value: ReactNode) => (
    <div className="flex gap-2 mb-2" style={{ alignItems: "baseline" }}>
      <span className="text-sm text-muted" style={{ width: 96, flexShrink: 0 }}>{label}</span>
      <span className="text-sm" style={{ wordBreak: "break-all" }}>{value}</span>
    </div>
  );

  return (
    <div>
      <PageHeader
        title={doc.title}
        actions={
          <Link to={returnTo} className="btn btn-ghost">
            ← 返回
          </Link>
        }
      />
      <div className="flex items-center gap-2 mb-4" style={{ marginTop: "-12px" }}>
        <StatusBadge status={doc.status} />
        <Tag>v{doc.version}</Tag>
        <Tag>处理版本 #{doc.process_version}</Tag>
      </div>

      {/* 操作区（PRD-03 §6 核心操作，按状态显隐） */}
      <Card title="操作" className="mb-4">
        <div className="flex gap-2" style={{ flexWrap: "wrap" }}>
          <Button
            variant="secondary"
            loading={busy === "parse"}
            onClick={() => void runAction("parse", `/api/rag/documents/${id}/parse`, "已重新解析（含切片与索引）")}
          >
            重新解析
          </Button>
          <Button
            variant="secondary"
            loading={busy === "chunk"}
            onClick={() => void runAction("chunk", `/api/rag/documents/${id}/chunk`, "已重新切片并重建索引")}
          >
            重新切片
          </Button>
          <Button
            variant="secondary"
            loading={busy === "index"}
            onClick={() => void runAction("index", `/api/rag/documents/${id}/index`, "已重新索引")}
          >
            重新索引
          </Button>
          {canArchive ? (
            <Button variant="secondary" onClick={() => setArchiveOpen(true)}>
              归档
            </Button>
          ) : null}
          {canDelete ? (
            <Button variant="danger" onClick={() => setDeleteOpen(true)}>
              删除
            </Button>
          ) : null}
        </div>
        <p className="text-xs text-muted mt-2">
          解析、切片、索引会自动完成；归档/删除仍会写入审计日志，已发布资料只能归档。
        </p>
      </Card>

      {/* 敏感信息告警（PRD-06 §4.3：身份证阻止发布，手机号/邮箱建议脱敏） */}
      {hasFlags ? (
        <div
          className={`form-alert ${flags?.block_publish ? "form-alert-error" : "form-alert-success"} mb-4`}
          role="alert"
          style={
            flags?.block_publish
              ? undefined
              : { background: "var(--color-warning-soft)", color: "var(--color-warning)" }
          }
        >
          <strong>检测到敏感信息：</strong>
          {(flags?.id_card ?? 0) > 0 ? `身份证号 ${flags?.id_card} 处（阻止发布，需脱敏后重新解析）；` : ""}
          {(flags?.phone ?? 0) > 0 ? `手机号 ${flags?.phone} 处（建议脱敏）；` : ""}
          {(flags?.email ?? 0) > 0 ? `邮箱 ${flags?.email} 处（建议脱敏）。` : ""}
        </div>
      ) : null}

      <div className="grid grid-cols-2">
        {/* 基本信息 */}
        <Card title="基本信息">
          {infoRow("文件类型", doc.file_type.toUpperCase())}
          {infoRow("版本", `v${doc.version}`)}
          {infoRow("可见范围", VISIBILITY_LABELS[doc.visibility] ?? doc.visibility)}
          {infoRow("数据类型", doc.data_types.map((t) => DATA_TYPE_LABELS[t] ?? t).join(" / ") || "—")}
          {infoRow("过期时间", fmtTime(doc.expires_at))}
          {infoRow("创建时间", fmtTime(doc.created_at))}
          {infoRow("更新时间", fmtTime(doc.updated_at))}
          {infoRow("发布时间", fmtTime(doc.published_at))}
          {doc.error_message ? infoRow("最近错误", <span className="text-danger">{doc.error_code}：{doc.error_message}</span>) : null}
        </Card>

        {/* 向量索引状态 */}
        <Card title="向量索引状态">
          {infoRow("切片总数", chunkTotal)}
          {infoRow(
            "已向量化",
            <>
              {embedded} / {Math.min(chunkTotal, CHUNK_STATS_LIMIT)}
              {chunkTotal > CHUNK_STATS_LIMIT ? (
                <span className="text-muted text-xs">（仅统计前 {CHUNK_STATS_LIMIT} 条）</span>
              ) : null}
            </>,
          )}
          {infoRow("嵌入模型", embedModels.length ? embedModels.join("、") : "—")}
          {infoRow("处理版本", `#${doc.process_version}（参数变化会生成新版本，PRD-06 §5.2）`)}
          {infoRow("文件哈希", doc.file_hash ? <span className="font-mono text-xs">{doc.file_hash.slice(0, 16)}…</span> : "—")}
        </Card>
      </div>

      {/* Keep source metadata useful for remediation without reviving the retired ledger workflow. */}
      <Card title="来源信息" className="mt-4">
        {infoRow("来源单位", doc.source_name || "—")}
        {infoRow("来源类型", SOURCE_TYPE_LABELS[doc.source_type] ?? doc.source_type)}
        {infoRow(
          "来源链接",
          doc.source_url ? (
            <a href={doc.source_url} target="_blank" rel="noreferrer">
              {doc.source_url}
            </a>
          ) : (
            "—"
          ),
        )}
        {infoRow("授权状态", <LicenseBadge status={doc.license_status} />)}
      </Card>

      {/* 只读预览保留资料处理结果，旧切片编辑器路由仍由兼容路由承接但不再是主流程入口。 */}
      <Card title={`切片列表（只读预览，共 ${chunkTotal} 条）`} className="mt-4">
        {chunks.length === 0 ? (
          <EmptyState title="暂无切片" hint="资料尚未完成解析切片，可在操作区触发重新解析" />
        ) : (
          <ul>
            {chunks.slice(0, CHUNK_PREVIEW_COUNT).map((chunk) => (
              <li key={chunk.id} className="mb-3">
                <div className="flex items-center gap-2 mb-2">
                  <Tag>切片 #{chunk.chunk_index}</Tag>
                  {chunk.section_title ? <strong className="text-sm">{chunk.section_title}</strong> : null}
                  <span className="text-xs text-muted">
                    {chunk.page_start != null
                      ? `第 ${chunk.page_start}${chunk.page_end != null && chunk.page_end !== chunk.page_start ? `-${chunk.page_end}` : ""} 页 · `
                      : ""}
                    {chunk.token_count} tokens
                  </span>
                </div>
                <p className="text-sm text-secondary" style={{ whiteSpace: "pre-wrap" }} title={chunk.content}>
                  {clamp(chunk.content, 320)}
                </p>
              </li>
            ))}
          </ul>
        )}
        {chunkTotal > CHUNK_PREVIEW_COUNT ? (
          <p className="text-sm text-muted mt-2">
            仅展示前 {CHUNK_PREVIEW_COUNT} 条；完整切片数据仍保留在资料记录中。
          </p>
        ) : null}
      </Card>

      {/* 关联能力 */}
      <Card title="关联能力 / 课程 / 任务" className="mt-4">
        {doc.cap_ids.length === 0 ? (
          <p className="text-sm text-secondary">
            未关联能力节点（可在上传时或后续编辑中补充，用于召回过滤与任务关联）。
          </p>
        ) : (
          <div className="flex gap-2" style={{ flexWrap: "wrap" }}>
            {doc.cap_ids.map((capId) => (
              <Tag key={capId}>{capNames[capId] ?? capId}</Tag>
            ))}
          </div>
        )}
      </Card>

      {/* 召回记录（学生问答与保留的历史管理检索命中日志） */}
      <Card title={`召回记录（共 ${recallTotal} 条）`} className="mt-4">
        {recallError ? (
          <div className="flex items-center gap-2">
            <span className="text-danger text-sm">{recallError}</span>
            <Button size="sm" variant="secondary" onClick={() => void loadRecall()}>
              重试
            </Button>
          </div>
        ) : (
          <>
            <DataTable
              ariaLabel="资料召回记录"
              columns={recallColumns}
              rows={recallItems}
              loading={recallLoading}
              empty={
                <EmptyState
                  title="暂无召回记录"
                  hint="该资料尚未产生可追溯的召回命中记录。"
                />
              }
            />
            <Pagination
              offset={recallOffset}
              limit={recallLimit}
              total={recallTotal}
              onChange={setRecallOffset}
              onLimitChange={(nextLimit) => {
                setRecallLimit(nextLimit);
                setRecallOffset(0);
              }}
            />
          </>
        )}
      </Card>

      {/* 版本历史（任务流水：阶段/状态/耗时/错误） */}
      <Card title="版本历史（处理任务）" className="mt-4">
        <p className="text-xs text-muted mb-2">
          当前处理版本 #{doc.process_version}；任务记录按时间倒序（任务不携带版本号，参数变化整链重跑）。
        </p>
        <DataTable
          ariaLabel="处理任务版本历史"
          columns={jobColumns}
          rows={detail.jobs}
          empty="暂无处理任务"
        />
      </Card>

      <ConfirmDialog
        open={archiveOpen}
        title="归档资料"
        confirmText="确认归档"
        description={`归档后「${doc.title}」立即退出学生端与教师端召回；切片与历史引用快照保留（PRD-06 §12.2），历史对话中的引用仍可追溯。`}
        onConfirm={async () => {
          await runAction("archive", `/api/rag/documents/${id}/archive`, "已归档");
          setArchiveOpen(false);
        }}
        onCancel={() => setArchiveOpen(false)}
      />
      <ConfirmDialog
        open={deleteOpen}
        title="删除资料"
        danger
        confirmText="确认删除"
        description={`将物理删除「${doc.title}」及其全部切片、任务与历史操作记录（操作保留审计日志）。此操作不可恢复。`}
        onConfirm={doDelete}
        onCancel={() => setDeleteOpen(false)}
      />
    </div>
  );
}
