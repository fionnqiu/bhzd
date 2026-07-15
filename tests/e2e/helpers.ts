import { resolve } from "node:path";

import type { Page } from "@playwright/test";

export const LEARNING_PROFILE_STORAGE_KEY = "bhzd.learning-profile.v1";

export const fixturePath = (fileName: string): string =>
  resolve(__dirname, "fixtures", fileName);

export const clearLearningProfile = async (page: Page): Promise<void> => {
  await page.goto("/");
  await page.evaluate((key) => {
    window.localStorage.removeItem(key);
  }, LEARNING_PROFILE_STORAGE_KEY);
};

export const readLearningProfile = async (
  page: Page,
): Promise<string | null> =>
  page.evaluate(
    (key) => window.localStorage.getItem(key),
    LEARNING_PROFILE_STORAGE_KEY,
  );

export const openFirstLesson = async (
  page: Page,
  domain: string,
): Promise<void> => {
  await page
    .getByRole("button", { name: new RegExp(`^${domain}课程`, "u") })
    .click();
  await page.getByRole("button", { name: /^打开课程：/u }).first().click();
};

export const completeFirstLesson = async (
  page: Page,
  domain: string,
): Promise<void> => {
  await openFirstLesson(page, domain);
  await page.getByRole("button", { name: "载入标准结构示例" }).click();
  await page.getByRole("button", { name: "提交自检" }).click();
};
