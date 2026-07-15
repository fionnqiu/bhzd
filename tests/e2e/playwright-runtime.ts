import { createRequire } from "node:module";
import { resolve } from "node:path";

const requireFromApp = createRequire(
  resolve(__dirname, "../../app/package.json"),
);

export const { expect, test } = requireFromApp("@playwright/test");
