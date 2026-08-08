/**
 * RAG 管理端页面测试（PRD-03）：资料库状态操作 / 上传校验 / 切片编辑 /
 * 任务重试 / 召回测试 / 评测运行 / 发布审核。
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
import SearchTestPage from "../src/pages/rag/SearchTestPage";
import EvalCasesPage from "../src/pages/rag/EvalCasesPage";
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

/** 带路由参数的页面渲染（ChunkEditor 需要 :id） */
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
    scenario_ids: [],
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
    // 审核状态派生徽章（筛选下拉也有同名 option，故用 getAllByText）
    expect(screen.getAllByText("待审核").length).toBeGreaterThan(0);
    expect(screen.getAllByText("已通过").length).toBeGreaterThan(0);
    // 行操作：indexed→送审；review_pending→发布审核链接；published→归档+重新索引；failed→重试；draft→删除
    const indexedRow = screen.getByText("已索引资料").closest("tr")!;
    expect(within(indexedRow).getByRole("button", { name: "送审" })).toBeInTheDocument();
    const reviewRow = screen.getByText("待审核资料").closest("tr")!;
    expect(within(reviewRow).getByRole("link", { name: "发布审核" })).toHaveAttribute(
      "href",
      "/rag-admin/publish",
    );
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
      "/rag-admin/documents/doc-indexed",
    );
  });

  it("送审/重新索引触发对应端点", async () => {
    renderPage(<DocumentsPage />);
    const indexedRow = (await screen.findByText("已索引资料")).closest("tr")!;
    fireEvent.click(within(indexedRow).getByRole("button", { name: "送审" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/rag/documents/doc-indexed/submit-review"),
    );
    const publishedRow = screen.getByText("已发布资料").closest("tr")!;
    fireEvent.click(within(publishedRow).getByRole("button", { name: "重新索引" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/rag/documents/doc-published/index"),
    );
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

  it("未填授权状态时前端拦截上传（§5.3 验收）", async () => {
    renderPage(<UploadPage />);
    fillRequired();
    fireEvent.click(screen.getByRole("button", { name: "确认上传" }));
    expect(await screen.findByText("请选择授权状态（未填授权状态不得上传）")).toBeInTheDocument();
    expect(mockedPostForm).not.toHaveBeenCalled();
  });

  it("未填来源时前端拦截上传（§5.3 验收）", async () => {
    renderPage(<UploadPage />);
    // 只选文件 + 授权状态，不填来源
    fireEvent.change(screen.getByLabelText("选择文件"), {
      target: { files: [new File(["x"], "a.md", { type: "text/markdown" })] },
    });
    fireEvent.click(screen.getByRole("combobox", { name: "资料类型" }));
    fireEvent.click(screen.getByRole("option", { name: "教材" }));
    fireEvent.change(screen.getByPlaceholderText("例如：1.0"), { target: { value: "1.0" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "文本" }));
    fireEvent.click(screen.getByRole("combobox", { name: "授权状态" }));
    fireEvent.click(screen.getByRole("option", { name: "已授权" }));
    fireEvent.click(screen.getByRole("button", { name: "确认上传" }));
    expect(await screen.findByText("请填写来源（未填来源不得上传）")).toBeInTheDocument();
    expect(mockedPostForm).not.toHaveBeenCalled();
  });

  it("合法提交：multipart 多值字段同名重复 append", async () => {
    renderPage(<UploadPage />);
    fillRequired();
    fireEvent.click(screen.getByRole("combobox", { name: "授权状态" }));
    fireEvent.click(screen.getByRole("option", { name: "已授权" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "智能客服标注" }));
    fireEvent.click(screen.getByRole("button", { name: "确认上传" }));
    await waitFor(() => expect(mockedPostForm).toHaveBeenCalledTimes(1));
    const [path, form] = mockedPostForm.mock.calls[0] as unknown as [string, FormData];
    expect(path).toBe("/api/rag/documents");
    expect(form.get("title")).toBe("spec"); // 文件名兜底标题
    expect(form.get("source_type")).toBe("standard");
    expect(form.get("source_name")).toBe("工业和信息化部");
    expect(form.get("license_status")).toBe("authorized");
    expect(form.get("visibility")).toBe("teacher");
    expect(form.getAll("data_types")).toEqual(["text"]);
    expect(form.getAll("scenario_ids")).toEqual(["SCN-CUSTOMER-SERVICE-001"]);
    expect(form.get("auto_submit")).toBe("false");
    // 成功态：提示进入处理队列并可看解析日志（§5.3）
    expect(await screen.findByText(/已进入异步处理队列/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看解析日志（任务队列）" })).toHaveAttribute(
      "href",
      "/rag-admin/jobs",
    );
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
      "/rag-admin/documents/:id/chunks",
      "/rag-admin/documents/doc1/chunks",
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
    renderPage(<JobsPage />);
    // 概览四卡
    expect(await screen.findByText("待处理")).toBeInTheDocument();
    expect(screen.getByText("处理中")).toBeInTheDocument();
    // 失败行：资料名映射、可理解错误（§7 验收）
    expect(await screen.findByText("客服规范")).toBeInTheDocument();
    expect(screen.getByText(/PARSE_EMPTY_TEXT：未解析出文本/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(mockedPost).toHaveBeenCalledWith("/api/rag/jobs/job-1/retry"));
    expect(document.querySelector(".toast-container")).not.toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 召回测试台 */

describe("SearchTestPage（PRD-03 §10）", () => {
  const HIT_A = {
    chunk_id: "ck-a",
    document_id: "d1",
    title: "客服规范",
    section_title: "第三章",
    page_start: 5,
    page_end: 5,
    version: "2.3",
    content: "情感标签判定规则正文……",
    score: 0.91,
    rerank_score: 0.88,
  };
  const HIT_B = {
    ...HIT_A,
    chunk_id: "ck-b",
    document_id: "d2",
    title: "车载指南",
    score: 0.8,
    rerank_score: 0.95,
  };

  beforeEach(() => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/rag/documents")
        return Promise.resolve({
          items: [
            makeDoc({ id: "d1", title: "客服规范" }),
            makeDoc({ id: "d2", title: "车载指南" }),
          ],
          total: 2,
        });
      return Promise.reject(new Error(`未打桩的 GET ${path}`));
    });
    mockedPost.mockImplementation((path: string) => {
      if (path === "/api/rag/search-test")
        return Promise.resolve({
          vector_results: [HIT_A, HIT_B],
          reranked_results: [HIT_B, HIT_A],
          rerank_note: null,
          below_threshold: false,
          notice: null,
          diagnostics: {
            latency_ms: 42,
            embedding_model: "local-hash-512",
            rerank_model: "provider-rerank",
            filters: {
              scenario_id: null,
              data_type: null,
              published_only: true,
              document_ids: null,
            },
            prompt_template_version: "v1",
          },
        });
      if (path === "/api/rag/query")
        return Promise.resolve({
          answer: "这是答案草稿",
          steps: [],
          notes: [],
          followups: [],
          citations: [
            {
              document_id: "d1",
              title: "客服规范",
              section_title: "第三章",
              page_start: 5,
              page_end: 5,
              version: "2.3",
              score: 0.91,
            },
          ],
          related_cap_ids: [],
          refused: false,
          notice: null,
        });
      if (path === "/api/rag/eval-cases") return Promise.resolve({ case: { id: "case-new" } });
      return Promise.reject(new Error(`未打桩的 POST ${path}`));
    });
  });

  it("双列展示原始召回与重排后 + 诊断信息 + 生成回答", async () => {
    renderPage(<SearchTestPage />);
    fireEvent.change(screen.getByPlaceholderText("例如：语音标注中情感标签的判定规则是什么？"), {
      target: { value: "情感标签怎么判？" },
    });
    fireEvent.click(screen.getByRole("button", { name: "运行召回测试" }));
    // 双列（§10 验收）
    expect(await screen.findByText("原始召回（2）")).toBeInTheDocument();
    expect(screen.getByText("重排后（2）")).toBeInTheDocument();
    // 命中卡：相似度与来源位置
    expect(screen.getAllByText("相似度 0.910").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/第 5 页/).length).toBeGreaterThan(0);
    // 诊断信息
    expect(screen.getByText("42ms")).toBeInTheDocument();
    expect(screen.getByText("provider-rerank")).toBeInTheDocument();
    // 生成回答（与学生端同路径）
    expect(await screen.findByText("这是答案草稿")).toBeInTheDocument();
    expect(screen.getByText("引用来源")).toBeInTheDocument();
  });

  it("保存为评测用例：必须命中文档按召回预填", async () => {
    renderPage(<SearchTestPage />);
    fireEvent.change(screen.getByPlaceholderText("例如：语音标注中情感标签的判定规则是什么？"), {
      target: { value: "情感标签怎么判？" },
    });
    fireEvent.click(screen.getByRole("button", { name: "运行召回测试" }));
    fireEvent.click(await screen.findByRole("button", { name: "保存为评测用例" }));
    fireEvent.change(screen.getByPlaceholderText("期望回答的要点…"), {
      target: { value: "应引用客服规范第三章" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存用例" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/rag/eval-cases",
        expect.objectContaining({
          question: "情感标签怎么判？",
          expected_answer: "应引用客服规范第三章",
          must_hit_document_ids: ["d2", "d1"],
        }),
      ),
    );
    expect(document.querySelector(".toast-container")).not.toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 评测集 */

describe("EvalCasesPage（PRD-03 §11）", () => {
  const CASE = {
    id: "case-1",
    question: "情感标签判定规则？",
    expected_answer: "见客服规范第三章",
    must_hit_document_ids: ["d1"],
    must_hit_chunk_ids: [],
    filters: {},
    created_by: "user-1",
    created_at: "2026-07-01T00:00:00Z",
  };

  beforeEach(() => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/rag/eval-cases") return Promise.resolve({ items: [CASE], total: 1 });
      if (path === "/api/rag/documents") return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error(`未打桩的 GET ${path}`));
    });
    mockedPost.mockResolvedValue({
      id: "run-1",
      status: "completed",
      metrics: {
        recall_at_k: 1,
        citation_accuracy: 0.5,
        refusal_accuracy: null,
        answer_faithfulness: 0.92,
        latency_ms_avg: 120.4,
        case_count: 1,
      },
      case_results: [
        {
          case_id: "case-1",
          question: CASE.question,
          refused: false,
          hit_document_ids: ["d1"],
          hit_chunk_ids: ["ck-a"],
          recall_hit: true,
          citation_ok: false,
          refusal_ok: null,
          faithfulness: 0.92,
          latency_ms: 120,
        },
      ],
      created_by: "user-1",
      created_at: "2026-07-02T00:00:00Z",
      finished_at: "2026-07-02T00:00:05Z",
    });
  });

  it("运行全部评测 → 指标卡 + 逐用例结果（§11 五指标）", async () => {
    renderPage(<EvalCasesPage />);
    expect(await screen.findByText("情感标签判定规则？")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "运行全部评测" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/rag/eval-runs", { case_ids: null }),
    );
    // 五张指标卡（含中文说明；历史对比区也有同名指标标签，故用 getAllByText）
    expect((await screen.findAllByText("Recall@K")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Citation Accuracy").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Answer Faithfulness").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Refusal Accuracy").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Latency").length).toBeGreaterThan(0);
    expect(screen.getAllByText("100%").length).toBeGreaterThan(0); // recall 1（卡片 + 趋势条）
    expect(screen.getAllByText("50%").length).toBeGreaterThan(0); // citation 0.5
    expect(screen.getAllByText("120ms").length).toBeGreaterThan(0); // 卡片与逐用例行
    expect(screen.getByText(/本次无样本/)).toBeInTheDocument(); // refusal null 不显示 0
    // 逐用例：命中 ✓ / 引用 ✗
    expect(screen.getByText("逐用例结果")).toBeInTheDocument();
    expect(screen.getByText("✓")).toBeInTheDocument();
    expect(screen.getByText("✗")).toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 发布审核 */

describe("PublishReviewPage（PRD-03 §2 发布审核）", () => {
  const QUEUE_ITEM = {
    id: "d1",
    title: "待审规范",
    uploader_name: "张老师",
    source_type: "standard",
    scenario_ids: ["SCN-CUSTOMER-SERVICE-001"],
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
