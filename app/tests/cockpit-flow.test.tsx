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
import CockpitPage from "../src/pages/student/CockpitPage";
import {
  FakeRunEventStream,
  installDefaultGetMock,
  latestStream,
} from "./cockpit-shared";

vi.mock("../src/api/client", async () =>
  (await import("./cockpit-shared")).buildApiClientMock(),
);
vi.mock("../src/api/sse", async () =>
  (await import("./cockpit-shared")).buildSseMock(),
);

const mockedGet = vi.mocked(api.get);
const mockedPost = vi.mocked(api.post);
const mockedDelete = vi.mocked(api.delete);
const mockedPostForm = vi.mocked(api.postForm);

/** 与生产 Provider 组合一致的渲染 */
function renderCockpit() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <ScenarioProvider>
          <CockpitPage />
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
    if (path === "/api/diagnostics/save-summary")
      return { summary_id: "s1", mastery_applied: [] };
    throw new ApiRequestError(404, "NOT_FOUND", `未预期的 POST ${path}`);
  });
});

describe("指挥舱 · 诊断上传", () => {
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
    await waitFor(() =>
      expect(FakeRunEventStream.instances.length).toBeGreaterThan(0),
    );
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
            { id: "m2", run_id: "r0", role: "assistant", content: "好的，先看规范。", created_at: "" },
            { id: "m3", run_id: "r0", role: "tool", content: "工具内部摘要不应展示", created_at: "" },
          ],
        };
      throw new ApiRequestError(404, "NOT_FOUND", `未预期的 GET ${path}`);
    });
  }

  it("点击历史会话 → 载入消息（tool 消息隐藏）；新会话回到欢迎态", async () => {
    mockConversationApis();
    renderCockpit();

    fireEvent.click(await screen.findByText("旧会话"));
    expect(await screen.findByText("我想学 NER")).toBeInTheDocument();
    expect(screen.getByText("好的，先看规范。")).toBeInTheDocument();
    expect(screen.queryByText("工具内部摘要不应展示")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /新会话/ }));
    expect(await screen.findByTestId("cockpit-welcome")).toBeInTheDocument();
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
    fireEvent.click(await screen.findByText("客服语音情感标签有哪些？"));
    await screen.findByTestId("chat-stream");
    await waitFor(() =>
      expect(FakeRunEventStream.instances.length).toBeGreaterThan(0),
    );

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
      ),
    );
    expect(await screen.findByText("预览已过期，未做任何修改，请重新发起操作。")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByTestId("confirmation-gate")).not.toBeInTheDocument(),
    );
    // Terminal status removes `sending`, so the next goal can be submitted.
    fireEvent.click(screen.getByRole("button", { name: "生成学习任务" }));
    expect(screen.getByRole("button", { name: "发送" })).not.toBeDisabled();
  });

  it("另一标签页发来的终态 SSE 也会移除本地确认卡", async () => {
    renderCockpit();
    fireEvent.click(await screen.findByText("客服语音情感标签有哪些？"));
    await screen.findByTestId("chat-stream");
    await waitFor(() =>
      expect(FakeRunEventStream.instances.length).toBeGreaterThan(0),
    );
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
    await waitFor(() =>
      expect(screen.queryByTestId("confirmation-gate")).not.toBeInTheDocument(),
    );
  });

  it("confirm 410 → toast 提示 + 刷新 run 状态", async () => {
    mockedPost.mockImplementation(async (path: string) => {
      if (path === "/api/runs") return { run_id: "r1", conversation_id: "c1" };
      if (path === "/api/events") return { accepted: 1 };
      if (path === "/api/confirmations/conf-1/confirm")
        throw new ApiRequestError(410, "CONFIRMATION_EXPIRED", "确认已过期，请重新生成预览后再确认");
      throw new ApiRequestError(404, "NOT_FOUND", `未预期的 POST ${path}`);
    });
    renderCockpit();
    fireEvent.click(await screen.findByText("客服语音情感标签有哪些？"));
    await screen.findByTestId("chat-stream");
    await waitFor(() =>
      expect(FakeRunEventStream.instances.length).toBeGreaterThan(0),
    );

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
    await waitFor(() =>
      expect(screen.queryByTestId("confirmation-gate")).not.toBeInTheDocument(),
    );
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
          throw new ApiRequestError(
            409,
            "CONFIRMATION_NOT_EXPIRED",
            "确认单尚未过期",
          );
        }
        return {
          status: "expired",
          summary: "预览已过期，未做任何修改，请重新发起操作。",
        };
      }
      throw new ApiRequestError(404, "NOT_FOUND", `未预期的 POST ${path}`);
    });

    renderCockpit();
    fireEvent.click(await screen.findByText("客服语音情感标签有哪些？"));
    await screen.findByTestId("chat-stream");
    await waitFor(() =>
      expect(FakeRunEventStream.instances.length).toBeGreaterThan(0),
    );
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
    await waitFor(() =>
      expect(screen.queryByTestId("confirmation-gate")).not.toBeInTheDocument(),
    );
  });

  it("run.failed 会清除过期确认门而不是保留可点击的旧预览", async () => {
    renderCockpit();
    fireEvent.click(await screen.findByText("客服语音情感标签有哪些？"));
    await screen.findByTestId("chat-stream");
    await waitFor(() =>
      expect(FakeRunEventStream.instances.length).toBeGreaterThan(0),
    );
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
