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

async function ensureSession(account: E2eAccount): Promise<string> {
  const cached = sessionCache.get(account.email);
  if (cached) return cached;

  const context = await request.newContext({ baseURL: "http://127.0.0.1:4173" });
  try {
    const response = await context.post("/api/auth/login", {
      data: {
        email: account.email,
        // Direct API setup must retain the same encrypted-password wire contract as the UI.
        passwordEnvelope: await createPasswordEnvelope(context, account.password),
      },
    });
    expect(response.status(), `API 登录应成功：${account.email}`).toBe(200);
    const match = (response.headers()["set-cookie"] ?? "").match(/bhzd_session=([^;]+)/);
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
