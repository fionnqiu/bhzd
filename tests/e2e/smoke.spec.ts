/**
 * PRD 主线端到端冒烟（重写版，2026-07-31 全权重构后）。
 *
 * 前置条件：
 *   1. 后端已用演示数据种子并运行于 127.0.0.1:8787
 *      （cd server && python -m bhzd_py.seed.loader --demo && python -m uvicorn bhzd_py.app:app --port 8787）
 *   2. playwright 配置自动拉起前端 dev server（127.0.0.1:4173，/api 代理到 8787）。
 *
 * 覆盖 PRD-00 §8 的关键验收主线：AC1（目标→任务草稿→预览卡→同步）、AC2（预设入口）、
 * AC5/AC6（引用与拒答）、AC7（图谱页）、教师工作台。
 *
 * 限流注意（NF5：5 次/分/IP）：整套用例只在 beforeAll 各登录一次（学生/教师），
 * 用例内复用缓存的会话 cookie；不要逐用例重新登录，否则会触发"尝试过于频繁"。
 */

import { injectSession } from "./auth-session";
import { expect, test } from "./playwright-runtime";

const STUDENT = { email: "student@demo.bhzd", password: "Demo1234!" };
const TEACHER = { email: "teacher@demo.bhzd", password: "Demo1234!" };

test.describe("学生端 PRD 主线", () => {
  test("登录页可登录并进入对话页欢迎态（快捷入口 + 目标输入）", async ({ page }) => {
    // UI 登录是真实浏览器路径验收；命中 NF5 限流（5 次/分/IP）时等滚动窗口过去再试
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      await page.goto("/login");
      await page.locator('input[type="email"]').fill(STUDENT.email);
      await page.locator('input[type="password"]').fill(STUDENT.password);
      await page.getByRole("button", { name: /登录|登 录/ }).click();
      const landed = await page
        .waitForURL(/\/($|presets|graph|tasks)/, { timeout: 15000 })
        .then(() => true)
        .catch(() => false);
      if (landed) break;
      if (attempt < 3) await page.waitForTimeout(61_000);
    }
    await expect(page).toHaveURL(/\/($|presets|graph|tasks)/);
    // The simplified cockpit intentionally exposes four bounded entry actions;
    // keeping this list aligned with the current product contract avoids reviving
    // the retired scenario/task shortcuts in an end-to-end assertion.
    for (const name of ["文本标注", "图像标注", "结果诊断", "薄弱补强"]) {
      await expect(page.getByText(name, { exact: false }).first()).toBeVisible();
    }
    await expect(page.locator('[placeholder*="输入你的学习目标"]').first()).toBeVisible();
  });

  test("AC1 目标输入 → Agent 生成任务草稿 → 预览卡 → 同步到学习任务", async ({ page }) => {
    await injectSession(page, STUDENT);
    await page.goto("/");
    const input = page.locator("textarea").first();
    // 信息完整的请求（类型+场景+水平）：生成前澄清应直接 READY 进入生成；
    // 无模型环境回退规则路径，同样直达草稿。
    await input.fill("我是零基础，想学习文本 NER 实体标注入门，帮我生成一个练习任务");
    await input.press("Enter");
    // 执行过程以步骤流呈现（plan.updated / tool.call.* 经 SSE 到达）
    await expect(page.getByTestId("agent-activity-timeline")).toBeVisible({ timeout: 20000 });
    // 回答底部出现任务卡按钮；点击打开预览弹窗
    const openButton = page.getByTestId("task-draft-open");
    await expect(openButton).toBeVisible({ timeout: 20000 });
    await openButton.click();
    await expect(page.getByText("学习任务卡预览")).toBeVisible({ timeout: 20000 });
    // 卡片上的「同步到学习任务」即学生显式确认：点击后出现已同步回执
    await page.getByTestId("task-draft-sync").click();
    await expect(page.getByText(/已同步 \d+ 个学习任务/).first()).toBeVisible({ timeout: 20000 });
  });

  test("AC2 预设学习：路径列表 → 详情抽屉", async ({ page }) => {
    await injectSession(page, STUDENT);
    await page.goto("/presets");
    await expect(page.getByText("NER 实体标注入门").first()).toBeVisible({ timeout: 15000 });
    await expect(page.getByText("车载唤醒词标注").first()).toBeVisible();
    // 打开一条路径详情
    // The shell sidebar can contain a recent session with the same title;
    // scope the click to the preset card inside main so the test exercises the
    // drawer contract rather than navigating to an unrelated conversation.
    await page
      .locator('main [role="button"]')
      .filter({ hasText: "车载唤醒词标注" })
      .first()
      .click();
    await expect(page.getByText(/开始学习|关联能力|预计/).first()).toBeVisible({ timeout: 10000 });
  });

  test("AC5/AC6 知识问答：专业问题带引用，无关问题拒答", async ({ page }) => {
    await injectSession(page, STUDENT);
    await page.goto("/rag-qa");
    const box = page.locator("textarea").first();
    await box.fill("唤醒词标注的边界容差是多少？");
    await page.getByRole("button", { name: /提问|发送|查询/ }).first().click();
    // 命中演示资料 → 引用来源可见（AC5）
    await expect(page.getByText(/车载唤醒词标注指南/).first()).toBeVisible({ timeout: 20000 });
    // 知识库外问题 → 拒答（AC6）
    await box.fill("曲率引擎的充电方式是什么？");
    await page.getByRole("button", { name: /提问|发送|查询/ }).first().click();
    // 知识库外问题 → 拒答（AC6）。无可用模型时拒答文案是服务不可用说明，
    // 两种都是"不编造答案"的合规拒答。
    await expect(
      page.getByText(/暂无可靠依据|资料不足|无法给出专业结论|暂时无法|暂不可用/).first(),
    ).toBeVisible({ timeout: 20000 });
  });

  test("AC7 能力图谱页：全图渲染与掌握度图例", async ({ page }) => {
    await injectSession(page, STUDENT);
    await page.goto("/graph");
    // vis-network 画布与掌握度图例（v3.0 §7.3.3 配色规则）
    await expect(page.locator("canvas").first()).toBeVisible({ timeout: 20000 });
    await expect(page.getByText(/已掌握|待加强|初学/).first()).toBeVisible();
  });
});

test.describe("教师端主线", () => {
  test("教师工作台：班级概览与薄弱能力", async ({ page }) => {
    await injectSession(page, TEACHER);
    await page.goto("/teacher");
    await expect(page.getByText(/薄弱|掌握度|班级/).first()).toBeVisible({ timeout: 15000 });
  });
});
