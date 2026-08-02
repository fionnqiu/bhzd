import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const appRoot = fileURLToPath(new URL(".", import.meta.url));
const dataRoot = fileURLToPath(new URL("../data/", import.meta.url));
// A test snapshot can point Vite at its own backend without changing the normal local default.
const apiTarget = process.env.VITE_API_TARGET?.trim() || "http://127.0.0.1:8787";

export default defineConfig({
  plugins: [react()],
  build: {
    manifest: true,
  },
  server: {
    fs: {
      allow: [appRoot, dataRoot],
    },
    proxy: {
      // 后端 FastAPI（127.0.0.1:8787）；同源代理让 cookie/SSE 都走 vite 端口
      "/api": {
        target: apiTarget,
        changeOrigin: false,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    // 测试只测纯前端逻辑（守卫/客户端/页面渲染），不依赖真实后端
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
