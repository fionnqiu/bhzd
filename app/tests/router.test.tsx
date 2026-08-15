/**
 * 路由守卫测试（蓝图 §14 守卫口径）。
 *
 * 复用生产路由表 `routes`（createMemoryRouter）而非另写测试路由——
 * 守卫行为只有挂在真实路由树上才有意义，否则测的是测试自己。
 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "../src/app/router";
import { legacyRagAdminTarget } from "../src/app/legacyRagRoutes";
import { AuthProvider } from "../src/auth/AuthContext";
import { ToastProvider } from "../src/components";
import { PORTALS } from "../src/layouts/ShellLayout";
import { ApiRequestError, api } from "../src/api/client";
import type { User } from "../src/api/types";

// 用可控的 api 桩替换客户端模块（AuthContext/页面全部经它取数）
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

function makeUser(role: User["role"]): User {
  return {
    id: `u-${role}`,
    email: `${role}@example.com`,
    name: "测试用户",
    role,
    status: "active",
    email_verified: true,
  };
}

/** 以指定路径渲染完整应用壳（与生产 Provider 组合一致） */
function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(
    <ToastProvider>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </ToastProvider>,
  );
  return { ...view, router };
}

/** Deliberately throws so the test exercises the real data-router error element. */
function BrokenRoute(): null {
  throw new Error("route render failure");
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("路由守卫", () => {
  it("未登录访问 / 重定向到 /login", async () => {
    mockedGet.mockRejectedValue(new ApiRequestError(401, "UNAUTHORIZED", "请先登录"));
    renderAt("/");
    // 登录页的标题出现即证明守卫已重定向
    expect(await screen.findByRole("heading", { name: "登录" })).toBeInTheDocument();
  });

  it("学生角色访问 /admin/providers 看到 403 页", async () => {
    mockedGet.mockResolvedValue({
      user: makeUser("student"),
      csrf_token: "tok",
    });
    renderAt("/admin/providers");
    expect(await screen.findByText("没有访问权限")).toBeInTheDocument();
    // 不应渲染管理端内容
    expect(screen.queryByText("RAG 参数配置")).not.toBeInTheDocument();
  });

  it("system_admin 访问 /admin/providers 渲染占位页", async () => {
    mockedGet.mockResolvedValue({
      user: makeUser("system_admin"),
      csrf_token: "tok",
    });
    renderAt("/admin/providers");
    expect(await screen.findByRole("heading", { name: "模型供应商" })).toBeInTheDocument();
  });

  it("教师访问学生端、RAG 管理和旧资源审核地址均看到 403 页", async () => {
    mockedGet.mockResolvedValue({
      user: makeUser("teacher"),
      csrf_token: "tok",
    });

    const restrictedPaths = ["/", "/rag-admin", "/teacher/review"];
    for (const path of restrictedPaths) {
      const view = renderAt(path);
      expect(await screen.findByText("没有访问权限")).toBeInTheDocument();
      view.unmount();
    }
  });

  it("独立 RAG 门户已移除，system_admin 从系统管理端进入 RAG 功能", () => {
    const studentPortal = PORTALS.find((portal) => portal.key === "student");
    const ragPortal = PORTALS.find((portal) => portal.key === "rag-admin");
    const adminPortal = PORTALS.find((portal) => portal.key === "admin");

    expect(studentPortal?.roles).toEqual(["student", "content_admin", "system_admin"]);
    expect(ragPortal).toBeUndefined();
    expect(adminPortal?.roles).toEqual(["system_admin"]);
  });

  it("教师端不再暴露教学 Agent 路由", () => {
    const teacherRoute = routes.find((route) => route.path === "/teacher");
    const childPaths = teacherRoute?.children?.map((route) => route.path);

    expect(childPaths).not.toContain("agent");
  });

  it("RAG 旧地址映射到系统管理端且保留资料深链接", () => {
    const legacyRoute = routes.find((route) => route.path === "/rag-admin/*");

    // A single guarded wildcard replaces the deleted RagAdminLayout and all
    // of its child routes, while the pure mapping keeps bookmark behavior explicit.
    expect(legacyRoute).toBeDefined();
    expect(legacyRoute?.children).toBeUndefined();
    expect(legacyRagAdminTarget("/rag-admin")).toBe("/admin/rag");
    expect(legacyRagAdminTarget("/rag-admin/upload")).toBe("/admin/rag/upload");
    expect(legacyRagAdminTarget("/rag-admin/documents/doc-1")).toBe(
      "/admin/rag/documents/doc-1",
    );
    expect(legacyRagAdminTarget("/rag-admin/documents/doc-1/chunks")).toBe(
      "/admin/rag/documents/doc-1",
    );
    expect(legacyRagAdminTarget("/rag-admin/eval-cases")).toBe(
      "/admin/rag/search-test",
    );
    expect(legacyRagAdminTarget("/rag-admin/jobs")).toBe("/admin/rag");
    expect(legacyRagAdminTarget("/rag-admin/unknown")).toBe("/admin/rag");
  });

  it("学生访问旧 /rag-qa 书签时回到 Agent 工作台", async () => {
    // Exercise the production route tree: a legacy URL must stay useful while
    // the retired knowledge-QA screen is no longer exposed in student navigation.
    mockedGet.mockImplementation(async (path: string) => {
      if (path === "/api/auth/session") {
        return { user: makeUser("student"), csrf_token: "tok" };
      }
      if (path === "/api/notifications/unread-count") return { unread: 0 };
      if (path === "/api/onboarding/assessment") return { status: "completed" };
      if (
        ["/api/conversations", "/api/presets", "/api/tasks", "/api/profile/mastery"].includes(path)
      ) {
        return { items: [], total: 0 };
      }
      return { items: [], total: 0 };
    });

    const { router } = renderAt("/rag-qa");

    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
    // Route chunks stay lazy in production.  Under the full parallel suite the
    // workbench transform can outlast Testing Library's one-second default, so
    // keep the assertion on the real welcome state with a bounded chunk budget.
    expect(
      await screen.findByTestId("cockpit-welcome", {}, { timeout: 5_000 }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "知识问答" })).not.toBeInTheDocument();
  });

  it("页面渲染失败时显示可恢复的路由错误状态，而不是白屏", async () => {
    const errorElement = routes[0]?.errorElement;
    if (!errorElement) throw new Error("router must provide a top-level error element");
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    try {
      const router = createMemoryRouter([{ path: "/", element: <BrokenRoute />, errorElement }]);
      render(<RouterProvider router={router} />);

      expect(await screen.findByRole("alert")).toHaveTextContent("页面加载出现问题，请稍后重试。");
    } finally {
      consoleError.mockRestore();
    }
  });
});
