/**
 * Teacher analytics remains available after RAG review is removed from the teacher portal.
 * The mock is deliberately limited to teaching endpoints so this test cannot accidentally
 * reintroduce a dependency on RAG management APIs.
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
  mockedGet.mockImplementation((path: string) => {
    if (path === "/api/teacher/classes") {
      return Promise.resolve({
        items: [{ id: "c1", name: "测试班", invite_code: "CODE", student_count: 2 }],
        total: 1,
      });
    }
    if (path === "/api/graph/nodes") return Promise.resolve({ items: [], total: 0 });
    if (path === "/api/teacher/classes/c1/students") return Promise.resolve({ items: [], total: 0 });
    if (path === "/api/teacher/analytics") {
      return Promise.resolve({
        heatmap: [{ cap_id: "CAP-1", cap_name: "语音切分", avg_score: 0.35, weak_count: 2, student_count: 2 }],
        trend: [],
        top_errors: [{ error_type: "boundary_overflow", count: 4, major: 1, minor: 3 }],
        scenario_comparison: [],
        suggestions: ["安排专项纠错练习"],
        student_count: 2,
        sample_warning: true,
      });
    }
    return Promise.reject(new Error(`Unexpected GET ${path}`));
  });
});

describe("AnalyticsPage", () => {
  it("keeps teaching analytics available without consulting RAG management", async () => {
    render(
      <ToastProvider>
        <MemoryRouter>
          <AnalyticsPage />
        </MemoryRouter>
      </ToastProvider>,
    );

    expect(await screen.findByText("语音切分")).toBeInTheDocument();
    expect(document.querySelector(".teacher-analytics-page")).toBeInTheDocument();
    expect(document.querySelector(".teacher-two-column")).toBeInTheDocument();
    expect(screen.getByText("boundary_overflow")).toBeInTheDocument();
    expect(mockedGet).not.toHaveBeenCalledWith(
      "/api/rag/documents",
      expect.anything(),
      expect.anything(),
    );
  });
});
