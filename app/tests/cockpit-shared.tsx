/**
 * 指挥舱测试共享桩（cockpit.test.tsx / cockpit-flow.test.tsx 共用）。
 *
 * 为什么抽出来：两个测试文件的 api 桩工厂与 FakeRunEventStream 完全相同，
 * 复制两份只会让后续契约调整改两遍。
 *
 * 关键约束（踩过的坑）：本模块**绝不能静态 import ../src/api/client 或
 * CockpitPage**——vi.mock 工厂会 `await import("./cockpit-shared")`，
 * 若共享模块又依赖被 mock 的模块，工厂等待自身解决形成循环死锁
 * （vitest 表现为零输出挂起）。mock 的 api 对象由工厂注册进来，
 * CockpitPage 的渲染装配留在各测试文件里（测试文件自身 import 无此问题）。
 *
 * 用法（各测试文件内，vi.mock 工厂必须留在测试文件里才能被正确提升）：
 * ```ts
 * vi.mock("../src/api/client", async () =>
 *   (await import("./cockpit-shared")).buildApiClientMock());
 * vi.mock("../src/api/sse", async () =>
 *   (await import("./cockpit-shared")).buildSseMock());
 * ```
 */
import { waitFor } from "@testing-library/react";
import { expect, vi } from "vitest";

/* ---------------------------------------------------------- api 桩 */

/** 与生产 ApiRequestError 同构的 mock 错误类（instanceof 判定依赖同一类对象） */
export class MockApiRequestError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
  }
}

type MockApi = {
  get: ReturnType<typeof vi.fn>;
  post: ReturnType<typeof vi.fn>;
  put: ReturnType<typeof vi.fn>;
  patch: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
  postForm: ReturnType<typeof vi.fn>;
};

// 工厂创建 mock api 后注册到这里，installDefaultGetMock 据此配置默认桩
// （本模块不能 import api/client，见模块头注释）
let registeredApi: MockApi | null = null;

/** ../src/api/client 的 vi.mock 工厂（与 router.test.tsx 同模式） */
export function buildApiClientMock() {
  const api: MockApi = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    postForm: vi.fn(),
  };
  registeredApi = api;
  return {
    ApiRequestError: MockApiRequestError,
    api,
    request: vi.fn(),
    setCsrfToken: vi.fn(),
    getCsrfToken: vi.fn(() => null),
    setOnUnauthorized: vi.fn(),
  };
}

/** 默认 GET 桩：四栏数据/会话/掌握度全部空集合（各用例可按需覆盖） */
export function installDefaultGetMock(): void {
  if (!registeredApi) throw new Error("api mock 尚未注册（vi.mock 工厂未执行）");
  registeredApi.get.mockImplementation(async (path: string) => {
    if (path === "/api/presets") return { items: [], total: 0 };
    if (path === "/api/tasks") return { items: [], total: 0 };
    if (path === "/api/conversations") return { items: [], total: 0 };
    if (path === "/api/profile/mastery") return { items: [], total: 0 };
    throw new MockApiRequestError(404, "NOT_FOUND", `未预期的 GET ${path}`);
  });
}

/* ------------------------------------------------------ SSE 伪事件流 */

/** 记录所有实例的伪事件流；emit 即"播放"一帧 SSE */
type FakeStreamOptions = {
  onConnected?: (lastSeq: number) => void;
  onInterrupted?: (event: {
    retryAttempt: number | null;
    retryInMs: number | null;
    lastSeq: number;
  }) => void;
  onExhausted?: (event: { attempts: number; lastSeq: number }) => void;
};

export class FakeRunEventStream {
  static instances: FakeRunEventStream[] = [];
  handlers = new Map<string, ((p: never, seq: number) => void)[]>();
  endHandlers: (() => void)[] = [];
  closed = false;
  lastSeq = 0;
  constructor(
    public runId: string,
    private readonly options: FakeStreamOptions = {},
  ) {
    FakeRunEventStream.instances.push(this);
  }
  on(type: string, handler: (p: never, seq: number) => void) {
    const list = this.handlers.get(type) ?? [];
    list.push(handler);
    this.handlers.set(type, list);
    return () => {};
  }
  onStreamEnd(handler: () => void) {
    this.endHandlers.push(handler);
    return () => {};
  }
  close() {
    this.closed = true;
  }
  emit(type: string, payload: Record<string, unknown>) {
    if (typeof payload.seq === "number") this.lastSeq = Math.max(this.lastSeq, payload.seq);
    for (const h of this.handlers.get(type) ?? []) {
      h(payload as never, (payload.seq as number) ?? 1);
    }
  }
  connected() {
    this.options.onConnected?.(this.lastSeq);
  }
  interrupted(retryAttempt = 1, retryInMs = 500) {
    this.options.onInterrupted?.({ retryAttempt, retryInMs, lastSeq: this.lastSeq });
  }
  exhausted() {
    this.options.onInterrupted?.({ retryAttempt: null, retryInMs: null, lastSeq: this.lastSeq });
    this.options.onExhausted?.({ attempts: 3, lastSeq: this.lastSeq });
  }
  end() {
    for (const h of this.endHandlers) h();
  }
}

/** ../src/api/sse 的 vi.mock 工厂 */
export function buildSseMock() {
  return { RunEventStream: FakeRunEventStream, STREAM_END_EVENT: "stream.end" };
}

/** 最近一次创建的流（每次发运行都会新建） */
export function latestStream(): FakeRunEventStream {
  const stream = FakeRunEventStream.instances[FakeRunEventStream.instances.length - 1];
  if (!stream) throw new Error("尚未创建 RunEventStream");
  return stream;
}

/** 等 POST /api/runs resolve、事件流真正挂上（避免断言抢在微任务前） */
export async function waitForStream(): Promise<void> {
  await waitFor(() => expect(FakeRunEventStream.instances.length).toBeGreaterThan(0));
}
