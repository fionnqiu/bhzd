/**
 * 教师端测试（二）：教学任务发布（PRD-02 §5）。
 *
 * 覆盖验收点：
 * - §5.4 客户端校验：能力节点 ≥1 + 来源资料 ≥1（未满足时绝不发请求）；
 * - §5.4 预览面板常驻渲染，表单编辑实时反映到任务卡；
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

/** 手动添加一条外部链接资源 */
function addResource() {
  fireEvent.change(screen.getByPlaceholderText("资源标题"), {
    target: { value: "标注规范文档" },
  });
  fireEvent.click(screen.getByRole("button", { name: /添加资源/ }));
}

function fillTitle() {
  fireEvent.change(screen.getByPlaceholderText("例如：客服语音情感标注实战"), {
    target: { value: "客服语音情感标注实战" },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedGet.mockImplementation((path, query) => {
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
    if (path === "/api/teacher/resources") {
      return Promise.resolve({
        items: [{ id: "doc-1", title: "已发布标注规范", version: "1.0" }],
        total: 1,
      });
    }
    if (path === "/api/graph/nodes") {
      // SCN 词表为空即可；CAP 恒返回「语音切分」（初始名称映射 + 搜索共用）
      if (query?.type === "SCN") return Promise.resolve({ items: [], total: 0 });
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
  it("uses the teacher published-resource catalog instead of the RAG management API", async () => {
    renderPage();
    expect(document.querySelector(".teacher-task-publish-page")).toBeInTheDocument();
    expect(document.querySelector(".teacher-task-publish-layout")).toBeInTheDocument();
    expect(document.querySelector(".teacher-task-editor-layout")).toBeInTheDocument();
    expect(document.querySelector(".teacher-task-preview")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("tab", { name: "从已发布资料选择" }));

    expect(await screen.findByText("已发布标注规范")).toBeInTheDocument();
    expect(mockedGet).toHaveBeenCalledWith(
      "/api/teacher/resources",
      expect.objectContaining({ limit: 10, offset: 0 }),
      expect.objectContaining({ signal: expect.anything() }),
    );
    expect(mockedGet).not.toHaveBeenCalledWith(
      "/api/rag/documents",
      expect.anything(),
      expect.anything(),
    );
  });

  it("客户端校验：缺少能力节点与来源资料时不发请求并给出字段错误", async () => {
    renderPage();
    // 等基础数据（班级下拉）就绪，避免与初始加载竞争
    expect(await screen.findByDisplayValue("请选择班级")).toBeInTheDocument();

    fillTitle();
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));

    expect(await screen.findByText("任务必须至少关联一个能力节点")).toBeInTheDocument();
    expect(screen.getByText("任务必须至少关联一个来源资料")).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();

    // 补上能力后，资源校验仍在拦截
    await addCap();
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() =>
      expect(screen.queryByText("任务必须至少关联一个能力节点")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("任务必须至少关联一个来源资料")).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
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

    addResource();
    // 资源列表行 + 预览引用卡（预览带 [序号] 前缀）
    expect(await screen.findByText("标注规范文档")).toBeInTheDocument();
    expect(await screen.findByText("[1] 标注规范文档")).toBeInTheDocument();
  });

  it("发布：先保存草稿再 publish，载荷正确并提示发布人数", async () => {
    renderPage();
    expect(await screen.findByDisplayValue("请选择班级")).toBeInTheDocument();

    fillTitle();
    await addCap();
    addResource();

    // 保存草稿：POST /api/teacher/tasks，携带能力与资源
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/teacher/tasks",
        expect.objectContaining({
          title: "客服语音情感标注实战",
          cap_ids: ["CAP-1"],
          resources: [expect.objectContaining({ type: "link", title: "标注规范文档" })],
        }),
      ),
    );
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
    addResource();
    fireEvent.click(screen.getByRole("button", { name: "发布" }));

    expect(await screen.findByText("发布前请选择班级")).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });
});
