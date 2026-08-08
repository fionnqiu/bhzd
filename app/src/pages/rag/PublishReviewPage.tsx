/**
 * 发布审核（/rag-admin/publish）——待发布队列 + 审核抽屉 + 发布记录（PRD-03 §2 发布审核）。
 *
 * 关键决策（为什么）：
 * - 待发布列表用 /api/rag/review-queue 而不是裸 documents 查询：它 JOIN 了
 *   上传人姓名与提交时间（documents DTO 只有 created_by id）；该队列由
 *   system_admin 专用的 RAG 管理门户读取。
 * - 审核抽屉一次性拉取详情 + 切片抽样：审核人必须在发布前看到来源台账、
 *   敏感信息标志与切片质量（PRD-06 §4.2 发布守卫的人工前置检查）。
 * - 审核意见只服务于驳回（后端 publish 不接受 comment，reject 接受）；
 *   驳回必须填意见——没有意见的驳回对上传人是不可行动的死信。
 * - 发布记录合并 published/rejected 两态按时间倒序；审核流水在抽屉里展示
 *   （review_records 只在详情响应里，列表响应没有）。
 */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type {
  DocumentDetailResponse,
  Paginated,
  RagChunk,
  RagDocument,
  ReviewQueueItem,
} from "../../api/types";
import {
  Button,
  Card,
  DataTable,
  Drawer,
  EmptyState,
  ErrorState,
  Field,
  PageHeader,
  StatusBadge,
  Tabs,
  Tag,
  Textarea,
  useToast,
  type Column,
} from "../../components";
import {
  clamp,
  errText,
  fmtTime,
  LICENSE_LABELS,
  REVIEW_ACTION_LABELS,
  scenarioLabel,
  SOURCE_TYPE_LABELS,
  VISIBILITY_LABELS,
} from "./ragShared";

/** 发布记录每态拉取条数（记录页是回顾视图，不需要深分页） */
const RECORDS_LIMIT = 15;

interface ReviewTarget {
  docId: string;
  title: string;
  /** review=待审核可操作；view=记录回看只读 */
  mode: "review" | "view";
}

export default function PublishReviewPage() {
  const toast = useToast();
  const [tab, setTab] = useState("pending");

  // ---- 待发布队列 ----
  const [queue, setQueue] = useState<ReviewQueueItem[]>([]);
  const [queueLoading, setQueueLoading] = useState(true);
  const [queueError, setQueueError] = useState<string | null>(null);

  // ---- 发布记录 ----
  const [records, setRecords] = useState<RagDocument[]>([]);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [recordsError, setRecordsError] = useState<string | null>(null);

  // ---- 审核抽屉 ----
  const [target, setTarget] = useState<ReviewTarget | null>(null);
  const [detail, setDetail] = useState<DocumentDetailResponse | null>(null);
  const [sampleChunks, setSampleChunks] = useState<RagChunk[]>([]);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [scope, setScope] = useState<"student" | "teacher">("student");
  const [acting, setActing] = useState<"publish" | "reject" | null>(null);

  const loadQueue = useCallback(async (signal?: AbortSignal) => {
    setQueueLoading(true);
    setQueueError(null);
    try {
      const res = await api.get<Paginated<ReviewQueueItem>>("/api/rag/review-queue", undefined, { signal });
      if (signal?.aborted) return;
      setQueue(res.items);
    } catch (err) {
      if (!signal?.aborted) setQueueError(errText(err, "待发布列表加载失败"));
    } finally {
      if (!signal?.aborted) setQueueLoading(false);
    }
  }, []);

  const loadRecords = useCallback(async (signal?: AbortSignal) => {
    setRecordsLoading(true);
    setRecordsError(null);
    try {
      const [published, rejected] = await Promise.all([
        api.get<Paginated<RagDocument>>("/api/rag/documents", {
          status: "published",
          limit: RECORDS_LIMIT,
        }, { signal }),
        api.get<Paginated<RagDocument>>("/api/rag/documents", {
          status: "rejected",
          limit: RECORDS_LIMIT,
        }, { signal }),
      ]);
      if (signal?.aborted) return;
      const merged = [...published.items, ...rejected.items].sort((a, b) =>
        b.updated_at.localeCompare(a.updated_at),
      );
      setRecords(merged);
    } catch (err) {
      if (!signal?.aborted) setRecordsError(errText(err, "发布记录加载失败"));
    } finally {
      if (!signal?.aborted) setRecordsLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadQueue(controller.signal);
    return () => controller.abort();
  }, [loadQueue]);

  useEffect(() => {
    if (tab !== "records") return;
    const controller = new AbortController();
    void loadRecords(controller.signal);
    return () => controller.abort();
  }, [tab, loadRecords]);

  /** 打开审核/回看抽屉：拉详情 + 前 3 条切片抽样 */
  const openReview = async (t: ReviewTarget) => {
    setTarget(t);
    setDetail(null);
    setSampleChunks([]);
    setDetailError(null);
    setComment("");
    setScope("student");
    try {
      const [detailRes, chunkRes] = await Promise.all([
        api.get<DocumentDetailResponse>(`/api/rag/documents/${t.docId}`),
        api.get<Paginated<RagChunk>>(`/api/rag/documents/${t.docId}/chunks`, { limit: 3 }),
      ]);
      setDetail(detailRes);
      setSampleChunks(chunkRes.items);
    } catch (err) {
      setDetailError(errText(err, "资料详情加载失败"));
    }
  };

  const doPublish = async () => {
    if (!target) return;
    setActing("publish");
    try {
      await api.post(`/api/rag/documents/${target.docId}/publish`, { scope });
      toast.success(scope === "student" ? "已发布，学生端可召回" : "已发布（仅教师可见）");
      setTarget(null);
      await loadQueue();
    } catch (err) {
      // 发布守卫（LICENSE_BLOCKED/CHUNK_EMPTY/SENSITIVE_INFO_BLOCKED 等）原样透出
      toast.error(errText(err));
    } finally {
      setActing(null);
    }
  };

  const doReject = async () => {
    if (!target) return;
    if (!comment.trim()) {
      toast.error("驳回必须填写审核意见");
      return;
    }
    setActing("reject");
    try {
      await api.post(`/api/rag/documents/${target.docId}/reject`, { comment: comment.trim() });
      toast.success("已驳回，该资料不参与召回");
      setTarget(null);
      await loadQueue();
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setActing(null);
    }
  };

  const queueColumns: Column<ReviewQueueItem>[] = [
    { key: "title", title: "标题", render: (item) => <Link to={`/rag-admin/documents/${item.id}`}>{item.title}</Link> },
    { key: "uploader_name", title: "上传人", width: "110px", render: (item) => item.uploader_name ?? "—" },
    {
      key: "source_type",
      title: "来源",
      width: "100px",
      render: (item) => SOURCE_TYPE_LABELS[item.source_type] ?? item.source_type,
    },
    {
      key: "scenario_ids",
      title: "场景",
      render: (item) =>
        item.scenario_ids.length > 0
          ? item.scenario_ids.map((s) => <Tag key={s}>{scenarioLabel(s)}</Tag>)
          : <Tag>通用</Tag>,
    },
    {
      key: "submitted_at",
      title: "提交时间",
      width: "150px",
      render: (item) => <span className="text-sm text-secondary">{fmtTime(item.submitted_at)}</span>,
    },
    {
      key: "actions",
      title: "操作",
      width: "100px",
      render: (item) => (
        <Button size="sm" onClick={() => void openReview({ docId: item.id, title: item.title, mode: "review" })}>
          审核
        </Button>
      ),
    },
  ];

  const recordColumns: Column<RagDocument>[] = [
    { key: "title", title: "标题", render: (doc) => <Link to={`/rag-admin/documents/${doc.id}`}>{doc.title}</Link> },
    { key: "status", title: "结果", width: "100px", render: (doc) => <StatusBadge status={doc.status} /> },
    {
      key: "source_name",
      title: "来源",
      render: (doc) => (
        <span className="text-sm">{SOURCE_TYPE_LABELS[doc.source_type] ?? doc.source_type} · {doc.source_name}</span>
      ),
    },
    {
      key: "updated_at",
      title: "处理时间",
      width: "150px",
      render: (doc) => <span className="text-sm text-secondary">{fmtTime(doc.updated_at)}</span>,
    },
    {
      key: "actions",
      title: "操作",
      width: "100px",
      render: (doc) => (
        <Button size="sm" variant="secondary" onClick={() => void openReview({ docId: doc.id, title: doc.title, mode: "view" })}>
          查看
        </Button>
      ),
    },
  ];

  const doc = detail?.document ?? null;
  const flags = detail?.sensitive_flags as { phone?: number; id_card?: number; email?: number; block_publish?: boolean } | null;
  const hasFlags = !!flags && ((flags.phone ?? 0) > 0 || (flags.id_card ?? 0) > 0 || (flags.email ?? 0) > 0);

  return (
    <div>
      <PageHeader
        title="发布审核"
        sub="审核待发布资料的来源、切片与敏感信息，决定发布范围或驳回；发布与驳回均写入审计日志"
      />
      <Tabs
        tabs={[
          { key: "pending", label: `待发布（${queue.length}）` },
          { key: "records", label: "发布记录" },
        ]}
        active={tab}
        onChange={setTab}
      />

      {tab === "pending" ? (
        queueError ? (
          <ErrorState message={queueError} onRetry={() => void loadQueue()} />
        ) : (
          <DataTable
            ariaLabel="待发布资料列表"
            columns={queueColumns}
            rows={queue}
            loading={queueLoading}
            empty={<EmptyState title="没有待审核资料" hint="资料送审后会出现在这里" />}
          />
        )
      ) : recordsError ? (
        <ErrorState message={recordsError} onRetry={() => void loadRecords()} />
      ) : (
        <DataTable
          ariaLabel="发布记录列表"
          columns={recordColumns}
          rows={records}
          loading={recordsLoading}
          empty={<EmptyState title="暂无发布记录" hint="通过或驳回的资料会记录在这里" />}
        />
      )}
      <p className="text-xs text-muted mt-2">发布与驳回均写入审计日志，可在系统管理端审计日志中追溯。</p>

      {/* 审核抽屉 */}
      <Drawer open={target !== null} title={target ? `审核：${target.title}` : ""} onClose={() => setTarget(null)}>
        {detailError ? (
          <ErrorState message={detailError} onRetry={() => target && void openReview(target)} />
        ) : !detail ? (
          <p className="text-sm text-secondary">正在加载资料详情…</p>
        ) : (
          <div>
            {/* 预览：元数据 + 状态 */}
            <div className="flex items-center gap-2 mb-3" style={{ flexWrap: "wrap" }}>
              {doc ? <StatusBadge status={doc.status} /> : null}
              {doc ? <Tag>v{doc.version}</Tag> : null}
              {doc ? <Tag>{VISIBILITY_LABELS[doc.visibility]}</Tag> : null}
              {doc ? <Tag>{LICENSE_LABELS[doc.license_status]}</Tag> : null}
            </div>
            {doc ? (
              <div className="mb-4 text-sm">
                <p className="mb-2">来源：{SOURCE_TYPE_LABELS[doc.source_type]} · {doc.source_name}</p>
                <p className="mb-2">
                  场景：{doc.scenario_ids.length ? doc.scenario_ids.map(scenarioLabel).join("、") : "通用"}
                </p>
                <p className="mb-2">切片数：{doc.chunk_count ?? 0}</p>
              </div>
            ) : null}

            {/* 敏感信息（阻止发布的必须醒目） */}
            {hasFlags ? (
              <p className="form-alert form-alert-error" role="alert">
                敏感信息：
                {(flags?.id_card ?? 0) > 0 ? `身份证 ${flags?.id_card} 处（阻止发布）；` : ""}
                {(flags?.phone ?? 0) > 0 ? `手机号 ${flags?.phone} 处；` : ""}
                {(flags?.email ?? 0) > 0 ? `邮箱 ${flags?.email} 处` : ""}
              </p>
            ) : null}

            {/* 来源台账 */}
            <Card title="来源台账" className="mb-4">
              {detail.ledger ? (
                <p className="text-sm">
                  {detail.ledger.source_code} · {detail.ledger.name}（{detail.ledger.authorization_status === "approved" ? "已批准" : "未批准/已过期"}）
                </p>
              ) : (
                <p className="text-sm text-secondary">未关联台账</p>
              )}
            </Card>

            {/* 切片抽样 */}
            <Card title="切片抽样（前 3 条）" className="mb-4">
              {sampleChunks.length === 0 ? (
                <p className="text-sm text-danger">无切片——切片为空不能发布</p>
              ) : (
                sampleChunks.map((chunk) => (
                  <div key={chunk.id} className="mb-3">
                    <div className="flex items-center gap-2 mb-2">
                      <Tag>#{chunk.chunk_index}</Tag>
                      {chunk.section_title ? <strong className="text-sm">{chunk.section_title}</strong> : null}
                    </div>
                    <p className="text-sm text-secondary">{clamp(chunk.content, 140)}</p>
                  </div>
                ))
              )}
              {doc ? (
                <Link to={`/rag-admin/documents/${doc.id}/chunks`} className="text-sm">
                  打开切片编辑器 →
                </Link>
              ) : null}
            </Card>

            {/* 关联能力 */}
            {doc && doc.cap_ids.length > 0 ? (
              <Card title="关联能力" className="mb-4">
                <div className="flex gap-1" style={{ flexWrap: "wrap" }}>
                  {doc.cap_ids.map((capId) => (
                    <Tag key={capId}>{capId}</Tag>
                  ))}
                </div>
              </Card>
            ) : null}

            {/* 审核记录（回看模式重点） */}
            {detail.review_records.length > 0 ? (
              <Card title="审核记录" className="mb-4">
                <ul>
                  {detail.review_records.map((r) => (
                    <li key={r.id} className="mb-2 text-sm">
                      <strong>{REVIEW_ACTION_LABELS[r.action] ?? r.action}</strong>
                      <span className="text-muted">　{fmtTime(r.created_at)}</span>
                      {r.comment ? <p className="text-secondary">{r.comment}</p> : null}
                    </li>
                  ))}
                </ul>
              </Card>
            ) : null}

            {/* 审核操作（仅待审核模式） */}
            {target?.mode === "review" ? (
              <div>
                <Field label="审核意见（驳回时必填）">
                  <Textarea
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    placeholder="例如：第 3 章缺少标注示例，请补充后重新送审"
                  />
                </Field>
                <Field label="发布范围">
                  <label className="flex items-center gap-2">
                    <input type="radio" name="review-scope" checked={scope === "student"} onChange={() => setScope("student")} />
                    学生端可见
                  </label>
                  <label className="flex items-center gap-2">
                    <input type="radio" name="review-scope" checked={scope === "teacher"} onChange={() => setScope("teacher")} />
                    仅教师可见
                  </label>
                </Field>
                <div className="flex gap-2 mt-4">
                  <Button loading={acting === "publish"} onClick={() => void doPublish()}>
                    通过发布
                  </Button>
                  <Button variant="danger" loading={acting === "reject"} onClick={() => void doReject()}>
                    驳回
                  </Button>
                </div>
                <p className="text-xs text-muted mt-2">发布与驳回均写入审计日志。</p>
              </div>
            ) : null}
          </div>
        )}
      </Drawer>
    </div>
  );
}
