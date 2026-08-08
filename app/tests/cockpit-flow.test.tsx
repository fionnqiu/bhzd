/**
 * 指挥舱链路测试：诊断上传 / 会话管理 / 确认门过期。
 * mock 策略与 cockpit.test.tsx 相同（共享桩见 cockpit-shared.tsx）。
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { api, ApiRequestError } from "../src/api/client";
import { ScenarioProvider } from "../src/app/ScenarioContext";
import { ToastProvider } from "../src/components";
import {
  StudentWorkbenchShellProvider,
  useStudentWorkbenchShell,
} from "../src/layouts/StudentWorkbenchShellContext";
import CockpitPage from "../src/pages/student/CockpitPage";
import {
  WorkbenchNewSession,
  WorkbenchRecentSessions,
} from "../src/pages/student/cockpit/LeftRail";
import {
  FakeRunEventStream,
  MockApiRequestError,
  installDefaultGetMock,
  latestStream,
} from "./cockpit-shared";

vi.mock("../src/api/client", async () => (await import("./cockpit-shared")).buildApiClientMock());
vi.mock("../src/api/sse", async () => (await import("./cockpit-shared")).buildSseMock());

const mockedGet = vi.mocked(api.get);
const mockedPost = vi.mocked(api.post);
const mockedDelete = vi.mocked(api.delete);
const mockedPostForm = vi.mocked(api.postForm);

function WorkbenchSidebarTestHost() {
  const {
    studentWorkbenchCloseRequest,
    conversations,
    conversationsLoading,
    conversationsError,
    refreshConversations,
    activeConversationId,
    sessionActionsDisabled,
    requestNewConversation,
    requestOpenConversation,
    removeConversation,
  } = useStudentWorkbenchShell();
  // The production StudentLayout renders this persistent rail. Focused tests
  // mount the same context-backed controls without requiring AuthContext.
  return (
    <aside>
      <WorkbenchNewSession
        busy={sessionActionsDisabled}
        onNewConversation={requestNewConversation}
      />
      <WorkbenchRecentSessions
        conversations={conversations}
        activeConversationId={activeConversationId}
        loading={conversationsLoading}
        error={conversationsError}
        onRetry={() => void refreshConversations()}
        onSelectConversation={requestOpenConversation}
        onDeleteConversation={removeConversation}
        busy={sessionActionsDisabled}
      />
      {/* This signal proves a global session action asks the compact shell to close. */}
      <output data-testid="workbench-close-request">{studentWorkbenchCloseRequest}</output>
    </aside>
  );
}

/** 与生产 Provider 组合一致的渲染 */
function renderCockpit() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <ScenarioProvider>
          <StudentWorkbenchShellProvider>
            <CockpitPage />
            <WorkbenchSidebarTestHost />
          </StudentWorkbenchShellProvider>
        </ScenarioProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
}

/** 诊断报告桩（diagnosis/engine.py 输出形状 + 路由层补的 token） */
const REPORT = {
  file_format: "coco_json",
  sample_count: 12,
  precheck: { fields: ["images", "annotations"], warnings: [] },
  errors: [
    {
      error_type: "边界溢出",
      severity: "major",
      user_value: 1024,
      expected: "<= 图像宽度",
      rule: "边界坐标不得超出图像范围",
      cap_id: "CAP-IMG-001",
      suggestion: "裁剪框边界到图像内",
    },
  ],
  severity_counts: { major: 1, minor: 2 },
  weak_cap_ids: ["CAP-IMG-001"],
  mastery_preview: [
    { cap_id: "CAP-IMG-001", scenario_id: "", delta: -0.2, old_score: 0.6, new_score: 0.4 },
  ],
  plan: {
    weak_caps: [{ cap_id: "CAP-IMG-001", cap_name: "框选边界控制" }],
    pre_path: [],
    resources: [],
    tasks: [],
  },
  notice: null,
  data_type: "image",
  scenario_id: null,
  diagnostic_token: "tok-abc",
};

beforeEach(() => {
  vi.clearAllMocks();
  FakeRunEventStream.instances = [];
  installDefaultGetMock();
  mockedPost.mockImplementation(async (path: string) => {
    if (path === "/api/runs") return { run_id: "r1", conversation_id: "c1" };
    if (path === "/api/events") return { accepted: 1 };
    if (path === "/api/diagnostics/save-summary") return { summary_id: "s1", mastery_applied: [] };
    throw new ApiRequestError(404, "NOT_FOUND", `未预期的 POST ${path}`);
  });
});

/** Uses the one real Composer path so lifecycle tests do not depend on welcome copy. */
async function submitComposerGoal(goal: string) {
  const input = await screen.findByLabelText("对话输入");
  fireEvent.change(input, { target: { value: goal } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await screen.findByTestId("chat-stream");
  await waitFor(() => expect(FakeRunEventStream.instances).toHaveLength(1));
}

describe("指挥舱 · SSE 恢复", () => {
  async function startRun() {
    renderCockpit();
    await submitComposerGoal("测试 SSE 恢复");
  }

  function installRunStatus(
    status: "running" | "waiting_confirmation" | "completed",
    recovered: {
      plan?: { steps: { id: string; title: string; status: string; tool?: string }[] } | null;
      toolCalls?: Record<string, unknown>[];
      confirmationToolCallId?: string;
    } = {},
  ) {
    mockedGet.mockImplementation(async (path: string) => {
      if (path === "/api/runs/r1") {
        return {
          run: {
            id: "r1",
            conversation_id: "c1",
            status,
            input_text: "测试 SSE 恢复",
            scenario_id: null,
            data_type: null,
            error: null,
            created_at: "2026-08-03T00:00:00Z",
            completed_at: status === "running" ? null : "2026-08-03T00:00:01Z",
          },
          plan: recovered.plan ?? null,
          tool_calls: recovered.toolCalls ?? [],
          confirmations:
            status === "waiting_confirmation"
              ? [
                  {
                    id: "conf-recovered",
                    ...(recovered.confirmationToolCallId
                      ? { tool_call_id: recovered.confirmationToolCallId }
                      : {}),
                    action_type: "task.create",
                    preview: { summary: "等待确认" },
                    status: "pending",
                    expires_at: new Date(Date.now() + 60_000).toISOString(),
                    created_at: "2026-08-03T00:00:00Z",
                  },
                ]
              : [],
          assistant_message:
            status === "completed"
              ? {
                  id: "m-recovered",
                  run_id: "r1",
                  role: "assistant",
                  content: "这是从服务端状态回查恢复的回复。",
                  created_at: "2026-08-03T00:00:01Z",
                }
              : null,
          summary: status === "completed" ? "服务端恢复的紧凑摘要。" : null,
          suggestion: null,
        };
      }
      return { items: [], total: 0 };
    });
  }

  it("stream.end 后以服务端终态恢复漏失的助手回复", async () => {
    installRunStatus("completed", {
      plan: {
        steps: [{ id: "p1", title: "定位关联能力", status: "completed", tool: "graph.reason" }],
      },
      toolCalls: [
        {
          id: "tc-recovered",
          tool: "course.search",
          permission: "read",
          status: "completed",
          execution_kind: "tool",
          input_summary: "关键词：BIO",
          output_summary: "找到 2 条课程资料",
          duration_ms: 18,
          is_write: false,
          created_at: "2026-08-03T00:00:00Z",
          completed_at: "2026-08-03T00:00:01Z",
        },
      ],
    });
    await startRun();

    act(() =>
      latestStream().emit("run.progress", {
        seq: 2,
        phase: "understanding",
        status: "running",
        title: "正在理解你的目标",
      }),
    );
    act(() =>
      latestStream().emit("run.progress", {
        seq: 3,
        phase: "planning",
        status: "running",
        title: "正在制定计划",
      }),
    );
    act(() =>
      latestStream().emit("run.progress", {
        seq: 4,
        phase: "synthesis",
        status: "running",
        activity_id: "answer:r1",
        title: "正在生成回答",
      }),
    );

    act(() => latestStream().end());

    await waitFor(() => expect(mockedGet).toHaveBeenCalledWith("/api/runs/r1"));
    expect(await screen.findByText("这是从服务端状态回查恢复的回复。")).toBeInTheDocument();
    expect(screen.queryByText("服务端恢复的紧凑摘要。")).not.toBeInTheDocument();
    expect(screen.queryByText("正在规划…")).not.toBeInTheDocument();
    expect(screen.queryByText("正在理解你的目标")).not.toBeInTheDocument();
    expect(screen.getByTestId("agent-activity-timeline")).toBeInTheDocument();
  });

  it("重试耗尽而服务端仍在运行时显示重连而不是运行失败", async () => {
    installRunStatus("running");
    await startRun();

    act(() => latestStream().exhausted());

    const recovery = await screen.findByTestId("stream-recovery");
    expect(within(recovery).getByText("实时连接已中断，任务仍在服务器运行。")).toBeInTheDocument();
    expect(screen.queryByTestId("run-failed")).not.toBeInTheDocument();
    fireEvent.click(within(recovery).getByRole("button", { name: "重新连接" }));
    await waitFor(() => expect(FakeRunEventStream.instances).toHaveLength(2));
  });

  it("回查到 waiting_confirmation 时保留确认门而不误标完成", async () => {
    installRunStatus("waiting_confirmation", {
      toolCalls: [
        {
          id: "tc-recovered",
          tool: "task.create",
          permission: "write",
          status: "awaiting_confirmation",
          execution_kind: "tool",
          input_summary: "已生成任务预览",
          output_summary: null,
          duration_ms: null,
          is_write: true,
          created_at: "2026-08-03T00:00:00Z",
          completed_at: null,
        },
      ],
      confirmationToolCallId: "tc-recovered",
    });
    await startRun();

    act(() => latestStream().end());

    expect(await screen.findByTestId("confirmation-gate")).toBeInTheDocument();
    expect(screen.queryByTestId("run-failed")).not.toBeInTheDocument();
    expect(screen.getByTestId("agent-activity-timeline")).toBeInTheDocument();
  });

  it("断流回查到确认门后，确认操作会重新订阅并接收续跑终态", async () => {
    installRunStatus("waiting_confirmation");
    mockedPost.mockImplementation(async (path: string) => {
      if (path === "/api/runs") return { run_id: "r1", conversation_id: "c1" };
      if (path === "/api/events") return { accepted: 1 };
      if (path === "/api/confirmations/conf-recovered/confirm") {
        return { status: "confirmed", result: {} };
      }
      throw new ApiRequestError(404, "NOT_FOUND", `未预期的 POST ${path}`);
    });
    await startRun();
    act(() =>
      latestStream().emit("run.progress", {
        seq: 2,
        phase: "planning",
        status: "running",
        title: "正在制定计划",
      }),
    );
    act(() => latestStream().end());

    const gate = await screen.findByTestId("confirmation-gate");
    fireEvent.click(within(gate).getByRole("button", { name: "确认" }));
    await waitFor(() => expect(FakeRunEventStream.instances).toHaveLength(2));

    act(() =>
      latestStream().emit("tool.call.requested", {
        seq: 3,
        tool_call_id: "tc-resumed",
        tool: "course.search",
        permission: "read",
      }),
    );
    expect(screen.getAllByText("正在执行课程检索").length).toBeGreaterThan(0);
    act(() => latestStream().emit("message.delta", { seq: 4, delta: "确认后的续跑回复。" }));
    act(() =>
      latestStream().emit("run.completed", {
        seq: 5,
        summary: "确认后的续跑摘要。",
      }),
    );

    expect(await screen.findByText("确认后的续跑回复。")).toBeInTheDocument();
    expect(screen.queryByText("确认后的续跑摘要。")).not.toBeInTheDocument();
    expect(screen.getByTestId("agent-activity-timeline")).toBeInTheDocument();
    expect(screen.getByTestId("agent-current-action")).toHaveAttribute("aria-expanded", "false");
  });
});

describe("指挥舱 · 内嵌输入操作", () => {
  it("把上传和发送操作放在对话输入的同一视觉壳层中", async () => {
    renderCockpit();

    const shell = await screen.findByTestId("composer-input-shell");
    expect(within(shell).getByLabelText("对话输入")).toBeInTheDocument();
    expect(within(shell).getByRole("button", { name: "上传诊断文件" })).toBeInTheDocument();
    expect(within(shell).getByRole("button", { name: "发送" })).toBeInTheDocument();
  });

  it("点击内嵌上传按钮仍打开原有文件选择器", async () => {
    renderCockpit();

    const fileInput = await screen.findByLabelText("上传标注结果文件");
    const openPicker = vi.spyOn(fileInput, "click");
    fireEvent.click(screen.getByRole("button", { name: "上传诊断文件" }));

    expect(openPicker).toHaveBeenCalledOnce();
    openPicker.mockRestore();
  });

  it("点击内嵌发送按钮仍提交去空白后的目标并清空文本框", async () => {
    renderCockpit();

    const input = await screen.findByLabelText("对话输入");
    fireEvent.change(input, { target: { value: "  生成一个文本标注练习  " } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/runs",
        expect.objectContaining({ input: "生成一个文本标注练习" }),
      ),
    );
    // Sending moves the same Composer from the welcome scroller to the
    // conversation footer, so assert against its mounted post-submit node.
    expect(await screen.findByLabelText("对话输入")).toHaveValue("");
  });

  it("运行中按 Enter 不会绕过内嵌发送按钮的禁用状态", async () => {
    renderCockpit();

    await submitComposerGoal("运行中的学习目标");
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/runs",
        expect.objectContaining({ input: "运行中的学习目标" }),
      ),
    );

    // The activity timeline owns long-running feedback; the send control stays
    // disabled for concurrency safety without replacing its icon with a spinner.
    const sendButton = screen.getByRole("button", { name: "发送" });
    expect(sendButton).toBeDisabled();
    expect(sendButton).toHaveAttribute("aria-busy", "true");
    expect(sendButton.querySelector(".spinner")).toBeNull();

    const input = screen.getByLabelText("对话输入");
    fireEvent.change(input, { target: { value: "不应并发提交" } });
    fireEvent.keyDown(input, { key: "Enter" });

    const runCalls = mockedPost.mock.calls.filter(([path]) => path === "/api/runs");
    expect(runCalls).toHaveLength(1);
  });
});

describe("指挥舱 · 诊断上传", () => {
  it("欢迎态和诊断报告位于独立滚动区，Hero Composer 保持在欢迎内容内", async () => {
    mockedPostForm.mockResolvedValue(REPORT);
    renderCockpit();

    const scrollRegion = await screen.findByTestId("cockpit-scroll-region");
    const composer = screen.getByTestId("composer");
    const welcome = screen.getByTestId("cockpit-welcome");
    expect(scrollRegion).toContainElement(welcome);
    expect(scrollRegion).toContainElement(composer);
    expect(welcome).toContainElement(composer);

    const fileInput = screen.getByLabelText("上传标注结果文件");
    fireEvent.change(fileInput, {
      target: { files: [new File(["{}"], "result.json", { type: "application/json" })] },
    });

    const report = await screen.findByTestId("diagnostic-report");
    expect(scrollRegion).toContainElement(report);
    expect(scrollRegion).toContainElement(screen.getByTestId("composer"));
  });

  it("会话开始后将 Composer 移到独立的对话底部", async () => {
    renderCockpit();
    await submitComposerGoal("把 Composer 放到对话底部");

    const scrollRegion = screen.getByTestId("cockpit-scroll-region");
    const composer = screen.getByTestId("composer");
    expect(scrollRegion).toContainElement(screen.getByTestId("chat-stream"));
    expect(scrollRegion).not.toContainElement(composer);
    expect(composer.previousElementSibling).toBe(scrollRegion);
    expect(composer).toHaveClass("composer-default");
  });

  it("上传 → 报告卡内联展示；保存摘要经确认弹窗（含掌握度 old→new）", async () => {
    mockedPostForm.mockResolvedValue(REPORT);
    renderCockpit();

    const fileInput = await screen.findByLabelText("上传标注结果文件");
    fireEvent.change(fileInput, {
      target: { files: [new File(["{}"], "result.json", { type: "application/json" })] },
    });

    const card = await screen.findByTestId("diagnostic-report");
    expect(within(card).getByText("格式 coco_json")).toBeInTheDocument();
    expect(within(card).getByText("严重 1")).toBeInTheDocument();
    expect(within(card).getByText("边界溢出")).toBeInTheDocument();
    expect(within(card).getByText(/框选边界控制/)).toBeInTheDocument();

    // 保存前必须出现确认弹窗，且展示 mastery_preview old→new（PRD-01 §7 验收）
    fireEvent.click(within(card).getByRole("button", { name: "保存诊断摘要" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/CAP-IMG-001：60% → 40%/)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/diagnostics/save-summary", {
        diagnostic_token: "tok-abc",
      }),
    );
    await screen.findByText("诊断摘要已保存，掌握度已更新");
  });

  it("生成补强计划 → 以 attachment 携带 diagnostic_token 发起运行", async () => {
    mockedPostForm.mockResolvedValue(REPORT);
    renderCockpit();
    const fileInput = await screen.findByLabelText("上传标注结果文件");
    fireEvent.change(fileInput, {
      target: { files: [new File(["{}"], "result.json", { type: "application/json" })] },
    });
    const card = await screen.findByTestId("diagnostic-report");

    fireEvent.click(within(card).getByRole("button", { name: "生成补强计划" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/runs",
        expect.objectContaining({
          input: "根据刚才的诊断结果生成补强计划",
          attachment: { diagnostic_token: "tok-abc" },
        }),
      ),
    );
    // runs.py RunCreate.attachment 受支持 → 编排器从 seed plan 读取 token
    await waitFor(() => expect(FakeRunEventStream.instances.length).toBeGreaterThan(0));
    expect(latestStream().runId).toBe("r1");
  });

  it("非法文件类型 → 中文错误提示，不发请求", async () => {
    renderCockpit();
    const fileInput = await screen.findByLabelText("上传标注结果文件");
    fireEvent.change(fileInput, {
      target: { files: [new File(["x"], "notes.txt", { type: "text/plain" })] },
    });
    expect(
      await screen.findByText("仅支持 JSON / TextGrid / VOC XML 标注文件"),
    ).toBeInTheDocument();
    expect(mockedPostForm).not.toHaveBeenCalled();
  });
});

describe("指挥舱 · 会话管理", () => {
  const CONVERSATION = {
    id: "c9",
    title: "旧会话",
    scenario_id: null,
    data_type: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-02T00:00:00Z",
  };

  function mockConversationApis() {
    mockedGet.mockImplementation(async (path: string) => {
      if (path === "/api/presets") return { items: [], total: 0 };
      if (path === "/api/tasks") return { items: [], total: 0 };
      if (path === "/api/profile/mastery") return { items: [], total: 0 };
      if (path === "/api/conversations") return { items: [CONVERSATION], total: 1 };
      if (path === "/api/conversations/c9")
        return {
          ...CONVERSATION,
          messages: [
            { id: "m1", run_id: "r0", role: "user", content: "我想学 NER", created_at: "" },
            {
              id: "m2",
              run_id: "r0",
              role: "assistant",
              content: "好的，先看规范。",
              created_at: "",
            },
            {
              id: "m3",
              run_id: "r0",
              role: "tool",
              content: "工具内部摘要不应展示",
              created_at: "",
            },
          ],
        };
      throw new ApiRequestError(404, "NOT_FOUND", `未预期的 GET ${path}`);
    });
  }

  it("点击历史会话 → 载入消息（tool 消息隐藏）；新会话回到欢迎态", async () => {
    mockConversationApis();
    renderCockpit();

    expect(screen.getByTestId("workbench-close-request")).toHaveTextContent("0");
    fireEvent.click(await screen.findByText("旧会话"));
    expect(await screen.findByText("我想学 NER")).toBeInTheDocument();
    expect(screen.getByText("好的，先看规范。")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("workbench-close-request")).toHaveTextContent("1"),
    );
    expect(screen.queryByText("工具内部摘要不应展示")).not.toBeInTheDocument();
    // Legacy conversations have no persisted learner-visible event projection.
    // Keep the transcript honest instead of manufacturing a completed activity.
    expect(screen.queryByTestId("agent-activity-timeline")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /新建会话/ }));
    expect(await screen.findByTestId("cockpit-welcome")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("workbench-close-request")).toHaveTextContent("2"),
    );
  });

  it("运行中锁定新会话、历史切换和删除，不能关闭当前 SSE", async () => {
    mockConversationApis();
    renderCockpit();

    const input = await screen.findByLabelText("对话输入");
    fireEvent.change(input, { target: { value: "运行中的学习目标" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(FakeRunEventStream.instances).toHaveLength(1));

    const newSession = screen.getByRole("button", { name: /新建会话/ });
    const historySession = screen.getByText("旧会话").closest("button");
    expect(newSession).toBeDisabled();
    expect(historySession).toBeDisabled();
    expect(screen.getByLabelText("删除会话 旧会话")).toBeDisabled();

    // A disabled rail action must leave the active stream and transcript intact.
    fireEvent.click(newSession);
    expect(latestStream().closed).toBe(false);
    expect(screen.getByTestId("chat-stream")).toBeInTheDocument();
  });

  it("创建运行后刷新最近会话列表", async () => {
    const createdConversation = { ...CONVERSATION, id: "c1", title: "新运行会话" };
    let conversationListCalls = 0;
    mockedGet.mockImplementation(async (path: string) => {
      if (path === "/api/presets" || path === "/api/profile/mastery") {
        return { items: [], total: 0 };
      }
      if (path === "/api/conversations") {
        conversationListCalls += 1;
        return conversationListCalls > 1
          ? { items: [createdConversation], total: 1 }
          : { items: [], total: 0 };
      }
      throw new ApiRequestError(404, "NOT_FOUND", `未预期的 GET ${path}`);
    });
    renderCockpit();

    const input = await screen.findByLabelText("对话输入");
    fireEvent.change(input, { target: { value: "创建一个新会话" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(FakeRunEventStream.instances).toHaveLength(1));

    await waitFor(() =>
      expect(
        within(screen.getByTestId("cockpit-conversation-panel")).getByText("新运行会话"),
      ).toBeInTheDocument(),
    );
    expect(conversationListCalls).toBeGreaterThanOrEqual(2);
  });

  it("历史活动显示在对应回复上方，默认折叠且继续保护敏感值", async () => {
    mockedGet.mockImplementation(async (path: string) => {
      if (path === "/api/presets") return { items: [], total: 0 };
      if (path === "/api/tasks") return { items: [], total: 0 };
      if (path === "/api/profile/mastery") return { items: [], total: 0 };
      if (path === "/api/conversations") return { items: [CONVERSATION], total: 1 };
      if (path === "/api/conversations/c9") {
        return {
          ...CONVERSATION,
          messages: [
            { id: "m1", run_id: "r-old", role: "user", content: "旧问题", created_at: "" },
            {
              id: "m2",
              run_id: "r-old",
              role: "assistant",
              content: "旧回答",
              created_at: "",
            },
            { id: "m3", run_id: "r-new", role: "user", content: "新问题", created_at: "" },
            {
              id: "m4",
              run_id: "r-new",
              role: "assistant",
              content: "新回答",
              created_at: "",
            },
            {
              id: "m5",
              run_id: "r-hidden",
              role: "assistant",
              content: "没有可见步骤的回答",
              created_at: "",
            },
          ],
          activities_by_run: {
            "r-old": [
              {
                seq: 2,
                event_seq: 3,
                activity_id: "history-answer:r-old",
                stage: "responding",
                status: "completed",
                message: "回答已生成",
              },
            ],
            "r-new": [
              {
                seq: 1,
                event_seq: 1,
                activity_id: "history-understanding:r-new",
                stage: "understanding",
                status: "completed",
                message: "旧会话的思考摘要不应展示",
              },
              {
                seq: 2,
                event_seq: 3,
                tool_call_id: "tool-1",
                stage: "tool",
                status: "completed",
                message: "课程检索已完成",
                tool: "course.search",
                duration_ms: 18,
                is_write: false,
              },
              {
                seq: 4,
                event_seq: 5,
                activity_id: "answer:r-new",
                stage: "responding",
                status: "completed",
                message: "回答已生成",
                detail: "token=history-secret",
              },
            ],
            "r-hidden": [
              {
                seq: 1,
                stage: "tool",
                status: "completed",
                message: "不应展示的资料召回",
                tool: "rag.search",
              },
              {
                seq: 2,
                stage: "planning",
                status: "completed",
                message: "不应展示的固定规划",
              },
            ],
          },
        };
      }
      throw new ApiRequestError(404, "NOT_FOUND", `未预期的 GET ${path}`);
    });
    renderCockpit();

    fireEvent.click(await screen.findByText("旧会话"));
    await screen.findByText("新回答");

    expect(screen.getByText("旧回答")).toBeInTheDocument();
    expect(screen.getByText("新回答")).toBeInTheDocument();
    const historicalTimelines = screen.getAllByTestId("agent-activity-timeline");
    expect(historicalTimelines).toHaveLength(3);
    for (const timeline of historicalTimelines) {
      expect(within(timeline).getByTestId("agent-current-action")).toHaveAttribute(
        "aria-expanded",
        "false",
      );
    }
    expect(screen.queryByText("旧会话的思考摘要不应展示")).not.toBeInTheDocument();
    expect(screen.queryByText("history-secret")).not.toBeInTheDocument();
  });

  it("删除会话 → 确认弹窗后 DELETE 并刷新列表", async () => {
    mockConversationApis();
    mockedDelete.mockResolvedValue({ deleted: true });
    renderCockpit();

    fireEvent.click(await screen.findByLabelText("删除会话 旧会话"));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "删除" }));
    await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith("/api/conversations/c9"));
  });
});

describe("指挥舱 · 确认门过期", () => {
  it("倒计时到期自动 POST expire，关闭确认门并恢复输入", async () => {
    mockedPost.mockImplementation(async (path: string) => {
      if (path === "/api/runs") return { run_id: "r1", conversation_id: "c1" };
      if (path === "/api/events") return { accepted: 1 };
      if (path === "/api/confirmations/conf-expired/expire") {
        return {
          status: "expired",
          summary: "预览已过期，未做任何修改，请重新发起操作。",
        };
      }
      throw new ApiRequestError(404, "NOT_FOUND", `未预期的 POST ${path}`);
    });
    renderCockpit();
    await submitComposerGoal("确认门过期测试");

    // Use a past ISO timestamp rather than fake timers: it exercises the same
    // countdown-to-hook path that runs after a real browser timer reaches zero.
    act(() =>
      latestStream().emit("confirmation.required", {
        seq: 2,
        confirmation: {
          id: "conf-expired",
          action_type: "task.create",
          status: "pending",
          expires_at: new Date(Date.now() - 1_000).toISOString(),
          created_at: new Date().toISOString(),
          preview: { action: "task.create", summary: "将创建学习任务" },
        },
      }),
    );

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/confirmations/conf-expired/expire",
        {},
        expect.objectContaining({ signal: expect.anything() }),
      ),
    );
    // The expired run keeps its state transition but must not restore a result summary card.
    expect(
      screen.queryByText("预览已过期，未做任何修改，请重新发起操作。"),
    ).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByTestId("confirmation-gate")).not.toBeInTheDocument());
    expect(screen.getByTestId("agent-activity-timeline")).toBeInTheDocument();
    // Terminal status removes `sending`, so the next goal can be submitted.
    fireEvent.change(screen.getByLabelText("对话输入"), {
      target: { value: "生成一个新的学习任务" },
    });
    expect(screen.getByRole("button", { name: "发送" })).not.toBeDisabled();
  });

  it("另一标签页发来的终态 SSE 也会移除本地确认卡", async () => {
    renderCockpit();
    await submitComposerGoal("另一标签页终态测试");
    act(() =>
      latestStream().emit("confirmation.required", {
        seq: 2,
        confirmation: {
          id: "conf-other-tab",
          action_type: "task.create",
          status: "pending",
          expires_at: new Date(Date.now() + 1800_000).toISOString(),
          created_at: new Date().toISOString(),
          preview: { action: "task.create", summary: "将创建学习任务" },
        },
      }),
    );
    expect(await screen.findByTestId("confirmation-gate")).toBeInTheDocument();
    act(() =>
      latestStream().emit("run.completed", {
        seq: 3,
        summary: "预览已过期，未做任何修改，请重新发起操作。",
      }),
    );
    await waitFor(() => expect(screen.queryByTestId("confirmation-gate")).not.toBeInTheDocument());
  });

  it("confirm 410 → toast 提示 + 刷新 run 状态", async () => {
    mockedPost.mockImplementation(async (path: string) => {
      if (path === "/api/runs") return { run_id: "r1", conversation_id: "c1" };
      if (path === "/api/events") return { accepted: 1 };
      if (path === "/api/confirmations/conf-1/confirm")
        throw new ApiRequestError(
          410,
          "CONFIRMATION_EXPIRED",
          "确认已过期，请重新生成预览后再确认",
        );
      throw new ApiRequestError(404, "NOT_FOUND", `未预期的 POST ${path}`);
    });
    renderCockpit();
    await submitComposerGoal("确认过期测试");

    act(() =>
      latestStream().emit("confirmation.required", {
        seq: 2,
        confirmation: {
          id: "conf-1",
          action_type: "task.create",
          status: "pending",
          expires_at: new Date(Date.now() + 1800_000).toISOString(),
          created_at: new Date().toISOString(),
          preview: { action: "task.create", summary: "将创建学习任务" },
        },
      }),
    );
    const gate = await screen.findByTestId("confirmation-gate");
    fireEvent.click(within(gate).getByRole("button", { name: "确认" }));

    expect(await screen.findByText("预览已过期，请重新生成")).toBeInTheDocument();
    // 过期后刷新 run（GET /api/runs/r1），确认门随之关闭
    await waitFor(() => expect(mockedGet).toHaveBeenCalledWith("/api/runs/r1"));
    await waitFor(() => expect(screen.queryByTestId("confirmation-gate")).not.toBeInTheDocument());
  });
});

describe("指挥舱 · 确认门终态收敛", () => {
  it("服务端尚未到期的 409 会重试并最终关闭确认门", async () => {
    let expireAttempts = 0;
    mockedPost.mockImplementation(async (path: string) => {
      if (path === "/api/runs") return { run_id: "r1", conversation_id: "c1" };
      if (path === "/api/events") return { accepted: 1 };
      if (path === "/api/confirmations/conf-clock-skew/expire") {
        expireAttempts += 1;
        if (expireAttempts === 1) {
          throw new ApiRequestError(409, "CONFIRMATION_NOT_EXPIRED", "确认单尚未过期");
        }
        return {
          status: "expired",
          summary: "预览已过期，未做任何修改，请重新发起操作。",
        };
      }
      throw new ApiRequestError(404, "NOT_FOUND", `未预期的 POST ${path}`);
    });

    renderCockpit();
    await submitComposerGoal("确认时钟偏差测试");
    act(() =>
      latestStream().emit("confirmation.required", {
        seq: 2,
        confirmation: {
          id: "conf-clock-skew",
          action_type: "task.create",
          status: "pending",
          // A past browser deadline simulates a client clock ahead of the server.
          expires_at: new Date(Date.now() - 1_000).toISOString(),
          created_at: new Date().toISOString(),
          preview: { action: "task.create", summary: "将创建学习任务" },
        },
      }),
    );

    await waitFor(() => expect(expireAttempts).toBe(1));
    await waitFor(() => expect(expireAttempts).toBe(2), { timeout: 2_500 });
    await waitFor(() => expect(screen.queryByTestId("confirmation-gate")).not.toBeInTheDocument());
  });

  it("run.failed 会清除过期确认门而不是保留可点击的旧预览", async () => {
    renderCockpit();
    await submitComposerGoal("确认失败测试");
    act(() =>
      latestStream().emit("confirmation.required", {
        seq: 2,
        confirmation: {
          id: "conf-failed",
          action_type: "task.create",
          status: "pending",
          expires_at: new Date(Date.now() + 1_800_000).toISOString(),
          created_at: new Date().toISOString(),
          preview: { action: "task.create", summary: "将创建学习任务" },
        },
      }),
    );
    expect(await screen.findByTestId("confirmation-gate")).toBeInTheDocument();

    act(() =>
      latestStream().emit("run.failed", {
        seq: 3,
        error: "确认的操作执行失败，请稍后重试",
      }),
    );
    expect(await screen.findByTestId("run-failed")).toBeInTheDocument();
    expect(screen.queryByTestId("confirmation-gate")).not.toBeInTheDocument();
  });
});

describe("cockpit reconciliation retry", () => {
  it("retries a transient run-state GET failure and restores the terminal reply", async () => {
    async function startRun() {
      renderCockpit();
      const input = await screen.findByLabelText("\u5bf9\u8bdd\u8f93\u5165");
      fireEvent.change(input, { target: { value: "test" } });
      fireEvent.click(screen.getByRole("button", { name: "\u53d1\u9001" }));
      await waitFor(() => expect(FakeRunEventStream.instances).toHaveLength(1));
    }

    const completedRun = {
      run: {
        id: "r1",
        conversation_id: "c1",
        status: "completed",
        input_text: "test",
        scenario_id: null,
        data_type: null,
        error: null,
        created_at: "2026-08-03T00:00:00Z",
        completed_at: "2026-08-03T00:00:01Z",
      },
      plan: null,
      tool_calls: [],
      confirmations: [],
      assistant_message: {
        id: "m-recovered",
        run_id: "r1",
        role: "assistant",
        content:
          "\u8fd9\u662f\u4ece\u670d\u52a1\u7aef\u72b6\u6001\u56de\u67e5\u6062\u590d\u7684\u56de\u590d\u3002",
        created_at: "2026-08-03T00:00:01Z",
      },
    };
    let attempts = 0;
    mockedGet.mockImplementation(async (path: string) => {
      if (path === "/api/presets") return { items: [], total: 0 };
      if (path === "/api/tasks") return { items: [], total: 0 };
      if (path === "/api/conversations") return { items: [], total: 0 };
      if (path === "/api/profile/mastery") return { items: [], total: 0 };
      if (path === "/api/runs/r1") {
        attempts += 1;
        if (attempts === 1) {
          throw new MockApiRequestError(
            0,
            "NETWORK_ERROR",
            "\u7f51\u7edc\u8fde\u63a5\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5\u7f51\u7edc\u540e\u91cd\u8bd5",
          );
        }
        return completedRun;
      }
      throw new MockApiRequestError(404, "NOT_FOUND", `unexpected GET ${path}`);
    });

    await startRun();
    act(() => latestStream().exhausted());

    expect(
      await screen.findByText(
        "\u8fd9\u662f\u4ece\u670d\u52a1\u7aef\u72b6\u6001\u56de\u67e5\u6062\u590d\u7684\u56de\u590d\u3002",
        undefined,
        { timeout: 2500 },
      ),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("stream-recovery")).not.toBeInTheDocument();
    expect(attempts).toBe(2);
  });
});
