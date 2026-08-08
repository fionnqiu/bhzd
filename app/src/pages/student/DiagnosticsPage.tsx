/**
 * 标注诊断页（PRD-01 §7 + PRD-06 §9 边界）。
 *
 * 闭环：上传（multipart，≤20MB 前端预检）→ 解析预检 + 确定性诊断报告
 * （错误列表含严重程度/期望值/规则依据/能力定位）→ 补强计划 →
 * 「保存诊断摘要」弹掌握度变化预览（PRD 验收：保存前必须展示）→
 * save-summary 落摘要 + 掌握度生效（token 一次性，确认后作废）。
 *
 * 关键决策（为什么）：
 * - 严重程度徽章不走 StatusBadge：其映射表不含 major/minor，会回落成英文
 *   原文；本地中文徽章保证"严重/轻微"全站一致。
 * - 上传错误（PARSE_FAILED/FIELDS_MISSING 等）直接展示后端中文 message
 *   （内含示例模板提示，PRD-06 §9.2），不另造文案。
 * - diagnostic_uploaded / diagnostic_summary_saved / mastery_updated 埋点
 *   均由后端端点上报，前端不重复发。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type {
  DiagnosticSummary,
  DiagnosticUploadResponse,
  Paginated,
  SaveSummaryResponse,
  Severity,
} from "../../api/types";
import {
  Button,
  Card,
  CitationCard,
  DataTable,
  EmptyState,
  Modal,
  PageHeader,
  Select,
  Spinner,
  Tag,
  useToast,
  type Column,
} from "../../components";
import { useScenario } from "../../app/ScenarioContext";
import {
  capNameOf,
  dataTypeLabel,
  errMsg,
  formatDateTime,
  MasteryPreviewList,
  useCapNames,
} from "./shared";

/** PRD-06 §9.1：单文件 ≤20MB（与后端 MAX_UPLOAD_BYTES 一致，前端先拦一道） */
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

/** 支持格式说明（PRD-01 §7：JSON/TextGrid/COCO JSON/VOC XML） */
const FORMAT_ROWS: { format: string; accept: string; desc: string }[] = [
  { format: "JSON", accept: ".json", desc: "通用自定义结构标注结果" },
  { format: "TextGrid", accept: ".textgrid", desc: "Praat 语音标注" },
  { format: "COCO JSON", accept: ".json", desc: "图像/视频检测与分割" },
  { format: "VOC XML", accept: ".xml", desc: "Pascal VOC 框选标注" },
];

// Fixed widths keep format guidance scan-friendly; longer descriptions use the table viewport.
const FORMAT_COLUMNS: Column<(typeof FORMAT_ROWS)[number]>[] = [
  { key: "format", title: "格式", width: "10rem", render: (row) => <Tag>{row.format}</Tag> },
  { key: "desc", title: "适用场景", width: "20rem" },
];

const DATA_TYPE_OPTIONS = [
  { value: "", label: "自动识别" },
  { value: "text", label: "文本" },
  { value: "image", label: "图像" },
  { value: "audio", label: "语音" },
  { value: "video", label: "视频" },
];

/** 严重程度中文徽章（本地化的原因见文件头注释） */
function SeverityBadge({ severity }: { severity: Severity }) {
  return severity === "major" ? (
    <span className="badge badge-danger">严重</span>
  ) : (
    <span className="badge badge-warning">轻微</span>
  );
}

export default function DiagnosticsPage() {
  const toast = useToast();
  const { scenarioId: globalScenarioId, scenarios } = useScenario();
  const capNames = useCapNames();

  const [dataType, setDataType] = useState("");
  // 场景默认取全局场景上下文（顶栏选择器），页内可覆盖
  const [scenarioId, setScenarioId] = useState(globalScenarioId);
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [report, setReport] = useState<DiagnosticUploadResponse | null>(null);

  const [summaries, setSummaries] = useState<DiagnosticSummary[] | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const loadSummaries = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await api.get<Paginated<DiagnosticSummary>>("/api/diagnostics/summaries", undefined, { signal });
      if (signal?.aborted) return;
      setSummaries(res.items);
    } catch {
      /* 历史摘要加载失败不阻断上传主流程，列表区保持空态 */
      if (!signal?.aborted) setSummaries([]);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadSummaries(controller.signal);
    return () => controller.abort();
  }, [loadSummaries]);

  /** 前端大小预检（PRD-06 §9.1）；格式交给后端嗅探（扩展名不可靠） */
  const pickFile = (picked: File | null) => {
    if (!picked) return;
    if (picked.size > MAX_UPLOAD_BYTES) {
      toast.error("文件超过 20MB 上限，请拆分或压缩后再上传");
      return;
    }
    setFile(picked);
    setUploadError(null);
  };

  /** 上传诊断：multipart 提交，原文件不持久化（NF3），报告带 30min token */
  const upload = async () => {
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      if (dataType) formData.append("data_type", dataType);
      if (scenarioId) formData.append("scenario_id", scenarioId);
      const res = await api.postForm<DiagnosticUploadResponse>("/api/diagnostics", formData);
      setReport(res);
      toast.success("诊断完成，请查看报告");
    } catch (err) {
      // 后端中文 message 已含示例模板/缺字段提示（PRD-06 §9.2），原样展示
      setUploadError(errMsg(err));
      setReport(null);
    } finally {
      setUploading(false);
    }
  };

  /** 确认保存摘要：掌握度预览生效 + 摘要入库（token 一次性，确认后清空报告区） */
  const saveSummary = async () => {
    if (!report) return;
    setSaving(true);
    try {
      await api.post<SaveSummaryResponse>("/api/diagnostics/save-summary", {
        diagnostic_token: report.diagnostic_token,
      });
      toast.success("诊断摘要已保存，掌握度已更新");
      setSaveOpen(false);
      setReport(null);
      setFile(null);
      await loadSummaries();
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="标注诊断"
        sub="上传标注结果文件，获取确定性诊断与个性化补强计划"
      />

      <div className="grid grid-cols-2 mb-4">
        {/* 上传区 */}
        <Card title="上传诊断文件">
          <div className="flex flex-col gap-3">
            <div
              role="button"
              tabIndex={0}
              aria-label="选择诊断文件"
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === "Enter") fileInputRef.current?.click();
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                pickFile(e.dataTransfer.files?.[0] ?? null);
              }}
              style={{
                border: `1px dashed ${dragOver ? "var(--color-primary)" : "var(--color-border-strong)"}`,
                borderRadius: "var(--radius-md)",
                padding: "var(--space-6)",
                textAlign: "center",
                cursor: "pointer",
                background: dragOver ? "var(--color-primary-soft)" : "var(--color-surface)",
              }}
            >
              {file ? (
                <span className="text-sm">
                  已选择：<strong>{file.name}</strong>（{(file.size / 1024).toFixed(1)} KB）
                </span>
              ) : (
                <span className="text-sm text-secondary">
                  拖拽文件到这里，或点击选择（单个文件，≤20MB）
                </span>
              )}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".json,.textgrid,.xml"
              style={{ display: "none" }}
              onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
            />
            <div className="grid grid-cols-2">
              <Select
                aria-label="数据类型"
                value={dataType}
                options={DATA_TYPE_OPTIONS}
                onChange={(e) => setDataType(e.target.value)}
              />
              <Select
                aria-label="场景"
                value={scenarioId}
                options={scenarios.map((s) => ({ value: s.id, label: s.name }))}
                onChange={(e) => setScenarioId(e.target.value)}
              />
            </div>
            <Button block loading={uploading} disabled={!file} onClick={upload}>
              上传并诊断
            </Button>
          </div>
        </Card>

        {/* 支持格式说明 */}
        <Card title="支持格式">
          <DataTable
            ariaLabel="支持文件格式"
            wrapperClassName="table-wrap-borderless"
            columns={FORMAT_COLUMNS}
            rows={FORMAT_ROWS}
            rowKey={(row) => row.format}
          />
          <p className="text-xs text-muted mt-3">
            原文件仅在请求内解析，不会保存到服务器；系统只保存你确认后的诊断摘要。
          </p>
        </Card>
      </div>

      {uploadError ? (
        <Card className="mb-4">
          <div className="form-alert form-alert-error" role="alert">
            {uploadError}
          </div>
          <p className="text-sm text-secondary">
            请对照上方支持格式表检查文件；JSON 可参考{' '}
            <code className="font-mono">{`[{"start":0,"end":1,"label":"实体"}]`}</code>{' '}
            这类结构导出后再试。
          </p>
        </Card>
      ) : null}

      {report ? (
        <>
          {/* 解析预检（PRD-01 §7：格式校验/字段识别/样本数量/风险提示） */}
          <Card title="解析预检" className="mb-4">
            <div className="flex items-center gap-3 flex-wrap">
              <Tag>格式：{report.file_format}</Tag>
              <Tag>样本数：{report.sample_count}</Tag>
              <Tag>{dataTypeLabel(report.data_type)}</Tag>
            </div>
            {report.precheck.fields.length > 0 ? (
              <div className="mt-3">
                <span className="text-sm text-secondary">识别字段：</span>
                <span className="flex items-center gap-2 flex-wrap mt-2">
                  {report.precheck.fields.map((field) => (
                    <Tag key={field}>{field}</Tag>
                  ))}
                </span>
              </div>
            ) : null}
            {report.precheck.warnings.length > 0 ? (
              <div className="mt-3">
                {report.precheck.warnings.map((warning, index) => (
                  <p key={index} className="text-sm" style={{ color: "var(--color-warning)" }}>
                    ⚠ {warning}
                  </p>
                ))}
              </div>
            ) : null}
            {report.notice ? (
              <p className="text-sm text-secondary mt-3">{report.notice}</p>
            ) : null}
          </Card>

          {/* 诊断报告（PRD-06 §9.3 最低结构逐项落地） */}
          <Card
            title="诊断报告"
            className="mb-4"
            actions={
              <span className="flex items-center gap-2">
                <span className="badge badge-danger">严重 {report.severity_counts.major}</span>
                <span className="badge badge-warning">轻微 {report.severity_counts.minor}</span>
              </span>
            }
          >
            {report.errors.length === 0 ? (
              <EmptyState title="未发现标注错误" hint="本次上传的标注结果通过了全部规则校验" />
            ) : (
              <div className="flex flex-col gap-3">
                {report.errors.map((error, index) => (
                  <div key={index} className="card card-padded">
                    <div className="flex items-center gap-2 flex-wrap mb-2">
                      <SeverityBadge severity={error.severity} />
                      <strong className="text-sm">{error.error_type}</strong>
                      <Link to={`/graph?node=${error.cap_id}`}>
                        <span className="badge badge-primary">
                          {error.cap_name ?? capNameOf(capNames, error.cap_id)}
                        </span>
                      </Link>
                    </div>
                    <div className="grid grid-cols-2">
                      <div>
                        <span className="text-xs text-muted">你的标注值</span>
                        <p className="text-sm font-mono" style={{ wordBreak: "break-all" }}>
                          {error.user_value == null ? "（空）" : String(error.user_value)}
                        </p>
                      </div>
                      <div>
                        <span className="text-xs text-muted">期望值 / 规则说明</span>
                        <p className="text-sm">{error.expected}</p>
                      </div>
                    </div>
                    <p className="text-sm text-secondary mt-2">规则：{error.rule}</p>
                    <p className="text-sm mt-2">建议：{error.suggestion}</p>
                    {error.citations && error.citations.length > 0 ? (
                      <div className="mt-3">
                        <span className="text-xs text-muted">规则依据（知识库命中）</span>
                        {error.citations.map((citation, citationIndex) => (
                          <CitationCard
                            key={citationIndex}
                            citation={citation}
                            index={citationIndex + 1}
                          />
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* 补强计划（薄弱能力 → PRE 路径 → 资源/练习 → 保存摘要） */}
          <Card title="补强计划" className="mb-4">
            <div className="flex flex-col gap-4">
              {report.plan.weak_caps.length > 0 ? (
                <div>
                  <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                    薄弱能力
                  </h3>
                  <div className="flex items-center gap-2 flex-wrap">
                    {report.plan.weak_caps.map((cap) => (
                      <Link key={cap.cap_id} to={`/graph?node=${cap.cap_id}`}>
                        <span className="badge badge-weak">{cap.cap_name}</span>
                      </Link>
                    ))}
                  </div>
                </div>
              ) : null}
              {report.plan.pre_path.length > 0 ? (
                <div>
                  <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                    推荐补强顺序（基础在前）
                  </h3>
                  <ol className="flex flex-col gap-2">
                    {report.plan.pre_path.map((capId, index) => (
                      <li key={capId} className="flex items-center gap-2">
                        <span className="badge badge-primary">{index + 1}</span>
                        <Link to={`/graph?node=${capId}`} className="text-sm">
                          {capNameOf(capNames, capId)}
                        </Link>
                      </li>
                    ))}
                  </ol>
                </div>
              ) : null}
              {report.plan.resources.length > 0 ? (
                <div>
                  <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                    推荐资源
                  </h3>
                  <div className="flex flex-col gap-2">
                    {report.plan.resources.map((resource, index) => (
                      <span key={index} className="flex items-center gap-2 text-sm">
                        <span className="badge badge-info">{resource.type}</span>
                        {resource.title}
                        {resource.data_type ? <Tag>{dataTypeLabel(resource.data_type)}</Tag> : null}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
              {report.plan.tasks.length > 0 ? (
                <div>
                  <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                    推荐练习
                  </h3>
                  <ul className="flex flex-col gap-2">
                    {report.plan.tasks.map((task, index) => (
                      <li key={index} className="text-sm text-secondary">
                        · {task}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <div>
                <Button onClick={() => setSaveOpen(true)}>保存诊断摘要</Button>
              </div>
            </div>
          </Card>
        </>
      ) : null}

      {/* 历史诊断摘要（PRD-06 §7.2 空态文案） */}
      <Card title="历史诊断摘要">
        {summaries === null ? (
          <div className="loading-block">
            <Spinner /> 加载中…
          </div>
        ) : summaries.length === 0 ? (
          <EmptyState
            title="还没有诊断摘要"
            hint="上传一次标注结果，获取第一次诊断"
          />
        ) : (
          <DataTable<DiagnosticSummary>
            ariaLabel="历史诊断摘要"
            columns={[
              { key: "created_at", title: "时间", render: (row) => formatDateTime(row.created_at) },
              { key: "file_format", title: "格式", render: (row) => <Tag>{row.file_format}</Tag> },
              { key: "error_count", title: "错误数" },
              {
                key: "severity_counts",
                title: "严重/轻微",
                render: (row) => `${row.severity_counts.major} / ${row.severity_counts.minor}`,
              },
              { key: "weak_cap_ids", title: "薄弱能力数", render: (row) => row.weak_cap_ids.length },
            ]}
            rows={summaries}
          />
        )}
      </Card>

      {/* 保存前确认：PRD 验收要求——保存摘要前必须展示掌握度变化预览 */}
      <Modal
        open={saveOpen}
        title="保存诊断摘要"
        onClose={() => setSaveOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setSaveOpen(false)} disabled={saving}>
              取消
            </Button>
            <Button loading={saving} onClick={saveSummary}>
              确认保存
            </Button>
          </>
        }
      >
        {report ? (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-secondary">
              将保存本次诊断摘要（{report.errors.length} 个错误、
              {report.weak_cap_ids.length} 项薄弱能力），并按以下预览更新掌握度：
            </p>
            <MasteryPreviewList changes={report.mastery_preview} capNames={capNames} />
            <p className="text-xs text-muted">
              原文件不会保存；摘要保存后本次诊断令牌即失效。
            </p>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
