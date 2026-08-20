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
