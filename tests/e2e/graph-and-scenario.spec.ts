import { expect, test } from "./playwright-runtime";
import { clearLearningProfile } from "./helpers";

test("navigates from graph search into a two-hop local view and back", async ({
  page,
}) => {
  await clearLearningProfile(page);
  await page.goto("/");
  await page.getByRole("tab", { name: "图谱" }).click();

  const search = page.getByRole("searchbox", { name: "搜索图谱节点" });
  await search.fill("CAP-TXT-ENTITY-BOUNDARY-001");
  await search.press("Enter");

  await expect(
    page.getByRole("heading", { name: "确定实体边界" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "返回总览" })).toBeVisible();

  await page.getByRole("button", { name: "返回总览" }).click();
  await expect(page.getByText(/总览：166 个节点/u)).toBeVisible();
});

test("compares two published text scenarios without changing the data domain", async ({
  page,
}) => {
  await clearLearningProfile(page);
  await page.goto("/");
  await page.getByRole("tab", { name: "任务转化" }).click();

  const medicalScenario = page.getByRole("button", {
    name: "医疗数据标注",
    exact: true,
  });
  await medicalScenario.click();
  await expect(medicalScenario).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("当前位置")).toContainText("SCN-MEDICAL-001");
  await expect(
    page.getByRole("button", { name: /^文本课程/u }),
  ).toHaveAttribute("aria-pressed", "true");

  const customerServiceScenario = page.getByRole("button", {
    name: "智能客服标注",
    exact: true,
  });
  await customerServiceScenario.click();
  await expect(customerServiceScenario).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("当前位置")).toContainText(
    "SCN-CUSTOMER-SERVICE-001",
  );
  await expect(
    page.getByRole("button", { name: /^文本课程/u }),
  ).toHaveAttribute("aria-pressed", "true");
});
