/**
 * 系统管理端 RAG 体验：处理状态、详情只读信息、测试台用例页签。
 *
 * These tests stay separate from the legacy queue/editor coverage because the old
 * compatibility routes remain supported while their primary navigation is reduced.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ReactElement } from "react";
import { api } from "../src/api/client";
import { ToastProvider } from "../src/components";
import DocumentsPage from "../src/pages/rag/DocumentsPage";
import DocumentDetailPage from "../src/pages/rag/DocumentDetailPage";
import SearchTestPage from "../src/pages/rag/SearchTestPage";

vi.mock("../src/api/client", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    postForm: vi.fn(),
  },
}));

const mockedGet = vi.mocked(api.get);
const mockedPost = vi.mocked(api.post);

const doc = (overrides: Record<string, unknown> = {}) => ({
  id: "doc-1",
  title: "客服规范",
  file_type: "md",
  source_type: "standard",
  source_name: "国家标准出版社",
  source_url: "https://example.test/standard",
  source_ledger_id: "ledger-1",
  version: "2.0",
  license_status: "authorized",
  data_types: ["text"],
  cap_ids: [],
  visibility: "student",
  status: "parsing",
  file_hash: "hash",
  error_code: null,
  error_message: null,
  process_version: 2,
  created_by: "admin",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-02T00:00:00Z",
  published_at: null,
  expires_at: null,
  chunk_count: 21,
  ...overrides,
});

const chunk = (index: number) => ({
  id: `chunk-${index}`,
  document_id: "doc-1",
  chunk_index: index,
  content: `切片正文 ${index}`,
  summary: null,
  keywords: [],
  page_start: index + 1,
  page_end: index + 1,
  section_title: `第 ${index + 1} 节`,
  token_count: 10,
  embedding_model: "local-hash-512",
  metadata: {},
  status: "active",
  process_version: 2,
});

function renderPage(ui: ReactElement) {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={["/admin/rag"]}>{ui}</MemoryRouter>
    </ToastProvider>,
  );
}

function renderDetail() {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={["/admin/rag/documents/doc-1"]}>
        <Routes>
          <Route path="/admin/rag/documents/:id" element={<DocumentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("P1-1 知识库处理状态", () => {
  it("显示处理状态列并从失败任务入口重试", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/rag/documents") {
        return Promise.resolve({ items: [doc({ status: "failed", error_code: "PARSE_EMPTY_TEXT" })], total: 1 });
      }
      if (path === "/api/rag/jobs") return Promise.resolve({ items: [{ id: "job-1" }], total: 1 });
      return Promise.reject(new Error(`unexpected GET ${path}`));
    });
    mockedPost.mockResolvedValue({});

    renderPage(<DocumentsPage />);
    const title = await screen.findByText("客服规范");
    expect(screen.getByRole("columnheader", { name: "处理状态" })).toBeInTheDocument();
    expect(screen.getByText("失败")).toBeInTheDocument();
    fireEvent.click(title.closest("tr")!.querySelector('button[aria-label="重试"]') ?? screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(mockedPost).toHaveBeenCalledWith("/api/rag/jobs/job-1/retry"));
  });
});

describe("P1-1 资料详情", () => {
  it("展示来源元数据和前 20 条只读切片预览", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/rag/documents/doc-1") {
        return Promise.resolve({
          document: doc({ status: "published" }),
          jobs: [],
          sensitive_flags: null,
          ledger: {
            id: "ledger-1",
            source_code: "STD-001",
            name: "客服规范台账",
            publisher: "标准出版社",
            source_type: "standard",
            version: "2026",
            authorization_status: "approved",
            valid_from: "2026-01-01T00:00:00Z",
            valid_to: "2027-01-01T00:00:00Z",
            related_document_ids: ["doc-1"],
            review_status: "reviewed",
            notes: "仅用于教学",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
            risk_expired: false,
            risk_unauthorized: false,
            risk_no_documents: false,
          },
          review_records: [
            {
              id: "review-1",
              action: "approve",
              reviewer_id: "reviewer-1",
              comment: "legacy review record",
              created_at: "2026-08-01T00:00:00Z",
            },
          ],
        });
      }
      if (path === "/api/rag/documents/doc-1/chunks") {
        return Promise.resolve({ items: Array.from({ length: 21 }, (_, index) => chunk(index)), total: 21 });
      }
      if (path === "/api/rag/documents/doc-1/recall-records") return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error(`unexpected GET ${path}`));
    });

    renderDetail();
    expect(await screen.findByText("来源信息")).toBeInTheDocument();
    // Historical ledger/review payloads remain API-compatible but are no
    // longer rendered as active content on the new detail workflow.
    expect(screen.queryByText("STD-001")).not.toBeInTheDocument();
    expect(screen.queryByText("legacy review record")).not.toBeInTheDocument();
    expect(screen.queryByText("审核记录")).not.toBeInTheDocument();
    expect(screen.getByText("切片列表（只读预览，共 21 条）")).toBeInTheDocument();
    expect(screen.getByText("切片正文 0")).toBeInTheDocument();
    expect(screen.getByText("切片正文 19")).toBeInTheDocument();
    expect(screen.queryByText("切片正文 20")).not.toBeInTheDocument();
  });
});

describe("P1-1 召回测试台页签", () => {
  it("加载已保存用例后恢复测试台表单", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/rag/documents") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/rag/eval-cases") {
        return Promise.resolve({
          items: [
            {
              id: "case-1",
              question: "规范如何判定？",
              expected_answer: "按第三章",
              must_hit_document_ids: [],
              must_hit_chunk_ids: [],
              filters: { data_type: "text", published_only: true, document_ids: null, top_k: 7 },
              created_by: "admin",
              created_at: "2026-08-02T00:00:00Z",
            },
          ],
          total: 1,
        });
      }
      return Promise.reject(new Error(`unexpected GET ${path}`));
    });

    renderPage(<SearchTestPage />);
    fireEvent.click(screen.getByRole("tab", { name: "已保存用例" }));
    expect(await screen.findByText("规范如何判定？")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "加载用例：规范如何判定？" }));
    expect(screen.getByRole("tab", { name: "测试台" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByPlaceholderText("例如：语音标注中情感标签的判定规则是什么？")).toHaveValue("规范如何判定？");
    expect(screen.getByPlaceholderText("例如：5")).toHaveValue("7");
  });
});
