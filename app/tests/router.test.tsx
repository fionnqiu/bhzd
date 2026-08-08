/**
 * 路由守卫测试（蓝图 §14 守卫口径）。
 *
 * 复用生产路由表 `routes`（createMemoryRouter）而非另写测试路由——
 * 守卫行为只有挂在真实路由树上才有意义，否则测的是测试自己。
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "../src/app/router";
import { AuthProvider } from "../src/auth/AuthContext";
import { ScenarioProvider } from "../src/app/ScenarioContext";
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
  return render(
    <ToastProvider>
      <AuthProvider>
        <ScenarioProvider>
          <RouterProvider router={router} />
        </ScenarioProvider>
      </AuthProvider>
    </ToastProvider>,
  );
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
    mockedGet.mockRejectedValue(
      new ApiRequestError(401, "UNAUTHORIZED", "请先登录"),
    );
    renderAt("/");
    // 登录页的标题出现即证明守卫已重定向
    expect(
      await screen.findByRole("heading", { name: "登录" }),
    ).toBeInTheDocument();
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
    expect(
      await screen.findByRole("heading", { name: "模型供应商" }),
    ).toBeInTheDocument();
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

  it("only system_admin has the RAG portal, while administrators retain the student portal", () => {
    const studentPortal = PORTALS.find((portal) => portal.key === "student");
    const ragPortal = PORTALS.find((portal) => portal.key === "rag-admin");

    expect(studentPortal?.roles).toEqual(["student", "content_admin", "system_admin"]);
    expect(ragPortal?.roles).toEqual(["system_admin"]);
  });

  it("页面渲染失败时显示可恢复的路由错误状态，而不是白屏", async () => {
    const errorElement = routes[0]?.errorElement;
    if (!errorElement) throw new Error("router must provide a top-level error element");
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    try {
      const router = createMemoryRouter([
        { path: "/", element: <BrokenRoute />, errorElement },
      ]);
      render(<RouterProvider router={router} />);

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "页面加载出现问题，请稍后重试。",
      );
    } finally {
      consoleError.mockRestore();
    }
  });
});
