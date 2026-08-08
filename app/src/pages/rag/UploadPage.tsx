/**
 * 资料上传（/rag-admin/upload）——拖拽上传 + 元数据 + 处理配置（PRD-03 §5）。
 *
 * 关键规则（为什么）：
 * - 来源（source_name）与授权状态（license_status）未填时前端直接拦截提交
 *   （PRD-03 §5.3 验收："未填写来源和授权状态时不得上传"），其余必填项与
 *   后端 upload_document 的 422 校验一一对应，错误落到字段旁。
 * - 多值字段（data_types/scenario_ids/cap_ids）按 FastAPI `list[str] = Form`
 *   契约用同名重复 append，不能 JSON 序列化成单值。
 * - 切片参数不在本页配置：后端上传固定读取系统 RAG 参数（rag_admin.py
 *   _default_stage_params），页面如实说明，不假装可配。
 * - 上传响应是 202 + 同步管线结果：展示最终状态与任务，并提示可去任务队列
 *   查看解析日志（PRD-03 §5.3"上传完成后可查看解析日志"）。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type {
  DocumentPipelineResponse,
  GraphNode,
  Paginated,
  SourceLedger,
} from "../../api/types";
import {
  Button,
  Card,
  Field,
  Input,
  PageHeader,
  Select,
  StatusBadge,
  Tag,
  useToast,
} from "../../components";
import {
  DATA_TYPE_OPTIONS,
  errText,
  LEDGER_AUTH_LABELS,
  LICENSE_OPTIONS,
  SCENARIO_OPTIONS,
  SOURCE_TYPE_OPTIONS,
  VISIBILITY_OPTIONS,
} from "./ragShared";

/** 上传约束与后端一致（rag_admin.py MAX_UPLOAD_BYTES / parsers.py SUPPORTED_FILE_TYPES：
 *  pdf/docx/md/txt/csv/xlsx 六种；file_type 由后端按扩展名映射，前端不重复推导） */
const MAX_BYTES = 50 * 1024 * 1024;
const ACCEPT = ".pdf,.docx,.md,.markdown,.txt,.csv,.xlsx,.xls";

interface SelectedCap {
  id: string;
  label: string;
}

export default function UploadPage() {
  const toast = useToast();

  // ---- 文件 ----
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ---- 元数据（PRD-03 §5.2 必填项 + 台账/能力关联） ----
  const [title, setTitle] = useState("");
  const [sourceType, setSourceType] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [ledgerId, setLedgerId] = useState("");
  const [version, setVersion] = useState("");
  const [dataTypes, setDataTypes] = useState<string[]>([]);
  const [scenarioIds, setScenarioIds] = useState<string[]>([]);
  const [caps, setCaps] = useState<SelectedCap[]>([]);
  const [visibility, setVisibility] = useState("teacher");
  const [licenseStatus, setLicenseStatus] = useState("");
  const [autoSubmit, setAutoSubmit] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // ---- 台账选项（来源链接或台账二选一关联） ----
  const [ledgers, setLedgers] = useState<SourceLedger[]>([]);

  // ---- 能力节点搜索 ----
  const [capQuery, setCapQuery] = useState("");
  const [capResults, setCapResults] = useState<GraphNode[]>([]);
  const [capSearching, setCapSearching] = useState(false);

  // ---- 提交状态 ----
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<DocumentPipelineResponse | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    // 台账下拉：授权状态一并展示，避免误绑未批准来源（发布守卫会拦截）
    api
      .get<Paginated<SourceLedger>>("/api/source-ledgers", { limit: 100 }, { signal: controller.signal })
      .then((res) => {
        if (!controller.signal.aborted) setLedgers(res.items);
      })
      .catch(() => {
        // 台账加载失败不阻断上传主流程（来源链接仍可手填）
      });
    return () => controller.abort();
  }, []);

  /** 文件选取统一入口：类型/大小前端先拦，少一次必败的往返 */
  const pickFile = (f: File | null | undefined) => {
    setFileError(null);
    if (!f) return;
    const ext = `.${f.name.split(".").pop()?.toLowerCase() ?? ""}`;
    if (!ACCEPT.split(",").includes(ext)) {
      setFileError("仅支持 PDF / Word(docx) / Markdown / TXT / CSV / Excel 文件");
      return;
    }
    if (f.size > MAX_BYTES) {
      setFileError("文件超过 50MB 上限，请拆分后再上传");
      return;
    }
    if (f.size === 0) {
      setFileError("文件内容为空");
      return;
    }
    setFile(f);
    // 标题留空时用文件名兜底（仍可改）：减少重复录入
    if (!title.trim()) setTitle(f.name.replace(/\.[^.]+$/, ""));
  };

  const toggleIn = (list: string[], value: string, set: (v: string[]) => void) => {
    set(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  };

  /** 能力节点搜索（图谱 CAP 节点；保持已选项不被搜索结果覆盖） */
  const searchCaps = useCallback(async (signal?: AbortSignal) => {
    if (signal?.aborted) return;
    const q = capQuery.trim();
    if (!q) {
      setCapResults([]);
      return;
    }
    setCapSearching(true);
    try {
      const res = await api.get<{ items: GraphNode[] }>("/api/graph/nodes", {
        q,
        type: "CAP",
        limit: 10,
      }, { signal });
      if (signal?.aborted) return;
      setCapResults(res.items.filter((n) => !caps.some((c) => c.id === n.id)));
    } catch {
      if (!signal?.aborted) setCapResults([]);
    } finally {
      if (!signal?.aborted) setCapSearching(false);
    }
  }, [capQuery, caps]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => void searchCaps(controller.signal), 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [searchCaps]);

  /** 提交前校验：与后端 422 口径一致，来源/授权状态是 PRD 硬性验收 */
  const validate = (): boolean => {
    const errors: Record<string, string> = {};
    if (!file) errors.file = "请选择要上传的文件";
    if (!title.trim()) errors.title = "请填写资料标题";
    if (!sourceType) errors.sourceType = "请选择资料类型";
    if (!sourceName.trim()) errors.sourceName = "请填写来源（未填来源不得上传）";
    if (!version.trim()) errors.version = "请填写版本号";
    if (dataTypes.length === 0) errors.dataTypes = "请至少选择一种适用数据类型";
    if (!licenseStatus) errors.licenseStatus = "请选择授权状态（未填授权状态不得上传）";
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const submit = async () => {
    if (!validate() || !file) return;
    setSubmitting(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("title", title.trim());
      form.append("source_type", sourceType);
      form.append("source_name", sourceName.trim());
      if (sourceUrl.trim()) form.append("source_url", sourceUrl.trim());
      if (ledgerId) form.append("source_ledger_id", ledgerId);
      form.append("version", version.trim());
      form.append("license_status", licenseStatus);
      form.append("visibility", visibility);
      // 多值字段：同名重复 append（FastAPI list[str] = Form 契约）
      dataTypes.forEach((v) => form.append("data_types", v));
      scenarioIds.forEach((v) => form.append("scenario_ids", v));
      caps.forEach((c) => form.append("cap_ids", c.id));
      form.append("auto_submit", autoSubmit ? "true" : "false");
      const res = await api.postForm<DocumentPipelineResponse>("/api/rag/documents", form);
      setResult(res);
      toast.success("上传成功，已进入处理流程");
    } catch (err) {
      toast.error(errText(err, "上传失败，请稍后重试"));
    } finally {
      setSubmitting(false);
    }
  };

  // ---- 上传成功态：状态 + 任务 + 详情/队列入口（PRD-03 §5.3） ----
  if (result) {
    return (
      <div>
        <PageHeader title="上传资料" sub="上传完成" />
        <Card title="上传成功">
          <div className="flex flex-col gap-3">
            <p>
              「{result.document.title}」已进入异步处理队列，可查看解析日志；学生端召回还需
              <strong>送审并通过发布审核</strong>。
            </p>
            <p className="flex items-center gap-2">
              当前状态：<StatusBadge status={result.document.status} />
              <Tag>{result.document.chunk_count ?? 0} 个切片</Tag>
              {result.document.error_message ? (
                <span className="text-danger text-sm">{result.document.error_message}</span>
              ) : null}
            </p>
            <div className="flex gap-2 mt-2">
              <Link to={`/rag-admin/documents/${result.document.id}`} className="btn btn-primary">
                查看资料详情
              </Link>
              <Link to="/rag-admin/jobs" className="btn btn-secondary">
                查看解析日志（任务队列）
              </Link>
              <Button variant="ghost" onClick={() => setResult(null)}>
                继续上传
              </Button>
            </div>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="上传资料"
        sub="支持 PDF / Word / Markdown / TXT / CSV / Excel，单文件不超过 50MB；上传后进入解析 → 切片 → 索引流程"
      />

      {/* 上传区（PRD-03 §5.1：拖拽 + 文件选择） */}
      <Card title="文件上传" className="mb-4">
        <div
          role="button"
          tabIndex={0}
          aria-label="拖拽或点击选择文件"
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            pickFile(e.dataTransfer.files?.[0]);
          }}
          onClick={() => fileInputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") fileInputRef.current?.click();
          }}
          style={{
            border: `2px dashed ${dragOver ? "var(--color-primary)" : "var(--color-border-strong)"}`,
            borderRadius: "var(--radius-lg)",
            padding: "var(--space-8)",
            textAlign: "center",
            cursor: "pointer",
            background: dragOver ? "var(--color-primary-soft)" : "transparent",
          }}
        >
          {file ? (
            <p>
              已选择：<strong>{file.name}</strong>（{(file.size / 1024 / 1024).toFixed(2)} MB）
              <span className="text-secondary text-sm">　点击可重新选择</span>
            </p>
          ) : (
            <p className="text-secondary">
              拖拽文件到此处，或点击选择文件
              <br />
              <span className="text-xs text-muted">支持 PDF/Word/Markdown/TXT/CSV/Excel</span>
              <br />
              <span className="text-xs text-muted">
                Excel 按 sheet 切块入库，CSV 按行聚合切块；大表格建议先拆分主题再上传
              </span>
            </p>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPT}
            hidden
            aria-label="选择文件"
            onChange={(e) => pickFile(e.target.files?.[0])}
          />
        </div>
        {fileError || fieldErrors.file ? (
          <p className="field-error-text mt-2">{fileError ?? fieldErrors.file}</p>
        ) : null}
      </Card>

      {/* 元数据（PRD-03 §5.2 必填表） */}
      <Card title="元数据" className="mb-4">
        <div className="grid grid-cols-2">
          <Field label="资料标题" required error={fieldErrors.title} hint="学生端引用来源展示名">
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：智能客服语音标注规范" />
          </Field>
          <Field label="资料类型" required error={fieldErrors.sourceType}>
            <Select
              aria-label="资料类型"
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value)}
              options={[...SOURCE_TYPE_OPTIONS]}
              placeholder="请选择资料类型"
            />
          </Field>
          <Field label="来源单位 / 作者" required error={fieldErrors.sourceName} hint="未填来源不得上传">
            <Input value={sourceName} onChange={(e) => setSourceName(e.target.value)} placeholder="例如：工业和信息化部 / 张老师" />
          </Field>
          <Field label="版本号" required error={fieldErrors.version} hint="资料变更追踪，例如 2.3">
            <Input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="例如：1.0" />
          </Field>
          <Field label="来源链接（可选）">
            <Input value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} placeholder="https://…" />
          </Field>
          <Field label="关联来源台账（可选）" hint="绑定台账的资料发布时校验台账授权与有效期">
            <Select
              aria-label="关联来源台账"
              value={ledgerId}
              onChange={(e) => setLedgerId(e.target.value)}
              options={ledgers.map((l) => ({
                value: l.id,
                label: `${l.source_code} · ${l.name}（${LEDGER_AUTH_LABELS[l.authorization_status] ?? l.authorization_status}）`,
              }))}
              placeholder="不关联台账"
            />
          </Field>
        </div>

        <Field label="适用数据类型" required error={fieldErrors.dataTypes}>
          <div className="flex gap-3" style={{ flexWrap: "wrap" }}>
            {DATA_TYPE_OPTIONS.map((opt) => (
              <label key={opt.value} className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={dataTypes.includes(opt.value)}
                  onChange={() => toggleIn(dataTypes, opt.value, setDataTypes)}
                />
                {opt.label}
              </label>
            ))}
          </div>
        </Field>

        <Field label="适用行业场景" hint="不选择默认为通用场景">
          <div className="flex gap-3" style={{ flexWrap: "wrap" }}>
            {SCENARIO_OPTIONS.filter((s) => s.id !== "").map((s) => (
              <label key={s.id} className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={scenarioIds.includes(s.id)}
                  onChange={() => toggleIn(scenarioIds, s.id, setScenarioIds)}
                />
                {s.name}
              </label>
            ))}
          </div>
        </Field>

        <Field label="关联能力节点" hint="搜索图谱能力节点并添加，用于召回过滤与任务关联">
          <Input
            value={capQuery}
            onChange={(e) => setCapQuery(e.target.value)}
            placeholder="搜索能力节点，例如：语音标注"
          />
          {caps.length > 0 ? (
            <div className="flex gap-2 mt-2" style={{ flexWrap: "wrap" }}>
              {caps.map((cap) => (
                <span key={cap.id} className="tag">
                  {cap.label}
                  <button
                    type="button"
                    aria-label={`移除 ${cap.label}`}
                    className="icon-btn"
                    style={{ width: 18, height: 18, marginLeft: 4 }}
                    onClick={() => setCaps(caps.filter((c) => c.id !== cap.id))}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          ) : null}
          {capSearching ? <p className="field-hint">搜索中…</p> : null}
          {!capSearching && capResults.length > 0 ? (
            <ul className="mt-2">
              {capResults.map((node) => (
                <li key={node.id} className="flex items-center justify-between mb-2">
                  <span className="text-sm">
                    {node.label} <span className="text-muted font-mono text-xs">{node.id}</span>
                  </span>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      setCaps([...caps, { id: node.id, label: node.label }]);
                      setCapResults(capResults.filter((n) => n.id !== node.id));
                    }}
                  >
                    添加
                  </Button>
                </li>
              ))}
            </ul>
          ) : null}
        </Field>

        <div className="grid grid-cols-2">
          <Field label="可见范围" required hint="发布后谁能召回该资料">
            <Select
              aria-label="可见范围"
              value={visibility}
              onChange={(e) => setVisibility(e.target.value)}
              options={[...VISIBILITY_OPTIONS]}
            />
          </Field>
          <Field label="授权状态" required error={fieldErrors.licenseStatus} hint="确认资料可用于教学系统">
            <Select
              aria-label="授权状态"
              value={licenseStatus}
              onChange={(e) => setLicenseStatus(e.target.value)}
              options={[...LICENSE_OPTIONS]}
              placeholder="请选择授权状态"
            />
          </Field>
        </div>
        {licenseStatus === "forbidden" ? (
          <p className="form-alert form-alert-error" role="alert">
            授权状态为"禁止"的资料将不能发布，仅可作为内部存档。
          </p>
        ) : null}
        {licenseStatus === "pending" ? (
          <p className="form-alert form-alert-error" role="alert" style={{ background: "var(--color-warning-soft)", color: "var(--color-warning)" }}>
            授权状态为"待确认"的资料可解析入库，但完成授权确认前不能发布。
          </p>
        ) : null}
      </Card>

      {/* 处理配置（PRD-03 §5.1） */}
      <Card title="处理配置" className="mb-4">
        <p className="text-sm text-secondary mb-3">
          切片策略使用系统默认切片参数（chunk_size / overlap 由系统管理端 RAG 参数统一配置），
          上传后按当前参数生成处理版本。
        </p>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={autoSubmit}
            onChange={(e) => setAutoSubmit(e.target.checked)}
          />
          处理完成后自动送审（仍需人工审核通过才能发布）
        </label>
      </Card>

      <div className="flex gap-2">
        <Button size="lg" loading={submitting} onClick={() => void submit()}>
          {submitting ? "上传处理中（大文件可能需要数十秒）…" : "确认上传"}
        </Button>
        <Link to="/rag-admin" className="btn btn-ghost btn-lg">
          返回资料库
        </Link>
      </div>
    </div>
  );
}
