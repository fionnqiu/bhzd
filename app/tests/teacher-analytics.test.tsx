/** Regression coverage for the class-scoped, AI-assisted teacher error card. */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../src/api/client";
import { ToastProvider } from "../src/components";
import AnalyticsPage from "../src/pages/teacher/AnalyticsPage";

vi.mock("../src/api/client", () => ({
  api: {
    get: vi.fn(),
  },
}));

const mockedGet = vi.mocked(api.get);

function renderPage() {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={["/teacher/analytics"]}>
        <AnalyticsPage />
      </MemoryRouter>
    </ToastProvider>,
  );
}

describe("教师学情分析错误点", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGet.mockImplementation((path) => {
      if (path === "/api/teacher/classes") {
        return Promise.resolve({
          items: [
            {
              id: "class-a",
              name: "AI分析班",
              invite_code: "CODE",
              student_count: 4,
              recent_task_title: "时间戳任务",
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          total: 1,
        });
      }
      if (path === "/api/teacher/analytics") {
        return Promise.resolve({
          heatmap: [],
          trend: [],
          top_errors: [
            {
              error_type: "timestamp_order",
              label: "时间戳顺序错误",
              count: 3,
              major: 2,
              minor: 1,
              affected_students: 2,
              task_ids: ["student-task-a"],
            },
          ],
          error_analysis: {
            source: "ai",
            sample_count: 3,
            provider_model: "analysis-test-model",
            generated_at: "2026-08-31T10:00:00Z",
            notice: null,
          },
          suggestions: [],
          student_count: 4,
          sample_warning: false,
        });
      }
      return Promise.reject(new Error(`未 mock 的 GET ${String(path)}`));
    });
  });

  it("renders the AI source and human-readable error label with affected students", async () => {
    renderPage();

    expect(await screen.findByText("时间戳顺序错误")).toBeInTheDocument();
    expect(screen.getByText(/AI 动态分析/)).toBeInTheDocument();
    expect(screen.getByText(/影响 2 名学生/)).toBeInTheDocument();
    expect(screen.getByText("3 次")).toBeInTheDocument();
  });
});
