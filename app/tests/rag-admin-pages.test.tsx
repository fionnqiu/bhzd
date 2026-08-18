/**
 * 系统管理端 RAG 页面测试（PRD-03）：活动资料库/上传，以及
 * 已合并工作流的底层组件回归覆盖。
 *
 * api 层整体打桩（与 auth-pages.test.tsx 同一模式）：断言页面触发的
 * 端点与载荷符合 rag_admin.py 契约，后端守卫话术透传到 toast。
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ReactElement } from "react";
import { ApiRequestError, api } from "../src/api/client";
import { ToastProvider } from "../src/components";
import DocumentsPage from "../src/pages/rag/DocumentsPage";
import UploadPage from "../src/pages/rag/UploadPage";
import ChunkEditorPage from "../src/pages/rag/ChunkEditorPage";
import JobsPage from "../src/pages/rag/JobsPage";
import PublishReviewPage from "../src/pages/rag/PublishReviewPage";

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
const mockedDelete = vi.mocked(api.delete);
const mockedPostForm = vi.mocked(api.postForm);

function renderPage(ui: ReactElement, route = "/") {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </ToastProvider>,
  );
}

/** Mounts a parameterized RAG component without coupling it to the production route tree. */
function renderWithRoute(ui: ReactElement, path: string, initial: string) {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path={path} element={ui} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

/* ---------------------------------------------------------------- 测试数据 */

function makeDoc(overrides: Record<string, unknown>) {
  return {
    id: "doc-x",
    title: "未命名资料",
    file_type: "md",
    source_type: "standard",
    source_name: "测试来源",
    source_url: null,
    source_ledger_id: null,
    version: "1.0",
    license_status: "authorized",
    data_types: ["text"],
    cap_ids: [],
    visibility: "teacher",
    status: "draft",
    file_hash: "abc",
    error_code: null,
    error_message: null,
    process_version: 1,
    created_by: "user-1",
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-02T00:00:00Z",
    published_at: null,
    expires_at: null,
    chunk_count: 3,
    ...overrides,
  };
}

function makeChunk(overrides: Record<string, unknown>) {
  return {
    id: "chunk-x",
    document_id: "doc1",
    chunk_index: 0,
    content: "第一段内容。第二句。",
    summary: null,
    keywords: ["语音"],
    page_start: 1,
    page_end: 1,
    section_title: "第一章",
    token_count: 10,
    embedding_model: "local-hash-512",
    metadata: {},
    status: "active",
    process_version: 1,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

/* ---------------------------------------------------------------- 资料库 */

describe("DocumentsPage（PRD-03 §4）", () => {
  const DOCS = [
    makeDoc({ id: "doc-indexed", title: "已索引资料", status: "indexed" }),
    makeDoc({ id: "doc-review", title: "待审核资料", status: "review_pending" }),
    makeDoc({ id: "doc-published", title: "已发布资料", status: "published" }),
    makeDoc({
      id: "doc-failed",
      title: "失败资料",
      status: "failed",
      error_code: "PARSE_EMPTY_TEXT",
      error_message: "未解析出文本",
    }),
    makeDoc({ id: "doc-draft", title: "草稿资料", status: "draft" }),
  ];

  beforeEach(() => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/rag/documents")
        return Promise.resolve({ items: DOCS, total: DOCS.length });
      if (path === "/api/rag/jobs")
        return Promise.resolve({ items: [{ id: "job-failed-1" }], total: 1 });
      return Promise.reject(new Error(`未打桩的 GET ${path}`));
    });
    mockedPost.mockResolvedValue({});
    mockedDelete.mockResolvedValue({ deleted: true });
  });

  it("渲染状态徽章与按状态操作列", async () => {
    renderPage(<DocumentsPage />);
    expect(await screen.findByText("已索引资料")).toBeInTheDocument();
    // 行操作：处理状态只提供重新索引/归档/重试/删除，审核不再是活动入口。
    const indexedRow = screen.getByText("已索引资料").closest("tr")!;
    expect(within(indexedRow).queryByRole("button", { name: "送审" })).not.toBeInTheDocument();
    const reviewRow = screen.getByText("待审核资料").closest("tr")!;
    expect(within(reviewRow).queryByRole("link", { name: "发布审核" })).not.toBeInTheDocument();
    const publishedRow = screen.getByText("已发布资料").closest("tr")!;
    expect(within(publishedRow).getByRole("button", { name: "归档" })).toBeInTheDocument();
    expect(within(publishedRow).getByRole("button", { name: "重新索引" })).toBeInTheDocument();
    // 已发布行不显示删除（PRD-06 §5.2 只能归档）
    expect(within(publishedRow).queryByRole("button", { name: "删除" })).not.toBeInTheDocument();
    const failedRow = screen.getByText("失败资料").closest("tr")!;
    expect(within(failedRow).getByRole("button", { name: "重试" })).toBeInTheDocument();
    const draftRow = screen.getByText("草稿资料").closest("tr")!;
    expect(within(draftRow).getByRole("button", { name: "删除" })).toBeInTheDocument();
    // 行标题链接到详情页
    expect(screen.getByRole("link", { name: "已索引资料" })).toHaveAttribute(
      "href",
      "/admin/rag/documents/doc-indexed?returnTo=%2Fadmin%2Frag",
    );
  });

  it("重新索引触发对应端点且不调用旧审核端点", async () => {
    renderPage(<DocumentsPage />);
    await screen.findByText("已索引资料");
    const publishedRow = screen.getByText("已发布资料").closest("tr")!;
    fireEvent.click(within(publishedRow).getByRole("button", { name: "重新索引" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/rag/documents/doc-published/index"),
    );
    expect(mockedPost.mock.calls.some(([path]) => String(path).includes("submit-review"))).toBe(false);
  });

  it("失败资料重试：先查失败任务再 POST retry", async () => {
    renderPage(<DocumentsPage />);
    const failedRow = (await screen.findByText("失败资料")).closest("tr")!;
    fireEvent.click(within(failedRow).getByRole("button", { name: "重试" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/rag/jobs/job-failed-1/retry"),
    );
    expect(mockedGet).toHaveBeenCalledWith(
      "/api/rag/jobs",
      expect.objectContaining({ document_id: "doc-failed", status: "failed" }),
    );
  });

  it("删除 409 时透传后端「已发布资料只能归档」话术", async () => {
    mockedDelete.mockRejectedValue(
      new ApiRequestError(409, "INVALID_STATE", "已发布资料只能归档，不能物理删除"),
    );
    renderPage(<DocumentsPage />);
    const draftRow = (await screen.findByText("草稿资料")).closest("tr")!;
    fireEvent.click(within(draftRow).getByRole("button", { name: "删除" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认删除" }));
    await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith("/api/rag/documents/doc-draft"));
    expect(document.querySelector(".toast-container")).not.toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 上传 */

describe("UploadPage（PRD-03 §5）", () => {
  beforeEach(() => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/source-ledgers") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/graph/nodes") return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error(`未打桩的 GET ${path}`));
    });
    mockedPostForm.mockResolvedValue({
      document: makeDoc({ id: "doc-new", title: "上传的规范", status: "indexed", chunk_count: 2 }),
      jobs: [],
    });
  });

  function fillRequired() {
    fireEvent.change(screen.getByLabelText("选择文件"), {
      target: { files: [new File(["# 规范内容"], "spec.md", { type: "text/markdown" })] },
    });
    fireEvent.click(screen.getByRole("combobox", { name: "资料类型" }));
    fireEvent.click(screen.getByRole("option", { name: "规范" }));
    fireEvent.change(screen.getByPlaceholderText("例如：工业和信息化部 / 张老师"), {
      target: { value: "工业和信息化部" },
    });
    fireEvent.change(screen.getByPlaceholderText("例如：1.0"), { target: { value: "2.3" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "文本" }));
  }

  it("仅选择文件即可提交，并将空高级元数据交给服务端默认", async () => {
    renderPage(<UploadPage />);
    // The simplified flow makes publication depend on a successful index,
    // rather than exposing a separate approval surface to administrators.
    expect(screen.getAllByText(/成功后自动发布到学生端/).length).toBeGreaterThan(0);
    const selected = new File(["# 规范内容"], "spec.md", { type: "text/markdown" });
    fireEvent.change(screen.getByLabelText("选择文件"), {
      target: { files: [selected] },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认上传" }));
    await waitFor(() => expect(mockedPostForm).toHaveBeenCalledTimes(1));
    const [path, form] = mockedPostForm.mock.calls[0] as unknown as [string, FormData];
    expect(path).toBe("/api/rag/documents");
    expect(form.get("file")).toBe(selected);
    // The title is prefilled from the filename for clarity; all other blank
    // advanced values stay absent so the API owns auditable safe defaults.
    expect(form.get("title")).toBe("spec");
    expect(form.get("source_type")).toBeNull();
    expect(form.get("source_name")).toBeNull();
    expect(form.get("version")).toBeNull();
    expect(form.get("license_status")).toBeNull();
    expect(form.get("visibility")).toBeNull();
    expect(form.getAll("data_types")).toEqual([]);
  });

  it("未选择文件时前端拦截上传", async () => {
    renderPage(<UploadPage />);
    fireEvent.click(screen.getByRole("button", { name: "确认上传" }));
    expect((await screen.findAllByText("请选择要上传的文件")).length).toBeGreaterThan(0);
    expect(mockedPostForm).not.toHaveBeenCalled();
  });

  it("合法提交：multipart 多值字段同名重复 append", async () => {
    renderPage(<UploadPage />);
    fillRequired();
    fireEvent.click(screen.getByRole("combobox", { name: "授权状态" }));
    fireEvent.click(screen.getByRole("option", { name: "已授权" }));
    fireEvent.click(screen.getByRole("button", { name: "确认上传" }));
    await waitFor(() => expect(mockedPostForm).toHaveBeenCalledTimes(1));
    const [path, form] = mockedPostForm.mock.calls[0] as unknown as [string, FormData];
    expect(path).toBe("/api/rag/documents");
    expect(form.get("title")).toBe("spec"); // 文件名兜底标题
    expect(form.get("source_type")).toBe("standard");
    expect(form.get("source_name")).toBe("工业和信息化部");
    expect(form.get("license_status")).toBe("authorized");
    expect(form.get("visibility")).toBeNull();
    expect(form.getAll("data_types")).toEqual(["text"]);
    expect(form.get("auto_submit")).toBeNull();
    expect(await screen.findByText(/索引成功后将提供学生召回/)).toBeInTheDocument();
  });

  it("选择多个文件后批量导入并自动处理", async () => {
    mockedPostForm.mockResolvedValue({
      files: { total: 2, imported: 2, failed: 0, queued: 2 },
      auto_publish: true,
    });
    renderPage(<UploadPage />);
    fireEvent.change(screen.getByLabelText("选择多个文件"), {
      target: {
        files: [
          new File(["# one"], "one.md", { type: "text/markdown" }),
          new File(["two"], "two.txt", { type: "text/plain" }),
        ],
      },
    });
    fireEvent.click(screen.getByRole("combobox", { name: "资料类型" }));
    fireEvent.click(screen.getByRole("option", { name: "规范" }));
    fireEvent.change(screen.getByPlaceholderText("例如：工业和信息化部 / 张老师"), {
      target: { value: "工业和信息化部" },
    });
    fireEvent.change(screen.getByPlaceholderText("例如：1.0"), { target: { value: "2.3" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "文本" }));
    fireEvent.click(screen.getByRole("combobox", { name: "授权状态" }));
    fireEvent.click(screen.getByRole("option", { name: "已授权" }));
    fireEvent.click(screen.getByRole("button", { name: "导入所选资料并自动处理" }));
    await waitFor(() =>
      expect(mockedPostForm).toHaveBeenCalledTimes(1),
    );
    const [path, form] = mockedPostForm.mock.calls[0] as unknown as [string, FormData];
    expect(path).toBe("/api/rag/documents/batch-import");
    expect(form.getAll("files").map((value) => (value as File).name)).toEqual(["one.md", "two.txt"]);
    // Visibility remains a server-owned default when the simplified form
    // omits it, keeping batch imports on the same safety path as one file.
    expect(form.get("visibility")).toBeNull();
    expect(form.get("auto_publish")).toBeNull();
    expect(await screen.findByText(/批量结果：共 2 个，导入 2 个/)).toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 切片编辑器 */

describe("ChunkEditorPage（PRD-03 §8）", () => {
  const CHUNKS = [
    makeChunk({ id: "c1", chunk_index: 0, content: "第一段内容。第二句。" }),
    makeChunk({
      id: "c2",
      chunk_index: 1,
      content: "第三段内容。第四句。",
      section_title: "第二章",
    }),
  ];

  beforeEach(() => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/rag/documents/doc1")
        return Promise.resolve({ document: makeDoc({ id: "doc1", title: "切片文档" }) });
      if (path === "/api/rag/documents/doc1/chunks")
        return Promise.resolve({ items: CHUNKS, total: CHUNKS.length });
      return Promise.reject(new Error(`未打桩的 GET ${path}`));
    });
    mockedPost.mockResolvedValue({ chunk: CHUNKS[0], chunks: CHUNKS });
    mockedPatch.mockResolvedValue({ chunk: CHUNKS[0] });
  });

  function renderEditor() {
    return renderWithRoute(
      <ChunkEditorPage />,
      "/admin/rag/documents/:id/chunks",
      "/admin/rag/documents/doc1/chunks",
    );
  }

  it("拆分携带字符偏移载荷", async () => {
    renderEditor();
    // Responsive columns belong to operations CSS, not a fixed inline grid,
    // so the editor can collapse safely on the management workbench drawer.
    await waitFor(() =>
      expect(document.querySelector(".rag-chunk-editor-layout")).toBeInTheDocument(),
    );
    expect(await screen.findByText("编辑切片 #0")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("留空自动"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "拆分" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/rag/chunks/c1/split", { at: 5 }),
    );
  });

  it("拆分留空时不传 at（后端自动取中点句读）", async () => {
    renderEditor();
    expect(await screen.findByText("编辑切片 #0")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "拆分" }));
    await waitFor(() => expect(mockedPost).toHaveBeenCalledWith("/api/rag/chunks/c1/split", {}));
  });

  it("合并所选提交 chunk_ids（按 chunk_index 排序）", async () => {
    renderEditor();
    expect(await screen.findByText("编辑切片 #0")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "选择切片 #1 用于合并" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择切片 #0 用于合并" }));
    fireEvent.click(screen.getByRole("button", { name: /合并所选/ }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/rag/chunks/merge", {
        chunk_ids: ["c1", "c2"],
      }),
    );
  });

  it("修改内容保存走 PATCH 且提示自动重嵌入", async () => {
    renderEditor();
    expect(await screen.findByText("编辑切片 #0")).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue("第一段内容。第二句。"), {
      target: { value: "改写后的切片内容" },
    });
    fireEvent.click(screen.getByRole("button", { name: /保存修改/ }));
    await waitFor(() =>
      expect(mockedPatch).toHaveBeenCalledWith("/api/rag/chunks/c1", {
        content: "改写后的切片内容",
      }),
    );
    expect(document.querySelector(".toast-container")).not.toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 任务队列 */

describe("JobsPage（PRD-03 §7）", () => {
  const FAILED_JOB = {
    id: "job-1",
    document_id: "doc1",
    stage: "parse",
    status: "failed",
    idempotency_key: "k1",
    progress: 0.4,
    error_code: "PARSE_EMPTY_TEXT",
    error_message: "未解析出文本",
    attempt: 1,
    params: {},
    created_at: "2026-07-01T00:00:00Z",
    started_at: "2026-07-01T00:00:01Z",
    finished_at: "2026-07-01T00:00:03Z",
  };

  beforeEach(() => {
    mockedGet.mockImplementation((path: string, query?: Record<string, unknown>) => {
      if (path === "/api/rag/jobs") {
        // 概览计数查询：limit=1 按 status 返回 total
        if (query?.limit === 1) {
          const totals: Record<string, number> = { queued: 2, running: 1, succeeded: 9, failed: 1 };
          return Promise.resolve({ items: [], total: totals[String(query.status)] ?? 0 });
        }
        return Promise.resolve({ items: [FAILED_JOB], total: 1 });
      }
      if (path === "/api/rag/documents")
        return Promise.resolve({ items: [makeDoc({ id: "doc1", title: "客服规范" })], total: 1 });
      return Promise.reject(new Error(`未打桩的 GET ${path}`));
    });
    mockedPost.mockResolvedValue({ run: {}, job: FAILED_JOB });
  });

  it("概览计数 + 失败任务可理解错误 + 重试", async () => {
    renderPage(<JobsPage />, "/admin/rag/jobs?status=failed");
    // 概览四卡
    expect(await screen.findByText("待处理")).toBeInTheDocument();
    expect(screen.getByText("处理中")).toBeInTheDocument();
    // 失败行：资料名映射、可理解错误（§7 验收）
    expect(await screen.findByText("客服规范")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "客服规范" })).toHaveAttribute(
      "href",
      "/admin/rag/documents/doc1?returnTo=%2Fadmin%2Frag%2Fjobs%3Fstatus%3Dfailed",
    );
    expect(screen.getByText(/PARSE_EMPTY_TEXT：未解析出文本/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(mockedPost).toHaveBeenCalledWith("/api/rag/jobs/job-1/retry"));
    expect(document.querySelector(".toast-container")).not.toBeInTheDocument();
  });

  it("首轮列表请求未完成时，手动刷新仍能重新加载", async () => {
    let listRequests = 0;
    mockedGet.mockImplementation((path: string, query?: Record<string, unknown>) => {
      if (path === "/api/rag/jobs") {
        if (query?.limit === 1) return Promise.resolve({ items: [], total: 0 });
        listRequests += 1;
        if (listRequests === 1) {
          // Keep the first lifecycle request pending to reproduce a lost/aborted fetch.
          return new Promise(() => undefined);
        }
        return Promise.resolve({ items: [FAILED_JOB], total: 1 });
      }
      if (path === "/api/rag/documents")
        return Promise.resolve({ items: [makeDoc({ id: "doc1", title: "客服规范" })], total: 1 });
      return Promise.reject(new Error(`未打桩的 GET ${path}`));
    });

    renderPage(<JobsPage />);
    await waitFor(() => expect(listRequests).toBe(1));
    fireEvent.click(screen.getByRole("button", { name: "刷新" }));

    expect(await screen.findByText("客服规范")).toBeInTheDocument();
    expect(listRequests).toBe(2);
    expect(screen.queryByText("加载中…")).not.toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 发布审核 */

describe("PublishReviewPage（PRD-03 §2 发布审核）", () => {
  const QUEUE_ITEM = {
    id: "d1",
    title: "待审规范",
    uploader_name: "张老师",
    source_type: "standard",
    data_types: ["text"],
    submitted_at: "2026-07-02T00:00:00Z",
  };

  beforeEach(() => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/rag/review-queue")
        return Promise.resolve({ items: [QUEUE_ITEM], total: 1 });
      if (path === "/api/rag/documents/d1")
        return Promise.resolve({
          document: makeDoc({
            id: "d1",
            title: "待审规范",
            status: "review_pending",
            chunk_count: 1,
          }),
          jobs: [],
          sensitive_flags: { phone: 1, id_card: 0, email: 0, block_publish: false },
          ledger: null,
          review_records: [],
        });
      if (path === "/api/rag/documents/d1/chunks")
        return Promise.resolve({ items: [makeChunk({ id: "ck-1" })], total: 1 });
      return Promise.reject(new Error(`未打桩的 GET ${path}`));
    });
    mockedPost.mockResolvedValue({ document: makeDoc({ id: "d1", status: "published" }) });
  });

  it("审核抽屉：敏感信息可见，按所选范围发布", async () => {
    renderPage(<PublishReviewPage />);
    fireEvent.click(await screen.findByRole("button", { name: "审核" }));
    // 抽屉：敏感信息告警 + 切片抽样
    expect(await screen.findByText(/手机号 1 处/)).toBeInTheDocument();
    expect(screen.getByText("切片抽样（前 3 条）")).toBeInTheDocument();
    // 选择"仅教师可见"再发布
    fireEvent.click(screen.getByRole("radio", { name: "仅教师可见" }));
    fireEvent.click(screen.getByRole("button", { name: "通过发布" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/rag/documents/d1/publish", {
        scope: "teacher",
      }),
    );
    expect(document.querySelector(".toast-container")).not.toBeInTheDocument();
  });

  it("驳回必须填审核意见", async () => {
    renderPage(<PublishReviewPage />);
    fireEvent.click(await screen.findByRole("button", { name: "审核" }));
    await screen.findByText("切片抽样（前 3 条）");
    fireEvent.click(screen.getByRole("button", { name: "驳回" }));
    expect(document.querySelector(".toast-container")).not.toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalledWith("/api/rag/documents/d1/reject", expect.anything());
    fireEvent.change(screen.getByPlaceholderText("例如：第 3 章缺少标注示例，请补充后重新送审"), {
      target: { value: "请补充示例后重报" },
    });
    fireEvent.click(screen.getByRole("button", { name: "驳回" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/rag/documents/d1/reject", {
        comment: "请补充示例后重报",
      }),
    );
  });
});
