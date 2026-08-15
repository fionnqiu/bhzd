/**
 * API 客户端（蓝图 §4/§6 的前端出口）。
 *
 * 关键设计（为什么）：
 * - CSRF 令牌由模块级状态持有：后端每次 GET /api/auth/session 都会**轮换**
 *   令牌（库里只存哈希，旧令牌立即失效），因此变更请求若收到 403
 *   CSRF_TOKEN_INVALID，必须重新拉一次会话拿新令牌并重试——这是契约级
 *   要求，不是优化。
 * - 401 不在这里直接跳转：/api/auth/* 自身的 401（如登录密码错误）是业务
 *   响应而非会话失效，误跳转会吃掉登录页的错误提示。只有非 auth 路径的
 *   401 才触发 onUnauthorized 回调（由 AuthContext 注册，清用户态后由
 *   路由守卫送回 /login）。
 */

import type { ApiErrorBody, SessionResponse } from "./types";

/** 统一请求错误：status=HTTP 状态；code=后端错误码（无则 HTTP_<status>） */
export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /** Response decoder; JSON remains the default, while downloads can request a Blob. */
  responseType?: "json" | "blob";
  /** JSON 请求体；undefined 表示无 body（不会带 Content-Type） */
  body?: unknown;
  /** 查询参数；undefined/null 值会被跳过 */
  query?: Record<string, string | number | boolean | undefined | null>;
  /** multipart 表单；与 body 互斥，浏览器自动带 boundary */
  formData?: FormData;
  /** 调用方的取消信号；会与客户端默认超时合并，而不是替换默认保护。 */
  signal?: AbortSignal;
  /** 单次 HTTP 往返的超时毫秒数；省略时使用 10 秒，长任务可显式提高。 */
  timeoutMs?: number;
}

/** 会话失效回调（AuthContext 注册：清 user + 触发重定向到 /login） */
type UnauthorizedHandler = () => void;

const DEFAULT_REQUEST_TIMEOUT_MS = 10_000;
export type RequestControlOptions = Pick<RequestOptions, "signal" | "timeoutMs">;

interface RequestAbortHandle {
  signal: AbortSignal;
  didTimeout: () => boolean;
  dispose: () => void;
}

/**
 * `AbortSignal.any()` is not available in every browser supported by Vite's default target.
 * Compose the caller's cancellation and the client timeout manually so either one stops the same
 * fetch without taking ownership of (or aborting) the caller's controller.
 */
function createRequestAbortHandle(options: RequestControlOptions = {}): RequestAbortHandle {
  const controller = new AbortController();
  const timeoutMs =
    typeof options.timeoutMs === "number" &&
    Number.isFinite(options.timeoutMs) &&
    options.timeoutMs > 0
      ? options.timeoutMs
      : DEFAULT_REQUEST_TIMEOUT_MS;
  let timedOut = false;
  const abortFromCaller = () => controller.abort();

  if (options.signal?.aborted) {
    abortFromCaller();
  } else {
    options.signal?.addEventListener("abort", abortFromCaller, { once: true });
  }

  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  return {
    signal: controller.signal,
    didTimeout: () => timedOut,
    dispose: () => {
      clearTimeout(timeout);
      options.signal?.removeEventListener("abort", abortFromCaller);
    },
  };
}

/** Convert transport-level rejections into actionable client errors without exposing browser internals. */
function transportError(handle: RequestAbortHandle): ApiRequestError {
  if (handle.didTimeout()) {
    return new ApiRequestError(0, "REQUEST_TIMEOUT", "请求超时，请稍后重试");
  }
  if (handle.signal.aborted) {
    return new ApiRequestError(0, "REQUEST_ABORTED", "请求已取消");
  }
  return new ApiRequestError(0, "NETWORK_ERROR", "网络连接失败，请检查网络后重试");
}

function cancelledRequestError(): ApiRequestError {
  return new ApiRequestError(0, "REQUEST_ABORTED", "请求已取消");
}

// ---------------------------------------------------------------- 模块状态

// CSRF 令牌只活在内存里（页面刷新后由会话引导重新签发，不做本地持久化——
// 后端每次 GET session 都轮换，持久化旧令牌没有意义）
let csrfToken: string | null = null;
let onUnauthorized: UnauthorizedHandler | null = null;
// 并发请求同时遇到 CSRF 失效时共享同一次会话刷新，避免互相把令牌再轮换掉
let csrfRefreshPromise: Promise<void> | null = null;

/** 写入/更新当前 CSRF 令牌（AuthContext 引导与登录响应时调用） */
export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

/** 注册 401 处理（应用启动时由 AuthContext 调用一次） */
export function setOnUnauthorized(handler: UnauthorizedHandler | null): void {
  onUnauthorized = handler;
}

// ---------------------------------------------------------------- 内部实现

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

/** 解析错误响应体为 ApiRequestError（后端契约 {"error":{code,message}}） */
async function toError(res: Response): Promise<ApiRequestError> {
  let code = `HTTP_${res.status}`;
  let message = `请求失败（${res.status}）`;
  try {
    const body = (await res.json()) as ApiErrorBody;
    if (body?.error?.code) code = body.error.code;
    if (body?.error?.message) message = body.error.message;
  } catch {
    // 非 JSON 错误体（如网关 502 页面）：保留兜底文案
  }
  return new ApiRequestError(res.status, code, message);
}

/** 重新拉取会话以轮换 CSRF 令牌（403 CSRF_TOKEN_INVALID 后的恢复路径） */
async function refreshCsrfToken(): Promise<void> {
  // 去重：多个请求同时触发时只发一次 GET /api/auth/session
  csrfRefreshPromise ??= (async () => {
    // A shared CSRF refresh must not be cancelled by any one request, but it still has a timeout.
    const abortHandle = createRequestAbortHandle();
    try {
      const res = await fetch("/api/auth/session", {
        credentials: "same-origin",
        signal: abortHandle.signal,
      });
      if (!res.ok) throw await toError(res);
      const data = (await res.json()) as SessionResponse;
      csrfToken = data.csrf_token;
    } catch (err) {
      if (err instanceof ApiRequestError) throw err;
      throw transportError(abortHandle);
    } finally {
      abortHandle.dispose();
    }
  })();
  try {
    await csrfRefreshPromise;
  } finally {
    csrfRefreshPromise = null;
  }
}

async function doFetch<T>(path: string, options: RequestOptions): Promise<T> {
  const method = options.method ?? "GET";
  const isMutation = method !== "GET";
  const headers: Record<string, string> = {};
  // 变更类请求必须携带 x-csrf-token（蓝图 §4 强制，服务端逐端点校验）
  if (isMutation && csrfToken) headers["x-csrf-token"] = csrfToken;

  let body: BodyInit | undefined;
  if (options.formData) {
    // multipart：不手动设 Content-Type，由浏览器生成 boundary
    body = options.formData;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  const abortHandle = createRequestAbortHandle(options);
  let res: Response;
  try {
    res = await fetch(buildUrl(path, options.query), {
      method,
      headers,
      body,
      // 同源 cookie（bhzd_session / bhzd_admin_session）随请求自动携带
      credentials: "same-origin",
      signal: abortHandle.signal,
    });
  } catch {
    const error = transportError(abortHandle);
    abortHandle.dispose();
    if (error.code !== "NETWORK_ERROR") throw error;
    throw new ApiRequestError(0, "NETWORK_ERROR", "网络连接失败，请检查网络后重试");
  }

  if (res.status === 204) {
    abortHandle.dispose();
    return undefined as T;
  }
  if (options.responseType === "blob" && res.ok) {
    try {
      // Keep the timeout armed until the complete download body arrives.
      const blob = await res.blob();
      abortHandle.dispose();
      return blob as T;
    } catch (err) {
      abortHandle.dispose();
      if (err instanceof ApiRequestError) throw err;
      throw transportError(abortHandle);
    }
  }
  let text: string;
  try {
    // Keep the timeout armed until the complete response body arrives, not only response headers.
    text = await res.text();
  } catch {
    const error = transportError(abortHandle);
    abortHandle.dispose();
    throw error;
  }
  if (!res.ok) {
    // 有 body 时 toError 已消费不了（上面已读 text），这里就地解析
    let code = `HTTP_${res.status}`;
    let message = `请求失败（${res.status}）`;
    if (text) {
      try {
        const parsed = JSON.parse(text) as ApiErrorBody;
        if (parsed?.error?.code) code = parsed.error.code;
        if (parsed?.error?.message) message = parsed.error.message;
      } catch {
        /* 非 JSON 错误体，保留兜底 */
      }
    }
    abortHandle.dispose();
    throw new ApiRequestError(res.status, code, message);
  }
  if (!text) {
    abortHandle.dispose();
    return undefined as T;
  }
  try {
    const parsed = JSON.parse(text) as T;
    abortHandle.dispose();
    return parsed;
  } catch {
    abortHandle.dispose();
    throw new ApiRequestError(res.status, "PARSE_ERROR", "服务响应格式异常");
  }
}

/**
 * 发起 API 请求。
 *
 * 自动行为：
 * - 变更类请求（非 GET）自动附带 `x-csrf-token`；
 * - 收到 403 + CSRF_TOKEN_INVALID 时，先重新拉取 /api/auth/session 轮换令牌，
 *   然后**原样重试一次**（契约要求；仍失败则抛给调用方）；
 * - 非 /api/auth/* 路径的 401 触发 onUnauthorized（会话已失效）。
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  try {
    return await doFetch<T>(path, options);
  } catch (err) {
    if (
      err instanceof ApiRequestError &&
      err.status === 403 &&
      err.code === "CSRF_TOKEN_INVALID"
    ) {
      // 令牌被轮换/过期：刷新后重试一次（不再递归，二次失败直接抛）
      await refreshCsrfToken();
      // The refresh is global, but a component that unmounted while waiting must not replay its write.
      if (options.signal?.aborted) throw cancelledRequestError();
      return await doFetch<T>(path, options);
    }
    if (
      err instanceof ApiRequestError &&
      err.status === 401 &&
      !path.startsWith("/api/auth/")
    ) {
      csrfToken = null;
      onUnauthorized?.();
    }
    throw err;
  }
}

/** 便捷方法族（保持调用点紧凑） */
export const api = {
  // Keep the existing positional arguments intact; control options are deliberately last so old
  // call sites remain source-compatible while effects can opt into unmount cancellation.
  get: <T>(
    path: string,
    query?: RequestOptions["query"],
    control: RequestControlOptions = {},
  ) => request<T>(path, { method: "GET", query, ...control }),
  getBlob: (path: string, query?: RequestOptions["query"], control: RequestControlOptions = {}) =>
    request<Blob>(path, { method: "GET", responseType: "blob", query, ...control }),
  post: <T>(path: string, body?: unknown, control: RequestControlOptions = {}) =>
    request<T>(path, { method: "POST", body, ...control }),
  put: <T>(path: string, body?: unknown, control: RequestControlOptions = {}) =>
    request<T>(path, { method: "PUT", body, ...control }),
  patch: <T>(path: string, body?: unknown, control: RequestControlOptions = {}) =>
    request<T>(path, { method: "PATCH", body, ...control }),
  delete: <T>(path: string, control: RequestControlOptions = {}) =>
    request<T>(path, { method: "DELETE", ...control }),
  postForm: <T>(path: string, formData: FormData, control: RequestControlOptions = {}) =>
    request<T>(path, { method: "POST", formData, ...control }),
};
