/**
 * Agent 内置诊断入口回归测试。
 *
 * 诊断接口和报告卡仍由 Cockpit 消费；这里只锁定产品边界：学生导航不再
 * 暴露独立诊断页，历史 /diagnostics 书签通过真实路由树回到 Agent。
 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { AuthProvider } from "../src/auth/AuthContext";
import { ScenarioProvider } from "../src/app/ScenarioContext";
import { routes } from "../src/app/router";
import { ToastProvider } from "../src/components";
import type { User } from "../src/api/types";
import { api } from "../src/api/client";

vi.mock("../src/api/client", () => ({
  ApiRequestError: class extends Error {
    status = 500;
    code = "MOCK";
  },
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
}));

const mockedGet = vi.mocked(api.get);

function student(): User {
  return {
    id: "student-1",
    email: "student@example.com",
    name: "测试学生",
    role: "student",
    status: "active",
    email_verified: true,
  };
}

function installStudentShellApi() {
  mockedGet.mockImplementation(async (path: string) => {
    if (path === "/api/auth/session") return { user: student(), csrf_token: "csrf" };
    if (path === "/api/onboarding/assessment") return { status: "completed" };
    if (path === "/api/notifications/unread-count") return { unread: 0 };
    if (path === "/api/conversations" || path === "/api/profile/mastery") {
      return { items: [], total: 0 };
    }
    return { items: [], total: 0 };
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  installStudentShellApi();
});

describe("Agent 内置标注诊断", () => {
  it("/diagnostics 兼容书签 replace 回 Agent 工作台", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/diagnostics"] });
    render(
      <ToastProvider>
        <AuthProvider>
          <ScenarioProvider>
            <RouterProvider router={router} />
          </ScenarioProvider>
        </AuthProvider>
      </ToastProvider>,
    );

    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
    expect(
      await screen.findByTestId("cockpit-welcome", {}, { timeout: 5_000 }),
    ).toBeInTheDocument();
    expect(router.state.historyAction).toBe("REPLACE");
  });

  it("学生导航不再渲染独立标注诊断入口", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/"] });
    render(
      <ToastProvider>
        <AuthProvider>
          <ScenarioProvider>
            <RouterProvider router={router} />
          </ScenarioProvider>
        </AuthProvider>
      </ToastProvider>,
    );

    const navigation = await screen.findByRole("navigation", { name: "学生端" });
    expect(navigation).not.toHaveTextContent("标注诊断");
    expect(navigation).toHaveTextContent("学习任务");
  });
});
