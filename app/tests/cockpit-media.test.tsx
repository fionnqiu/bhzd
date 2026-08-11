import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { api, ApiRequestError } from "../src/api/client";
import { ScenarioProvider } from "../src/app/ScenarioContext";
import { ToastProvider } from "../src/components";
import { StudentWorkbenchShellProvider } from "../src/layouts/StudentWorkbenchShellContext";
import CockpitPage from "../src/pages/student/CockpitPage";
import { FakeRunEventStream, installDefaultGetMock } from "./cockpit-shared";

vi.mock("../src/api/client", async () => (await import("./cockpit-shared")).buildApiClientMock());
vi.mock("../src/api/sse", async () => (await import("./cockpit-shared")).buildSseMock());

const mockedPost = vi.mocked(api.post);
const mockedPostForm = vi.mocked(api.postForm);
const mockedGet = vi.mocked(api.get);
const mockedDelete = vi.mocked(api.delete);

function renderCockpit() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <ScenarioProvider>
          <StudentWorkbenchShellProvider>
            <CockpitPage />
          </StudentWorkbenchShellProvider>
        </ScenarioProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  FakeRunEventStream.instances = [];
  installDefaultGetMock();
  mockedPost.mockImplementation(async (path: string) => {
    if (path === "/api/runs") return { run_id: "r-media", conversation_id: "c-media" };
    if (path === "/api/events") return { accepted: 1 };
    throw new ApiRequestError(404, "NOT_FOUND", `Unexpected POST ${path}`);
  });
  mockedPostForm.mockResolvedValue({
    attachment_token: "media-token",
    name: "photo.png",
    mime_type: "image/png",
    kind: "image",
    size: 5,
    expires_at: 1_000,
  });
  mockedDelete.mockResolvedValue({});
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Agent media attachments", () => {
  it("keeps a named loading placeholder visible until the upload completes", async () => {
    let finishUpload!: (value: unknown) => void;
    // Hold the multipart request open so this checks the state users see on a
    // slow connection, rather than only the immediate resolved-state card.
    mockedPostForm.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishUpload = resolve;
        }),
    );
    renderCockpit();

    fireEvent.change(await screen.findByLabelText("选择对话附件"), {
      target: {
        files: [new File(["%PDF-1.7"], "课程资料.pdf", { type: "application/pdf" })],
      },
    });

    const pending = await screen.findByTestId("composer-media-uploading");
    expect(pending).toHaveAttribute("aria-busy", "true");
    expect(pending).toHaveTextContent("课程资料.pdf");
    expect(pending).toHaveTextContent("正在上传");
    expect(screen.queryByTestId("composer-media-preview")).not.toBeInTheDocument();

    const textInput = screen.getByLabelText("对话输入");
    fireEvent.change(textInput, { target: { value: "请读取这个文件" } });
    const send = screen.getByRole("button", { name: "发送" });
    expect(send).toBeDisabled();
    fireEvent.keyDown(textInput, { key: "Enter" });
    expect(mockedPost.mock.calls.filter(([path]) => path === "/api/runs")).toHaveLength(0);

    finishUpload({
      attachment_token: "pdf-token",
      name: "课程资料.pdf",
      mime_type: "application/pdf",
      kind: "document",
      size: 8,
      expires_at: 1_000,
    });

    const attachment = await screen.findByTestId("composer-media-preview");
    expect(attachment).toHaveTextContent("课程资料.pdf");
    expect(screen.queryByTestId("composer-media-uploading")).not.toBeInTheDocument();
    expect(send).not.toBeDisabled();
    fireEvent.click(send);
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/runs",
        expect.objectContaining({ attachments: [{ attachment_token: "pdf-token" }] }),
      ),
    );
  });

  it("uploads a media file, shows its Composer preview, and forwards it on send", async () => {
    renderCockpit();

    const input = await screen.findByLabelText("选择对话附件");
    expect(input).toHaveAttribute("accept", expect.stringContaining("image/*"));
    expect(input).toHaveAttribute("accept", expect.stringContaining("video/*"));
    expect(input).toHaveAttribute("accept", expect.stringContaining("audio/*"));
    expect(input).toHaveAttribute("accept", expect.stringContaining(".docx"));
    expect(input).toHaveAttribute("accept", expect.stringContaining(".md"));
    expect(input).toHaveAttribute("multiple");

    fireEvent.change(input, {
      target: {
        files: [new File(["bytes"], "photo.png", { type: "image/png" })],
      },
    });
    const preview = await screen.findByTestId("composer-media-preview");
    expect(preview).toBe(screen.getByRole("group", { name: "已上传图片预览" }));
    expect(screen.getByTestId("composer-input-shell")).toContainElement(preview);
    expect(screen.queryByText("媒体已上传，可随消息发送")).not.toBeInTheDocument();
    expect(mockedPostForm).toHaveBeenCalledWith("/api/runs/attachments", expect.any(FormData));

    const textInput = screen.getByLabelText("对话输入");
    fireEvent.change(textInput, { target: { value: "请描述这张图片" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/runs",
        expect.objectContaining({
          input: "请描述这张图片",
          attachments: [{ attachment_token: "media-token" }],
        }),
      ),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("composer-media-preview")).not.toBeInTheDocument(),
    );
  });

  it("normalizes a misleading browser MIME type to the accepted extension MIME", async () => {
    renderCockpit();

    fireEvent.change(await screen.findByLabelText("选择对话附件"), {
      target: {
        files: [new File(["bytes"], "photo.png", { type: "application/octet-stream" })],
      },
    });

    await screen.findByTestId("composer-media-preview");
    const form = mockedPostForm.mock.calls[0]?.[1] as FormData;
    const payload = form.get("file") as File;
    expect(payload.type).toBe("image/png");
  });

  it("replaces the optimistic image preview with the durable thumbnail and releases its blob URL", async () => {
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:sent-photo"),
      revokeObjectURL,
    });
    mockedPost.mockImplementation(async (path: string) => {
      if (path === "/api/runs") {
        return {
          run_id: "r-media",
          conversation_id: "c-media",
          user_message: {
            id: "m-media",
            run_id: "r-media",
            role: "user",
            content: "请描述这张图片",
            created_at: "",
            attachments: [
              {
                id: "a-media",
                ordinal: 0,
                name: "photo.png",
                kind: "image",
                mime_type: "image/png",
                size: 5,
                thumbnail_url: "/api/messages/m-media/attachments/a-media/thumbnail",
              },
            ],
          },
        };
      }
      if (path === "/api/events") return { accepted: 1 };
      throw new ApiRequestError(404, "NOT_FOUND", `Unexpected POST ${path}`);
    });
    renderCockpit();

    fireEvent.change(await screen.findByLabelText("选择对话附件"), {
      target: { files: [new File(["bytes"], "photo.png", { type: "image/png" })] },
    });
    await screen.findByTestId("composer-media-preview");
    fireEvent.change(screen.getByLabelText("对话输入"), { target: { value: "请描述这张图片" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() =>
      expect(screen.getByAltText("photo.png 缩略图")).toHaveAttribute(
        "src",
        "/api/messages/m-media/attachments/a-media/thumbnail",
      ),
    );
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith("blob:sent-photo"));
  });

  it("keeps the local image preview when persistence has no safe thumbnail", async () => {
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:thumbnail-fallback"),
      revokeObjectURL,
    });
    mockedPost.mockImplementation(async (path: string) => {
      if (path === "/api/runs") {
        return {
          run_id: "r-media",
          conversation_id: "c-media",
          user_message: {
            id: "m-media",
            run_id: "r-media",
            role: "user",
            content: "请描述这张图片",
            created_at: "",
            attachments: [
              {
                id: "a-media",
                ordinal: 0,
                name: "photo.png",
                kind: "image",
                mime_type: "image/png",
                size: 5,
                thumbnail_url: null,
              },
            ],
          },
        };
      }
      if (path === "/api/events") return { accepted: 1 };
      throw new ApiRequestError(404, "NOT_FOUND", `Unexpected POST ${path}`);
    });
    renderCockpit();

    fireEvent.change(await screen.findByLabelText("选择对话附件"), {
      target: { files: [new File(["bytes"], "photo.png", { type: "image/png" })] },
    });
    await screen.findByTestId("composer-media-preview");
    fireEvent.change(screen.getByLabelText("对话输入"), { target: { value: "请描述这张图片" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByAltText("photo.png 缩略图")).toHaveAttribute(
      "src",
      "blob:thumbnail-fallback",
    );
    expect(revokeObjectURL).not.toHaveBeenCalled();
  });

  it("opens the attachment preview and closes it when the file is removed", async () => {
    // Blob URLs are browser-owned. Stub them so jsdom can assert that the
    // preview receives the local file URL without depending on a real browser.
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:composer-preview"),
      revokeObjectURL: vi.fn(),
    });
    renderCockpit();
    fireEvent.change(await screen.findByLabelText("选择对话附件"), {
      target: {
        files: [new File(["bytes"], "photo.png", { type: "image/png" })],
      },
    });
    await screen.findByTestId("composer-media-preview");

    fireEvent.click(screen.getByRole("button", { name: "预览文件 photo.png" }));
    const dialog = await screen.findByRole("dialog", { name: "photo.png" });
    expect(dialog).toContainElement(screen.getByAltText("photo.png"));
    expect(screen.getByAltText("photo.png")).toHaveAttribute("src", "blob:composer-preview");

    fireEvent.click(screen.getByRole("button", { name: "移除附件 photo.png" }));
    await waitFor(() => {
      expect(screen.queryByTestId("composer-media-preview")).not.toBeInTheDocument();
      expect(screen.queryByRole("dialog", { name: "photo.png" })).not.toBeInTheDocument();
    });
  });

  it("uploads a markdown document and labels it as a document preview", async () => {
    mockedPostForm.mockResolvedValueOnce({
      attachment_token: "doc-token",
      name: "guide.md",
      mime_type: "text/markdown",
      kind: "document",
      size: 12,
      expires_at: 1_000,
    });
    renderCockpit();

    fireEvent.change(await screen.findByLabelText("选择对话附件"), {
      target: {
        files: [new File(["# Guide"], "guide.md", { type: "text/markdown" })],
      },
    });

    await screen.findByRole("group", { name: "已上传文件预览" });
    expect(mockedPostForm).toHaveBeenCalledWith("/api/runs/attachments", expect.any(FormData));
  });

  it("sends a single JSON file as current-turn Agent context instead of a diagnostic upload", async () => {
    mockedPostForm.mockResolvedValueOnce({
      attachment_token: "json-token",
      name: "labels.json",
      mime_type: "application/json",
      kind: "document",
      size: 16,
      expires_at: 1_000,
    });
    renderCockpit();

    fireEvent.change(await screen.findByLabelText("选择对话附件"), {
      target: {
        files: [new File(['{"labels": []}'], "labels.json", { type: "application/json" })],
      },
    });
    await screen.findByRole("group", { name: "已上传文件预览" });
    expect(mockedPostForm).toHaveBeenCalledWith("/api/runs/attachments", expect.any(FormData));

    fireEvent.change(screen.getByLabelText("对话输入"), {
      target: { value: "请检查这个标注结果" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/runs",
        expect.objectContaining({
          input: "请检查这个标注结果",
          attachments: [{ attachment_token: "json-token" }],
        }),
      ),
    );
  });

  it("keeps failed-run text and attachments available for retry", async () => {
    renderCockpit();
    fireEvent.change(await screen.findByLabelText("选择对话附件"), {
      target: {
        files: [new File(["bytes"], "photo.png", { type: "image/png" })],
      },
    });
    await screen.findByTestId("composer-media-preview");
    mockedPost.mockRejectedValueOnce(new ApiRequestError(503, "UNAVAILABLE", "服务暂不可用"));

    const textInput = screen.getByLabelText("对话输入");
    fireEvent.change(textInput, { target: { value: "请描述这张图片" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledWith("/api/runs", expect.any(Object)));
    await waitFor(() => expect(screen.getByTestId("composer-media-preview")).toBeInTheDocument());
    expect(textInput).toHaveValue("请描述这张图片");
    // A rejected create request did not make a durable message. Its optimistic
    // row must disappear before a retry can create the one real user turn.
    expect(document.querySelectorAll(".bubble-user")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() =>
      expect(mockedPost.mock.calls.filter(([path]) => path === "/api/runs")).toHaveLength(2),
    );
    await waitFor(() => expect(document.querySelectorAll(".bubble-user")).toHaveLength(1));
  });

  it("does not reuse a consumed media token after a persisted run fails", async () => {
    renderCockpit();
    fireEvent.change(await screen.findByLabelText("\u9009\u62e9\u5bf9\u8bdd\u9644\u4ef6"), {
      target: {
        files: [new File(["bytes"], "photo.png", { type: "image/png" })],
      },
    });
    await screen.findByTestId("composer-media-preview");

    fireEvent.change(screen.getByLabelText("\u5bf9\u8bdd\u8f93\u5165"), {
      target: { value: "describe the image" },
    });
    fireEvent.click(screen.getByRole("button", { name: "\u53d1\u9001" }));
    await waitFor(() => expect(FakeRunEventStream.instances).toHaveLength(1));

    // The server accepted this turn and owns its one-shot media token. A later
    // run failure must ask for re-upload instead of silently retrying a token
    // the orchestrator has already discarded.
    await act(async () => {
      FakeRunEventStream.instances[0]?.emit("run.failed", {
        seq: 1,
        error: "temporary provider failure",
      });
    });
    const failed = await screen.findByTestId("run-failed");
    const runCallsBeforeRetry = mockedPost.mock.calls.filter(([path]) => path === "/api/runs").length;
    const retryButton = failed.querySelector("button");
    expect(retryButton).not.toBeNull();

    fireEvent.click(retryButton!);
    await waitFor(() =>
      expect(mockedPost.mock.calls.filter(([path]) => path === "/api/runs")).toHaveLength(
        runCallsBeforeRetry,
      ),
    );
  });

  it("shows the media capability error and keeps the attachment after the run is rejected", async () => {
    renderCockpit();
    fireEvent.change(await screen.findByLabelText("选择对话附件"), {
      target: {
        files: [new File(["bytes"], "photo.png", { type: "image/png" })],
      },
    });
    await screen.findByTestId("composer-media-preview");
    mockedPost.mockRejectedValueOnce(
      new ApiRequestError(
        422,
        "ATTACHMENT_MEDIA_UNSUPPORTED",
        "当前主模型和回退模型均无法处理图片附件。请配置支持图片输入的模型后重试。",
      ),
    );

    fireEvent.change(screen.getByLabelText("对话输入"), { target: { value: "请描述图片" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(
      await screen.findByText(
        "当前主模型和回退模型均无法处理图片附件。请配置支持图片输入的模型后重试。",
      ),
    ).toBeInTheDocument();
    expect(screen.getByTestId("composer-media-preview")).toBeInTheDocument();
  });

  it("keeps multiple files and sends every short-lived token", async () => {
    let resolveFirstUpload!: (value: unknown) => void;
    let resolveSecondUpload!: (value: unknown) => void;
    mockedPostForm
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirstUpload = resolve;
          }),
      )
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveSecondUpload = resolve;
          }),
      );
    renderCockpit();

    fireEvent.change(await screen.findByLabelText("选择对话附件"), {
      target: {
        files: [
          new File(["image"], "first.png", { type: "image/png" }),
          new File(["%PDF-1.7"], "second.pdf", { type: "application/pdf" }),
        ],
      },
    });

    await waitFor(() => expect(mockedPostForm).toHaveBeenCalledTimes(2));
    // Complete the second request first to prove the visible/sent order follows
    // the learner's selection rather than a race between multipart responses.
    resolveSecondUpload({
      attachment_token: "second-token",
      name: "second.pdf",
      mime_type: "application/pdf",
      kind: "document",
      size: 8,
      expires_at: 1_000,
    });
    resolveFirstUpload({
      attachment_token: "first-token",
      name: "first.png",
      mime_type: "image/png",
      kind: "image",
      size: 5,
      expires_at: 1_000,
    });

    await waitFor(() => expect(screen.getAllByTestId("composer-media-preview")).toHaveLength(2));
    const previews = screen.getAllByTestId("composer-media-preview");
    expect(previews[0]).toHaveTextContent("first.png");
    expect(previews[1]).toHaveTextContent("second.pdf");

    fireEvent.change(screen.getByLabelText("对话输入"), { target: { value: "对比两个文件" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/runs",
        expect.objectContaining({
          input: "对比两个文件",
          attachments: [{ attachment_token: "first-token" }, { attachment_token: "second-token" }],
        }),
      ),
    );
  });

  it("loads extracted text for document formats without a native browser preview", async () => {
    mockedPostForm.mockResolvedValueOnce({
      attachment_token: "office-token",
      name: "lesson.docx",
      mime_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      kind: "document",
      size: 12,
      expires_at: 1_000,
    });
    mockedGet.mockImplementation(async (path: string) => {
      if (path === "/api/runs/attachments/office-token/preview") {
        return {
          name: "lesson.docx",
          mime_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          content: "课程目标",
          truncated: false,
        };
      }
      if (
        path === "/api/presets" ||
        path === "/api/tasks" ||
        path === "/api/conversations" ||
        path === "/api/profile/mastery"
      ) {
        return { items: [], total: 0 };
      }
      throw new ApiRequestError(404, "NOT_FOUND", `Unexpected GET ${path}`);
    });
    renderCockpit();

    fireEvent.change(await screen.findByLabelText("选择对话附件"), {
      target: {
        files: [
          new File(["docx"], "lesson.docx", {
            type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          }),
        ],
      },
    });
    await screen.findByRole("group", { name: "已上传文件预览" });

    fireEvent.click(screen.getByRole("button", { name: "预览文件 lesson.docx" }));
    expect(await screen.findByText("课程目标")).toBeInTheDocument();
    expect(mockedGet).toHaveBeenCalledWith("/api/runs/attachments/office-token/preview");
  });
});
