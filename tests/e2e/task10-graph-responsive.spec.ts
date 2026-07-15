import { expect, test } from "./playwright-runtime";

test.use({ viewport: { width: 390, height: 844 } });

test("keeps the graph workspace within a 390px viewport", async ({ page }) => {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];

  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => {
    pageErrors.push(error.message);
  });

  await page.goto("/");
  await page.getByRole("tab", { name: "图谱" }).click();

  await expect(
    page.getByRole("searchbox", { name: "搜索图谱节点" }),
  ).toBeVisible();
  await expect(
    page.locator('[aria-label="通用掌握度未学习数量"]'),
  ).toHaveText("40");

  const widths = await page.evaluate(() => ({
    documentClientWidth: document.documentElement.clientWidth,
    documentScrollWidth: document.documentElement.scrollWidth,
    bodyClientWidth: document.body.clientWidth,
    bodyScrollWidth: document.body.scrollWidth,
  }));

  expect(widths.documentScrollWidth).toBeLessThanOrEqual(
    widths.documentClientWidth,
  );
  expect(widths.bodyScrollWidth).toBeLessThanOrEqual(widths.bodyClientWidth);
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});
