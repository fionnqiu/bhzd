// vitest 全局准备：jest-dom 断言扩展 + 每个用例后卸载组件树
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// 兼容垫片（为什么需要）：react-router v7 数据路由在导航时会用
// `new Request(url, { signal })` 构造内部请求；jsdom 自带的 AbortSignal
// 与 Node undici Request 校验的 AbortSignal 不是同一个类（instanceof 失败，
// 路由跳转直接抛 TypeError）。测试环境没有中断语义需求，包一层丢弃
// 不兼容的 signal 即可，不影响真实浏览器行为。
const NativeRequest = globalThis.Request;
globalThis.Request = class extends NativeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    if (init?.signal) {
      const { signal: _dropped, ...rest } = init;
      super(input, rest);
    } else {
      super(input, init);
    }
  }
} as typeof Request;

afterEach(() => {
  cleanup();
  // 组件可能写 localStorage；用例间必须隔离
  localStorage.clear();
});
