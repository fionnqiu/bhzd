/**
 * 学生端页面测试（F2：预设/图谱/任务/任务详情/诊断/问答/个人中心）。
 *
 * 打桩策略（为什么）：
 * - api 层整体打桩（与 F0 测试同一约定）：页面逻辑只依赖 DTO 形状，
 *   后端真实行为由 pytest 覆盖，前端测试聚焦交互闭环。
 * - vis-network 整体打桩：jsdom 无 canvas/布局引擎，真实 Network 初始化
 *   必炸；mock 后捕获事件回调，用人工派发验证"点节点 → 开抽屉"逻辑。
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ToastProvider } from "../src/components";
import { ApiRequestError, api } from "../src/api/client";
import PresetsPage from "../src/pages/student/PresetsPage";
import GraphPage from "../src/pages/student/GraphPage";
import TasksPage from "../src/pages/student/TasksPage";
import TaskDetailPage from "../src/pages/student/TaskDetailPage";
import DiagnosticsPage from "../src/pages/student/DiagnosticsPage";
import RagQaPage from "../src/pages/student/RagQaPage";
import ProfilePage from "../src/pages/student/ProfilePage";

/* ---------------------------------------------------------------- 打桩 */

const visHandlers = vi.hoisted(() => ({
  handlers: {} as Record<string, (params?: unknown) => void>,
}));

vi.mock("vis-network/standalone", () => ({
  Network: vi.fn().mockImplementation(() => ({
    on: (event: string, cb: (params?: unknown) => void) => {
      visHandlers.handlers[event] = cb;
    },
    once: (event: string, cb: (params?: unknown) => void) => {
      visHandlers.handlers[event] = cb;
    },
    setOptions: vi.fn(),
    setData: vi.fn(),
    stabilize: vi.fn(),
    destroy: vi.fn(),
  })),
}));

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

// ProfilePage 改名后需要读取会话与刷新会话；其余学生页不消费 AuthContext。
vi.mock("../src/auth/AuthContext", () => ({
  useAuth: () => ({
    user: {
      id: "u1",
      email: "student@demo.bhzd",
      name: "演示同学",
      role: "student",
      email_verified: true,
    },
    bootstrapping: false,
    logout: vi.fn(),
    refreshSession: vi.fn(),
  }),
}));

const mockedGet = vi.mocked(api.get);
const mockedPost = vi.mocked(api.post);
const mockedDelete = vi.mocked(api.delete);
const mockedPostForm = vi.mocked(api.postForm);

/** 与生产 Provider 组合一致（Toast）；附带跳转目标标记路由 */
function renderPage(ui: ReactElement, route: string, path: string) {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={ui} />
          <Route path="/tasks" element={<div>任务列表页标记</div>} />
          <Route path="/tasks/:id" element={<div>任务详情页标记</div>} />
          <Route path="/presets" element={<div>预设页标记</div>} />
          <Route path="/graph" element={<div>图谱页标记</div>} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

/** 各用例统一的默认桩：图谱总览空图（useCapNames 依赖）；其余路径 404 */
function installDefaultGet() {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/api/graph/overview") return Promise.resolve({ nodes: [], edges: [] });
    return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  visHandlers.handlers = {};
  installDefaultGet();
  mockedPost.mockRejectedValue(new ApiRequestError(500, "NOT_MOCKED", "未 mock 的 POST"));
  mockedDelete.mockResolvedValue({});
  mockedPostForm.mockRejectedValue(new ApiRequestError(500, "NOT_MOCKED", "未 mock 的 POST form"));
});

/* ---------------------------------------------------------------- 预设学习 */

describe("PresetsPage", () => {
  const presetListItem = {
    id: "p1",
    title: "数据标注零基础入门",
    description: "从零认识数据标注",
    data_type: "general",
    goal: "掌握数据标注全流程",
    difficulty: 1,
    est_minutes: 90,
    cap_ids: ["C1", "C2"],
    unit_ids: ["TU-1"],
    recommended_for: "零基础新生",
    caps: [
      { cap_id: "C1", cap_name: "能力一", mastery_status: "weak", score: 0.3 },
      { cap_id: "C2", cap_name: "能力二", mastery_status: "mastered", score: 0.9 },
    ],
    units: [{ unit_id: "TU-1", title: "标注词汇入门" }],
    mastered_collapsed: false,
    weak_count: 1,
  };

  function installPresetsGet() {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/presets") return Promise.resolve({ items: [presetListItem], total: 1 });
      if (path === "/api/presets/p1") return Promise.resolve(presetListItem);
      if (path === "/api/graph/overview")
        return Promise.resolve({ nodes: [{ id: "C1", label: "能力一", type: "CAP" }], edges: [] });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
  }

  it("筛选变更携带查询参数重新拉取", async () => {
    installPresetsGet();
    renderPage(<PresetsPage />, "/presets", "/presets");

    expect(await screen.findByText("数据标注零基础入门")).toBeInTheDocument();
    // 薄弱 1 项 → 归入当前推荐分组
    expect(screen.getByText("薄弱能力推荐")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("combobox", { name: "数据类型筛选" }));
    fireEvent.click(screen.getByRole("option", { name: "语音" }));
    await waitFor(() => {
      expect(mockedGet).toHaveBeenCalledWith(
        "/api/presets",
        expect.objectContaining({ data_type: "audio" }),
        expect.objectContaining({ signal: expect.anything() }),
      );
    });
  });

  it("≤3 次点击完成开始任务：卡片 → 开始学习 → 确认创建", async () => {
    installPresetsGet();
    mockedPost.mockImplementation((path: string) => {
      if (path === "/api/presets/p1/start")
        return Promise.resolve({
          confirmation: {
            id: "c1",
            action_type: "task.create",
            status: "pending",
            expires_at: "2099-01-01T00:00:00Z",
            run_id: "r1",
          },
          preview: {
            title: "数据标注零基础入门·第1课：标注词汇入门",
            goal: "掌握数据标注全流程",
            data_type: null,
            cap_ids: ["C1"],
            steps: [{ title: "认识标注术语", description: "" }],
            resources: [],
            source: "preset",
            preset_id: "p1",
            counts_toward_mastery: 1,
          },
        });
      if (path === "/api/confirmations/c1/confirm")
        return Promise.resolve({ status: "confirmed", result: { task_id: "t1" } });
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 POST ${path}`));
    });
    renderPage(<PresetsPage />, "/presets", "/presets");

    // 点击1：打开路径抽屉；已掌握能力默认折叠（PRD-01 §4.4）
    fireEvent.click(await screen.findByText("数据标注零基础入门"));
    expect(await screen.findByText("能力一")).toBeInTheDocument();
    expect(screen.queryByText("能力二")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /已掌握 1 项/ }));
    expect(screen.getByText("能力二")).toBeInTheDocument();

    // 点击2：生成任务 → 确认门预览任务卡
    fireEvent.click(screen.getByRole("button", { name: "生成任务" }));
    expect(await screen.findByText("确认创建学习任务")).toBeInTheDocument();
    expect(screen.getByText("数据标注零基础入门·第1课：标注词汇入门")).toBeInTheDocument();

    // 点击3：确认创建 → 跳转任务列表
    fireEvent.click(screen.getByRole("button", { name: "确认创建" }));
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/confirmations/c1/confirm");
    });
    expect(await screen.findByText("任务列表页标记")).toBeInTheDocument();
  });

  it("筛选无结果展示空态与重置入口", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/presets") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/graph/overview") return Promise.resolve({ nodes: [], edges: [] });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
    renderPage(<PresetsPage />, "/presets", "/presets");
    expect(await screen.findByText("没有符合条件的学习推荐")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "清除筛选" })).toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 任务列表 */

describe("TasksPage", () => {
  const teacherTask = {
    id: "t1",
    title: "客服情感标注练习",
    goal: "完成一轮情感标注",
    data_type: "audio",
    cap_ids: ["CAP-1"],
    source: "teacher",
    status: "in_progress",
    progress: 0.5,
    latest_score: 0.8,
    counts_toward_mastery: true,
    due_at: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-02T00:00:00Z",
  };

  it("空列表展示引导空态（PRD-06 §7.2）", async () => {
    installDefaultGet();
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/tasks") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/graph/overview") return Promise.resolve({ nodes: [], edges: [] });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
    renderPage(<TasksPage />, "/tasks", "/tasks");

    expect(await screen.findByText("还没有学习任务")).toBeInTheDocument();
    expect(screen.getByText("去预设学习")).toBeInTheDocument();
    expect(screen.getByText("开始对话")).toBeInTheDocument();
    expect(screen.getByText("上传标注诊断")).toBeInTheDocument();
  });

  it("渲染任务卡（教师徽标/打开任务）并归档需二次确认", async () => {
    let items: unknown[] = [teacherTask];
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/tasks") return Promise.resolve({ items, total: items.length });
      if (path === "/api/graph/overview")
        return Promise.resolve({
          nodes: [{ id: "CAP-1", label: "标注情感与副语言", type: "CAP" }],
          edges: [],
        });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
    mockedPost.mockImplementation((path: string) => {
      if (path === "/api/tasks/t1/archive") {
        items = [];
        return Promise.resolve({ ...teacherTask, status: "archived" });
      }
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 POST ${path}`));
    });
    renderPage(<TasksPage />, "/tasks", "/tasks");

    expect(await screen.findByText("客服情感标注练习")).toBeInTheDocument();
    expect(screen.getByText("教师")).toBeInTheDocument();
    // Capability labels are no longer part of the compact task-card surface.
    expect(screen.queryByText("标注情感与副语言")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "打开任务" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "归档" }));
    expect(await screen.findByText("归档任务")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认归档" }));
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/tasks/t1/archive");
    });
    // 归档后列表刷新为空态
    expect(await screen.findByText("还没有学习任务")).toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 任务详情 */

describe("TaskDetailPage", () => {
  const taskDetail = {
    id: "t1",
    title: "NER 边界练习",
    goal: "掌握实体边界划分",
    data_type: "text",
    cap_ids: ["CAP-1"],
    source: "preset",
    status: "in_progress",
    progress: 0.5,
    latest_score: null,
    counts_toward_mastery: true,
    due_at: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-02T00:00:00Z",
    steps: [
      { title: "阅读规范", description: "先读 BIO 规范", notes: "注意边界", common_errors: "越界" },
    ],
    resources: [{ type: "teaching_unit", title: "NER 边界单元", ref_id: "TU-1" }],
    rubric: [{ key: "q1", expected: "正确", weight: 1, hint: "再想想" }],
    practice: {
      questions: [{ key: "q1", prompt: "边界是否正确？", hint: "按 BIO" }],
      checklist: ["检查边界一致性"],
    },
    caps: [{ cap_id: "CAP-1", cap_name: "实体边界划分" }],
    linked: { certificates: [], knowledge: [], graph_resources: [] },
    teacher_id: null,
    class_id: null,
    version: 1,
    parent_task_id: null,
    attempts: [],
    latest_attempt: null,
  };

  it("提交 → 反馈 → 确认更新掌握度 闭环", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/tasks/t1") return Promise.resolve(taskDetail);
      if (path === "/api/profile/mastery") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/graph/overview") return Promise.resolve({ nodes: [], edges: [] });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
    mockedPost.mockImplementation((path: string, body?: unknown) => {
      if (path === "/api/tasks/t1/submit") {
        expect(body).toEqual({ answers: { q1: "正确" } });
        return Promise.resolve({
          attempt_id: "a1",
          score: 1,
          feedback: [{ key: "q1", expected: "正确", got: "正确", ok: true, hint: "回答正确" }],
          mastery_preview: [{ cap_id: "CAP-1", delta: 0.15, old_score: 0.5, new_score: 0.65 }],
          status: "submitted",
        });
      }
      if (path === "/api/tasks/t1/apply-mastery")
        return Promise.resolve({
          applied: [{ cap_id: "CAP-1", delta: 0.15, old_score: 0.5, new_score: 0.65 }],
          already_applied: false,
          status: "completed",
        });
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 POST ${path}`));
    });
    renderPage(<TaskDetailPage />, "/tasks/t1", "/tasks/:id");

    // 学习任务只展示名称、描述、学习内容和练习；评分答案不得提前泄露。
    expect(await screen.findByText("NER 边界练习")).toBeInTheDocument();
    expect(screen.getByText("掌握实体边界划分")).toBeInTheDocument();
    expect(screen.queryByText("常见错误：越界")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "操作步骤" })).not.toBeInTheDocument();
    expect(screen.getByText("检查边界一致性")).toBeInTheDocument();

    // 作答并提交
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "正确" } });
    fireEvent.click(screen.getByRole("button", { name: "完成并提交任务" }));
    expect(await screen.findByText("本次得分")).toBeInTheDocument();
    expect(screen.getAllByText("100 分")).not.toHaveLength(0);
    // 掌握度变化预览先于确认（PRD-06 §6.4 门口径）
    expect(screen.getByText(/50% → 65%/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "确认更新掌握度" }));
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/tasks/t1/apply-mastery", {
        attempt_id: "a1",
      });
    });
    expect(await screen.findByRole("button", { name: "掌握度已更新" })).toBeDisabled();
  });

  it("旧对象型 rubric 不会让任务详情白屏", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/tasks/t1") {
        // Older backends can still return this pre-DTO shape during a rolling upgrade.
        return Promise.resolve({
          ...taskDetail,
          rubric: { rules: [{ key: "q1" }] },
          practice: null,
        });
      }
      if (path === "/api/profile/mastery") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/graph/overview") return Promise.resolve({ nodes: [], edges: [] });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
    renderPage(<TaskDetailPage />, "/tasks/t1", "/tasks/:id");

    expect(await screen.findByText("NER 边界练习")).toBeInTheDocument();
    expect(
      screen.getByText("该任务没有预设练习题，完成学习后可直接提交，系统将按完成情况评分。"),
    ).toBeInTheDocument();
  });

  it("返回任务详情时保留来源页的筛选路径", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/tasks/t1") return Promise.resolve(taskDetail);
      if (path === "/api/profile/mastery") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/graph/overview") return Promise.resolve({ nodes: [], edges: [] });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
    render(
      <ToastProvider>
        <MemoryRouter
          initialEntries={[
            { pathname: "/tasks/t1", state: { returnTo: "/tasks?status=completed" } },
          ]}
        >
          <Routes>
            <Route path="/tasks/:id" element={<TaskDetailPage />} />
            <Route path="/tasks" element={<div>任务列表页标记</div>} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>,
    );

    const returnLinks = await screen.findAllByRole("link", { name: "返回任务列表" });
    // The first link is in the page header, so learners can leave a long task before reaching its footer.
    expect(returnLinks[0]).toHaveAttribute("href", "/tasks?status=completed");
    // The task page has one header exit; the former footer recommendation link
    // was intentionally removed from the simplified task surface.
    expect(returnLinks).toHaveLength(1);
  });

  it("刷新后恢复最近提交、教师来源并隐藏历史任务资源", async () => {
    const restoredTask = {
      ...taskDetail,
      source: "teacher",
      teacher_id: "teacher-private-id",
      class_id: "class-private-id",
      status: "submitted",
      progress: 0.9,
      latest_score: 0.8,
      resources: [
        { type: "teaching_unit", title: "NER 边界单元", ref_id: "TU-1" },
        {
          type: "rag_citation",
          title: "BIO 标注规范",
          ref_id: "DOC-1",
          citation: {
            document_id: "DOC-1",
            title: "BIO 标注规范",
            section_title: "实体边界",
            page_start: 3,
            page_end: 4,
            version: "1.2",
            score: 0.95,
          },
        },
      ],
      linked: {
        certificates: [],
        knowledge: [],
        graph_resources: [{ id: "GR-1", name: "实体边界图谱参考" }],
      },
      attempts: [
        {
          id: "a-restored",
          attempt_number: 2,
          score: 0.8,
          mastery_applied: false,
          created_at: "2026-07-03T00:00:00Z",
        },
      ],
      latest_attempt: {
        id: "a-restored",
        attempt_number: 2,
        score: 0.8,
        mastery_applied: false,
        created_at: "2026-07-03T00:00:00Z",
        answers: { q1: "BIO" },
        feedback: [{ key: "q1", expected: "BIO", got: "BIO", ok: true, hint: "回答正确" }],
        mastery_preview: [{ cap_id: "CAP-1", delta: 0.1, old_score: 0.6, new_score: 0.7 }],
      },
    };
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/tasks/t1") return Promise.resolve(restoredTask);
      if (path === "/api/profile/mastery") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/graph/overview") return Promise.resolve({ nodes: [], edges: [] });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
    mockedPost.mockImplementation((path: string, body?: unknown) => {
      if (path === "/api/tasks/t1/apply-mastery") {
        expect(body).toEqual({ attempt_id: "a-restored" });
        return Promise.resolve({
          applied: [{ cap_id: "CAP-1", delta: 0.1, old_score: 0.6, new_score: 0.7 }],
          already_applied: false,
          status: "completed",
        });
      }
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 POST ${path}`));
    });
    renderPage(<TaskDetailPage />, "/tasks/t1", "/tasks/:id");

    const answer = await screen.findByRole("textbox", { name: "边界是否正确？" });
    expect(answer).toHaveValue("BIO");
    expect(answer).toHaveAccessibleDescription("按 BIO");
    // Historical resources remain in the DTO for compatibility, but the task
    // page no longer treats them as an assigned learning-material surface.
    expect(screen.queryByRole("heading", { name: "学习材料", level: 2 })).not.toBeInTheDocument();
    expect(screen.getByText("教师发布")).toBeInTheDocument();
    expect(screen.getByText("教师任务")).toBeInTheDocument();
    expect(screen.queryByText("teacher-private-id")).not.toBeInTheDocument();
    expect(screen.queryByText("class-private-id")).not.toBeInTheDocument();
    expect(screen.queryByText("图谱参考资源")).not.toBeInTheDocument();
    expect(screen.queryByText("实体边界图谱参考")).not.toBeInTheDocument();
    expect(screen.queryByText("教学单元")).not.toBeInTheDocument();
    expect(screen.queryByText(/BIO 标注规范/)).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "下一步推荐" })).not.toBeInTheDocument();
    expect(
      screen.getByText("本次作答已提交。你可以核对反馈后确认完成，也可以修改答案后再次提交。"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "确认更新掌握度" }));
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/tasks/t1/apply-mastery", {
        attempt_id: "a-restored",
      });
    });
    expect(
      await screen.findByText("任务已完成，已保留最近一次作答与反馈供回顾。"),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("progressbar")[0]).toHaveAttribute("aria-valuenow", "100");
  });

  it("开始任务后同步状态和学习进度", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/tasks/t1") {
        return Promise.resolve({ ...taskDetail, status: "not_started", progress: 0 });
      }
      if (path === "/api/profile/mastery") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/graph/overview") return Promise.resolve({ nodes: [], edges: [] });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
    mockedPost.mockImplementation((path: string) => {
      if (path === "/api/tasks/t1/start")
        return Promise.resolve({ status: "in_progress", progress: 0.5 });
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 POST ${path}`));
    });
    renderPage(<TaskDetailPage />, "/tasks/t1", "/tasks/:id");

    fireEvent.click(await screen.findByRole("button", { name: "开始任务" }));
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/tasks/t1/start");
    });
    expect(screen.getByText("进行中")).toBeInTheDocument();
    expect(screen.getAllByRole("progressbar")[0]).toHaveAttribute("aria-valuenow", "50");
    expect(screen.getByRole("button", { name: "完成并提交任务" })).toBeEnabled();
  });

  it("历史任务的 none 状态展示自动排队提示，不提供手动生成按钮", async () => {
    const legacyTask = {
      ...taskDetail,
      content_status: "none",
      knowledge_points: [],
      exercises: [],
    };
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/tasks/t1") return Promise.resolve(legacyTask);
      if (path === "/api/profile/mastery") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/graph/overview") return Promise.resolve({ nodes: [], edges: [] });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });

    // The server queues historical rows on first detail read; the UI must not
    // reintroduce a second, student-triggered generation workflow.
    renderPage(<TaskDetailPage />, "/tasks/t1", "/tasks/:id");

    expect(await screen.findByText("学习内容已自动排队，正在准备中，请稍候…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "开始生成学习内容" })).not.toBeInTheDocument();
  });

  it("学习内容保留知识点，AI 练习迁移到练习区并呈现评阅状态", async () => {
    const readyTask = {
      ...taskDetail,
      content_status: "done",
      knowledge_points: [
        {
          id: "k1",
          title: "BIO 边界规则",
          content: "实体边界必须保持连续。",
          sort_order: 1,
          created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:00:00Z",
        },
      ],
      exercises: [
        {
          id: "e1",
          question: "标注一个连续实体。",
          type: "open_ended",
          options: null,
          sort_order: 1,
          created_at: "2026-08-01T00:00:00Z",
          submission: {
            id: "s1",
            answer: "北京",
            grade_status: "done",
            score: 88,
            feedback: "边界正确",
            graded_at: "2026-08-01T00:02:00Z",
            created_at: "2026-08-01T00:01:00Z",
          },
        },
        {
          id: "e2",
          question: "说明一个常见边界错误。",
          type: "open_ended",
          options: ["越界", "漏标"],
          sort_order: 2,
          created_at: "2026-08-01T00:00:00Z",
          submission: {
            id: "s2",
            answer: "",
            grade_status: "failed",
            score: null,
            feedback: null,
            graded_at: null,
            created_at: "2026-08-01T00:01:00Z",
          },
        },
      ],
      content_generated_at: "2026-08-01T00:00:00Z",
    };
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/tasks/t1") return Promise.resolve(readyTask);
      if (path === "/api/profile/mastery") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/graph/overview") return Promise.resolve({ nodes: [], edges: [] });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
    renderPage(<TaskDetailPage />, "/tasks/t1", "/tasks/:id");

    expect(await screen.findByText(/BIO 边界规则/)).toBeInTheDocument();
    expect(screen.getByText("实体边界必须保持连续。")).toBeInTheDocument();
    expect(screen.queryByRole("tablist", { name: "学习内容类型" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "练习" })).not.toBeInTheDocument();

    const practiceHeading = screen.getByRole("heading", { name: "练习区" });
    const practiceCard = practiceHeading.closest(".card");
    expect(practiceCard).not.toBeNull();
    expect(within(practiceCard as HTMLElement).getByRole("heading", { name: "练习" })).toBeInTheDocument();
    expect(within(practiceCard as HTMLElement).getByText(/标注一个连续实体/)).toBeInTheDocument();
    expect(within(practiceCard as HTMLElement).getByText(/说明一个常见边界错误/)).toBeInTheDocument();
    await waitFor(() => {
      expect(
        within(practiceCard as HTMLElement).getByRole("textbox", { name: "AI 练习 1 答案" }),
      ).toHaveValue("北京");
    });
    expect(within(practiceCard as HTMLElement).getByText(/得分：88\/100/)).toBeInTheDocument();
    expect(
      within(practiceCard as HTMLElement).getByText("AI 评阅暂不可用，请稍后重试。"),
    ).toBeInTheDocument();
    expect(within(practiceCard as HTMLElement).queryByText("越界")).not.toBeInTheDocument();
  });

  it("纯结构化练习恢复整体提交答案，并提供重新完成任务的操作", async () => {
    const structuredTask = {
      ...taskDetail,
      status: "submitted",
      progress: 0.9,
      rubric: null,
      practice: null,
      content_status: "done",
      knowledge_points: [],
      exercises: [
        {
          id: "e-choice",
          question: "请选择正确的实体边界。",
          type: "multiple_choice",
          options: ["A", "B"],
          sort_order: 1,
          created_at: "2026-08-01T00:00:00Z",
          submission: null,
        },
        {
          id: "e-boolean",
          question: "判断该边界是否正确。",
          type: "true_false",
          options: null,
          sort_order: 2,
          created_at: "2026-08-01T00:00:00Z",
          submission: null,
        },
      ],
      latest_attempt: {
        id: "a-structured",
        attempt_number: 1,
        score: 1,
        mastery_applied: false,
        created_at: "2026-08-01T00:01:00Z",
        // Whole-task attempts do not generate task_exercise_submissions. The
        // detail page must still restore these choice controls after a reload.
        answers: { "e-choice": "B", "e-boolean": "错误" },
        feedback: [],
        mastery_preview: [],
      },
    };
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/tasks/t1") return Promise.resolve(structuredTask);
      if (path === "/api/graph/overview") return Promise.resolve({ nodes: [], edges: [] });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
    mockedPost.mockImplementation((path: string, body?: unknown) => {
      if (path === "/api/tasks/t1/submit") {
        expect(body).toEqual({ answers: { "e-choice": "B", "e-boolean": "错误" } });
        return Promise.resolve({
          attempt_id: "a-structured-next",
          score: 1,
          feedback: [],
          mastery_preview: [],
          status: "submitted",
        });
      }
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 POST ${path}`));
    });
    renderPage(<TaskDetailPage />, "/tasks/t1", "/tasks/:id");

    expect(await screen.findByRole("radio", { name: "B" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "错误" })).toBeChecked();
    const completion = screen.getByRole("button", { name: "重新提交任务" });
    expect(completion).toBeEnabled();
    fireEvent.click(completion);
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/tasks/t1/submit", {
        answers: { "e-choice": "B", "e-boolean": "错误" },
      });
    });
  });
});

/* ---------------------------------------------------------------- 标注诊断 */

describe("DiagnosticsPage", () => {
  const report = {
    file_format: "JSON",
    sample_count: 3,
    precheck: { fields: ["start", "end", "label"], warnings: ["样本数较少，结果仅供参考"] },
    errors: [
      {
        error_type: "空标注",
        severity: "major",
        user_value: null,
        expected: "标签非空",
        rule: "空标注检查",
        cap_id: "CAP-1",
        cap_name: "标签合法性校验",
        suggestion: "删除或补全空标注样本",
        citations: [
          {
            document_id: "d1",
            title: "NER 标注入门规范",
            section_title: "第 2 章",
            page_start: 3,
            page_end: 4,
            version: "1.0",
            score: 0.9,
          },
        ],
      },
    ],
    severity_counts: { major: 1, minor: 0 },
    weak_cap_ids: ["CAP-1"],
    mastery_preview: [{ cap_id: "CAP-1", delta: -0.2, old_score: 0.5, new_score: 0.3 }],
    plan: {
      weak_caps: [{ cap_id: "CAP-1", cap_name: "标签合法性校验" }],
      pre_path: ["CAP-1"],
      resources: [
        { type: "teaching_unit", unit_id: "TU-1", title: "标签校验单元", data_type: "text" },
      ],
      tasks: ["「标签合法性校验」专项纠错练习"],
    },
    notice: null,
    data_type: "text",
    diagnostic_token: "tok1",
  };

  it("上传 → 报告 → 保存（保存前展示掌握度预览）", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/diagnostics/summaries") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/graph/overview") return Promise.resolve({ nodes: [], edges: [] });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
    mockedPostForm.mockResolvedValue(report);
    mockedPost.mockImplementation((path: string) => {
      if (path === "/api/diagnostics/save-summary")
        return Promise.resolve({ summary_id: "s1", mastery_applied: report.mastery_preview });
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 POST ${path}`));
    });
    const { container } = renderPage(<DiagnosticsPage />, "/diagnostics", "/diagnostics");

    // 历史摘要空态（PRD-06 §7.2）
    expect(await screen.findByText("上传一次标注结果，获取第一次诊断")).toBeInTheDocument();

    // 选择文件并上传
    const file = new File([JSON.stringify([{ start: 0, end: 1, label: "" }])], "result.json", {
      type: "application/json",
    });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    expect(await screen.findByText(/result\.json/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "上传并诊断" }));
    await waitFor(() => {
      expect(mockedPostForm).toHaveBeenCalledWith("/api/diagnostics", expect.any(FormData));
    });

    // 预检 + 报告 + 补强计划渲染
    expect(await screen.findByText("解析预检")).toBeInTheDocument();
    expect(screen.getByText("空标注")).toBeInTheDocument();
    expect(screen.getByText("严重")).toBeInTheDocument();
    expect(screen.getByText(/NER 标注入门规范/)).toBeInTheDocument();
    expect(screen.getByText("补强计划")).toBeInTheDocument();

    // 保存前必须展示掌握度变化预览（PRD-01 §7 验收）
    fireEvent.click(screen.getByRole("button", { name: "保存诊断摘要" }));
    expect(await screen.findByText(/50% → 30%/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认保存" }));
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/diagnostics/save-summary", {
        diagnostic_token: "tok1",
      });
    });
  });

  it("上传失败展示后端中文错误（含格式提示）", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/diagnostics/summaries") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/graph/overview") return Promise.resolve({ nodes: [], edges: [] });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
    mockedPostForm.mockRejectedValue(
      new ApiRequestError(400, "PARSE_FAILED", "文件不是合法的 JSON，请检查导出格式"),
    );
    const { container } = renderPage(<DiagnosticsPage />, "/diagnostics", "/diagnostics");

    const file = new File(["not-json"], "bad.json", { type: "application/json" });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(await screen.findByRole("button", { name: "上传并诊断" }));
    expect(await screen.findByText("文件不是合法的 JSON，请检查导出格式")).toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- RAG 问答 */

describe("RagQaPage", () => {
  const citation = {
    document_id: "d1",
    title: "客服语音标注规范",
    section_title: "第 3 章",
    page_start: 5,
    page_end: 5,
    version: "2.3",
    score: 0.87,
  };

  function installRagGet() {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/graph/overview")
        return Promise.resolve({
          nodes: [{ id: "CAP-1", label: "标注情感与副语言", type: "CAP" }],
          edges: [],
        });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
  }

  it("拒答展示诚实提示卡，不编造答案", async () => {
    installRagGet();
    mockedPost.mockImplementation((path: string) => {
      if (path === "/api/rag/query")
        return Promise.resolve({
          answer: "知识库中未找到与该问题相关的已发布资料。",
          steps: [],
          notes: [],
          followups: [],
          citations: [],
          related_cap_ids: [],
          refused: true,
          notice: null,
        });
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 POST ${path}`));
    });
    renderPage(<RagQaPage />, "/rag-qa", "/rag-qa");

    // 空态示例问题（PRD-06 §7.2）
    expect(screen.getByText("NER 标注中实体边界应该如何划分？")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("问题输入"), { target: { value: "冷门问题" } });
    fireEvent.click(screen.getByRole("button", { name: "提问" }));
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/rag/query",
        expect.objectContaining({ question: "冷门问题", published_only: true }),
      );
    });
    expect(await screen.findByText("暂未找到可靠依据")).toBeInTheDocument();
    expect(screen.getByText("知识库暂无可靠依据，暂不能给出专业结论。")).toBeInTheDocument();
    expect(screen.getByText("去预设学习打基础")).toBeInTheDocument();
  });

  it("命中展示答案与引用；引用点击上报 citation_clicked；可一键加入任务", async () => {
    installRagGet();
    mockedPost.mockImplementation((path: string, body?: unknown) => {
      if (path === "/api/rag/query")
        return Promise.resolve({
          answer: "副语言事件需要单独记录。",
          steps: ["先听完整段录音", "再标注副语言事件"],
          notes: ["不要与情感标签混淆"],
          followups: ["情感标签有哪些？"],
          citations: [citation],
          related_cap_ids: ["CAP-1"],
          refused: false,
          notice: null,
        });
      if (path === "/api/events") return Promise.resolve({ accepted: 1 });
      if (path === "/api/tasks") {
        expect(body).toEqual(expect.objectContaining({ cap_ids: ["CAP-1"], source: "agent" }));
        return Promise.resolve({ id: "t9" });
      }
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 POST ${path}`));
    });
    renderPage(<RagQaPage />, "/rag-qa", "/rag-qa");

    fireEvent.change(screen.getByLabelText("问题输入"), {
      target: { value: "副语言事件如何记录？" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提问" }));

    expect(await screen.findByText("副语言事件需要单独记录。")).toBeInTheDocument();
    expect(screen.getByText(/先听完整段录音/)).toBeInTheDocument();
    expect(screen.getByText(/客服语音标注规范/)).toBeInTheDocument();
    // 关联能力 chip 经图谱名称解析展示中文名
    expect(await screen.findByText("标注情感与副语言")).toBeInTheDocument();

    // 引用点击 → 埋点 + 抽屉详情
    fireEvent.click(screen.getByText(/客服语音标注规范/));
    expect(await screen.findByText("引用详情")).toBeInTheDocument();
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/events", {
        events: [{ name: "citation_clicked", props: { document_id: "d1" } }],
      });
    });

    // 一键加入学习任务
    fireEvent.click(screen.getByRole("button", { name: "加入学习任务" }));
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/tasks",
        expect.objectContaining({ cap_ids: ["CAP-1"], source: "agent" }),
      );
    });
    expect(document.querySelector(".toast-container")).not.toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 个人中心 */

describe("ProfilePage", () => {
  it("学习任务记录保留、能力地图/诊断摘要/成长记录已移除；加入班级失败展示后端错误提示", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/profile")
        return Promise.resolve({
          user: { id: "u1", email: "student@demo.bhzd", name: "演示同学", role: "student" },
          task_counts: { in_progress: 1 },
          recent_diagnostic_summaries: [],
          growth: [],
          favorites: [],
          favorites_note: "收藏资料功能为 P1 规划项，当前版本暂未开放",
          classes: [{ id: "class-1", name: "个人中心测试班", joined_at: "2026-08-09T08:00:00Z" }],
        });
      if (path === "/api/tasks") return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
    mockedPost.mockRejectedValue(
      new ApiRequestError(404, "INVITE_CODE_INVALID", "邀请码无效，请向教师确认后再试"),
    );
    renderPage(<ProfilePage />, "/profile", "/profile");

    // 学习任务记录保留；能力地图/诊断摘要/成长记录按产品要求下线
    expect(await screen.findByText("学习任务记录")).toBeInTheDocument();
    expect(screen.queryByText("能力地图")).not.toBeInTheDocument();
    expect(screen.queryByText("诊断摘要")).not.toBeInTheDocument();
    expect(screen.queryByText("成长记录")).not.toBeInTheDocument();
    // 个人中心不再承载收藏入口，避免把资料收藏误认为学习主流程。
    expect(screen.queryByText("还没有收藏")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("班级邀请码"), { target: { value: "BAD-CODE" } });
    fireEvent.click(screen.getByRole("button", { name: "加入班级" }));
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/student/join-class", {
        invite_code: "BAD-CODE",
      });
    });
    expect(document.querySelector(".toast-container")).not.toBeInTheDocument();

    expect(screen.getByText("个人中心测试班")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "退出班级" }));
    expect(await screen.findByText(/确认退出「个人中心测试班」吗/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "退出班级" })[1]);
    await waitFor(() => {
      expect(mockedDelete).toHaveBeenCalledWith("/api/student/classes/class-1");
    });
    expect(screen.queryByText("个人中心测试班")).not.toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 能力图谱 */

describe("GraphPage", () => {
  it("总览加载渲染工具栏/画布；点击节点打开抽屉并可快速建任务", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/graph/overview")
        return Promise.resolve({
          nodes: [
            {
              id: "CAP-1",
              label: "标注情感与副语言",
              type: "CAP",
              description: "区分情感状态和副语言事件",
              data_types: ["audio"],
              mastery_status: "weak",
              mastery_score: 0.3,
            },
            { id: "KNG-1", label: "副语言知识", type: "KNG" },
          ],
          edges: [{ id: "e1", source: "KNG-1", target: "CAP-1", relation: "SUP" }],
        });
      if (path === "/api/graph/nodes/CAP-1")
        return Promise.resolve({
          id: "CAP-1",
          label: "标注情感与副语言",
          type: "CAP",
          description: "区分情感状态和副语言事件",
          data_types: ["audio"],
          prerequisites: [],
          knowledge: [{ id: "KNG-1", label: "副语言知识", type: "KNG" }],
          resources: [],
          tasks: [],
          certificates: [],
          // Preserve the raw graph relationship field while the UI keeps it hidden.
          scenarios: [],
          related: [],
          learning_materials: [
            {
              type: "teaching_unit",
              ref_id: "TU-AUDIO-EMOTION-PARALINGUISTICS-001",
              title: "分轨标注语音情感与副语言事件",
            },
          ],
          mastery: [
            {
              score: 0.3,
              source: "exercise",
              updated_at: "2026-07-01T00:00:00Z",
              mastery_status: "weak",
            },
          ],
        });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
    mockedPost.mockImplementation((path: string, body?: unknown) => {
      if (path === "/api/tasks/start-learning") {
        // P0-8 starts a task through the dedicated endpoint so content
        // generation can run asynchronously without blocking navigation.
        expect(body).toEqual({ cap_node_id: "CAP-1", generate_content: true });
        return Promise.resolve({ task_id: "t5" });
      }
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 POST ${path}`));
    });
    renderPage(<GraphPage />, "/graph", "/graph");

    // 工具栏/画布/图例渲染
    expect(await screen.findByLabelText("能力图谱画布")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("搜索能力 / 知识 / 任务")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "全图" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "路径" })).toBeInTheDocument();
    // The scrollbar override is scoped to this graph filter group and must not
    // require changing the shared Tabs component used by other portals.
    expect(screen.getByRole("tablist").closest(".graph-view-mode-tabs")).not.toBeNull();
    expect(screen.getByText("已掌握")).toBeInTheDocument();

    // 模拟画布点击节点（真实环境中由 vis-network 派发）
    await act(async () => {
      visHandlers.handlers["click"]?.({ nodes: ["CAP-1"] });
    });
    expect(await screen.findByText("节点说明")).toBeInTheDocument();
    expect(screen.getByText("我的掌握度")).toBeInTheDocument();
    // 学生图谱只展示能力节点与前置关系，不再暴露知识节点。
    expect(screen.queryByText("副语言知识")).not.toBeInTheDocument();

    // 生成练习 → 快速建任务 → 跳详情
    fireEvent.click(screen.getByRole("button", { name: "生成练习" }));
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/tasks/start-learning", {
        cap_node_id: "CAP-1",
        generate_content: true,
      });
    });
    expect(await screen.findByText("任务详情页标记")).toBeInTheDocument();
  });
});
