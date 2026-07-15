import { expect, test } from "./playwright-runtime";
import { clearLearningProfile } from "./helpers";

test("requests a clarification instead of guessing an ambiguous enterprise task", async ({
  page,
}) => {
  await clearLearningProfile(page);
  await page.goto("/");
  await page.getByRole("tab", { name: "任务转化" }).click();
  await page.getByLabel("企业任务描述").fill("请帮我完成一项标注工作");
  await page.getByRole("button", { name: "生成学习任务卡" }).click();

  await expect(
    page.getByRole("heading", { name: "需要补充信息" }),
  ).toBeVisible();
  await expect(page.getByRole("status")).toContainText("数据类型");
});
