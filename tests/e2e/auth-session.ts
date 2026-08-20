/**
 * Shared demo-account session bootstrap for the serial Playwright suite.
 *
 * Both spec files run against one seeded SQLite database and the same IP-based
 * authentication limiter.  Keeping the cache in this shared module prevents
 * each file from independently logging the demo accounts in again, while the
 * browser-login test remains free to verify the real UI path.
 */
import { createPasswordEnvelope } from "./auth-envelope";
import { expect, request } from "./playwright-runtime";
import type { Page } from "@playwright/test";

export interface E2eAccount {
  email: string;
  password: string;
}

const sessionCache = new Map<string, string>();

/** NF5 限流窗口（同一 IP 每分钟 5 次登录）。命中 429 时等窗口滚过再重试。 */
const RATE_LIMIT_WINDOW_MS = 61_000;
const LOGIN_MAX_ATTEMPTS = 3;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function ensureSession(account: E2eAccount): Promise<string> {
  const cached = sessionCache.get(account.email);
  if (cached) return cached;

  const context = await request.newContext({ baseURL: "http://127.0.0.1:4173" });
  try {
    // 无 LLM 的降级路径让套件跑得更快，登录尝试容易在滚动窗口内挤过 5 次上限；
    // 429 不是产品缺陷，按窗口长度退避重试，避免限流误报成 UI 失败。
    let response: Awaited<ReturnType<typeof context.post>> | null = null;
    for (let attempt = 1; attempt <= LOGIN_MAX_ATTEMPTS; attempt += 1) {
      response = await context.post("/api/auth/login", {
        data: {
          email: account.email,
          // Direct API setup must retain the same encrypted-password wire contract as the UI.
          passwordEnvelope: await createPasswordEnvelope(context, account.password),
        },
      });
      if (response.status() !== 429) break;
      if (attempt < LOGIN_MAX_ATTEMPTS) await sleep(RATE_LIMIT_WINDOW_MS);
    }
    expect(response!.status(), `API 登录应成功：${account.email}`).toBe(200);
    const match = (response!.headers()["set-cookie"] ?? "").match(/bhzd_session=([^;]+)/);
    expect(match, "登录响应应下发 bhzd_session").toBeTruthy();
    const token = match![1];
    sessionCache.set(account.email, token);
    return token;
  } finally {
    await context.dispose();
  }
}

/** Inject one cached session into a browser context without consuming another login attempt. */
export async function injectSession(page: Page, account: E2eAccount): Promise<void> {
  const token = await ensureSession(account);
  await page.context().addCookies([
    { name: "bhzd_session", value: token, domain: "127.0.0.1", path: "/" },
  ]);
}
