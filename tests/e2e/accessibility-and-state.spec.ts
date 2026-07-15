import { expect, test } from "./playwright-runtime";
import {
  clearLearningProfile,
  completeFirstLesson,
  readLearningProfile,
} from "./helpers";

test("persists a completed lesson across reload and clears it after reset", async ({
  page,
}) => {
  await clearLearningProfile(page);
  await page.goto("/");
  await completeFirstLesson(page, "文本");
  expect(await readLearningProfile(page)).not.toBeNull();

  await page.reload();
  await expect(page.getByRole("heading", { name: "结构化练习" })).toBeVisible();

  await page.getByRole("button", { name: "重置学习档案" }).click();
  await page.getByRole("button", { name: "确认重置" }).click();
  await expect(page.getByText("学习档案已重置，航线已返回文本课程。")).toBeVisible();
  await expect(page.getByRole("heading", { name: "文本课程航线" })).toBeVisible();
  expect(await readLearningProfile(page)).toBeNull();
});

test("keeps keyboard focus inside the reset dialog and restores it on escape", async ({
  page,
}) => {
  await clearLearningProfile(page);
  await page.goto("/");

  const resetButton = page.getByRole("button", { name: "重置学习档案" });
  await resetButton.click();
  await expect(page.getByRole("button", { name: "取消" })).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(resetButton).toBeFocused();
});

test("honors reduced-motion preferences while keeping graph navigation usable", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await clearLearningProfile(page);
  await page.goto("/");

  const duration = await page.locator(".course-card").first().evaluate((card) =>
    Number.parseFloat(window.getComputedStyle(card).animationDuration),
  );
  expect(duration).toBeLessThanOrEqual(0.01);

  await page.getByRole("tab", { name: "图谱" }).click();
  const search = page.getByRole("searchbox", { name: "搜索图谱节点" });
  await search.fill("CAP-TXT-ENTITY-BOUNDARY-001");
  await search.press("Enter");
  await expect(
    page.getByRole("heading", { name: "确定实体边界" }),
  ).toBeVisible();
});
