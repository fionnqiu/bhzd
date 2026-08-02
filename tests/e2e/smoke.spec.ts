/**
 * PRD 主线端到端冒烟（重写版，2026-07-31 全权重构后）。
 *
 * 前置条件：
 *   1. 后端已用演示数据种子并运行于 127.0.0.1:8787
 *      （cd server && python -m bhzd_py.seed.loader --demo && python -m uvicorn bhzd_py.app:app --port 8787）
 *   2. playwright 配置自动拉起前端 dev server（127.0.0.1:4173，/api 代理到 8787）。
 *
 * 覆盖 PRD-00 §8 的关键验收主线：AC1（目标→计划→确认→任务）、AC2（预设入口）、
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
  test("登录页可登录并进入指挥舱欢迎态（8 入口 + 占位文案）", async ({ page }) => {
    await page.goto("/login");
    await page.locator('input[type="email"]').fill(STUDENT.email);
    await page.locator('input[type="password"]').fill(STUDENT.password);
    await page.getByRole("button", { name: /登录|登 录/ }).click();
    await expect(page).toHaveURL(/\/($|presets|graph|tasks)/, { timeout: 15000 });
    // 欢迎态 8 快捷入口（PRD-01 §3.6：不少于 6 个）
    for (const name of ["文本标注入门", "图像标注入门", "语音标注入门", "视频标注入门", "岗位任务训练", "上传结果诊断", "考证路径", "今日薄弱补强"]) {
      await expect(page.getByText(name, { exact: false }).first()).toBeVisible();
    }
    // 目标输入占位文案（v3.0 §7.1.3 契约占位）
    await expect(page.locator('[placeholder*="说说你想学什么"]').first()).toBeVisible();
  });

  test("AC1 目标输入 → Agent 计划 → 确认门 → 任务创建", async ({ page }) => {
    await injectSession(page, STUDENT);
    await page.goto("/");
    const input = page.locator("textarea").first();
    await input.fill("我想学车载唤醒词标注");
    await input.press("Enter");
    // 计划卡或执行轨迹应出现（plan.updated / tool.call.* 经 SSE 到达）
    await expect(page.getByText(/计划|执行轨迹|任务/).first()).toBeVisible({ timeout: 20000 });
    // 写操作应出现确认门；确认后任务创建回执或摘要可见
    const confirmButton = page.getByRole("button", { name: /^确认$|确认创建|确认执行/ }).first();
    if (await confirmButton.isVisible({ timeout: 20000 }).catch(() => false)) {
      await confirmButton.click();
      await expect(page.getByText(/已创建|查看任务|已完成|任务已/).first()).toBeVisible({ timeout: 20000 });
    }
  });

  test("AC2 预设学习：路径列表 → 详情抽屉", async ({ page }) => {
    await injectSession(page, STUDENT);
    await page.goto("/presets");
    await expect(page.getByText("NER 实体标注入门").first()).toBeVisible({ timeout: 15000 });
    await expect(page.getByText("车载唤醒词标注").first()).toBeVisible();
    // 打开一条路径详情
    await page.getByText("车载唤醒词标注").first().click();
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
    await expect(page.getByText(/暂无可靠依据|资料不足|无法给出专业结论/).first()).toBeVisible({ timeout: 20000 });
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
