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
  use: {
    baseURL: "http://127.0.0.1:4173",
  },
  webServer: {
    command: "npm run dev -- --mode test --port 4173",
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
