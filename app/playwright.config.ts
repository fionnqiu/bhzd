import { existsSync } from "node:fs";
import { join } from "node:path";

import { defineConfig } from "@playwright/test";

const edgeExecutableCandidates = [
  process.env.ProgramFiles,
  process.env["ProgramFiles(x86)"],
  process.env.LOCALAPPDATA,
]
  .filter((directory): directory is string => typeof directory === "string")
  .map((directory) =>
    join(directory, "Microsoft", "Edge", "Application", "msedge.exe"),
  );

const hasMsEdge = edgeExecutableCandidates.some((candidate) =>
  existsSync(candidate),
);

export default defineConfig({
  testDir: "../tests/e2e",
  // The login limiter (NF5: 5 attempts/min/IP) can force ensureSession and the
  // UI-login test into a 61s backoff; 30s would kill the test mid-wait.
  timeout: 200_000,
  // The suite deliberately shares one seeded SQLite database and two demo accounts.
  // Parallel workers contend for the same write lock and can trip the global login
  // limiter, yielding false UI timeouts instead of product-level failures.
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:4173",
  },
  webServer: {
    // Keep the dev server on the same lockfile-backed package manager as the test runner.
    // Invoke Vite directly: pnpm v11 forwards the separator from `run` literally,
    // which otherwise prevents Vite from receiving the test mode and port options.
    command: "pnpm exec vite --host 127.0.0.1 --mode test --port 4173",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: false,
    timeout: 120_000,
  },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
    ...(hasMsEdge
      ? [
          {
            name: "msedge",
            use: { browserName: "chromium", channel: "msedge" },
          },
        ]
      : []),
  ],
});
