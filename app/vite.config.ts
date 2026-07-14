import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const appRoot = fileURLToPath(new URL(".", import.meta.url));
const dataRoot = fileURLToPath(new URL("../data/", import.meta.url));

export default defineConfig({
  plugins: [react()],
  server: {
    fs: {
      allow: [appRoot, dataRoot],
    },
  },
  test: {
    environment: "jsdom",
  },
});
