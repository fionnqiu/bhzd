/**
 * 任务草稿链路测试：task.draft 事件 → 回答底部按钮 → 预览弹窗 → 同步/继续修改。
 * mock 策略与 cockpit-flow.test.tsx 相同（共享桩见 cockpit-shared.tsx）。
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { api, ApiRequestError } from "../src/api/client";
import { ToastProvider } from "../src/components";
import {
  StudentWorkbenchShellProvider,
  useStudentWorkbenchShell,
} from "../src/layouts/StudentWorkbenchShellContext";
import CockpitPage from "../src/pages/student/CockpitPage";
import { WorkbenchNewSession, WorkbenchRecentSessions } from "../src/pages/student/cockpit/LeftRail";
import { FakeRunEventStream, installDefaultGetMock, latestStream } from "./cockpit-shared";

vi.mock("../src/api/client", async () => (await import("./cockpit-shared")).buildApiClientMock());
vi.mock("../src/api/sse", async () => (await import("./cockpit-shared")).buildSseMock());

const mockedGet = vi.mocked(api.get);
const mockedPost = vi.mocked(api.post);

/** 与生产 Provider 组合一致的渲染（含会话侧栏，供历史会话切换） */
function SidebarHost() {
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
  return (
    <aside>
      <WorkbenchNewSession busy={sessionActionsDisabled} onNewConversation={requestNewConversation} />
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

function renderCockpit() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <StudentWorkbenchShellProvider>
          <CockpitPage />
          <SidebarHost />
        </StudentWorkbenchShellProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
}

const DRAFT = {
  id: "d1",
  status: "draft" as const,
  source: "agent",
  cards: [
    {
      title: "图像框选入门任务",
      goal: "掌握边界框标注规范",
      description: "掌握边界框标注规范",
      data_type: "image",
      cap_ids: ["CAP-IMG-001"],
      cap_names: [{ cap_id: "CAP-IMG-001", name: "框选边界控制" }],
      knowledge_points: [{ title: "边界框规则", content: "框必须贴合目标外缘。" }],
      exercises: [
        {
          question: "边界框应贴合到哪里？",
          type: "open_ended",
          options: [],
          reference_answer: "目标物体的最外缘像素。",
        },
      ],
      est_minutes: 30,
    },
  ],
  task_ids: [] as string[],
  created_at: "2026-08-21T00:00:00Z",
  synced_at: null,
};

const CONVERSATION = {
  id: "c9",
  title: "旧会话",
  data_type: null,
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-02T00:00:00Z",
};

async function submitGoal(goal: string) {
  const input = await screen.findByLabelText("对话输入");
  fireEvent.change(input, { target: { value: goal } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(FakeRunEventStream.instances).toHaveLength(1));
}

beforeEach(() => {
  vi.clearAllMocks();
  FakeRunEventStream.instances = [];
  installDefaultGetMock();
  mockedPost.mockImplementation(async (path: string) => {
    if (path === "/api/runs") return { run_id: "r1", conversation_id: "c1" };
    if (path === "/api/task-drafts/d1/sync") {
      return {
        draft_id: "d1",
        status: "synced",
        task_ids: ["t1"],
        tasks: [{ id: "t1", title: "图像框选入门任务" }],
        already_synced: false,
      };
    }
    throw new ApiRequestError(404, "NOT_FOUND", `未预期的 POST ${path}`);
  });
});

describe("任务草稿 · 生成 → 预览 → 同步/修改", () => {
  it("task.draft 事件后回答底部出现按钮；弹窗预览并同步落库", async () => {
    renderCockpit();
    await submitGoal("帮我生成一个图像标注的学习任务");

    act(() => {
      latestStream().emit("message.delta", { seq: 1, delta: "已为你生成学习任务草稿。" });
      latestStream().emit("task.draft", { seq: 2, draft: DRAFT });
    });

    // 交互按钮出现在回答内容底部
    expect(screen.getByText("已为你生成学习任务草稿。")).toBeInTheDocument();
    fireEvent.click(await screen.findByTestId("task-draft-open"));

    // 预览弹窗展示刚生成的任务卡
    expect(await screen.findByText("学习任务卡预览")).toBeInTheDocument();
    expect(screen.getByText("图像框选入门任务")).toBeInTheDocument();
    expect(screen.getByText("边界框规则")).toBeInTheDocument();
    expect(screen.getByText(/边界框应贴合到哪里/)).toBeInTheDocument();

    // 同步按钮点击 → 直接落库（幂等响应驱动已同步态）
    fireEvent.click(screen.getByTestId("task-draft-sync"));
    await waitFor(() => expect(mockedPost).toHaveBeenCalledWith("/api/task-drafts/d1/sync", {}));
    expect(await screen.findByText("已同步 1 个学习任务。")).toBeInTheDocument();
    expect(screen.getByTestId("task-draft-sync")).toBeDisabled();
    expect(screen.getByRole("link", { name: /前往学习任务查看/ })).toBeInTheDocument();
  });

  it("「继续修改」预填修订话术到输入框", async () => {
    renderCockpit();
    await submitGoal("帮我生成一个图像标注的学习任务");
    act(() => {
      latestStream().emit("task.draft", { seq: 1, draft: DRAFT });
    });

    fireEvent.click(await screen.findByTestId("task-draft-open"));
    expect(await screen.findByText("学习任务卡预览")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("task-draft-revise"));

    const input = (await screen.findByLabelText("对话输入")) as HTMLTextAreaElement;
    expect(input.value).toBe("请修改刚才的学习任务：");
  });

  it("历史会话回放：task_drafts_by_run 让旧回答下方复原按钮与已同步态", async () => {
    mockedGet.mockImplementation(async (path: string) => {
      if (path === "/api/presets") return { items: [], total: 0 };
      if (path === "/api/tasks") return { items: [], total: 0 };
      if (path === "/api/profile/mastery") return { items: [], total: 0 };
      if (path === "/api/conversations") return { items: [CONVERSATION], total: 1 };
      if (path === "/api/conversations/c9")
        return {
          ...CONVERSATION,
          messages: [
            { id: "m1", run_id: "r0", role: "user", content: "帮我生成学习任务", created_at: "" },
            { id: "m2", run_id: "r0", role: "assistant", content: "已生成草稿。", created_at: "" },
          ],
          task_drafts_by_run: {
            r0: { ...DRAFT, id: "d0", status: "synced" as const, task_ids: ["t0"] },
          },
        };
      throw new ApiRequestError(404, "NOT_FOUND", `未预期的 GET ${path}`);
    });
    renderCockpit();

    fireEvent.click(await screen.findByText("旧会话"));
    const openButton = await screen.findByTestId("task-draft-open");
    expect(openButton).toHaveTextContent("已同步");

    fireEvent.click(openButton);
    expect(await screen.findByText("学习任务卡预览")).toBeInTheDocument();
    expect(screen.getByTestId("task-draft-sync")).toBeDisabled();
    // 已同步草稿不再发起同步请求
    expect(mockedPost).not.toHaveBeenCalledWith("/api/task-drafts/d0/sync", {});
  });
});
