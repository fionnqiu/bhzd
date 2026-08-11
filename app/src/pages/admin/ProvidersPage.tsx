/**
 * 模型供应商配置（/admin/providers）——供应商 CRUD + 角色 + 连接测试（PRD-04 §3）。
 *
 * 关键决策（为什么）：
 * - API Key 只进不出：编辑态显示固定掩码，掩码留在表单仅表示服务端已有密钥，
 *   永远不会作为替换值提交；后端发现/测试端点负责复用服务端密钥。
 * - base_url 安全校验（NF9）由后端执行：INVALID_BASE_URL 的中文错误落到
 *   字段旁而不是 toast——表单错误出现在字段旁是 PRD 表单交互口径。
 * - 角色独占（同角色至多一个）由后端事务保证；前端在"替换已有持有者"时
 *   先弹确认框说明后果，无持有者时直接设置，减少打断。
 * - 连接测试结果直接写回行的 last_test（POST test 的响应即入库结果），
 *   不需整表刷新——行内即时反馈延迟/错误是 PRD-04 §3.3 验收点。
 */

import { Check, ChevronDown, Eye, EyeOff, Import } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import "./ProvidersPage.css";
import { ApiRequestError, api } from "../../api/client";
import type {
  Paginated,
  ProviderConfig,
  ProviderModelDiscoveryResult,
  ProviderTestResult,
} from "../../api/types";
import {
  Button,
  Card,
  ConfirmDialog,
  DataTable,
  Drawer,
  EmptyState,
  ErrorState,
  Field,
  IconButton,
  Input,
  PageHeader,
  Select,
  Spinner,
  Tag,
  useToast,
  type Column,
} from "../../components";
import {
  errText,
  fmtTime,
  PROTOCOL_LABELS,
  PROTOCOL_OPTIONS,
  PROVIDER_ROLE_LABELS,
  PROVIDER_ROLE_OPTIONS,
} from "./adminShared";

/** 抽屉表单（新建/编辑共用；api_key 编辑态留空 = 不更换） */
interface ProviderForm {
  name: string;
  protocol: string;
  base_url: string;
  model: string;
  api_key: string;
  role: string;
  timeout_seconds: string;
  enabled: boolean;
  model_inputs: ModelInput[];
}

/** Fixed mask shown for an existing credential; it is never submitted as a replacement. */
const MASKED_API_KEY = "********";

/** A fixed mask is display state, never a credential eligible for transient calls. */
function hasUsableApiKey(value: string): boolean {
  return Boolean(value) && value !== MASKED_API_KEY;
}

const MODEL_INPUT_OPTIONS = [
  { value: "text", label: "文本" },
  { value: "audio", label: "音频" },
  { value: "video", label: "视频" },
  { value: "image", label: "图片" },
] as const;

type ModelInput = (typeof MODEL_INPUT_OPTIONS)[number]["value"];

function modelInputsFromExtra(extra: Record<string, unknown>): ModelInput[] {
  const storedInputs = extra.model_inputs;
  if (!Array.isArray(storedInputs)) return [];

  // Preserve a predictable label order and discard legacy/unknown values so a
  // malformed provider record cannot create a selection the editor cannot clear.
  return MODEL_INPUT_OPTIONS.filter((option) => storedInputs.includes(option.value)).map(
    (option) => option.value,
  );
}

interface ModelInputMultiSelectProps {
  value: readonly ModelInput[];
  onChange: (value: ModelInput[]) => void;
}

/** Compact multi-select for provider capabilities; choices stay explicit instead of inferring them from a model name. */
function ModelInputMultiSelect({ value, onChange }: ModelInputMultiSelectProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listboxId = useId();
  const selectedLabel = MODEL_INPUT_OPTIONS.filter((option) => value.includes(option.value))
    .map((option) => option.label)
    .join("、");

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus({ preventScroll: true });
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const toggle = (nextValue: ModelInput) => {
    onChange(
      value.includes(nextValue)
        ? value.filter((currentValue) => currentValue !== nextValue)
        : [...value, nextValue],
    );
  };

  return (
    <div className="provider-input-types" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="provider-input-types-trigger"
        role="combobox"
        aria-label="模型输入"
        aria-haspopup="listbox"
        aria-controls={listboxId}
        aria-expanded={open}
        onClick={() => setOpen((currentOpen) => !currentOpen)}
      >
        <span className="provider-input-types-value">{selectedLabel || "请选择模型输入"}</span>
        <ChevronDown size={16} aria-hidden="true" />
      </button>
      {open ? (
        <div
          id={listboxId}
          className="provider-input-types-listbox"
          role="listbox"
          aria-multiselectable
        >
          {MODEL_INPUT_OPTIONS.map((option) => {
            const selected = value.includes(option.value);
            return (
              <button
                key={option.value}
                type="button"
                className="provider-input-types-option"
                role="option"
                aria-selected={selected}
                onClick={() => toggle(option.value)}
              >
                <span>{option.label}</span>
                {selected ? <Check size={16} aria-hidden="true" /> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

const EMPTY_FORM: ProviderForm = {
  name: "",
  protocol: "chat_completions",
  base_url: "",
  model: "",
  api_key: "",
  role: "none",
  timeout_seconds: "30",
  enabled: true,
  model_inputs: [],
};

function toForm(p: ProviderConfig): ProviderForm {
  return {
    name: p.name,
    protocol: p.protocol,
    base_url: p.base_url,
    model: p.model,
    api_key: p.api_key_set ? p.api_key_masked || MASKED_API_KEY : "",
    role: p.role,
    timeout_seconds: String(p.timeout_seconds),
    enabled: p.enabled,
    model_inputs: modelInputsFromExtra(p.extra),
  };
}

/** 角色徽章（主/回退/嵌入/重排是系统关键路径，给强调色） */
function RoleBadge({ role }: { role: string }) {
  if (role === "none") return <span className="badge badge-neutral">无</span>;
  const tone = role === "primary" ? "primary" : role === "fallback" ? "warning" : "info";
  return <span className={`badge badge-${tone}`}>{PROVIDER_ROLE_LABELS[role] ?? role}</span>;
}

/** 最近测试结果单元格：只展示安全的测试状态、延迟与错误短码。 */
function LastTestCell({ test }: { test: ProviderTestResult | null }) {
  if (!test) return <span className="text-muted text-sm">未测试</span>;
  const tip = [test.error, `模型：${test.model}`, fmtTime(test.tested_at)]
    .filter(Boolean)
    .join(" · ");
  return (
    <span
      className={`provider-last-test text-sm ${test.ok ? "text-success" : "text-danger"}`}
      title={tip}
    >
      {test.ok ? `连接 · ✓ ${test.latency_ms}ms` : `连接 · ✗ ${test.error ?? "验证失败"}`}
    </span>
  );
}

export default function ProvidersPage() {
  const toast = useToast();
  const [items, setItems] = useState<ProviderConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 抽屉：null 关闭 / "new" 新建 / ProviderConfig 编辑
  const [editor, setEditor] = useState<"new" | ProviderConfig | null>(null);
  const [form, setForm] = useState<ProviderForm>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [baseUrlError, setBaseUrlError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [modelOptions, setModelOptions] = useState<{ value: string; label: string }[]>([]);
  const [modelDiscoveryError, setModelDiscoveryError] = useState<string | null>(null);
  const [discoveringModels, setDiscoveringModels] = useState(false);
  const [testingForm, setTestingForm] = useState(false);
  const [formTestResult, setFormTestResult] = useState<ProviderTestResult | null>(null);
  // Visibility applies only to an administrator's new replacement input; a saved key never enters this state.
  const [apiKeyVisible, setApiKeyVisible] = useState(false);

  // 连接测试独立持有 loading，避免请求让同一行的其他操作看似也在执行。
  const [testingId, setTestingId] = useState<string | null>(null);
  // 删除目标单独保存，确认取消或失败时仍保留原列表行，避免误删造成视觉丢失。
  const [deleteTarget, setDeleteTarget] = useState<ProviderConfig | null>(null);
  // Role assignment remains exclusive. Saving from the drawer explains a replacement
  // before the backend performs its transactional handoff.
  const [roleConfirm, setRoleConfirm] = useState<{
    role: string;
    holderName: string;
  } | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<Paginated<ProviderConfig>>("/api/admin/providers", undefined, {
        signal,
      });
      if (signal?.aborted) return;
      // 形状兜底：响应不是预期分页结构时按空列表渲染而不是让整页崩溃
      // （F0 路由冒烟用同一个 api 桩喂所有 GET，形状与真实后端不同）
      setItems(Array.isArray(res?.items) ? res.items : []);
    } catch (err) {
      if (!signal?.aborted) setError(errText(err, "供应商列表加载失败"));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const openEditor = (target: "new" | ProviderConfig) => {
    setForm(target === "new" ? EMPTY_FORM : toForm(target));
    setApiKeyVisible(false);
    setFormError(null);
    setBaseUrlError(null);
    setModelOptions([]);
    setModelDiscoveryError(null);
    setFormTestResult(null);
    setEditor(target);
  };

  const closeEditor = () => {
    // Replacement credentials are transient form input, so clear them when this drawer leaves the workflow.
    setApiKeyVisible(false);
    setForm(EMPTY_FORM);
    setFormTestResult(null);
    setEditor(null);
  };

  const set = <K extends keyof ProviderForm>(key: K, value: ProviderForm[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    if (key === "model" || key === "role") setFormTestResult(null);
  };

  const providerExtra = () => ({
    // Provider updates replace `extra_json`; retain protocol-specific settings while
    // recording this UI's capability selection under one stable, namespaced key.
    ...(editor !== null && editor !== "new" ? editor.extra : {}),
    model_inputs: form.model_inputs,
  });

  const setConnectionField = <K extends "protocol" | "base_url" | "api_key">(
    key: K,
    value: ProviderForm[K],
  ) => {
    // A discovered list belongs to one exact credential and endpoint. Clear it
    // immediately when either changes so a stale model cannot be saved by mistake.
    setForm((prev) => ({ ...prev, [key]: value, model: "" }));
    setModelOptions([]);
    setModelDiscoveryError(null);
    setFormTestResult(null);
  };

  const savedEditor = editor && editor !== "new" ? editor : null;
  const hasUnsavedConnectionChange =
    savedEditor !== null &&
    (form.protocol !== savedEditor.protocol ||
      form.base_url.trim() !== savedEditor.base_url ||
      (Boolean(form.api_key) && form.api_key !== MASKED_API_KEY));
  // A newly selected model still needs a live probe, but the masked key must
  // stay server-side; it therefore uses the saved-key transient test route.
  const hasUnsavedModelChange =
    savedEditor !== null && form.model.trim() !== savedEditor.model;
  // Selecting a model must not force the browser to resend a saved key. Only
  // endpoint or credential changes use the transient server route.
  const usesTransientFormConnection = editor === "new" || hasUnsavedConnectionChange;
  const canDiscoverModels =
    Boolean(form.protocol && form.base_url.trim()) &&
    (usesTransientFormConnection ? hasUsableApiKey(form.api_key) : savedEditor !== null);
  const canTestForm = usesTransientFormConnection
    ? Boolean(
        form.protocol &&
          form.base_url.trim() &&
          hasUsableApiKey(form.api_key) &&
          form.model.trim(),
      )
    : savedEditor !== null;
  // New or modified credentials must be supplied in the current form. A saved,
  // unchanged provider can still use its encrypted server-side credential.
  const modelDiscoveryStatus = canDiscoverModels
    ? null
    : "选择协议并输入 Base URL 和 API Key 后即可获取模型";
  const formTestStatus = canTestForm
    ? null
    : usesTransientFormConnection
      ? "选择模型并输入 API Key 后即可测试当前连接"
      : null;

  const discoverModels = async () => {
    if (!canDiscoverModels || editor === null) return;
    setDiscoveringModels(true);
    setModelDiscoveryError(null);
    try {
      const result = usesTransientFormConnection
        ? await api.post<ProviderModelDiscoveryResult>("/api/admin/providers/discover-models", {
            protocol: form.protocol,
            base_url: form.base_url.trim(),
            api_key: form.api_key,
          })
        : await api.post<ProviderModelDiscoveryResult>(
            `/api/admin/providers/${editor.id}/discover-models`,
          );
      const options = Array.isArray(result.models)
        ? result.models.map((model) => ({ value: model.id, label: model.label }))
        : [];
      setModelOptions(options);
      setForm((prev) => ({
        ...prev,
        model: options.some((option) => option.value === prev.model) ? prev.model : "",
      }));
      if (result.supported === false) {
        setModelDiscoveryError("该协议暂不支持获取模型，请手动填写模型名");
      } else if (options.length === 0) {
        setModelDiscoveryError("供应商未返回可选模型，请手动填写模型名");
      }
    } catch (err) {
      setModelOptions([]);
      setModelDiscoveryError(errText(err, "获取模型失败，请检查供应商配置后重试"));
    } finally {
      setDiscoveringModels(false);
    }
  };

  const validateSave = () => {
    const timeout = Number(form.timeout_seconds);
    if (!form.name.trim() || !form.base_url.trim() || !form.model.trim()) {
      setFormError("名称、base_url 与模型名不能为空");
      return null;
    }
    if (editor === "new" && !form.api_key) {
      setFormError("请填写 API Key（仅录入时提交；编辑态显示固定掩码）");
      return null;
    }
    if (!Number.isFinite(timeout) || timeout <= 0 || timeout > 300) {
      setFormError("超时需为 0-300 秒之间的数字");
      return null;
    }
    return timeout;
  };

  const save = async () => {
    const timeout = validateSave();
    if (timeout === null) return;
    setSaving(true);
    setFormError(null);
    setBaseUrlError(null);
    try {
      if (editor === "new") {
        await api.post("/api/admin/providers", {
          name: form.name.trim(),
          protocol: form.protocol,
          base_url: form.base_url.trim(),
          model: form.model.trim(),
          api_key: form.api_key,
          role: form.role,
          // A configured runtime role must be runnable immediately; operators can
          // still suspend it later using the explicit table-level toggle.
          enabled: form.role === "none" ? form.enabled : true,
          timeout_seconds: timeout,
          extra: providerExtra(),
        });
        toast.success("供应商已创建");
      } else if (editor) {
        // 编辑：api_key 留空不提交（后端语义 = 不更换密钥）
        await api.put<ProviderConfig>(`/api/admin/providers/${editor.id}`, {
          name: form.name.trim(),
          protocol: form.protocol,
          base_url: form.base_url.trim(),
          model: form.model.trim(),
          ...(form.api_key && form.api_key !== MASKED_API_KEY
            ? { api_key: form.api_key }
            : {}),
          role: form.role,
          enabled: form.role === "none" ? form.enabled : true,
          timeout_seconds: timeout,
          extra: providerExtra(),
        });
        toast.success("供应商已更新");
      }
      // Discovery and transient testing already work before persistence, so a
      // successful save can consistently return to the provider table.
      closeEditor();
      await load();
    } catch (err) {
      // NF9：base_url 安全校验失败落到字段旁
      if (err instanceof ApiRequestError && err.code === "INVALID_BASE_URL") {
        setBaseUrlError(err.message);
      } else {
        setFormError(errText(err));
      }
    } finally {
      setSaving(false);
    }
  };

  const requestSave = () => {
    if (validateSave() === null) return;
    const holder =
      form.role !== "none"
        ? items.find((item) => item.role === form.role && item.id !== savedEditor?.id)
        : undefined;
    if (holder) {
      setRoleConfirm({ role: form.role, holderName: holder.name });
      return;
    }
    void save();
  };

  /** 连接测试：响应即最新 last_test，行内更新（PRD-04 §3.3 记录延迟/状态/错误） */
  const runTest = async (p: ProviderConfig) => {
    setTestingId(p.id);
    try {
      // The server limits the live probe to eight seconds; retain one second for
      // request scheduling and response persistence before unblocking the row.
      const result = await api.post<ProviderTestResult>(
        `/api/admin/providers/${p.id}/test`,
        undefined,
        { timeoutMs: 9_000 },
      );
      setItems((prev) =>
        prev.map((item) => (item.id === p.id ? { ...item, last_test: result } : item)),
      );
      if (result.ok) {
        toast.success(`「${p.name}」连接正常（${result.latency_ms}ms）`);
      } else {
        toast.error(`「${p.name}」连接失败：${result.error ?? "未知错误"}`);
      }
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setTestingId(null);
    }
  };

  /**
   * Tests the values visible in the drawer.  A new or changed connection uses
   * the transient route so its key and result cannot leak into provider rows;
   * an untouched saved row keeps the established persisted test behavior.
   */
  const runFormTest = async () => {
    if (!editor || !canTestForm) return;
    setTestingForm(true);
    setFormError(null);
    setBaseUrlError(null);
    try {
      const result = usesTransientFormConnection
        ? await api.post<ProviderTestResult>(
            "/api/admin/providers/test-connection",
            {
              protocol: form.protocol,
              base_url: form.base_url.trim(),
              api_key: form.api_key,
              model: form.model.trim(),
              role: form.role,
            },
            { timeoutMs: 9_000 },
          )
        : hasUnsavedModelChange
          ? await api.post<ProviderTestResult>(
              `/api/admin/providers/${savedEditor!.id}/test-connection`,
              { model: form.model.trim() },
              { timeoutMs: 9_000 },
            )
          : await api.post<ProviderTestResult>(
              `/api/admin/providers/${savedEditor!.id}/test`,
              undefined,
              { timeoutMs: 9_000 },
            );
      setFormTestResult(result);
      if (!usesTransientFormConnection && !hasUnsavedModelChange && savedEditor) {
        setItems((prev) =>
          prev.map((item) => (item.id === savedEditor.id ? { ...item, last_test: result } : item)),
        );
      }
      if (result.ok) {
        toast.success(`连接正常（${result.latency_ms}ms）`);
      } else {
        toast.error(`连接失败：${result.error ?? "未知错误"}`);
      }
    } catch (err) {
      if (err instanceof ApiRequestError && err.code === "INVALID_BASE_URL") {
        setBaseUrlError(err.message);
      } else {
        setFormError(errText(err, "连接测试失败，请检查当前配置后重试"));
      }
    } finally {
      setTestingForm(false);
    }
  };

  /** 删除供应商：后端保留脱敏审计，成功后才从当前列表移除。 */
  const deleteProvider = async () => {
    if (!deleteTarget) return;
    const target = deleteTarget;
    try {
      await api.delete(`/api/admin/providers/${target.id}`);
      setItems((prev) => prev.filter((item) => item.id !== target.id));
      setDeleteTarget(null);
      toast.success(`供应商「${target.name}」已删除`);
    } catch (err) {
      toast.error(errText(err));
    }
  };

  const columns: Column<ProviderConfig>[] = [
    { key: "name", title: "名称", render: (p) => <strong>{p.name}</strong> },
    {
      key: "protocol",
      title: "协议类型",
      width: "170px",
      render: (p) => (
        <span className="provider-protocol">
          <Tag>{PROTOCOL_LABELS[p.protocol] ?? p.protocol}</Tag>
        </span>
      ),
    },
    {
      key: "model",
      title: "模型名",
      render: (p) => <span className="font-mono text-sm">{p.model}</span>,
    },
    { key: "role", title: "角色", width: "100px", render: (p) => <RoleBadge role={p.role} /> },
    {
      key: "model_inputs",
      title: "模型输入",
      width: "150px",
      render: (p) => {
        const inputs = modelInputsFromExtra(p.extra);
        return inputs.length ? (
          <div className="provider-input-types-cell">
            {inputs.map((input) => (
              <Tag key={input}>
                {MODEL_INPUT_OPTIONS.find((option) => option.value === input)?.label ?? input}
              </Tag>
            ))}
          </div>
        ) : (
          <span className="text-muted text-sm">未声明</span>
        );
      },
    },
    {
      key: "last_test",
      title: "最近测试",
      width: "180px",
      render: (p) => <LastTestCell test={p.last_test} />,
    },
    {
      key: "actions",
      title: "操作",
      width: "220px",
      render: (p) => {
        const isTesting = testingId === p.id;
        return (
          <div className="provider-actions flex items-center">
            <Button size="sm" variant="ghost" onClick={() => openEditor(p)}>
              编辑
            </Button>
            <Button
              className="provider-test-button"
              size="sm"
              variant="secondary"
              loading={isTesting}
              aria-busy={isTesting}
              aria-label={isTesting ? "正在测试连接" : "连接测试"}
              onClick={() => void runTest(p)}
            >
              {/* Preserve the idle label width while the loading spinner is overlaid. */}
              <span className="provider-test-button-label">连接测试</span>
            </Button>
            <Button size="sm" variant="danger" onClick={() => setDeleteTarget(p)}>
              删除
            </Button>
          </div>
        );
      },
    },
  ];

  return (
    <div>
      <PageHeader
        title="模型供应商"
        sub="接入主/回退/嵌入/重排模型；API Key 加密存储，编辑时显示固定掩码；同角色全局至多一个供应商"
        actions={<Button onClick={() => openEditor("new")}>新建供应商</Button>}
      />

      {error ? (
        <ErrorState message={error} onRetry={() => void load()} />
      ) : (
        <Card padded={false}>
          <div className="provider-table">
            <DataTable
              ariaLabel="模型供应商列表"
              columns={columns}
              rows={items}
              loading={loading}
              empty={
                <EmptyState
                  title="暂无供应商"
                  hint="配置主模型后 Agent 才能合成自然语言回答；未配置时系统使用内置降级策略"
                />
              }
            />
          </div>
        </Card>
      )}

      {/* 新建/编辑抽屉 */}
      <Drawer
        open={editor !== null}
        title={editor === "new" ? "新建供应商" : `编辑供应商：${form.name}`}
        onClose={closeEditor}
        bodyClassName="provider-drawer-body"
        footerClassName="provider-drawer-footer"
        footer={
          <>
            <Button variant="ghost" onClick={closeEditor}>
              取消
            </Button>
            <Button loading={saving} onClick={requestSave}>
              {editor === "new" ? "创建供应商" : "保存修改"}
            </Button>
          </>
        }
      >
        {formError ? (
          <p className="form-alert form-alert-error" role="alert">
            {formError}
          </p>
        ) : null}
        <Field label="供应商名称" required>
          <Input
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
            placeholder="例如：讯飞星火主模型"
          />
        </Field>
        <Field label="协议类型" required>
          <Select
            aria-label="协议类型"
            value={form.protocol}
            onChange={(e) => setConnectionField("protocol", e.target.value)}
            options={PROTOCOL_OPTIONS}
          />
        </Field>
        <Field label="base_url" required error={baseUrlError ?? undefined}>
          <Input
            value={form.base_url}
            onChange={(e) => setConnectionField("base_url", e.target.value)}
            invalid={!!baseUrlError}
            placeholder="https://api.example.com/v1"
          />
        </Field>
        {/* Saved credentials stay server-side; the fixed mask is cleared only when an administrator edits this field. */}
        <Field
          label={editor === "new" ? "API Key" : "API Key（已保存）"}
          required={editor === "new"}
        >
          <div className="provider-api-key-control">
            <Input
              type={apiKeyVisible ? "text" : "password"}
              aria-label={editor === "new" ? "API Key" : "替换 API Key"}
              value={form.api_key}
              onFocus={() => {
                if (form.api_key === MASKED_API_KEY) {
                  setForm((current) => ({ ...current, api_key: "" }));
                  setApiKeyVisible(false);
                }
              }}
              onChange={(e) => setConnectionField("api_key", e.target.value)}
              placeholder={editor === "new" ? "输入 API Key" : "输入以更换"}
              autoComplete="new-password"
            />
            <IconButton
              type="button"
              className="provider-api-key-visibility-button"
              aria-label={apiKeyVisible ? "隐藏 API Key" : "显示 API Key"}
              title={apiKeyVisible ? "隐藏 API Key" : "显示 API Key"}
              disabled={!form.api_key || form.api_key === MASKED_API_KEY}
              onClick={() => setApiKeyVisible((visible) => !visible)}
            >
              {apiKeyVisible ? (
                <EyeOff size={16} aria-hidden="true" />
              ) : (
                <Eye size={16} aria-hidden="true" />
              )}
            </IconButton>
          </div>
        </Field>
        <Field label="模型名" required>
          <div
            className="provider-model-discovery"
            aria-live="polite"
            aria-busy={discoveringModels}
          >
            <div className="provider-model-control">
              {modelOptions.length > 0 ? (
                <Select
                  aria-label="模型名"
                  value={form.model}
                  onChange={(e) => set("model", e.target.value)}
                  options={modelOptions}
                  placeholder="请选择模型"
                />
              ) : (
                <Input
                  aria-label="模型名"
                  value={form.model}
                  onChange={(e) => set("model", e.target.value)}
                  placeholder="例如：spark-x1 / gpt-4o-mini"
                />
              )}
              <IconButton
                type="button"
                className="provider-model-import-button"
                aria-label="获取模型"
                disabled={!canDiscoverModels || discoveringModels}
                title={modelDiscoveryStatus ?? "获取模型"}
                onClick={() => void discoverModels()}
              >
                {discoveringModels ? (
                  <Spinner size={14} />
                ) : (
                  <Import size={16} aria-hidden="true" />
                )}
              </IconButton>
            </div>
            {modelDiscoveryError || modelDiscoveryStatus ? (
              <p
                className={modelDiscoveryError ? "field-error-text" : "field-hint"}
                role={modelDiscoveryError ? "alert" : undefined}
              >
                {modelDiscoveryError ?? modelDiscoveryStatus}
              </p>
            ) : null}
          </div>
        </Field>
        <Field label="模型输入">
          <ModelInputMultiSelect
            value={form.model_inputs}
            onChange={(modelInputs) => set("model_inputs", modelInputs)}
          />
        </Field>
        <Field label="角色">
          <Select
            aria-label="角色"
            value={form.role}
            onChange={(e) => set("role", e.target.value)}
            options={PROVIDER_ROLE_OPTIONS}
          />
        </Field>
        <div className="provider-timeout-test-row">
          <Field label="超时（秒）">
            <Input
              value={form.timeout_seconds}
              onChange={(e) => set("timeout_seconds", e.target.value)}
              inputMode="decimal"
            />
          </Field>
          <Field label="连接测试">
            <div
              className="provider-form-test"
              role="group"
              aria-label="连接测试"
              aria-live="polite"
            >
              <div className="provider-form-test-button-row">
                <Button
                  type="button"
                  className="provider-form-test-button"
                  variant="secondary"
                  loading={testingForm}
                  aria-busy={testingForm}
                  disabled={!canTestForm}
                  title={formTestStatus ?? "测试当前连接"}
                  onClick={() => void runFormTest()}
                >
                  {/* Keep the label width stable while Button overlays its loading spinner. */}
                  <span className="provider-form-test-button-label">测试连接</span>
                </Button>
                <div className="provider-form-test-result">
                  {formTestResult ? <LastTestCell test={formTestResult} /> : null}
                </div>
              </div>
              {formTestStatus ? <p className="field-hint">{formTestStatus}</p> : null}
            </div>
          </Field>
        </div>
      </Drawer>

      {/* 角色替换确认（同角色独占：替换前讲清后果） */}
      <ConfirmDialog
        open={roleConfirm !== null}
        title="确认角色设置"
        confirmText="确认设置"
        description={
          roleConfirm
            ? `将替换当前${PROVIDER_ROLE_LABELS[roleConfirm.role] ?? roleConfirm.role}「${roleConfirm.holderName}」——原供应商将被降为"无角色"。系统运行时同角色只使用一个供应商。`
            : undefined
        }
        onConfirm={async () => {
          // The drawer is the sole role editor. Keep the confirmation local,
          // then reuse the normal save path so role and connection changes stay atomic.
          setRoleConfirm(null);
          await save();
        }}
        onCancel={() => setRoleConfirm(null)}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        title="删除供应商"
        confirmText="确认删除"
        danger
        description={
          deleteTarget
            ? `确定删除「${deleteTarget.name}」吗？此操作不可恢复；若它当前承担${PROVIDER_ROLE_LABELS[deleteTarget.role] ?? deleteTarget.role}，后续 Agent 调用将使用备用或降级策略。`
            : undefined
        }
        onConfirm={deleteProvider}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
