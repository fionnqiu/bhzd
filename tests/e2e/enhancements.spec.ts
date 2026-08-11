/**
 * 增强特性端到端验收（2026-08-01 增强包：入学测评/通知/RAG 治理/批量操作）。
 *
 * 前置：后端 8787 演示库运行中；playwright 配置自动拉起前端 4173。
 * 限流注意（NF5 5 次/分/IP）：整套用例登录次数 ≤3（1 次 UI 登录 + 2 次 API 缓存登录）。
 * 选择器全部以页面真实 aria-label/文本为准（已对照页面源码）。
 */

import { injectSession } from "./auth-session";
import { expect, request, test } from "./playwright-runtime";
import { createPasswordEnvelope } from "./auth-envelope";

const FRONTEND_ORIGIN = "http://127.0.0.1:4173";
const STUDENT = { email: "student@demo.bhzd", password: "Demo1234!" };
const TEACHER = { email: "teacher@demo.bhzd", password: "Demo1234!" };

test("入学测评：新注册学生被引导完成测评并生成初始能力地图", async ({
  page,
}) => {
  // API 注册新学生。注册即时生效，不再依赖验证令牌或邮件投递。
  const email = `e2e-${Date.now() % 1000000}@demo.bhzd`;
  const ctx = await request.newContext({ baseURL: FRONTEND_ORIGIN });
  const reg = await ctx.post("/api/auth/register", {
    data: {
      email,
      name: "测评新生",
      passwordEnvelope: await createPasswordEnvelope(ctx, "Demo1234!"),
    },
  });
  expect(reg.status()).toBeLessThan(300);
  const regBody = await reg.json();
  expect(regBody.user.email_verified).toBe(true);
  await ctx.dispose();

  // UI 登录 → 未完成测评应被引导到 /onboarding
  await page.goto("/login");
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').fill("Demo1234!");
  await page.getByRole("button", { name: /登录|登 录/ }).click();
  await expect(page).toHaveURL(/\/onboarding/, { timeout: 15000 });

  // 第一步：方向与目标
  await page.getByRole("combobox", { name: "专业方向" }).click();
  await page
    .getByRole("option", { name: "人工智能技术应用", exact: true })
    .click();
  await page
    .locator('[aria-label="目标一句话"]')
    .fill("想做语音标注方向的岗位实训");
  await page.getByRole("button", { name: "下一步：入学测评" }).click();

  // 第二步：8 道测评题全部作答（每组选第一项）
  const groups = page.locator('[role="radiogroup"]');
  await expect(groups).toHaveCount(8, { timeout: 10000 });
  for (let i = 0; i < 8; i += 1) {
    await groups.nth(i).locator('input[type="radio"]').first().check();
  }
  await page.getByRole("button", { name: "提交测评" }).click();

  // 第三步：结果与初始能力地图 → 进入指挥舱
  await expect(page.getByText("初始能力地图")).toBeVisible({ timeout: 15000 });
  await expect(page.getByText(/本次得分/)).toBeVisible();
  await page.getByRole("button", { name: "进入指挥舱" }).click();
  await expect(page).toHaveURL(/127\.0\.0\.1:4173\/$/, { timeout: 15000 });
});

test("教师发布任务 → 学生通知铃铛收到并读", async ({ page, browser }) => {
  // 教师端：用预设模板快速组装并发布
  await injectSession(page, TEACHER);
  await page.goto("/teacher/tasks");
  await page.getByRole("button", { name: "新建教学任务" }).click();
  await page.getByRole("tab", { name: "从预设模板选择" }).click();
  await page.getByRole("button", { name: "使用模板" }).first().click();
  // 标题补一个时间戳便于在通知里辨认
  const title = `e2e 通知任务 ${Date.now() % 100000}`;
  const titleInput = page
    .locator(".field", { hasText: "任务名称" })
    .locator("input");
  await titleInput.fill(title);
  // 发布设置：选择班级并发布（按钮内部先保存草稿再 publish）
  await page.getByRole("combobox", { name: "选择班级" }).click();
  await page
    .getByRole("option", { name: "数据标注2301班", exact: true })
    .click();
  await page.getByRole("button", { name: "发布", exact: true }).click();
  await expect(page.getByText(/已发布给 \d+ 名学生/)).toBeVisible({
    timeout: 20000,
  });

  // 学生端：铃铛出现未读，通知内容可见，全部已读
  const studentPage = await browser.newPage();
  await injectSession(studentPage, STUDENT);
  await studentPage.goto("/");
  const bell = studentPage.locator('[aria-label^="通知"]').first();
  await expect(bell).toBeVisible({ timeout: 15000 });
  await bell.click();
  // 通知下拉项是可点按钮（无障碍名以"通知 "开头）；同名任务还会出现在左侧栏，须精确匹配避免 strict 冲突
  await expect(
    studentPage.getByRole("button", { name: new RegExp(`通知 ${title}`) }),
  ).toBeVisible({ timeout: 10000 });
  await studentPage.getByRole("button", { name: "全部已读" }).click();
  await studentPage.close();
});

test("RAG 上传→送审→发布→学生问答命中引用", async ({ page, browser }) => {
  await injectSession(page, TEACHER);
  await page.goto("/rag-admin/upload");
  const title = `e2e质检规范${Date.now() % 100000}`;
  const md = `# ${title} v1.0\n\n## 日合格率\n标注员每日合格率不得低于百分之九十六，低于该线必须当日复检。\n`;
  await page.locator('input[type="file"]').setInputFiles({
    name: "qa-rule.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(md, "utf-8"),
  });
  await page
    .locator(".field", { hasText: "资料标题" })
    .locator("input")
    .fill(title);
  await page.getByRole("combobox", { name: "资料类型" }).click();
  await page.getByRole("option", { name: "规范", exact: true }).click();
  await page
    .locator(".field", { hasText: "来源单位" })
    .locator("input")
    .fill("e2e 教研组");
  await page
    .locator(".field", { hasText: "版本号" })
    .locator("input")
    .fill("v1.0");
  // 适用数据类型：勾选 文本
  await page
    .locator(".field", { hasText: "适用数据类型" })
    .getByText("文本", { exact: true })
    .click();
  await page.getByRole("combobox", { name: "可见范围" }).click();
  await page.getByRole("option", { name: "学生可见", exact: true }).click();
  await page.getByRole("combobox", { name: "授权状态" }).click();
  await page.getByRole("option", { name: "已授权", exact: true }).click();
  await page.getByRole("button", { name: /确认上传/ }).click();
  await expect(page.getByText("上传成功", { exact: true })).toBeVisible({
    timeout: 40000,
  });

  // 详情页：送审 → 发布（学生范围）
  await page
    .getByRole("link", { name: /查看详情|资料详情/ })
    .first()
    .click();
  await page.getByRole("button", { name: "送审" }).click();
  await expect(page.getByText(/已送审/)).toBeVisible({ timeout: 15000 });
  await page.getByRole("button", { name: "发布…" }).click();
  await page.getByText("学生端可见（进入学生召回）").click();
  await page.getByRole("button", { name: "确认发布" }).click();
  await expect(page.getByText(/已发布，学生端可召回/)).toBeVisible({
    timeout: 15000,
  });

  // 学生端：提问命中该资料并展示引用
  const studentPage = await browser.newPage();
  await injectSession(studentPage, STUDENT);
  await studentPage.goto("/rag-qa");
  const box = studentPage.locator("textarea").first();
  await box.fill("标注员每日合格率不得低于多少？");
  await studentPage
    .getByRole("button", { name: /提问|发送|查询/ })
    .first()
    .click();
  await expect(studentPage.getByText(title).first()).toBeVisible({
    timeout: 25000,
  });
  await studentPage.close();
});

test("学习任务批量归档", async ({ page }) => {
  await injectSession(page, STUDENT);
  // API 造两个任务（CSRF 取自会话接口）
  const session = await page.request.get("/api/auth/session");
  const csrf = (await session.json()).csrf_token;
  for (let i = 0; i < 2; i += 1) {
    const r = await page.request.post("/api/tasks", {
      data: { title: `e2e 批量任务${i}-${Date.now() % 10000}`, cap_ids: [] },
      headers: { "x-csrf-token": csrf },
    });
    expect(r.status()).toBeLessThan(300);
  }
  await page.goto("/tasks");
  await page.locator('[aria-label="全选当前列表"]').check();
  await page.getByRole("button", { name: /批量归档/ }).click();
  await page.getByRole("button", { name: "确认批量归档", exact: true }).click();
  await expect(page.getByText(/已批量归档 \d+ 项任务/)).toBeVisible({
    timeout: 15000,
  });
});
