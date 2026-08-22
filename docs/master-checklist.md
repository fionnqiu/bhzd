# 标航智导 · 全量改动与目标清单

**版本：** v1.1  
**创建日期：** 2026-08-15  
**整合来源：** tech-optimization-checklist / tech-concepts-evaluation / student-side-refactor-checklist / feature-simplification-checklist / admin-optimization-checklist  
**执行状态：** 已完成代码实现与自动化回归；本轮已完成本地浏览器视觉复核与隔离语料基线，真实 Provider 与正式学生试用仍待环境/授权验收

### 执行证据（2026-08-15）

- 后端全量：`cd server; uv run pytest -q` → **468 passed**（仅 Starlette/httpx 弃用警告）。
- 前端全量：`cd app; pnpm test:run` → **31 个测试文件 / 257 passed**。
- 前端门禁：`pnpm run typecheck`、`pnpm run lint`、`pnpm run build` 均通过；lint 为 0 errors / 51 个既有 warnings，build 仅有 chunk size 提示。
- 后端目标文件 Ruff：`uv run ruff check bhzd_py/tools/teacher_agent_tools.py bhzd_py/routers/teacher.py bhzd_py/routers/teacher_agent.py bhzd_py/routers/tasks.py` 通过；全仓库 Ruff 仍有旧测试文件的命名/未使用导入问题，未扩大本轮范围。
- 迁移验证：使用 `017_provider_protocol_grader.sql`、`018_task_learning_content.sql`、`019_query_rewrite_setting.sql`、`020_rag_sampling_settings.sql` 在临时库完成迁移、重跑幂等和历史数据兼容测试。
- 真实验证报告：`evidence/real-validation/2026-08-15/validation-report.md` 记录隔离 E2E 4 passed、桌面/移动视觉截图，以及 20 条评测用例的 Top-3/5/7/8 检索基线。
- 本轮本地教师回归：浏览器实际创建并发布 1 名学生任务副本；原件与副本的自动学习内容均进入 `done`，学生详情展示自动排队状态截图。

**证据边界：** 本清单中的自动化结果主要是离线/模拟 Provider 与组件契约；本轮新增的浏览器截图来自本地演示服务，语料结果来自隔离 SQLite 备份。未声称真实 Provider 连通、真实生产语料调优或正式学生试用已完成。

---

## 一、总体目标清单

### 1.1 产品目标

1. **学生端体验升级**
   - 预设学习页筛选简化为仅"数据类型"，移除学习目标与难度两个维度
   - 学习任务模式升级：操作步骤+学习资料 → 知识点（Agent生成，由浅到深）+ AI 评阅结构化练习题
   - 任务不再强制关联学习资源，知识获取统一由 RAG 问答页承载

2. **教学管理优化**
   - 教师端新增任务管理中心（列表+新建+编辑），发布页简化为手动+AI生成两种模式
   - 能力图谱"开始学习"通过 `generate_content=true` 标志异步触发知识点和题目生成

3. **系统管理现代化**
   - 删除讯飞两个 WebSocket 协议（xunfei_xingchen / xunfei_spark），新增 OpenAI Responses API
   - 修复供应商连接测试假阴性问题（`invalid_chat_response`）
   - RAG 管理功能并入系统管理端，保留 3 个活动入口；上传后自动完成解析/切片/索引/发布
   - RAG 参数配置页仅允许调整切片与召回参数，其中 `top_k`、`temperature`、`top_p` 可直接编辑；生成策略、Prompt 模板和发布审核均为系统内置逻辑
   - 新增 `grader` 供应商角色，专用于练习题异步 AI 评阅

4. **RAG 检索质量**
   - 引入查询改写（Query Rewriting）：短 query 扩写后再检索，提升召回准确率
   - Agent 编排迁移为 LangGraph 确定性状态图；只在知识问答中引入受限只读 ReAct 子图与查询时 GraphRAG 融合，不引入完整 LangChain Agent/Chain

### 1.2 技术目标

1. **零破坏性**：所有改动向后兼容，数据库迁移保留全量历史数据
2. **安全降级**：AI 评阅、查询改写等新功能异常时静默回退，不阻断主流程
3. **可配置化**：新功能通过数据库开关控制（如 `query_rewrite_enabled`），管理员可随时关闭
4. **协议统一**：provider 层统一为 3 个协议（chat_completions / anthropic_messages / responses）

---

## 二、改动总览速查表

| 编号 | 改动项 | 优先级 | 预估工时 | 依赖 |
|------|--------|--------|---------|------|
| P0-1 | 修复 `invalid_chat_response` 假阴性 | 🔴 P0 | 2h | 无 |
| P0-2 | 预设学习筛选简化（移除目标/难度） | 🔴 P0 | 1.5h | 无 |
| P0-3 | 删除讯飞协议 + 新增 Responses API | 🔴 P0 | 13h | P0-1之后 |
| P0-4 | 新增 grader 供应商角色 | 🔴 P0 | 4h | 与P0-3同迁移批次 |
| P0-5 | 移除学习任务资源关联 | 🔴 P0 | 1天 | 无 |
| P0-6 | 教师端任务管理页重组 | 🔴 P0 | 2-3天 | P0-5之后/可并行 |
| P0-7 | 学习任务 AI 评阅模式重构 | 🔴 P0 | 25h | P0-4之后 |
| P0-8 | 图谱节点任务同步优化 | 🔴 P0 | 2h | P0-7之后 |
| P0-9 | Advanced RAG 查询改写 | 🔴 P0 | 4h | 独立 |
| P1-1 | RAG管理端从9页精简为4页 | 🟡 P1 | 3-4天 | 独立 |
| P1-2 | RAG参数配置重构 | 🟡 P1 | 4h | 独立 |
| P2-1 | Token 计数优化 | ⚪ P2 | 2.5h | P0稳定后 |
| P2-2 | LLM 输出质量回归测试 | ⚪ P2 | 1-2天 | P0稳定后 |
| P2-3~7 | Chunking/top-k/Prompt/Embedding/temperature调优 | ⚪ P2 | 随迭代 | 随迭代 |
| P2-8 | 安全配置页增加运行时指标 | ⚪ P2 | 3h | 独立 |
| P2-9 | 管理端导航平铺优化 | ⚪ P2 | 1h | 独立 |
| P2-10 | 用户页批量操作+导出 | ⚪ P2 | 4h | 独立 |
| P2-11 | 审计日志行展开详情 | ⚪ P2 | 2h | 独立 |
| P0-10 | LangGraph 混合架构迁移（含受限 ReAct/查询时 GraphRAG） | ✅ 已完成 | 原生 StateGraph | 现有 Agent 编排器 |

> **P0 总计：约 40h（~1周）｜P1：约 28h（~3.5天）｜P2：随迭代按需**

---

## 三、P0 改动详情（按建议执行顺序）

---

### P0-1 · 修复 `invalid_chat_response` 假阴性

**预估工时：** 2h  **主要文件：** `server/bhzd_py/agent/providers.py`

#### 根本原因

`_first_text_delta()` 要求流中出现至少一个非空字符 delta，4种场景导致误报：

| 触发场景 | 说明 |
|---------|------|
| 推理模型（o3/o4-mini）| 首个 token 是思考内容，不在 `content` 字段出现 |
| 流格式轻微偏差 | 部分 API 网关 `choices[0].delta` 路径略有不同 |
| `max_tokens=1` 过小 | 少数模型在此限制下不产出任何文本 |
| 上游提前关闭流 | 网络层面流被提前关闭 |

#### 改动（方案A + 方案B 同时应用）

**方案A — 修改 `_first_text_delta()`（`providers.py`）**

```python
async def _first_text_delta(events: AsyncIterator[dict[str, Any]]) -> None:
    """
    接受第一个有 delta 键（含空串）即视为成功。
    修复原因：部分模型在 max_tokens=1 限制下返回空串 delta，
    原实现 delta.strip() 将其排除，导致整个流消耗完后抛 invalid_chat_response。
    done 事件也视为正常完成（某些协议只发 done 不发 delta）。
    """
    async with aclosing(events):
        async for event in events:
            delta = event.get("delta")
            if isinstance(delta, str):   # 有 delta 键（含空串）即通过
                return
            if event.get("done"):        # done 事件也算正常完成
                return
    raise ProviderError("invalid_chat_response")
```

**方案B — 提高探测 token 数（`providers.py`）**

```python
# 从 1 提高到 4，给模型更多输出空间
_PROVIDER_TEST_CHAT_MAX_TOKENS = 4
```

#### 验收标准

- [ ] 对支持 Responses API 的推理模型（o3/o4-mini）连接测试不再报假阴性（代码与模拟协议已覆盖；真实 Provider 待验收）
- [x] 对正常返回空 delta 的模型，测试报告 `ok`（`test_providers.py`）
- [x] 流中确实无任何内容时（模型服务异常），仍正确报 `invalid_chat_response`（`test_providers.py`）

---

### P0-2 · 预设学习筛选简化（移除目标 / 难度）

**预估工时：** 1.5h  **独立，无依赖**

#### 决策

只保留"数据类型"筛选。学习目标和难度由系统内部 `groupOf()` 分组计算，不作为显式筛选项暴露。`difficulty` 字段在数据库和 seed 里保留（内部分组逻辑仍需要它）。

#### 前端改动 — `app/src/pages/student/PresetsPage.tsx`

```typescript
// ① 删除常量
const GOAL_OPTIONS = [...]        // 整个删除
const DIFFICULTY_OPTIONS = [...]  // 整个删除

// ② 删除 matchGoal() 辅助函数（整个删除）

// ③ filters 状态简化
// 改前：{ dataType: "", goal: "", difficulty: "" }
const [filters, setFilters] = useState({ dataType: "" });

// ④ resetFilters 简化
const resetFilters = () => setFilters({ dataType: "" });

// ⑤ UI 筛选区从3列变1列 — 删除以下两行 Select
<Select value={filters.goal} ... />        // 学习目标 Select — 删除
<Select value={filters.difficulty} ... />  // 难度 Select — 删除
// 保留：
<Select value={filters.dataType} ... />    // 数据类型 Select — 保留
```

#### 后端改动 — `server/bhzd_py/routers/presets.py`

```python
# GET /api/presets 删除 difficulty / goal 查询参数及对应过滤逻辑
@router.get("/api/presets")
def list_presets(
    data_type: str | None = None,
    # goal: str | None = None,       # 删除
    # difficulty: int | None = None, # 删除
    ...
):
```

#### 保持不变

- `api/types.ts` 的 `Preset.difficulty` 字段保留（`groupOf()` 仍需使用）
- seed 数据里的 `difficulty` 字段保留
- 分组逻辑（新手/岗位胜任/证书备考/薄弱补强）完全不变

#### 验收标准

- [x] 预设学习页只有"数据类型"一个筛选项
- [x] 4个分组仍正常显示
- [x] 删除 goal/difficulty 参数后后端接口无报错（旧参数被兼容忽略）
- [x] 现有预设数据展示不受影响

---

### P0-3 · 删除讯飞两个协议 + 新增 Responses API

**预估工时：** 13h（约2天）  **依赖：P0-1 完成后执行**  
**注意：P0-3 与 P0-4 合并为一次数据库迁移（避免重建 provider_configs 表两次）**

#### 删除范围（`server/bhzd_py/agent/providers.py`）

```python
# 1. 协议常量更新
_PROTOCOLS = ("chat_completions", "anthropic_messages", "responses")
# 删除: "xunfei_spark", "xunfei_xingchen"

# 2. 删除讯飞专用代码（6个函数/常量全部删除）
_SPARK_MODEL_ROUTES: dict[str, tuple[str, str]] = {...}  # 整个字典删除
def _signed_ws_url(...)    # 讯飞 WebSocket 签名 URL 生成
def _spark_route(...)      # 星火模型路由
def _xunfei_frame(...)     # 讯飞帧构造
async def _xunfei_stream(...)  # 讯飞 WebSocket 流式实现

# 3. _PROTOCOL_MEDIA_INPUTS 删除两行
"xunfei_spark": frozenset(),
"xunfei_xingchen": frozenset(),

# 4. discover_models() 删除讯飞分支
if protocol in ("xunfei_spark", "xunfei_xingchen"):
    return {"supported": False, "models": []}   # 整块删除

# 5. _complete_strict() / _stream_strict() / _smoke_chat() 删除 xunfei 分支
# 6. 如 websockets 仅讯飞使用，评估是否从 requirements.txt 移除
```

#### 前端/路由改动

```python
# server/bhzd_py/routers/admin.py
_PROTOCOLS = ("chat_completions", "anthropic_messages", "responses")
# 删除: "xunfei_xingchen", "xunfei_spark"
```

```typescript
// app/src/pages/admin/adminShared.ts（或 ProvidersPage.tsx）
export const PROTOCOL_OPTIONS = [
  { value: "chat_completions",   label: "Chat Completions" },
  { value: "anthropic_messages", label: "Anthropic Messages" },
  { value: "responses",          label: "Responses" },   // 新增
  // 删除: xunfei_xingchen / xunfei_spark
];
```

#### 新增 Responses API 实现（`providers.py`）

Responses API（OpenAI 2025新一代接口）与 Chat Completions 差异：

| 特性 | Chat Completions | Responses API |
|------|-----------------|---------------|
| 端点 | `POST /v1/chat/completions` | `POST /v1/responses` |
| 请求体 | `{model, messages, stream}` | `{model, input, stream}` |
| 流事件类型 | `choices[0].delta.content` | `response.output_text.delta` |
| 完成标志 | `data: [DONE]` | `response.completed` |

```python
def _responses_body(row, messages, *, stream: bool, max_tokens_override=None) -> dict:
    """
    Responses API 使用 input 字段而非 messages；
    system 消息合并为顶层 instructions 字段。
    Why: Responses API 是 OpenAI 新一代接口，结构与 Chat Completions 不同，
    需要独立的请求体构造函数。
    """
    extra = _extra(row)
    system_parts = [
        _text_content(m.get("content", ""))
        for m in messages if m.get("role") == "system"
    ]
    chat = [m for m in messages if m.get("role") != "system"]
    body = {
        "model": row["model"],
        "input": [
            {"role": m.get("role", "user"),
             "content": _text_content(m.get("content", ""))}
            for m in chat
        ],
        "stream": stream,
    }
    if system_parts:
        body["instructions"] = "\n".join(p for p in system_parts if p)
    if max_tokens_override is not None:
        body["max_output_tokens"] = max_tokens_override
    elif "max_tokens" in extra:
        body["max_output_tokens"] = extra["max_tokens"]
    if "temperature" in extra:
        body["temperature"] = extra["temperature"]
    return body

async def _responses_stream(client, row, api_key, messages, *, max_tokens_override=None):
    """
    Responses API SSE 流：response.output_text.delta → 文本增量，
    response.completed → 结束事件（含 usage）。
    """
    async with client.stream(
        "POST", f"{row['base_url'].rstrip('/')}/responses",
        headers=_cc_headers(row, api_key),   # 复用 Bearer 认证头
        json=_responses_body(
            row, messages, stream=True,
            max_tokens_override=max_tokens_override
        ),
    ) as resp:
        _raise_for_status(resp)
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: "):].strip()
            if not payload or payload == "[DONE]":
                continue
            chunk = json.loads(payload)
            event_type = chunk.get("type", "")
            if event_type == "response.output_text.delta":
                delta = chunk.get("delta", "")
                if delta:
                    yield {"delta": str(delta)}
            elif event_type == "response.completed":
                usage_raw = (chunk.get("response") or {}).get("usage") or {}
                usage = _normalize_usage({
                    "prompt_tokens": usage_raw.get("input_tokens"),
                    "completion_tokens": usage_raw.get("output_tokens"),
                })
                if usage:
                    yield {"usage": usage}
                break
```

**模型发现：** Responses 协议复用 `GET /v1/models`（格式与 chat_completions 一致）。

**嵌入支持：** Responses API 无 embeddings 端点，嵌入仅支持 `chat_completions` 协议。

#### 数据库迁移（P0-3 + P0-4 合并为一次）

> **重要：** P0-3 和 P0-4 均需重建 `provider_configs` 表以修改 CHECK 约束，必须合并为单个迁移文件，避免重建两次。

**文件：** `server/bhzd_py/migrations/017_provider_protocol_grader.sql`

```sql
-- 迁移：删除讯飞协议 + 新增 responses 协议 + 新增 grader 角色
-- 合并 P0-3 和 P0-4，避免对同一张表重建两次

-- Step 1：迁移现有讯飞配置为 chat_completions + 禁用
UPDATE provider_configs
SET protocol = 'chat_completions', enabled = 0, updated_at = datetime('now')
WHERE protocol IN ('xunfei_spark', 'xunfei_xingchen');

-- Step 2：重建 provider_configs 表（更新两处 CHECK 约束）
CREATE TABLE provider_configs_new (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  protocol TEXT NOT NULL CHECK (
    protocol IN ('chat_completions', 'anthropic_messages', 'responses')
  ),
  base_url TEXT NOT NULL,
  model TEXT NOT NULL,
  api_key_encrypted TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'none' CHECK (
    role IN ('primary', 'fallback', 'embedding', 'rerank', 'grader', 'none')
  ),
  enabled INTEGER NOT NULL DEFAULT 1,
  timeout_seconds REAL NOT NULL DEFAULT 30,
  extra_json TEXT NOT NULL DEFAULT '{}',
  last_test_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
INSERT INTO provider_configs_new SELECT * FROM provider_configs;
DROP TABLE provider_configs;
ALTER TABLE provider_configs_new RENAME TO provider_configs;
```

#### 工作量明细

| 子任务 | 工时 |
|--------|------|
| 删除讯飞协议（providers.py） | 3h |
| 新增 Responses 协议实现（providers.py） | 4h |
| admin.py / adminShared.ts / ProvidersPage.tsx 同步 | 1h |
| 数据库迁移脚本 | 2h |
| 单元测试更新 | 3h |
| **合计** | **13h** |

#### 验收标准

- [x] 管理端供应商配置"协议"下拉不再显示讯飞两个选项
- [x] 新增 Responses 协议选项，可成功配置并测试连接（模拟适配器契约；真实 Provider 待验收）
- [x] 原讯飞配置自动降级为 `chat_completions + disabled`，数据不丢失（017 迁移测试）
- [ ] Responses API 流式输出可正常渲染到学生端对话框（适配器 SSE 已测试；真实 Provider/浏览器待验收）
- [x] `_embed_strict` 对 `responses` 协议正确返回 `embedding_not_supported`

---

### P0-4 · 新增 `grader` 供应商角色

**预估工时：** 4h（含迁移，与 P0-3 合并迁移脚本）  
**主要文件：** `providers.py` / `admin.py` / `adminShared.ts`

#### 背景

P0-7（学习任务 AI 评阅）需要一个专用 provider 角色来路由评阅请求。当前角色只有 `primary / fallback / embedding / rerank / none`，新增 `grader` 角色使评阅模型与教学对话模型解耦。

#### 后端改动

```python
# providers.py — 角色常量更新
_ROLES = ("primary", "fallback", "embedding", "rerank", "grader", "none")

# 新增：按角色获取 provider 的辅助函数
async def get_provider_by_role(role: str) -> dict | None:
    """
    按角色查找首个 enabled provider。
    grader 角色找不到时回退到 primary 角色（降级策略）。
    Why: 允许管理员指定专用评阅模型，未配置时自动使用主模型降级。
    """
    row = _db_get_provider_by_role(role)
    if row is None and role == "grader":
        row = _db_get_provider_by_role("primary")   # 静默降级
    return row
```

#### 前端改动

```typescript
// adminShared.ts — 角色下拉新增 grader
export const ROLE_OPTIONS = [
  { value: "primary",   label: "主模型" },
  { value: "fallback",  label: "备用模型" },
  { value: "embedding", label: "嵌入模型" },
  { value: "rerank",    label: "重排序模型" },
  { value: "grader",    label: "评阅模型" },   // 新增
  { value: "none",      label: "无角色" },
];
```

#### 数据库迁移

已合并至 P0-3 的 `017_provider_protocol_grader.sql`（见上；既有 013-016 已占用，不能覆盖）。

#### P0-4 验收标准

- [x] 管理端供应商配置"角色"可选 `grader`
- [x] `get_provider_by_role("grader")` 未配置时自动回退到 `primary`
- [x] 迁移后现有数据 role 字段不变（均为原有值）

---

### P0-5 · 移除学习任务资源关联

**预估工时：** 1天（独立，无依赖）  
**主要文件：** `tasks.py` / `teacher.py` / `TaskDetailPage.tsx` / `TaskPublishPage.tsx` / `types.ts`

#### 决策背景

任务不再强制关联学习资源，学习材料由 RAG 问答页承载。保留图谱参考资源（`graph_resources`，只读）和能力节点关联（`cap_ids`）。数据库 `resources_json` 列保留但新建任务写入空数组。

#### Phase 1 — 后端改动

**`server/bhzd_py/routers/tasks.py`**

```python
class CreateTaskRequest(BaseModel):
    # resources: list[dict] | None = None  # 删除此字段
    cap_ids: list[str]
    # ...其他字段不变

# 删除 RESOURCES_REQUIRED 校验块：
# if not body.resources:
#     raise ApiError(400, "RESOURCES_REQUIRED", "至少需要关联一个来源资料")

# 创建/更新任务时 resources_json 写入空数组而非 body.resources
resources_json = "[]"   # 固定值
```

**`server/bhzd_py/tools/task_tools.py`**（Agent 工具）

```python
# 删除 resources 参数传递（任务草稿生成不再包含 resources 字段）
```

**`server/bhzd_py/routers/teacher.py` / `teacher_agent.py`**

```python
# 删除 resources 字段及 RESOURCES_REQUIRED 错误码引用
```

#### Phase 2 — 前端改动

**`app/src/pages/student/TaskDetailPage.tsx`**

```tsx
// 删除"学习材料"区块（约562-580行）
{detail.resources.length > 0 ? (
  <ul>{ detail.resources.map(...CitationCard...) }</ul>
) : (
  <EmptyState hint="该任务暂未关联已发布的教学资料..." />
)}
// ↑ 整个条件渲染块删除

// 保留（图谱参考资源，约548-557行）
{detail.linked.graph_resources.length > 0 && (
  <div>
    <span>图谱参考资源</span>
    {detail.linked.graph_resources.map((r) => <Tag key={r.id}>{r.name}</Tag>)}
  </div>
)}
```

**`app/src/pages/teacher/TaskPublishPage.tsx`**

```tsx
// 删除 ResourceRow 接口（整个删除）
interface ResourceRow { type: string; title: string; refId?: string; ... }

// FormState 中删除 resources 字段
// 删除资源管理区块（添加/删除资源的 UI）
// 删除 API 调用中的 resources 参数
```

**`app/src/api/types.ts`**

```typescript
export interface LearningTask {
  // resources: TaskResource[];  // 删除或保留为可选兼容字段
}
```

#### Phase 3 — 数据库

```sql
-- 可选：清理现有 resources_json 数据（不删列）
-- UPDATE learning_tasks SET resources_json = '[]';
-- 新建任务自动写入 '[]'，历史数据按需清理
```

#### 验收标准

- [x] 学生端任务详情页无"学习材料"区块，图谱参考资源正常显示
- [x] 教师端发布任务无资源选择区块，创建/保存任务不再校验资源
- [x] 现有已关联资源的历史任务不报错（`resources_json` 仍存在，前端不渲染即可）
- [x] Agent 工具 `create_task` / `update_task` 不再传递 `resources` 参数

---

### P0-6 · 教师端任务管理页重组

**预估工时：** 2-3天（建议与 P0-5 并行，P0-5完成后整合）  
**主要文件：** 新增 `TasksManagePage.tsx` / 修改 `TaskPublishPage.tsx` / 修改 `router.tsx` / 修改 `TeacherLayout.tsx`

#### 新架构

```
/teacher/tasks          → TasksManagePage（任务列表中心）
/teacher/tasks/new      → TaskPublishPage（新建任务，精简版）
/teacher/tasks/:id      → TaskPublishPage（编辑任务，精简版）
```

#### Phase 1 — 新增 `TasksManagePage.tsx`

**文件：** `app/src/pages/teacher/TasksManagePage.tsx`（新建）

```tsx
/**
 * 教师任务管理中心（/teacher/tasks）。
 * 展示教师所有任务（草稿 + 已发布），提供新建入口和快捷操作。
 *
 * Why: 原架构只有发布入口，无任务列表/管理视图；
 * 发布页 4 个来源 Tab 增加认知负担，重组为列表+详情模式更清晰。
 */
const columns: Column<TeacherTask>[] = [
  { key: "title",          label: "任务标题",   render: (v) => v ?? "未命名任务" },
  { key: "data_type",      label: "数据类型",   render: dataTypeLabel },
  { key: "published_count",label: "发布班级数" },
  { key: "status",         label: "状态",       render: (v) => <StatusBadge status={v} /> },
  { key: "created_at",     label: "创建时间",   render: fmtDateTime },
];

// 主页面：任务列表 + Tab 筛选（草稿/已发布/全部）+ 新建按钮
export default function TasksManagePage() {
  // 列表、分页、状态筛选、跳转编辑...
}
```

#### Phase 2 — 路由修改（`app/src/app/router.tsx` 或 `App.tsx`）

```tsx
// 改前
{ path: "tasks", element: <TaskPublishPage /> },

// 改后
{ path: "tasks",         element: <TasksManagePage /> },
{ path: "tasks/new",     element: <TaskPublishPage /> },
{ path: "tasks/:taskId", element: <TaskPublishPage /> },
```

#### Phase 3 — 精简 `TaskPublishPage.tsx`

```tsx
// 删除 3 个来源 Tab（只保留手动输入 + AI生成）
// 改前（4个Tab）：type SourceTab = "manual" | "rag" | "preset" | "history"
// 改后（1个模式）：
type SourceTab = "manual";  // rag/preset/history Tab 整体删除

// 删除对应 Tab 内容区块：
// ① "已发布资料" Tab（资料搜索区块，约940-980行）— 整块删除
// ② "预设模板" Tab 内容 — 整块删除
// ③ "历史任务" Tab 内容（约1000-1020行）— 整块删除

// 更新页面标题（新建 vs. 编辑）
const isNew = !taskIdFromParams;
const pageTitle = isNew ? "新建教学任务" : "编辑教学任务";

// 新增面包屑（返回任务管理）
<PageHeader
  title={pageTitle}
  breadcrumb={[
    { label: "任务管理", href: "/teacher/tasks" },
    { label: pageTitle },
  ]}
/>
```

#### Phase 4 — 导航菜单（`app/src/layouts/TeacherLayout.tsx`）

```tsx
{ path: "/teacher/tasks", label: "任务管理", icon: <ClipboardList /> }
// 原来"发布任务"→ 改为"任务管理"
```

#### Phase 5 — 后端支持

```python
# 确认 GET /api/teacher/tasks 支持返回草稿+已发布（status=all）
# teacher.py list_teacher_tasks() 如果只返回已发布，需补充草稿支持
```

#### P0-6 验收标准

- [x] `/teacher/tasks` 显示任务列表（草稿/已发布可筛选）
- [x] "新建任务"跳转精简版发布页（只有手动输入+AI生成）
- [x] 发布页有"返回任务管理"面包屑
- [x] 点击任务行可跳转编辑模式 `/teacher/tasks/:id`
- [x] 3个来源Tab（已发布资料/预设模板/历史任务）不再出现

---

### P0-7 · 学习任务 AI 评阅模式重构

**预估工时：** 25h（约3天）  **依赖：P0-4 完成后执行**  
**核心变化：** 任务从"操作步骤+学习资料"升级为"知识点（AI生成）+ AI 评阅练习题"

#### Phase 1 — 数据库迁移

**文件：** `server/bhzd_py/migrations/018_task_learning_content.sql`

```sql
-- 知识点表
CREATE TABLE IF NOT EXISTS task_knowledge_points (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES learning_tasks(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  content TEXT NOT NULL,      -- 知识点内容（Markdown）
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 练习题表
CREATE TABLE IF NOT EXISTS task_exercises (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES learning_tasks(id) ON DELETE CASCADE,
  question TEXT NOT NULL,
  type TEXT NOT NULL DEFAULT 'open_ended',  -- open_ended / multiple_choice
  options_json TEXT,          -- 选择题选项（null for open_ended）
  reference_answer TEXT,      -- 参考答案（供评阅使用）
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 学生答题记录表
CREATE TABLE IF NOT EXISTS task_exercise_submissions (
  id TEXT PRIMARY KEY,
  exercise_id TEXT NOT NULL REFERENCES task_exercises(id) ON DELETE CASCADE,
  student_id TEXT NOT NULL,
  answer TEXT NOT NULL,
  grade_status TEXT NOT NULL DEFAULT 'pending',  -- pending/grading/done/failed
  score INTEGER,              -- 0-100
  feedback TEXT,              -- AI 评阅反馈（Markdown）
  graded_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- learning_tasks 表扩展
ALTER TABLE learning_tasks ADD COLUMN content_status TEXT NOT NULL DEFAULT 'none';
-- none=无内容 / generating=生成中 / done=已生成 / failed=生成失败
ALTER TABLE learning_tasks ADD COLUMN content_generated_at TEXT;
```

#### Phase 2 — 后端 API

**文件：** `server/bhzd_py/routers/tasks.py`

```python
# 新增知识点/练习题的 CRUD 接口
# GET  /api/tasks/{task_id}/knowledge-points  → 获取知识点列表
# POST /api/tasks/{task_id}/knowledge-points  → 新增知识点（教师/Agent）
# GET  /api/tasks/{task_id}/exercises         → 获取练习题列表
# POST /api/tasks/{task_id}/exercises         → 新增练习题（教师/Agent）

# 新增学生答题接口
# POST /api/tasks/{task_id}/exercises/{ex_id}/submit  → 提交答案（触发异步评阅）

# 新增异步评阅入口（内部）
# POST /api/internal/grade-submission           → 由 submit 异步触发
```

**文件：** `server/bhzd_py/routers/tasks.py` — 异步评阅流程

```python
async def _grade_submission_async(submission_id: str) -> None:
    """
    异步 AI 评阅：取 grader provider → 调用 LLM → 写 score + feedback。
    Why: 评阅可能耗时3-5s，不阻塞学生提交响应；
    失败时将 grade_status 设为 'failed'，前端显示"评阅暂不可用"。
    """
    sub = _db_get_submission(submission_id)
    exercise = _db_get_exercise(sub["exercise_id"])
    provider = await get_provider_by_role("grader")  # P0-4 新增的接口

    prompt = _build_grading_prompt(
        question=exercise["question"],
        reference=exercise["reference_answer"],
        student_answer=sub["answer"],
    )
    try:
        response = await complete(prompt, provider=provider, max_tokens=300)
        score, feedback = _parse_grading_response(response)
        _db_update_submission(
            submission_id,
            grade_status="done", score=score,
            feedback=feedback, graded_at=datetime.utcnow().isoformat()
        )
    except Exception:
        # 评阅失败：静默降级，前端显示"AI评阅暂不可用，请稍后重试"
        _db_update_submission(submission_id, grade_status="failed")
```

**文件：** `server/bhzd_py/tools/task_tools.py` — Agent 生成内容工具

```python
# 新增 generate_task_content 工具（供 Agent 调用）
async def generate_task_content(task_id: str) -> dict:
    """
    为任务生成知识点和练习题（任务创建、图谱开始学习和教师发布后自动入队）。
    Why: 知识点和练习题由 LLM 根据任务的 cap_ids（能力节点）生成，
    生成完毕后更新 content_status = 'done'；学生只在失败时需要显式重试。
    """
    task = _db_get_task(task_id)
    cap_nodes = _db_get_cap_nodes(task["cap_ids"])

    # 生成知识点
    knowledge_prompt = _build_knowledge_prompt(task, cap_nodes)
    knowledge_response = await complete(knowledge_prompt, max_tokens=2000)
    knowledge_points = _parse_knowledge_points(knowledge_response)

    # 生成练习题
    exercise_prompt = _build_exercise_prompt(task, knowledge_points)
    exercise_response = await complete(exercise_prompt, max_tokens=1500)
    exercises = _parse_exercises(exercise_response)

    # 持久化
    _db_save_knowledge_points(task_id, knowledge_points)
    _db_save_exercises(task_id, exercises)
    _db_update_task(task_id, content_status="done",
                    content_generated_at=datetime.utcnow().isoformat())
    return {"knowledge_points": len(knowledge_points), "exercises": len(exercises)}
```

#### Phase 3 — 前端改动

**`app/src/pages/student/TaskDetailPage.tsx`**

```tsx
// 任务详情页新增两个 Tab：知识点 / 练习
// Tab 1: 知识点（从浅到深展示，按 sort_order 排序）
// Tab 2: 练习题（逐题作答，提交后轮询评阅结果）

// 内容生成状态展示：
{task.content_status === 'generating' && (
  <div className="flex items-center gap-2 text-sm text-slate-500">
    <Spinner size="sm" />
    <span>AI 正在为你生成学习内容，请稍候…</span>
  </div>
)}
{task.content_status === 'failed' && (
  <Button onClick={handleGenerateContent}>重试生成</Button>
)}

// 练习题评阅结果展示：
{submission.grade_status === 'done' && (
  <div>
    <span>得分：{submission.score}/100</span>
    <Markdown>{submission.feedback}</Markdown>
  </div>
)}
{submission.grade_status === 'failed' && (
  <span className="text-amber-600">AI评阅暂不可用，请稍后重试</span>
)}
```

#### P0-7 验收标准

- [x] 数据库迁移通过，3张新表正确创建
- [x] 学生端任务详情的学习内容只保留"知识点"板块，AI 练习题、提交与评阅统一位于独立"练习区"
- [x] 新任务创建、教师发布学生副本与历史 `content_status=none` 任务详情读取均自动入队；学生端仅显示排队/生成状态，失败时才提供重试
- [x] 学生提交答案后页面轮询，评阅完成后自动显示得分和反馈（组件实现；离线提交/评阅状态测试通过）
- [x] 评阅失败时显示"AI评阅暂不可用"，不影响其他流程
- [x] `grader` provider 未配置时自动回退到 `primary` provider（P0-4的降级策略）

---

### P0-8 · 图谱节点"开始学习"同步优化

**预估工时：** 2h  **依赖：P0-7 完成后执行**  
**主要文件：** `app/src/pages/student/GraphPage.tsx` / `server/bhzd_py/routers/tasks.py`

#### 当前问题

图谱节点"开始学习"需要在快速跳转的同时为新建或无内容任务自动入队内容生成。`generate_content=true` 仅保留给失败任务的显式重试兼容，不能作为学生获取学习内容的前置操作。

#### 改动

**前端 `GraphPage.tsx`**

```tsx
// "开始学习"按钮创建/复用任务；后端会自动将 none 状态内容入队。
const handleStartLearning = (nodeId: string) => {
  // 保留这个旧标志不会改变新任务自动入队的行为。
  api.post(`/api/tasks/start-learning`, {
    cap_node_id: nodeId,
    generate_content: true,
  }).then(({ task_id }) => {
    navigate(`/student/tasks/${task_id}`);
  });
};
```

**后端 `tasks.py`**

```python
# POST /api/tasks/start-learning
async def start_learning(body: StartLearningRequest):
    """
    找到或创建节点对应的学习任务。
    新建或无内容任务自动异步触发知识点+练习题生成。
    Why: 解耦"找到任务"和"生成内容"，让跳转响应快速返回，
    并避免学生再点击一次生成按钮。
    """
    task = _get_or_create_task_for_node(body.cap_node_id)
    if task["content_status"] == "none" or (
        body.generate_content and task["content_status"] == "failed"
    ):
        # 队列函数负责标记 generating 并提交；请求不等待 worker 完成
        queue_task_content(conn, task["id"], force=task["content_status"] == "failed")
    return {"task_id": task["id"]}
```

#### P0-8 验收标准

- [x] 图谱节点"开始学习"点击后快速跳转（不等待内容生成完成）
- [x] 跳转到任务详情后，页面显示"正在生成内容"加载状态
- [x] 内容生成完成后，知识点和练习题自动出现（前端轮询）

---

#### P0-9 背景

当前 `retrieve()` 直接用原始 query 检索，短输入效果有限。改写后召回率明显提升，失败时静默回退，风险极低。

#### Step 1 — 添加 `_rewrite_query()` 函数（`retriever.py`）

```python
async def _rewrite_query(query: str, data_type: str | None = None) -> str:
    """
    对短 query（<15字）扩写为更完整的检索串。
    Why: 学生常输入"怎么标注情感"等简短问题，LLM 扩写为
    "情感标注规则 标签类别 正负例判定标准"后，向量召回准确率显著提升。
    失败时静默回退原始 query，与现有离线降级模式一致。
    输出 >200 字符时也回退（防止 LLM 输出过多噪音）。
    """
    prompt = (
        f"请将以下简短的数据标注学习问题扩写为更完整的检索查询，"
        f"保留原意，补充相关专业术语和上下文，输出一行，不要解释：\n\n"
        f"原始查询：{query}\n数据类型：{data_type or '通用'}\n\n扩写查询："
    )
    try:
        result = await complete(prompt, max_tokens=100)
        return result.strip() if result and len(result) < 200 else query
    except Exception:
        return query   # 任何失败均静默回退
```

#### Step 2 — 修改 `retrieve()` 入口（`retriever.py`）

```python
async def retrieve(query: str, ...) -> RetrievalResult:
    # 短 query 改写：仅在开关开启且查询较短时触发，失败时静默回退原始 query
    effective_query = query
    if settings.query_rewrite_enabled and len(query) < 15:
        effective_query = await _rewrite_query(
            query, filters.data_type if filters else None
        )
    # 原有检索逻辑使用 effective_query（query 保留用于日志）
    ...
```

#### Step 3 — 数据库配置（迁移文件）

```sql
-- migrations/019_query_rewrite_setting.sql
ALTER TABLE rag_settings ADD COLUMN query_rewrite_enabled INTEGER NOT NULL DEFAULT 0;
-- 默认 False，完全向后兼容
```

#### Step 4 — `RagSettings` 模型更新

```python
class RagSettings(BaseModel):
    query_rewrite_enabled: bool = False  # 新增字段，默认关闭
    # ...其他字段不变
```

#### Step 5 — 管理端 UI 开关（可延后至 P1）

```tsx
// app/src/pages/admin/RagSettingsPage.tsx — 在召回参数区块增加
<Field label="查询改写" hint="对少于15字的短查询，自动扩写后再检索（需LLM可用）">
  <Toggle checked={form.query_rewrite_enabled} onChange={...} />
</Field>
```

#### P0-9 验收标准

- [x] `query_rewrite_enabled` 默认 `False`，现有行为完全不变
- [x] 开关开启后，`len(query) < 15` 的查询经过改写后进入检索
- [x] LLM 调用失败时 `retrieve()` 继续正常执行（使用原始 query）
- [x] 单元测试：开关关闭时不调用 LLM，开关开启+异常时正确回退

---

## 四、P1 改动详情

---

### P1-1 · RAG 管理功能并入系统管理端

**预估工时：** 3-4天（独立，无依赖）

#### 精简对照表

| 原工作流（9个） | 当前或历史地址 | 精简后归属 |
|------------|--------|---------|
| RAG 资料库 | `/admin/rag` | ✅ 并入系统管理（重命名"资料库"） |
| 资料上传 | `/admin/rag/upload` | ✅ 并入系统管理（从资料库页面也可访问） |
| 资料详情 | `/admin/rag/documents/:id` | ✅ 并入系统管理（资料元数据+切片预览） |
| 解析任务 | `/rag-admin/jobs` | ❌ 删除 → 合并到知识库列表 |
| 切片编辑器 | `/rag-admin/documents/:id/chunks` | ❌ 删除 → 降级为只读切片预览 |
| 来源台账 | `/rag-admin/ledgers` | ❌ 删除活动页面；历史字段仅后端兼容 |
| 召回测试台 | `/admin/rag/search-test` | ✅ 并入系统管理（增加已保存用例Tab） |
| 召回评测集 | `/rag-admin/eval-cases` | ❌ 删除 → 合并到召回测试台 |
| 发布审核 | `/rag-admin/publish` | ❌ 删除活动页面；旧链接仅兼容重定向 |

#### 非活动组件

```
app/src/pages/rag/LedgersPage.tsx       — 来源台账历史组件（不挂载生产路由）
app/src/pages/rag/EvalCasesPage.tsx     — 召回评测集历史组件（核心用例能力已并入召回测试）
app/src/pages/rag/JobsPage.tsx          — 解析任务历史组件（状态与重试已并入资料库）
app/src/pages/rag/ChunkEditorPage.tsx   — 切片编辑历史组件（生产详情只提供只读预览）
app/src/pages/rag/PublishReviewPage.tsx — 发布审核历史组件（生产上传流程自动发布）
```

#### 上传处理 — 系统内置自动管线

```tsx
// UploadPage.tsx — 上传成功后由系统自动解析、切片、索引并发布到学生召回范围。
// 页面不提供送审/发布按钮，也不创建新的来源台账；旧台账字段仅用于历史数据兼容。

// UploadPage.tsx — 仅填写资料自身的来源与授权元数据，不展示台账配置。
```

#### 合并2 — 召回评测集 → 召回测试台 Tab

```tsx
// SearchTestPage.tsx — 增加两个 Tab
<Tabs>
  <Tab label="测试台">
    {/* 原有测试台内容 */}
    <Button onClick={saveAsCase}>保存为测试用例</Button>
  </Tab>
  <Tab label="已保存用例">
    {/* EvalCasesPage 的用例列表迁移至此 */}
    {cases.map(c => (
      <CaseRow key={c.id} onLoad={() => loadCase(c)} />  // 点击加载到测试台
    ))}
  </Tab>
</Tabs>
```

#### 合并3 — 解析任务 → 知识库列表处理状态列

```tsx
// DocumentsPage.tsx — DataTable 增加处理状态列
const columns = [
  { key: "title", label: "资料名称" },
  { key: "status", label: "处理状态",
    render: (v, row) => (
      <StatusBadge status={v} onRetry={v === "failed" ? () => retryJob(row.id) : undefined} />
    )
  },
  // ...
];
```

#### 合并4 — 切片编辑器 → 资料详情只读预览

```tsx
// DocumentDetailPage.tsx — 增加切片只读预览区块（前20条）
{chunks.slice(0, 20).map(chunk => (
  <div key={chunk.id} className="p-3 border-b text-sm">
    <div className="flex justify-between text-slate-400 text-xs mb-1">
      <span>切片 #{chunk.index}</span>
      <span>{chunk.token_count} tokens</span>
    </div>
    <p>{chunk.content}</p>
  </div>
))}
```

#### 路由修改（`app/src/app/router.tsx`）

```tsx
// 活动页面全部挂在系统管理壳下。
{ path: "rag", element: <DocumentsPage /> },
{ path: "rag/upload", element: <UploadPage /> },
{ path: "rag/documents/:id", element: <DocumentDetailPage /> },
{ path: "rag/search-test", element: <SearchTestPage /> },

// 独立 RAG 壳已删除；旧书签由受 system_admin 守卫的通配路由重定向。
{ path: "/rag-admin/*", element: <LegacyRagAdminRedirect /> },
```

#### 系统管理导航（`app/src/layouts/AdminLayout.tsx`）

```tsx
// RAG 知识库分组的 3 个活动入口（独立 RagAdminLayout 已删除）
const navItems = [
  { path: "/admin/rag",             label: "资料库" },
  { path: "/admin/rag/search-test", label: "召回测试" },
  { path: "/admin/rag/upload",      label: "上传资料" },
];
```

#### P1-1 验收标准

- [x] 系统管理端包含 3 个 RAG 活动入口，独立 RAG 门户已删除
- [x] `/rag-admin/*` 仅保留受权限保护的兼容重定向，不再渲染独立管理壳
- [x] 上传资料后自动完成解析、切片、索引和学生可见发布，不需要人工送审
- [x] 知识库列表包含处理状态列和失败重试操作
- [x] 资料详情页包含资料元数据和切片只读预览，不展示台账/审核操作
- [x] 召回测试台包含"测试台"和"已保存用例"两个Tab
- [x] 5 个退出活动路由的工作流数据仍在数据库，核心操作不受影响

---

### P1-2 · RAG 参数配置重构

**预估工时：** 4h（独立，无依赖）  
**主要文件：** `app/src/pages/admin/RagSettingsPage.tsx` / `server/bhzd_py/routers/admin.py`

#### 重构方案：切片参数 + 召回参数两个 Card（策略均为系统内置）

```
改后布局
├── 切片参数（chunk_size / chunk_overlap / title_inherit）
│   ✂️ 删除：table_strategy（不生效的配置位）
└── 召回参数（top_k / score_threshold / temperature / top_p /
    hybrid_search / rerank_enabled / query_rewrite_enabled）
```

#### 删除 `table_strategy`

```python
# admin.py RagSettingsPatch — 删除
# table_strategy: str | None = None

# admin.py _RAG_TEXT_LIMITS — 删除
# "table_strategy": 20,
```

```tsx
// RagSettingsPage.tsx — 删除"表格处理策略" Field 组件（整行删除）
```

#### 系统内置策略

```tsx
// 生成 Prompt、引用格式、最大引用数和资料发布策略由系统内置。
// 管理员只在“召回参数”卡片调整 top_k、temperature、top_p 及其他召回开关。
```

#### 参数标签中文化（只改 label，不改字段名）

| 现在 | 改后 |
|------|------|
| chunk_size（切片长度） | 切片长度（默认500字符） |
| chunk_overlap（重叠长度） | 切片重叠（默认80字符，必须小于切片长度） |
| score_threshold | 最低相似度阈值（低于此分数将拒答） |
| top_k（召回数量） | 每次最多召回资料数 |
| temperature | 答案采样随机性（范围 0-2） |
| top_p | 答案采样候选概率（范围 0-1） |

#### P1-2 验收标准

- [x] `table_strategy` 从管理 DTO、校验和写入契约移除（数据库列与切片管线保留内部兼容）
- [x] 生成参数、Prompt 模板和发布参数不出现在配置表单，均由系统内置
- [x] `top_k`、`temperature`、`top_p` 在 RAG 参数页可编辑并按范围校验、保存和读取
- [x] 所有可调参数标签已中文化，功能不变

---

## 五、P2 改动详情（等 P0 稳定后按需执行）

### P2-1 · Token 计数优化

**预估工时：** 2.5h  **主要文件：** `conversation_memory.py` / `retriever.py`

**状态：** 已实现近似 token 估算与私有记忆/RAG 证据预算；纳入后端全量回归，未以真实模型 tokenizer 做误差基准。

```python
def estimate_tokens(text: str) -> int:
    """
    近似估算 token 数。中文字符约1字=1token，ASCII 约4字符=1token。
    Why: 不引入 tokenizer 依赖，字符密度近似误差 ±20%，足够控制预算。
    """
    cjk = sum(1 for c in text if '一' <= c <= '鿿')
    rest = len(text) - cjk
    return cjk + rest // 4
```

改动点：
- `conversation_memory.format_context()` 中 2400 字符预算 → ~600 token 预算
- `rag/retriever.py` 证据压缩 `_EVIDENCE_BUDGET=800` → ~200 token 预算

### P2-2 · LLM 输出质量回归测试

**预估工时：** 1-2天  **文件：** `server/tests/test_llm_quality.py`（新建）

4类核心测试用例：
- 已知问题答案包含预期关键词（召回准确性）
- 引用 `doc_id` 与实际文档匹配（引用准确性）
- 超出知识库范围的问题不输出虚假引用（拒答边界）
- LLM 不可用时使用模板答案降级（降级行为）

标注 `@pytest.mark.slow`，CI 可选择性运行。

**状态：** 已实现 7 个离线质量与 Top-K 契约测试，`tests/test_llm_quality.py` 定向运行通过；真实 Provider/标注语料质量仍待验收。

### P2-3 · Chunking 参数调优

**状态：** 已保留并验证章节边界、长文本句读切分及历史切片兼容契约；隔离备份的 20 条评测用例已完成只读 Top-K 基线，但没有 >50 页真实文档和 overlap 100-120 的召回对比，因此不宣称生产参数调优完成。切片策略字段不在管理页面暴露。

- 表格密集型文档：在召回测试台对比当前系统切片参数，不恢复已移除的 `table_strategy` 配置位
- 答案被截断：将 `overlap` 调至 100-120（直接更新数据库，无需改代码）
- 长文档（>50页）：验证章节边界切分，必要时减小 `chunk_size` 至 400

### P2-4 · top-k 参数复审

**状态：** 已修复保存用例的 `top_k` 同时传入 Recall@K 与回答生成的链路，并补充契约测试；隔离备份上 Top-3/5/7/8 均为 20/20 目标文档命中，未擅自把默认值改为 7/8 或宣称 `_RERANK_POOL_SIZE` 最优。真实生产评测集仍待授权。

- RAG `top_k=5` 对长问答场景是否足够（业界建议7-10）
- 召回率偏低时可调至 7-8，观察精度变化
- `_RERANK_POOL_SIZE=20` 是否对所有查询有效

### P2-5~7 · 内置 Prompt/Embedding/temperature 维护

**状态：** 已验证系统内置 Prompt、Provider 嵌入/本地哈希降级及温度透传的离线契约；Prompt 不作为页面配置项，当前没有新增数据类型分支、真实嵌入 Recall@K 差距或场景级温度强制策略，真实调优待后续基准。

- **Prompt**：新增数据类型时同步更新 `data_type` 相关提示词分支
- **Embedding 降级**：建立本地哈希嵌入与 provider 嵌入的召回差距基准（差距>20%时评估接入开源模型）
- **temperature**：教学场景建议 ≤0.3，通用对话保持0.5

### P2-8 · 安全配置页增加运行时指标

**预估工时：** 3h

```

**状态：** 已实现登录成功/失败、活跃会话、API 成功率和 Provider 延迟指标，并由后端与前端测试覆盖。
安全配置（改后）
├── 系统告警（已有，保持）
├── 安全策略（已有，保持）
└── 新增：运行时指标（GET /api/admin/metrics）
    ├── 今日登录成功/失败次数
    ├── 当前活跃会话数
    ├── API 调用成功率（24h）
    └── LLM Provider 延迟（最近10次均值）
```

### P2-9 · 管理端导航平铺优化

**预估工时：** 1h — 将5个导航入口按高频操作顺序平铺展示：模型供应商、RAG 参数、用户管理、安全配置、审计日志。

**状态：** 已取消"核心配置 / 用户管理 / 运维监控"的二级分组；系统管理左侧导航保持单一列表，并通过 Shell/Admin 页面回归。

### P2-10 · 用户页批量操作+导出

**预估工时：** 4h — 批量禁用/启用 + CSV 导出（按角色筛选）

**状态：** 已实现批量状态更新、角色/关键字筛选导出及 CSV 公式注入防护，并通过后端/前端回归。

### P2-11 · 审计日志行展开详情

**预估工时：** 2h — 点击日志行展开侧边抽屉（Drawer），展示 before/after JSON diff

**状态：** 已实现审计详情 Drawer 与 before/after 展示，并通过管理页面回归。

---

## 六、Agent 架构边界与明确不引入项

| 技术 | 不引入原因 |
|------|-----------|
| **LangGraph** | ✅ 学生/教师所有可恢复业务流程均由原生 StateGraph 编排；`agent/graph_runtime.py` 使用旁路 SQLite checkpoint，`agent_runs`、`agent_events`、确认门和 SSE 仍是业务事实源 |
| **LangChain Agent/Chain** | ❌ 不引入；LangGraph 的 `langchain-core` 传递依赖仅用于运行时协议，不改写现有 Provider、RAG、向量和提示实现 |
| **受限 ReAct 子图** | ✅ 仅服务知识问答的只读探索；白名单为 `rag.search`、`graph.reason`、`course.search`，最大步数/超时/结果数均受策略限制，写工具在执行前拒绝 |
| **查询时 GraphRAG** | ✅ 只融合已有人工能力图谱、课程单元和 RAG 证据，结果进入学生图私有合成上下文；不自动抽取实体、不自动建图、不写入图谱 |

---

## 七、执行顺序与里程碑

```
Week 1（P0 快速启动）
├── P0-1：修复 invalid_chat_response（2h）
├── P0-2：预设筛选简化（1.5h）
└── P0-3+P0-4：讯飞删除+Responses+grader角色（13h+4h，合并迁移）

Week 2（P0 核心功能）
├── P0-5：移除任务资源关联（1天）
├── P0-6：教师端任务管理重组（2-3天）（可与P0-5并行）
└── P0-9：Advanced RAG 查询改写（4h，独立可穿插）

Week 3（P0 收尾）
├── P0-7：学习任务 AI 评阅模式重构（25h）
└── P0-8：图谱节点任务同步（2h，P0-7完成后）

Week 4+（P1）
├── P1-1：RAG管理端精简（3-4天）
└── P1-2：RAG参数配置重构（4h，可与P1-1并行）

持续进行（P2，按需）
└── P2-1~11 各项，P0稳定后随迭代执行
```

---

## 八、文件影响矩阵

| 文件 | 改动项 |
|------|--------|
| `agent/providers.py` | P0-1, P0-3, P0-4 |
| `routers/admin.py` | P0-3, P0-4, P1-2 |
| `routers/tasks.py` | P0-5, P0-7, P0-8 |
| `routers/teacher.py` | P0-5, P0-6 |
| `tools/task_tools.py` | P0-5, P0-7 |
| `rag/retriever.py` | P0-9, P2-1 |
| `agent/conversation_memory.py` | P2-1 |
| `migrations/017_provider_protocol_grader.sql` | P0-3, P0-4（合并） |
| `migrations/018_task_learning_content.sql` | P0-7 |
| `migrations/019_query_rewrite_setting.sql` | P0-9 |
| `migrations/020_rag_sampling_settings.sql` | P1-2（temperature/top_p） |
| `app/src/pages/student/PresetsPage.tsx` | P0-2 |
| `app/src/pages/student/TaskDetailPage.tsx` | P0-5, P0-7 |
| `app/src/pages/student/GraphPage.tsx` | P0-8 |
| `app/src/pages/teacher/TaskPublishPage.tsx` | P0-5, P0-6 |
| `app/src/pages/teacher/TasksManagePage.tsx` | P0-6（新建） |
| `app/src/pages/admin/adminShared.ts` | P0-3, P0-4 |
| `app/src/pages/rag/DocumentsPage.tsx` | P1-1 |
| `app/src/pages/rag/DocumentDetailPage.tsx` | P1-1 |
| `app/src/pages/rag/SearchTestPage.tsx` | P1-1 |
| `app/src/pages/admin/RagSettingsPage.tsx` | P0-9（开关），P1-2 |
| `app/src/pages/rag/LedgersPage.tsx` | P1-1（删除） |
| `app/src/pages/rag/EvalCasesPage.tsx` | P1-1（删除） |
| `app/src/pages/rag/JobsPage.tsx` | P1-1（删除） |
| `app/src/pages/rag/ChunkEditorPage.tsx` | P1-1（删除） |
| `app/src/layouts/TeacherLayout.tsx` | P0-6 |
| `app/src/layouts/AdminLayout.tsx` / `app/src/app/router.tsx` | P1-1 |
| `app/src/app/router.tsx` | P0-6, P1-1 |
| `app/src/api/types.ts` | P0-5, P0-7 |

---

*本文档版本 v1.1，2026-08-15，整合自5份分析文档并回填本轮实现与验证证据。*
