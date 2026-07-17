# 标航智导 Agent 平台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留现有确定性教学能力的前提下，交付 Windows 优先、支持真实 LLM、多供应商、邮箱账号、单一管理员 `/admin`、工具内嵌和人工确认门的标航智导 Agent 平台。

**Architecture:** 保留 `app/` React 应用与既有业务模块，新建同源 `server/` Node.js/TypeScript 服务。服务端使用 Fastify、SQLite 和独立的用户/管理员会话，通过四类 Provider Adapter 将模型响应统一为 Agent 事件；Tool Gateway 复用现有课程、图谱、任务转化和诊断模块，所有写工具进入服务端确认门。

**Tech Stack:** React 19、TypeScript、Vite、Fastify、better-sqlite3、Argon2id、Zod、Nodemailer、Vitest、Playwright、Windows PowerShell、讯飞星辰/星火原生 API、Chat Completions、Anthropic Messages。

**Authoritative design:** `docs/superpowers/specs/2026-07-17-agent-platform-design.md`

---

## File and responsibility map

```text
server/
├── package.json                    # 服务端依赖与 Windows 命令
├── tsconfig.json                   # 严格类型检查，不输出 JS
├── src/
│   ├── main.ts                     # 进程入口与优雅退出
│   ├── app.ts                      # Fastify 组装，不读取全局环境
│   ├── config.ts                   # Zod 环境配置
│   ├── db/
│   │   ├── database.ts             # SQLite 打开、PRAGMA、事务
│   │   ├── migrate.ts              # 顺序迁移执行器
│   │   └── migrations/*.sql        # 用户、供应商、会话与 Agent 表
│   ├── security/
│   │   ├── password.ts             # Argon2id
│   │   ├── encryption.ts           # AES-256-GCM
│   │   ├── session.ts              # 随机令牌、哈希、Cookie
│   │   └── csrf.ts                 # Origin + 会话 CSRF 校验
│   ├── auth/                       # 用户注册、验证、登录、重置
│   ├── admin/                      # 单一管理员会话与供应商 API
│   ├── mail/                       # SMTP 端口与模板
│   ├── providers/                  # 统一协议、注册表和四类适配器
│   ├── tools/                      # 类型化工具、读写权限和现有能力适配
│   ├── agent/                      # 编排、事件流、确认、检查点、回退
│   └── conversations/              # 消息、运行摘要与删除
└── tests/                          # Fastify inject、SQLite 临时库与适配器测试

app/src/
├── api/                            # 同源 fetch、CSRF、SSE 解析
├── auth/                           # 登录、注册、验证、重置页面
├── admin/                          # `/admin` 独立页面与供应商配置
├── agent/                          # 指挥舱、消息、计划、轨迹、确认
├── embedded-tools/                 # 课程、图谱、任务、诊断内嵌卡
└── app/router.tsx                  # 小型 history 路由与守卫

scripts/
├── dev-windows.ps1                # 并行启动前后端
├── verify-windows.ps1             # 全量 Windows 验证
└── hash-admin-password.ps1        # 生成管理员 Argon2id 哈希
```

## Global execution rules

- 每个任务严格执行 RED → GREEN → REFACTOR；不能把多个任务的实现一次写完再补测试。
- 每次提交前运行该任务的目标测试和 `git diff --check`。
- 不提交 `.env.local`、`var/`、SQLite/WAL、真实邮件地址、API Key、管理员密码或真实模型响应。
- 真实供应商测试默认跳过；只有显式设置 `BHZD_LIVE_PROVIDER_TESTS=1` 才运行。
- 任一需求改变时先停下，修订设计、计划、验收和日志，再继续执行。

## Scope coverage summary

- 首期模型协议：讯飞星辰原生、讯飞星火原生、Chat Completions、Anthropic Messages。
- 供应商运行角色：管理员设置一个主模型和一个回退模型，并通过连接测试后启用。
- 用户主界面：Agent 指挥舱统一承载对话、计划、执行轨迹、确认门和四项嵌入式工具。
- 发布证据：Windows 自动化与真实模型验证通过后，仍需人工领域放行和 2-3 名师生真实试用。

---

### Task 1: Freeze baseline and prove Windows native dependencies

**Files:**
- Modify: `.gitignore`
- Modify: `app/vite.config.ts`
- Create: `server/package.json`
- Create: `server/tsconfig.json`
- Create: `server/src/config.ts`
- Create: `server/tests/native-dependencies.test.ts`
- Create: `.env.example`

- [ ] **Step 1: Record the untouched baseline**

Run:

```powershell
python -m pytest -q
npm.cmd --prefix app test -- --run
npm.cmd --prefix app run build
```

Expected: Python suite, 418 frontend tests, and production build pass before server work. Record exact counts in `docs/logs/document-changelog.md` only when implementation begins.

- [ ] **Step 2: Write the failing Windows dependency test**

```ts
// server/tests/native-dependencies.test.ts
import { afterEach, expect, test } from "vitest";
import Database from "better-sqlite3";
import argon2 from "argon2";

const databases: Database.Database[] = [];
afterEach(() => databases.splice(0).forEach((db) => db.close()));

test("opens an in-memory SQLite database and verifies Argon2id", async () => {
  const db = new Database(":memory:");
  databases.push(db);
  expect(db.prepare("select 1 as value").get()).toEqual({ value: 1 });

  const hash = await argon2.hash("local-test-password", {
    type: argon2.argon2id,
    memoryCost: 19_456,
    timeCost: 2,
    parallelism: 1,
  });
  expect(await argon2.verify(hash, "local-test-password")).toBe(true);
});
```

- [ ] **Step 3: Run RED before dependencies exist**

Run: `npm.cmd --prefix server test -- --run tests/native-dependencies.test.ts`

Expected: FAIL because `server/package.json` or native packages do not exist.

- [ ] **Step 4: Create the server package and strict configuration**

```json
// server/package.json
{
  "name": "bhzd-agent-server",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "engines": { "node": ">=22.12.0" },
  "scripts": {
    "dev": "tsx watch src/main.ts",
    "start": "tsx src/main.ts",
    "typecheck": "tsc --noEmit",
    "test": "vitest",
    "test:run": "vitest run"
  },
  "dependencies": {
    "@fastify/cookie": "^11.0.0",
    "@fastify/rate-limit": "^10.0.0",
    "@fastify/static": "^8.0.0",
    "@xmldom/xmldom": "^0.8.11",
    "argon2": "^0.41.0",
    "better-sqlite3": "^11.0.0",
    "fastify": "^5.0.0",
    "nodemailer": "^7.0.0",
    "zod": "^4.0.0"
  },
  "devDependencies": {
    "@types/better-sqlite3": "^7.6.0",
    "@types/node": "^22.0.0",
    "@types/nodemailer": "^7.0.0",
    "tsx": "^4.0.0",
    "typescript": "^5.0.0",
    "vitest": "^3.0.0"
  }
}
```

`server/tsconfig.json` must use `target: ES2022`, `module: ESNext`, `moduleResolution: Bundler`, `strict: true`, `resolveJsonModule: true`, `noEmit: true`, and include `src`, `tests`, plus the imported pure modules under `../app/src`.

Add `var/`, `server/.env.local`, `*.sqlite`, `*.sqlite-shm`, and `*.sqlite-wal` to `.gitignore`. Add non-secret names and localhost values to `.env.example`.

- [ ] **Step 5: Install and verify GREEN on Windows**

Run:

```powershell
npm.cmd --prefix server install
npm.cmd --prefix server test -- --run tests/native-dependencies.test.ts
npm.cmd --prefix server run typecheck
```

Expected: one dependency test passes and typecheck exits 0. If either native package cannot install on Node 22.12+, stop the plan and revise the approved SQLite/Argon2 implementation choice before Task 2.

- [ ] **Step 6: Add the development proxy**

Modify `app/vite.config.ts` so `server.proxy["/api"]` targets `http://127.0.0.1:8787` with `changeOrigin: false`. Do not proxy arbitrary paths.

- [ ] **Step 7: Commit**

```powershell
git add .gitignore .env.example app/vite.config.ts server
git commit -m "chore(agent): establish Windows server baseline"
```

---

### Task 2: Add environment validation, secrets, and health endpoint

**Files:**
- Create: `server/src/app.ts`
- Create: `server/src/main.ts`
- Modify: `server/src/config.ts`
- Create: `server/tests/config.test.ts`
- Create: `server/tests/health.test.ts`
- Create: `server/tests/support/testConfig.ts`

- [ ] **Step 1: Write failing config and health tests**

```ts
// server/tests/config.test.ts
import { expect, test } from "vitest";
import { parseConfig } from "../src/config";

test("rejects missing encryption and administrator hashes", () => {
  expect(() => parseConfig({ NODE_ENV: "test" })).toThrow(/BHZD_CONFIG_ENCRYPTION_KEY/);
});

test("accepts explicit test secrets without reading process.env", () => {
  const config = parseConfig({
    NODE_ENV: "test",
    BHZD_CONFIG_ENCRYPTION_KEY: Buffer.alloc(32, 7).toString("base64"),
    BHZD_ADMIN_PASSWORD_HASH: "$argon2id$test-only",
    BHZD_DATABASE_PATH: ":memory:",
    BHZD_PUBLIC_ORIGIN: "http://127.0.0.1:5173",
  });
  expect(config.port).toBe(8787);
});
```

```ts
// server/tests/health.test.ts
import { expect, test } from "vitest";
import { buildApp } from "../src/app";
import { testConfig } from "./support/testConfig";

test("returns a non-sensitive health response", async () => {
  const app = await buildApp({ config: testConfig() });
  const response = await app.inject({ method: "GET", url: "/api/health" });
  expect(response.statusCode).toBe(200);
  expect(response.json()).toEqual({ status: "ok" });
  expect(response.body).not.toContain("PASSWORD");
  await app.close();
});
```

- [ ] **Step 2: Run RED**

Run: `npm.cmd --prefix server test -- --run tests/config.test.ts tests/health.test.ts`

Expected: FAIL because `parseConfig`, `buildApp`, and test support do not exist.

- [ ] **Step 3: Implement the immutable config contract**

```ts
export interface AppConfig {
  readonly nodeEnv: "development" | "test" | "production";
  readonly host: string;
  readonly port: number;
  readonly publicOrigin: string;
  readonly databasePath: string;
  readonly encryptionKey: Uint8Array;
  readonly adminPasswordHash: string;
  readonly secureCookies: boolean;
}
```

`parseConfig(source)` must use Zod, decode exactly 32 Base64 bytes for `BHZD_CONFIG_ENCRYPTION_KEY`, reject wildcard origins, default host to `127.0.0.1`, port to `8787`, and set secure cookies only in production. It must never log `source`.

- [ ] **Step 4: Implement app assembly and process entry**

`buildApp(dependencies)` creates Fastify with `logger.redact` covering authorization, cookie, API key, password, SMTP password, and encryption key paths. Register `GET /api/health` only. `main.ts` parses `process.env`, starts the app, and handles `SIGINT`/`SIGTERM` by closing Fastify.

- [ ] **Step 5: Run GREEN**

Run:

```powershell
npm.cmd --prefix server test -- --run tests/config.test.ts tests/health.test.ts
npm.cmd --prefix server run typecheck
```

Expected: config and health tests pass; typecheck exits 0.

- [ ] **Step 6: Commit**

```powershell
git add server/src server/tests
git commit -m "feat(server): validate secrets and expose health"
```

---

### Task 3: Create SQLite migration and repository foundation

**Files:**
- Create: `server/src/db/database.ts`
- Create: `server/src/db/migrate.ts`
- Create: `server/src/db/migrations/001_identity.sql`
- Create: `server/src/db/migrations/002_providers.sql`
- Create: `server/src/db/migrations/003_agent.sql`
- Create: `server/tests/database.test.ts`
- Create: `server/tests/support/testDatabase.ts`

- [ ] **Step 1: Write the failing migration test**

```ts
test("creates identity, provider, conversation, tool, and confirmation tables", () => {
  const db = createTestDatabase();
  const tables = db.prepare(
    "select name from sqlite_master where type = 'table' order by name",
  ).all().map(({ name }) => name);
  expect(tables).toEqual(expect.arrayContaining([
    "users", "user_credentials", "email_verification_tokens",
    "password_reset_tokens", "user_sessions", "admin_sessions",
    "provider_configs", "provider_audit_events", "conversations",
    "messages", "agent_runs", "agent_events", "tool_calls",
    "pending_confirmations", "learning_profiles", "learning_events",
  ]));
  db.close();
});
```

Also assert `PRAGMA foreign_keys = 1`, migration re-entry is idempotent, and deleting a conversation cascades only its messages, runs, events, tool calls, and pending confirmations.

- [ ] **Step 2: Run RED**

Run: `npm.cmd --prefix server test -- --run tests/database.test.ts`

Expected: FAIL because database and migrations do not exist.

- [ ] **Step 3: Implement database opening and migrations**

`openDatabase(path)` must set `foreign_keys = ON`, `journal_mode = WAL` for file databases, `busy_timeout = 5000`, and return a typed `better-sqlite3` handle. `migrate(db)` creates `schema_migrations`, hashes migration SQL, rejects a changed already-applied migration, and applies each new migration inside a transaction.

Every identity/provider/Agent table must have explicit foreign keys and timestamps stored as UTC ISO strings. `provider_configs` must enforce partial unique indexes for one enabled primary and one enabled fallback. `pending_confirmations` must include `expires_at`, `status`, `idempotency_key`, and unique `(user_id, idempotency_key)`.

- [ ] **Step 4: Run GREEN**

Run: `npm.cmd --prefix server test -- --run tests/database.test.ts`

Expected: database tests pass with no temporary files left in the repository.

- [ ] **Step 5: Commit**

```powershell
git add server/src/db server/tests/database.test.ts server/tests/support/testDatabase.ts
git commit -m "feat(server): add SQLite persistence schema"
```

---

### Task 4: Implement password, encryption, session, and CSRF primitives

**Files:**
- Create: `server/src/security/password.ts`
- Create: `server/src/security/encryption.ts`
- Create: `server/src/security/session.ts`
- Create: `server/src/security/csrf.ts`
- Create: `server/tests/security.test.ts`
- Create: `scripts/hash-admin-password.ps1`

- [ ] **Step 1: Write failing security tests**

Test these exact properties:

```ts
expect(await verifyPassword(await hashPassword("Correct-Horse-9"), "Correct-Horse-9")).toBe(true);
expect(await verifyPassword(await hashPassword("Correct-Horse-9"), "wrong")).toBe(false);

const encrypted = encryptSecret("provider-key", keyOfByte(3), "provider:cfg-1");
expect(decryptSecret(encrypted, keyOfByte(3), "provider:cfg-1")).toBe("provider-key");
expect(() => decryptSecret(encrypted, keyOfByte(4), "provider:cfg-1")).toThrow();
expect(JSON.stringify(encrypted)).not.toContain("provider-key");

const session = createSessionMaterial();
expect(session.token).not.toBe(session.tokenHash);
expect(session.csrfToken).not.toBe(session.csrfTokenHash);
```

Also test constant-time CSRF comparison, exact Origin matching, and rejection of missing Origin on browser state-changing requests.

- [ ] **Step 2: Run RED**

Run: `npm.cmd --prefix server test -- --run tests/security.test.ts`

Expected: FAIL because security primitives do not exist.

- [ ] **Step 3: Implement minimal secure primitives**

- `hashPassword` uses Argon2id with the Task 1 parameters and rejects passwords shorter than 10 or longer than 128 Unicode code points.
- `encryptSecret` uses `aes-256-gcm`, a 12-byte random nonce, version `v1`, AAD, ciphertext, and auth tag encoded as Base64.
- Session and CSRF tokens use `randomBytes(32)`; stored hashes use SHA-256.
- CSRF validation requires exact configured Origin and `x-csrf-token` matching the authenticated session hash.
- `hash-admin-password.ps1` reads a SecureString interactively, invokes a small checked-in TypeScript CLI, and prints only the Argon2id hash.

- [ ] **Step 4: Run GREEN**

Run:

```powershell
npm.cmd --prefix server test -- --run tests/security.test.ts
npm.cmd --prefix server run typecheck
```

Expected: all security tests pass; no plaintext test secret appears in snapshots or logs.

- [ ] **Step 5: Commit**

```powershell
git add server/src/security server/tests/security.test.ts scripts/hash-admin-password.ps1
git commit -m "feat(security): add password encryption and session primitives"
```

---

### Task 5: Implement user registration, verification, login, and reset

**Files:**
- Create: `server/src/mail/mailer.ts`
- Create: `server/src/mail/templates.ts`
- Create: `server/src/auth/repository.ts`
- Create: `server/src/auth/service.ts`
- Create: `server/src/auth/routes.ts`
- Create: `server/src/auth/guard.ts`
- Create: `server/tests/auth.test.ts`
- Modify: `server/src/app.ts`
- Modify: `server/src/config.ts`

- [ ] **Step 1: Write failing Auth API tests**

Use Fastify `inject` with a memory mailer. Cover:

```ts
await request("POST", "/api/auth/register", { email: " Student@Example.com ", password: "Valid-Pass-19" })
  .expect(202, { message: "如果该邮箱可用，我们已发送验证邮件。" });

expect(await users.findByEmail("student@example.com")).toMatchObject({ status: "pending_verification" });
expect(mailer.sent).toHaveLength(1);

await request("POST", "/api/auth/login", { email: "student@example.com", password: "Valid-Pass-19" })
  .expect(401);
```

Then verify one-time email token activation, login Cookie flags, `/api/auth/session`, logout, generic forgot-password response for existing and missing email, one-time reset, and all old sessions revoked after reset.

- [ ] **Step 2: Run RED**

Run: `npm.cmd --prefix server test -- --run tests/auth.test.ts`

Expected: FAIL because Auth routes and repositories do not exist.

- [ ] **Step 3: Implement repository and service**

Normalize email with `trim().toLowerCase()`. Store password hashes separately from `users`. Verification and reset tokens expire after configurable periods, store only SHA-256 hashes, and are consumed transactionally. Login rotates sessions and sets `bhzd_user_session` plus readable CSRF response data; do not put CSRF token in a non-HttpOnly Cookie.

Mailer interface:

```ts
export interface Mailer {
  sendVerification(input: { to: string; verificationUrl: string }): Promise<void>;
  sendPasswordReset(input: { to: string; resetUrl: string }): Promise<void>;
}
```

Production implementation uses Nodemailer from `BHZD_SMTP_HOST`, port, secure mode, username, password, and `BHZD_MAIL_FROM`.

- [ ] **Step 4: Register rate-limited routes and guard**

Routes: register, verify-email, resend-verification, login, session, logout, forgot-password, reset-password. Rate-limit registration/reset by IP and normalized email. `requireUser` resolves token hash, checks expiry and user status, and attaches only `{ userId, email, csrfTokenHash }`.

- [ ] **Step 5: Run GREEN**

Run: `npm.cmd --prefix server test -- --run tests/auth.test.ts`

Expected: Auth tests pass; no response distinguishes a missing email during registration or reset.

- [ ] **Step 6: Commit**

```powershell
git add server/src/auth server/src/mail server/src/app.ts server/src/config.ts server/tests/auth.test.ts
git commit -m "feat(auth): add verified email user accounts"
```

---

### Task 6: Implement the single-administrator session and `/api/admin` guard

**Files:**
- Create: `server/src/admin/authService.ts`
- Create: `server/src/admin/authRoutes.ts`
- Create: `server/src/admin/guard.ts`
- Create: `server/tests/admin-auth.test.ts`
- Modify: `server/src/app.ts`

- [ ] **Step 1: Write failing administrator tests**

Verify: user Cookie cannot access admin, wrong passwords return the same 401 message, repeated failures reach 429/lockout, correct password creates `bhzd_admin_session`, CSRF is required for logout/write APIs, and no response contains the configured Argon2 hash.

```ts
expect((await app.inject({ method: "GET", url: "/api/admin/session" })).statusCode).toBe(401);
expect((await loginAdmin("wrong-password")).json()).toEqual({ message: "管理员认证失败。" });
expect((await loginAdmin("correct-password")).cookies.find(c => c.name === "bhzd_admin_session")?.httpOnly).toBe(true);
```

- [ ] **Step 2: Run RED**

Run: `npm.cmd --prefix server test -- --run tests/admin-auth.test.ts`

Expected: FAIL because admin auth is absent.

- [ ] **Step 3: Implement independent admin auth**

Verify against `config.adminPasswordHash`; never create an admin user row. Store only session token hash, CSRF hash, IP hash, created/expiry timestamps in `admin_sessions`. Use a 30-minute idle timeout and 8-hour absolute timeout. On successful login, clear the failure bucket for that IP; on repeated failures, apply exponential delay and a 15-minute lock after 8 failures.

- [ ] **Step 4: Run GREEN**

Run: `npm.cmd --prefix server test -- --run tests/admin-auth.test.ts`

Expected: admin tests pass, including Cookie separation and lockout.

- [ ] **Step 5: Commit**

```powershell
git add server/src/admin server/src/app.ts server/tests/admin-auth.test.ts
git commit -m "feat(admin): secure the single administrator session"
```

---

### Task 7: Add encrypted provider registry, audit, and health tests

**Files:**
- Create: `server/src/providers/types.ts`
- Create: `server/src/providers/configSchema.ts`
- Create: `server/src/providers/repository.ts`
- Create: `server/src/providers/registry.ts`
- Create: `server/src/admin/providerRoutes.ts`
- Create: `server/tests/providers.test.ts`
- Modify: `server/src/app.ts`

- [ ] **Step 1: Write failing provider registry tests**

Use protocol union:

```ts
export type ProviderProtocol =
  | "xunfei-xingchen"
  | "xunfei-spark"
  | "chat-completions"
  | "anthropic-messages";
```

Test create/update/disable/delete, encrypted database value, masked admin output, one primary and one fallback, prohibited headers, prohibited loopback/link-local/private Base URLs for custom remote providers, and audit rows that never contain plaintext secrets.

- [ ] **Step 2: Run RED**

Run: `npm.cmd --prefix server test -- --run tests/providers.test.ts`

Expected: FAIL because provider registry does not exist.

- [ ] **Step 3: Implement config validation and encrypted repository**

Provider input schema accepts `displayName`, protocol, HTTPS `baseUrl`, model, new API key, whitelisted optional headers, timeout 1-120 seconds, max output 1-32768, temperature 0-2, enabled, primary, fallback. Reject primary=fallback on the same record and reject enabling an untested configuration as primary.

Use AAD `provider:<id>` with Task 4 encryption. Admin reads return `hasApiKey`, `apiKeyMask` using only the last four characters, and never return encrypted fields.

- [ ] **Step 4: Implement administrator routes**

Routes: list, create, update, disable, delete, set roles, connection test, audit list. All writes require admin session + CSRF. Connection test must call an injected `ProviderTester`, save only error category, HTTP status, latency and remote model identifier.

- [ ] **Step 5: Run GREEN**

Run: `npm.cmd --prefix server test -- --run tests/providers.test.ts`

Expected: provider tests pass and raw SQLite inspection cannot find test API key text.

- [ ] **Step 6: Commit**

```powershell
git add server/src/providers server/src/admin/providerRoutes.ts server/src/app.ts server/tests/providers.test.ts
git commit -m "feat(admin): manage encrypted model providers"
```

---

### Task 8: Implement unified provider events plus Chat Completions and Anthropic

**Files:**
- Create: `server/src/providers/events.ts`
- Create: `server/src/providers/adapter.ts`
- Create: `server/src/providers/http.ts`
- Create: `server/src/providers/chatCompletions.ts`
- Create: `server/src/providers/anthropicMessages.ts`
- Create: `server/tests/provider-adapters.test.ts`
- Create: `server/tests/fixtures/providers/*.txt`

- [ ] **Step 1: Write failing fixture-driven adapter tests**

Define the adapter contract:

```ts
export interface ProviderAdapter {
  stream(input: ProviderRunInput, signal: AbortSignal): AsyncIterable<ProviderEvent>;
}

export type ProviderEvent =
  | { type: "message.delta"; text: string }
  | { type: "tool.call.delta"; callId: string; name?: string; argumentsDelta?: string }
  | { type: "tool.call.completed"; callId: string; name: string; argumentsJson: string }
  | { type: "run.usage"; inputTokens?: number; outputTokens?: number }
  | { type: "run.completed"; finishReason: string };
```

Fixtures must cover split SSE frames, `[DONE]`, Chat Completions `delta.tool_calls`, Anthropic `content_block_start/delta/stop`, UTF-8 split boundaries, abort, non-2xx JSON, and secret-redacted errors.

- [ ] **Step 2: Run RED**

Run: `npm.cmd --prefix server test -- --run tests/provider-adapters.test.ts`

Expected: FAIL because adapters and fixture parser do not exist.

- [ ] **Step 3: Implement the bounded streaming HTTP client**

Use Node `fetch`, explicit timeout with `AbortSignal.any`, maximum response header/body/event sizes, HTTPS-only provider URL from validated config, and SSE parsing that buffers incomplete lines. Do not follow redirects to a different origin. Map network, timeout, auth, rate-limit, upstream, safety and protocol errors to a closed union.

- [ ] **Step 4: Implement both adapters**

Chat Completions posts `messages`, `tools`, `tool_choice: "auto"`, `stream: true`, model and configured sampling values. Anthropic posts `messages`, `system`, `tools`, `stream: true`, model, `max_tokens`, and the required API version header. Both reconstruct tool arguments by call ID and emit the shared event union.

- [ ] **Step 5: Run GREEN**

Run:

```powershell
npm.cmd --prefix server test -- --run tests/provider-adapters.test.ts
npm.cmd --prefix server run typecheck
```

Expected: all fixture tests pass without real network access.

- [ ] **Step 6: Commit**

```powershell
git add server/src/providers server/tests/provider-adapters.test.ts server/tests/fixtures/providers
git commit -m "feat(agent): adapt Chat Completions and Anthropic streams"
```

---

### Task 9: Freeze current Xunfei contracts and implement native adapters

**Files:**
- Create: `docs/references/providers/xunfei-contracts.md`
- Create: `server/src/providers/xunfeiXingchen.ts`
- Create: `server/src/providers/xunfeiSpark.ts`
- Create: `server/tests/xunfei-adapters.test.ts`
- Create: `server/tests/fixtures/providers/xunfei-*.txt`
- Create: `server/tests/live/xunfei-live.test.ts`
- Modify: `docs/logs/document-changelog.md`

- [ ] **Step 1: Obtain and record current official contracts**

With valid project accounts, record in `xunfei-contracts.md` for each product: official documentation URL, access date, endpoint family, required credential fields, signature algorithm, streaming transport, tool-call capability, request/response version and account permission used. Do not copy credentials or entire private console pages.

Hard gate: if official documentation or account access does not establish any field, mark the task blocked and do not invent the request. This is the only acceptable blocking outcome for this task.

- [ ] **Step 2: Save sanitized fixtures and write failing tests**

Fixtures must be captured from official examples or the project account, replace identifiers and text with safe values, and preserve framing. Tests require both adapters to emit the same `ProviderEvent` union as Task 8 and classify signature/auth, quota, safety, malformed frame and disconnect errors.

- [ ] **Step 3: Run RED**

Run: `npm.cmd --prefix server test -- --run tests/xunfei-adapters.test.ts`

Expected: FAIL because native adapters are not implemented.

- [ ] **Step 4: Implement Xingchen and Spark separately**

Do not share authentication code unless the frozen contracts are identical. Each adapter accepts a typed credential object derived from encrypted provider config, creates only the required signature/headers, parses its native stream, and maps text/tool/usage/finish information to `ProviderEvent`.

- [ ] **Step 5: Run offline GREEN and optional live smoke**

Run:

```powershell
npm.cmd --prefix server test -- --run tests/xunfei-adapters.test.ts
$env:BHZD_LIVE_PROVIDER_TESTS='1'; npm.cmd --prefix server test -- --run tests/live/xunfei-live.test.ts
```

Expected: offline fixtures always pass. Live tests run only with explicit environment secrets, produce a stream and a read-tool request, and log only provider ID, latency and result category.

- [ ] **Step 6: Update document changelog and commit**

```powershell
git add docs/references/providers/xunfei-contracts.md docs/logs/document-changelog.md server/src/providers server/tests
git commit -m "feat(agent): add native Xunfei provider adapters"
```

---

### Task 10: Wrap existing deterministic capabilities in a typed Tool Gateway

**Files:**
- Create: `server/src/tools/types.ts`
- Create: `server/src/tools/catalog.ts`
- Create: `server/src/tools/courseTool.ts`
- Create: `server/src/tools/graphTool.ts`
- Create: `server/src/tools/taskTool.ts`
- Create: `server/src/tools/diagnosticsTool.ts`
- Create: `server/src/tools/learningTool.ts`
- Create: `server/src/tools/gateway.ts`
- Create: `server/tests/tools.test.ts`
- Modify: `server/tsconfig.json`

- [ ] **Step 1: Write failing tool catalog and permission tests**

```ts
export type ToolPermission = "read" | "write";
export interface ToolDefinition<I, O> {
  readonly name: string;
  readonly description: string;
  readonly permission: ToolPermission;
  readonly inputSchema: z.ZodType<I>;
  execute(input: I, context: ToolContext): Promise<O>;
}
```

Assert the exact tools and permissions from the design: `course.search`, `graph.query`, `task.preview`, `task.create`, `diagnostics.preview`, `diagnostics.saveSummary`, `learning.previewUpdate`, `learning.commitUpdate`. Invalid tool names and arguments must never reach an executor.

- [ ] **Step 2: Run RED**

Run: `npm.cmd --prefix server test -- --run tests/tools.test.ts`

Expected: FAIL because Tool Gateway is absent.

- [ ] **Step 3: Implement read adapters over existing modules**

Import the canonical repository, graph engine, task converter and diagnostic functions from `app/src` through explicit relative paths. Do not import React components or browser state. Install `DOMParser` from `@xmldom/xmldom` only inside diagnostics execution. Convert outputs to JSON-safe immutable objects and include source/rule/node references.

`diagnostics.preview` accepts `{ name, size, type, text, unitId, scenarioId }`, rejects files over 5 MiB before parsing, and never writes the text to SQLite or logs.

- [ ] **Step 4: Implement write tools behind injected repositories**

Write tools require a confirmed execution context containing `confirmationId`, `userId`, `idempotencyKey`, and transaction handle. Calling them without this context throws `ConfirmationRequiredError`; repeating an idempotency key returns the recorded result without applying a second state change.

- [ ] **Step 5: Run GREEN and existing regressions**

Run:

```powershell
npm.cmd --prefix server test -- --run tests/tools.test.ts
npm.cmd --prefix app test -- --run tests/tasks/taskConverter.test.ts tests/diagnostics/diagnostics.test.ts tests/graph/graphEngine.test.ts
```

Expected: Tool Gateway tests and existing task/diagnostic/graph tests pass.

- [ ] **Step 6: Commit**

```powershell
git add server/src/tools server/tests/tools.test.ts server/tsconfig.json
git commit -m "feat(agent): expose deterministic teaching tools"
```

---

### Task 11: Implement Agent runs, confirmation gates, checkpoints, and fallback

**Files:**
- Create: `server/src/agent/events.ts`
- Create: `server/src/agent/repository.ts`
- Create: `server/src/agent/orchestrator.ts`
- Create: `server/src/agent/confirmationService.ts`
- Create: `server/src/agent/routes.ts`
- Create: `server/tests/orchestrator.test.ts`
- Create: `server/tests/agent-routes.test.ts`
- Modify: `server/src/app.ts`

- [ ] **Step 1: Write failing orchestrator state-machine tests**

Cover exact transitions:

```text
created -> streaming -> tool_read -> streaming -> completed
created -> streaming -> confirmation_required -> confirmed -> tool_write -> completed
created -> provider_failed_before_output -> fallback_streaming -> completed
created -> streaming_with_visible_output -> provider_failed -> paused
confirmation_required -> expired
```

Assert no write tool executes before confirmation, a replayed confirmation is idempotent, and fallback never automatically replays after visible output or a write tool.

- [ ] **Step 2: Run RED**

Run: `npm.cmd --prefix server test -- --run tests/orchestrator.test.ts`

Expected: FAIL because orchestrator is absent.

- [ ] **Step 3: Implement persisted public events**

Use only the design event names: `run.started`, `plan.updated`, `message.delta`, `tool.call.requested`, `tool.call.started`, `tool.call.completed`, `confirmation.required`, `run.completed`, `run.failed`. Persist sequence numbers and public payloads; do not persist hidden chain-of-thought or provider secrets.

- [ ] **Step 4: Implement the tool loop and confirmation service**

Parse completed provider tool arguments through the catalog schema. Execute reads immediately. For writes, store a 10-minute pending confirmation containing a human-readable preview, tool name, validated arguments, user/conversation/run IDs, and idempotency key. Confirmation API revalidates ownership, CSRF, expiry and current status before executing transactionally.

- [ ] **Step 5: Implement fallback boundaries**

Registry supplies primary and optional fallback adapters. Automatically fall back only when no visible delta, read/write tool result or confirmation was emitted. Otherwise emit a paused failure with an explicit `canRetryWithFallback` flag; user action starts a new run linked by `resumes_run_id`.

- [ ] **Step 6: Run GREEN**

Run:

```powershell
npm.cmd --prefix server test -- --run tests/orchestrator.test.ts tests/agent-routes.test.ts
npm.cmd --prefix server run typecheck
```

Expected: state-machine and API tests pass; all event sequences are monotonic.

- [ ] **Step 7: Commit**

```powershell
git add server/src/agent server/src/app.ts server/tests/orchestrator.test.ts server/tests/agent-routes.test.ts
git commit -m "feat(agent): orchestrate tools confirmations and fallback"
```

---

### Task 12: Persist conversations, messages, summaries, and deletion

**Files:**
- Create: `server/src/conversations/repository.ts`
- Create: `server/src/conversations/routes.ts`
- Create: `server/tests/conversations.test.ts`
- Modify: `server/src/agent/orchestrator.ts`
- Modify: `server/src/app.ts`

- [ ] **Step 1: Write failing ownership and deletion tests**

Test create/list/get, stable pagination, two users cannot read each other's conversations, message/run/tool summaries persist, raw diagnostic input never appears in any table, deleting one conversation cascades its Agent data, and clear-all removes only the current user's conversations.

- [ ] **Step 2: Run RED**

Run: `npm.cmd --prefix server test -- --run tests/conversations.test.ts`

Expected: FAIL because conversation routes are absent.

- [ ] **Step 3: Implement repositories and routes**

Routes: `POST /api/conversations`, `GET /api/conversations`, `GET /api/conversations/:id`, `DELETE /api/conversations/:id`, `DELETE /api/conversations`. All require user session; deletes require CSRF. Titles default to the first 60 visible characters and can be updated only by the owner.

Persist user/assistant visible messages and structured tool summaries. For diagnostics, save only format, issue counts, rule/capability refs, severity and explicit user-confirmed learning changes.

- [ ] **Step 4: Run GREEN**

Run: `npm.cmd --prefix server test -- --run tests/conversations.test.ts`

Expected: all ownership, persistence and deletion tests pass.

- [ ] **Step 5: Commit**

```powershell
git add server/src/conversations server/src/agent/orchestrator.ts server/src/app.ts server/tests/conversations.test.ts
git commit -m "feat(agent): persist user conversations safely"
```

---

### Task 13: Add frontend routing, Auth pages, and session API

**Files:**
- Create: `app/src/api/client.ts`
- Create: `app/src/api/sse.ts`
- Create: `app/src/app/router.tsx`
- Create: `app/src/auth/AuthProvider.tsx`
- Create: `app/src/auth/LoginPage.tsx`
- Create: `app/src/auth/RegisterPage.tsx`
- Create: `app/src/auth/VerifyEmailPage.tsx`
- Create: `app/src/auth/ForgotPasswordPage.tsx`
- Create: `app/src/auth/ResetPasswordPage.tsx`
- Create: `app/tests/auth/authFlow.test.tsx`
- Modify: `app/src/main.tsx`
- Modify: `app/src/app/app.css`

- [ ] **Step 1: Write failing Auth routing tests**

Using React Testing Library and a fake API transport, verify unauthenticated `/` redirects to `/login`, `/admin` is not present in normal links, registration shows generic success, verified login routes to `/`, Auth API failures preserve the email field, and reset-password removes the token from visible UI after submission.

- [ ] **Step 2: Run RED**

Run: `npm.cmd --prefix app test -- --run tests/auth/authFlow.test.tsx`

Expected: FAIL because routing/Auth pages do not exist.

- [ ] **Step 3: Implement a small history router and API client**

The router recognizes only the paths in the design and listens to `popstate`. `apiClient` always uses `credentials: "same-origin"`, sends JSON only to `/api`, attaches the in-memory CSRF token to state-changing authenticated requests, and converts non-2xx responses into typed `{ code, message, status }` errors.

- [ ] **Step 4: Implement accessible Auth pages**

Each page uses real `<form>`, labels, autocomplete attributes, inline validation, pending state, `aria-live` result, and one primary action. Do not expose password policy as long design prose; show concise requirements adjacent to the password field.

- [ ] **Step 5: Run GREEN and app regression**

Run:

```powershell
npm.cmd --prefix app test -- --run tests/auth/authFlow.test.tsx
npm.cmd --prefix app test -- --run
```

Expected: Auth tests and the full frontend suite pass.

- [ ] **Step 6: Commit**

```powershell
git add app/src/api app/src/auth app/src/app/router.tsx app/src/main.tsx app/src/app/app.css app/tests/auth
git commit -m "feat(web): add verified email authentication flows"
```

---

### Task 14: Build the hidden-route administrator UI

**Files:**
- Create: `app/src/admin/AdminPage.tsx`
- Create: `app/src/admin/AdminLogin.tsx`
- Create: `app/src/admin/ProviderList.tsx`
- Create: `app/src/admin/ProviderEditor.tsx`
- Create: `app/src/admin/ProviderHealth.tsx`
- Create: `app/tests/admin/adminPage.test.tsx`
- Modify: `app/src/app/router.tsx`
- Modify: `app/src/app/app.css`

- [ ] **Step 1: Write failing `/admin` tests**

Verify direct navigation shows only the administrator password form when unauthenticated; no ordinary page links to `/admin`; authenticated admin can add four protocol types, cannot see a full stored key, must provide CSRF for writes, can test connection, and cannot select an untested/disabled provider as primary.

- [ ] **Step 2: Run RED**

Run: `npm.cmd --prefix app test -- --run tests/admin/adminPage.test.tsx`

Expected: FAIL because Admin UI does not exist.

- [ ] **Step 3: Implement the Admin route and pages**

Keep Admin state separate from `AuthProvider`. Provider editor shows protocol-specific labels but sends the common registry shape. Existing key input is blank with “已保存，留空则不更换”; never place a masked key in the input value. Destructive delete requires an inline confirmation naming the provider.

- [ ] **Step 4: Run GREEN**

Run:

```powershell
npm.cmd --prefix app test -- --run tests/admin/adminPage.test.tsx
npm.cmd --prefix app run build
```

Expected: Admin tests and production build pass; built public HTML contains no visible Admin link.

- [ ] **Step 5: Commit**

```powershell
git add app/src/admin app/src/app/router.tsx app/src/app/app.css app/tests/admin
git commit -m "feat(web): add hidden-route provider administration"
```

---

### Task 15: Replace four-mode shell with Agent Cockpit and embedded tools

**Files:**
- Create: `app/src/agent/AgentCockpit.tsx`
- Create: `app/src/agent/ConversationList.tsx`
- Create: `app/src/agent/MessageStream.tsx`
- Create: `app/src/agent/PlanStrip.tsx`
- Create: `app/src/agent/ExecutionTrace.tsx`
- Create: `app/src/agent/ConfirmationCard.tsx`
- Create: `app/src/agent/Composer.tsx`
- Create: `app/src/agent/useAgentRun.ts`
- Create: `app/src/embedded-tools/CourseResult.tsx`
- Create: `app/src/embedded-tools/GraphResult.tsx`
- Create: `app/src/embedded-tools/TaskResult.tsx`
- Create: `app/src/embedded-tools/DiagnosticResult.tsx`
- Create: `app/tests/agent/agentCockpit.test.tsx`
- Create: `tests/e2e/agent-cockpit.spec.ts`
- Modify: `app/src/app/App.tsx`
- Modify: `app/src/app/app.css`

- [ ] **Step 1: Write failing Agent Cockpit component tests**

Cover: no four top-level work-mode Tabs; direct prompt starts a run; plan states update from events; read tool appears inline; write tool shows confirmation; rejecting confirmation leaves state unchanged; execution trace exposes public steps only; “专注视图” opens the existing graph/course/task/diagnostic component and returns focus to the invoking card.

- [ ] **Step 2: Run RED**

Run: `npm.cmd --prefix app test -- --run tests/agent/agentCockpit.test.tsx`

Expected: FAIL because Agent Cockpit components do not exist.

- [ ] **Step 3: Implement streaming state reducer**

`useAgentRun` owns a reducer keyed by run ID and event sequence. Ignore duplicate sequence numbers, reconnect with `Last-Event-ID`, stop on logout/unmount, and represent status as `idle | connecting | streaming | awaiting_confirmation | paused | completed | failed`. It must not infer tool success before `tool.call.completed`.

- [ ] **Step 4: Implement the approved information architecture**

- Top: brand, Agent status, context, user menu; no course/graph/task/diagnostic Tabs.
- Left: current mission, mounted capabilities, recent conversations.
- Center: messages, concise plan, embedded results, one primary next action.
- Right: collapsible execution trace and context.
- Narrow screens: left becomes drawer, right becomes bottom sheet, embedded tools become one column.

Keep production copy concise. Put tool parameters, rule detail, privacy boundary and full trace behind expandable details or focus view.

- [ ] **Step 5: Reuse existing workspaces in focus mode**

Do not duplicate graph layout, lesson view, task card or diagnostic report logic. Wrap existing components with typed embedded-result adapters; preserve their data-test selectors and keyboard behavior. Existing local profile becomes a one-time migration source after login, with explicit user confirmation before server import.

- [ ] **Step 6: Run GREEN and E2E**

Run:

```powershell
npm.cmd --prefix app test -- --run tests/agent/agentCockpit.test.tsx
npm.cmd --prefix app test -- --run
npm.cmd --prefix app run test:e2e -- tests/e2e/agent-cockpit.spec.ts
```

Expected: Agent component tests, full frontend suite, and Agent E2E pass at desktop and 390px viewport.

- [ ] **Step 7: Commit**

```powershell
git add app/src/agent app/src/embedded-tools app/src/app/App.tsx app/src/app/app.css app/tests/agent tests/e2e/agent-cockpit.spec.ts
git commit -m "feat(web): make Agent the unified teaching workspace"
```

---

### Task 16: Complete Windows verification, live provider gates, docs, and release evidence

**Files:**
- Create: `scripts/dev-windows.ps1`
- Create: `scripts/verify-windows.ps1`
- Create: `server/tests/security-boundaries.test.ts`
- Create: `server/tests/live/provider-live.test.ts`
- Modify: `evidence/user-trials/trial-protocol.md`
- Modify: `evidence/user-trials/trial-record-template.md`
- Modify: `docs/superpowers/specs/2026-07-17-agent-platform-design.md`
- Modify: `docs/superpowers/plans/2026-07-17-agent-platform-implementation.md`
- Modify: `docs/开发流程与里程碑.md`
- Modify: `docs/功能验收与赛事提交清单.md`
- Modify: `docs/标航智导.md`
- Modify: `docs/logs/document-changelog.md`

- [ ] **Step 1: Write failing cross-cutting security tests**

Assert logs/responses/SQLite contain none of seeded passwords, API keys, reset tokens or uploaded file text; SSRF validation rejects localhost/private/link-local/mixed-encoding IPs and cross-origin redirects; user/admin Cookies are not interchangeable; expired confirmations do not execute; concurrent idempotent confirms apply one write.

- [ ] **Step 2: Run RED**

Run: `npm.cmd --prefix server test -- --run tests/security-boundaries.test.ts`

Expected: FAIL for any unclosed cross-cutting boundary; fix the owning module minimally and rerun until GREEN.

- [ ] **Step 3: Add Windows scripts**

`dev-windows.ps1` validates Node version and required environment names, migrates SQLite, starts server hidden and Vite in the current terminal, and stops the child server on exit. `verify-windows.ps1` runs Python tests, graph/scenario validators, server typecheck/tests, frontend tests/build/E2E, secret scan and `git diff --check`, stopping on the first failure.

- [ ] **Step 4: Add opt-in live provider matrix**

`provider-live.test.ts` reads only provider IDs from a seeded administrator-created database. With `BHZD_LIVE_PROVIDER_TESTS=1`, for each enabled protocol it records: connection status, streaming text received, a read-tool request, latency and sanitized error category. It must skip absent configurations and never print configuration values.

- [ ] **Step 5: Run full fresh verification**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify-windows.ps1
```

Expected: all Python, graph, scenario, server, frontend, build and Edge/Chromium flows pass. Vite chunk-size advisories may remain documented but cannot hide failures.

- [ ] **Step 6: Run genuine trials only after release approval**

Update the protocol to cover login, direct task prompt, automatic graph/course tool selection, confirmed task creation, deterministic exercise, diagnostic preview, confirmed summary, history deletion, and recovery from one provider failure. Obtain actual human-domain release approval and 2-3 genuine participants; do not create synthetic participant records.

- [ ] **Step 7: Synchronize status documents**

Mark only evidence-backed milestones complete. Record actual protocol/model names tested, Windows versions, browser versions, SMTP provider class, test counts, remaining provider/account gaps, and Linux/Docker as unstarted. Add the required document changelog and external Obsidian work log.

- [ ] **Step 8: Final commit**

```powershell
git add scripts server/tests evidence docs
git commit -m "docs(agent): record verified Windows Agent release"
```

---

## Plan self-review checklist

- [x] Every first-phase design requirement maps to a task: Windows service, SQLite, user Auth, SMTP, single admin, hidden `/admin`, encrypted providers, four protocols, primary/fallback, typed tools, confirmation gates, conversations, embedded UI, privacy, tests and trials.
- [x] Linux/Docker and Xunfei platform hosting are not treated as first-phase completion; they remain explicit later milestones in the design and development roadmap.
- [x] Provider secrets and administrator credentials have one storage path each and never appear in committed fixtures.
- [x] Provider event names, tool names, session Cookie names and confirmation semantics remain consistent across tasks.
- [x] Every code-producing task starts with a failing test, specifies the RED command, minimal implementation boundary, GREEN command and commit.
- [x] Existing deterministic modules are reused through adapters; no task duplicates authoritative graph, course, task-conversion or diagnostic logic.
- [x] The Xunfei implementation has an explicit official-contract hard gate instead of guessed authentication or payload fields.
