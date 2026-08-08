/**
 * 系统管理端页面测试（PRD-04）：供应商校验/测试/角色、RAG 参数脏保存、
 * 用户禁用与重置、审计筛选参数。
 *
 * api 层整体打桩（与 auth-pages.test.tsx 同一模式）。
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { ReactElement } from "react";
import { ApiRequestError, api } from "../src/api/client";
import { ToastProvider } from "../src/components";
import ProvidersPage from "../src/pages/admin/ProvidersPage";
import RagSettingsPage from "../src/pages/admin/RagSettingsPage";
import UsersPage from "../src/pages/admin/UsersPage";
import AuditLogsPage from "../src/pages/admin/AuditLogsPage";

vi.mock("../src/api/client", () => {
  class MockApiRequestError extends Error {
    status: number;
    code: string;
    constructor(status: number, code: string, message: string) {
      super(message);
      this.name = "ApiRequestError";
      this.status = status;
      this.code = code;
    }
  }
  return {
    ApiRequestError: MockApiRequestError,
    api: {
      get: vi.fn(),
      post: vi.fn(),
      put: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
      postForm: vi.fn(),
    },
    request: vi.fn(),
    setCsrfToken: vi.fn(),
    getCsrfToken: vi.fn(() => null),
    setOnUnauthorized: vi.fn(),
  };
});

const mockedGet = vi.mocked(api.get);
const mockedPost = vi.mocked(api.post);
const mockedPut = vi.mocked(api.put);
const mockedPatch = vi.mocked(api.patch);
const mockedDelete = vi.mocked(api.delete);

function renderPage(ui: ReactElement) {
  return render(
    <ToastProvider>
      <MemoryRouter>{ui}</MemoryRouter>
    </ToastProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

/* ---------------------------------------------------------------- 供应商 */

describe("ProvidersPage（PRD-04 §3）", () => {
  const P1 = {
    id: "p1",
    name: "星辰主模型",
    protocol: "xunfei_xingchen",
    base_url: "https://xingchen.example.com/v1",
    model: "xingchen-1",
    role: "primary",
    enabled: true,
    timeout_seconds: 30,
    extra: {},
    api_key_set: true,
    // A deliberately non-secret sentinel guards against accidentally rendering
    // a future backend field that contains a persisted credential.
    api_key: "stored-key-must-not-render",
    last_test: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
  };
  const P2 = {
    ...P1,
    id: "p2",
    name: "备用模型",
    protocol: "chat_completions",
    model: "gpt-x",
    role: "none",
    last_test: {
      ok: false,
      latency_ms: 0,
      model: "gpt-x",
      error: "TIMEOUT",
      tested_at: "2026-07-01T00:00:00Z",
    },
  };

  beforeEach(() => {
    mockedGet.mockResolvedValue({ items: [P1, P2], total: 2 });
    mockedPost.mockResolvedValue({});
    mockedPut.mockResolvedValue(P1);
  });

  it("列表渲染角色徽章与最近测试结果", async () => {
    renderPage(<ProvidersPage />);
    expect(await screen.findByText("星辰主模型")).toBeInTheDocument();
    expect(screen.getByText("主模型")).toBeInTheDocument();
    expect(screen.getByText("讯飞星辰")).toBeInTheDocument();
    expect(screen.getByText(/连接.*TIMEOUT/)).toBeInTheDocument();
    expect(screen.getByText("未测试")).toBeInTheDocument();
    const fallbackRow = screen.getByText("备用模型").closest("tr")!;
    expect(within(fallbackRow).getByRole("button", { name: "删除" })).toBeInTheDocument();
    expect(within(fallbackRow).getByRole("button", { name: "删除" }).parentElement!).toHaveClass(
      "provider-actions",
    );
    expect(
      within(fallbackRow).queryByRole("combobox", { name: "设置 备用模型 的角色" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "流式验证" })).not.toBeInTheDocument();
  });

  it("创建时 base_url 安全校验错误落到字段旁（NF9）", async () => {
    mockedPost.mockRejectedValue(
      new ApiRequestError(400, "INVALID_BASE_URL", "base_url 不允许使用本机或内网地址"),
    );
    renderPage(<ProvidersPage />);
    fireEvent.click(await screen.findByRole("button", { name: "新建供应商" }));
    fireEvent.change(screen.getByPlaceholderText("例如：讯飞星火主模型"), {
      target: { value: "内网测试" },
    });
    fireEvent.change(screen.getByPlaceholderText("https://api.example.com/v1"), {
      target: { value: "http://192.168.1.10/v1" },
    });
    fireEvent.change(screen.getByPlaceholderText("输入 API Key"), {
      target: { value: "sk-secret" },
    });
    // Changing a connection credential intentionally invalidates a prior model choice.
    fireEvent.change(screen.getByPlaceholderText("例如：spark-x1 / gpt-4o-mini"), {
      target: { value: "m1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建供应商" }));
    // 错误落在 base_url 字段旁而非吞掉（表单错误在字段旁的 PRD 口径）
    expect(await screen.findByText("base_url 不允许使用本机或内网地址")).toBeInTheDocument();
    // 创建请求体包含全部必填字段且密钥仅此时提交
    expect(mockedPost).toHaveBeenCalledWith(
      "/api/admin/providers",
      expect.objectContaining({
        name: "内网测试",
        protocol: "chat_completions",
        base_url: "http://192.168.1.10/v1",
        model: "m1",
        api_key: "sk-secret",
      }),
    );
  });

  it("连接测试结果行内更新（状态/延迟）", async () => {
    mockedPost.mockResolvedValue({
      ok: true,
      latency_ms: 120,
      model: "xingchen-1",
      error: null,
      tested_at: "2026-07-02T00:00:00Z",
    });
    renderPage(<ProvidersPage />);
    const row = (await screen.findByText("星辰主模型")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "连接测试" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/admin/providers/p1/test", undefined, {
        timeoutMs: 9_000,
      }),
    );
    expect(await within(row).findByText(/连接.*120ms/)).toBeInTheDocument();
  });

  it("连接测试加载时保留按钮宽度占位并暴露状态", async () => {
    let resolveTest: (result: {
      ok: boolean;
      latency_ms: number;
      model: string;
      error: string | null;
      tested_at: string;
    }) => void;
    const pendingTest = new Promise<{
      ok: boolean;
      latency_ms: number;
      model: string;
      error: string | null;
      tested_at: string;
    }>((resolve) => {
      resolveTest = resolve;
    });
    mockedPost.mockReturnValueOnce(pendingTest);

    renderPage(<ProvidersPage />);
    const row = (await screen.findByText("星辰主模型")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "连接测试" }));

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/admin/providers/p1/test", undefined, {
        timeoutMs: 9_000,
      }),
    );
    const testButton = within(row).getByRole("button", { name: "正在测试连接" });
    expect(testButton).toBeDisabled();
    expect(testButton).toHaveAttribute("aria-busy", "true");
    expect(testButton).toHaveClass("provider-test-button");
    expect(within(testButton).getByRole("status")).toBeInTheDocument();
    expect(within(testButton).getByText("连接测试")).toHaveClass("provider-test-button-label");

    resolveTest!({
      ok: true,
      latency_ms: 120,
      model: "xingchen-1",
      error: null,
      tested_at: "2026-07-02T00:00:00Z",
    });
    expect(await within(row).findByText(/连接.*120ms/)).toBeInTheDocument();
  });

  it("删除前需要确认，取消不会发请求", async () => {
    renderPage(<ProvidersPage />);
    const row = (await screen.findByText("星辰主模型")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "删除" }));
    expect(await screen.findByText(/此操作不可恢复/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(mockedDelete).not.toHaveBeenCalled();
    expect(screen.getByText("星辰主模型")).toBeInTheDocument();
  });

  it("确认删除成功后移除供应商行", async () => {
    mockedDelete.mockResolvedValueOnce({ message: "供应商配置已删除" });
    renderPage(<ProvidersPage />);
    const row = (await screen.findByText("星辰主模型")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "删除" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认删除" }));
    await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith("/api/admin/providers/p1"));
    expect(await screen.findByText("供应商「星辰主模型」已删除")).toBeInTheDocument();
    expect(screen.queryByText("星辰主模型")).not.toBeInTheDocument();
  });

  it("删除失败时保留供应商行并提示错误", async () => {
    mockedDelete.mockRejectedValueOnce(new ApiRequestError(500, "DELETE_FAILED", "删除失败"));
    renderPage(<ProvidersPage />);
    const row = (await screen.findByText("星辰主模型")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "删除" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认删除" }));
    expect(await screen.findByText("删除失败")).toBeInTheDocument();
    expect(screen.getByText("星辰主模型")).toBeInTheDocument();
  });

  it("只在编辑抽屉设置角色，并在替换已有持有者前确认后保存", async () => {
    mockedPut.mockResolvedValueOnce({ ...P2, role: "primary" });
    renderPage(<ProvidersPage />);
    const row = (await screen.findByText("备用模型")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "编辑" }));
    fireEvent.click(screen.getByRole("combobox", { name: "角色" }));
    // 自定义 Select 的 listbox 通过 Portal 挂在全局文档，不能限定到抽屉节点。
    fireEvent.click(screen.getByRole("option", { name: "主模型" }));
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));

    expect(await screen.findByText(/将替换当前主模型「星辰主模型」/)).toBeInTheDocument();
    expect(mockedPut).not.toHaveBeenCalledWith("/api/admin/providers/p2", expect.anything());
    fireEvent.click(screen.getByRole("button", { name: "确认设置" }));
    await waitFor(() =>
      expect(mockedPut).toHaveBeenCalledWith(
        "/api/admin/providers/p2",
        expect.objectContaining({ role: "primary" }),
      ),
    );
    expect(mockedPost).not.toHaveBeenCalledWith(
      "/api/admin/providers/p2/set-role",
      expect.anything(),
    );
  });

  it("新建时可通过模型右侧的导入图标发现并选择模型", async () => {
    mockedPost.mockResolvedValueOnce({
      models: [
        { id: "gpt-4.1-mini", label: "GPT-4.1 Mini" },
        { id: "gpt-4.1", label: "GPT-4.1" },
      ],
    });
    renderPage(<ProvidersPage />);
    fireEvent.click(await screen.findByRole("button", { name: "新建供应商" }));
    fireEvent.change(screen.getByPlaceholderText("https://api.example.com/v1"), {
      target: { value: "https://api.example.com/v1" },
    });
    fireEvent.change(screen.getByPlaceholderText("输入 API Key"), {
      target: { value: "sk-discovery" },
    });
    const modelInput = screen.getByPlaceholderText("例如：spark-x1 / gpt-4o-mini");
    const discoverButton = screen.getByRole("button", { name: "获取模型" });
    expect(discoverButton).toHaveClass("icon-btn");
    expect(discoverButton).toHaveClass("provider-model-import-button");
    expect(discoverButton).toHaveAttribute("title", "获取模型");
    expect(discoverButton).not.toHaveTextContent("获取模型");
    expect(discoverButton.querySelector("svg.lucide-import")).not.toBeNull();
    // The compact action belongs to the model field, so it remains adjacent
    // when the field switches from free input to the discovered combobox.
    expect(modelInput.parentElement).toContainElement(discoverButton);
    fireEvent.click(discoverButton);

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/admin/providers/discover-models", {
        protocol: "chat_completions",
        base_url: "https://api.example.com/v1",
        api_key: "sk-discovery",
      }),
    );
    const modelSelect = await screen.findByRole("combobox", { name: "模型名" });
    expect(modelSelect.closest(".provider-model-control")).toContainElement(discoverButton);
    fireEvent.click(modelSelect);
    fireEvent.click(screen.getByRole("option", { name: "GPT-4.1 Mini" }));
    expect(modelSelect).toHaveTextContent("GPT-4.1 Mini");
  });

  it("编辑时 API Key 仅显示已保存状态且不回显，并可发现模型", async () => {
    mockedPost.mockResolvedValueOnce({ models: [{ id: "gpt-x", label: "GPT X" }] });
    renderPage(<ProvidersPage />);
    const row = (await screen.findByText("备用模型")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "编辑" }));
    expect(screen.getByText("API Key（已保存）")).toBeInTheDocument();
    const apiKeyInput = screen.getByPlaceholderText("输入以更换");
    expect(apiKeyInput).toHaveValue("");
    expect(screen.queryByDisplayValue("stored-key-must-not-render")).not.toBeInTheDocument();

    const modelInput = screen.getByPlaceholderText("例如：spark-x1 / gpt-4o-mini");
    const discoverButton = screen.getByRole("button", { name: "获取模型" });
    expect(discoverButton).toHaveClass("icon-btn");
    expect(discoverButton).toHaveClass("provider-model-import-button");
    expect(modelInput.parentElement).toContainElement(discoverButton);
    fireEvent.click(discoverButton);

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/admin/providers/p2/discover-models"),
    );
  });

  it("显示或隐藏只作用于本次输入的替换 API Key", async () => {
    renderPage(<ProvidersPage />);
    const row = (await screen.findByText("备用模型")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "编辑" }));

    const apiKeyInput = screen.getByPlaceholderText("输入以更换");
    const showButton = screen.getByRole("button", { name: "显示 API Key" });
    expect(apiKeyInput).toHaveValue("");
    expect(apiKeyInput).toHaveAttribute("type", "password");
    expect(showButton).toBeDisabled();

    // Visibility is available only after an administrator supplies a new replacement value.
    fireEvent.change(apiKeyInput, { target: { value: "test-replacement-value" } });
    expect(apiKeyInput).toHaveValue("test-replacement-value");
    expect(showButton).toBeEnabled();
    fireEvent.click(showButton);
    expect(apiKeyInput).toHaveAttribute("type", "text");

    const hideButton = screen.getByRole("button", { name: "隐藏 API Key" });
    fireEvent.click(hideButton);
    expect(apiKeyInput).toHaveAttribute("type", "password");
    expect(screen.queryByDisplayValue("stored-key-must-not-render")).not.toBeInTheDocument();
  });

  it("编辑时未输入替换 API Key 的保存请求不携带 api_key", async () => {
    renderPage(<ProvidersPage />);
    const row = (await screen.findByText("备用模型")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "编辑" }));
    expect(screen.getByPlaceholderText("输入以更换")).toHaveValue("");

    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    await waitFor(() => expect(mockedPut).toHaveBeenCalled());
    const updateCall = mockedPut.mock.calls.find(([path]) => path === "/api/admin/providers/p2");

    // An empty replacement field preserves the server-stored credential instead of resubmitting it.
    expect(updateCall).toBeDefined();
    expect(updateCall?.[1]).not.toHaveProperty("api_key");
  });

  it("编辑抽屉隐藏固定说明，仅在需要操作时显示状态", async () => {
    renderPage(<ProvidersPage />);
    const row = (await screen.findByText("备用模型")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "编辑" }));

    expect(
      screen.queryByText("仅允许公网 HTTPS 地址；禁止本机与内网地址（NF9 安全校验）"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("AES-256-GCM 加密存储；仅录入时提交，永不回显"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("使用已加密保存的 API Key 获取可用模型，密钥不会回显"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("0-300")).not.toBeInTheDocument();
    expect(screen.queryByText("同角色全局至多一个")).not.toBeInTheDocument();
  });

  it("连接字段变更会清空已发现模型，并允许用当前表单重新获取", async () => {
    mockedPost.mockResolvedValueOnce({ models: [{ id: "gpt-x", label: "GPT X" }] });
    renderPage(<ProvidersPage />);
    const row = (await screen.findByText("备用模型")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "编辑" }));
    fireEvent.click(screen.getByRole("button", { name: "获取模型" }));
    const modelSelect = await screen.findByRole("combobox", { name: "模型名" });
    fireEvent.click(modelSelect);
    fireEvent.click(screen.getByRole("option", { name: "GPT X" }));

    fireEvent.change(screen.getByPlaceholderText("https://api.example.com/v1"), {
      target: { value: "https://replacement.example.com/v1" },
    });
    // A model list belongs to the prior endpoint and credential, so the stale selection must vanish.
    expect(screen.queryByRole("combobox", { name: "模型名" })).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("例如：spark-x1 / gpt-4o-mini")).toHaveValue("");
    expect(
      screen.getByText("选择协议并输入 Base URL 和 API Key 后即可获取模型"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "获取模型" })).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("输入以更换"), {
      target: { value: "sk-replacement" },
    });
    expect(screen.getByRole("button", { name: "获取模型" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "获取模型" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/admin/providers/discover-models", {
        protocol: "chat_completions",
        base_url: "https://replacement.example.com/v1",
        api_key: "sk-replacement",
      }),
    );
  });

  it("新建抽屉可在保存前测试当前连接", async () => {
    mockedPost.mockResolvedValueOnce({
      ok: true,
      role: "none",
      latency_ms: 42,
      model: "manual-model",
      error: null,
      tested_at: "2026-08-08T00:00:00Z",
    });
    renderPage(<ProvidersPage />);
    fireEvent.click(await screen.findByRole("button", { name: "新建供应商" }));
    fireEvent.change(screen.getByPlaceholderText("https://api.example.com/v1"), {
      target: { value: "https://api.example.com/v1" },
    });
    fireEvent.change(screen.getByPlaceholderText("输入 API Key"), {
      target: { value: "sk-form-test" },
    });
    fireEvent.change(screen.getByPlaceholderText("例如：spark-x1 / gpt-4o-mini"), {
      target: { value: "manual-model" },
    });
    const testButton = screen.getByRole("button", { name: "测试连接" });
    expect(testButton).toBeEnabled();
    fireEvent.click(testButton);
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/admin/providers/test-connection",
        {
          protocol: "chat_completions",
          base_url: "https://api.example.com/v1",
          api_key: "sk-form-test",
          model: "manual-model",
          role: "none",
        },
        { timeoutMs: 9_000 },
      ),
    );
    expect(await screen.findByText(/连接 · ✓ 42ms/)).toBeInTheDocument();
  });

  it("发现模型失败后仍允许手工填写模型名", async () => {
    mockedPost.mockRejectedValueOnce(
      new ApiRequestError(502, "PROVIDER_UNAVAILABLE", "供应商模型目录暂不可用"),
    );
    renderPage(<ProvidersPage />);
    fireEvent.click(await screen.findByRole("button", { name: "新建供应商" }));
    fireEvent.change(screen.getByPlaceholderText("https://api.example.com/v1"), {
      target: { value: "https://api.example.com/v1" },
    });
    fireEvent.change(screen.getByPlaceholderText("输入 API Key"), {
      target: { value: "sk-fallback" },
    });
    fireEvent.click(screen.getByRole("button", { name: "获取模型" }));

    expect(await screen.findByText("供应商模型目录暂不可用")).toBeInTheDocument();
    const modelInput = screen.getByPlaceholderText("例如：spark-x1 / gpt-4o-mini");
    fireEvent.change(modelInput, { target: { value: "manual-model" } });
    expect(modelInput).toHaveValue("manual-model");
  });
});

/* ---------------------------------------------------------------- RAG 参数 */

describe("RagSettingsPage（PRD-04 §4）", () => {
  const SETTINGS = {
    id: 1,
    chunk_size: 500,
    chunk_overlap: 80,
    title_inherit: true,
    table_strategy: "keep",
    top_k: 5,
    score_threshold: 0.35,
    hybrid_search: true,
    rerank_enabled: false,
    citation_format: "【{title} {section} {page} v{version}】",
    refusal_policy: "refuse",
    max_citations: 5,
    prompt_template: "你是助教……",
    prompt_template_version: "v1",
    require_manual_review: true,
    student_visibility_default: "student",
    expired_doc_policy: "remove",
    updated_at: "2026-07-01T00:00:00Z",
    updated_by: "admin-1",
  };

  beforeEach(() => {
    mockedGet.mockResolvedValue(SETTINGS);
    mockedPatch.mockResolvedValue({ ...SETTINGS, chunk_size: 800 });
  });

  it("干净状态保存禁用；修改后只 PATCH 变更字段", async () => {
    renderPage(<RagSettingsPage />);
    const saveBtn = (await screen.findByRole("button", { name: "保存参数" })) as HTMLButtonElement;
    expect(saveBtn.disabled).toBe(true);
    fireEvent.change(screen.getByRole("spinbutton", { name: "chunk_size（切片长度）" }), {
      target: { value: "800" },
    });
    const dirtyBtn = await screen.findByRole("button", { name: "保存参数（1 项变更）" });
    expect((dirtyBtn as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(dirtyBtn);
    await waitFor(() =>
      // 只提交变更字段：审计 before/after 精确（PRD-04 §4.2）
      expect(mockedPatch).toHaveBeenCalledWith("/api/admin/rag-settings", { chunk_size: 800 }),
    );
    expect(await screen.findByText("已保存并记录审计日志")).toBeInTheDocument();
  });

  it("chunk_overlap ≥ chunk_size 时客户端拦截", async () => {
    renderPage(<RagSettingsPage />);
    // 等设置加载完成（首渲染为加载态）
    const overlapInput = await screen.findByRole("spinbutton", {
      name: "chunk_overlap（重叠长度）",
    });
    fireEvent.change(overlapInput, { target: { value: "600" } });
    expect(await screen.findByText("chunk_overlap 必须小于 chunk_size")).toBeInTheDocument();
    const saveBtn = screen.getByRole("button", { name: /保存参数/ }) as HTMLButtonElement;
    expect(saveBtn.disabled).toBe(true);
    expect(mockedPatch).not.toHaveBeenCalled();
  });
});

/* ---------------------------------------------------------------- 用户权限 */

describe("UsersPage（PRD-04 §5）", () => {
  const U1 = {
    id: "u1",
    email: "student@demo.bhzd",
    name: "学生甲",
    role: "student",
    status: "active",
    email_verified: true,
    created_at: "2026-07-01T00:00:00Z",
  };
  const U2 = { ...U1, id: "u2", email: "admin@demo.bhzd", name: "管理员乙", role: "system_admin" };

  beforeEach(() => {
    mockedGet.mockResolvedValue({ items: [U1, U2], total: 2 });
    mockedPatch.mockResolvedValue(U1);
    mockedPost.mockResolvedValue({
      temporary_password: "Temp1234Aa1",
      message: "临时密码已生成",
    });
  });

  it("禁用走确认框并 PATCH status；自我禁用透传后端话术", async () => {
    renderPage(<UsersPage />);
    // 禁用普通用户
    const row1 = (await screen.findByText("学生甲")).closest("tr")!;
    fireEvent.click(within(row1).getByRole("button", { name: "禁用" }));
    expect(await screen.findByText(/将立即终止其全部会话/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认禁用" }));
    await waitFor(() =>
      expect(mockedPatch).toHaveBeenCalledWith("/api/admin/users/u1", { status: "disabled" }),
    );
    // 自我禁用：后端 400 → 话术 toast（前端不拦截）
    mockedPatch.mockRejectedValue(
      new ApiRequestError(400, "SELF_OPERATION_FORBIDDEN", "不能禁用当前登录的管理员账号"),
    );
    const row2 = screen.getByText("管理员乙").closest("tr")!;
    fireEvent.click(within(row2).getByRole("button", { name: "禁用" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认禁用" }));
    expect(await screen.findByText("不能禁用当前登录的管理员账号")).toBeInTheDocument();
  });

  it("重置密码：确认后临时密码仅展示一次", async () => {
    renderPage(<UsersPage />);
    const row = (await screen.findByText("学生甲")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "重置密码" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认重置" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/admin/users/u1/reset-password"),
    );
    expect(await screen.findByText("Temp1234Aa1")).toBeInTheDocument();
    expect(screen.getByText(/仅本次展示/)).toBeInTheDocument();
  });

  it("编辑角色走 PATCH 并提示审计", async () => {
    renderPage(<UsersPage />);
    const row = (await screen.findByText("学生甲")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "编辑角色" }));
    expect(await screen.findByText(/权限变更将记录审计日志/)).toBeInTheDocument();
    // 触发器在弹窗内；选项通过 Portal 挂在全局文档，不能按 dialog 限定。
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "教师" }));
    fireEvent.click(screen.getByRole("button", { name: "保存角色" }));
    await waitFor(() =>
      expect(mockedPatch).toHaveBeenCalledWith("/api/admin/users/u1", { role: "teacher" }),
    );
  });
});

/* ---------------------------------------------------------------- 审计日志 */

describe("AuditLogsPage（PRD-04 §7）", () => {
  const LOG = {
    id: "log-1",
    actor_id: "admin-1-abcdef",
    actor_role: "system_admin",
    action: "provider.set_role",
    target_type: "provider",
    target_id: "p1",
    before: { role: "none" },
    after: { role: "primary" },
    ip: "10.0.0.8",
    user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome",
    created_at: "2026-07-02T00:00:00Z",
  };

  beforeEach(() => {
    mockedGet.mockResolvedValue({ items: [LOG], total: 1 });
  });

  it("渲染 before→after 变更摘要与只读说明", async () => {
    renderPage(<AuditLogsPage />);
    expect(await screen.findByText("provider.set_role")).toBeInTheDocument();
    expect(screen.getByText("role: none → primary")).toBeInTheDocument();
    // 页头副标题与底部说明各出现一次
    expect(screen.getAllByText(/审计日志不允许删除/).length).toBeGreaterThan(0);
  });

  it("筛选条件映射为查询参数", async () => {
    renderPage(<AuditLogsPage />);
    await screen.findByText("provider.set_role");
    fireEvent.change(screen.getByPlaceholderText("操作人 ID（actor_id）"), {
      target: { value: "admin-1" },
    });
    fireEvent.click(screen.getByRole("combobox", { name: "动作类型" }));
    fireEvent.click(screen.getByRole("option", { name: "provider.update" }));
    fireEvent.click(screen.getByRole("combobox", { name: "目标类型" }));
    fireEvent.click(screen.getByRole("option", { name: "provider" }));
    fireEvent.change(screen.getByLabelText("起始时间"), { target: { value: "2026-07-01T00:00" } });
    fireEvent.change(screen.getByLabelText("截止时间"), { target: { value: "2026-07-31T23:59" } });
    await waitFor(() =>
      expect(mockedGet).toHaveBeenLastCalledWith(
        "/api/admin/audit-logs",
        {
          actor_id: "admin-1",
          action: "provider.update",
          target_type: "provider",
          from: "2026-07-01T00:00",
          to: "2026-07-31T23:59",
          limit: 20,
          offset: 0,
        },
        expect.objectContaining({ signal: expect.anything() }),
      ),
    );
  });
});
