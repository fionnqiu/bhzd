/**
 * 认证页测试：登录页渲染 + 表单提交（api 层打桩）。
 *
 * 登录是接入后续一切页面的入口，回归代价最高，故 F0 就纳入冒烟。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "../src/auth/AuthContext";
import LoginPage from "../src/auth/LoginPage";
import { ApiRequestError, api } from "../src/api/client";

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

vi.mock("../src/auth/passwordCrypto", () => ({
  // Auth pages are responsible for handing plaintext only to the crypto helper;
  // the helper itself has browser WebCrypto coverage in the backend contract.
  createPasswordEnvelope: vi.fn(async () => ({
    keyId: "test-key",
    encryptedKey: "wrapped-key",
    iv: "test-iv",
    ciphertext: "test-ciphertext",
  })),
}));

const mockedGet = vi.mocked(api.get);
const mockedPost = vi.mocked(api.post);

function renderLogin() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<div>指挥舱占位</div>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // 会话引导返回 401（未登录），让登录页正常渲染
  mockedGet.mockRejectedValue(new ApiRequestError(401, "UNAUTHORIZED", "请先登录"));
});

describe("LoginPage", () => {
  it("渲染登录表单（中文文案）", async () => {
    renderLogin();
    expect(
      await screen.findByRole("heading", { name: "登录" }),
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText("you@example.com")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("请输入密码")).toBeInTheDocument();
    expect(screen.getByText("标航智导")).toBeInTheDocument();
  });

  it("提交邮箱密码调用 /api/auth/login 并跳转首页", async () => {
    mockedPost.mockResolvedValue({
      user: {
        id: "u1",
        email: "a@b.com",
        name: "同学",
        role: "student",
        status: "active",
        email_verified: true,
      },
      csrf_token: "tok",
    });
    renderLogin();

    fireEvent.change(await screen.findByPlaceholderText("you@example.com"), {
      target: { value: "a@b.com" },
    });
    fireEvent.change(screen.getByPlaceholderText("请输入密码"), {
      target: { value: "Passw0rd1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/auth/login", {
        email: "a@b.com",
        passwordEnvelope: {
          keyId: "test-key",
          encryptedKey: "wrapped-key",
          iv: "test-iv",
          ciphertext: "test-ciphertext",
        },
      });
    });
    // 登录成功 → 守卫来源缺省回 /
    expect(await screen.findByText("指挥舱占位")).toBeInTheDocument();
  });

  it("登录失败展示后端中文错误", async () => {
    mockedPost.mockRejectedValue(
      new ApiRequestError(401, "INVALID_CREDENTIALS", "邮箱或密码不正确"),
    );
    renderLogin();

    fireEvent.change(await screen.findByPlaceholderText("you@example.com"), {
      target: { value: "a@b.com" },
    });
    fireEvent.change(screen.getByPlaceholderText("请输入密码"), {
      target: { value: "wrong-pass1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByText("邮箱或密码不正确")).toBeInTheDocument();
  });
});
