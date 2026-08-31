/**
 * 教师端测试（二）：教学任务发布（PRD-02 §5）。
 *
 * 覆盖已确认的任务正文契约：
 * - 任务编辑只包含名称、描述、学习内容和练习，名称是唯一最小必填项；
 * - 学习内容和练习在任务行落库后分别保存，选择题保留题型、选项与教师参考答案；
 * - 班级、截止时间和掌握度只属于独立发布设置，不会混入任务正文；
 * - Teacher Agent 交接的草稿能恢复四字段内容，但不会隐式发布。
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
const mockedPut = vi.mocked(api.put);

const testClass = {
  id: "c1",
  name: "数据标注2301班",
  invite_code: "CODE",
  student_count: 5,
  recent_task_title: null,
  created_at: "2026-01-01T00:00:00Z",
};

function renderPage() {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={["/teacher/tasks"]}>
        <TaskPublishPage />
      </MemoryRouter>
    </ToastProvider>,
  );
}

function fillTitle(value = "客服语音情感标注实战") {
  fireEvent.change(screen.getByPlaceholderText("例如：客服语音情感标注实战"), {
    target: { value },
  });
}

function fillDescription(value = "学习并判断客服语音中的情感极性。") {
  fireEvent.change(screen.getByPlaceholderText("说明学生要学习的主题、范围和预期结果"), {
    target: { value },
  });
}

function addLearningContent() {
  fireEvent.click(screen.getByRole("button", { name: "添加学习内容" }));
  fireEvent.change(screen.getByPlaceholderText("知识点 1"), {
    target: { value: "情感标注规范" },
  });
  fireEvent.change(screen.getByPlaceholderText("填写这一知识点的学习内容"), {
    target: { value: "区分投诉、咨询和中性表达，并记录判断依据。" },
  });
}

/** The project Select exposes a button + portal listbox, so choose its visible option. */
function selectExerciseType(optionName: "选择题" | "判断题" | "问答题") {
  fireEvent.click(screen.getByRole("combobox", { name: "练习 1 题型" }));
  fireEvent.click(screen.getByRole("option", { name: optionName }));
}

function addChoiceExercise() {
  fireEvent.click(screen.getByRole("button", { name: "添加练习" }));
  fireEvent.change(screen.getByPlaceholderText("练习题 1"), {
    target: { value: "客户明确表达不满时，应标注为哪种情感？" },
  });
  selectExerciseType("选择题");
  fireEvent.change(screen.getByPlaceholderText("每行一个选项"), {
    target: { value: "负面\n中性" },
  });
  fireEvent.change(screen.getByPlaceholderText("参考答案（仅教师可见）"), {
    target: { value: "负面" },
  });
}

function createAgentTask(id: string, title: string) {
  return {
    id,
    published_count: 0,
    title,
    // goal remains the rolling storage-compatible alias for the visible task description.
    goal: "根据对话生成的学习任务描述。",
    description: "根据对话生成的学习任务描述。",
    data_type: null,
    cap_ids: [],
    steps: [],
    rubric: [],
    knowledge_points: [
      {
        id: "kp-agent",
        title: "复盘要点",
        content: "对照示例梳理本轮学习的关键判断依据。",
        sort_order: 0,
        created_at: "2026-08-01T00:00:00Z",
        updated_at: "2026-08-01T00:00:00Z",
      },
    ],
    exercises: [
      {
        id: "ex-agent",
        question: "提交前是否应复核所有必填项？",
        type: "true_false",
        options: ["正确", "错误"],
        reference_answer: "正确",
        sort_order: 0,
        created_at: "2026-08-01T00:00:00Z",
        submission: null,
      },
    ],
    class_id: "c1",
    version: 1,
    updated_at: "2026-08-01T00:00:00Z",
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedGet.mockImplementation((path) => {
    if (path === "/api/teacher/tasks") return Promise.resolve({ items: [], total: 0 });
    if (path === "/api/teacher/classes") return Promise.resolve({ items: [testClass], total: 1 });
    // The page still loads the graph name map for legacy task rows, but the
    // active authoring UI must not require or render a capability association.
    if (path === "/api/graph/nodes") return Promise.resolve({ items: [], total: 0 });
    if (path === "/api/teacher/tasks/t1/knowledge-points") return Promise.resolve({ items: [] });
    if (path === "/api/teacher/tasks/t1/exercises") return Promise.resolve({ items: [] });
    return Promise.reject(new Error("未 mock 的 GET " + String(path)));
  });
  mockedPost.mockImplementation((path) => {
    if (path === "/api/teacher/tasks") {
      return Promise.resolve({ id: "t1", published_count: 0, version: 1, version_bumped: false });
    }
    if (path === "/api/teacher/tasks/t1/knowledge-points") {
      return Promise.resolve({ id: "kp1" });
    }
    if (path === "/api/teacher/tasks/t1/exercises") {
      return Promise.resolve({ id: "ex1" });
    }
    if (path === "/api/teacher/tasks/t1/publish") {
      return Promise.resolve({ published: 5, class_id: "c1" });
    }
    return Promise.reject(new Error("未 mock 的 POST " + String(path)));
  });
  mockedPatch.mockResolvedValue({
    id: "t1",
    published_count: 0,
    version: 1,
    version_bumped: false,
  });
  mockedPut.mockImplementation((path) => {
    if (path === "/api/teacher/tasks/t1/content") {
      return Promise.resolve({ knowledge_points: [], exercises: [] });
    }
    return Promise.reject(new Error("未 mock 的 PUT " + String(path)));
  });
});

describe("TaskPublishPage（PRD-02 §5）", () => {
  it("opens the four-field task handed off by Teacher Agent", async () => {
    const agentTask = createAgentTask("t-agent", "Agent 生成任务");
    mockedGet.mockImplementation((path) => {
      if (path === "/api/teacher/tasks/t-agent") return Promise.resolve(agentTask);
      if (path === "/api/teacher/tasks") return Promise.resolve({ items: [agentTask], total: 1 });
      if (path === "/api/teacher/classes") return Promise.resolve({ items: [testClass], total: 1 });
      if (path === "/api/graph/nodes") return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error("未 mock 的 GET " + String(path)));
    });

    render(
      <ToastProvider>
        <MemoryRouter initialEntries={[{ pathname: "/teacher/tasks", state: { taskId: "t-agent" } }]}>
          <TaskPublishPage />
        </MemoryRouter>
      </ToastProvider>,
    );

    expect(await screen.findByDisplayValue("Agent 生成任务")).toBeInTheDocument();
    expect(screen.getByDisplayValue("根据对话生成的学习任务描述。")).toBeInTheDocument();
    expect(screen.getByDisplayValue("复盘要点")).toBeInTheDocument();
    expect(screen.getByDisplayValue("对照示例梳理本轮学习的关键判断依据。")).toBeInTheDocument();
    expect(screen.getByDisplayValue("提交前是否应复核所有必填项？")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "练习 1 题型" })).toHaveTextContent("判断题");
    expect(screen.getByRole("combobox", { name: "选择班级" })).toHaveTextContent("数据标注2301班");
    expect(mockedPost.mock.calls.some(([path]) => String(path).endsWith("/publish"))).toBe(false);
  });

  it("persists an Agent handoff as task fields plus learning content and exercises, then publishes only on demand", async () => {
    const agentTask = createAgentTask("t-agent-contract", "Agent 字段契约草稿");
    mockedGet.mockImplementation((path) => {
      if (path === "/api/teacher/tasks") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/teacher/tasks/t-agent-contract") return Promise.resolve(agentTask);
      if (path === "/api/teacher/classes") return Promise.resolve({ items: [testClass], total: 1 });
      if (path === "/api/graph/nodes") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/teacher/tasks/t-agent-contract/knowledge-points") {
        return Promise.resolve({ items: agentTask.knowledge_points });
      }
      if (path === "/api/teacher/tasks/t-agent-contract/exercises") {
        return Promise.resolve({ items: agentTask.exercises });
      }
      return Promise.reject(new Error("未 mock 的 GET " + String(path)));
    });
    mockedPatch.mockImplementation((path) => {
      if (path === "/api/teacher/tasks/t-agent-contract") {
        return Promise.resolve({
          id: "t-agent-contract",
          published_count: 0,
          version: 1,
          version_bumped: false,
        });
      }
      return Promise.resolve({});
    });
    mockedPut.mockImplementation((path) => {
      if (path === "/api/teacher/tasks/t-agent-contract/content") {
        return Promise.resolve({
          ...agentTask,
          version_bumped: false,
          knowledge_points: agentTask.knowledge_points,
          exercises: agentTask.exercises,
        });
      }
      return Promise.reject(new Error("未 mock 的 PUT " + String(path)));
    });
    mockedPost.mockImplementation((path) => {
      if (path === "/api/teacher/tasks/t-agent-contract/publish") {
        return Promise.resolve({ published: 5, class_id: "c1" });
      }
      return Promise.reject(new Error("未 mock 的 POST " + String(path)));
    });

    render(
      <ToastProvider>
        <MemoryRouter initialEntries={["/teacher/tasks?taskId=t-agent-contract"]}>
          <TaskPublishPage />
        </MemoryRouter>
      </ToastProvider>,
    );

    expect(await screen.findByDisplayValue("Agent 字段契约草稿")).toBeInTheDocument();
    expect(screen.getByDisplayValue("复盘要点")).toBeInTheDocument();
    expect(screen.getByDisplayValue("提交前是否应复核所有必填项？")).toBeInTheDocument();
    await waitFor(() =>
      expect(mockedGet).toHaveBeenCalledWith(
        "/api/teacher/tasks/t-agent-contract",
        undefined,
        expect.objectContaining({ signal: expect.anything() }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() =>
      expect(mockedPatch).toHaveBeenCalledWith("/api/teacher/tasks/t-agent-contract", {
        title: "Agent 字段契约草稿",
        description: "根据对话生成的学习任务描述。",
        defer_content_generation: true,
      }),
    );
    await waitFor(() =>
      expect(mockedPut).toHaveBeenCalledWith("/api/teacher/tasks/t-agent-contract/content", {
        knowledge_points: [
          {
            title: "复盘要点",
            content: "对照示例梳理本轮学习的关键判断依据。",
            sort_order: 0,
          },
        ],
        exercises: [
          {
            question: "提交前是否应复核所有必填项？",
            type: "true_false",
            options: ["正确", "错误"],
            reference_answer: "正确",
            sort_order: 0,
          },
        ],
      }),
    );
    const taskSaveCall = mockedPatch.mock.calls.find(
      ([path]) => path === "/api/teacher/tasks/t-agent-contract",
    );
    expect(taskSaveCall?.[1]).not.toHaveProperty("cap_ids");
    expect(taskSaveCall?.[1]).not.toHaveProperty("steps");
    expect(taskSaveCall?.[1]).not.toHaveProperty("rubric");
    expect(taskSaveCall?.[1]).not.toHaveProperty("resources");
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

  it("renders only the four task fields and keeps legacy authoring controls absent", async () => {
    renderPage();

    expect(document.querySelector(".teacher-task-publish-page")).toBeInTheDocument();
    expect(document.querySelector(".teacher-task-editor-layout")).toBeInTheDocument();
    expect(document.querySelector(".teacher-task-review-layout")).toBeInTheDocument();
    expect(screen.getByText("任务名称")).toBeInTheDocument();
    expect(screen.getByText("任务描述")).toBeInTheDocument();
    expect(screen.getByText("学习内容")).toBeInTheDocument();
    expect(screen.getByText("练习")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI 生成任务卡" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "仅填入学习目标" })).toBeInTheDocument();
    expect(screen.queryByText("关联能力")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("搜索能力节点…")).not.toBeInTheDocument();
    expect(screen.queryByText("操作步骤")).not.toBeInTheDocument();
    expect(screen.queryByText("评分规则")).not.toBeInTheDocument();
    expect(screen.queryByText("学习资源")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("资源标题")).not.toBeInTheDocument();
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

  it("requires only a name to save a draft and keeps publish settings out of the task payload", async () => {
    renderPage();
    expect(await screen.findByDisplayValue("请选择班级")).toBeInTheDocument();

    fillTitle();
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/teacher/tasks", {
        title: "客服语音情感标注实战",
        description: null,
        defer_content_generation: true,
      }),
    );
    const saveCall = mockedPost.mock.calls.find(([path]) => path === "/api/teacher/tasks");
    expect(saveCall?.[1]).not.toHaveProperty("class_id");
    expect(saveCall?.[1]).not.toHaveProperty("due_at");
    expect(saveCall?.[1]).not.toHaveProperty("counts_toward_mastery");
    expect(screen.queryByText("任务必须至少关联一个能力节点")).not.toBeInTheDocument();
  });

  it("keeps a live preview of task name, description, learning content, and practice", async () => {
    renderPage();
    expect(screen.getByText("未命名任务")).toBeInTheDocument();
    expect(screen.getByText("暂无学习内容")).toBeInTheDocument();
    expect(screen.getByText("暂无练习")).toBeInTheDocument();

    fillTitle();
    fillDescription();
    addLearningContent();
    addChoiceExercise();

    expect(
      await screen.findByRole("heading", { name: "客服语音情感标注实战" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("学习并判断客服语音中的情感极性。").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("情感标注规范").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("客户明确表达不满时，应标注为哪种情感？").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("（选择题）")).toBeInTheDocument();
    expect(screen.queryByText("关联能力（")).not.toBeInTheDocument();
    expect(screen.queryByText("操作步骤（")).not.toBeInTheDocument();
    expect(screen.queryByText("评分规则")).not.toBeInTheDocument();
  });

  it("publishes after persisting the four-field task body and its learning content and practice", async () => {
    renderPage();
    expect(await screen.findByDisplayValue("请选择班级")).toBeInTheDocument();

    fillTitle();
    fillDescription();
    addLearningContent();
    addChoiceExercise();
    fireEvent.change(screen.getByDisplayValue("请选择班级"), {
      target: { value: "c1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发布" }));

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/teacher/tasks", {
        title: "客服语音情感标注实战",
        description: "学习并判断客服语音中的情感极性。",
        defer_content_generation: true,
      }),
    );
    await waitFor(() =>
      expect(mockedPut).toHaveBeenCalledWith("/api/teacher/tasks/t1/content", {
        knowledge_points: [
          {
            title: "情感标注规范",
            content: "区分投诉、咨询和中性表达，并记录判断依据。",
            sort_order: 0,
          },
        ],
        exercises: [
          {
            question: "客户明确表达不满时，应标注为哪种情感？",
            type: "multiple_choice",
            options: ["负面", "中性"],
            reference_answer: "负面",
            sort_order: 0,
          },
        ],
      }),
    );
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/teacher/tasks/t1/publish", {
        class_id: "c1",
        due_at: null,
        counts_toward_mastery: true,
      }),
    );
  });

  it("blocks publishing until a class is selected without requiring a capability relation", async () => {
    renderPage();
    expect(await screen.findByDisplayValue("请选择班级")).toBeInTheDocument();

    fillTitle();
    fireEvent.click(screen.getByRole("button", { name: "发布" }));

    expect(await screen.findByText("发布前请选择班级")).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("saves authored learning content atomically and shows a persistent publish result", async () => {
    renderPage();
    expect(await screen.findByDisplayValue("请选择班级")).toBeInTheDocument();

    fillTitle();
    fillDescription();
    addLearningContent();
    addChoiceExercise();
    fireEvent.change(screen.getByDisplayValue("请选择班级"), {
      target: { value: "c1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发布" }));

    await waitFor(() => {
      expect(mockedPut).toHaveBeenCalledWith("/api/teacher/tasks/t1/content", {
        knowledge_points: [
          {
            title: "情感标注规范",
            content: "区分投诉、咨询和中性表达，并记录判断依据。",
            sort_order: 0,
          },
        ],
        exercises: [
          {
            question: "客户明确表达不满时，应标注为哪种情感？",
            type: "multiple_choice",
            options: ["负面", "中性"],
            reference_answer: "负面",
            sort_order: 0,
          },
        ],
      });
    });
    expect(await screen.findByRole("status", { name: "发布结果" })).toHaveTextContent(
      "已发布给 5 名学生",
    );
  });

  it("retains the created draft id when content persistence fails so retry cannot duplicate the task", async () => {
    let attempts = 0;
    mockedPut.mockImplementation((path) => {
      if (path !== "/api/teacher/tasks/t1/content") {
        return Promise.reject(new Error("未 mock 的 PUT " + String(path)));
      }
      attempts += 1;
      if (attempts === 1) return Promise.reject(new Error("内容保存失败"));
      return Promise.resolve({ knowledge_points: [], exercises: [] });
    });

    renderPage();
    expect(await screen.findByDisplayValue("请选择班级")).toBeInTheDocument();
    fillTitle();
    addChoiceExercise();
    fireEvent.change(screen.getByDisplayValue("请选择班级"), {
      target: { value: "c1" },
    });

    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    expect(await screen.findByRole("alert", { name: "发布结果" })).toHaveTextContent(
      "草稿保存失败，已保留当前输入",
    );

    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() =>
      expect(mockedPatch).toHaveBeenCalledWith("/api/teacher/tasks/t1", {
        title: "客服语音情感标注实战",
        description: null,
        defer_content_generation: true,
      }),
    );
  });

  it("uses the content response state when a completed draft is cleared", async () => {
    const existing = {
      ...createAgentTask("t-cleared", "待清空任务"),
      content_status: "done" as const,
      content_generation_source: "manual" as const,
    };
    mockedGet.mockImplementation((path) => {
      if (path === "/api/teacher/tasks") return Promise.resolve({ items: [existing], total: 1 });
      if (path === "/api/teacher/tasks/t-cleared") return Promise.resolve(existing);
      if (path === "/api/teacher/classes") return Promise.resolve({ items: [testClass], total: 1 });
      if (path === "/api/graph/nodes") return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error("未 mock 的 GET " + String(path)));
    });
    mockedPatch.mockResolvedValue({
      ...existing,
      content_status: "done",
      content_generation_source: "manual",
      version_bumped: false,
    });
    mockedPut.mockResolvedValue({
      ...existing,
      knowledge_points: [],
      exercises: [],
      content_status: "none",
      content_generation_source: "none",
      content_generated_at: null,
      content_failure_reason: null,
      content_generation_message: null,
    });
    mockedPost.mockImplementation((path) => {
      if (path === "/api/teacher/tasks/t-cleared/content/retry") {
        return Promise.resolve({
          ...existing,
          knowledge_points: [],
          exercises: [],
          content_status: "generating",
          content_generation_source: "none",
        });
      }
      return Promise.reject(new Error("未 mock 的 POST " + String(path)));
    });

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /待清空任务/ }));
    fireEvent.click(screen.getByRole("button", { name: "删除学习内容 1" }));
    fireEvent.click(screen.getByRole("button", { name: "删除练习 1" }));
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/teacher/tasks/t-cleared/content/retry"),
    );
  });

  it("disables publishing and explains the executable-practice requirement", async () => {
    renderPage();
    expect(await screen.findByDisplayValue("请选择班级")).toBeInTheDocument();

    fillTitle();
    fireEvent.change(screen.getByDisplayValue("请选择班级"), {
      target: { value: "c1" },
    });

    const publishButton = screen.getByRole("button", { name: "发布" });
    expect(publishButton).toBeDisabled();
    expect(screen.getByText("发布前请至少添加一道可执行练习题")).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("shows safe generation failure details and can explicitly retry", async () => {
    const failedTask = {
      id: "t-failed",
      published_count: 0,
      title: "待生成任务",
      goal: "需要生成学习内容",
      description: "需要生成学习内容",
      data_type: null,
      cap_ids: [],
      steps: [],
      rubric: [],
      knowledge_points: [],
      exercises: [],
      class_id: null,
      version: 1,
      parent_task_id: null,
      status: "draft",
      content_status: "failed",
      content_generation_source: "none",
      content_failure_reason: "模型服务暂不可用",
      content_generation_message: null,
      content_generation_retry_count: 2,
      content_last_attempt_at: "2026-08-20T10:00:00Z",
      created_at: "2026-08-20T09:00:00Z",
      updated_at: "2026-08-20T10:00:00Z",
    };
    mockedGet.mockImplementation((path) => {
      if (path === "/api/teacher/tasks") return Promise.resolve({ items: [failedTask], total: 1 });
      if (path === "/api/teacher/classes") return Promise.resolve({ items: [testClass], total: 1 });
      if (path === "/api/graph/nodes") return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error("未 mock 的 GET " + String(path)));
    });
    mockedPost.mockImplementation((path) => {
      if (path === "/api/teacher/tasks/t-failed/content/retry") {
        return Promise.resolve({
          ...failedTask,
          content_status: "generating",
          content_generation_retry_count: 3,
        });
      }
      return Promise.reject(new Error("未 mock 的 POST " + String(path)));
    });

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /待生成任务/ }));

    expect(await screen.findByText("模型服务暂不可用")).toBeInTheDocument();
    expect(screen.getByText(/已重试 2 次/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试生成" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/teacher/tasks/t-failed/content/retry"),
    );
    expect(await screen.findByText("生成中")).toBeInTheDocument();
  });

  it("labels deterministic template fallback instead of presenting it as model output", async () => {
    const templateTask = {
      id: "t-template",
      published_count: 0,
      title: "模板任务",
      goal: "模板内容",
      description: "模板内容",
      data_type: null,
      cap_ids: [],
      steps: [],
      rubric: [],
      knowledge_points: [],
      exercises: [],
      class_id: null,
      version: 1,
      parent_task_id: null,
      status: "draft",
      content_status: "done",
      content_generation_source: "template",
      content_failure_reason: null,
      content_generation_message: "模型服务暂不可用，已使用本地模板补全，请审核后发布",
      content_generation_retry_count: 0,
      content_last_attempt_at: "2026-08-20T10:00:00Z",
      created_at: "2026-08-20T09:00:00Z",
      updated_at: "2026-08-20T10:00:00Z",
    };
    mockedGet.mockImplementation((path) => {
      if (path === "/api/teacher/tasks") return Promise.resolve({ items: [templateTask], total: 1 });
      if (path === "/api/teacher/classes") return Promise.resolve({ items: [testClass], total: 1 });
      if (path === "/api/graph/nodes") return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error("未 mock 的 GET " + String(path)));
    });

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /模板任务/ }));
    expect(await screen.findByText("模板兜底")).toBeInTheDocument();
    expect(screen.getByText("当前内容来自本地模板兜底，请审核后再发布。")).toBeInTheDocument();
    expect(screen.getByText("模型服务暂不可用，已使用本地模板补全，请审核后发布")).toBeInTheDocument();
  });
});
