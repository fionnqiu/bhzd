# 标航智导全权重构蓝图（单一事实来源）

> 版本：v1.0 · 2026-07-31
> 依据：`docs/标航智导-PRD/` v3.1 六份子 PRD（准绳）+ v3.0 完整版独有内容（埋点、SourceLedger schema、图谱配色、欢迎态文案、"内容安全文本审核"预设、性能指标 NF9-NF14、AC13/AC14、演示模式）。
> 本文档是所有研发子任务的接口契约：目录、schema、API、事件、工具、归属以此为准。业务规则细节直接引用各 PRD 章节。

---

## 1. 技术决策

| 项 | 决策 | 理由 |
|----|------|------|
| 后端 | Python 3.11 + FastAPI 0.139 + SQLite(WAL) | 工具链已就绪；PRD 未限定栈 |
| 后端新增依赖 | pypdf（PDF 解析）、python-docx（DOCX 解析） | 环境已安装；PRD-03 P0 格式 |
| 移除依赖 | langgraph（声明未用） | Agent 编排自研、确定性优先 |
| 前端 | React 19 + Vite 7 + TS + react-router-dom v7 + vis-network + lucide-react | 路由为新增，其余沿用 |
| 数据库 | sqlite3 标准库 + SQL 迁移文件（sha256 校验） | 沿用已验证模式 |
| 向量检索 | SQLite BLOB 存向量 + Python 余弦；嵌入走 provider，未配置时用确定性本地哈希嵌入（512 维词袋） | 保证离线/演示/测试可跑（PRD-06 §11 降级） |
| LLM 接入 | 4 协议适配器：xunfei_xingchen / xunfei_spark / chat_completions / anthropic_messages；主备切换 | PRD-04 §3.1 P0 |
| 无 LLM 降级 | 模板化答案合成器（展示工具结果，不编造） | PRD-06 §11.1 |

## 2. 目录布局

### 2.1 后端 `server/`

```
server/
  pyproject.toml                  # 重写：name bhzd-agent-server-py, py>=3.11
  bhzd_py/
    __init__.py
    main.py                       # uvicorn 入口：python -m bhzd_py.main
    app.py                        # create_app()：中间件 + 注册全部 router + 静态(var/uploads 不提供公开访问)
    config.py                     # pydantic-settings，BHZD_ 前缀
    db.py                         # 连接、迁移执行器(sha256 校验)、事务助手
    security.py                   # argon2id、AES-256-GCM、token、限流/锁定、base_url 安全校验(NF9)
    audit.py                      # audit_log(actor, action, target, before, after, ip, ua)
    deps.py                       # FastAPI 依赖：current_user / require_role / csrf_protect
    errors.py                     # ApiError + 统一错误格式 + 全局 handler
    telemetry.py                  # 埋点采集（14 事件名见 §8）
    migrations/  001_identity.sql 002_org.sql 003_agent.sql 004_learning.sql 005_rag.sql 006_admin.sql
    routers/
      auth.py  runs.py  confirmations.py  presets.py  graph.py  tasks.py
      diagnostics.py  profile.py  rag_query.py  rag_admin.py  teacher.py  admin.py  events.py
      # 每个模块暴露 APIRouter 实例名 `router`
    agent/
      orchestrator.py             # 意图→计划→工具循环→SSE；追问规则；确认门
      events.py                   # 事件名常量（§7）
      intents.py                  # 规则式意图/场景/数据类型识别 + 可选 LLM 分类
      composer.py                 # LLM 合成 + 模板降级合成
      prompts.py
    tools/
      registry.py                 # ToolSpec(name, permission, auto_execute, handler, description)
      course_search.py graph_reason.py task_tools.py diagnostic_tools.py mastery_tools.py rag_tools.py
    rag/
      parsers.py                  # pdf(pypdf)/docx(python-docx)/md/txt；其余→PARSE_UNSUPPORTED
      chunker.py                  # chunk_size/overlap/标题继承（参数来自 rag_settings）
      embeddings.py               # provider 嵌入 + 本地哈希嵌入 fallback
      vectorstore.py              # sqlite BLOB 余弦检索
      retriever.py                # 混合召回(向量+关键词)、元数据过滤、阈值拒答、场景冲突降权
      pipeline.py                 # parse→chunk→index 异步任务状态机(幂等/重试/版本)
    diagnosis/
      detect.py parsers.py rules.py engine.py   # JSON/TextGrid/COCO/VOC 确定性诊断
    graphx/
      loader.py reason.py         # 加载 data/graph JSON；PRE 路径(Kahn 拓扑+无环校验)、子图、搜索
    mastery/service.py            # 掌握度更新规则(PRD-06 §8.3/8.4, clamp 0..1)
    seed/
      loader.py                   # python -m bhzd_py.seed.loader [--demo]
      presets.py                  # 8 条预设路径（PRD-01 §4.3 七条 + v3.0"内容安全文本审核"）
      demo_docs/*.md              # 4 篇内置规范文档（演示模式发布态）
  tests/                          # pytest，按域分文件
```

### 2.2 前端 `app/src/`

```
app/src/
  main.tsx  index.css
  app/router.tsx                  # createBrowserRouter + 角色守卫
  api/client.ts  api/sse.ts  api/types.ts   # types.ts = §6 DTO 契约
  auth/AuthContext.tsx  auth/*.tsx(Login/Register/VerifyEmail/ForgotPassword/ResetPassword)
  layouts/{StudentLayout,TeacherLayout,RagAdminLayout,AdminLayout}.tsx
  components/                     # DataTable StatusBadge ConfirmDialog CitationCard MasteryBadge EmptyState Field 等
  pages/student/  CockpitPage PresetsPage GraphPage TasksPage TaskDetailPage DiagnosticsPage RagQaPage ProfilePage
  pages/student/cockpit/          # WelcomeState ChatStream PlanCard ExecutionTrace ConfirmationGate EmbeddedCard Composer
  pages/teacher/  DashboardPage ClassesPage ClassDetailPage TaskPublishPage AnalyticsPage
  pages/rag/  DocumentsPage UploadPage DocumentDetailPage JobsPage ChunkEditorPage LedgersPage SearchTestPage EvalCasesPage PublishReviewPage
  pages/admin/  ProvidersPage RagSettingsPage UsersPage SecurityPage AuditLogsPage
app/tests/                        # vitest：router 守卫 + 关键页面冒烟
```

## 3. 配置（config.py，BHZD_ 前缀）

`BHZD_HOST`(127.0.0.1) `BHZD_PORT`(8787) `BHZD_DATABASE_PATH`(var/bhzd.sqlite) `BHZD_DATA_DIR`(仓库 data/) `BHZD_UPLOAD_DIR`(var/uploads) `BHZD_CONFIG_ENCRYPTION_KEY`(hex/base64 32B；仅开发模式可使用进程内临时 key，生产必须提供固定值) `BHZD_ADMIN_EMAIL`+`BHZD_ADMIN_PASSWORD`(初始系统管理员) `BHZD_SMTP_*`+`BHZD_MAIL_FROM`(仅开发模式允许写入 `var/mail_outbox.log` 并返回 dev token；生产必须通过 SMTP 投递且不回显 token) `BHZD_DEMO_MODE`(bool) `BHZD_SESSION_TTL_HOURS`(72) `BHZD_CORS_ORIGINS`(默认仅 `BHZD_PUBLIC_ORIGIN`)。
兼容旧名：读取 `.env.example` 已有变量名，不破坏 .env.local。

生产启动在迁移前校验并 fail closed：配置加密密钥必须是有效 32B 值；教师邀请码必须是非默认、至少 16 字符的私有值；SMTP 主机与发件人必须显式配置；`BHZD_PUBLIC_ORIGIN` 及全部 CORS 源必须为具体 HTTPS origin。生产 cookie 使用 Secure 属性，开发便利项不会进入生产路径。

## 4. 通用约定

- ID：uuid4 hex；时间：UTC ISO8601 字符串；分页：`?limit&offset` → `{items,total}`。
- 错误：`{"error":{"code":"SNAKE_CODE","message":"面向用户的中文消息"}}` + 恰当 HTTP 状态；学生端不暴露堆栈（PRD-01 §3.5 失败态）。
- 变更类请求必须带 `x-csrf-token`（登录后由 /api/auth/session 签发）。
- 会话隔离（NF4）：学生/教师端 cookie `bhzd_session`，系统管理端独立 cookie `bhzd_admin_session`（/api/admin/* 仅认后者，登录时按角色签发）。
- 审计（NF8）：审核/发布/归档/删除/权限变更/模型配置变更/参数修改必须写 audit_logs。
- 代码注释：解释"为什么"（关键逻辑、非显然决策、变通），风格跟随栈（Python docstring/#，TS // /** */）。

---

## 5. 数据库 Schema（迁移文件逐字契约，SQLite）

### 001_identity.sql
```sql
CREATE TABLE users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('student','teacher','content_admin','system_admin')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  school_id TEXT,
  email_verified_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE user_credentials (
  user_id TEXT PRIMARY KEY REFERENCES users(id),
  password_hash TEXT NOT NULL,          -- argon2id
  algo TEXT NOT NULL DEFAULT 'argon2id',
  updated_at TEXT NOT NULL
);
CREATE TABLE email_verification_tokens (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL, expires_at TEXT NOT NULL,
  consumed_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE password_reset_tokens (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL, expires_at TEXT NOT NULL,
  consumed_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE user_sessions (             -- 学生/教师/内容管理员会话
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL UNIQUE, csrf_token_hash TEXT NOT NULL,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT,
  ip TEXT, user_agent TEXT
);
CREATE TABLE admin_sessions (            -- 系统管理员独立会话(NF4 会话隔离)
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL UNIQUE, csrf_token_hash TEXT NOT NULL,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT,
  ip TEXT, user_agent TEXT
);
CREATE TABLE login_attempts (            -- 限流/失败锁定(NF5)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL, ip TEXT, success INTEGER NOT NULL, created_at TEXT NOT NULL
);
```

### 002_org.sql
```sql
CREATE TABLE schools ( id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL );
CREATE TABLE classes (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, school_id TEXT REFERENCES schools(id),
  invite_code TEXT UNIQUE, archived_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE class_teachers (
  class_id TEXT NOT NULL REFERENCES classes(id),
  teacher_id TEXT NOT NULL REFERENCES users(id),
  PRIMARY KEY (class_id, teacher_id)
);
CREATE TABLE class_enrollments (
  class_id TEXT NOT NULL REFERENCES classes(id),
  student_id TEXT NOT NULL REFERENCES users(id),
  joined_at TEXT NOT NULL, left_at TEXT,
  PRIMARY KEY (class_id, student_id)
);
```

### 003_agent.sql
```sql
CREATE TABLE conversations (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  title TEXT, scenario_id TEXT, data_type TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT
);
CREATE TABLE messages (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
  run_id TEXT, role TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool')),
  content TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE agent_runs (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
  user_id TEXT NOT NULL REFERENCES users(id),
  status TEXT NOT NULL CHECK (status IN ('running','waiting_confirmation','completed','failed','cancelled')),
  input_text TEXT NOT NULL, plan_json TEXT, scenario_id TEXT, data_type TEXT,
  provider_id TEXT, error TEXT, usage_json TEXT,
  created_at TEXT NOT NULL, completed_at TEXT
);
CREATE TABLE agent_events (              -- SSE 持久化，支持断线重连回放
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES agent_runs(id),
  seq INTEGER NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE tool_calls (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES agent_runs(id),
  tool_name TEXT NOT NULL, permission TEXT NOT NULL CHECK (permission IN ('read','write')),
  status TEXT NOT NULL CHECK (status IN ('requested','running','completed','failed','awaiting_confirmation','cancelled')),
  args_json TEXT, result_json TEXT, duration_ms INTEGER, is_write INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, completed_at TEXT
);
CREATE TABLE pending_confirmations (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES agent_runs(id),
  user_id TEXT NOT NULL REFERENCES users(id),
  tool_call_id TEXT NOT NULL REFERENCES tool_calls(id),
  action_type TEXT NOT NULL,             -- task.create / diagnostic.save_summary / mastery.update / teacher.publish_task / rag.publish_document / rag.archive_document / rag.create_document / rag.reindex_document / rag.save_eval_case
  preview_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','confirmed','cancelled','expired')),
  expires_at TEXT NOT NULL,              -- 普通写 30min；删除/归档 10min(PRD-06 §6.4)
  created_at TEXT NOT NULL, resolved_at TEXT
);
```

### 004_learning.sql
```sql
CREATE TABLE learning_profiles (
  user_id TEXT PRIMARY KEY REFERENCES users(id),
  goal_text TEXT, major TEXT, target_cert TEXT,
  onboarding_json TEXT,                  -- 入学测评结果(完整版 §11.1)
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE mastery (                   -- scenario_id 为 '' 表示通用掌握度
  user_id TEXT NOT NULL REFERENCES users(id),
  cap_id TEXT NOT NULL, scenario_id TEXT NOT NULL DEFAULT '',
  score REAL NOT NULL CHECK (score BETWEEN 0 AND 1),
  source TEXT, updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, cap_id, scenario_id)
);
CREATE TABLE mastery_events (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  cap_id TEXT NOT NULL, scenario_id TEXT NOT NULL DEFAULT '',
  old_score REAL NOT NULL, new_score REAL NOT NULL,
  source TEXT NOT NULL,                  -- exercise / diagnostic / teacher_task / assessment
  ref_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE learning_tasks (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),   -- 学生
  title TEXT NOT NULL, goal TEXT, data_type TEXT, scenario_id TEXT,
  cap_ids_json TEXT NOT NULL DEFAULT '[]',
  source TEXT NOT NULL CHECK (source IN ('agent','preset','teacher','diagnostic')),
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','not_started','in_progress','submitted','completed','paused','archived')),
  steps_json TEXT NOT NULL DEFAULT '[]',        -- [{title,description,notes,common_errors}]
  resources_json TEXT NOT NULL DEFAULT '[]',    -- [{type,title,ref_id,citation?}]
  rubric_json TEXT, practice_json TEXT,         -- 评分规则 / 练习样本
  counts_toward_mastery INTEGER NOT NULL DEFAULT 1,
  teacher_id TEXT, class_id TEXT, due_at TEXT,
  version INTEGER NOT NULL DEFAULT 1, parent_task_id TEXT,
  created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT
);
CREATE TABLE task_attempts (
  id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES learning_tasks(id),
  user_id TEXT NOT NULL REFERENCES users(id),
  attempt_number INTEGER NOT NULL,
  submission_json TEXT NOT NULL, score REAL, feedback_json TEXT,
  mastery_applied INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE diagnostic_summaries (      -- 原文件不持久化，仅存摘要(NF3)
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  file_format TEXT NOT NULL, data_type TEXT, scenario_id TEXT,
  error_count INTEGER NOT NULL, severity_counts_json TEXT NOT NULL,
  report_json TEXT NOT NULL, weak_cap_ids_json TEXT NOT NULL DEFAULT '[]',
  plan_json TEXT, created_at TEXT NOT NULL
);
CREATE TABLE analytics_events (          -- 埋点(§8)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT, event_name TEXT NOT NULL, props_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
```

### 005_rag.sql
```sql
CREATE TABLE rag_documents (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  file_type TEXT NOT NULL CHECK (file_type IN ('pdf','docx','md','txt','xlsx','csv','image','other')),
  source_type TEXT NOT NULL CHECK (source_type IN ('textbook','standard','enterprise','teacher','competition','other')),
  source_name TEXT NOT NULL, source_url TEXT, source_ledger_id TEXT,
  version TEXT NOT NULL,
  license_status TEXT NOT NULL CHECK (license_status IN ('authorized','internal','pending','forbidden')),
  data_types_json TEXT NOT NULL DEFAULT '[]',     -- ['text','image','audio','video']
  scenario_ids_json TEXT NOT NULL DEFAULT '[]',
  cap_ids_json TEXT NOT NULL DEFAULT '[]',
  visibility TEXT NOT NULL DEFAULT 'teacher' CHECK (visibility IN ('admin','teacher','student')),
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
    ('draft','parsing','parsed','chunking','chunked','indexing','indexed','review_pending','published','rejected','archived','expired','failed')),
  storage_path TEXT, file_hash TEXT,
  error_code TEXT, error_message TEXT,
  process_version INTEGER NOT NULL DEFAULT 1,     -- 参数变化生成新处理版本(PRD-06 §5.2)
  created_by TEXT NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  published_at TEXT, expires_at TEXT
);
CREATE TABLE rag_chunks (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES rag_documents(id),
  chunk_index INTEGER NOT NULL, content TEXT NOT NULL,
  summary TEXT, keywords_json TEXT NOT NULL DEFAULT '[]',
  page_start INTEGER, page_end INTEGER, section_title TEXT,
  token_count INTEGER NOT NULL DEFAULT 0,
  embedding BLOB, embedding_model TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  process_version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE rag_jobs (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES rag_documents(id),
  stage TEXT NOT NULL CHECK (stage IN ('parse','chunk','index')),
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
  idempotency_key TEXT UNIQUE,                    -- 幂等(PRD-06 §5.2)
  progress REAL NOT NULL DEFAULT 0,
  error_code TEXT, error_message TEXT, attempt INTEGER NOT NULL DEFAULT 0,
  params_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
);
CREATE TABLE source_ledgers (              -- v3.0 §12.4 字段级 schema
  id TEXT PRIMARY KEY, source_code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL, publisher TEXT, source_type TEXT, version TEXT,
  authorization_status TEXT NOT NULL CHECK (authorization_status IN ('approved','pending','expired','forbidden')),
  valid_from TEXT, valid_to TEXT,
  related_document_ids_json TEXT NOT NULL DEFAULT '[]',
  review_status TEXT NOT NULL DEFAULT 'draft' CHECK (review_status IN ('draft','reviewed','published')),
  notes TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE review_records (
  id TEXT PRIMARY KEY, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
  reviewer_id TEXT NOT NULL REFERENCES users(id),
  action TEXT NOT NULL CHECK (action IN ('submit','approve','approve_teacher_only','reject','archive','publish')),
  comment TEXT, created_at TEXT NOT NULL
);
CREATE TABLE eval_cases (
  id TEXT PRIMARY KEY, question TEXT NOT NULL, expected_answer TEXT,
  must_hit_document_ids_json TEXT NOT NULL DEFAULT '[]',
  must_hit_chunk_ids_json TEXT NOT NULL DEFAULT '[]',
  filters_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE eval_runs (
  id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','completed','failed')),
  metrics_json TEXT, case_results_json TEXT,
  created_by TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT
);
CREATE TABLE rag_settings (                -- 单行(id=1)
  id INTEGER PRIMARY KEY CHECK (id = 1),
  chunk_size INTEGER NOT NULL DEFAULT 500, chunk_overlap INTEGER NOT NULL DEFAULT 80,
  title_inherit INTEGER NOT NULL DEFAULT 1, table_strategy TEXT NOT NULL DEFAULT 'keep',
  top_k INTEGER NOT NULL DEFAULT 5, score_threshold REAL NOT NULL DEFAULT 0.35,
  hybrid_search INTEGER NOT NULL DEFAULT 1, rerank_enabled INTEGER NOT NULL DEFAULT 0,
  citation_format TEXT NOT NULL DEFAULT '【{title} {section} {page} v{version}】',
  refusal_policy TEXT NOT NULL DEFAULT 'refuse',  -- refuse / generic_advice
  max_citations INTEGER NOT NULL DEFAULT 5,
  prompt_template TEXT NOT NULL DEFAULT '', prompt_template_version TEXT NOT NULL DEFAULT 'v1',
  require_manual_review INTEGER NOT NULL DEFAULT 1,
  student_visibility_default TEXT NOT NULL DEFAULT 'student',
  expired_doc_policy TEXT NOT NULL DEFAULT 'remove',  -- 过期自动移出学生召回
  updated_at TEXT NOT NULL, updated_by TEXT
);
```

### 006_admin.sql
```sql
CREATE TABLE provider_configs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL,
  protocol TEXT NOT NULL CHECK (protocol IN ('xunfei_xingchen','xunfei_spark','chat_completions','anthropic_messages')),
  base_url TEXT NOT NULL, model TEXT NOT NULL,
  api_key_encrypted TEXT NOT NULL,          -- AES-256-GCM(NF2)，明文永不出库/日志
  role TEXT NOT NULL DEFAULT 'none' CHECK (role IN ('primary','fallback','embedding','rerank','none')),
  enabled INTEGER NOT NULL DEFAULT 1,
  timeout_seconds REAL NOT NULL DEFAULT 30,
  extra_json TEXT NOT NULL DEFAULT '{}',
  last_test_json TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE audit_logs (
  id TEXT PRIMARY KEY, actor_id TEXT, actor_role TEXT,
  action TEXT NOT NULL, target_type TEXT, target_id TEXT,
  before_json TEXT, after_json TEXT,
  ip TEXT, user_agent TEXT, created_at TEXT NOT NULL
);
```

---

## 6. API 契约（JSON DTO 关键字段；全部 `/api` 前缀）

通用：`UserDTO{id,email,name,role,status,email_verified:bool}`。所有 mutation 需 `x-csrf-token`。

### 6.1 认证 routers/auth.py（PRD-05 §4.1 + PRD-06 §3）
| 端点 | 说明 |
|------|------|
| GET /api/auth/password-key | 无需会话，返回当前 `{keyId,algorithm:"RSA-OAEP-256+A256GCM",publicKeyPem}`；响应带 `Cache-Control: no-store`，不得由浏览器或中间层复用 |
| POST /api/auth/register `{email,name,passwordEnvelope,role?,teacher_invite?}` | 学生自注册；教师角色需邀请码字段 `teacher_invite`；已存在邮箱→统一提示不暴露验证状态 |
| POST /api/auth/verify-email `{token}` | 邮箱验证；未验证禁止 Agent/RAG 问答 |
| POST /api/auth/resend-verification | 重发 |
| POST /api/auth/login `{email,passwordEnvelope}` | 限流 5 次/分/IP，连续失败 10 次锁 15 分钟；按角色签发 `bhzd_session` 或 `bhzd_admin_session` |
| POST /api/auth/logout；GET /api/auth/session | 返回 `{user, csrf_token}` |
| POST /api/auth/forgot-password `{email}`；POST /api/auth/reset-password `{token,passwordEnvelope}` | 不暴露账号存在性 |

`passwordEnvelope` 固定为 `{keyId,encryptedKey,iv,ciphertext}`：浏览器用 WebCrypto 生成一次性 AES-256 密钥和 12-byte IV，以 AES-GCM 加密口令，再用从 `/password-key` 获取的 RSA 公钥按 RSA-OAEP-SHA256 包装 AES 密钥。服务端先校验并解封，再进入既有 Argon2id 哈希或校验路径。注册、登录、重置密码均设置 `extra="forbid"`，旧明文 `password` 字段不属于 DTO 且会被拒绝；解封失败（失效 key、非 Base64、篡改等）统一返回安全的 `400 INVALID_PASSWORD_ENCRYPTION`，不暴露密码学细节。该请求层协议不替代 HTTPS。

### 6.2 Agent routers/runs.py + confirmations.py（PRD-05 §4.1/§5）
| 端点 | 说明 |
|------|------|
| GET/POST /api/conversations；GET/DELETE /api/conversations/{id} | 删除会话保留审计(PRD-06 §12.2) |
| POST /api/runs `{conversation_id?, input, scenario_id?, data_type?, attachment?}` | 启动运行 → `{run_id, conversation_id}` |
| GET /api/runs/{id} | 运行详情（状态、计划、工具调用、消息） |
| GET /api/runs/{id}/events?after_seq=N | SSE 事件流（§7），支持断点续播 |
| POST /api/confirmations/{id}/confirm；POST /api/confirmations/{id}/cancel；POST /api/confirmations/{id}/expire | 均须登录用户本人的 CSRF token；`expire` 只收敛到期确认，不执行写工具 |

`POST /api/confirmations/{id}/expire` 的状态语义：未到期的 pending 确认返回 `409 CONFIRMATION_NOT_EXPIRED`；到期且仍未被领取、或已处于 expired 的本人确认返回 `200 {status:"expired",summary}`；若另一标签页已抢占执行，则返回 `409 CONFIRMATION_IN_PROGRESS`。首次到期在同一事务内将确认标记为 `expired`、未领取的写工具标记为 `cancelled`、对应等待中的计划步骤改为 cancelled，并将等待确认的 run 收尾为 completed；随后发出工具完成、计划更新和运行完成 SSE。整个过期路径不执行写操作。confirm/cancel 在发现到期且本次成功收敛时返回 `410 CONFIRMATION_EXPIRED`，客户端必须重新生成预览；并发抢占仍按 `409 CONFIRMATION_IN_PROGRESS` 处理。

### 6.3 学习域 routers/presets.py graph.py tasks.py diagnostics.py profile.py
| 端点 | 说明 |
|------|------|
| GET /api/presets?data_type&scenario_id&goal&difficulty | 8 条预设路径；`PresetDTO{id,title,description,data_type,scenario_id,goal,difficulty,est_minutes,cap_ids,unit_ids,recommended_for}` |
| GET /api/presets/{id} | 详情+关联单元/能力 |
| POST /api/presets/{id}/start | 走确认门生成首个任务（action=task.create） |
| GET /api/graph/overview | 全图 `{nodes:[GraphNodeDTO],edges:[GraphEdgeDTO]}`（166 节点） |
| GET /api/graph/nodes?q&type&data_type&scenario_id | 搜索 |
| GET /api/graph/nodes/{id} | 详情：前置/关联资源/典型任务/证书 |
| GET /api/graph/subgraph?node_id&depth=2 | 局部子图（≤500ms） |
| GET /api/graph/pre-path?target_id&skip_mastered=1&user_id(本人) | PRE 补强路径，必须无环 |
| GET /api/tasks?status&source；POST /api/tasks | 列表/手动创建 |
| GET/PATCH /api/tasks/{id}；POST /api/tasks/{id}/archive | 状态机(PRD-06 §8.1) |
| POST /api/tasks/{id}/start | not_started→in_progress |
| POST /api/tasks/{id}/submit `{answers}` | 确定性评分 → `{attempt_id,score,feedback,mastery_preview:[{cap_id,scenario_id,old_score,new_score}]}`（不直接落掌握度） |
| POST /api/tasks/{id}/apply-mastery `{attempt_id}` | 学生确认后写 mastery + mastery_events |
| POST /api/diagnostics (multipart: file + data_type + scenario_id) | ≤20MB，内存解析不持久化 → `DiagnosticReportDTO` + `diagnostic_token`（内存缓存 30min） |
| POST /api/diagnostics/save-summary `{diagnostic_token}` | 确认门动作：存摘要+掌握度预览生效 |
| GET /api/diagnostics/summaries | 历史摘要 |
| GET /api/profile/mastery；GET /api/profile | 掌握度/个人中心聚合 |

`DiagnosticReportDTO{file_format,sample_count,precheck:{fields,warnings},errors:[{error_type,severity,user_value,expected,rule, citation?,cap_id,cap_name,suggestion}],severity_counts,weak_cap_ids,mastery_preview,plan:{weak_caps,pre_path,resources,tasks},notice}`（PRD-06 §9.3 最低结构）

### 6.4 RAG routers/rag_query.py + rag_admin.py（PRD-05 §4.3）
| 端点 | 说明 |
|------|------|
| POST /api/rag/query `{question,scenario_id?,data_type?,published_only=true}` | 学生端角色（`student` / `content_admin` / `system_admin`）可用；→ `RagAnswerDTO{answer,steps,notes,followups,citations:[CitationDTO],related_cap_ids,refused,notice}`；无召回/低于阈值→refused=true 不编造(AC6) |
| `CitationDTO{document_id,title,section_title,page_start,page_end,version,score}` | 学生端不显示 chunk_id/上传人(PRD-06 §4.5) |
| GET/POST /api/rag/documents；GET/PATCH/DELETE /api/rag/documents/{id} | 仅 `system_admin`；上传必填校验(PRD-03 §5.2)；已发布仅可归档不可物理删；未发布可删留审计 |
| POST /api/rag/documents/{id}/parse /chunk /index | 仅 `system_admin`；生成 rag_jobs（幂等 key），同步执行但保留状态机/重试语义 |
| POST /api/rag/documents/{id}/submit-review /publish /archive | 仅 `system_admin`；状态机迁移 + review_records + audit_logs；发布校验(PRD-06 §4.2：forbidden/缺来源/空切片/敏感信息阻止) |
| GET /api/rag/documents/{id}/chunks；GET/PATCH /api/rag/chunks/{id}；POST /api/rag/chunks/{id}/split；POST /api/rag/chunks/merge `{chunk_ids}` | 仅 `system_admin`；切片编辑器；保存后重建索引 |
| GET /api/rag/jobs?status；POST /api/rag/jobs/{id}/retry | 仅 `system_admin`；队列/重试从失败阶段继续 |
| POST /api/rag/search-test `{query,filters,top_k}` | 仅 `system_admin`；`{vector_results,reranked_results,diagnostics:{latency_ms,embedding_model,rerank_model,filters,prompt_template_version}}`；可存为评测用例 |
| GET/POST /api/rag/eval-cases；POST /api/rag/eval-runs；GET /api/rag/eval-runs/{id} | 仅 `system_admin`；指标：Recall@K/CitationAccuracy/Faithfulness/RefusalAccuracy/Latency |
| GET/POST/PATCH /api/source-ledgers | 仅 `system_admin`；台账；风险提示(过期/未授权/缺引用位置) |

召回规则（PRD-06 §4.4）：学生端仅 `status=published AND visibility=student AND license_status=authorized AND 未过期`；场景冲突降权并提示；多版本取最新已发布；未发布资料请求引用→拒绝。

### 6.5 教师端 routers/teacher.py（PRD-02）
| 端点 | 说明 |
|------|------|
| GET /api/teacher/dashboard | 班级概览/完成率/平均掌握度/薄弱 Top5/待办 |
| GET/POST /api/teacher/classes；GET /api/teacher/classes/{id}；POST /api/teacher/classes/{id}/invite | 仅自己班级；邀请码 |
| GET /api/teacher/classes/{id}/students?status&mastery_min&mastery_max | 完成率/掌握度/最近活跃 |
| GET/POST /api/teacher/tasks；POST /api/teacher/tasks/{id}/publish `{class_id,due_at,counts_toward_mastery}` | 发布前必须预览(任务体随 POST 提交)；≥1 能力节点+≥1 来源资料；发布→学生任务列表可见(source=teacher)；改已发布任务→version+1 新记录(parent_task_id) |
| GET /api/teacher/analytics?class_id&data_type&scenario_id&source&range | 热力图/趋势/高频错误/干预建议；学生<3 人提示样本过小 |
| GET /api/teacher/resources `?q&limit&offset` | 只读资料选择器：仅返回已发布、`visibility=student`、授权有效且未过期的资料，供教师任务附加；不复用 RAG 管理 API |

### 6.6 系统管理 routers/admin.py（仅 admin session）
| 端点 | 说明 |
|------|------|
| GET/POST/PUT/DELETE /api/admin/providers；POST /api/admin/providers/{id}/test；POST /api/admin/providers/{id}/set-role `{role}` | base_url 安全校验(NF9：拒 localhost/内网/元数据地址)；仅 enabled 且角色为 `primary/fallback/embedding/rerank` 的供应商可测试，`none` 或 disabled 不发起外网请求；按角色执行最小真实能力检查（primary/fallback=chat、embedding=嵌入、rerank=重排）。test 仅保存/返回 `ok,role,latency_ms,model,error,tested_at` 等安全字段，不保存 URL、请求头、API Key、测试提示词或供应商响应；API Key 仅录入时提交，永不回显 |
| GET/PATCH /api/admin/rag-settings | 参数修改写审计；返回完整 RagSettingsDTO |
| GET /api/admin/users?role&q；PATCH /api/admin/users/{id} `{role?,status?}`；POST /api/admin/users/{id}/reset-password | 权限变更写审计 |
| GET /api/admin/audit-logs?actor&action&target_type&from&to | 审计查询 |
| GET /api/admin/metrics | 运营指标(PRD-06 §13.1)：工具成功率/召回命中率/拒答率/任务转化率/预设启动率/诊断成功率/掌握度确认率/模型失败率 |

### 6.7 埋点 routers/events.py
POST /api/events `{events:[{name,props}]}` → 202。仅接受 §8 白名单事件名。

## 7. SSE 事件契约（PRD-05 §5，agent/events.py 常量）

`run.started` `message.delta{delta}` `plan.updated{steps:[{id,title,status}]}` `tool.call.requested{tool_call_id,tool,permission,args_summary}` `tool.call.completed{tool_call_id,tool,status,duration_ms,is_write,result}` `rag.retrieval.started` `rag.retrieval.completed{hit_count,latency_ms}` `citation.attached{citations}` `confirmation.required{confirmation}` `run.completed{summary}` `run.failed{error}` `run.usage{prompt_tokens?,completion_tokens?,model}`。
每个事件写 agent_events(seq 自增)，SSE 帧 `event: <type>\ndata: <json 含 seq>`，前端用 `after_seq` 重连续播。

## 8. 埋点事件白名单（v3.0 §16）

preset_clicked / goal_submitted / agent_plan_shown / rag_query_submitted / rag_retrieval_completed / citation_clicked / task_preview_created / task_created / diagnostic_uploaded / diagnostic_summary_saved / mastery_updated / rag_document_uploaded / rag_document_published / rag_eval_run_completed。属性按 v3.0 §16 表。

## 9. 工具契约（PRD-05 §6，tools/registry.py）

| 工具 | 权限 | 自动 | 实现要点 |
|------|------|------|----------|
| course.search | read | 是 | 检索 data/curriculum teaching-units.json（内存索引，按 data_type/scenario/cap 过滤） |
| graph.reason | read | 是 | graphx.reason：节点定位/PRE 路径/子图 |
| task.preview | read | 是 | 组装任务卡 DTO（不落库），埋点 task_preview_created |
| task.create | write | 否 | 确认后写 learning_tasks(source=agent/preset)，埋点 task_created |
| diagnostic.preview | read | 是 | 调 diagnosis.engine；原文件不持久化 |
| diagnostic.save_summary | write | 否 | 确认后写 diagnostic_summaries + 触发 mastery.update 预览 |
| mastery.update | write | 否 | 确认后写 mastery + mastery_events（clamp 0..1） |
| rag.search | read | 是 | rag.retriever；事件 rag.retrieval.* |
| rag.answer | read | 是 | 证据压缩+LLM/模板合成+引用校验；拒答策略 |
| rag.preview_upload | read | 是 | 仅 `system_admin`；预检：类型/大小/敏感信息检测(PRD-06 §4.3) |
| rag.create_document | write | 否 | 仅 `system_admin` 可经 Agent 建资料草稿 |
| rag.reindex_document / rag.publish_document / rag.archive_document / rag.save_eval_case | write | 否 | 仅 `system_admin`；全部确认门+审计 |

确认门过期：普通写 30min，删除/归档 10min；过期需重新生成预览（PRD-06 §6.4）。

## 10. Agent 编排规则（PRD-06 §6 + PRD-01 §3.4）

1. 意图识别（规则优先，可 LLM 辅助）：learn_goal / preset / diagnose / rag_question / task_convert / teacher_task / smalltalk。
2. 信息不足**每轮只追问一个**最关键问题（数据类型→场景→目标→文件来源工具，PRD-06 §6.2 话术表）。
3. 计划边界：纯问答≤3 步；任务转化≥[RAG 召回，图谱定位，任务卡生成]；诊断≥[格式校验，规则诊断，依据召回，补强路径]；预设≥[路径选择，任务创建，练习反馈]。
4. 场景切换：识别到他场景关键词只建议不自动切（PRD-06 §7.3）。
5. LLM 可用→流式合成；不可用→模板合成工具结果（不编造）；主模型失败切回退，回退也失败→仅展示工具结果。
6. 诊断只做解释，评分扣分永远来自确定性引擎（P0：诊断可信）。

## 11. 诊断引擎规则（diagnosis/，PRD-06 §9）

- 格式识别：扩展名+内容嗅探（TextGrid 头 `File type = "ooTextFile"`；COCO=json 含 images+annotations+categories；VOC=xml `<annotation>`；通用 JSON）。
- 校验链：格式可解析→字段齐全（缺字段不评分）→样本统计→规则引擎（场景规则库 data/scenarios + 通用规则：时长边界/重叠/空标注/类别合法性/IOU/边界溢出等）→错误归因 cap → RAG 召回规则依据（无命中则不给专业解释，PRD-06 §9.2）→补强计划（PRE 路径+资源+练习）。
- 规则库未覆盖：不扣分，notice 提示暂未覆盖。

## 12. 掌握度规则（mastery/service.py，PRD-06 §8.3/8.4）

- 通用练习→`scenario_id=''`；场景练习→CAP+SCN；诊断→确认后更新；教师任务→按 counts_toward_mastery。
- 更新公式：练习 `new = clamp(old + 0.15*score - 0.1*(1-score))`；诊断扣分按错误严重度(major −0.2, minor −0.05, 按 cap 聚合)；测评写入初始值。全部 clamp[0,1]，写 mastery_events 历史，重复提交按最新有效。

## 13. 种子数据（seed/loader.py，`python -m bhzd_py.seed.loader [--demo]`）

1. rag_settings 单行默认值；schools 默认校"标航职业学院"。
2. 初始系统管理员（BHZD_ADMIN_EMAIL/PASSWORD，默认 admin@bhzd.local / 启动日志打印一次）。
3. 图谱/教学单元/场景运行时从 data/ 加载（不入库）；启动时校验图谱可加载+PRE 无环。
4. 预设路径 8 条（presets.py，cap_ids 须存在于图谱，加载时校验告警）。
5. `--demo`：演示账号（student@demo.bhzd / teacher@demo.bhzd / admin@demo.bhzd，统一密码 Demo1234!）、1 个班级+学生入班、demo_docs 4 篇（客服语音标注规范/车载唤醒词标注指南/NER 标注入门规范/1+X 数据标注考试说明）走完整管线至 published+authorized、台账 4 条、评测用例 ≥8 条、示例学习任务与一条诊断摘要。

## 14. 前端信息架构与路由（PRD-01/02/03/04）

- 学生壳导航：Agent 指挥舱(/) 预设学习(/presets) 能力图谱(/graph) 学习任务(/tasks) 标注诊断(/diagnostics) 知识问答(/rag-qa) 个人中心(/profile)。
- 教师壳：工作台(/teacher) 班级管理(/teacher/classes) 任务发布(/teacher/tasks) 学情分析(/teacher/analytics)。教师不能进入学生端或 RAG 管理端。
- RAG 管理壳（仅 system_admin）：资料库(/rag-admin) 上传(/rag-admin/upload) 任务队列(/rag-admin/jobs) 来源台账(/rag-admin/ledgers) 召回测试(/rag-admin/search-test) 评测集(/rag-admin/eval-cases) 发布审核(/rag-admin/publish)。资料详情 /rag-admin/documents/:id（含切片编辑器入口 /rag-admin/documents/:id/chunks）。
- 系统管理壳（仅 system_admin）：模型供应商(/admin/providers) RAG 参数(/admin/rag-settings) 用户权限(/admin/users) 安全配置(/admin/security) 审计日志(/admin/audit-logs)。
- 守卫：未登录→/login；角色不足→403 页；学生端仅 `student` / `content_admin` / `system_admin`，教师访问学生端或其 API 必须拒绝；RAG 管理端与其 HTTP/Agent 管理能力仅 `system_admin`。
- 指挥舱要点：欢迎态=目标输入(占位文案"说说你想学什么，比如：我想学客服语音情感标注")+8 预设快捷卡+3 示例问题；右栏执行轨迹(工具名/状态/耗时/是否写操作，默认折叠)+引用来源+确认门+当前能力定位；嵌入工具卡两级展示"卡片+专注视图"(NF19)；状态机(空白/计划中/工具调用中/等待确认/完成/失败不暴露堆栈)。
- 图谱页配色：已掌握=绿实心，待加强=橙描边，初学=红描边（v3.0 §7.3.3）；搜索/类型筛选/视图模式(全图/局部/路径)/节点抽屉/PRE 路径面板(跳过已掌握)。
- 埋点：§8 事件在对应交互触发。

## 15. 角色权限矩阵（PRD-04 §5.1 + PRD-06 §3.3，deps.py 强制）

学生端 API：`student`、`content_admin`、`system_admin`；教师：仅 `teacher/*` 教学任务、班级和学情能力，不能访问学生端 API 或 RAG 管理；内容管理员：保留学生端与既有教师协作权限，但无 RAG 管理权限；系统管理员：学生端 + `rag-admin/*` + `admin/*`。RAG 管理由 `system_admin` 独占，服务端逐端点校验，教师数据按 class_teachers 隔离。

## 16. 测试计划

- server/tests（pytest）：auth 流程/权限矩阵/限流锁定；教师访问学生端 API 与 RAG HTTP/Agent 管理能力均为 403，`content_admin` / `system_admin` 保留学生端，RAG 仅 `system_admin`；password-key 与三条密码信封路径、明文拒绝和篡改信封安全失败；RAG 管线(上传→发布→召回→引用→拒答 AC4/5/6)；诊断四格式+边界(PRD-06 §14.3)；图谱 PRE 无环/子图性能；掌握度 clamp/冲突；确认门过期/取消与 SSE 终态；provider key 加密不回显+base_url 校验、按角色最小测试和 disabled/none 零外呼；审计写入；种子幂等。
- app/tests（vitest）：路由守卫 + 指挥舱欢迎态 8 入口 + 关键页渲染冒烟。
- tests/content、tests/graph 保持通过（data/ 不动）。
- tests/e2e 重写为单文件冒烟（登录→指挥舱→预设→任务预览确认），wave4 执行。

## 17. 实施波次与模块归属

- Wave1（地基，1 代理）：pyproject、config/db/security/audit/deps/errors、migrations 001-006、app.py(注册全部 router 占位)、seed 全部、main.py；验证：迁移跑通+seed(--demo)+/api/health。
- Wave2（后端 4 代理并行，文件互不重叠；router 模块名与 §2.1 一致，app.py 由集成阶段统一 include）：
  - B1 账号与系统域：routers/auth.py、routers/admin.py、routers/events.py、providers 协议适配器(沿用 4 协议，放 agent/providers.py)、telemetry.py + 对应 tests。
  - B2 RAG 域：rag/*、routers/rag_query.py、routers/rag_admin.py + tests。
  - B3 Agent 域：agent/*（不含 providers）、tools/*、routers/runs.py、routers/confirmations.py + tests。
  - B4 学习与教师域：graphx/*、mastery/*、diagnosis/*、routers/{presets,graph,tasks,diagnostics,profile,teacher}.py + tests。
- Wave3（前端）：F0 骨架(api/types+client+router+layouts+auth 页) → F1 指挥舱 / F2 学生其余页 / F3 教师端 / F4 RAG+系统管理端 并行。
- Wave4（集成）：app.py include 全部 router、全量 pytest/vitest/tsc build/e2e 冒烟、双端启动 curl 冒烟、demo 种子、文档收尾。
