/**
 * 学生端增强测试（B1：入学引导 / 通知铃铛 / 任务批量归档 / 引用收藏 / 个人中心增强）。
 *
 * 打桩策略（与 student-pages.test.tsx 同一约定）：
 * - api 层整体打桩：页面逻辑只依赖 DTO 形状，后端真实行为由 pytest 覆盖。
 * - AuthContext 打桩：StudentLayout → ShellLayout 依赖 useAuth；
 *   本文件只关心学生端交互，不真实走会话引导。
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useEffect, type ReactElement, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ScenarioProvider } from "../src/app/ScenarioContext";
import { ToastProvider } from "../src/components";
import { ApiRequestError, api } from "../src/api/client";
import OnboardingPage from "../src/pages/student/OnboardingPage";
import StudentLayout from "../src/layouts/StudentLayout";
import { useStudentWorkbenchShell } from "../src/layouts/StudentWorkbenchShellContext";
import CockpitPage from "../src/pages/student/CockpitPage";
import TasksPage from "../src/pages/student/TasksPage";
import RagQaPage from "../src/pages/student/RagQaPage";
import ProfilePage from "../src/pages/student/ProfilePage";

/* ---------------------------------------------------------------- 打桩 */

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

// ShellLayout 只需要一个已登录学生；邮箱已验证使 EmailVerifyBanner 直接短路（不发请求）
vi.mock("../src/auth/AuthContext", () => ({
  useAuth: () => ({
    user: {
      id: "u1",
      email: "stu@example.com",
      name: "学生甲",
      role: "student",
      email_verified: true,
    },
    bootstrapping: false,
    logout: vi.fn(),
  }),
  AuthProvider: ({ children }: { children: ReactNode }) => children,
}));

const mockedGet = vi.mocked(api.get);
const mockedPost = vi.mocked(api.post);
const mockedPatch = vi.mocked(api.patch);
const mockedDelete = vi.mocked(api.delete);

/** 与生产 Provider 组合一致（Toast + 场景上下文）；initialEntry 为测试起始路由 */
function renderPage(routes: ReactElement, initialEntry: string) {
  return render(
    <ToastProvider>
      <ScenarioProvider>
        <MemoryRouter initialEntries={[initialEntry]}>
          <Routes>{routes}</Routes>
        </MemoryRouter>
      </ScenarioProvider>
    </ToastProvider>,
  );
}

/** 默认桩：能力名映射空图；其余 404 显式失败（未 mock 即测试缺口） */
function installDefaultGet() {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/api/graph/overview") return Promise.resolve({ nodes: [], edges: [] });
    return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  installDefaultGet();
  mockedPost.mockRejectedValue(new ApiRequestError(500, "NOT_MOCKED", "未 mock 的 POST"));
  mockedPatch.mockRejectedValue(new ApiRequestError(500, "NOT_MOCKED", "未 mock 的 PATCH"));
  mockedDelete.mockRejectedValue(new ApiRequestError(500, "NOT_MOCKED", "未 mock 的 DELETE"));
});

/* ---------------------------------------------------------------- 入学引导 */

const QUESTIONS = [
  {
    id: "q1",
    question: "BIO 标注中实体片段第一个字应标为？",
    options: ["I-类型", "B-类型", "O", "E-类型"],
    cap_id: "C1",
    data_type: "text",
  },
  {
    id: "q2",
    question: "IOU 指的是什么？",
    options: ["交并比", "面积占比", "中心距离", "长宽比"],
    cap_id: "C2",
    data_type: "image",
  },
];

function installOnboardingGet() {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/api/graph/overview")
      return Promise.resolve({
        nodes: [
          { id: "C1", label: "能力甲", type: "CAP" },
          { id: "C2", label: "能力乙", type: "CAP" },
        ],
        edges: [],
      });
    if (path === "/api/onboarding/assessment")
      return Promise.resolve({ status: "not_started", questions: QUESTIONS, total: 2 });
    return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
  });
}

function renderOnboarding() {
  return renderPage(
    <>
      <Route path="/onboarding" element={<OnboardingPage />} />
      <Route path="/" element={<div>指挥舱标记</div>} />
    </>,
    "/onboarding",
  );
}

describe("OnboardingPage 入学引导", () => {
  it("三步闭环：方向目标 → 答完全部题 → 提交 → 结果与初始能力地图", async () => {
    installOnboardingGet();
    mockedPost.mockImplementation((path: string) => {
      if (path === "/api/onboarding/assessment")
        return Promise.resolve({
          score: 1,
          correct: 2,
          total: 2,
          status: "completed",
          mastery_applied: [
            { cap_id: "C1", scenario_id: "", delta: 0.4, old_score: 0, new_score: 0.4 },
            { cap_id: "C2", scenario_id: "", delta: 0.4, old_score: 0, new_score: 0.4 },
          ],
        });
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 POST ${path}`));
    });
    renderOnboarding();

    // ① 方向与目标：专业下拉 + 目标 chip + 一句话
    expect(await screen.findByText("方向与目标")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("combobox", { name: "专业方向" }));
    fireEvent.click(screen.getByRole("option", { name: "人工智能技术应用" }));
    fireEvent.click(screen.getByRole("button", { name: "入门" }));
    fireEvent.change(screen.getByLabelText("目标一句话"), {
      target: { value: "三个月掌握文本标注" },
    });
    fireEvent.click(screen.getByRole("button", { name: "下一步：入学测评" }));

    // ② 测评：进度 0/2，未答完不可提交（题目前带序号前缀，用正则匹配）
    expect(await screen.findByText(new RegExp(QUESTIONS[0].question))).toBeInTheDocument();
    expect(screen.getByText("已答 0/2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /还有 2 题未作答/ })).toBeDisabled();

    const radios = screen.getAllByRole("radio");
    fireEvent.click(radios[0]); // q1 → 选项 0
    fireEvent.click(radios[5]); // q2 → 选项 1
    expect(screen.getByText("已答 2/2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "提交测评" }));

    // 提交体契约：answers:{qid:index} + goal + major
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/onboarding/assessment", {
        answers: { q1: 0, q2: 1 },
        goal: "入门：三个月掌握文本标注",
        major: "人工智能技术应用",
      });
    });

    // ③ 结果页：得分 + 初始能力地图（能力名由图谱解析）+ 进入指挥舱
    expect(await screen.findByText("初始能力地图")).toBeInTheDocument();
    expect(await screen.findByText("能力甲")).toBeInTheDocument();
    expect(screen.getByText("能力乙")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "进入指挥舱" }));
    expect(await screen.findByText("指挥舱标记")).toBeInTheDocument();
  });

  it("稍后再测：POST skip 后回首页", async () => {
    installOnboardingGet();
    mockedPost.mockImplementation((path: string) => {
      if (path === "/api/onboarding/skip")
        return Promise.resolve({ status: "skipped", message: "已跳过入学测评" });
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 POST ${path}`));
    });
    renderOnboarding();

    fireEvent.click(await screen.findByRole("button", { name: "稍后再测" }));
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/onboarding/skip");
    });
    expect(await screen.findByText("指挥舱标记")).toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 通知铃铛 */

const NOTIFICATIONS = [
  {
    id: "n1",
    type: "task_assigned",
    title: "教师发布了新任务",
    body: null,
    ref_type: "task",
    ref_id: "t9",
    read_at: null,
    created_at: "2026-07-31T09:00:00Z",
  },
  {
    id: "n2",
    type: "system",
    title: "系统维护通知",
    body: null,
    ref_type: null,
    ref_id: null,
    read_at: "2026-07-30T08:00:00Z",
    created_at: "2026-07-30T08:00:00Z",
  },
];

function installNotificationGet() {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/api/notifications/unread-count") return Promise.resolve({ unread: 2 });
    if (path === "/api/notifications") return Promise.resolve({ items: NOTIFICATIONS, total: 2 });
    return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
  });
}

function renderLayout() {
  return renderPage(
    <Route path="/" element={<StudentLayout />}>
      <Route index element={<div>指挥舱标记</div>} />
      <Route path="tasks/:id" element={<div>任务详情标记</div>} />
    </Route>,
    "/",
  );
}

/** Simulates the Cockpit-owned run lock while keeping the persistent shell mounted. */
function LockedStudentCockpit() {
  const { setSessionActionsDisabled } = useStudentWorkbenchShell();

  useEffect(() => {
    setSessionActionsDisabled(true);
    return () => setSessionActionsDisabled(false);
  }, [setSessionActionsDisabled]);

  return <div data-testid="locked-student-cockpit">locked student cockpit</div>;
}

function renderLockedLayout() {
  return renderPage(
    <Route path="/" element={<StudentLayout />}>
      <Route index element={<LockedStudentCockpit />} />
      <Route path="rag-qa" element={<div>help page</div>} />
      <Route path="tasks/:id" element={<div>task detail page</div>} />
    </Route>,
    "/",
  );
}

const STUDENT_SESSION = {
  id: "c9",
  title: "跨页面学习会话",
  scenario_id: "SCN-IN-VEHICLE-001",
  data_type: null,
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-02T00:00:00Z",
};

/** The persistent session rail is exercised with lightweight non-cockpit routes. */
function renderStudentSessionShell(initialEntry = "/profile") {
  return renderPage(
    <Route path="/" element={<StudentLayout />}>
      <Route index element={<CockpitPage />} />
      <Route path="profile" element={<div>个人中心页面</div>} />
      <Route path="tasks" element={<div>学习任务页面</div>} />
      <Route path="diagnostics" element={<div>标注诊断页面</div>} />
    </Route>,
    initialEntry,
  );
}

function installStudentSessionGet() {
  let sessionList = [STUDENT_SESSION];
  mockedGet.mockImplementation((path: string) => {
    if (path === "/api/conversations")
      return Promise.resolve({ items: sessionList, total: sessionList.length });
    if (path === "/api/conversations/c9")
      return Promise.resolve({
        ...STUDENT_SESSION,
        messages: [
          { id: "m1", run_id: "r0", role: "user", content: "打开跨页面会话", created_at: "" },
          { id: "m2", run_id: "r0", role: "assistant", content: "会话已恢复", created_at: "" },
        ],
      });
    if (path === "/api/onboarding/assessment") return Promise.resolve({ status: "completed" });
    if (path === "/api/profile/mastery") return Promise.resolve({ items: [], total: 0 });
    if (path === "/api/notifications/unread-count") return Promise.resolve({ unread: 0 });
    return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
  });
  mockedDelete.mockImplementation(async (path: string) => {
    if (path === "/api/conversations/c9") {
      sessionList = [];
      return { deleted: true };
    }
    throw new ApiRequestError(404, "NOT_FOUND", `未 mock 的 DELETE ${path}`);
  });
}

describe("学生工作台全局会话栏", () => {
  it("个人中心、任务和诊断页共享新建/打开/删除会话意图，且不创建空会话", async () => {
    installStudentSessionGet();
    renderStudentSessionShell();

    expect(await screen.findByText("跨页面学习会话")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新建会话" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("link", { name: "学习任务" }));
    expect(await screen.findByText("学习任务页面")).toBeInTheDocument();
    expect(screen.getByText("跨页面学习会话")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "新建会话" }));
    expect(await screen.findByTestId("cockpit-welcome")).toBeInTheDocument();
    expect(mockedPost.mock.calls.some(([path]) => path === "/api/conversations")).toBe(false);

    fireEvent.click(screen.getByText("跨页面学习会话"));
    expect(await screen.findByText("会话已恢复")).toBeInTheDocument();
    expect(mockedGet).toHaveBeenCalledWith("/api/conversations/c9");
    // A restored transcript must surface its saved title and continuation
    // context before the learner sends the next message.
    const conversationInfo = await screen.findByRole("status", { name: "当前对话信息" });
    expect(conversationInfo).toHaveTextContent("跨页面学习会话");
    expect(conversationInfo).not.toHaveTextContent("继续场景：");
    expect(
      within(screen.getByTestId("composer")).getByRole("combobox", { name: "继续场景" }),
    ).toHaveTextContent("车载语音标注");

    fireEvent.click(screen.getByRole("link", { name: "标注诊断" }));
    expect(await screen.findByText("标注诊断页面")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("删除会话 跨页面学习会话"));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "删除" }));
    await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith("/api/conversations/c9"));
    expect(mockedPost.mock.calls.some(([path]) => path === "/api/conversations")).toBe(false);
  });

  it("会话列表加载失败时保留可访问重试入口", async () => {
    let attempts = 0;
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/conversations") {
        attempts += 1;
        return attempts === 1
          ? Promise.reject(new ApiRequestError(503, "UNAVAILABLE", "会话服务暂不可用"))
          : Promise.resolve({ items: [STUDENT_SESSION], total: 1 });
      }
      if (path === "/api/notifications/unread-count") return Promise.resolve({ unread: 0 });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
    renderStudentSessionShell();

    expect(await screen.findByRole("alert")).toHaveTextContent("会话服务暂不可用");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("跨页面学习会话")).toBeInTheDocument();
    expect(attempts).toBeGreaterThanOrEqual(2);
  });
});

describe("StudentLayout 通知铃铛", () => {
  it("未读角标 + 打开面板 + 点击通知标已读并跳任务详情", async () => {
    installNotificationGet();
    mockedPost.mockImplementation((path: string) => {
      if (path === "/api/notifications/n1/read") return Promise.resolve({ id: "n1", read: true });
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 POST ${path}`));
    });
    renderLayout();

    // 角标来自 unread-count 轮询首刷
    const bell = await screen.findByRole("button", { name: "通知（2 条未读）" });
    // The viewport-level slot keeps this persistent control outside both the
    // sidebar and normal page flow across every student workbench route.
    expect(bell.closest(".student-workbench-floating-actions")).not.toBeNull();
    expect(document.querySelector(".student-workbench-page-actions")).toBeNull();
    const sidebar = document.querySelector<HTMLElement>("#shell-sidebar");
    expect(sidebar).not.toBeNull();
    expect(sidebar!).not.toContainElement(bell);
    expect(bell).toHaveAttribute("title", "通知");
    expect(within(bell).getByText("2")).toBeInTheDocument();

    // 打开面板：最近通知（类型中文徽标 + 标题）
    fireEvent.click(bell);
    const item = await screen.findByText("教师发布了新任务");
    expect(screen.getByText("任务")).toBeInTheDocument();
    expect(screen.getByText("系统维护通知")).toBeInTheDocument();

    // 点击任务类通知：标已读 + 跳 /tasks/t9
    fireEvent.click(item);
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/notifications/n1/read");
    });
    expect(await screen.findByText("任务详情标记")).toBeInTheDocument();
    // Route changes can refresh the unread count, so persistence matters here
    // rather than preserving the transient post-click badge value.
    const taskPageBell = await screen.findByRole("button", { name: /^通知/ });
    expect(taskPageBell.closest(".student-workbench-floating-actions")).not.toBeNull();
    expect(taskPageBell.closest(".student-workbench-cockpit-actions")).toBeNull();
    expect(document.querySelector(".student-workbench-page-actions")).toBeNull();
  });

  it("keeps notifications inside the active Cockpit run while the help entry stays removed", async () => {
    installNotificationGet();
    renderLockedLayout();

    expect(await screen.findByTestId("locked-student-cockpit")).toBeInTheDocument();
    expect(document.querySelector(".student-workbench-help-link")).toBeNull();
    expect(screen.getByTestId("locked-student-cockpit")).toBeInTheDocument();

    const bell = await screen.findByRole("button", { name: "通知（2 条未读）" });
    // The Cockpit route keeps the global bell in the shared top-band slot,
    // while the active run still governs which notification actions are safe.
    expect(bell.closest(".student-workbench-cockpit-actions")).not.toBeNull();
    fireEvent.click(bell);
    const taskTitle = await screen.findByText(NOTIFICATIONS[0].title);
    const taskButton = taskTitle.closest("button");
    expect(taskButton).toBeDisabled();
    fireEvent.click(taskButton!);
    expect(screen.getByTestId("locked-student-cockpit")).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalledWith("/api/notifications/n1/read");
  });

  it("全部已读：POST read-all 并清零角标", async () => {
    installNotificationGet();
    mockedPost.mockImplementation((path: string) => {
      if (path === "/api/notifications/read-all") return Promise.resolve({ updated: 2 });
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 POST ${path}`));
    });
    renderLayout();

    fireEvent.click(await screen.findByRole("button", { name: "通知（2 条未读）" }));
    fireEvent.click(await screen.findByRole("button", { name: "全部已读" }));
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/notifications/read-all");
    });
    // 角标清零后铃铛恢复无未读口径
    expect(await screen.findByRole("button", { name: "通知" })).toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 任务批量归档 */

const TASKS = [
  {
    id: "t1",
    title: "任务甲",
    goal: "目标甲",
    status: "in_progress",
    source: "agent",
    data_type: "text",
    scenario_id: null,
    cap_ids: [],
    progress: 0.4,
    latest_score: null,
  },
  {
    id: "t2",
    title: "任务乙",
    goal: "目标乙",
    status: "not_started",
    source: "teacher",
    data_type: "image",
    scenario_id: null,
    cap_ids: [],
    progress: 0,
    latest_score: null,
  },
];

function installTasksGet() {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/api/graph/overview") return Promise.resolve({ nodes: [], edges: [] });
    if (path === "/api/tasks") return Promise.resolve({ items: TASKS, total: 2 });
    return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
  });
}

function renderTasks() {
  return renderPage(<Route path="/tasks" element={<TasksPage />} />, "/tasks");
}

describe("TasksPage 批量归档", () => {
  it("勾选 2 项 → 确认 → batch 载荷正确且列表刷新", async () => {
    installTasksGet();
    mockedPost.mockImplementation((path: string) => {
      if (path === "/api/tasks/batch")
        return Promise.resolve({
          action: "archive",
          results: [
            { id: "t1", ok: true, message: "已归档" },
            { id: "t2", ok: true, message: "已归档" },
          ],
          succeeded: 2,
          failed: 0,
        });
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 POST ${path}`));
    });
    renderTasks();

    expect(await screen.findByText("任务甲")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("选择任务 任务甲"));
    fireEvent.click(screen.getByLabelText("选择任务 任务乙"));
    expect(screen.getByText("已选 2 项")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "批量归档" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认批量归档" }));

    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/tasks/batch", {
        ids: ["t1", "t2"],
        action: "archive",
      });
    });
    expect(document.querySelector(".toast-container")).not.toBeInTheDocument();
    // 批量完成后重新拉取列表（首次加载 + 归档后刷新 = ≥2 次）
    await waitFor(() => {
      const calls = mockedGet.mock.calls.filter((c) => c[0] === "/api/tasks");
      expect(calls.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("部分失败：失败项以 toast 明细展示任务名与原因", async () => {
    installTasksGet();
    mockedPost.mockImplementation((path: string) => {
      if (path === "/api/tasks/batch")
        return Promise.resolve({
          action: "archive",
          results: [
            { id: "t1", ok: true, message: "已归档" },
            { id: "t2", ok: false, message: "任务不存在或无权限操作" },
          ],
          succeeded: 1,
          failed: 1,
        });
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 POST ${path}`));
    });
    renderTasks();

    expect(await screen.findByText("任务甲")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("全选当前列表"));
    expect(screen.getByText("已选 2 项")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "批量归档" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认批量归档" }));

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/tasks/batch", {
        ids: ["t1", "t2"],
        action: "archive",
      }),
    );
    expect(document.querySelector(".toast-container")).not.toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- RAG 引用收藏 */

const RAG_ANSWER = {
  answer: "实体边界应按 B-I-O 规则划分。",
  steps: [],
  notes: [],
  followups: [],
  citations: [
    {
      document_id: "d1",
      title: "规范文档A",
      section_title: "第三章",
      page_start: 1,
      page_end: 2,
      version: "3",
      score: 0.9,
    },
  ],
  related_cap_ids: [],
  refused: false,
  notice: null,
};

function renderRagQa() {
  return renderPage(<Route path="/rag-qa" element={<RagQaPage />} />, "/rag-qa");
}

describe("RagQaPage 引用收藏", () => {
  it("☆ 收藏 → ★ 已收藏 → 再点取消收藏", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/graph/overview") return Promise.resolve({ nodes: [], edges: [] });
      if (path === "/api/profile/favorites") return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
    });
    mockedPost.mockImplementation((path: string) => {
      if (path === "/api/rag/query") return Promise.resolve(RAG_ANSWER);
      if (path === "/api/profile/favorites")
        return Promise.resolve({
          favorite: { id: "f1", item_type: "citation", item_id: "d1", title: "规范文档A" },
          created: true,
        });
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 POST ${path}`));
    });
    mockedDelete.mockImplementation((path: string) => {
      if (path === "/api/profile/favorites/f1") return Promise.resolve({ message: "已取消收藏" });
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 DELETE ${path}`));
    });
    renderRagQa();

    // 提问拿到带引用的回答
    fireEvent.change(screen.getByLabelText("问题输入"), {
      target: { value: "实体边界如何划分？" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提问" }));

    // 收藏：POST item_type='citation' + meta{section,version}
    const star = await screen.findByRole("button", { name: "收藏 规范文档A" });
    fireEvent.click(star);
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/profile/favorites", {
        item_type: "citation",
        item_id: "d1",
        title: "规范文档A",
        meta: { section: "第三章", version: "3" },
      });
    });

    // 已收藏态（★）→ 取消收藏按收藏行 id DELETE
    const unstar = await screen.findByRole("button", { name: "取消收藏 规范文档A" });
    fireEvent.click(unstar);
    await waitFor(() => {
      expect(mockedDelete).toHaveBeenCalledWith("/api/profile/favorites/f1");
    });
    expect(await screen.findByRole("button", { name: "收藏 规范文档A" })).toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 个人中心增强 */

function installProfileGet(shareDiagnostics: boolean) {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/api/profile")
      return Promise.resolve({
        user: { id: "u1", email: "stu@example.com", name: "学生甲", role: "student" },
        task_counts: { in_progress: 1 },
        recent_diagnostic_summaries: [],
        growth: [],
        favorites: [],
        settings: { share_diagnostics: shareDiagnostics },
      });
    if (path === "/api/profile/mastery")
      return Promise.resolve({
        items: [
          {
            cap_id: "C1",
            cap_name: "能力甲",
            scenario_id: "",
            score: 0.5,
            source: "exercise",
            updated_at: "2026-07-31T00:00:00Z",
            scenario_name: "通用",
          },
        ],
        total: 1,
      });
    if (path === "/api/tasks") return Promise.resolve({ items: [], total: 0 });
    if (path === "/api/profile/favorites")
      return Promise.resolve({
        items: [
          {
            id: "f9",
            item_type: "rag_document",
            item_id: "d1",
            title: "规范文档A",
            meta: {},
            created_at: "2026-07-01T10:00:00Z",
          },
        ],
        total: 1,
      });
    if (path === "/api/profile/mastery/trend")
      return Promise.resolve({
        items: [
          {
            date: "2026-07-20",
            cap_id: "C1",
            scenario_id: "",
            old_score: 0.3,
            new_score: 0.4,
            source: "exercise",
            created_at: "2026-07-20T10:00:00Z",
          },
          {
            date: "2026-07-31",
            cap_id: "C1",
            scenario_id: "",
            old_score: 0.4,
            new_score: 0.5,
            source: "exercise",
            created_at: "2026-07-31T10:00:00Z",
          },
        ],
        total: 2,
        days: 30,
        cap_id: "C1",
      });
    return Promise.reject(new ApiRequestError(404, "NOT_FOUND", `未 mock 的 GET ${path}`));
  });
}

describe("ProfilePage 增强", () => {
  it("收藏资料真实列表渲染（类型中文 Tag + 标题）", async () => {
    installProfileGet(false);
    renderPage(<Route path="/profile" element={<ProfilePage />} />, "/profile");

    expect(await screen.findByText("规范文档A")).toBeInTheDocument();
    expect(screen.getByText("资料文档")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "删除收藏 规范文档A" })).toBeInTheDocument();
  });

  it("诊断分享开关：勾选即 PATCH share_diagnostics", async () => {
    installProfileGet(false);
    mockedPatch.mockImplementation((path: string) => {
      if (path === "/api/profile")
        return Promise.resolve({ settings: { share_diagnostics: true } });
      return Promise.reject(new ApiRequestError(500, "NOT_MOCKED", `未 mock 的 PATCH ${path}`));
    });
    renderPage(<Route path="/profile" element={<ProfilePage />} />, "/profile");

    const toggle = await screen.findByLabelText("允许任课教师查看我的诊断详情");
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    await waitFor(() => {
      expect(mockedPatch).toHaveBeenCalledWith("/api/profile", {
        share_diagnostics: true,
      });
    });
    // 成功后开关反映服务端回执
    await waitFor(() => {
      expect(screen.getByLabelText("允许任课教师查看我的诊断详情")).toBeChecked();
    });
  });

  it("点击能力行打开趋势抽屉：拉取 trend 并渲染折线", async () => {
    installProfileGet(false);
    renderPage(<Route path="/profile" element={<ProfilePage />} />, "/profile");

    fireEvent.click(await screen.findByRole("button", { name: "能力甲" }));
    expect(await screen.findByText("能力甲 · 近 30 天趋势")).toBeInTheDocument();
    await waitFor(() => {
      expect(mockedGet).toHaveBeenCalledWith(
        "/api/profile/mastery/trend",
        {
          cap_id: "C1",
          days: 30,
        },
        expect.objectContaining({ signal: expect.anything() }),
      );
    });
    expect(await screen.findByRole("img", { name: "掌握度趋势" })).toBeInTheDocument();
  });
});
