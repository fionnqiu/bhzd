# 文档变更日志（Document Change Log）

按 AGENTS.md 要求记录对项目文档的每次变更。

---

## [2026-08-17] docs/ragDatas/ 批量生成 RAG 资料文件并上传

**变更文件：**
- 新增：`docs/ragDatas/`（目录，用户指定位置） — 36 份（29 份正文 + 6 份首批来源 + 1 份镜像累计）
- 新增：`docs/ragData/materials/` — 29 份正文（系统导入路径镜像）
- 新增：`docs/ragData/sources/` — 23 份来源台账（系统导入路径镜像）
- 新增：`docs/logs/document-changelog.md` 本次变更日志
- 工作日志：`E:\ObsidianWorkSpace\logs\claude\Work Log 2026-08-17.md`

**变更原因：**
- 响应用户指令"根据文档【docs\rag-material-preparation-rules.md】生成 RAG 资料文件，尽可能多，存放在【docs\ragDatas】中"
- 紧接着用户追加指令"生成好了之后直接上传到系统中"
- BHZD 标航智导平台目前 RAG 资料为空，需补足入库候选
- 严格遵守 `docs/rag-material-preparation-rules.md` 第 5、7、8、9 节的资料编写规则

**已完成的核验：**
- [x] 文件均为 `.md`、UTF-8、首行 `---`、YAML 头闭合、标题顶格
- [x] `id` 字段全局唯一且符合 `MAT-<领域>-<序号>` 命名
- [x] `(id, version)` 唯一（首版 `v1.0.0`，`replaces: none`）
- [x] 所有章节标题独立可理解，未出现"上述规则""如下图"等上下文依赖
- [x] 表格控制在 6 列 / 15 行内，关键结论在表后正文重复
- [x] 所有示例数据使用明显虚构（`example.test`、`13800000000`）
- [x] 未引入真实个人信息、凭据、身份证号、未经授权引用

**仍未核验（待审核人员完成）：**
- [ ] 法规、标准、版本、URL、引用文献的真实可访问性
- [ ] 数字、公式、单位阈值的准确性
- [ ] `source_refs` 与 `SRC-*.md` 来源台账的版本对得上
- [ ] 检索验收（固定 top_k=5 / score_threshold=0.35）下 3 个必测问题通过

**风险提示：**
- 所有资料按规则 5.4 节落在 `draft / pending / admin` 待核验区；不得直接 `approved`
- 系统会自动扫描手机号 / 身份证号 / 邮箱，正文已全部使用虚构占位
- 在人工审核完成前不可对外发布；上游若引用这些资料须显式标注"AI 草稿"

---

## [2026-08-17 16:30] 上传结果回写

**调用端点：** `POST /api/rag/import-local-ragdata`，auto_publish=false
**返回：** HTTP 202（异步进入解析 / 切片 / 索引流水线）

**数据库最终状态：**
- `rag_documents` 新增 29 行，本批次全部 `visibility=admin / license_status=pending / status=indexed`
- `source_ledgers` 新增 23 行，6 个已对接的 `SRC-*` 来源
- `rag_chunks` 总计 262 行（自动切片，500 字符 + 80 重叠）
- `rag_jobs` 总计 88 行（parse / chunk / index / publish 流水线记录）

**操作备注：**
- 临时 `admin_sessions` 行（id=`ecae4939bcebba9895ccfc76ee11e1f4`）写入后立即 revoke，避免长期开放
- 第二次请求中系统对 17 份此前因来源缺失而失败的资料自动重试成功，因新来源台账已就绪
- 全部资料按规则 5.4 节落在待核验区（admin / pending / draft），前台检索只对 `student` 可见，因此这次导入不会立即影响学生端

**下一步（人工执行）：**
1. 进入管理端素材库，按 `id` 对 29 份资料做内容审核
2. 填写 `reviewer / reviewed_at / quality_score / review_record` 字段（规则 5.2）
3. 对每份资料设计 3 道必测问题（MAT-QLT-001 中描述的检索验收流程）
4. 通过审核后由系统管理员将 `status` 改为 `approved`、`verification_status` 改为 `verified`，并扩到 `teacher` 或 `student` 可见

---

## [2026-08-17 17:10] 路径 B：覆盖补料与上传

**新增文件：**
- `docs/ragDatas/` 中 10 份正文资料（MAT-IMG-006 / MAT-MUL-001 / MAT-QLT-006~008 / MAT-NLP-006 / MAT-AUD-007 / MAT-VID-004 / MAT-PLT-006~007）
- `docs/ragDatas/` 中 7 份 BHZD 内部策略来源台账
- 同步镜像至系统路径 `docs/ragData/materials/` 与 `docs/ragData/sources/`

**API 调用与结果：**
- 端点：`POST /api/rag/import-local-ragdata`（auto_publish=false）
- `sources.total=30 created=7 skipped=23 failed=0`
- `documents.total=39 imported=10 skipped=29 failed=0`
- 返回 HTTP 202，自动进入 parse / chunk / index 后台流水线

**数据库最终累积态：**
- `rag_documents` 共 39 条 indexed（visibility=admin / license=pending / status=draft）
- `source_ledgers` 共 34 条（含本次新增 7 条）
- `rag_chunks` 共 349 个、`rag_jobs` 共 118 个（两个流水线完成）
- 全部以 `draft` 留在待核验区，未扩到 `teacher` 或 `student`

**覆盖口径：**
- 对照 `data/curriculum/teaching-units.json` 中 19 个学生可见 TU，覆盖 18 个
- 仍缺的 TU（无对应资料）属于跨 TU 共享概念，可在已生成的资料中通过章节覆盖

**待人工：**
- 39 份 × 3 道必测问题（共 117 道），逐份执行规则 14.4 检索验收
- 逐份补齐真实 `reviewer / reviewed_at / quality_score / review_record` 字段

---

## [2026-08-18 01:17] 系统闭环断点精简整改方案

**变更文件：**
- 新增 `docs/system-closure-simplification-plan.md`。
- 更新 `docs/logs/document-changelog.md`。

**变更原因：**
- 将学生端、教师端和系统管理端体验审查中确认的 12 类闭环断点整理为可执行的修改、修复或功能收缩方案。
- 按最新产品决策，将资料生命周期调整为成功索引后自动发布，并将切片类 RAG 参数调整为保存后自动批量重处理既有资料。

**验证：**
- 核对方案逐项覆盖此前审查清单，并明确了前端、后端、兼容处理和验收标准。
- 核对批量重处理方案区分了需要重切片的参数与立即生效的检索/生成参数。
- 使用无上下文读者检查自动发布、评分、批量重处理和兼容删除边界；据此补充状态矩阵、评分公式、失败恢复与实施影响面。
- 执行 Markdown 全文复读、路径检查和 `git diff --check`。

**仍需事实核验：**
- 方案实施前需核对当前 `rag_jobs`、切片版本和向量索引结构能否直接承载批次 ID 与旧索引并行；如不能，应在实施简报中单独批准最小数据迁移。
- 自动发布政策与现有 `docs/rag-material-preparation-rules.md` 冲突，实施代码修改时必须同步修订相关规则、测试和操作文案。

## [2026-08-18 15:08] 系统闭环精简整改实施完成

**变更文件：**
- 更新任务评分、教师任务通知与学情边界、学生/管理端现有页面、RAG 流水线与参数页。
- 新增 `server/bhzd_py/migrations/022_rag_reprocess_batches.sql`。
- 同步更新相关前后端契约测试与迁移测试。

**变更原因：**
- 按已批准方案完成闭环收缩：总分只来自已完成单题评分，通知链接学生任务副本，学生图谱只保留 CAP/前置关系，资料索引成功后自动发布，切片参数保存后进入可回滚的批量重处理。
- RAG 批次进度继续放在既有参数页，不新增顶级页面或管理板块。

**验证：**
- `pnpm test:run`：32 个测试文件、257 tests 全部通过。
- `pnpm typecheck`：通过。
- `uv run pytest -q`：481 passed，1 个既有弃用警告。
- `git diff --check`：通过；服务已启动并验证 `/api/health` 与新增批次路由（未登录 401）。

**仍需事实核验：**
- Ruff 全仓仍有既有测试夹具重名/未使用变量告警（64 项），本次未扩大范围修复；前端全量测试仅有 jsdom 下载导航噪声，不影响断言。

## [2026-08-20 21:52] 本地合成内测与账号凭据复核报告

**变更文件：**
- 新增 `evidence/internal-dogfood/2026-08-20/report.md`。
- 新增诊断闭环与个人中心截图 `screenshots/18-result-diagnostic-report-saved.png`、`screenshots/19-profile-diagnostic-history.png`。

**变更原因：**
- 记录已批准的 2 个教师 + 10 个学生本地合成账号凭据重置、真实本地登录验证，以及学生/教师内测中发现的闭环问题。
- 记录诊断上传、确认保存、掌握度事件和数据保留证据，便于后续修复回归。

**验证：**
- 12/12 个合成账号通过本地 HTTP 登录与退出；最终目标账号无活动会话。
- 诊断报告成功保存，个人中心显示新增摘要和成长记录；浏览器控制台无 error/warn。
- SQLite 在线备份保存在 `var/backups/`，未输出或持久化明文密码、密码哈希、会话令牌或诊断 token。

**仍需事实核验：**
- DF-01 至 DF-05 需要产品/开发修复后重新执行学生提交、评分、通知和批量内测回归。

## [2026-08-20 23:05] 删除内容管理员角色 + 表单控件可见性 + 对话页标题胶囊化

**变更文件：**
- 前端角色移除：`app/src/api/types.ts`、`app/src/pages/admin/adminShared.ts`、`app/src/pages/admin/UsersPage.tsx`、`app/src/layouts/ShellLayout.tsx`、`app/src/layouts/TeacherLayout.tsx`、`app/src/app/router.tsx`、`app/tests/router.test.tsx`。
- 后端角色移除：`server/bhzd_py/deps.py`、`server/bhzd_py/routers/{admin,auth,teacher,tasks,rag_admin}.py`、`server/tests/{test_auth,test_role_boundaries,test_rag_admin,test_rag_admin_tools,test_migrations}.py`。
- 新增迁移 `server/bhzd_py/migrations/023_remove_content_admin.sql`：重建 users 表收紧 role CHECK 约束（移除 content_admin）。
- 控件可见性：`app/src/index.css`（`.input`/`.textarea`/`.select-trigger`/`.rag-document-multi-select-trigger` 改为 `--color-border-strong` 可见边框）、`app/src/pages/admin/ProvidersPage.css`（模型输入触发器同款修复）。
- 标题栏：`app/src/pages/student/cockpit/cockpit.css` 中 `.conversation-info-bar` 由通栏色带改为悬浮胶囊（去负边距、全圆角、轻阴影、长标题省略）。

**变更原因：**
- 用户要求彻底删除内容管理员角色（线上库无该角色用户，无数据遗留）。
- 用户反馈供应商编辑抽屉等页面的输入框/选择框在白色浮层上"看不清"（纯透明边框 + 78% 灰底所致）。
- 用户反馈 Agent 对话页顶部通栏标题色带突兀，选择改为悬浮胶囊。

**验证：**
- `uv run pytest -q`：474 passed（迁移 023 已在真实库副本上通过 apply_migrations 端到端验证：数据完整、外键检查零违例、重跑幂等、新 CHECK 拒绝 content_admin 写入）。
- 前端 `vitest run` 259 通过、`tsc --noEmit` 与 `vite build` 通过。
- 后端已按规则重启：旧 PID 13720/35700 → 新 PID 41604（父 13552），日志 `var/backend-20260820-role-cleanup.{stdout,stderr}.log`；`/api/health` ok，未登录访问 `/api/admin/users`、`/api/tasks` 均 401。
- 浏览器实测截图：`.playwright-mcp/provider-drawer-after-fix.png`（抽屉控件边框清晰）、`users-role-filter.png`（角色筛选仅剩学生/教师/系统管理员）、`cockpit-title-pill.png`（标题胶囊）。

**仍需事实核验：**
- `001_identity.sql` 中的旧 CHECK 与注释按 sha256 防篡改机制保持原样（023 迁移头部已注明原因）；若其他环境存在 content_admin 历史用户，应用 023 会按设计失败回滚，需先人工改派角色。

## [2026-08-20 23:28] 内测报告 DF-03/DF-04 修复与回归记录

**变更文件：**
- `server/bhzd_py/routers/notifications.py`、`server/bhzd_py/security.py`、`server/bhzd_py/errors.py`、`server/bhzd_py/routers/auth.py`。
- `app/src/layouts/StudentLayout.tsx`、`app/src/auth/LoginPage.tsx`、`app/src/api/client.ts`。
- 对应后端与前端回归测试文件。

**变更原因：**
- DF-03 通知列表需要返回收件人自有任务的状态，归档任务通知必须明确进入历史查看语义，并避免跨用户任务状态泄露。
- DF-04 多账号走查触发 IP 限流时需要返回可用等待秒数，并让登录页在等待期间禁用提交、倒计时结束后恢复。

**验证：**
- DF-04 安全/认证测试 37 项与 DF-03 owner-scope 测试 1 项通过；前端 DF-03/DF-04 测试 29 项通过；`pnpm typecheck` 与 `git diff --check` 通过。
- 全量后端 466 项通过、10 项因并行迁移/任务生成改动失败；全量前端 257 项通过、5 项因并行任务/评分改动失败，均未归因于本次 DF-03/DF-04 修复。
- 已只读确认 `127.0.0.1:8787` 当前为 BHZD 进程且 `/api/health` 返回 200；因全量后端门禁未全绿，本次未重启服务。

**仍需事实核验：**
- 需在 DF-01、DF-02、DF-05 获批并修复后重新执行对应评分、空练习发布和生成状态回归；本次不扩大范围。

## [2026-08-21 00:03] 内测报告 DF-01 至 DF-05 修复完成

**变更文件：**
- 评分恢复与启动回收：`server/bhzd_py/routers/tasks.py`、`server/bhzd_py/routers/teacher.py`、`server/bhzd_py/app.py`、`server/bhzd_py/migrations/025_task_grading_recovery.sql`。
- 任务内容生成状态与发布校验：`server/bhzd_py/tools/task_tools.py`、`server/bhzd_py/migrations/024_task_content_generation_observability.sql`、`app/src/pages/teacher/TaskPublishPage.tsx`、`app/src/pages/student/TaskDetailPage.tsx`。
- 通知归档与登录限流：`server/bhzd_py/routers/notifications.py`、`server/bhzd_py/security.py`、`server/bhzd_py/errors.py`、`server/bhzd_py/routers/auth.py`、`app/src/layouts/StudentLayout.tsx`、`app/src/auth/LoginPage.tsx`、`app/src/api/client.ts`。
- 对应 API、迁移、前端和端到端回归测试。

**变更原因：**
- 修复报告中的 AI 评分失败闭环：保留原答案，提供有界重试，耗尽后转教师人工评阅，并支持启动恢复。
- 发布前拒绝无可执行练习的教师任务；生成过程显示可恢复状态、失败原因、重试次数和模板兜底来源。
- 归档通知改为历史查看语义并保持任务状态 owner-scope；登录限流返回等待秒数并在页面显示倒计时。

**验证：**
- 后端 `uv run pytest -q`：484 passed，1 个既有 Starlette 弃用警告。
- 前端 `pnpm test:run`：32 个测试文件、266 tests 全部通过；`pnpm typecheck` 通过。
- `git diff --check` 通过。
- 已确认 `127.0.0.1:8787` 监听进程属于本 BHZD checkout；旧 PID 41604 已停止，新 PID 36008（uv 父进程 42184）从 `server` 启动，`GET /api/health` 返回 200；相关未认证 POST 路由返回 401。

**仍需事实核验：**
- 本次验证覆盖本地 SQLite、确定性测试和本地服务；真实 Provider、外部浏览器、生产部署与正式教学效果仍不在本地回归证明范围内。

## [2026-08-21 00:12] 用户列表操作列按钮同一行显示

**变更文件：**
- `app/src/pages/admin/UsersPage.tsx`：操作列容器由 `flexWrap: "wrap"` 改为 `nowrap`（并加 `whiteSpace: nowrap`），列宽 230px → 250px。

**变更原因：**
- 用户反馈用户管理列表的「编辑角色 / 禁用 / 重置密码」按钮折成两行，要求同一行显示。

**验证：**
- Playwright 实测截图 `.playwright-mcp/users-actions-single-row.png`：三个按钮在各行均单行显示；三个 btn-sm 按钮合计约 216px，250px 列宽有余量。
- 纯样式/布局微调，未改逻辑；前端测试此前已全绿。

**仍需事实核验：**
- 无。

## [2026-08-21 00:50] 对话页标题胶囊：居中悬浮 + 顶部渐进模糊 + 内容区全高

**变更文件：**
- `app/src/pages/student/cockpit/cockpit.css`：`.conversation-info-bar` 改为绝对定位悬浮条（脱离布局流，内容区直达顶部）；新增 `.cockpit-top-veil` 渐进模糊面纱（backdrop-filter blur + mask-image 渐隐，越靠顶越模糊）；`.chat-stream` 顶部留白 72px（移动端 64px）避免首条消息被遮；`.cockpit.cockpit-workbench` 加 `position: relative` 作为定位基准。
- `app/src/pages/student/CockpitPage.tsx`：会话激活时渲染 veil 元素；更新注释。
- 追加调整：胶囊固定为与内容列同宽（`min(100%, 900px)`，移动端 `46rem`），标题文字靠左显示。

**变更原因：**
- 用户要求标题胶囊居中、过渡半透明（越靠近顶部越模糊）、对话内容盒拓展到顶部全高；随后要求胶囊固定内容区宽度、标题靠左。

**验证：**
- `tsc --noEmit` 通过；`vitest run tests/cockpit-flow.test.tsx tests/cockpit-summary.test.ts` 27/27 通过。
- Playwright 实测截图 `.playwright-mcp/cockpit-title-bar-width.png`（等宽胶囊、标题靠左）与 `cockpit-title-blur-scroll.png`（滚动时消息在顶部面纱下渐隐模糊）。

**仍需事实核验：**
- 无。

## [2026-08-21 00:57] 删除会话确认弹窗改为全页面全局显示

**变更文件：**
- `app/src/pages/student/cockpit/LeftRail.tsx`：`WorkbenchRecentSessions` 内的 `ConfirmDialog` 改为通过 `createPortal(..., document.body)` 渲染（含 SSR 防护 `typeof document === "undefined"` 判断），并补充注释说明 portal 原因。

**变更原因：**
- 用户反馈删除 Agent 会话历史的确认弹窗只出现在左侧导航栏区域。根因：侧栏 `.shell[data-shell-variant="student-workbench"] .sidebar` 带 `backdrop-filter: blur(...)`，会成为 fixed 后代的包含块，将弹窗裁剪到侧栏内。
- 选择 portal 到 body 而非全局改 `Modal`：避免学生工作台 shell 上重映射的设计令牌（`--color-surface` 等）对全局 Modal 失效；该确认弹窗仅用 material 令牌，root 与学生端取值几乎一致，视觉无差。

**验证：**
- `tsc --noEmit` 通过；`vitest run tests/cockpit-flow.test.tsx` 25/25 通过。
- Playwright 实测：遮罩 `.overlay` 覆盖整个视口（1560×850），弹窗居中（中心点 780,425 与视口中心重合），DOM 挂载在 `BODY` 下；截图 `.playwright-mcp/confirm-dialog-global.png`。

**仍需事实核验：**
- 无。

## [2026-08-21 10:36] 学生端 agent 对话：隐藏引用来源区 + 头像与字体排版优化

**变更文件：**
- `app/src/pages/student/cockpit/ChatStream.tsx`：移除对话流底部 `<RightRail>` 渲染及其 import，滚动跟随依赖中的 `run.citations` 一并移除；更新过时的 "citation panel" 注释。
- `app/src/pages/student/cockpit/RightRail.tsx`：整文件删除（引用来源区唯一实现，已无消费者）。
- `app/src/pages/student/cockpit/cockpit.css`：删除 `.cockpit-runtime-context` / `.runtime-context-*` / `.runtime-citations` 及其工作台覆盖（死样式）；`.assistant-avatar` 改为 8px 圆角方块、无描边；`.cockpit-workbench .assistant-avatar` 改为 30px 实心品牌蓝（`var(--accent)`）+ 白色图标，移除右下角琥珀色状态点 `::after`；新增深色主题头像底色压深规则（#2b6cb8）；`.cockpit-workbench .bubble` 正文 15px → 16px；`.cockpit-workbench .bubble-markdown` 正文色 `--ink-soft` → `--ink`、行高 1.75 → 1.8。
- `app/src/components/agent/agent-presentation.css`：`.agent-avatar` 基础样式由浅底描边芯片改为品牌色实心底 + 白色图标（对齐 Kimi/DeepSeek/MiniMax 助手身份处理）。
- `app/tests/cockpit.test.tsx`：`citation.attached` 用例改为负向断言——事件仍入运行状态，但对话画布不出现 `citation-section` 与「引用来源」文案。

**变更原因：**
- 用户要求学生端 agent 对话 UI 不再显示「引用来源/引用资料」类区块；仅隐藏 cockpit 对话页，RAG 问答页（RagQaPage）与教师端"如实展示"保持不变。
- 用户要求参考 Kimi/DeepSeek/MiniMax 优化 agent 头像与对话字体：实心品牌色圆角方块白图标头像、16px 近墨色正文、1.8 行高提升中文长文阅读舒适度。
- 后端 citation 数据管道（SSE `citation.attached`、`run.citations` 状态）保持不变，仅前端不渲染，便于日后恢复。

**验证：**
- `npx tsc --noEmit` 通过；`npx vitest run` 32 个测试文件、267 tests 全部通过（含改写后的引用隐藏用例与 agent-presentation/message-bubble 头像用例）。
- Playwright 实测（dev server 5173 热更新生效）：历史会话中助手头像呈实心蓝底白图标圆角方块，对话流无引用来源区块；截图 `.playwright-mcp/cockpit-chat-ui-after.png`。

**仍需事实核验：**
- 深色主题为预留偏好（非默认），其头像底色规则未做实机目检。

## [2026-08-21 12:03] 学生端对话 Markdown 渲染精化：标题层级 + 代码块头部栏

**变更文件：**
- `app/src/pages/student/cockpit/MessageBubble.tsx`：新增 `MarkdownCodeBlock` 组件并注册为 react-markdown 的 `pre` 渲染器——代码块外包一层头部栏，左侧语言标签（从 `language-x` className 提取，无标注回退 "code"），右侧复制按钮（`navigator.clipboard` 写 pre 纯文本，成功显示"已复制" 1.6s，剪贴板不可用静默失败）。
- `app/src/pages/student/cockpit/cockpit.css`：工作台 markdown 标题字号与 16px 正文拉开层级（h1 20px/700、h2 18px/700、h3-h6 16px/650，基础样式中 h2 曾与正文同号、h3 反小于正文）；代码块边框/圆角/底色/下间距迁移至 `.md-codeblock` 外壳，pre 仅保留代码排版；新增 `.md-codeblock-header/-lang/-copy` 样式（令牌化颜色，暗色主题自动跟随）；列表项间距 2px → 4px 适配 1.8 行高。
- `app/tests/message-bubble.test.tsx`：新增两例——python 围栏代码块渲染语言标签 + 复制按钮 + `.md-codeblock` 外壳；无语言标注代码块回退 "code" 标签。

**变更原因：**
- 用户要求优化对话内容 markdown 显示。实测现有 ReactMarkdown+GFM 渲染功能正常，但与 Kimi/DeepSeek 相比标题层级弱（h2 与正文同号）、代码块无语言标签/复制按钮。按用户拍板：只做对话页渲染精化，不新增语法高亮依赖。

**验证：**
- `npx tsc --noEmit` 通过；`npx vitest run` 32 个测试文件、269 tests 全部通过。
- Playwright 实测（历史会话重载）：computed style 确认 h1 20px / h2 18px / 正文 16px / 行高 28.8px（=1.8）；代码块头部栏渲染 "python" + 复制按钮，点击后按钮变"已复制"。截图 `.playwright-mcp/markdown-polished-top.png`、`markdown-polished-codeblock.png`。

**仍需事实核验：**
- 复制按钮依赖安全上下文（localhost/127.0.0.1 满足）；非安全上下文下静默不复制，未做降级 UI 提示。

## [2026-08-21 15:21] 扩充预设演示学习内容与知识图谱专项节点

**变更文件：**
- `server/bhzd_py/seed/demo_learning_content.py`：新增 8 条项目内置预设任务的确定性知识点和练习定义；每条任务含 2 个知识点、3 道混合题型练习，并保留旧 NER 业务键。
- `server/bhzd_py/seed/loader.py`：`--demo` 为演示学生幂等写入 8 条预设任务、知识点和练习，标记为手工完成内容，并把图谱任务和教学单元写入资源追溯信息。
- `data/graph/graph-catalog.json`：新增内容安全上下文、客服情感证据、车载唤醒负例、图像 IOU、视频事件边界五组 KNG/TSK/RES 节点及可追溯关系。
- `data/graph/annotation-capability-graph.json`、`data/graph/annotation-capability-graph.graphml`：由构建脚本重新生成的图谱产物。
- `scripts/validate_graph.py`、`server/tests/test_seed.py`、`server/tests/test_graphx.py`：同步图谱规模契约，并覆盖 seed 内容、图谱任务引用和幂等性。

**变更原因：**
- 演示版本需要更多与标航智导现有文本、图像、语音、视频教学规则一致的预设练习、知识点、题目和图谱节点，避免使用脱离项目的通用样例。

**验证：**
- `python scripts/build_graph.py` 生成 181 个节点、260 条边；`python scripts/validate_graph.py data/graph/annotation-capability-graph.json` 全项通过。
- `uv run ruff check bhzd_py/seed/loader.py bhzd_py/seed/demo_learning_content.py tests/test_seed.py tests/test_graphx.py` 通过；`uv run python -m compileall -q bhzd_py/seed` 通过。
- `uv run pytest -q tests/test_seed.py tests/test_graphx.py tests/test_task_learning_content.py`：26 passed，保留 1 个既有 Starlette/httpx 弃用警告；`git diff --check` 无空白错误。
- 完整后端回归为 498 passed / 1 failed；失败为工作区既有的 `tests/test_task_drafts.py::test_revision_wording_routes_to_task_flow`，其任务草稿意图识别与本次演示数据文件无直接交集。

**仍需事实核验：**
- 因完整后端回归未全绿，未重启 `127.0.0.1:8787`，也未对当前持久化演示库运行 seed；运行时图谱刷新和持久化演示数据加载留待该独立失败处理后执行。

## [2026-08-21 15:35] Agent 学习任务改为「草稿 → 回答底部按钮 → 预览卡 → 显式同步」链路

**变更文件：**
- `server/bhzd_py/migrations/027_task_drafts.sql`（新增）、`server/bhzd_py/agent/task_drafts.py`（新增）：任务草稿表与生成/同步逻辑；LLM 只产出任务卡文案字段，data_type/cap_ids 来自确定性计划与图谱工具结果；模型不可用时回退模板卡。
- `server/bhzd_py/agent/orchestrator.py`：任务类意图计划改为 rag.search + graph.reason 两个读步骤，收尾阶段生成草稿；不再为学生端学习任务开 task.preview/task.create 确认门（工具本身保留，预设/教师路径不受影响）。
- `server/bhzd_py/agent/events.py`、`prompts.py`、`composer.py`、`intents.py`：新增 task.draft 持久化事件与草稿生成提示词；模板降级补草稿引导文案；意图动词扩展 修改/调整/更新（支持「继续修改」话术，"如何修改…"仍走 RAG）。
- `server/bhzd_py/routers/tasks.py`：新增 `POST /api/task-drafts/{id}/sync`（CSRF+属主校验，synced 状态幂等，重复点击/刷新不重复建任务）；`server/bhzd_py/routers/runs.py`：会话详情新增 task_drafts_by_run 投影供历史回放。
- 前端：`app/src/api/types.ts`、`app/src/api/sse.ts`、`cockpit/runStream.ts`、`useCockpitRun.ts`、`ChatStream.tsx`、`CockpitPage.tsx`、新增 `TaskDraftSection.tsx`（预览弹窗：同步到学习任务 / 继续修改预填输入框）、`cockpit.css`；`EmbeddedCard.tsx` 导出 TaskCardBody 复用。
- 测试：`server/tests/test_task_drafts.py`（新增 11 例）、`test_agent_orchestrator.py`、`test_confirmations.py`（确认门覆盖改用 diagnostic.save_summary 写门）、`test_migrations.py`（登记 027）；`app/tests/task-draft.test.tsx`（新增 3 例）；`tests/e2e/smoke.spec.ts` AC1 改为新链路断言。
- `docs/master-checklist.md`：「不引入 ReAct」一行补充写确认路径口径（诊断/掌握度/预设走确认门；学习任务创建走草稿卡片显式同步）。

**变更原因：**
- 用户指出 Agent 无法真正生成学习任务：旧链路任务卡为固定模板（标题恒为「×标注练习任务」），LLM 不参与内容生成。按已批准简报改为：LLM 生成任务内容整理进回答，回答底部加交互按钮，点击打开任务卡预览，卡上按钮直接同步到学习任务或预填话术让 Agent 继续修改；旧 task.preview 嵌入卡 + task.create 确认门流程被替换（卡片同步按钮即学生显式确认）。

**验证：**
- 后端 `uv run pytest -q` 最终回归 500 passed（此前的 graphx/teacher_agent 失败为工作区并行会话改动与测试隔离抖动，孤立复跑均通过）；前端 `npx tsc --noEmit`、`npx eslint`（0 error）、`npx vitest run` 33 文件 272 tests 全部通过。
- 后端已按 AGENTS.md 流程重启：旧进程 PID 39940（父 33968，venv `python -m bhzd_py.main`）→ 新进程 PID 36540（父 6776），2026-08-21 15:42，`GET /api/health` 200，迁移 027 已应用（schema_migrations=27）。
- 真实链路验证（`scripts/verify_task_draft_chain.py`，直连 8787）：发起生成 → run 完成无确认门停留 → 会话详情含草稿卡（含学习内容/练习）→ 同步落库且内容行存在 → 二次同步幂等（already_synced）→ 无 CSRF 403 → 通过，验证数据已清理。
- e2e `tests/e2e/smoke.spec.ts` AC1 在真实浏览器 chromium 与 msedge 双通道通过（按钮 → 预览弹窗 → 同步回执）。

**仍需事实核验：**
- 多阶段任务的 LLM 卡 JSON 结构（stages 数组）依赖模型遵从度，已有模板回退兜底但未经真实模型输出验证；「继续修改」的修订效果同理（提示词组装已有测试覆盖）。
