/**
 * RAG 参数配置（/admin/rag-settings）——切片/召回/生成/发布四组参数（PRD-04 §4）。
 *
 * 关键决策（为什么）：
 * - 脏跟踪 + 只提交变更字段：后端 PATCH 是部分更新且必须写审计（PRD-04 §4.2），
 *   只发变化字段让审计 before/after 精确可读，也避免"没改也产生一条审计"。
 * - 校验范围与后端 admin.py 完全同口径（_RAG_INT_RANGES / 枚举 / 文本上限），
 *   前端先拦一次减少必败往返；chunk_overlap < chunk_size 是后端防死循环
 *   的硬约束，前端同样校验。
 * - table_strategy 当前只落库不生效（chunker 未消费）：如实标注"保留配置位"，
 *   不虚构选项让管理员误以为能改变切片行为。
 * - 召回参数默认值即安全值（published_only 在学生端强制、threshold 拒答），
 *   页面提示改参数后用评测集回归（PRD-04 §4.2 验收）。
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type { RagSettings } from "../../api/types";
import {
  Button,
  Card,
  ErrorState,
  Field,
  Input,
  PageHeader,
  Select,
  Spinner,
  Textarea,
  useToast,
} from "../../components";
import { errText, fmtTime } from "./adminShared";

/** 数值/枚举校验规则（与后端 admin.py 同口径，前端只做提前拦截） */
const INT_RANGES: Record<string, [number, number]> = {
  chunk_size: [100, 2000],
  chunk_overlap: [0, 1000],
  top_k: [1, 20],
  max_citations: [1, 20],
};

/** 表单状态 = RagSettings 全量（后端 GET/PATCH 同形） */
type SettingsForm = Omit<RagSettings, "id" | "updated_at" | "updated_by">;

const FORM_KEYS = [
  "chunk_size",
  "chunk_overlap",
  "title_inherit",
  "table_strategy",
  "top_k",
  "score_threshold",
  "hybrid_search",
  "rerank_enabled",
  "citation_format",
  "refusal_policy",
  "max_citations",
  "prompt_template",
  "prompt_template_version",
  "require_manual_review",
  "student_visibility_default",
  "expired_doc_policy",
] as const;

type FormKey = (typeof FORM_KEYS)[number];

function toForm(s: RagSettings): SettingsForm {
  const { id: _id, updated_at: _u, updated_by: _b, ...form } = s;
  return form;
}

/** 客户端校验：返回字段 → 错误文案（空对象 = 通过） */
function validate(form: SettingsForm): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const [key, [low, high]] of Object.entries(INT_RANGES)) {
    const value = form[key as FormKey] as number;
    if (!Number.isInteger(value) || value < low || value > high) {
      errors[key] = `必须为 ${low}-${high} 的整数`;
    }
  }
  if (form.chunk_overlap >= form.chunk_size) {
    errors.chunk_overlap = "chunk_overlap 必须小于 chunk_size";
  }
  if (form.score_threshold < 0 || form.score_threshold > 1) {
    errors.score_threshold = "必须在 0 到 1 之间";
  }
  if (!form.citation_format.trim() || form.citation_format.length > 200) {
    errors.citation_format = "不能为空且不超过 200 字符";
  }
  if (!form.table_strategy.trim() || form.table_strategy.length > 20) {
    errors.table_strategy = "不能为空且不超过 20 字符";
  }
  if (!form.prompt_template.trim() || form.prompt_template.length > 4000) {
    errors.prompt_template = "不能为空且不超过 4000 字符";
  }
  if (!form.prompt_template_version.trim() || form.prompt_template_version.length > 50) {
    errors.prompt_template_version = "不能为空且不超过 50 字符";
  }
  return errors;
}

/** 开关行（checkbox + 文案；全站无独立 Switch 组件，保持语义化 label） */
function SwitchRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="mb-3">
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
        {label}
      </label>
      {hint ? <p className="text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

export default function RagSettingsPage() {
  const toast = useToast();
  const [initial, setInitial] = useState<SettingsForm | null>(null);
  const [form, setForm] = useState<SettingsForm | null>(null);
  const [meta, setMeta] = useState<{ updated_at: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<RagSettings>("/api/admin/rag-settings", undefined, { signal });
      if (signal?.aborted) return;
      setInitial(toForm(res));
      setForm(toForm(res));
      setMeta({ updated_at: res.updated_at });
    } catch (err) {
      if (!signal?.aborted) setError(errText(err, "RAG 参数加载失败"));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  /** 变更键集合（驱动"保存"可用性与 PATCH 载荷） */
  const dirtyKeys = useMemo<FormKey[]>(() => {
    if (!initial || !form) return [];
    return FORM_KEYS.filter((key) => form[key] !== initial[key]);
  }, [initial, form]);

  const fieldErrors = useMemo(() => (form ? validate(form) : {}), [form]);
  const dirty = dirtyKeys.length > 0;
  const valid = Object.keys(fieldErrors).length === 0;

  const set = <K extends FormKey>(key: K, value: SettingsForm[K]) =>
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));

  const save = async () => {
    if (!form || !dirty || !valid) return;
    setSaving(true);
    setSaveError(null);
    try {
      // 只提交变更字段：审计 before/after 精确（见文件头说明）
      const patch = Object.fromEntries(dirtyKeys.map((key) => [key, form[key]]));
      const res = await api.patch<RagSettings>("/api/admin/rag-settings", patch);
      setInitial(toForm(res));
      setForm(toForm(res));
      setMeta({ updated_at: res.updated_at });
      toast.success("已保存并记录审计日志");
    } catch (err) {
      setSaveError(errText(err));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="loading-block">
        <Spinner large /> 正在加载 RAG 参数…
      </div>
    );
  }
  if (error || !form) {
    return <ErrorState message={error ?? "参数不存在"} onRetry={() => void load()} />;
  }

  /** 数字输入：Number('') = 0 会立即触发范围校验提示，符合"改错即提示" */
  const numField = (
    key: "chunk_size" | "chunk_overlap" | "top_k" | "max_citations",
    label: string,
    hint?: string,
  ) => {
    const [low, high] = INT_RANGES[key];
    return (
      <Field label={label} required error={fieldErrors[key]} hint={hint ?? `范围 ${low}-${high}`}>
        <Input
          type="number"
          aria-label={label}
          min={low}
          max={high}
          value={form[key]}
          invalid={!!fieldErrors[key]}
          onChange={(e) => set(key, e.target.value === "" ? 0 : Number(e.target.value))}
        />
      </Field>
    );
  };

  return (
    <div>
      <PageHeader
        title="RAG 参数配置"
        sub={`切片 / 召回 / 生成 / 发布四组参数；修改立即生效并记录审计日志${meta ? `（最近更新：${fmtTime(meta.updated_at)}）` : ""}`}
        actions={
          <>
            <Button variant="ghost" disabled={!dirty} onClick={() => setForm(initial)}>
              放弃修改
            </Button>
            <Button loading={saving} disabled={!dirty || !valid} onClick={() => void save()}>
              保存参数{dirty ? `（${dirtyKeys.length} 项变更）` : ""}
            </Button>
          </>
        }
      />
      {saveError ? <p className="form-alert form-alert-error" role="alert">{saveError}</p> : null}
      {!valid && dirty ? (
        <p className="form-alert form-alert-error" role="alert">
          存在校验失败的参数，请修正后再保存。
        </p>
      ) : null}

      <div className="grid grid-cols-2">
        {/* 切片参数 */}
        <Card title="切片参数">
          {numField("chunk_size", "chunk_size（切片长度）")}
          {numField("chunk_overlap", "chunk_overlap（重叠长度）", "必须小于切片长度，范围 0-1000")}
          <SwitchRow
            label="标题继承（切片自动带上所属章节标题）"
            checked={form.title_inherit}
            onChange={(v) => set("title_inherit", v)}
          />
          <Field
            label="表格处理策略"
            error={fieldErrors.table_strategy}
            hint="保留配置位：当前切片器统一按纯文本处理，该值随参数落库（≤20 字符）"
          >
            <Input
              value={form.table_strategy}
              invalid={!!fieldErrors.table_strategy}
              onChange={(e) => set("table_strategy", e.target.value)}
            />
          </Field>
        </Card>

        {/* 召回参数 */}
        <Card title="召回参数">
          {numField("top_k", "top_k（召回数量）")}
          <Field
            label={`score_threshold（相似度阈值：${form.score_threshold.toFixed(2)}）`}
            error={fieldErrors.score_threshold}
            hint="低于阈值的召回将被拒答，范围 0-1"
          >
            <div className="flex items-center gap-3">
              <input
                type="range"
                aria-label="score_threshold 滑块"
                min={0}
                max={1}
                step={0.05}
                value={form.score_threshold}
                style={{ flex: 1 }}
                onChange={(e) => set("score_threshold", Number(e.target.value))}
              />
              <Input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={form.score_threshold}
                invalid={!!fieldErrors.score_threshold}
                style={{ width: 100 }}
                onChange={(e) => set("score_threshold", e.target.value === "" ? 0 : Number(e.target.value))}
              />
            </div>
          </Field>
          <SwitchRow
            label="hybrid_search（向量 + 关键词混合召回）"
            checked={form.hybrid_search}
            onChange={(v) => set("hybrid_search", v)}
          />
          <SwitchRow
            label="rerank（重排序，需配置重排模型供应商）"
            checked={form.rerank_enabled}
            onChange={(v) => set("rerank_enabled", v)}
          />
        </Card>

        {/* 生成参数 */}
        <Card title="生成参数">
          <Field
            label="引用格式模板"
            required
            error={fieldErrors.citation_format}
            hint="可用变量：{title} 标题、{section} 章节、{page} 页码、{version} 版本"
          >
            <Input
              value={form.citation_format}
              invalid={!!fieldErrors.citation_format}
              onChange={(e) => set("citation_format", e.target.value)}
            />
          </Field>
          <Field label="资料不足拒答策略" required>
            <Select
              value={form.refusal_policy}
              onChange={(e) => set("refusal_policy", e.target.value as SettingsForm["refusal_policy"])}
              options={[
                { value: "refuse", label: "直接拒答（不生成专业结论）" },
                { value: "generic_advice", label: "给通用学习建议" },
              ]}
            />
          </Field>
          {numField("max_citations", "最大引用数量")}
          <Field label="Prompt 模板" required error={fieldErrors.prompt_template}>
            <Textarea
              value={form.prompt_template}
              invalid={!!fieldErrors.prompt_template}
              style={{ minHeight: 120 }}
              onChange={(e) => set("prompt_template", e.target.value)}
            />
          </Field>
          <Field label="Prompt 模板版本" required error={fieldErrors.prompt_template_version} hint="召回测试诊断信息中展示">
            <Input
              value={form.prompt_template_version}
              invalid={!!fieldErrors.prompt_template_version}
              onChange={(e) => set("prompt_template_version", e.target.value)}
            />
          </Field>
        </Card>

        {/* 发布参数 */}
        <Card title="发布参数">
          <SwitchRow
            label="要求人工审核（发布前必须送审）"
            hint="关闭后仍需通过发布守卫（授权/切片/敏感信息）"
            checked={form.require_manual_review}
            onChange={(v) => set("require_manual_review", v)}
          />
          <Field label="学生端默认可见范围" required>
            <Select
              value={form.student_visibility_default}
              onChange={(e) =>
                set("student_visibility_default", e.target.value as SettingsForm["student_visibility_default"])
              }
              options={[
                { value: "student", label: "学生可见" },
                { value: "teacher", label: "仅教师" },
                { value: "admin", label: "仅管理员" },
              ]}
            />
          </Field>
          <Field label="过期资料处理" required hint="到达 expires_at 的资料如何处置">
            <Select
              value={form.expired_doc_policy}
              onChange={(e) => set("expired_doc_policy", e.target.value as SettingsForm["expired_doc_policy"])}
              options={[
                { value: "remove", label: "自动移出学生召回" },
                { value: "keep", label: "保留召回（仅标记）" },
              ]}
            />
          </Field>
          <p className="text-xs text-muted">
            提示：召回相关参数调整后，建议立即在评测集跑一次回归（PRD-04 §4.2）。
          </p>
        </Card>
      </div>
    </div>
  );
}
