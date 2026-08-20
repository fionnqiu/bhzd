/**
 * API 客户端测试：CSRF 头自动携带 + 令牌失效后的"刷新并重试一次"契约。
 *
 * 后端每次 GET /api/auth/session 都轮换 CSRF 令牌（auth.py session_info），
 * 因此客户端在 403 CSRF_TOKEN_INVALID 后重新拉会话拿新令牌重试是硬契约，
 * 这里用桩 fetch 逐步验证调用序列。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setCsrfToken } from "../src/api/client";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  setCsrfToken(null);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

describe("api client", () => {
  it("变更请求自动携带 x-csrf-token，GET 不携带", async () => {
    setCsrfToken("tok-1");
    // 每次调用新建 Response：body 只能读一次，复用同一对象会报 "Body has already been read"
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse(200, { ok: true })),
    );

    await api.post("/api/tasks", { title: "练习" });
    const [, postInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(postInit.method).toBe("POST");
    expect((postInit.headers as Record<string, string>)["x-csrf-token"]).toBe(
      "tok-1",
    );
    expect(JSON.parse(postInit.body as string)).toEqual({ title: "练习" });

    await api.get("/api/tasks");
    const [, getInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(
      (getInit.headers as Record<string, string>)["x-csrf-token"],
    ).toBeUndefined();
  });

  it("403 CSRF_TOKEN_INVALID 时刷新令牌并重试一次", async () => {
    setCsrfToken("old-tok");
    fetchMock
      // 第一次：旧令牌已被轮换，服务端拒绝
      .mockResolvedValueOnce(
        jsonResponse(403, {
          error: { code: "CSRF_TOKEN_INVALID", message: "安全校验失败" },
        }),
      )
      // 刷新会话：签发新令牌
      .mockResolvedValueOnce(
        jsonResponse(200, {
          user: {
            id: "u1",
            email: "a@b.com",
            name: "测试",
            role: "student",
            status: "active",
            email_verified: true,
          },
          csrf_token: "new-tok",
        }),
      )
      // 重试成功
      .mockResolvedValueOnce(jsonResponse(200, { id: "task-1" }));

    const result = await api.post<{ id: string }>("/api/tasks", { title: "x" });

    expect(result).toEqual({ id: "task-1" });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    // 第二次是会话刷新
    expect(fetchMock.mock.calls[1][0]).toBe("/api/auth/session");
    // 第三次重试带的是新令牌
    const [, retryInit] = fetchMock.mock.calls[2] as [string, RequestInit];
    expect((retryInit.headers as Record<string, string>)["x-csrf-token"]).toBe(
      "new-tok",
    );
  });

  it("保留 429 Retry-After 与错误详情中的恢复秒数", async () => {
    // Error details take precedence over the header so the UI uses the
    // server's canonical countdown when both transports are present.
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: {
            code: "RATE_LIMITED",
            message: "尝试过于频繁",
            details: { retry_after_seconds: 7 },
          },
        }),
        { status: 429, headers: { "Retry-After": "9" } },
      ),
    );

    await expect(api.post("/api/auth/login", { email: "a@b.com" })).rejects.toMatchObject({
      status: 429,
      code: "RATE_LIMITED",
      retryAfterSeconds: 7,
    });
  });

  it("combines a caller abort signal without changing the existing api.get arguments", async () => {
    const caller = new AbortController();
    let requestSignal: AbortSignal | undefined;
    fetchMock.mockImplementation((_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        requestSignal = init?.signal as AbortSignal | undefined;
        requestSignal?.addEventListener("abort", () => reject(new Error("aborted")), {
          once: true,
        });
      }),
    );

    const pending = api.get("/api/slow", undefined, {
      signal: caller.signal,
      timeoutMs: 500,
    });
    expect(requestSignal).toBeDefined();
    expect(requestSignal).not.toBe(caller.signal);

    const rejection = expect(pending).rejects.toMatchObject({
      status: 0,
      code: "REQUEST_ABORTED",
    });
    caller.abort();
    await rejection;
  });

  it("reports REQUEST_TIMEOUT when an API request never settles", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation((_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        const signal = init?.signal as AbortSignal;
        signal.addEventListener("abort", () => reject(new Error("timed out")), {
          once: true,
        });
      }),
    );

    const pending = api.get("/api/slow", undefined, { timeoutMs: 25 });
    const rejection = expect(pending).rejects.toMatchObject({
      status: 0,
      code: "REQUEST_TIMEOUT",
    });
    await vi.advanceTimersByTimeAsync(25);
    await rejection;
  });
});
