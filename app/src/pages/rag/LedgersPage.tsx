/**
 * 已下线的来源台账组件；生产知识库入口已统一到 /admin/rag。
 *
 * 关键决策（为什么）：
 * - 风险提示直接消费后端 _ledger_dto 的 risk_* 计算（过期/未授权/缺少关联资料），
 *   前端不重复实现日期与授权判断，保证与发布守卫（publish 时校验台账）口径一致。
 * - 新建/编辑共用一个抽屉表单：source_code 是业务主键（DUPLICATE 409），
 *   编辑态锁定不可改——编号变了等于换了条台账。
 * - 关联资料标题通过资料列表做 best-effort 解析：台账 DTO 只有 id 数组，
 *   解析不到就显示 id，不阻塞详情展示。
 */

import { useCallback, useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../../api/client";
import type { Paginated, RagDocument, SourceLedger } from "../../api/types";
import {
  Button,
  Card,
  DataTable,
  Drawer,
  EmptyState,
  ErrorState,
  Field,
  Input,
  PageHeader,
  Pagination,
  Select,
  Tag,
  Textarea,
  useToast,
  type Column,
} from "../../components";
import {
  errText,
  fmtTime,
  LEDGER_REVIEW_LABELS,
  LedgerAuthBadge,
  SOURCE_TYPE_OPTIONS,
  safeRagReturnPath,
} from "./ragShared";

const DEFAULT_LIMIT = 20;

/** 抽屉表单状态（新建空表单 / 编辑预填共用） */
interface LedgerForm {
  source_code: string;
  name: string;
  publisher: string;
  source_type: string;
  version: string;
  authorization_status: string;
  valid_from: string;
  valid_to: string;
  review_status: string;
  notes: string;
}

const EMPTY_FORM: LedgerForm = {
  source_code: "",
  name: "",
  publisher: "",
  source_type: "",
  version: "",
  authorization_status: "pending",
  valid_from: "",
  valid_to: "",
  review_status: "draft",
  notes: "",
};

const AUTH_OPTIONS = [
  { value: "approved", label: "已批准" },
  { value: "pending", label: "待审批" },
  { value: "expired", label: "已过期" },
  { value: "forbidden", label: "禁止" },
];

const REVIEW_OPTIONS = [
  { value: "draft", label: "草稿" },
  { value: "reviewed", label: "已审核" },
  { value: "published", label: "已发布" },
];

function toForm(ledger: SourceLedger): LedgerForm {
  return {
    source_code: ledger.source_code,
    name: ledger.name,
    publisher: ledger.publisher ?? "",
    source_type: ledger.source_type ?? "",
    version: ledger.version ?? "",
    authorization_status: ledger.authorization_status,
    valid_from: ledger.valid_from ?? "",
    valid_to: ledger.valid_to ?? "",
    review_status: ledger.review_status,
    notes: ledger.notes ?? "",
  };
}

/** 风险提示标签（PRD-03 §9 验收：过期/未授权/缺引用位置必须可见） */
function RiskTags({ ledger }: { ledger: SourceLedger }) {
  const risks: string[] = [];
  if (ledger.risk_expired) risks.push("已过期");
  if (ledger.risk_unauthorized) risks.push("未授权");
  if (ledger.risk_no_documents) risks.push("缺少关联资料");
  if (risks.length === 0) return <span className="text-muted text-xs">无</span>;
  return (
    <span className="flex gap-1" style={{ flexWrap: "wrap" }}>
      {risks.map((r) => (
        <span key={r} className="badge badge-danger">
          {r}
        </span>
      ))}
    </span>
  );
}

export default function LedgersPage() {
  const location = useLocation();
  const returnTo = safeRagReturnPath(`${location.pathname}${location.search}`);
  const toast = useToast();
  const [items, setItems] = useState<SourceLedger[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [docTitles, setDocTitles] = useState<Record<string, string>>({});

  // 抽屉：edit=null 关闭；edit="new" 新建；否则为被编辑台账
  const [editor, setEditor] = useState<"new" | SourceLedger | null>(null);
  const [form, setForm] = useState<LedgerForm>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [detail, setDetail] = useState<SourceLedger | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<Paginated<SourceLedger>>("/api/source-ledgers", {
        limit,
        offset,
      }, { signal });
      if (signal?.aborted) return;
      setItems(res.items);
      setTotal(res.total);
    } catch (err) {
      if (!signal?.aborted) setError(errText(err, "台账加载失败"));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [offset, limit]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  // 资料标题映射：详情抽屉把 related_document_ids 解析成可读标题
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
        /* 映射失败回退显示 id */
      });
    return () => controller.abort();
  }, []);

  const openEditor = (target: "new" | SourceLedger) => {
    setFormError(null);
    setForm(target === "new" ? EMPTY_FORM : toForm(target));
    setEditor(target);
  };

  const set = (key: keyof LedgerForm) => (e: { target: { value: string } }) =>
    setForm((prev) => ({ ...prev, [key]: e.target.value }));

  const save = async () => {
    if (!form.source_code.trim() || !form.name.trim()) {
      setFormError("台账编号与来源名称不能为空");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      if (editor === "new") {
        await api.post("/api/source-ledgers", {
          source_code: form.source_code.trim(),
          name: form.name.trim(),
          publisher: form.publisher.trim() || null,
          source_type: form.source_type || null,
          version: form.version.trim() || null,
          authorization_status: form.authorization_status,
          valid_from: form.valid_from || null,
          valid_to: form.valid_to || null,
          notes: form.notes.trim() || null,
        });
        toast.success("台账已创建");
      } else if (editor) {
        await api.patch(`/api/source-ledgers/${editor.id}`, {
          name: form.name.trim(),
          publisher: form.publisher.trim() || null,
          source_type: form.source_type || null,
          version: form.version.trim() || null,
          authorization_status: form.authorization_status,
          valid_from: form.valid_from || null,
          valid_to: form.valid_to || null,
          review_status: form.review_status,
          notes: form.notes.trim() || null,
        });
        toast.success("台账已更新");
      }
      setEditor(null);
      await load();
    } catch (err) {
      setFormError(errText(err));
    } finally {
      setSaving(false);
    }
  };

  const columns: Column<SourceLedger>[] = [
    { key: "source_code", title: "台账编号", width: "130px", render: (l) => <span className="font-mono text-sm">{l.source_code}</span> },
    {
      key: "name",
      title: "来源名称",
      render: (l) => (
        <button type="button" className="dropdown-item" style={{ padding: 0, color: "var(--color-primary)" }} onClick={() => setDetail(l)}>
          {l.name}
        </button>
      ),
    },
    { key: "source_type", title: "类型", width: "90px", render: (l) => SOURCE_TYPE_OPTIONS.find((o) => o.value === l.source_type)?.label ?? l.source_type ?? "—" },
    { key: "publisher", title: "发布单位", render: (l) => l.publisher ?? "—" },
    { key: "version", title: "版本", width: "70px", render: (l) => l.version ?? "—" },
    { key: "auth", title: "授权状态", width: "100px", render: (l) => <LedgerAuthBadge status={l.authorization_status} /> },
    {
      key: "validity",
      title: "有效期",
      width: "180px",
      render: (l) => (
        <span className="text-sm text-secondary">
          {l.valid_from || l.valid_to ? `${l.valid_from ?? "—"} ~ ${l.valid_to ?? "—"}` : "长期"}
        </span>
      ),
    },
    { key: "risk", title: "风险提示", width: "160px", render: (l) => <RiskTags ledger={l} /> },
    {
      key: "actions",
      title: "操作",
      width: "130px",
      render: (l) => (
        <div className="flex gap-1">
          <Button size="sm" variant="ghost" onClick={() => setDetail(l)}>
            详情
          </Button>
          <Button size="sm" variant="secondary" onClick={() => openEditor(l)}>
            编辑
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="来源台账"
        sub="每条面向学生的专业规则必须绑定来源台账；过期或未授权来源不得发布"
        actions={
          <Button onClick={() => openEditor("new")}>新建台账</Button>
        }
      />

      {error ? (
        <ErrorState message={error} onRetry={() => void load()} />
      ) : (
        <>
          <DataTable
            ariaLabel="来源台账列表"
            columns={columns}
            rows={items}
            loading={loading}
            empty={<EmptyState title="暂无台账" hint="新建来源台账后，上传资料时可绑定作为权威来源" />}
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

      {/* 新建/编辑抽屉 */}
      <Drawer
        open={editor !== null}
        title={editor === "new" ? "新建台账" : `编辑台账：${form.source_code}`}
        onClose={() => setEditor(null)}
      >
        {formError ? <p className="form-alert form-alert-error" role="alert">{formError}</p> : null}
        <Field label="台账编号" required hint="业务主键，创建后不可修改">
          <Input
            value={form.source_code}
            onChange={set("source_code")}
            disabled={editor !== "new"}
            placeholder="例如：SRC-2026-001"
          />
        </Field>
        <Field label="来源名称" required>
          <Input value={form.name} onChange={set("name")} placeholder="例如：智能客服语音标注规范" />
        </Field>
        <Field label="发布单位">
          <Input value={form.publisher} onChange={set("publisher")} />
        </Field>
        <Field label="来源类型">
          <Select
            value={form.source_type}
            onChange={set("source_type")}
            options={[...SOURCE_TYPE_OPTIONS]}
            placeholder="未设置"
          />
        </Field>
        <Field label="版本">
          <Input value={form.version} onChange={set("version")} placeholder="例如：2.3" />
        </Field>
        <Field label="授权状态" required hint="未批准的台账关联资料不能发布">
          <Select value={form.authorization_status} onChange={set("authorization_status")} options={AUTH_OPTIONS} />
        </Field>
        <div className="grid grid-cols-2">
          <Field label="有效期起">
            <Input type="date" value={form.valid_from} onChange={set("valid_from")} />
          </Field>
          <Field label="有效期止" hint="过期后关联资料不能发布">
            <Input type="date" value={form.valid_to} onChange={set("valid_to")} />
          </Field>
        </div>
        {editor !== "new" ? (
          <Field label="审核状态">
            <Select value={form.review_status} onChange={set("review_status")} options={REVIEW_OPTIONS} />
          </Field>
        ) : null}
        <Field label="适用规则 / 备注">
          <Textarea value={form.notes} onChange={set("notes")} placeholder="该来源适用的规则范围、使用限制等" />
        </Field>
        <div className="flex gap-2 mt-4">
          <Button loading={saving} onClick={() => void save()}>
            {editor === "new" ? "创建台账" : "保存修改"}
          </Button>
          <Button variant="ghost" onClick={() => setEditor(null)}>
            取消
          </Button>
        </div>
      </Drawer>

      {/* 详情抽屉 */}
      <Drawer open={detail !== null} title={detail ? `${detail.source_code} · ${detail.name}` : ""} onClose={() => setDetail(null)}>
        {detail ? (
          <div>
            <div className="flex gap-2 mb-4" style={{ flexWrap: "wrap" }}>
              <LedgerAuthBadge status={detail.authorization_status} />
              <span className="badge badge-neutral">
                {LEDGER_REVIEW_LABELS[detail.review_status] ?? detail.review_status}
              </span>
              <RiskTags ledger={detail} />
            </div>
            <Card title="基本信息" className="mb-4">
              <p className="text-sm mb-2">发布单位：{detail.publisher ?? "—"}</p>
              <p className="text-sm mb-2">版本：{detail.version ?? "—"}</p>
              <p className="text-sm mb-2">
                有效期：{detail.valid_from || detail.valid_to ? `${detail.valid_from ?? "—"} ~ ${detail.valid_to ?? "—"}` : "长期"}
              </p>
              <p className="text-sm mb-2">创建：{fmtTime(detail.created_at)}　更新：{fmtTime(detail.updated_at)}</p>
            </Card>
            <Card title={`关联资料（${detail.related_document_ids.length}）`} className="mb-4">
              {detail.related_document_ids.length === 0 ? (
                <p className="text-sm text-secondary">
                  暂无关联资料——上传资料时在"关联来源台账"中选择本台账即可绑定。
                </p>
              ) : (
                <ul>
                  {detail.related_document_ids.map((docId) => (
                    <li key={docId} className="mb-2 text-sm">
                      <Link
                        to={`/admin/rag/documents/${docId}?returnTo=${encodeURIComponent(returnTo)}`}
                        state={{ returnTo }}
                      >
                        {docTitles[docId] ?? `${docId.slice(0, 8)}…`}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="适用规则 / 备注">
              <p className="text-sm text-secondary" style={{ whiteSpace: "pre-wrap" }}>
                {detail.notes || "—"}
              </p>
            </Card>
            <div className="mt-4">
              <Button
                variant="secondary"
                onClick={() => {
                  setDetail(null);
                  openEditor(detail);
                }}
              >
                编辑该台账
              </Button>
            </div>
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}
