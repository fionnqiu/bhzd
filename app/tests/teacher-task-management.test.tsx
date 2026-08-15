/**
 * 教师任务管理中心回归测试（P0-6）。
 *
 * 只打桩任务列表接口，验证目录页自己的筛选与导航契约；发布表单的字段校验和
 * 写入链路继续由 teacher-tasks.test.tsx 覆盖，避免把两个工作流耦合成一个脆弱用例。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ToastProvider } from "../src/components";
import TasksManagePage from "../src/pages/teacher/TasksManagePage";
import { api } from "../src/api/client";
import { routes } from "../src/app/router";

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

const draftTask = {
  id: "draft-1",
  title: "草稿任务",
  goal: null,
  data_type: "text",
  cap_ids: [],
  steps: [],
  resources: [],
  rubric: null,
  practice: null,
  status: "draft" as const,
  class_id: null,
  version: 1,
  parent_task_id: null,
  published_count: 0,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-02T00:00:00Z",
};

const publishedTask = {
  ...draftTask,
  id: "published-1",
  title: "已发布任务",
  data_type: "audio",
  published_count: 3,
  updated_at: "2026-08-03T00:00:00Z",
};

function renderPage() {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={["/teacher/tasks"]}>
        <TasksManagePage />
      </MemoryRouter>
    </ToastProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedGet.mockResolvedValue({ items: [draftTask, publishedTask], total: 2 });
});

describe("TasksManagePage（P0-6）", () => {
  it("列出草稿与已发布任务，并提供编辑/发布入口", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "任务管理" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "草稿任务" })).toHaveAttribute(
      "href",
      "/teacher/tasks/draft-1",
    );
    expect(screen.getByRole("link", { name: "已发布任务" })).toHaveAttribute(
      "href",
      "/teacher/tasks/published-1",
    );
    expect(screen.getByRole("link", { name: "发布 草稿任务" })).toHaveAttribute(
      "href",
      "/teacher/tasks/draft-1",
    );
    expect(screen.getByRole("link", { name: "再次发布 已发布任务" })).toHaveAttribute(
      "href",
      "/teacher/tasks/published-1",
    );
    expect(screen.getAllByRole("button", { name: "新建任务" }).length).toBeGreaterThan(0);
  });

  it("按草稿/已发布筛选而不重新请求接口", async () => {
    renderPage();
    expect(await screen.findByText("已发布任务")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "草稿" }));
    expect(screen.getByRole("link", { name: "草稿任务" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "已发布任务" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "已发布" }));
    expect(screen.getByRole("link", { name: "已发布任务" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "草稿任务" })).not.toBeInTheDocument();
    expect(mockedGet).toHaveBeenCalledTimes(1);
  });

  it("显示加载失败并支持重试", async () => {
    mockedGet.mockRejectedValueOnce(new Error("network"));
    renderPage();
    expect(await screen.findByText("任务列表加载失败")).toBeInTheDocument();

    mockedGet.mockResolvedValueOnce({ items: [], total: 0 });
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(screen.getByText("还没有教学任务")).toBeInTheDocument());
  });

  it("registers the management, new, and edit routes under the teacher shell", () => {
    const teacherRoute = routes.find((route) => route.path === "/teacher");
    const childPaths = teacherRoute?.children?.map((route) => route.path);
    expect(childPaths).toEqual(expect.arrayContaining(["tasks", "tasks/new", "tasks/:taskId"]));
  });
});
