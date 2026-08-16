/**
 * 教师端测试（四）：B2 增强项。
 *
 * 覆盖验收点：
 * - PRD-02 §5.3 AI 生成任务卡：POST /api/teacher/tasks/generate 的草稿整体
 *   填入名称、描述、学习内容和练习；旧能力、步骤、评分与资源编辑不再出现；
 *   横幅如实展示 sources_note 与 llm_used 徽章，且填入后四字段仍可编辑；
 * - PRD-06 §10.1 已发布任务截止时间调整：选中已发布任务时出现"不生成新版本"
 *   说明，提交只 PATCH due_at；
 * - PRD-02 §6 学生个人能力地图：在独立分析页选择学生后调 analytics/students/{id} 渲染
 *   掌握度表格/最近任务/趋势图，诊断未授权时展示提示而非数据；
 * - PRD-06 §15 #2 班级详情"查看诊断"：403 SHARE_NOT_GRANTED → "学生未授权"
 *   空态；授权 → 摘要表 + 可展开的逐条错误报告。
 *
 * api 层整体打桩（与前三个教师测试文件同一模式）。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ReactElement } from "react";
import { ToastProvider } from "../src/components";
import TaskPublishPage from "../src/pages/teacher/TaskPublishPage";
import AnalyticsPage from "../src/pages/teacher/AnalyticsPage";
import StudentAnalyticsPage from "../src/pages/teacher/StudentAnalyticsPage";
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
const mockedPatch = vi.mocked(api.patch);

function renderPage(ui: ReactElement, route: string, path?: string) {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[route]}>
        {path ? (
          <Routes>
            <Route path={path} element={ui} />
          </Routes>
        ) : (
          ui
        )}
      </MemoryRouter>
    </ToastProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

/* ---------------------------------------------------------------- AI 生成任务卡 */

describe("TaskPublishPage：AI 生成任务卡（PRD-02 §5.3）", () => {
  /** generate 端点响应（结构对齐 teacher.py generate_teacher_task） */
  const aiDraft = {
    title: "客服语音情感标注实战",
    goal: "完成「客服语音情感标注实战」对应的学习任务，掌握相关规范要点。",
    description: "完成「客服语音情感标注实战」对应的学习任务，掌握相关规范要点。",
    data_type: "audio",
    caps: [],
    knowledge_points: [
      {
        title: "情感判断标准",
        content: "区分投诉、咨询和中性表达，并记录支撑判断的原句。",
      },
      {
        title: "复核方法",
        content: "提交前复核情感标签、上下文与遗漏项。",
      },
    ],
    exercises: [
      {
        question: "客户明确表达不满时，应选择哪种情感？",
        type: "multiple_choice",
        options: ["负面", "中性", "正面"],
        reference_answer: "负面",
      },
      {
        question: "提交前需要复核全部必填项。",
        type: "true_false",
        options: ["正确", "错误"],
        reference_answer: "正确",
      },
      {
        question: "请说明你判断负面情感的依据。",
        type: "open_ended",
        options: null,
        reference_answer: "结合客户表达的不满与投诉意图说明。",
      },
    ],
    difficulty: 3,
    est_minutes: 60,
    sources_note: "已引用 1 份已发布知识库资料，发布前请核对引用条款是否适用",
    llm_used: true,
    notice: null,
  };

  beforeEach(() => {
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
      if (path === "/api/graph/nodes") return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error(`未 mock 的 GET ${String(path)}`));
    });
    mockedPost.mockImplementation((path) => {
      if (path === "/api/teacher/tasks/generate") return Promise.resolve(aiDraft);
      return Promise.reject(new Error(`未 mock 的 POST ${String(path)}`));
    });
  });

  it("AI 生成草稿整体填入表单，横幅展示来源说明与生成方式，且字段仍可编辑", async () => {
    renderPage(<TaskPublishPage />, "/teacher/tasks");
    // 等基础数据（班级下拉）就绪，避免与初始加载竞争
    expect(await screen.findByDisplayValue("请选择班级")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/粘贴或描述企业岗位任务/), {
      target: { value: "对客服通话录音完成情感极性标注" },
    });
    fireEvent.click(screen.getByRole("button", { name: /AI 生成任务卡/ }));

    // 请求打到 generate 端点并携带描述
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/teacher/tasks/generate",
        expect.objectContaining({ description: "对客服通话录音完成情感极性标注" }),
      ),
    );

    // 四字段草稿填入：任务名称、描述、学习内容与练习都是可编辑表单控件。
    expect(await screen.findByDisplayValue("客服语音情感标注实战")).toBeInTheDocument();
    expect(screen.getByDisplayValue(/掌握相关规范要点/)).toBeInTheDocument();
    expect(screen.getByDisplayValue("情感判断标准")).toBeInTheDocument();
    expect(screen.getByDisplayValue("区分投诉、咨询和中性表达，并记录支撑判断的原句。")).toBeInTheDocument();
    expect(screen.getByDisplayValue("客户明确表达不满时，应选择哪种情感？")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "练习 1 题型" })).toHaveTextContent("选择题");
    expect(
      (screen.getAllByPlaceholderText("每行一个选项")[0] as HTMLTextAreaElement).value,
    ).toContain("负面");
    expect(screen.getByRole("combobox", { name: "练习 2 题型" })).toHaveTextContent("判断题");
    expect(screen.getByRole("combobox", { name: "练习 3 题型" })).toHaveTextContent("问答题");

    // Removed task-authoring fields must not reappear when AI returns a draft.
    expect(screen.queryByText("关联能力")).not.toBeInTheDocument();
    expect(screen.queryByText("操作步骤")).not.toBeInTheDocument();
    expect(screen.queryByText("评分规则")).not.toBeInTheDocument();
    expect(screen.queryByText("学习资源")).not.toBeInTheDocument();

    // 横幅：审核提示 + llm_used 徽章 + sources_note
    expect(await screen.findByText("AI 草稿，请审核后发布")).toBeInTheDocument();
    expect(screen.getByText("模型润色")).toBeInTheDocument();
    expect(
      screen.getByText("已引用 1 份已发布知识库资料，发布前请核对引用条款是否适用"),
    ).toBeInTheDocument();

    // 填入后字段仍可编辑：改标题，常驻预览实时跟随
    fireEvent.change(screen.getByPlaceholderText("例如：客服语音情感标注实战"), {
      target: { value: "人工修订后的任务标题" },
    });
    expect(
      await screen.findByRole("heading", { name: "人工修订后的任务标题" }),
    ).toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 已发布任务截止时间调整 */

describe("TaskPublishPage：已发布任务截止时间调整（PRD-06 §10.1）", () => {
  const publishedTask = {
    id: "t9",
    title: "已发布的标注任务",
    goal: "完成标注",
    description: "完成标注",
    data_type: "audio",
    cap_ids: [],
    steps: [],
    rubric: [],
    knowledge_points: [
      {
        id: "kp9",
        title: "标注规范",
        content: "按要求完成标注。",
        sort_order: 0,
        created_at: "2026-07-01T00:00:00Z",
        updated_at: "2026-07-01T00:00:00Z",
      },
    ],
    exercises: [],
    status: "draft",
    version: 1,
    parent_task_id: null,
    published_count: 2,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-20T00:00:00Z",
  };

  beforeEach(() => {
    mockedGet.mockImplementation((path, _query) => {
      if (path === "/api/teacher/tasks") {
        return Promise.resolve({ items: [publishedTask], total: 1 });
      }
      if (path === "/api/teacher/classes") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/graph/nodes") return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error(`未 mock 的 GET ${String(path)}`));
    });
    mockedPatch.mockResolvedValue({ ...publishedTask, version_bumped: false });
  });

  it("选中已发布任务时展示不升版本说明，提交只 PATCH due_at", async () => {
    renderPage(<TaskPublishPage />, "/teacher/tasks");

    // 在左侧任务列表选中已发布任务
    fireEvent.click(await screen.findByRole("button", { name: /已发布的标注任务/ }));

    // 内容编辑的版本升级横幅 + 截止时间调整的"不生成新版本"说明都在场
    expect(
      await screen.findByText("修改已发布任务将生成新版本，不影响已开始的学生"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("修改截止时间将通知本班学生并记录审计（不生成新版本）"),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("新的截止时间"), {
      target: { value: "2026-08-10T12:00" },
    });
    fireEvent.click(screen.getByRole("button", { name: "更新截止时间" }));

    // 只 PATCH due_at，不携带任何内容字段（内容变更才触发版本升级）
    await waitFor(() =>
      expect(mockedPatch).toHaveBeenCalledWith("/api/teacher/tasks/t9", {
        due_at: new Date("2026-08-10T12:00").toISOString(),
      }),
    );
    expect(document.querySelector(".toast-container")).not.toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 学情：学生个人明细 */

describe("StudentAnalyticsPage：学生个人能力地图明细（PRD-02 §6）", () => {
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
    mockedGet.mockImplementation((path, _query) => {
      if (path === "/api/teacher/classes") {
        return Promise.resolve({
          items: [
            {
              id: "c1",
              name: "数据标注2301班",
              invite_code: "CODE",
              student_count: 1,
              recent_task_title: null,
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          total: 1,
        });
      }
      if (path === "/api/graph/nodes") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/teacher/classes/c1/students") {
        return Promise.resolve({ items: [student], total: 1 });
      }
      if (path === "/api/teacher/analytics") {
        return Promise.resolve({
          heatmap: [],
          trend: [],
          top_errors: [],
          suggestions: [],
          student_count: 1,
          sample_warning: true,
        });
      }
      if (path === "/api/teacher/analytics/students/s1") {
        return Promise.resolve({
          student_id: "s1",
          class_id: "c1",
          mastery: [
            {
              cap_id: "CAP-1",
              cap_name: "语音切分",
              score: 0.85,
              updated_at: "2026-07-31T10:00:00Z",
            },
          ],
          tasks: [
            {
              id: "st1",
              title: "情感标注练习",
              status: "completed",
              source: "teacher",
              score: 0.92,
              updated_at: "2026-07-30T09:00:00Z",
            },
          ],
          // 未授权：diagnostics=null + note（PRD-06 §15 #2）
          diagnostics: null,
          diagnostics_note: "学生未授权教师查看诊断详情，此处仅展示聚合学习数据（PRD-06 §10.2）",
          mastery_events: [
            {
              cap_id: "CAP-1",
              old_score: 0.7,
              new_score: 0.85,
              source: "practice",
              created_at: "2026-07-31T10:00:00Z",
            },
          ],
        });
      }
      return Promise.reject(new Error(`未 mock 的 GET ${String(path)}`));
    });
  });

  it("选择学生后按 class_id 拉取明细，渲染掌握度/任务/趋势，未授权诊断展示提示", async () => {
    renderPage(<StudentAnalyticsPage />, "/teacher/analytics/students?class_id=c1");

    // 通过可见组合框完成选择，覆盖 Portal 选项列表而非隐藏的表单值桥接层。
    const studentSelect = await screen.findByRole("combobox", { name: "学生" });
    await waitFor(() => expect(studentSelect).not.toBeDisabled());
    fireEvent.click(studentSelect);
    fireEvent.click(await screen.findByRole("option", { name: "张三（zhangsan@demo.bhzd）" }));

    // 明细请求必须带 class_id（教师数据权限以班级为边界）
    await waitFor(() =>
      expect(mockedGet).toHaveBeenCalledWith(
        "/api/teacher/analytics/students/s1",
        { class_id: "c1" },
        expect.objectContaining({ signal: expect.anything() }),
      ),
    );

    // 掌握度表格：能力名 + 分数徽章/百分比
    expect(await screen.findByText("逐能力掌握度（1）")).toBeInTheDocument();
    expect(screen.getAllByText("语音切分").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("85%").length).toBeGreaterThanOrEqual(1);

    // 最近任务：标题 + 状态徽章 + 得分
    expect(screen.getByText("情感标注练习")).toBeInTheDocument();
    expect(screen.getByText("已完成")).toBeInTheDocument();
    expect(screen.getByText("92%")).toBeInTheDocument();

    // 掌握度趋势：SVG 折线图 + 图例（最新分数）
    expect(screen.getByRole("img", { name: "掌握度变化趋势图" })).toBeInTheDocument();
    expect(screen.getByText(/最新 85%/)).toBeInTheDocument();

    // 诊断未授权：提示 + 后端 note，绝不渲染诊断数据
    expect(await screen.findByText("该学生未授权诊断详情")).toBeInTheDocument();
    expect(screen.getByText(/学生未授权教师查看诊断详情/)).toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 班级详情：诊断授权查看 */

describe("ClassDetailPage：学生诊断查看（PRD-06 §15 #2）", () => {
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

  function mockClassBase() {
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
      if (path === "/api/teacher/classes/c1/students/s1/diagnostics") {
        return Promise.reject(
          new ApiRequestError(403, "SHARE_NOT_GRANTED", "学生未授权教师查看诊断详情"),
        );
      }
      return Promise.reject(new Error(`未 mock 的 GET ${String(path)}`));
    });
  }

  /** 打开学生抽屉并点击"查看诊断" */
  async function openAndLoadDiagnostics() {
    expect(await screen.findByText("张三")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看" }));
    expect(await screen.findByText("张三 的学习状态")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看诊断" }));
  }

  it("未授权：403 SHARE_NOT_GRANTED 展示学生未授权空态与开启指引", async () => {
    mockClassBase();
    renderPage(<ClassDetailPage />, "/teacher/classes/c1", "/teacher/classes/:id");

    await openAndLoadDiagnostics();

    await waitFor(() =>
      expect(mockedGet).toHaveBeenCalledWith("/api/teacher/classes/c1/students/s1/diagnostics"),
    );
    expect(await screen.findByText("学生未授权")).toBeInTheDocument();
    expect(screen.getByText(/学生可在个人中心开启/)).toBeInTheDocument();
  });

  it("已授权：渲染诊断摘要表，展开报告展示逐条错误归因", async () => {
    mockClassBase();
    // 覆盖未授权打桩：返回带报告的授权响应
    const baseImpl = mockedGet.getMockImplementation()!;
    mockedGet.mockImplementation((path) => {
      if (path === "/api/teacher/classes/c1/students/s1/diagnostics") {
        return Promise.resolve({
          items: [
            {
              id: "dg1",
              file_format: "textgrid",
              data_type: "audio",
              error_count: 2,
              severity_counts: { major: 1, minor: 1 },
              created_at: "2026-07-29T08:00:00Z",
              report: {
                errors: [
                  {
                    error_type: "boundary_overflow",
                    severity: "major",
                    user_value: 12.5,
                    expected: "不超过音频时长",
                    rule: "标注区间越界",
                    cap_id: "CAP-1",
                    suggestion: "将区间右边界收回到音频时长以内",
                  },
                ],
              },
            },
          ],
          total: 1,
          shared: true,
        });
      }
      return baseImpl(path as string);
    });

    renderPage(<ClassDetailPage />, "/teacher/classes/c1", "/teacher/classes/:id");
    await openAndLoadDiagnostics();

    // 摘要表：格式 + 严重度徽章 + 错误数
    expect(await screen.findByText("textgrid")).toBeInTheDocument();
    expect(screen.getByText("严重 1")).toBeInTheDocument();
    expect(screen.getByText("次要 1")).toBeInTheDocument();

    // 展开报告：逐条错误（严重度 + error_type + 规则 + 建议）
    fireEvent.click(screen.getByRole("button", { name: "展开" }));
    expect(await screen.findByText("boundary_overflow")).toBeInTheDocument();
    expect(screen.getByText("规则：标注区间越界")).toBeInTheDocument();
    expect(screen.getByText("建议：将区间右边界收回到音频时长以内")).toBeInTheDocument();
  });
});
