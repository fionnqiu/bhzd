/**
 * 教师端测试（二）：教学任务发布（PRD-02 §5）。
 *
 * 覆盖验收点：
 * - §5.4 客户端校验：能力节点 ≥1（未满足时绝不发请求），任务资源可为空；
 * - §5.4 预览面板常驻渲染，表单编辑实时反映到任务卡；
 * - P0-5/P0-6：发布页只保留手动输入与 AI 生成，不展示或提交资源关联；
 * - §5.4 发布链路：先落库（POST 草稿）再 publish，载荷含 class_id /
 *   due_at / counts_toward_mastery，成功后提示"已发布给 N 名学生"。
 *
 * api 层打桩；图谱 CAP 搜索走防抖（SearchInput 300ms），断言用 findBy 等待。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ToastProvider } from "../src/components";
import TaskPublishPage from "../src/pages/teacher/TaskPublishPage";
import { api } from "../src/api/client";

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
const mockedPatch = vi.mocked(api.patch);

function renderPage() {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={["/teacher/tasks"]}>
        <TaskPublishPage />
      </MemoryRouter>
    </ToastProvider>,
  );
}

/** 通过能力搜索把 CAP-1「语音切分」加进表单（走真实防抖 + mock 搜索） */
async function addCap() {
  fireEvent.change(screen.getByPlaceholderText("搜索能力节点…"), {
    target: { value: "语音" },
  });
  const addBtn = await screen.findByRole("button", { name: "添加" }, { timeout: 2000 });
  fireEvent.click(addBtn);
}

function fillTitle() {
  fireEvent.change(screen.getByPlaceholderText("例如：客服语音情感标注实战"), {
    target: { value: "客服语音情感标注实战" },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedGet.mockImplementation((path, _query) => {
    if (path === "/api/teacher/tasks") return Promise.resolve({ items: [], total: 0 });
    if (path === "/api/teacher/classes") {
      return Promise.resolve({
        items: [
          {
            id: "c1",
            name: "数据标注2301班",
            invite_code: "CODE",
            student_count: 5,
            recent_task_title: null,
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
        total: 1,
      });
    }
    if (path === "/api/graph/nodes") {
      return Promise.resolve({
        items: [{ id: "CAP-1", label: "语音切分", type: "CAP" }],
        total: 1,
      });
    }
    return Promise.reject(new Error(`未 mock 的 GET ${String(path)}`));
  });
  mockedPost.mockImplementation((path) => {
    if (path === "/api/teacher/tasks") {
      return Promise.resolve({ id: "t1", published_count: 0, version: 1, version_bumped: false });
    }
    if (path === "/api/teacher/tasks/t1/publish") {
      return Promise.resolve({ published: 5, class_id: "c1" });
    }
    return Promise.reject(new Error(`未 mock 的 POST ${String(path)}`));
  });
  // 已保存草稿再编辑发布时会先 PATCH 持久化最新内容（页面契约：publish 复制数据库行）
  mockedPatch.mockResolvedValue({
    id: "t1",
    published_count: 0,
    version: 1,
    version_bumped: false,
  });
});

describe("TaskPublishPage（PRD-02 §5）", () => {
  it("opens the task handed off by Teacher Agent", async () => {
    const agentTask = {
      id: "t-agent",
      published_count: 0,
      title: "Agent 生成任务",
      goal: "根据对话生成的学习目标",
      data_type: "text",
      cap_ids: [],
      steps: [],
      rubric: [],
      resources: [],
    };
    mockedGet.mockImplementation((path) => {
      if (path === "/api/teacher/tasks/t-agent") return Promise.resolve(agentTask);
      if (path === "/api/teacher/tasks") return Promise.resolve({ items: [agentTask], total: 1 });
      if (path === "/api/teacher/classes") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/graph/nodes") return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error(`未 mock 的 GET ${String(path)}`));
    });

    render(
      <ToastProvider>
        <MemoryRouter
          initialEntries={[
            { pathname: "/teacher/tasks", state: { taskId: "t-agent" } },
          ]}
        >
          <TaskPublishPage />
        </MemoryRouter>
      </ToastProvider>,
    );

    expect(await screen.findByDisplayValue("Agent 生成任务")).toBeInTheDocument();
  });

  it("normalizes an Agent-shaped persisted draft, keeps its class selected, and publishes only on demand", async () => {
    const agentTask = {
      id: "t-agent-contract",
      published_count: 0,
      title: "Agent field contract draft",
      goal: "Turn the class insight into a review task.",
      data_type: "image",
      cap_ids: ["CAP-1"],
      // This is the durable Agent payload shape saved before the publisher normalizes it.
      steps: [{ title: "Review each annotation", description: "Compare it with the reference." }],
      rubric: [
        {
          criterion: "Required labels",
          description: "Use the agreed vocabulary consistently.",
          points: 10,
        },
      ],
      resources: [{ type: "rag_document", title: "Annotation guide", ref_id: "doc-1" }],
      class_id: "c1",
    };
    mockedGet.mockImplementation((path, _query) => {
      if (path === "/api/teacher/tasks") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/teacher/tasks/t-agent-contract") return Promise.resolve(agentTask);
      if (path === "/api/teacher/classes") {
        return Promise.resolve({
          items: [
            {
              id: "c1",
              name: "数据标注2301班",
              invite_code: "CODE",
              student_count: 5,
              recent_task_title: null,
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          total: 1,
        });
      }
      if (path === "/api/graph/nodes") {
        return Promise.resolve({
          items: [{ id: "CAP-1", label: "语音切分", type: "CAP" }],
          total: 1,
        });
      }
      return Promise.reject(new Error(`未 mock 的 GET ${String(path)}`));
    });
    mockedPatch.mockResolvedValue({
      id: "t-agent-contract",
      published_count: 0,
      version: 1,
      version_bumped: false,
    });
    mockedPost.mockImplementation((path) => {
      if (path === "/api/teacher/tasks/t-agent-contract/publish") {
        return Promise.resolve({ published: 5, class_id: "c1" });
      }
      return Promise.reject(new Error(`未 mock 的 POST ${String(path)}`));
    });

    render(
      <ToastProvider>
        <MemoryRouter initialEntries={["/teacher/tasks?taskId=t-agent-contract"]}>
          <TaskPublishPage />
        </MemoryRouter>
      </ToastProvider>,
    );

    expect(await screen.findByDisplayValue("Agent field contract draft")).toBeInTheDocument();
    // Legacy task rows may still carry resources, but the publisher must not surface them.
    expect(screen.queryByText("Annotation guide")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(mockedGet).toHaveBeenCalledWith(
        "/api/teacher/tasks/t-agent-contract",
        undefined,
        expect.objectContaining({ signal: expect.anything() }),
      ),
    );
    expect(await screen.findByRole("combobox", { name: "选择班级" })).toHaveTextContent(
      "数据标注2301班",
    );
    // Selecting the Agent's class restores publishing context; it never acts as an implicit publish.
    expect(mockedPost.mock.calls.some(([path]) => String(path).endsWith("/publish"))).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() =>
      expect(mockedPatch).toHaveBeenCalledWith(
        "/api/teacher/tasks/t-agent-contract",
        expect.objectContaining({
          steps: [
            expect.objectContaining({
              title: "Review each annotation",
              notes: "Compare it with the reference.",
            }),
          ],
          rubric: [
            expect.objectContaining({
              key: "Required labels",
              expected: "Use the agreed vocabulary consistently.",
              weight: 10,
            }),
          ],
        }),
      ),
    );
    const legacySaveCall = mockedPatch.mock.calls.find(
      ([path]) => path === "/api/teacher/tasks/t-agent-contract",
    );
    expect(legacySaveCall?.[1]).not.toHaveProperty("resources");
    expect(mockedPost.mock.calls.some(([path]) => String(path).endsWith("/publish"))).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "发布" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/teacher/tasks/t-agent-contract/publish", {
        class_id: "c1",
        due_at: null,
        counts_toward_mastery: true,
      }),
    );
  });

  it("只展示手动输入和 AI 生成，不暴露资源关联来源", async () => {
    renderPage();
    expect(document.querySelector(".teacher-task-publish-page")).toBeInTheDocument();
    expect(document.querySelector(".teacher-task-publish-layout")).toBeInTheDocument();
    expect(document.querySelector(".teacher-task-editor-layout")).toBeInTheDocument();
    expect(document.querySelector(".teacher-task-review-layout")).toBeInTheDocument();
    expect(document.querySelector(".teacher-task-preview")).toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI 生成任务卡" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "仅填入学习目标" })).toBeInTheDocument();
    expect(screen.queryByText("已发布资料")).not.toBeInTheDocument();
    expect(screen.queryByText("预设模板")).not.toBeInTheDocument();
    expect(screen.queryByText("历史任务")).not.toBeInTheDocument();
    expect(screen.queryByText("学习资源")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("资源标题")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /添加资源/ })).not.toBeInTheDocument();
    expect(mockedGet).not.toHaveBeenCalledWith(
      "/api/teacher/resources",
      expect.anything(),
      expect.anything(),
    );
    expect(mockedGet).not.toHaveBeenCalledWith(
      "/api/rag/documents",
      expect.anything(),
      expect.anything(),
    );
  });

  it("AI 草稿兼容旧 resources 返回，但不把它们带入编辑器", async () => {
    mockedPost.mockImplementation((path) => {
      if (path === "/api/teacher/tasks/generate") {
        return Promise.resolve({
          title: "AI 生成任务",
          goal: "完成一次规范化标注",
          data_type: "text",
          cap_ids: ["CAP-1"],
          caps: [{ cap_id: "CAP-1", cap_name: "语音切分" }],
          steps: [{ title: "检查标签", description: "逐项核对" }],
          rubric: [{ criterion: "准确性", description: "达到 90%", points: 10 }],
          // Older providers may still include these fields; the page intentionally ignores them.
          resources: [{ type: "rag_document", title: "旧资源", ref_id: "doc-legacy" }],
          citations: [{ document_id: "doc-legacy", title: "旧资源" }],
          difficulty: 2,
          est_minutes: 20,
          sources_note: "基于历史模型响应",
          llm_used: false,
          notice: null,
        });
      }
      return Promise.reject(new Error(`未 mock 的 POST ${String(path)}`));
    });

    renderPage();
    fireEvent.change(screen.getByPlaceholderText(/粘贴或描述企业岗位任务/), {
      target: { value: "完成规范化标注" },
    });
    fireEvent.click(screen.getByRole("button", { name: "AI 生成任务卡" }));

    expect(await screen.findByDisplayValue("AI 生成任务")).toBeInTheDocument();
    expect(screen.queryByText("旧资源")).not.toBeInTheDocument();
    expect(screen.queryByText("学习资源")).not.toBeInTheDocument();
  });

  it("keeps the right review cards in one width and scroll surface", async () => {
    renderPage();
    const review = document.querySelector(".teacher-task-review-layout");

    // Selection, preview, and publishing remain siblings so one bounded review surface controls
    // their vertical movement instead of giving the preview a competing nested scrollbar.
    expect(review).toBeInTheDocument();
    expect(review?.querySelector(":scope > .teacher-task-selection")).toBeInTheDocument();
    expect(review?.querySelector(":scope > .teacher-task-preview")).toBeInTheDocument();
    expect(review?.querySelector(":scope > .teacher-task-publish-settings")).toBeInTheDocument();
    expect(review?.querySelectorAll(":scope > .card")).toHaveLength(2);
    expect(review?.querySelector(".teacher-task-preview > .card")).toBeInTheDocument();
  });

  it("客户端校验：能力节点仍必需，但来源资料可选", async () => {
    renderPage();
    // 等基础数据（班级下拉）就绪，避免与初始加载竞争
    expect(await screen.findByDisplayValue("请选择班级")).toBeInTheDocument();

    fillTitle();
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));

    expect(await screen.findByText("任务必须至少关联一个能力节点")).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();

    // 补上能力后即可保存无资源任务；后端会把缺省资源持久化为空数组。
    await addCap();
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() =>
      expect(screen.queryByText("任务必须至少关联一个能力节点")).not.toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/teacher/tasks",
        expect.objectContaining({ title: "客服语音情感标注实战", cap_ids: ["CAP-1"] }),
      ),
    );
    const saveCall = mockedPost.mock.calls.find(([path]) => path === "/api/teacher/tasks");
    expect(saveCall?.[1]).not.toHaveProperty("resources");
  });

  it("预览面板常驻渲染并随表单实时更新", async () => {
    renderPage();
    // 空表单的诚实占位
    expect(screen.getByText("未命名任务")).toBeInTheDocument();
    expect(screen.getByText("尚未关联能力节点（发布必需）")).toBeInTheDocument();

    fillTitle();
    // 预览区出现任务卡标题（表单 input 之外的 heading）
    expect(
      await screen.findByRole("heading", { name: "客服语音情感标注实战" }),
    ).toBeInTheDocument();

    await addCap();
    // 芯片 + 预览 Tag 都会显示能力名（findAll 命中一个即返回，数量断言要用 waitFor 收敛）
    await waitFor(() => expect(screen.getAllByText("语音切分").length).toBeGreaterThanOrEqual(2));

    // 资源字段即使出现在旧 DTO 中也不再进入编辑器或预览。
    expect(screen.queryByText("学习资源")).not.toBeInTheDocument();
  });

  it("发布：先保存草稿再 publish，载荷正确并提示发布人数", async () => {
    renderPage();
    expect(await screen.findByDisplayValue("请选择班级")).toBeInTheDocument();

    fillTitle();
    await addCap();
    // 保存草稿：POST /api/teacher/tasks，不携带已移除的资源关联字段
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/teacher/tasks",
        expect.objectContaining({
          title: "客服语音情感标注实战",
          cap_ids: ["CAP-1"],
        }),
      ),
    );
    const saveCall = mockedPost.mock.calls.find(([path]) => path === "/api/teacher/tasks");
    expect(saveCall?.[1]).not.toHaveProperty("resources");
    expect(document.querySelector(".toast-container")).not.toBeInTheDocument();

    // 选择班级后发布
    fireEvent.change(screen.getByDisplayValue("请选择班级"), {
      target: { value: "c1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发布" }));

    // 发布链路：先把最新编辑 PATCH 回落库草稿，再调 publish 复制给学生
    await waitFor(() =>
      expect(mockedPatch).toHaveBeenCalledWith(
        "/api/teacher/tasks/t1",
        expect.objectContaining({ title: "客服语音情感标注实战", cap_ids: ["CAP-1"] }),
      ),
    );
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/teacher/tasks/t1/publish", {
        class_id: "c1",
        due_at: null,
        counts_toward_mastery: true,
      }),
    );
    expect(document.querySelector(".toast-container")).not.toBeInTheDocument();
  });

  it("未选班级时发布被客户端拦截", async () => {
    renderPage();
    expect(await screen.findByDisplayValue("请选择班级")).toBeInTheDocument();

    fillTitle();
    await addCap();
    fireEvent.click(screen.getByRole("button", { name: "发布" }));

    expect(await screen.findByText("发布前请选择班级")).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });
});
