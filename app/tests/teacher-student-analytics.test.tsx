/**
 * 学生能力分析页回归测试：班级筛选可由外层 query 带入，且未选择学生时不得请求个人明细。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ToastProvider } from "../src/components";
import StudentAnalyticsPage from "../src/pages/teacher/StudentAnalyticsPage";
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
        items: [
          { id: "c1", name: "一班", invite_code: "C1", student_count: 0 },
          { id: "c2", name: "二班", invite_code: "C2", student_count: 1 },
        ],
        total: 2,
      });
    }
    if (path === "/api/graph/nodes") return Promise.resolve({ items: [], total: 0 });
    if (path === "/api/teacher/classes/c2/students") {
      return Promise.resolve({
        items: [
          {
            id: "s2",
            name: "李四",
            email: "lisi@example.com",
            task_count: 1,
            completion_rate: 1,
            avg_mastery: 0.8,
            last_active: null,
            joined_at: "2026-01-01T00:00:00Z",
            left_at: null,
          },
        ],
        total: 1,
      });
    }
    if (path === "/api/teacher/classes/c1/students") {
      return Promise.resolve({ items: [], total: 0 });
    }
    if (path === "/api/teacher/analytics/students/s2") {
      return Promise.resolve({
        student_id: "s2",
        class_id: "c2",
        mastery: [],
        tasks: [],
        diagnostics: null,
        diagnostics_note: null,
        mastery_events: [],
      });
    }
    return Promise.reject(new Error(`未 mock 的 GET ${path}`));
  });
});

describe("StudentAnalyticsPage", () => {
  it("carries class_id from the aggregate page and keeps personal data unloaded by default", async () => {
    render(
      <ToastProvider>
        <MemoryRouter initialEntries={["/teacher/analytics/students?class_id=c2"]}>
          <StudentAnalyticsPage />
        </MemoryRouter>
      </ToastProvider>,
    );

    expect(await screen.findByRole("combobox", { name: "班级" })).toHaveTextContent("二班");
    await waitFor(() =>
      expect(mockedGet).toHaveBeenCalledWith(
        "/api/teacher/classes/c2/students",
        undefined,
        expect.objectContaining({ signal: expect.anything() }),
      ),
    );
    expect(mockedGet).not.toHaveBeenCalledWith(
      "/api/teacher/analytics/students/s2",
      expect.anything(),
      expect.anything(),
    );
    expect(screen.getByText("选择学生后显示其详细能力数据")).toBeInTheDocument();
    expect(screen.queryByText("李四 的学习明细")).not.toBeInTheDocument();
  });

  it("requests detail only after a student is explicitly selected", async () => {
    render(
      <ToastProvider>
        <MemoryRouter initialEntries={["/teacher/analytics/students?class_id=c2"]}>
          <StudentAnalyticsPage />
        </MemoryRouter>
      </ToastProvider>,
    );

    const studentSelect = await screen.findByRole("combobox", { name: "学生" });
    await waitFor(() => expect(studentSelect).not.toBeDisabled());
    fireEvent.click(studentSelect);
    fireEvent.click(await screen.findByRole("option", { name: "李四（lisi@example.com）" }));

    await waitFor(() =>
      expect(mockedGet).toHaveBeenCalledWith(
        "/api/teacher/analytics/students/s2",
        { class_id: "c2" },
        expect.objectContaining({ signal: expect.anything() }),
      ),
    );
  });
});
