/**
 * RAG-ADMIN + SYSTEM-ADMIN 增强测试：资料批量操作 / 资料详情召回记录 /
 * 上传 csv+xlsx / 系统告警。
 *
 * api 层整体打桩（与 rag-admin-pages.test.tsx 同一模式）：断言页面触发的
 * 端点与载荷符合 rag_admin.py / admin.py 契约，后端中文话术原样透传。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ReactElement } from "react";
import { api } from "../src/api/client";
import { ToastProvider } from "../src/components";
import DocumentsPage from "../src/pages/rag/DocumentsPage";
import DocumentDetailPage from "../src/pages/rag/DocumentDetailPage";
import UploadPage from "../src/pages/rag/UploadPage";
import SecurityPage from "../src/pages/admin/SecurityPage";

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

function renderPage(ui: ReactElement, route = "/") {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </ToastProvider>,
  );
}

/** 带路由参数的页面渲染（资料详情需要 :id） */
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

beforeEach(() => {
  vi.clearAllMocks();
});

/* ---------------------------------------------------------------- 资料批量操作 */

describe("DocumentsPage 批量操作（PRD-03 §7）", () => {
  const DOCS = [
    makeDoc({ id: "doc-indexed", title: "已索引资料", status: "indexed" }),
    makeDoc({ id: "doc-draft", title: "草稿资料", status: "draft" }),
  ];

  beforeEach(() => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/rag/documents") return Promise.resolve({ items: DOCS, total: DOCS.length });
      return Promise.reject(new Error(`未打桩的 GET ${path}`));
    });
    mockedPost.mockImplementation((path: string) => {
      if (path === "/api/rag/documents/batch")
        // Batch remains useful for reindex/archive; the retired review action
        // is intentionally absent from the active page contract.
        return Promise.resolve({
          results: [
            { id: "doc-indexed", ok: true },
            {
              id: "doc-draft",
              ok: false,
              code: "INVALID_STATE",
              message: "当前状态不可重建索引",
            },
          ],
        });
      return Promise.resolve({});
    });
  });

  it("选中 2 项 → 批量重新索引 → 校验载荷并展示部分成功结果弹窗", async () => {
    renderPage(<DocumentsPage />);
    expect(await screen.findByText("已索引资料")).toBeInTheDocument();

    // 逐行勾选 2 项 → 批量操作条出现
    fireEvent.click(screen.getByRole("checkbox", { name: "选择资料：已索引资料" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择资料：草稿资料" }));
    expect(screen.getByText("已选 2 项")).toBeInTheDocument();

    // 批量重建索引 → 二次确认；审核不再是资料库的活动动作。
    fireEvent.click(screen.getByRole("button", { name: "批量重新索引" }));
    expect(await screen.findByText(/按当前系统切片参数/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认重建" }));

    // 载荷符合 POST /api/rag/documents/batch 契约（ids + action）
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/rag/documents/batch", {
        ids: ["doc-indexed", "doc-draft"],
        action: "reindex",
      }),
    );

    // 结果弹窗：成功/失败汇总 + 失败项透传后端中文原因
    expect(await screen.findByText(/成功 1 项/)).toBeInTheDocument();
    expect(screen.getByText(/当前状态不可重建索引/)).toBeInTheDocument();
    expect(screen.getByText(/「已索引资料」/)).toBeInTheDocument();
  });

  it("批量归档确认话术明示「学生端不再召回」", async () => {
    renderPage(<DocumentsPage />);
    expect(await screen.findByText("已索引资料")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "选择资料：已索引资料" }));
    fireEvent.click(screen.getByRole("button", { name: "批量归档" }));
    // 高危动作后果必须讲清（归档影响学生端召回）
    expect(await screen.findByText(/学生端不再召回这些资料/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认归档" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/rag/documents/batch", {
        ids: ["doc-indexed"],
        action: "archive",
      }),
    );
  });
});

/* ---------------------------------------------------------------- 资料详情召回记录 */

describe("DocumentDetailPage 召回记录（PRD-03 §6）", () => {
  const DETAIL = {
    document: makeDoc({ id: "doc1", title: "客服规范", status: "published", cap_ids: [] }),
    jobs: [],
    sensitive_flags: null,
    ledger: null,
    review_records: [],
  };

  function mockDetail(recall: { items: unknown[]; total: number }) {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/rag/documents/doc1") return Promise.resolve(DETAIL);
      if (path === "/api/rag/documents/doc1/chunks") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/rag/documents/doc1/recall-records") return Promise.resolve(recall);
      return Promise.reject(new Error(`未打桩的 GET ${path}`));
    });
  }

  function renderDetail() {
    return renderWithRoute(
      <DocumentDetailPage />,
      "/admin/rag/documents/:id",
      "/admin/rag/documents/doc1",
    );
  }

  it("渲染召回记录表格：查询/渠道中文标签/相似度/用户", async () => {
    mockDetail({
      items: [
        {
          id: "r1",
          query: "情感标签怎么判？",
          channel: "student_query",
          score: 0.91,
          chunk_id: "ck1",
          user_id: "u1",
          user_name: "张同学",
          created_at: "2026-07-30T08:00:00Z",
        },
        {
          id: "r2",
          query: "车载唤醒词要求",
          channel: "search_test",
          score: 0.8,
          chunk_id: "ck2",
          user_id: null,
          user_name: null,
          created_at: "2026-07-29T08:00:00Z",
        },
      ],
      total: 2,
    });
    renderDetail();
    expect(await screen.findByText("情感标签怎么判？")).toBeInTheDocument();
    expect(screen.getByText("学生问答")).toBeInTheDocument();
    expect(screen.getByText("历史管理检索")).toBeInTheDocument();
    expect(screen.getByText("0.910")).toBeInTheDocument();
    expect(screen.getByText("张同学")).toBeInTheDocument();
    // 分页摘要（共 2 条 · 第 1 / 1 页）
    expect(screen.getByText(/共 2 条 · 第 1 \/ 1 页/)).toBeInTheDocument();
  });

  it("无记录时显示空态「暂无召回记录」", async () => {
    mockDetail({ items: [], total: 0 });
    renderDetail();
    expect(await screen.findByText("暂无召回记录")).toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 上传类型扩展 */

describe("UploadPage 文件类型扩展（csv/xlsx）", () => {
  beforeEach(() => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/source-ledgers") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/graph/nodes") return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error(`未打桩的 GET ${path}`));
    });
  });

  it("accept 含 csv/xlsx，选择 xlsx 文件不再报类型错误", async () => {
    renderPage(<UploadPage />);
    const input = screen.getByLabelText("选择文件");
    expect(input).toHaveAttribute("accept", expect.stringContaining(".csv"));
    expect(input).toHaveAttribute("accept", expect.stringContaining(".xlsx"));
    // 类型提示文案覆盖六种格式
    expect(screen.getByText("支持 PDF/Word/Markdown/TXT/CSV/Excel")).toBeInTheDocument();

    fireEvent.change(input, {
      target: { files: [new File(["a,b\n1,2"], "标注表.xlsx")] },
    });
    // 选中成功：显示文件名，无类型错误
    expect(await screen.findByText("标注表.xlsx")).toBeInTheDocument();
    expect(screen.queryByText(/仅支持/)).not.toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------- 系统告警 */

describe("SecurityPage 系统告警（PRD-06 §13.2）", () => {
  it("critical 告警卡片：级别徽章/指标/阈值/当前值/评估时间", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/admin/alerts")
        return Promise.resolve({
          alerts: [
            {
              code: "AGENT_RUN_FAILURE_RATE",
              fingerprint: "a".repeat(64),
              level: "critical",
              message: "近 5 分钟智能体运行失败率超过阈值",
              metric: "agent_run_failure_rate_5m",
              threshold: 0.5,
              current: 0.8,
              since: "2026-07-30T00:00:00Z",
            },
          ],
          evaluated_at: "2026-08-01T00:00:00Z",
        });
      return Promise.reject(new Error(`未打桩的 GET ${path}`));
    });
    renderPage(<SecurityPage />);
    expect(await screen.findByText("近 5 分钟智能体运行失败率超过阈值")).toBeInTheDocument();
    expect(screen.getByText("严重")).toBeInTheDocument(); // critical → 红色徽章
    // rate 类指标按百分比格式化（阈值 0.5 → 50.0%，当前值 0.8 → 80.0%）
    expect(screen.getByText(/agent_run_failure_rate_5m/)).toBeInTheDocument();
    expect(screen.getByText(/50\.0%/)).toBeInTheDocument();
    expect(screen.getByText(/80\.0%/)).toBeInTheDocument();
    expect(screen.getByText(/统计窗口起点：/)).toBeInTheDocument();
    expect(screen.getByText(/评估时间：/)).toBeInTheDocument();
    // 既有策略卡不受影响
    expect(screen.getByText("登录限流")).toBeInTheDocument();
  });

  it("无告警时显示绿色「当前无告警」卡片", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/admin/alerts")
        return Promise.resolve({ alerts: [], evaluated_at: "2026-08-01T00:00:00Z" });
      return Promise.reject(new Error(`未打桩的 GET ${path}`));
    });
    renderPage(<SecurityPage />);
    expect(await screen.findByText(/当前无告警/)).toBeInTheDocument();
    expect(screen.getByText("审计覆盖")).toBeInTheDocument(); // 第 11 张策略卡仍在
  });

  it("按管理员忽略告警并从当前列表移除", async () => {
    const fingerprint = "b".repeat(64);
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/admin/alerts")
        return Promise.resolve({
          alerts: [
            {
              code: "AGENT_RUN_FAILURE_RATE",
              fingerprint,
              level: "critical",
              message: "需要忽略的运行告警",
              metric: "agent_run_failure_rate_5m",
              threshold: 0.1,
              current: 0.4,
            },
          ],
          evaluated_at: "2026-08-01T00:00:00Z",
        });
      return Promise.reject(new Error(`未打桩的 GET ${path}`));
    });
    mockedPost.mockResolvedValue({ ignored: true, fingerprint });

    renderPage(<SecurityPage />);
    fireEvent.click(await screen.findByRole("button", { name: "忽略" }));

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(`/api/admin/alerts/${fingerprint}/ignore`),
    );
    await waitFor(() => expect(screen.queryByText("需要忽略的运行告警")).not.toBeInTheDocument());
    expect(screen.getByText(/当前无告警/)).toBeInTheDocument();
  });
});
