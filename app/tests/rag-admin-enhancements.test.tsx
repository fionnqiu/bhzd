/**
 * RAG-ADMIN + SYSTEM-ADMIN 增强测试：资料批量操作 / 资料详情召回记录 /
 * 评测历史（服务端数据源）/ 上传 csv+xlsx / 系统告警。
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
import EvalCasesPage from "../src/pages/rag/EvalCasesPage";
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
        // 部分成功：indexed 可送审，draft 被后端守卫拒绝（后端是资格唯一权威）
        return Promise.resolve({
          results: [
            { id: "doc-indexed", ok: true },
            {
              id: "doc-draft",
              ok: false,
              code: "INVALID_STATE",
              message: "当前状态不可送审，请先完成解析与索引",
            },
          ],
        });
      return Promise.resolve({});
    });
  });

  it("选中 2 项 → 批量送审 → 校验载荷并展示部分成功结果弹窗", async () => {
    renderPage(<DocumentsPage />);
    expect(await screen.findByText("已索引资料")).toBeInTheDocument();

    // 逐行勾选 2 项 → 批量操作条出现
    fireEvent.click(screen.getByRole("checkbox", { name: "选择资料：已索引资料" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择资料：草稿资料" }));
    expect(screen.getByText("已选 2 项")).toBeInTheDocument();

    // 批量送审 → 二次确认（讲清后果与资格提示）
    fireEvent.click(screen.getByRole("button", { name: "批量送审" }));
    expect(await screen.findByText(/已选 2 项资料提交送审/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认送审" }));

    // 载荷符合 POST /api/rag/documents/batch 契约（ids + action）
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/rag/documents/batch", {
        ids: ["doc-indexed", "doc-draft"],
        action: "submit_review",
      }),
    );

    // 结果弹窗：成功/失败汇总 + 失败项透传后端中文原因
    expect(await screen.findByText(/成功 1 项/)).toBeInTheDocument();
    expect(screen.getByText(/当前状态不可送审，请先完成解析与索引/)).toBeInTheDocument();
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
      "/rag-admin/documents/:id",
      "/rag-admin/documents/doc1",
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
    expect(screen.getByText("召回测试")).toBeInTheDocument();
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

/* ---------------------------------------------------------------- 评测历史（服务端数据源） */

describe("EvalCasesPage 历史对比（GET /api/rag/eval-runs）", () => {
  const RUN = {
    id: "run-h1",
    status: "completed",
    metrics: {
      recall_at_k: 0.8,
      citation_accuracy: 0.5,
      refusal_accuracy: null,
      answer_faithfulness: 0.92,
      latency_ms_avg: 120.4,
      case_count: 2,
    },
    created_at: "2026-07-29T00:00:00Z",
    finished_at: "2026-07-29T00:01:00Z",
  };

  beforeEach(() => {
    mockedGet.mockImplementation((path: string) => {
      if (path === "/api/rag/eval-cases") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/rag/documents") return Promise.resolve({ items: [], total: 0 });
      if (path === "/api/rag/eval-runs") return Promise.resolve({ items: [RUN], total: 1 });
      if (path === "/api/rag/eval-runs/run-h1")
        // 列表不携带 case_results，展开时按需拉详情
        return Promise.resolve({
          ...RUN,
          case_results: [
            {
              case_id: "case-1",
              question: "情感标签判定规则？",
              refused: false,
              hit_document_ids: ["d1"],
              hit_chunk_ids: ["ck-a"],
              recall_hit: true,
              citation_ok: false,
              refusal_ok: null,
              faithfulness: 0.92,
              latency_ms: 118,
            },
          ],
        });
      return Promise.reject(new Error(`未打桩的 GET ${path}`));
    });
  });

  it("历史列表来自服务端（不读 localStorage），点击展开逐用例结果", async () => {
    const getItemSpy = vi.spyOn(Storage.prototype, "getItem");
    try {
      renderPage(<EvalCasesPage />);
      // 历史卡片渲染 API 数据（localStorage 无任何记录也能显示）
      expect(await screen.findByText("历史对比（最近 1 次运行）")).toBeInTheDocument();
      expect(mockedGet).toHaveBeenCalledWith(
        "/api/rag/eval-runs",
        { limit: 10 },
        expect.objectContaining({ signal: expect.anything() }),
      );
      // 五指标 mini-row：recall 0.8 → 80%，latency → 120ms，无样本 → —
      expect(screen.getByText("80%")).toBeInTheDocument();
      expect(screen.getByText("120ms")).toBeInTheDocument();
      // 旧 localStorage 方案已移除
      expect(getItemSpy).not.toHaveBeenCalledWith("bhzd.eval_run_ids");

      // 展开逐用例结果 → 按需拉详情端点
      fireEvent.click(screen.getByRole("button", { name: "逐用例结果" }));
      expect(await screen.findByText("情感标签判定规则？")).toBeInTheDocument();
      expect(mockedGet).toHaveBeenCalledWith("/api/rag/eval-runs/run-h1");
    } finally {
      getItemSpy.mockRestore();
    }
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
});
