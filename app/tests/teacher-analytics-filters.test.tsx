/**
 * 学情分析筛选布局回归测试。
 *
 * The page keeps filter state and request semantics unchanged; this test only verifies that
 * the five controls stay in the intentional 3+2 row groups exposed to the layout stylesheet.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ToastProvider } from "../src/components";
import AnalyticsPage from "../src/pages/teacher/AnalyticsPage";
import { api } from "../src/api/client";

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

beforeEach(() => {
  vi.clearAllMocks();
  mockedGet.mockImplementation((path) => {
    if (path === "/api/teacher/classes") {
      return Promise.resolve({
        items: [{ id: "c1", name: "测试班", invite_code: "CODE", student_count: 3 }],
        total: 1,
      });
    }
    if (path === "/api/graph/nodes") return Promise.resolve({ items: [], total: 0 });
    if (path === "/api/teacher/classes/c1/students")
      return Promise.resolve({ items: [], total: 0 });
    if (path === "/api/teacher/analytics") {
      return Promise.resolve({
        heatmap: [],
        trend: [],
        top_errors: [],
        scenario_comparison: [],
        suggestions: [],
        student_count: 3,
        sample_warning: false,
      });
    }
    return Promise.reject(new Error(`Unexpected GET ${String(path)}`));
  });
});

describe("AnalyticsPage filter rows", () => {
  it("groups class, data type, and scene before source and time", async () => {
    render(
      <ToastProvider>
        <MemoryRouter>
          <AnalyticsPage />
        </MemoryRouter>
      </ToastProvider>,
    );

    expect(await screen.findByRole("combobox", { name: "班级" })).toBeInTheDocument();

    const primary = document.querySelector(".teacher-analytics-filter-row-primary");
    const secondary = document.querySelector(".teacher-analytics-filter-row-secondary");

    expect(primary).toBeInTheDocument();
    expect(secondary).toBeInTheDocument();
    expect(primary?.querySelectorAll(".select")).toHaveLength(3);
    expect(secondary?.querySelectorAll(".select")).toHaveLength(2);
    expect(primary?.querySelector('[aria-label="班级"]')).toBeInTheDocument();
    expect(primary?.querySelector('[aria-label="数据类型"]')).toBeInTheDocument();
    expect(primary?.querySelector('[aria-label="行业场景"]')).toBeInTheDocument();
    expect(secondary?.querySelector('[aria-label="任务来源"]')).toBeInTheDocument();
    expect(secondary?.querySelector('[aria-label="时间范围"]')).toBeInTheDocument();
  });
});
