/**
 * 教师端测试（一）：工作台 + 班级管理 + 班级详情。
 *
 * 覆盖 PRD-02 验收点：
 * - §3.2 工作台渲染统计卡与薄弱能力 Top5（真实字段口径）；
 * - §4.2 新建班级后邀请码醒目展示（创建响应即时回显）；
 * - §4.2 添加学生失败时后端中文错误原样 toast；导出报表触发客户端 CSV 下载
 *   （PRD-06 §10.2：列只含聚合学情，不含诊断原文件）。
 *
 * api 层整体打桩（与 tests/auth-pages.test.tsx 同一模式），页面断言只依赖
 * 组件树的可见行为，不探测实现细节。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ReactElement } from "react";
import { ToastProvider } from "../src/components";
import DashboardPage from "../src/pages/teacher/DashboardPage";
import ClassesPage from "../src/pages/teacher/ClassesPage";
import ClassDetailPage from "../src/pages/teacher/ClassDetailPage";
import { ApiRequestError, api } from "../src/api/client";

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

/** 页面统一依赖 ToastProvider（useToast）与 Router（Link/useNavigate/useParams） */
function renderPage(ui: ReactElement, route: string, path = "*") {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={ui} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

/* ---------------------------------------------------------------- 工作台 */

describe("DashboardPage（PRD-02 §3）", () => {
  beforeEach(() => {
    mockedGet.mockImplementation((path) => {
      if (path === "/api/teacher/dashboard") {
        return Promise.resolve({
          classes: [
            {
              id: "c1",
              name: "数据标注2301班",
              student_count: 1,
              task_completion_rate: 0.5,
              avg_mastery: 0.7,
            },
            {
              id: "c2",
              name: "数据标注2302班",
              student_count: 2,
              task_completion_rate: null,
              avg_mastery: null,
            },
          ],
          weak_caps_top5: [
            { cap_id: "CAP-1", cap_name: "语音切分", avg_score: 0.35, student_count: 2 },
          ],
          todos: { unpublished_teacher_tasks: 2 },
        });
      }
      if (path === "/api/teacher/tasks") {
        return Promise.resolve({
          items: [
            {
              id: "t1",
              title: "客服语音情感标注",
              goal: null,
              data_type: "audio",
              scenario_id: null,
              cap_ids: ["CAP-1"],
              steps: [],
              resources: [],
              rubric: null,
              practice: null,
              status: "draft",
              version: 1,
              parent_task_id: null,
              published_count: 0,
              created_at: "2026-07-30T00:00:00Z",
              updated_at: "2026-07-30T08:00:00Z",
            },
          ],
          total: 1,
        });
      }
      return Promise.reject(new Error(`未 mock 的 GET ${String(path)}`));
    });
  });

  it("渲染统计卡、薄弱 Top5、待办与快捷入口", async () => {
    renderPage(<DashboardPage />, "/teacher");

    // 统计卡（班级数 2 / 学生总数 3 来自两个班级的聚合）
    expect(await screen.findByText("班级数")).toBeInTheDocument();
    expect(document.querySelector(".teacher-dashboard-page")).toBeInTheDocument();
    expect(document.querySelector(".teacher-dashboard-stats")).toBeInTheDocument();
    expect(document.querySelector(".teacher-two-column")).toBeInTheDocument();
    expect(screen.getByText("学生总数")).toBeInTheDocument();
    expect(screen.getByText("任务完成率")).toBeInTheDocument();
    expect(screen.getByText("平均掌握度")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument(); // 学生总数 1+2

    // 高频薄弱能力 Top5：cap 名称 + 平均分与薄弱人数
    expect(screen.getByText("高频薄弱能力 Top 5")).toBeInTheDocument();
    expect(screen.getByText("语音切分")).toBeInTheDocument();
    expect(screen.getByText("平均 35% · 2 人薄弱")).toBeInTheDocument();

    // 教师待办只保留教学任务；RAG 审核在系统管理端处理。
    expect(screen.getByText("待发布任务（草稿）")).toBeInTheDocument();

    // 最近任务 + 教学快捷入口
    expect(screen.getByText("客服语音情感标注")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /新建教学任务/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /查看学情/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /上传资料/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /召回测试/ })).not.toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 班级列表 */

describe("ClassesPage（PRD-02 §4）", () => {
  it("新建班级后展示邀请码与分享提示", async () => {
    mockedGet.mockResolvedValue({ items: [], total: 0 });
    mockedPost.mockResolvedValue({ id: "c9", name: "数据标注2303班", invite_code: "INV-ABC123" });

    renderPage(<ClassesPage />, "/teacher/classes");

    expect(document.querySelector(".teacher-classes-page")).toBeInTheDocument();
    expect(
      document.querySelector(".teacher-table-surface .table-wrap-borderless"),
    ).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: "新建班级" }));
    fireEvent.change(screen.getByPlaceholderText("例如：数据标注2301班"), {
      target: { value: "数据标注2303班" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建" }));

    // 创建请求携带班级名
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/teacher/classes", {
        name: "数据标注2303班",
      }),
    );
    // 邀请码醒目展示 + 复制按钮 + 分享提示
    expect(await screen.findByText("INV-ABC123")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "复制邀请码" })).toBeInTheDocument();
    expect(screen.getByText(/分享给学生加入/)).toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 班级详情 */

describe("ClassDetailPage（PRD-02 §4）", () => {
  const student = {
    id: "s1",
    name: "张三",
    email: "zhangsan@demo.bhzd",
    task_count: 2,
    completion_rate: 0.5,
    avg_mastery: 0.6,
    last_active: "2026-07-30T10:00:00Z",
    joined_at: "2026-06-01T00:00:00Z",
    left_at: null,
  };

  beforeEach(() => {
    mockedGet.mockImplementation((path) => {
      if (path === "/api/teacher/classes/c1") {
        return Promise.resolve({
          id: "c1",
          name: "数据标注2301班",
          invite_code: "CODE-123",
          student_count: 1,
          avg_mastery: 0.6,
          recent_tasks: [],
          created_at: "2026-01-01T00:00:00Z",
        });
      }
      if (path === "/api/teacher/classes/c1/students") {
        return Promise.resolve({ items: [student], total: 1 });
      }
      return Promise.reject(new Error(`未 mock 的 GET ${String(path)}`));
    });
  });

  it("添加学生失败时 toast 展示后端中文错误", async () => {
    mockedPost.mockRejectedValue(
      new ApiRequestError(404, "STUDENT_NOT_FOUND", "未找到该学生账号，请确认学生已注册"),
    );

    renderPage(<ClassDetailPage />, "/teacher/classes/c1", "/teacher/classes/:id");

    // 等待学生行渲染后再操作（确保初始加载完成）
    expect(await screen.findByText("张三")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/学生注册邮箱/), {
      target: { value: "ghost@demo.bhzd" },
    });
    fireEvent.click(screen.getByRole("button", { name: "添加" }));

    expect(await screen.findByText("未找到该学生账号，请确认学生已注册")).toBeInTheDocument();
    expect(mockedPost).toHaveBeenCalledWith("/api/teacher/classes/c1/enroll", {
      student_email: "ghost@demo.bhzd",
    });
  });

  it("导出报表触发客户端 CSV 下载（仅聚合列）", async () => {
    // jsdom 没有 createObjectURL：打桩验证 Blob 下载链路
    const createObjectURL = vi.fn((_blob: Blob) => "blob:mock-url");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    renderPage(<ClassDetailPage />, "/teacher/classes/c1", "/teacher/classes/:id");
    expect(await screen.findByText("张三")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "导出报表" }));

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blob = createObjectURL.mock.calls[0][0];
    expect(blob).toBeInstanceOf(Blob);
    // jsdom 的 Blob 没有 .text()：走 FileReader 读取内容
    const text = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = () => reject(reader.error);
      reader.readAsText(blob);
    });
    // readAsText 会吞掉 BOM：改读原始字节验证 UTF-8 BOM（EF BB BF）真实存在
    const bytes = new Uint8Array(
      await new Promise<ArrayBuffer>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as ArrayBuffer);
        reader.onerror = () => reject(reader.error);
        reader.readAsArrayBuffer(blob);
      }),
    );
    expect([bytes[0], bytes[1], bytes[2]]).toEqual([0xef, 0xbb, 0xbf]);
    // CSV 内容：中文表头 + 学生行（不含诊断原文等额外字段）
    expect(text).toContain("姓名,邮箱,任务数,完成率,平均掌握度,最近活跃");
    expect(text).toContain("张三");
    expect(text).toContain("zhangsan@demo.bhzd");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
    clickSpy.mockRestore();
  });
});
