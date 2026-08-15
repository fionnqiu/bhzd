/**
 * 指挥舱测试（PRD-01 §3.6 验收驱动）：欢迎态 + SSE 事件流全链路。
 * mock 策略：api 桩（按 path 分派）+ FakeRunEventStream 播放事件帧（见 cockpit-shared）。
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { api, ApiRequestError } from "../src/api/client";
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
  installDefaultGetMock,
  latestStream,
  waitForStream,
} from "./cockpit-shared";

vi.mock("../src/api/client", async () => (await import("./cockpit-shared")).buildApiClientMock());
vi.mock("../src/api/sse", async () => (await import("./cockpit-shared")).buildSseMock());

const mockedPost = vi.mocked(api.post);

function WorkbenchSidebarTestHost() {
  const {
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
  // mount the same context-backed controls without AuthContext.
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
    </aside>
  );
}

/** 与生产 Provider 组合一致的渲染（页面用 Link/useToast） */
function renderCockpit() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <StudentWorkbenchShellProvider>
          {/* Mirror ShellLayout's route-level scroll owner so streaming tests
              exercise the same page surface as the production workbench. */}
          <main className="main-content student-workbench-main-content student-workbench-cockpit-main-content">
            <CockpitPage />
          </main>
          <WorkbenchSidebarTestHost />
        </StudentWorkbenchShellProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
}

function emit(type: string, payload: Record<string, unknown>) {
  act(() => latestStream().emit(type, payload));
}

beforeEach(() => {
  vi.clearAllMocks();
  FakeRunEventStream.instances = [];
  installDefaultGetMock();
  mockedPost.mockImplementation(async (path: string) => {
    if (path === "/api/runs") return { run_id: "r1", conversation_id: "c1" };
    if (path === "/api/events") return { accepted: 1 };
    throw new ApiRequestError(404, "NOT_FOUND", `未预期的 POST ${path}`);
  });
});

const TEST_RUN_GOAL = "请生成一份文本标注练习计划";

describe("指挥舱 · 欢迎态", () => {
  it("渲染五个快捷入口，并把 Hero Composer 放在欢迎滚动内容内", async () => {
    renderCockpit();

    const scrollRegion = await screen.findByTestId("cockpit-scroll-region");
    const welcome = screen.getByTestId("cockpit-welcome");
    const composer = screen.getByTestId("composer");
    const quickLinks = document.querySelector<HTMLElement>(".welcome-quick-actions");

    expect(quickLinks).not.toBeNull();
    expect(within(quickLinks!).getAllByRole("button")).toHaveLength(5);
    for (const label of ["文本标注", "图像标注", "结果诊断", "薄弱补强", "规范问答"]) {
      expect(within(quickLinks!).getByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(scrollRegion).toContainElement(welcome);
    expect(welcome).toContainElement(composer);
    expect(composer).toHaveClass("composer-hero");
  });

  it("文本快捷入口只预填并聚焦 Composer，不会在用户确认前启动运行", async () => {
    renderCockpit();

    const input = await screen.findByLabelText("对话输入");
    fireEvent.click(screen.getByRole("button", { name: "文本标注" }));

    await waitFor(() => expect(input).toHaveValue("我想学习文本标注入门"));
    expect(input).toHaveFocus();
    expect(mockedPost.mock.calls.filter(([path]) => path === "/api/runs")).toHaveLength(0);
    expect(mockedPost).toHaveBeenCalledWith("/api/events", {
      events: [{ name: "preset_clicked", props: { preset_id: "text-intro", source: "welcome" } }],
    });
  });

  it("诊断快捷入口打开专用诊断选择器，不会启动 Agent 运行", async () => {
    renderCockpit();

    const fileInput = await screen.findByLabelText("上传诊断文件");
    const openPicker = vi.spyOn(fileInput, "click");
    fireEvent.click(screen.getByRole("button", { name: "结果诊断" }));

    expect(openPicker).toHaveBeenCalledOnce();
    expect(mockedPost.mock.calls.filter(([path]) => path === "/api/runs")).toHaveLength(0);
    openPicker.mockRestore();
  });

  it("用户从 Composer 提交目标时打开事件流", async () => {
    renderCockpit();
    const input = await screen.findByLabelText("对话输入");
    fireEvent.change(input, { target: { value: TEST_RUN_GOAL } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await screen.findByTestId("chat-stream");
    // The pre-answer state is the same bounded lifecycle summary used by the
    // execution record; no standalone thinking widget is rendered.
    const executionRecord = await screen.findByTestId("agent-activity-timeline");
    expect(within(executionRecord).getByTestId("agent-current-action")).toHaveTextContent(
      /执行计划|正在整理学习目标|正在准备练习内容/,
    );
    expect(within(executionRecord).getByTestId("agent-current-action")).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.queryByTestId("agent-thinking-state")).not.toBeInTheDocument();
    const conversationInfo = screen.getByRole("status", { name: "当前对话信息" });
    expect(conversationInfo).toHaveTextContent("学习会话");
    expect(conversationInfo).toHaveClass("conversation-info-bar", "conversation-heading");
    // The transcript may scroll independently, while the active Composer must
    // remain its sibling so a long history cannot scroll the input away.
    const scrollRegion = screen.getByTestId("cockpit-scroll-region");
    const composer = screen.getByTestId("composer");
    const contentInner = screen.getByTestId("cockpit-content-inner");
    expect(scrollRegion).not.toContainElement(conversationInfo);
    expect(conversationInfo.parentElement).toBe(scrollRegion.parentElement?.parentElement);
    expect(conversationInfo.parentElement).not.toBe(scrollRegion.parentElement);
    expect(scrollRegion).not.toContainElement(composer);
    expect(composer.parentElement).toBe(scrollRegion.parentElement);
    // The scroll region wraps the message stack; the inner stack is layout-only
    // so a long transcript cannot create a second scrollbar in the middle box.
    expect(scrollRegion).toContainElement(contentInner);
    expect(contentInner).toContainElement(screen.getByTestId("chat-stream"));
    expect(composer.querySelector("svg.lucide-folder-open")).toBeNull();
    await waitForStream();
    expect(mockedPost).toHaveBeenCalledWith(
      "/api/runs",
      expect.objectContaining({
        input: TEST_RUN_GOAL,
      }),
    );
    expect(latestStream().runId).toBe("r1");
  });
});

describe("指挥舱 · 运行事件流", () => {
  async function startRun() {
    renderCockpit();
    const input = await screen.findByLabelText("对话输入");
    fireEvent.change(input, { target: { value: TEST_RUN_GOAL } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByTestId("chat-stream");
    await waitForStream();
  }

  it("plan.updated 在处理面板展示受控执行清单", async () => {
    await startRun();
    emit("plan.updated", {
      seq: 2,
      steps: [
        { id: "s1", title: "召回标注规范资料", tool: "rag.search", status: "completed" },
        { id: "s2", title: "基于资料生成回答", tool: "rag.answer", status: "pending" },
        { id: "s3", title: "定位关联能力", tool: "graph.reason", status: "pending" },
      ],
    });
    // Later plan frames refresh the same learner-visible execution record.
    emit("plan.updated", {
      seq: 3,
      steps: [
        { id: "s1", title: "召回标注规范资料", tool: "rag.search", status: "completed" },
        { id: "s2", title: "基于资料生成回答", tool: "rag.answer", status: "pending" },
        { id: "s3", title: "定位关联能力", tool: "graph.reason", status: "running" },
      ],
    });

    expect(screen.getByTestId("agent-activity-timeline")).toBeInTheDocument();
    expect(screen.getByTestId("execution-plan")).toHaveTextContent("召回标注规范资料");
    expect(screen.getByTestId("execution-plan")).toHaveTextContent("定位关联能力");
  });

  it("执行事件显示受控阶段，但不泄露内部思考或参数", async () => {
    await startRun();
    expect(screen.getByTestId("agent-activity-timeline")).toBeInTheDocument();
    emit("run.started", { seq: 1 });
    emit("run.progress", {
      seq: 2,
      phase: "understanding",
      status: "running",
      title: "正在理解你的目标",
    });
    emit("run.progress", {
      seq: 3,
      phase: "planning",
      status: "running",
      title: "正在制定学习计划",
      detail: "会先梳理学习目标，再匹配练习路径",
    });
    // Deliberately emit a larger sequence first to prove the reducer keeps the
    // persisted-event order rather than the browser callback order.
    emit("rag.retrieval.started", { seq: 5 });
    emit("tool.call.requested", {
      seq: 4,
      tool_call_id: "tc-safe-summary",
      tool: "course.search",
      permission: "read",
      args_summary: "关键词：BIO；token=top-secret",
    });
    emit("run.progress", {
      seq: 6,
      phase: "synthesis",
      status: "running",
      activity_id: "answer:r1",
      title: "正在生成最终回复",
    });
    emit("run.progress", {
      seq: 3,
      phase: "planning",
      status: "running",
      title: "这条重放不应重复显示",
    });
    emit("run.progress", {
      seq: 7,
      phase: "synthesis",
      status: "completed",
      activity_id: "answer:r1",
      title: "回答已生成",
    });

    expect(screen.getByTestId("agent-activity-timeline")).toBeInTheDocument();
    expect(screen.getByTestId("agent-current-action")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("正在制定学习计划")).toBeInTheDocument();
    expect(screen.queryByText("关键词：BIO")).not.toBeInTheDocument();
    expect(screen.queryByText("top-secret")).not.toBeInTheDocument();
  });

  it("终态默认展开安全处理过程面板", async () => {
    await startRun();
    emit("run.started", { seq: 1 });
    emit("run.progress", {
      seq: 2,
      phase: "synthesis",
      status: "running",
      activity_id: "answer:r1",
      title: "正在生成回答",
    });
    emit("run.completed", { seq: 3, summary: "已完成本次处理。" });

    expect(screen.getByTestId("agent-activity-timeline")).toBeInTheDocument();
    const summary = screen.getByTestId("agent-current-action");
    expect(summary).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("agent-activity-history")).toBeInTheDocument();
    expect(summary).toHaveTextContent("处理完成");

    fireEvent.click(summary);
    expect(summary).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("agent-activity-history")).not.toBeInTheDocument();
  });

  it("RAG 生命周期显示安全检索摘要，不显示思考原文", async () => {
    await startRun();
    emit("run.progress", {
      seq: 1,
      phase: "understanding",
      status: "running",
      title: "正在理解你的目标",
    });
    emit("run.progress", {
      seq: 2,
      phase: "retrieval",
      status: "running",
      title: "不应展示的资料检索进度",
    });

    emit("rag.retrieval.started", { seq: 3 });
    emit("rag.retrieval.completed", { seq: 4, hit_count: 0, latency_ms: 1 });
    expect(screen.getByTestId("agent-activity-timeline")).toHaveTextContent("资料检索完成");
    expect(screen.getByTestId("agent-activity-timeline")).toHaveTextContent(
      "命中 0 条资料，耗时 1 ms",
    );
    // A row owns its status beside the stage label. Keeping only two direct
    // children prevents completed labels from reforming a detached right column.
    const retrievalRow = document.querySelector<HTMLElement>(".agent-activity-row-retrieval");
    if (!retrievalRow) throw new Error("retrieval activity row must be visible after expansion");
    expect(retrievalRow.children).toHaveLength(2);
    expect(
      retrievalRow.querySelector(".agent-activity-row-primary .agent-activity-status"),
    ).toHaveTextContent("已完成");
    expect(screen.queryByText("正在理解你的目标")).not.toBeInTheDocument();
    emit("run.progress", {
      seq: 5,
      phase: "synthesis",
      status: "running",
      activity_id: "answer:r1",
      title: "正在生成回答",
    });
    expect(screen.getByTestId("agent-activity-timeline")).toBeInTheDocument();
  });

  it("message.delta → 流式助手气泡增量拼接", async () => {
    await startRun();
    emit("message.delta", { seq: 2, delta: "BIO 边界按" });
    emit("message.delta", { seq: 3, delta: "实体起始与延续划分。" });
    expect(await screen.findByText("BIO 边界按实体起始与延续划分。")).toBeInTheDocument();
    expect(screen.getByTestId("agent-activity-timeline")).toBeInTheDocument();
  });

  it("流式增量在读者位于底部时继续跟随，不依赖消息条数变化", async () => {
    const getComputedStyleSpy = vi.spyOn(window, "getComputedStyle").mockReturnValue({
      overflowY: "auto",
      // The scroll helper also reads CSS custom properties from the style declaration.
      getPropertyValue: () => "",
    } as unknown as CSSStyleDeclaration);
    const originalScrollIntoView = Element.prototype.scrollIntoView;
    const scrollIntoView = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });

    try {
      await startRun();
      // The transcript owns the scroll surface; the Composer remains outside it.
      const scrollRegion = document.querySelector<HTMLElement>(".cockpit-content-scroll");
      expect(scrollRegion).not.toBeNull();
      Object.defineProperties(scrollRegion!, {
        clientHeight: { configurable: true, value: 200 },
        scrollHeight: { configurable: true, value: 1_000 },
      });
      Object.defineProperty(scrollRegion!, "scrollTop", { configurable: true, value: 800 });
      fireEvent.scroll(scrollRegion!);
      scrollIntoView.mockClear();

      emit("message.delta", { seq: 2, delta: "第一段" });
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());
      scrollIntoView.mockClear();

      // The second delta updates the existing assistant bubble in place, which
      // used to leave the transcript parked above the newest generated text.
      emit("message.delta", { seq: 3, delta: "第二段" });
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledOnce());
    } finally {
      getComputedStyleSpy.mockRestore();
      Object.defineProperty(Element.prototype, "scrollIntoView", {
        configurable: true,
        value: originalScrollIntoView,
      });
    }
  });

  it("模型分片保留在回答气泡，处理面板同步生成阶段", async () => {
    await startRun();
    emit("run.progress", {
      seq: 1,
      phase: "synthesis",
      status: "running",
      activity_id: "answer:r1",
      title: "正在生成回答",
    });
    emit("message.delta", { seq: 2, delta: "第一段" });
    emit("message.delta", { seq: 3, delta: "第二段" });

    expect(await screen.findByText("第一段第二段")).toBeInTheDocument();
    expect(screen.getByTestId("agent-activity-timeline")).toHaveTextContent("正在生成回答");
  });

  it("工具安全摘要会隐藏 JSON 凭据和多段认证/Cookie 值", async () => {
    await startRun();
    emit("tool.call.requested", {
      seq: 1,
      tool_call_id: "tc-redacted",
      tool: "course.search",
      permission: "read",
      input_summary:
        '{"token":"json-secret"} Authorization: Basic basic-secret Cookie: session=cookie-secret; theme=dark',
    });

    expect(screen.getByTestId("agent-activity-timeline")).toBeInTheDocument();
    expect(screen.queryByText("json-secret")).not.toBeInTheDocument();
    expect(screen.queryByText("basic-secret")).not.toBeInTheDocument();
    expect(screen.queryByText("cookie-secret")).not.toBeInTheDocument();
  });

  it("工具和 RAG 事件合并到同一执行记录", async () => {
    await startRun();
    emit("run.progress", {
      seq: 1,
      phase: "tool",
      status: "running",
      title: "不应重复展示的工具进度",
    });
    emit("tool.call.requested", {
      seq: 2,
      tool_call_id: "tc-dedup",
      tool: "course.search",
      permission: "read",
    });
    emit("run.progress", {
      seq: 3,
      phase: "retrieval",
      status: "running",
      title: "不应重复展示的检索进度",
    });
    emit("rag.retrieval.started", { seq: 4 });

    expect(screen.getByTestId("agent-activity-timeline")).toBeInTheDocument();
  });

  it("终态处理面板展示安全摘要而不泄露工具载荷", async () => {
    await startRun();
    emit("tool.call.requested", {
      seq: 1,
      tool_call_id: "tc-command",
      tool: "shell.run",
      permission: "read",
      execution_kind: "command",
      input_summary: "执行检查 · 参数 2 项，具体值已隐藏",
    });
    emit("tool.call.completed", {
      seq: 2,
      tool_call_id: "tc-command",
      tool: "shell.run",
      status: "completed",
      execution_kind: "command",
      duration_ms: 12,
      output_summary: "执行完成，返回 1 项",
      result: null,
    });
    emit("run.completed", { seq: 3, summary: "已完成" });
    expect(screen.getByTestId("agent-activity-timeline")).toBeInTheDocument();
    expect(screen.getByTestId("agent-current-action")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("agent-activity-history")).toBeInTheDocument();
    expect(screen.queryByText("执行检查 · 参数 2 项，具体值已隐藏")).not.toBeInTheDocument();
    expect(screen.queryByText("执行完成，返回 1 项")).not.toBeInTheDocument();
  });

  it("连续工具调用在终态保留安全处理面板且不泄露参数", async () => {
    await startRun();
    emit("run.started", { seq: 1 });
    emit("tool.call.requested", {
      seq: 2,
      tool_call_id: "tc-group-1",
      tool: "course.search",
      permission: "read",
      args_summary: "keyword=NER; token=never-rendered",
    });
    emit("tool.call.completed", {
      seq: 3,
      tool_call_id: "tc-group-1",
      tool: "course.search",
      status: "completed",
      is_write: false,
      duration_ms: 18,
      result: null,
    });
    emit("tool.call.requested", {
      seq: 4,
      tool_call_id: "tc-group-2",
      tool: "graph.reason",
      permission: "read",
    });
    emit("tool.call.completed", {
      seq: 5,
      tool_call_id: "tc-group-2",
      tool: "graph.reason",
      status: "completed",
      is_write: false,
      duration_ms: 24,
      result: null,
    });
    emit("run.progress", {
      seq: 6,
      phase: "synthesis",
      status: "running",
      activity_id: "answer:r1",
      title: "正在生成回答",
    });
    emit("run.completed", { seq: 7, summary: "已完成" });

    expect(screen.getByTestId("agent-activity-timeline")).toBeInTheDocument();
    expect(screen.getByTestId("agent-current-action")).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByText("token=never-rendered")).not.toBeInTheDocument();
  });

  it("RAG 不渲染结果卡或右侧重复轨迹，只保留安全处理记录", async () => {
    await startRun();
    emit("tool.call.requested", {
      seq: 1,
      tool_call_id: "tc-rag-search",
      tool: "rag.search",
      permission: "read",
    });
    emit("rag.retrieval.started", { seq: 2 });
    emit("tool.call.completed", {
      seq: 3,
      tool_call_id: "tc-rag-search",
      tool: "rag.search",
      status: "completed",
      is_write: false,
      result: { hit_count: 2 },
    });
    emit("tool.call.requested", {
      seq: 4,
      tool_call_id: "tc-rag-answer",
      tool: "rag.answer",
      permission: "read",
    });
    emit("tool.call.completed", {
      seq: 5,
      tool_call_id: "tc-rag-answer",
      tool: "rag.answer",
      status: "completed",
      is_write: false,
      result: { answer: "不应以规范解答卡呈现" },
    });
    emit("run.progress", {
      seq: 6,
      phase: "synthesis",
      status: "running",
      activity_id: "answer:r1",
      title: "正在生成回答",
    });

    expect(screen.queryByTestId("embedded-rag.search")).not.toBeInTheDocument();
    expect(screen.queryByTestId("embedded-rag.answer")).not.toBeInTheDocument();
    expect(screen.getByTestId("agent-activity-timeline")).toBeInTheDocument();
  });

  it("阅读历史消息时，后续活动不会强制把滚动区拉回底部", async () => {
    const getComputedStyleSpy = vi.spyOn(window, "getComputedStyle").mockReturnValue({
      overflowY: "auto",
      // Match the browser StyleDeclaration contract used by the scroll helper.
      getPropertyValue: () => "",
    } as unknown as CSSStyleDeclaration);
    const originalScrollIntoView = Element.prototype.scrollIntoView;
    const scrollIntoView = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });

    try {
      await startRun();
      // A reader who leaves the transcript near its history must not be pulled
      // back when later Agent activity arrives.
      const scrollRegion = document.querySelector<HTMLElement>(".cockpit-content-scroll");
      expect(scrollRegion).not.toBeNull();
      Object.defineProperties(scrollRegion!, {
        clientHeight: { configurable: true, value: 200 },
        scrollHeight: { configurable: true, value: 1_000 },
      });
      Object.defineProperty(scrollRegion!, "scrollTop", { configurable: true, value: 100 });
      fireEvent.scroll(scrollRegion!);
      scrollIntoView.mockClear();

      emit("run.progress", {
        seq: 1,
        phase: "planning",
        status: "running",
        title: "正在制定计划",
      });
      expect(scrollIntoView).not.toHaveBeenCalled();
    } finally {
      getComputedStyleSpy.mockRestore();
      Object.defineProperty(Element.prototype, "scrollIntoView", {
        configurable: true,
        value: originalScrollIntoView,
      });
    }
  });

  it("位于底部时，新的安全处理阶段会继续跟随", async () => {
    const originalScrollIntoView = Element.prototype.scrollIntoView;
    const scrollIntoView = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });

    try {
      await startRun();
      const scrollRegion = document.querySelector<HTMLElement>(".cockpit-content-scroll");
      expect(scrollRegion).not.toBeNull();
      Object.defineProperties(scrollRegion!, {
        clientHeight: { configurable: true, value: 200 },
        scrollHeight: { configurable: true, value: 1_000 },
      });
      Object.defineProperty(scrollRegion!, "scrollTop", { configurable: true, value: 800 });
      fireEvent.scroll(scrollRegion!);
      scrollIntoView.mockClear();

      // The status remains planning here. This assertion specifically proves
      // that activity-array changes, rather than only chat-token changes,
      // drive the guarded bottom-follow behavior.
      emit("run.progress", {
        seq: 1,
        phase: "planning",
        status: "running",
        title: "正在制定计划",
      });

      await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());
    } finally {
      Object.defineProperty(Element.prototype, "scrollIntoView", {
        configurable: true,
        value: originalScrollIntoView,
      });
    }
  });

  it("tool.call.completed(task.preview) → 嵌入任务卡", async () => {
    await startRun();
    emit("tool.call.requested", {
      seq: 2,
      tool_call_id: "tc1",
      tool: "task.preview",
      permission: "read",
    });
    emit("tool.call.completed", {
      seq: 3,
      tool_call_id: "tc1",
      tool: "task.preview",
      status: "completed",
      duration_ms: 12,
      is_write: 0,
      result: {
        card: {
          title: "NER 标注练习任务",
          goal: "掌握 BIO 边界划分",
          data_type: "text",
          cap_names: [{ cap_id: "CAP-1", name: "实体识别" }],
          steps: [{ title: "学习规范" }, { title: "完成练习" }],
          resources: [],
          est_minutes: 45,
        },
      },
    });
    const card = await screen.findByTestId("embedded-task.preview");
    expect(within(card).getByText("NER 标注练习任务")).toBeInTheDocument();
    expect(within(card).getByText("实体识别")).toBeInTheDocument();
    // A read-only preview never receives a write CTA until task.create has
    // emitted its own confirmation, which prevents tool-call ID mismatches.
    expect(screen.queryByTestId("task-sync-button")).not.toBeInTheDocument();
  });

  it("任务确认门提供一键同步，并通过既有确认端点创建任务", async () => {
    mockedPost.mockImplementation(async (path: string) => {
      if (path === "/api/runs") return { run_id: "r1", conversation_id: "c1" };
      if (path === "/api/events") return { accepted: 1 };
      if (path === "/api/confirmations/conf-1/confirm")
        return { status: "confirmed", result: { task_id: "t1" } };
      throw new ApiRequestError(404, "NOT_FOUND", `未预期的 POST ${path}`);
    });
    await startRun();
    emit("tool.call.requested", {
      seq: 1,
      tool_call_id: "tc-write",
      tool: "task.create",
      permission: "write",
    });
    emit("tool.call.completed", {
      seq: 2,
      tool_call_id: "tc-write",
      tool: "task.create",
      status: "awaiting_confirmation",
      is_write: true,
      result: null,
    });
    emit("confirmation.required", {
      seq: 3,
      confirmation: {
        id: "conf-1",
        tool_call_id: "tc-write",
        action_type: "task.create",
        status: "pending",
        expires_at: new Date(Date.now() + 1800_000).toISOString(),
        created_at: new Date().toISOString(),
        preview: {
          action: "task.create",
          summary: "将创建学习任务「NER 标注练习任务」",
          card: {
            title: "NER 标注练习任务",
            goal: "掌握 BIO 边界划分",
            steps: [{ title: "学习规范" }, { title: "完成练习" }],
            cap_names: [{ cap_id: "CAP-1", name: "实体识别" }],
          },
        },
      },
    });

    const gate = await screen.findByTestId("confirmation-gate");
    const syncButton = within(gate).getByTestId("task-sync-button");
    expect(syncButton).toHaveTextContent("同步到学习任务");
    expect(screen.getByTestId("agent-activity-timeline")).toBeInTheDocument();

    fireEvent.click(syncButton);
    await waitFor(() => expect(screen.queryByTestId("confirmation-gate")).not.toBeInTheDocument());
    expect(mockedPost).toHaveBeenCalledWith("/api/confirmations/conf-1/confirm", {});

    emit("tool.call.completed", {
      seq: 4,
      tool_call_id: "tc-write",
      tool: "task.create",
      status: "completed",
      duration_ms: 9,
      is_write: true,
      result: { task_id: "t1", title: "NER 标注练习任务" },
    });
    const receipt = await screen.findByTestId("embedded-task.create");
    expect(within(receipt).getByText("学习任务「NER 标注练习任务」已同步。")).toBeInTheDocument();
    expect(within(receipt).getByRole("link", { name: "前往学习任务查看 →" })).toHaveAttribute(
      "href",
      "/tasks",
    );
  });

  it("待确认任务收到“同步到学习任务中”时复用确认端点，而不是发送普通聊天", async () => {
    mockedPost.mockImplementation(async (path: string) => {
      if (path === "/api/runs") return { run_id: "r1", conversation_id: "c1" };
      if (path === "/api/events") return { accepted: 1 };
      if (path === "/api/confirmations/conf-text-sync/confirm") {
        return { status: "confirmed", result: { task_id: "t1" } };
      }
      throw new ApiRequestError(404, "NOT_FOUND", `未预期的 POST ${path}`);
    });
    await startRun();
    emit("confirmation.required", {
      seq: 1,
      confirmation: {
        id: "conf-text-sync",
        action_type: "task.create",
        status: "pending",
        expires_at: new Date(Date.now() + 1800_000).toISOString(),
        created_at: new Date().toISOString(),
        preview: { action: "task.create", summary: "将创建学习任务" },
      },
    });

    const input = await screen.findByLabelText("对话输入");
    fireEvent.change(input, { target: { value: "同步到学习任务中" } });
    const sendButton = screen.getByRole("button", { name: "发送" });
    await waitFor(() => expect(sendButton).toBeEnabled());
    fireEvent.click(sendButton);

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/confirmations/conf-text-sync/confirm", {}),
    );
    expect(mockedPost.mock.calls.filter(([path]) => path === "/api/runs")).toHaveLength(1);
    expect(screen.getByText("同步到学习任务中")).toBeInTheDocument();
  });

  it("任务同步请求未完成时，连续点击只提交一次确认", async () => {
    let resolveConfirmation: (() => void) | undefined;
    // Keep the write pending so the second interaction exercises the synchronous
    // confirmation lock rather than relying only on the rendered disabled state.
    const confirmationRequest = new Promise<{ status: string; result: Record<string, never> }>(
      (resolve) => {
        resolveConfirmation = () => resolve({ status: "confirmed", result: {} });
      },
    );
    mockedPost.mockImplementation(async (path: string) => {
      if (path === "/api/runs") return { run_id: "r1", conversation_id: "c1" };
      if (path === "/api/events") return { accepted: 1 };
      if (path === "/api/confirmations/conf-duplicate/confirm") return confirmationRequest;
      throw new ApiRequestError(404, "NOT_FOUND", `未预期的 POST ${path}`);
    });
    await startRun();
    emit("confirmation.required", {
      seq: 1,
      confirmation: {
        id: "conf-duplicate",
        action_type: "task.create",
        status: "pending",
        expires_at: new Date(Date.now() + 1800_000).toISOString(),
        created_at: new Date().toISOString(),
        preview: { action: "task.create", summary: "将创建学习任务" },
      },
    });

    const syncButton = await screen.findByTestId("task-sync-button");
    fireEvent.click(syncButton);
    fireEvent.click(syncButton);
    expect(
      mockedPost.mock.calls.filter(
        ([path]) => path === "/api/confirmations/conf-duplicate/confirm",
      ),
    ).toHaveLength(1);

    await act(async () => resolveConfirmation?.());
    await waitFor(() => expect(screen.queryByTestId("confirmation-gate")).not.toBeInTheDocument());
  });

  it("run.failed → 中文错误 + 重试按原输入重发（不暴露堆栈）", async () => {
    await startRun();
    emit("run.failed", { seq: 2, error: "模型服务暂时不可用，请稍后重试" });

    const failed = await screen.findByTestId("run-failed");
    expect(within(failed).getByText("模型服务暂时不可用，请稍后重试")).toBeInTheDocument();

    const runCallsBefore = mockedPost.mock.calls.filter((c) => c[0] === "/api/runs").length;
    fireEvent.click(within(failed).getByRole("button", { name: "重试" }));
    await act(async () => {});
    const runCalls = mockedPost.mock.calls.filter((c) => c[0] === "/api/runs");
    expect(runCalls.length).toBe(runCallsBefore + 1);
    expect(runCalls[runCalls.length - 1][1]).toEqual(
      expect.objectContaining({ input: TEST_RUN_GOAL }),
    );
  });

  it("run.completed 不显示结果摘要", async () => {
    await startRun();
    emit("run.completed", {
      seq: 2,
      summary: "已生成 NER 学习路径与练习任务。",
    });

    // 完成态不应重复渲染独立的结果摘要卡。
    expect(screen.queryByTestId("run-summary")).not.toBeInTheDocument();
    expect(screen.queryByText("结果摘要")).not.toBeInTheDocument();
  });

  it("citation.attached → 引用来源进入对话画布", async () => {
    await startRun();
    emit("citation.attached", {
      seq: 2,
      citations: [
        {
          document_id: "d1",
          title: "NER 标注入门规范",
          section_title: "BIO 边界",
          page_start: 3,
          page_end: 4,
          version: "1.0",
          score: 0.86,
        },
      ],
    });
    const section = await screen.findByTestId("citation-section");
    expect(within(section).getByText(/NER 标注入门规范/)).toBeInTheDocument();
    const anchor = screen.getByTestId("chat-stream-bottom");
    // Runtime context must stay before the anchor so bottom-following scrolls
    // reveal citations and confirmation cards as soon as they arrive.
    expect(section.compareDocumentPosition(anchor) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
