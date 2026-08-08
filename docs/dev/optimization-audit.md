# 标航智导项目优化审计报告

**审计日期：** 2026-08-02
**审计方式：** 只读静态分析 + 实测（`EXPLAIN QUERY PLAN`、`TestClient` 端点探测、AST 扫描、`vitest run`、`pytest`）
**基线：** `python -m pytest server/tests` 258 passed · `vitest run` 104 passed · `tsc --noEmit` exit 0
**范围：** FastAPI 后端 134 个 .py（约 3 万行）+ React 19 前端 98 个 .ts/.tsx（约 2.1 万行）+ 9 个 SQL 迁移 + 38 张表

---

## 一、P0：规模化悬崖

> 这些问题在当前体量下完全无感，但真实课堂负载下**会同时失效**，且彼此放大。

### 1.1 缺 12 个热点索引（最高优先）

**取证命令：** `EXPLAIN QUERY PLAN` 实测 17 个高频 WHERE 列，12 个返回 `SCAN … TEMP B-TREE`。

| 表.列 | 典型查询场景 | 后果 |
|---|---|---|
| `agent_events(run_id, seq)` | SSE 事件拉取（每客户端 4 次/秒） | 全表扫 + 临时 B 树排序，最严重 |
| `messages(conversation_id, created_at)` | 会话消息列表 | 全表扫 + B 树 |
| `learning_tasks(user_id, class_id)` | 学生任务列表 | 全表扫 |
| `audit_logs(created_at)` | 审计日志分页 | 全表扫 + B 树 |
| `conversations(user_id)` | 用户会话列表 | 全表扫 |
| `tool_calls(run_id)` | 编排历史 | 全表扫 |
| `agent_runs(conversation_id)` | 会话详情 | 全表扫 |
| `mastery_events(user_id)` | 掌握度历史 | 全表扫 |
| `rag_chunks(document_id)` | RAG 召回 | 全表扫 |
| `rag_jobs(document_id)` | 管线状态 | 全表扫 |
| `task_attempts(task_id)` | 任务详情 | 全表扫 |
| `messages(conversation_id)` | _(已列)_ | |

**最坏情况：** 30 名学生同时在指挥舱页面 → 每秒 120 次全表扫 `agent_events`，SQLite 写锁竞争。

**修复：** 新增迁移文件 `server/bhzd_py/migrations/010_indexes.sql`，内容约 12 条 `CREATE INDEX`，幂等，风险低。

**已验证无问题（勿改）：** `user_sessions.token_hash` 靠 UNIQUE 约束的 `sqlite_autoindex` 已走索引，不在缺失之列。

---

### 1.2 18 个列表端点的 `limit`/`offset` 无上下界

**取证：** AST 扫描发现 `rag_admin.py`、`diagnostics.py` 等文件中 `limit: int = 50` 是裸 int，缺 `Query(ge=1, le=200)`。

```
# 有问题（rag_admin.py 等）
limit: int = 50,   # ?limit=999999999 直接落 SQL

# 正确示范（admin.py 已有）
limit: int = Query(default=50, ge=1, le=200),
```

**修复：** 参照 `routers/admin.py` 的写法，对涉及列表的参数补 `Query(ge, le)` 声明，各处改动均独立，无耦合。

---

### 1.3 RAG 上传：同步管线 + 全量内存读取

**取证：** `server/bhzd_py/routers/rag_admin.py:354`（`content = file.file.read()`）与 `rag_admin.py:411`（`pipeline.run_pending()`）。

端点状态码声明 `202 Accepted`（语义：异步），实际行为是**先把最多 50MB 文件整体读进内存，再在 HTTP 请求线程里同步跑解析 → 切片 → 嵌入**。三个并发上传足以耗尽线程池。注意：超限校验在 `read()` **之后**，所以 50MB 内存在拒绝前已经分配。

**修复方案：**
1. 先做 `Content-Length` 预检，超限直接拒绝（节省内存）；
2. `pipeline.run_pending()` 改为后台任务（`BackgroundTasks` 或 `orchestrator.spawn`），让 202 名副其实；
3. 考虑 `shutil.copyfileobj` 流式落盘替代全量 `read()`。

---

### 1.4 无孤儿运行回收器

**取证：** 当前库里 6 个 run 处于 `waiting_confirmation` 状态（永不结束），`orchestrator.py` 使用进程级守护线程背景 loop，重启后在途 run 不会自动 fail。

`server/bhzd_py/agent/orchestrator.py` 的 `execute_run` 在守护线程中运行，与 HTTP 请求生命周期解耦（这是正确设计），但 app.py 的 `_lifespan` 没有在启动时把仍处于 `running`/`waiting_confirmation` 的 run 标记为 `failed`。前端 SSE 等到 `stream.end` 事件才关闭 EventSource，这些卡住的会话会让浏览器永远转圈。

**修复：** 在 `_lifespan` 启动阶段执行一条 UPDATE，把非终态 run 全部标记 `failed`，并 emit 一条 `agent.error` 事件。

---

## 二、P1：体验与工程

### 2.1 前端 1.22MB 单 bundle，零代码分割

**取证：** `dist/assets/index-CKHS-dSz.js` = 1.22MB；`app/src/app/router.tsx` 45 个 import 全是静态，`React.lazy` 用了 0 次；`vite.config.ts` 无 `manualChunks`。

学生打开登录页，需要下载完整个 vis-network 图谱引擎 + 全部管理端 + 全部教师端。

**修复：**
```ts
// router.tsx：四个 layout 天然边界，各自 lazy
const StudentLayout = React.lazy(() => import("../layouts/StudentLayout"));
const TeacherLayout = React.lazy(() => import("../layouts/TeacherLayout"));
// vis-network 只在 GraphPage 用，单独切分
const GraphPage = React.lazy(() => import("../pages/student/GraphPage"));
```
预估首屏可砍至 200–300KB，图谱页按需加载。

---

### 2.2 全项目 0 处 AbortController，fetch 无超时，无 ErrorBoundary

**取证：**
- `grep -c "AbortController" src/api/client.ts` → 0
- `grep -c "AbortController" src/api/sse.ts` → 0
- 12 个页面 `useEffect` 发请求且无取消逻辑
- 全应用无 `componentDidCatch`/`errorElement`

**影响：**
- 快速切页时旧响应覆盖新状态（竞态）
- 后端挂起时 fetch 无限等待（用户看到永久 loading）
- 任一页面渲染抛错 → 整个 SPA 白屏

**修复（三件套，每件独立）：**
1. `client.ts`：`fetch` 包装加 `AbortSignal.timeout(10_000)`
2. 所有 `useEffect` fetch：加 cleanup 函数调用 `controller.abort()`
3. `App.tsx`/`router.tsx`：加顶层 `errorElement`（React Router v7 原生支持）

---

### 2.3 纯 Python 余弦检索，无 numpy

**取证：** `server/bhzd_py/rag/local_embed.py:63`：

```python
dot = sum(x * y for x, y in zip(a, b))  # 纯 Python 循环
```

`vectorstore.py` 把全语料候选拉进 Python 逐个打分。当前 12 个切片 × 512 维 = 6144 次浮点运算，无感。1 万切片时 = 512 万次单线程浮点运算，且发生在**同步端点**里（所有 router 除 `runs.py` 的 8 个 async 端点外均为同步 def），阻塞整个 anyio 线程池槽位。

**修复：** `pyproject.toml` 加 `numpy`（已是 scipy/scikit 的传递依赖，体积不是问题），把 `cosine_similarity` 改为 `np.dot(a, b)` 或 `np.float32` 数组操作，速度提升约 10–50×。将来升规模可换 `faiss`。

---

### 2.4 teacher.py N+1 查询

**取证：** `teacher.py` 19 个 for 循环内有 9 处 `conn.execute`。典型：`teacher.py:403` 班级详情页对每个学生发 2 条查询（任务统计 + 平均掌握度）。

```python
# 现状：30 人班级 = 60 次数据库往返
for enr in enrollments:
    stats = conn.execute("... WHERE user_id = ? AND class_id = ?", ...)
    avg   = conn.execute("... WHERE user_id = ?", ...)
```

同文件 `teacher.py:900` 已用了正确的批量写法 `IN ({_placeholders(ids)})`，模式就在隔壁。

**修复：** 两条 `GROUP BY` 查询先取全班数据，再 Python 端组装，消除 O(N) 数据库往返。

---

### 2.5 无 CI，无 lint/format/type 门禁

**取证：**
- 无 `.github/` 目录
- `server/pyproject.toml` 无 `ruff`/`mypy` 声明
- `app/package.json` 无 `eslint`/`prettier`
- 无 `.pre-commit-config.yaml`
- `pytest` 被列在 `[project].dependencies`（运行时依赖）而非开发依赖

258 + 104 个测试是真资产，全靠手动跑，代码合并时无门禁。

**修复（逐步建立）：**

```toml
# server/pyproject.toml
[dependency-groups]
dev = ["ruff>=0.5", "mypy>=1.10", "pytest>=8.2"]
```

```yaml
# .github/workflows/ci.yml（最小版本）
on: [push, pull_request]
jobs:
  backend:
    run: cd server && ruff check . && python -m pytest
  frontend:
    run: cd app && npx tsc --noEmit && pnpm test:run
```

---

## 三、P2：债务清理

### 3.1 Wave1 router 容错脚手架已过期

`server/bhzd_py/app.py:83-89`：

```python
try:
    module = importlib.import_module(f"bhzd_py.routers.{name}")
    app.include_router(module.router)
except ImportError:
    logger.warning("router 模块尚未就绪，已跳过注册")  # 生产中是事故
```

**取证（实测）：** 14 个模块全部就位，Wave1 阶段已过。用 `__import__` 注入模拟写错一个 router 内部 import，结果该 router 的 30 个端点静默变成 404，`/api/health` 仍报 200 ——— 监控无感知。

**修复：** 删除 `try/except`，改为硬 import；若某个 router 确实需要可选，改用明确的功能开关而非异常吞掉。

---

### 3.2 `server/_legacy` 265KB / 39 文件已无引用

**取证：** `grep -rn "_legacy" server/bhzd_py app/src scripts` 零结果（`scripts/build_curriculum.py` 里的 `_load_legacy_snapshot` 是本地函数名，与 `_legacy` 目录无关）。`server/tests` 里两处 "legacy session" 只是描述旧格式会话升级的概念，不 import 该目录。

**修复：** 直接删除 `server/_legacy`，释放 265KB，消除开发者困惑。

---

### 3.3 7 张只增表无保留策略

以下表无任何 `DELETE` 语句，只追加：`agent_events`、`audit_logs`、`analytics_events`、`login_attempts`、`recall_logs`、`mastery_events`、`tool_calls`。

生产运行一学期后，`agent_events` 会涨到数十万行，加剧 1.1 节的索引缺失问题。

**修复：** 增加后台定时任务（或启动时 prune），保留最近 N 天或 M 条，具体阈值按 PRD 确定。

---

### 3.4 大文件清单（参考重构优先级）

| 文件 | 行数 | 主要问题 |
|---|---|---|
| `server/bhzd_py/routers/rag_admin.py` | 1952 | 55 个端点 + 业务逻辑 + DB 操作全混在一起 |
| `server/bhzd_py/routers/teacher.py` | 1421 | N+1 查询 + 大量重复分页模式 |
| `app/src/pages/teacher/TaskPublishPage.tsx` | 1252 | 表单 + 预览 + 验证 + API 调用 + 发布流程混合 |
| `app/src/api/types.ts` | 1079 | 手维护，无 OpenAPI 生成，与后端 Pydantic 模型存在漂移风险 |
| `app/src/pages/teacher/AnalyticsPage.tsx` | 801 | 图表 + 数据获取 + 筛选逻辑混合 |

18 个页面各自手写 `loading`/`error`/`data` 三件套，无统一数据获取层，无 `app/src/hooks` 目录。引入共享 `useFetch<T>` hook 或 TanStack Query 可消除 ~60% 的 `useState<boolean>(true)` 样板。

---

## 四、已验证安全 / 无需改动的部分

> 这些项目看起来可疑，但实测均无问题，请**勿凭直觉改动**。

| 项目 | 结论 | 取证 |
|---|---|---|
| 7 处 f-string SQL 拼接 | 安全 | 拼入的只有硬编码表名或白名单列名，值全部走 `?` 占位符 |
| 口令散列 | 安全 | argon2id（`argon2-cffi` 默认参数），timing-safe verify |
| Provider 密钥落盘 | 安全 | AES-GCM 加密，密钥来自 `BHZD_CONFIG_ENCRYPTION_KEY` |
| 口令传输 | 安全 | RSA 公钥包裹 AES 密钥，客户端加密后传输（`app/src/auth/passwordCrypto.ts`） |
| Cookie 属性 | 安全 | `httponly=True`, `samesite="lax"`，生产环境加 `secure=True` |
| 生产配置门禁 | 安全 | `config.validate_runtime_configuration()` 在迁移前 fail-closed |
| 错误处理器 | 安全 | `errors.py` 兜底 handler 不泄露堆栈 |
| 13 个无鉴权端点 | 合理 | `/api/auth/*` 是入口（无会话可绑定），`/api/graph/*` 为设计上的可选登录 |
| 68 个变更端点 CSRF | 基本覆盖 | 52 个有 CSRF dep；16 个缺失项均为 auth 入口或有设计注释说明 |
| `user_sessions.token_hash` 索引 | 已有 | 靠 UNIQUE 约束 `sqlite_autoindex` 走索引，无需额外创建 |

**唯一值得商量的小点：** `/api/auth/logout` 无 CSRF 保护，攻击者可强制他人登出（无数据损失，有解），修起来一行 Depends 替换。

---

## 五、建议的执行顺序

每步均可独立验证，不互相依赖。

| 步骤 | 内容 | 改动范围 | 风险 |
|---|---|---|---|
| ① | 新建 `010_indexes.sql`：12 条 `CREATE INDEX` | 1 个迁移文件 | 极低，幂等 |
| ② | 18 个端点补 `Query(ge, le)` 边界 | 参数声明改动 | 极低 |
| ③ | 删除 `server/_legacy`（265KB） | 纯删除 | 极低 |
| ④ | app.py router 注册改硬 import | 5 行改动 | 低 |
| ⑤ | `_lifespan` 加孤儿 run reaper | ~10 行改动 | 低 |
| ⑥ | RAG 管线改后台任务 + 上传预检顺序调整 | `rag_admin.py` | 中 |
| ⑦ | 前端路由懒加载 + ErrorBoundary + fetch 超时 | `router.tsx`、`client.ts` | 低 |
| ⑧ | `cosine_similarity` 引入 numpy | `local_embed.py` + `pyproject.toml` | 低 |
| ⑨ | teacher.py N+1 → GROUP BY 批量 | `teacher.py` | 中 |
| ⑩ | 补 CI + ruff + eslint + pre-commit | 配置文件 | 低，一次性 |
