import { createRequire } from "node:module";
import { resolve } from "node:path";

const requireFromApp = createRequire(
  resolve(__dirname, "../../app/package.json"),
);

// tests/e2e 位于 app/ 之外，Node 无法沿目录链解析到 app/node_modules，
// 因此统一从这里用 createRequire 以 app/package.json 为锚点导出运行时。
export const { expect, test, request } = requireFromApp("@playwright/test");
