/**
 * RAG 参数管理页。
 *
 * The management contract intentionally exposes only the knobs that affect
 * retrieval and answer sampling. Prompt templates, generation policy, and
 * publication policy are product defaults, so they remain built in rather
 * than becoming independent administrator configuration surfaces.
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
  Spinner,
  useToast,
} from "../../components";
import { errText, fmtTime } from "./adminShared";

const INT_RANGES = {
  chunk_size: [100, 2000],
  chunk_overlap: [0, 1000],
  top_k: [1, 20],
} as const;

const FLOAT_RANGES = {
  score_threshold: [0, 1],
  temperature: [0, 2],
  top_p: [0, 1],
} as const;

type SettingsForm = Omit<RagSettings, "id" | "updated_at" | "updated_by">;
type FormKey = keyof SettingsForm;

const FORM_KEYS: FormKey[] = [
  "chunk_size",
  "chunk_overlap",
  "title_inherit",
  "top_k",
  "score_threshold",
  "temperature",
  "top_p",
  "hybrid_search",
  "rerank_enabled",
  "query_rewrite_enabled",
];

function toForm(settings: RagSettings): SettingsForm {
  const { id: _id, updated_at: _updatedAt, updated_by: _updatedBy, ...form } = settings;
  return form;
}

/** Keep client feedback aligned with the API bounds before a request is sent. */
function validate(form: SettingsForm): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const [key, [low, high]] of Object.entries(INT_RANGES)) {
    const value = form[key as keyof typeof INT_RANGES] as number;
    if (!Number.isInteger(value) || value < low || value > high) {
      errors[key] = `必须是 ${low}-${high} 的整数`;
    }
  }
  for (const [key, [low, high]] of Object.entries(FLOAT_RANGES)) {
    const value = form[key as keyof typeof FLOAT_RANGES] as number;
    if (!Number.isFinite(value) || value < low || value > high) {
      errors[key] = `必须在 ${low} 到 ${high} 之间`;
    }
  }
  if (form.chunk_overlap >= form.chunk_size) {
    errors.chunk_overlap = "切片重叠必须小于切片长度";
  }
  return errors;
}

function SwitchRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="mb-3">
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
        />
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
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const settings = await api.get<RagSettings>("/api/admin/rag-settings", undefined, { signal });
      if (signal?.aborted) return;
      const next = toForm(settings);
      setInitial(next);
      setForm(next);
      setUpdatedAt(settings.updated_at);
    } catch (cause) {
      if (!signal?.aborted) setError(errText(cause, "RAG 参数加载失败"));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const dirtyKeys = useMemo<FormKey[]>(() => {
    if (!initial || !form) return [];
    return FORM_KEYS.filter((key) => form[key] !== initial[key]);
  }, [form, initial]);
  const fieldErrors = useMemo(() => (form ? validate(form) : {}), [form]);
  const dirty = dirtyKeys.length > 0;
  const valid = Object.keys(fieldErrors).length === 0;

  const set = <K extends FormKey>(key: K, value: SettingsForm[K]) => {
    setForm((current) => (current ? { ...current, [key]: value } : current));
  };

  const save = async () => {
    if (!form || !dirty || !valid) return;
    setSaving(true);
    setSaveError(null);
    try {
      // Send only changed fields so audit records describe the actual tuning operation.
      const patch = Object.fromEntries(dirtyKeys.map((key) => [key, form[key]]));
      const settings = await api.patch<RagSettings>("/api/admin/rag-settings", patch);
      const next = toForm(settings);
      setInitial(next);
      setForm(next);
      setUpdatedAt(settings.updated_at);
      toast.success("RAG 参数已保存");
    } catch (cause) {
      setSaveError(errText(cause, "RAG 参数保存失败"));
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
  if (!form || error) {
    return <ErrorState message={error ?? "RAG 参数不存在"} onRetry={() => void load()} />;
  }

  const integerField = (key: keyof typeof INT_RANGES, label: string, hint?: string) => {
    const [min, max] = INT_RANGES[key];
    return (
      <Field label={label} required error={fieldErrors[key]} hint={hint ?? `范围 ${min}-${max}`}>
        <Input
          type="number"
          aria-label={label}
          min={min}
          max={max}
          value={form[key]}
          invalid={Boolean(fieldErrors[key])}
          onChange={(event) => set(key, event.target.value === "" ? 0 : Number(event.target.value))}
        />
      </Field>
    );
  };

  const decimalField = (
    key: keyof typeof FLOAT_RANGES,
    label: string,
    step: number,
    hint: string,
  ) => {
    const [min, max] = FLOAT_RANGES[key];
    const value = form[key];
    return (
      <Field label={label} required error={fieldErrors[key]} hint={hint}>
        <div className="flex items-center gap-3">
          <input
            type="range"
            aria-label={`${label}滑块`}
            min={min}
            max={max}
            step={step}
            value={value}
            style={{ flex: 1 }}
            onChange={(event) => set(key, Number(event.target.value))}
          />
          <Input
            type="number"
            aria-label={label}
            min={min}
            max={max}
            step={step}
            value={value}
            invalid={Boolean(fieldErrors[key])}
            style={{ width: 100 }}
            onChange={(event) =>
              set(key, event.target.value === "" ? 0 : Number(event.target.value))
            }
          />
        </div>
      </Field>
    );
  };

  return (
    <div>
      <PageHeader
        title="RAG 参数配置"
        sub={`切片与召回调优；温度和 top-p 作为内置采样参数在此调整${
          updatedAt ? `（最近更新：${fmtTime(updatedAt)}）` : ""
        }`}
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
      {saveError ? (
        <p className="form-alert form-alert-error" role="alert">
          {saveError}
        </p>
      ) : null}
      {!valid && dirty ? (
        <p className="form-alert form-alert-error" role="alert">
          存在校验失败的参数，请修正后再保存。
        </p>
      ) : null}

      <div className="grid grid-cols-2">
        <Card title="切片参数">
          {integerField("chunk_size", "切片长度（默认 500 字符）")}
          {integerField(
            "chunk_overlap",
            "切片重叠（默认 80 字符）",
            "必须小于切片长度，范围 0-1000",
          )}
          <SwitchRow
            label="标题继承（切片自动带上所属章节标题）"
            checked={form.title_inherit}
            onChange={(value) => set("title_inherit", value)}
          />
        </Card>

        <Card title="召回参数">
          {integerField("top_k", "每次最多召回资料数", "范围 1-20")}
          {decimalField(
            "score_threshold",
            "最低相似度阈值",
            0.05,
            "低于阈值的召回将被拒答，范围 0-1",
          )}
          {/* Keep provider-facing sampling names exact so operators can map UI values to API payloads. */}
          {decimalField("temperature", "temperature", 0.05, "答案采样随机性，范围 0-2")}
          {decimalField("top_p", "top-p", 0.05, "答案采样候选概率，范围 0-1")}
          <SwitchRow
            label="混合召回（向量 + 关键词）"
            checked={form.hybrid_search}
            onChange={(value) => set("hybrid_search", value)}
          />
          <SwitchRow
            label="启用重排（需要配置重排模型供应商）"
            checked={form.rerank_enabled}
            onChange={(value) => set("rerank_enabled", value)}
          />
          <SwitchRow
            label="查询改写"
            hint="短查询先补充检索上下文；供应商不可用时使用原始查询。"
            checked={form.query_rewrite_enabled}
            onChange={(value) => set("query_rewrite_enabled", value)}
          />
        </Card>
      </div>
    </div>
  );
}
