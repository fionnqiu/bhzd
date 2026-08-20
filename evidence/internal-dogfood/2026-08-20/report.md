# BHZD 本地合成内测报告

## 执行摘要

- **环境**：本地 Vite `127.0.0.1:5173` + FastAPI `127.0.0.1:8787`，运行库为 `var\bhzd.sqlite`。
- **账号**：锁定命名空间 `dogfood-20260820-f421d417-*`，共 2 个教师（t01/t02）和 10 个学生（s01-s10）。演示账号、历史账号和真实账号未纳入重置。
- **凭据操作**：最终一轮为 12 个账号生成新 Argon2id 凭据，吊销旧会话；12/12 通过真实本地 HTTP 登录与退出验证。明文密码、哈希、会话令牌和诊断 token 均未写入报告或日志。
- **数据保留**：目标用户记录保留 12 行，验证结束后目标账号没有活动会话；诊断上传、确认保存、掌握度事件和审计记录保留在数据库中。
- **浏览器控制台**：本轮诊断上传、保存和个人中心导航未发现 error/warn。

## 已验证流程

1. 学生登录后从 Agent 欢迎态进入“结果诊断”。
2. 上传本地合成 COCO JSON，系统识别为 `coco_json`，报告发现 2 个严重错误：越界框和未声明类别。
3. 保存前显示掌握度预览（两个能力均为 `0% → 0%`），确认后摘要写入数据库并清空一次性报告。
4. 个人中心出现新的诊断摘要和成长记录，证明上传、确认、摘要和掌握度事件形成持久化闭环。
5. `/diagnostics` 旧入口正确重定向到 Agent 首页；`/student/diagnostics` 并非当前路由，直接访问会落到 404 页面，属于不应继续使用的猜测路径。

## 缺陷与优化建议

### DF-01：AI 评阅失败后学生无法完成成绩闭环

- **严重度**：High
- **类别**：Functional / Learning outcome
- **证据**：[11-student-ai-grading-unavailable.png](E:\AgentWorkspaces\bhzd\evidence\internal-dogfood\2026-08-20\screenshots\11-student-ai-grading-unavailable.png)
- **现象**：S06 的练习提交记录为 `grade_status=failed`，`score`、`feedback`、`graded_at` 均为空；页面显示“AI 评阅暂不可用，请稍后重试”。
- **影响**：学生已经提交答案，但任务不能进入可解释的完成/得分状态，教师也无法据此反馈学习结果。
- **建议**：提供明确的重试入口和重试状态；保留原始提交；超过重试上限时转为人工/规则评阅或明确标记“待处理”，禁止静默停留在失败态。

### DF-02：部分教师任务没有练习题，提交链路不可达

- **严重度**：High
- **类别**：Functional / UX
- **证据**：[15-no-exercise-task-cannot-submit.png](E:\AgentWorkspaces\bhzd\evidence\internal-dogfood\2026-08-20\screenshots\15-no-exercise-task-cannot-submit.png)
- **现象**：S02、S04 对应的教师任务数据库记录练习数为 0；学生可打开任务，但没有可提交内容。
- **影响**：教师看到任务已发布，学生却无法完成任务，发布成功与学习可执行性之间断开。
- **建议**：发布前强制校验至少一个可执行练习；若生成失败，显示生成失败原因和重试动作，不允许把空任务当作正常发布成功。

### DF-03：通知可能指向已归档任务

- **严重度**：Medium
- **类别**：UX / Content
- **证据**：先前内测浏览器记录显示未读通知跳转后页面为“已归档”。
- **影响**：学生从通知进入后无法完成任务，容易误以为系统丢失或链接失效。
- **建议**：归档任务的通知应转为只读历史页并明确说明；或在归档时同步撤回未读行动型通知。

### DF-04：多账号本地走查容易触发全局 IP 限流

- **严重度**：Medium
- **类别**：UX / Testability
- **现象**：连续验证多个本地账号时触发 `429 RATE_LIMITED`。等待窗口后登录正常，未发现凭据错误。
- **影响**：内测人员容易把安全限流误判为账号重置失败；批量验证耗时较长。
- **建议**：在本地内测模式提供受控的批量验证工具或按账号/IP 维度显示剩余等待时间；生产环境仍保留严格限流。

### DF-05：教师任务生成失败需要更明确的可恢复状态

- **严重度**：Medium
- **类别**：Functional / UX
- **证据**：[17-teacher-ai-template-draft.png](E:\AgentWorkspaces\bhzd\evidence\internal-dogfood\2026-08-20\screenshots\17-teacher-ai-template-draft.png)
- **现象**：教师 AI 模板可以停留在草稿/生成中间态；与空练习任务组合时，教师不容易判断下一步是等待、重试还是手工补题。
- **建议**：统一显示生成状态、失败原因、重试次数和“发布前检查”结果；发布按钮应对不可执行内容禁用并说明原因。

## 证据索引

- 诊断输入：[diagnostic-sample.json](E:\AgentWorkspaces\bhzd\evidence\internal-dogfood\2026-08-20\diagnostic-sample.json)
- 诊断报告截图：`MEDIA:E:\AgentWorkspaces\bhzd\evidence\internal-dogfood\2026-08-20\screenshots\18-result-diagnostic-report-saved.png`
- 个人中心持久化截图：`MEDIA:E:\AgentWorkspaces\bhzd\evidence\internal-dogfood\2026-08-20\screenshots\19-profile-diagnostic-history.png`
- 教师/学生内测截图：`evidence/internal-dogfood/2026-08-20/screenshots/01` 至 `17`
- 最终 SQLite 在线备份：`var\backups\bhzd.sqlite.before-internal-dogfood-password-reset-verified-20260820-133420.sqlite`

## 证据边界与未覆盖项

- 本轮证明的是本地服务、确定性诊断和本地账号登录；不证明真实 Provider、生产邮件、外部浏览器或正式教学效果。
- AI 评阅失败、空练习任务和通知归档联动仍需要产品决定与修复后的回归验证。
- 未删除任何内测账号、任务、提交、成绩或诊断数据。
