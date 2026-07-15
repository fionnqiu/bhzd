import { expect, test } from "./playwright-runtime";
import {
  clearLearningProfile,
  fixturePath,
  readLearningProfile,
} from "./helpers";

test("renders a complete report for a test-mode standard structured answer", async ({
  page,
}) => {
  await clearLearningProfile(page);
  await page.goto("/");
  const labelVocabularyCard = page
    .locator(".course-card")
    .filter({ hasText: "TU-TEXT-LABEL-VOCAB-001" });
  await labelVocabularyCard.getByRole("button", { name: /^打开课程：/u }).click();
  await page.getByRole("button", { name: "载入标准结构示例" }).click();
  const standardAnswer = await page.getByLabel("结构化答案").inputValue();

  await page.getByRole("tab", { name: "标注诊断" }).click();
  await page
    .getByLabel("上传标注导出文件")
    .setInputFiles({
      name: "valid-response.json",
      mimeType: "application/json",
      buffer: Buffer.from(standardAnswer, "utf8"),
    });

  await expect(page.getByRole("heading", { name: "诊断报告" })).toBeVisible();
  await expect(page.getByText("诊断状态：complete")).toBeVisible();
});

test("groups actionable issues from an invalid structured diagnostic export", async ({
  page,
}) => {
  await clearLearningProfile(page);
  await page.goto("/");
  await page.getByRole("button", { name: /^图像课程/u }).click();
  await page.getByRole("tab", { name: "标注诊断" }).click();
  await page
    .getByLabel("上传标注导出文件")
    .setInputFiles(fixturePath("coco-broken.json"));

  await expect(page.getByRole("heading", { name: "诊断报告" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: /严重问题|中等问题|轻微问题/u }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "按前置关系排序的补强计划" }),
  ).toBeVisible();
});

test("keeps a screenshot upload in explanation-only mode without scoring", async ({
  page,
}) => {
  await clearLearningProfile(page);
  await page.goto("/");
  await page.getByRole("tab", { name: "标注诊断" }).click();
  const profileBeforeUpload = await readLearningProfile(page);

  await page
    .getByLabel("上传标注导出文件")
    .setInputFiles(fixturePath("explanation.png"));

  await expect(page.getByText("辅助讲解模式", { exact: true })).toBeVisible();
  await expect(
    page.getByText(/截图仅用于本地讲解，不计分也不更新掌握度/u),
  ).toBeVisible();
  expect(await readLearningProfile(page)).toBe(profileBeforeUpload);
});
