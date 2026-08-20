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
import RegisterPage from "../src/auth/RegisterPage";
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
          <Route path="/" element={<div>对话页占位</div>} />
          <Route path="/teacher" element={<div>教师端占位</div>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

function renderRegister() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/register"]}>
        <Routes>
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/login" element={<div>登录页占位</div>} />
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

  it("使用简洁的注册入口文案", async () => {
    renderLogin();

    // Keep the compact link label stable so the login card does not reintroduce
    // the older, wider student-only wording on small viewports.
    expect(await screen.findByRole("link", { name: "注册" })).toHaveAttribute(
      "href",
      "/register",
    );
    expect(screen.queryByRole("link", { name: "注册学生账号" })).not.toBeInTheDocument();
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
    expect(await screen.findByText("对话页占位")).toBeInTheDocument();
  });

  it("教师登录时跳转教师端而不是学生端", async () => {
    mockedPost.mockResolvedValue({
      user: {
        id: "t1",
        email: "teacher@example.com",
        name: "教师",
        role: "teacher",
        status: "active",
        email_verified: true,
      },
      csrf_token: "tok",
    });
    renderLogin();

    fireEvent.change(await screen.findByPlaceholderText("you@example.com"), {
      target: { value: "teacher@example.com" },
    });
    fireEvent.change(screen.getByPlaceholderText("请输入密码"), {
      target: { value: "Passw0rd1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByText("教师端占位")).toBeInTheDocument();
    expect(screen.queryByText("对话页占位")).not.toBeInTheDocument();
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

describe("RegisterPage", () => {
  async function chooseTeacherRole() {
    fireEvent.click(screen.getByRole("combobox", { name: /角色/ }));
    fireEvent.click(await screen.findByRole("option", { name: "教师" }));
  }

  function fillRegisterForm(password: string, confirm: string) {
    fireEvent.change(screen.getByPlaceholderText("真实姓名或昵称"), {
      target: { value: "王老师" },
    });
    fireEvent.change(screen.getByPlaceholderText("you@example.com"), {
      target: { value: "teacher@example.com" },
    });
    const passwordInputs = screen.getAllByLabelText(/密码/);
    fireEvent.change(passwordInputs[0], { target: { value: password } });
    fireEvent.change(passwordInputs[1], { target: { value: confirm } });
  }

  it("教师自助注册不显示邀请码，并且请求不携带已废弃字段", async () => {
    mockedPost.mockResolvedValue({
      user: {
        id: "t1",
        email: "teacher@example.com",
        name: "王老师",
        role: "teacher",
        status: "active",
        email_verified: true,
      },
      message: "注册成功",
    });
    renderRegister();

    expect(await screen.findByRole("heading", { name: "注册账号" })).toBeInTheDocument();
    await chooseTeacherRole();
    expect(screen.queryByText(/邀请码/)).not.toBeInTheDocument();

    fillRegisterForm("Passw0rd1", "Passw0rd1");
    fireEvent.click(screen.getByRole("button", { name: "注册" }));

    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/api/auth/register", {
        email: "teacher@example.com",
        name: "王老师",
        role: "teacher",
        passwordEnvelope: {
          keyId: "test-key",
          encryptedKey: "wrapped-key",
          iv: "test-iv",
          ciphertext: "test-ciphertext",
        },
      });
    });
    // The envelope wrapper must not accidentally revive retired invitation data.
    expect(mockedPost.mock.calls[0]?.[1]).not.toHaveProperty("teacher_invite");
    expect(await screen.findByRole("heading", { name: "注册成功" })).toBeInTheDocument();
    expect(screen.getByText(/账号已启用，可使用 teacher@example\.com 直接登录。/)).toBeInTheDocument();
  });

  it("密码不一致时不发起教师注册请求", async () => {
    renderRegister();

    expect(await screen.findByRole("heading", { name: "注册账号" })).toBeInTheDocument();
    await chooseTeacherRole();
    fillRegisterForm("Passw0rd1", "Passw0rd2");
    fireEvent.click(screen.getByRole("button", { name: "注册" }));

    expect(await screen.findByText("两次输入的密码不一致")).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });
});
