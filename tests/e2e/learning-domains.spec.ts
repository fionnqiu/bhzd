import { expect, test } from "./playwright-runtime";
import { clearLearningProfile, completeFirstLesson } from "./helpers";

for (const domain of ["文本", "图像", "语音", "视频"]) {
  test(`${domain} completes a representative learning loop`, async ({ page }) => {
    await clearLearningProfile(page);
    await page.goto("/");

    await completeFirstLesson(page, domain);

    await expect(
      page.getByRole("status", { name: "自检反馈" }),
    ).toContainText("通过");
    await expect(
      page.getByRole("heading", { name: "掌握度", exact: true }),
    ).toBeVisible();
  });
}
