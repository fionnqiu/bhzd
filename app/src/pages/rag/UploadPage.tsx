/**
 * 系统管理 · 资料上传（/admin/rag/upload）——文件优先 + 可选元数据（PRD-03 §5）。
 *
 * 关键规则（为什么）：
 * - 文件是唯一必填项；留空的高级元数据由服务端写入可追溯的安全默认值，
 *   其中待确认授权不会绕过既有的学生端发布门禁。
 * - 多值字段（data_types/cap_ids）按 FastAPI `list[str] = Form`
 *   契约用同名重复 append，不能 JSON 序列化成单值。
 * - 切片参数不在本页配置：后端上传固定读取系统 RAG 参数（rag_admin.py
 *   _default_stage_params），页面如实说明，不假装可配。
 * - 上传响应是 202 + 同步管线结果：展示最终状态与任务；资料完成索引后仍须
 *   通过授权确认与发布门禁，不能把默认的 pending 状态误当成学生端可见。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../../api/client";
import type {
  DocumentPipelineResponse,
  GraphNode,
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
  LICENSE_OPTIONS,
  SOURCE_TYPE_OPTIONS,
  safeRagReturnPath,
} from "./ragShared";

/** 上传约束与后端一致（rag_admin.py MAX_UPLOAD_BYTES / parsers.py SUPPORTED_FILE_TYPES：
 *  pdf/docx/md/txt/csv/xlsx 六种；file_type 由后端按扩展名映射，前端不重复推导） */
const MAX_BYTES = 50 * 1024 * 1024;
const ACCEPT = ".pdf,.docx,.md,.markdown,.txt,.csv,.xlsx,.xls";

interface SelectedCap {
  id: string;
  label: string;
}

interface SelectedFilesImportResult {
  files: { total: number; imported: number; failed: number; queued: number };
  auto_publish: boolean;
  samples?: {
    imported?: { items: Array<{ id: string; file: string }>; remaining: number };
    failed?: { items: Array<{ file: string; reason: string }>; remaining: number };
  };
}

export default function UploadPage() {
  const location = useLocation();
  const returnTo = safeRagReturnPath(`${location.pathname}${location.search}`);
  const toast = useToast();

  // ---- 文件 ----
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const batchFilesInputRef = useRef<HTMLInputElement>(null);
  const batchFolderInputRef = useRef<HTMLInputElement>(null);
  const [batchFiles, setBatchFiles] = useState<File[]>([]);
  const [batchFileError, setBatchFileError] = useState<string | null>(null);

  // ---- 可选元数据（服务端会为未提交字段提供审计友好的默认值） ----
  const [title, setTitle] = useState("");
  const [sourceType, setSourceType] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [version, setVersion] = useState("");
  const [dataTypes, setDataTypes] = useState<string[]>([]);
  const [caps, setCaps] = useState<SelectedCap[]>([]);
  const [licenseStatus, setLicenseStatus] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // ---- 能力节点搜索 ----
  const [capQuery, setCapQuery] = useState("");
  const [capResults, setCapResults] = useState<GraphNode[]>([]);
  const [capSearching, setCapSearching] = useState(false);

  // ---- 提交状态 ----
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<DocumentPipelineResponse | null>(null);
  const [importingBatch, setImportingBatch] = useState(false);
  const [batchImportResult, setBatchImportResult] = useState<SelectedFilesImportResult | null>(null);

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

  /** Validate a browser file-list once so file and directory selection share the same limits. */
  const pickBatchFiles = (list: FileList | null | undefined) => {
    setBatchFileError(null);
    const selected = Array.from(list ?? []);
    const valid: File[] = [];
    const rejected: string[] = [];
    for (const candidate of selected) {
      const ext = `.${candidate.name.split(".").pop()?.toLowerCase() ?? ""}`;
      if (!ACCEPT.split(",").includes(ext)) {
        rejected.push(`${candidate.name}：格式不支持`);
      } else if (candidate.size > MAX_BYTES) {
        rejected.push(`${candidate.name}：超过 50MB`);
      } else if (candidate.size === 0) {
        rejected.push(`${candidate.name}：文件为空`);
      } else {
        valid.push(candidate);
      }
    }
    setBatchFiles(valid);
    if (rejected.length > 0) {
      setBatchFileError(`已跳过 ${rejected.length} 个文件：${rejected.slice(0, 3).join("；")}`);
    }
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

  /** Only file selection is required; optional metadata is sent when supplied. */
  const validate = (): boolean => {
    const errors: Record<string, string> = {};
    if (!file) errors.file = "请选择要上传的文件";
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const validateBatch = (): boolean => {
    const errors: Record<string, string> = {};
    if (batchFiles.length === 0) errors.file = "请选择要导入的文件或目录";
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const submit = async () => {
    if (!validate() || !file) return;
    setSubmitting(true);
    try {
      const form = new FormData();
      form.append("file", file);
      if (title.trim()) form.append("title", title.trim());
      if (sourceType) form.append("source_type", sourceType);
      if (sourceName.trim()) form.append("source_name", sourceName.trim());
      if (sourceUrl.trim()) form.append("source_url", sourceUrl.trim());
      if (version.trim()) form.append("version", version.trim());
      if (licenseStatus) form.append("license_status", licenseStatus);
      // 多值字段：同名重复 append（FastAPI list[str] = Form 契约）
      dataTypes.forEach((v) => form.append("data_types", v));
      caps.forEach((c) => form.append("cap_ids", c.id));
      const res = await api.postForm<DocumentPipelineResponse>("/api/rag/documents", form);
      setResult(res);
      toast.success("上传成功，已进入处理流程");
    } catch (err) {
      toast.error(errText(err, "上传失败，请稍后重试"));
    } finally {
      setSubmitting(false);
    }
  };

  /** Upload explicit browser selections; the server never scans a client or repository path. */
  const importSelectedFiles = async () => {
    if (!validateBatch()) return;
    setImportingBatch(true);
    try {
      const form = new FormData();
      batchFiles.forEach((selected) => form.append("files", selected));
      if (sourceType) form.append("source_type", sourceType);
      if (sourceName.trim()) form.append("source_name", sourceName.trim());
      if (sourceUrl.trim()) form.append("source_url", sourceUrl.trim());
      if (version.trim()) form.append("version", version.trim());
      if (licenseStatus) form.append("license_status", licenseStatus);
      dataTypes.forEach((value) => form.append("data_types", value));
      caps.forEach((cap) => form.append("cap_ids", cap.id));
      const imported = await api.postForm<SelectedFilesImportResult>(
        "/api/rag/documents/batch-import",
        form,
        { timeoutMs: 600_000 },
      );
      setBatchImportResult(imported);
      // Pending-license imports can be processed now, but remain blocked from
      // student publication until an authorized reviewer confirms the source.
      toast.success(`已排入 ${imported.files.queued} 份资料的处理队列；索引成功后自动发布`);
    } catch (err) {
      toast.error(errText(err, "批量导入失败，请稍后重试"));
    } finally {
      setImportingBatch(false);
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
            「{result.document.title}」已进入解析、切片、索引流程；索引成功后将提供学生召回。
            </p>
            <p className="flex items-center gap-2">
              当前状态：<StatusBadge status={result.document.status} />
              <Tag>{result.document.chunk_count ?? 0} 个切片</Tag>
              {result.document.error_message ? (
                <span className="text-danger text-sm">{result.document.error_message}</span>
              ) : null}
            </p>
            <div className="flex gap-2 mt-2">
              <Link
                to={`/admin/rag/documents/${result.document.id}?returnTo=${encodeURIComponent(returnTo)}`}
                state={{ returnTo }}
                className="btn btn-primary"
              >
                查看资料详情
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

      <Card title="批量导入" className="mb-4">
        <div className="flex flex-col gap-3">
          <p className="text-sm text-secondary">
            可选择多个文件或整个目录（每批最多 1000 个）；系统只上传你明确选择的文件，不会扫描固定的 docs/ragData。
            每份资料会逐一解析、切片、索引；成功后自动发布到学生端。
          </p>
          <div className="flex items-center gap-2" style={{ flexWrap: "wrap" }}>
            <Button variant="secondary" onClick={() => batchFilesInputRef.current?.click()}>
              选择文件
            </Button>
            <Button variant="secondary" onClick={() => batchFolderInputRef.current?.click()}>
              选择目录
            </Button>
            <Button loading={importingBatch} disabled={batchFiles.length === 0} onClick={() => void importSelectedFiles()}>
              {importingBatch ? "正在导入并建立队列" : "导入所选资料并自动处理"}
            </Button>
          </div>
          <input
            ref={batchFilesInputRef}
            type="file"
            accept={ACCEPT}
            multiple
            hidden
            aria-label="选择多个文件"
            onChange={(event) => pickBatchFiles(event.target.files)}
          />
          <input
            ref={(node) => {
              batchFolderInputRef.current = node;
              // Chromium's directory picker is a progressive enhancement; other browsers still
              // expose the regular file picker without receiving an invalid server path.
              node?.setAttribute("webkitdirectory", "");
            }}
            type="file"
            accept={ACCEPT}
            multiple
            hidden
            aria-label="选择目录"
            onChange={(event) => pickBatchFiles(event.target.files)}
          />
          {batchFiles.length > 0 ? (
            <p className="text-sm" role="status">
              已选择 {batchFiles.length} 个有效文件，将使用当前元数据批量导入。
            </p>
          ) : null}
          {batchFileError || fieldErrors.file ? (
            <p className="field-error-text">{batchFileError ?? fieldErrors.file}</p>
          ) : null}
          {batchImportResult ? (
            <p className="text-sm" role="status">
              批量结果：共 {batchImportResult.files.total} 个，导入 {batchImportResult.files.imported} 个，
              失败 {batchImportResult.files.failed} 个，已排队 {batchImportResult.files.queued} 个。
            </p>
          ) : null}
        </div>
      </Card>

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

      {/* Advanced values remain available without turning ordinary uploads into a form-filling workflow. */}
      <details className="mb-4">
        <summary className="text-sm" style={{ cursor: "pointer", marginBottom: "var(--space-2)" }}>
          高级元数据（可选）
        </summary>
      <Card title="资料元数据">
        <div className="grid grid-cols-2">
          <Field label="资料标题" hint="留空时使用文件名">
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：智能客服语音标注规范" />
          </Field>
          <Field label="资料类型" hint="留空时使用“其他”">
            <Select
              aria-label="资料类型"
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value)}
              options={[...SOURCE_TYPE_OPTIONS]}
              placeholder="请选择资料类型"
            />
          </Field>
          <Field label="来源单位 / 作者" hint="留空时记录为“用户上传资料”">
            <Input value={sourceName} onChange={(e) => setSourceName(e.target.value)} placeholder="例如：工业和信息化部 / 张老师" />
          </Field>
          <Field label="版本号" hint="留空时使用 1.0">
            <Input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="例如：1.0" />
          </Field>
          <Field label="来源链接（可选）">
            <Input value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} placeholder="https://…" />
          </Field>
        </div>

        <Field label="适用数据类型" hint="留空时使用文本">
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
          <Field label="授权状态（兼容字段）" hint="仅保留历史元数据，不影响成功索引后的发布">
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
            授权状态为“禁止”的资料仍会被安全校验拦截并归档。
          </p>
        ) : null}
        {licenseStatus === "pending" ? (
          <p className="form-alert form-alert-error" role="alert" style={{ background: "var(--color-warning-soft)", color: "var(--color-warning)" }}>
            授权状态为“待确认”仅作为历史元数据保留。
          </p>
        ) : null}
      </Card>
      </details>

      {/* Processing is deliberately automatic so a successful upload cannot
          be stranded behind a manual review toggle or a hidden queue step. */}
      <Card title="自动处理" className="mb-4">
        <p className="text-sm text-secondary mb-3">
          切片策略使用系统默认切片参数（chunk_size / overlap 由系统管理端 RAG 参数统一配置），
            上传后自动完成解析、切片与索引；成功后自动发布到学生端。
        </p>
      </Card>

      <div className="flex gap-2">
        <Button size="lg" loading={submitting} onClick={() => void submit()}>
          {submitting ? "上传处理中（大文件可能需要数十秒）…" : "确认上传"}
        </Button>
        <Link to="/admin/rag" className="btn btn-ghost btn-lg">
          返回资料库
        </Link>
      </div>
    </div>
  );
}
