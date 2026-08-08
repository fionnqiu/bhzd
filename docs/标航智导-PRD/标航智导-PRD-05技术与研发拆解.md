# 标航智导 PRD 05：技术与研发拆解

> 文档版本：v3.1  
> 更新日期：2026-08-06  
> 文档定位：数据模型、API、Agent 事件流、工具契约、研发闭环与赛事演示闭环

---

## 1. 技术逻辑架构

```text
用户输入
  ↓
Agent 编排层
  ├── 意图识别
  ├── 场景识别
  ├── 计划生成
  ├── 工具选择
  └── 结果整合
  ↓
工具能力层
  ├── RAG 知识召回
  ├── 能力图谱推理
  ├── 课程检索
  ├── 任务卡生成
  ├── 标注文件诊断
  └── 掌握度更新
  ↓
数据与知识层
  ├── RAG 文档库
  ├── 向量索引
  ├── 数据标注能力图谱
  ├── 教学单元库
  ├── 场景规则库
  ├── 来源台账
  └── 学习行为数据
```

---

## 2. 核心数据模型

| 实体 | 说明 |
|------|------|
| User | 用户 |
| Role | 角色 |
| Class | 班级 |
| Session | Agent 会话 |
| Run | Agent 单次运行 |
| ToolCall | 工具调用 |
| Confirmation | 确认门 |
| LearningProfile | 学习画像 |
| Mastery | 掌握度 |
| LearningTask | 学习任务 |
| DiagnosticSummary | 诊断摘要 |
| GraphNode | 图谱节点 |
| GraphEdge | 图谱边 |
| TeachingUnit | 教学单元 |
| RagDocument | RAG 资料 |
| RagChunk | RAG 切片 |
| RagIndexJob | 索引任务 |
| SourceLedger | 来源台账 |
| ReviewRecord | 审核记录 |
| EvalCase | RAG 评测用例 |

---

## 3. RAG 核心实体

### 3.1 RagDocument

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 资料 ID |
| title | string | 标题 |
| file_type | enum | pdf / docx / md / xlsx / csv / image / other |
| source_type | enum | textbook / standard / enterprise / teacher / competition / other |
| source_name | string | 来源名称 |
| source_url | string | 来源链接，可为空 |
| version | string | 版本号 |
| license_status | enum | authorized / internal / pending / forbidden |
| data_types | array | text / image / audio / video |
| scenario_ids | array | 场景 |
| cap_ids | array | 关联能力 |
| status | enum | draft / parsing / indexed / review_pending / published / rejected / archived / failed |
| created_by | UUID | 上传人 |
| created_at | datetime | 上传时间 |
| updated_at | datetime | 更新时间 |

### 3.2 RagChunk

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 切片 ID |
| document_id | UUID | 所属资料 |
| chunk_index | int | 切片序号 |
| content | text | 切片文本 |
| summary | text | 切片摘要 |
| keywords | array | 关键词 |
| page_start | int | 起始页 |
| page_end | int | 结束页 |
| section_title | string | 章节标题 |
| token_count | int | token 数 |
| embedding_id | string | 向量 ID |
| metadata | object | 场景、能力、数据类型等 |
| status | enum | active / disabled |

---

## 4. API 需求

### 4.1 学生端 API（仅 `student` / `content_admin` / `system_admin`）

教师账号不得调用以下学生端 API；路由守卫与服务端依赖均须返回 403。内容管理员和系统管理员保留学生端访问权限。

| 端点 | 方法 | 说明 |
|------|------|------|
| /api/auth/register | POST | 用户注册 |
| /api/auth/verify-email | POST | 邮箱验证 |
| /api/auth/login | POST | 登录 |
| /api/auth/logout | POST | 登出 |
| /api/runs | POST | 启动 Agent 运行 |
| /api/runs/{id} | GET | 获取运行详情 |
| /api/runs/{id}/events | GET | SSE 事件流 |
| /api/confirmations/{id}/confirm | POST | 确认写操作 |
| /api/confirmations/{id}/cancel | POST | 取消写操作 |
| /api/presets | GET | 获取预设学习路径 |
| /api/tasks | GET/POST | 学习任务列表 / 创建 |
| /api/tasks/{id} | GET/PATCH | 任务详情 / 更新 |
| /api/diagnostics | POST | 上传并诊断标注结果 |
| /api/profile/mastery | GET | 获取掌握度 |
| /api/rag/query | POST | RAG 知识问答 |

### 4.2 教师端 API

| 端点 | 方法 | 说明 |
|------|------|------|
| /api/teacher/dashboard | GET | 教师工作台 |
| /api/teacher/classes | GET/POST | 班级列表 / 创建 |
| /api/teacher/classes/{id}/students | GET | 班级学生 |
| /api/teacher/tasks | GET/POST | 教学任务 |
| /api/teacher/tasks/{id}/publish | POST | 发布任务 |
| /api/teacher/resources | GET | 只读资料选择器；仅返回已发布、学生可见、已授权且未过期的可分配资料 |
| /api/teacher/analytics | GET | 学情分析 |

### 4.3 RAG 管理 API（仅 `system_admin`）

| 端点 | 方法 | 说明 |
|------|------|------|
| /api/rag/documents | GET/POST | 资料列表 / 上传 |
| /api/rag/documents/{id} | GET/PATCH/DELETE | 资料详情 / 编辑 / 删除 |
| /api/rag/documents/{id}/parse | POST | 重新解析 |
| /api/rag/documents/{id}/chunk | POST | 重新切片 |
| /api/rag/documents/{id}/index | POST | 重新索引 |
| /api/rag/documents/{id}/submit-review | POST | 提交审核 |
| /api/rag/documents/{id}/publish | POST | 发布 |
| /api/rag/documents/{id}/archive | POST | 归档 |
| /api/rag/chunks/{id} | GET/PATCH | 查看 / 编辑切片 |
| /api/rag/search-test | POST | 召回测试 |
| /api/rag/eval-cases | GET/POST | 评测集 |
| /api/rag/eval-runs | POST | 运行评测 |
| /api/source-ledgers | GET/POST | 来源台账 |

教师、内容管理员和学生调用任一 RAG 管理端点必须返回 403。学生端 RAG 问答仍使用 `/api/rag/query`，并遵循学生端角色边界。

### 4.4 系统管理 API

| 端点 | 方法 | 说明 |
|------|------|------|
| /api/admin/providers | GET/POST/PUT/DELETE | 模型供应商 |
| /api/admin/providers/{id}/test | POST | 连接测试 |
| /api/admin/rag-settings | GET/PATCH | RAG 参数配置 |
| /api/admin/users | GET/PATCH | 用户与权限 |
| /api/admin/audit-logs | GET | 审计日志 |

---

## 5. Agent 事件流

| 事件 | 说明 |
|------|------|
| run.started | 运行开始 |
| message.delta | 文本增量 |
| plan.updated | 计划更新 |
| tool.call.requested | 工具调用请求 |
| tool.call.completed | 工具调用完成 |
| rag.retrieval.started | RAG 召回开始 |
| rag.retrieval.completed | RAG 召回完成 |
| citation.attached | 引用来源已附加 |
| confirmation.required | 需要用户确认 |
| run.completed | 运行完成 |
| run.failed | 运行失败 |
| run.usage | token 使用统计 |

---

## 6. 工具契约

| 工具 | 权限 | 自动执行 | 说明 |
|------|------|----------|------|
| course.search | read | 是 | 课程检索 |
| graph.reason | read | 是 | 图谱推理 |
| task.preview | read | 是 | 任务卡预览 |
| task.create | write | 否 | 创建学习任务 |
| diagnostic.preview | read | 是 | 诊断预览 |
| diagnostic.save_summary | write | 否 | 保存诊断摘要 |
| mastery.update | write | 否 | 更新掌握度 |
| rag.search | read | 是 | 按问题和元数据召回切片 |
| rag.answer | read | 是 | 基于召回证据生成答案 |
| rag.preview_upload | read | 是 | 预检上传文件 |
| rag.create_document | write | 否 | 创建资料记录 |
| rag.reindex_document | write | 否 | 重建向量索引 |
| rag.publish_document | write | 否 | 发布资料 |
| rag.archive_document | write | 否 | 归档资料 |
| rag.save_eval_case | write | 否 | 保存评测问题 |

`rag.preview_upload`、`rag.create_document`、`rag.reindex_document`、`rag.publish_document`、`rag.archive_document` 与 `rag.save_eval_case` 属于 RAG 管理能力，仅 `system_admin` 可调用；教师不得通过 Agent 绕过 RAG 管理边界。

---

## 7. 研发闭环拆解

### 7.1 第一开发闭环：学生可用闭环

| 顺序 | 交付项 | 依赖 |
|------|--------|------|
| 1 | 登录 / 注册 / 基础用户态 | 无 |
| 2 | Agent 指挥舱欢迎态与输入框 | 用户态 |
| 3 | 预设学习卡与预设路径数据 | 教学单元 |
| 4 | 学习任务卡预览与创建 | 确认门 |
| 5 | 学习任务详情与完成反馈 | 掌握度模型 |
| 6 | 能力图谱局部展示 | 图谱数据 |

### 7.2 第二开发闭环：RAG 可召回闭环

| 顺序 | 交付项 | 依赖 |
|------|--------|------|
| 1 | RAG 资料上传与元数据表单 | 文件存储 |
| 2 | 文档解析与切片任务 | 解析器 |
| 3 | 向量化与索引 | 嵌入模型 |
| 4 | 资料审核与发布 | 权限系统 |
| 5 | 召回测试台 | rag.search |
| 6 | 学生端 RAG 问答与引用展示 | rag.answer |

### 7.3 第三开发闭环：诊断补强闭环

| 顺序 | 交付项 | 依赖 |
|------|--------|------|
| 1 | 标注文件上传与格式校验 | 文件解析器 |
| 2 | 确定性诊断规则 | 场景规则库 |
| 3 | RAG 召回规则依据 | 已发布知识库 |
| 4 | 图谱定位薄弱能力 | 能力图谱 |
| 5 | 补强计划生成 | PRE 路径 |
| 6 | 保存诊断摘要与掌握度更新 | 确认门 |

### 7.4 第四开发闭环：教师教学闭环

| 顺序 | 交付项 | 依赖 |
|------|--------|------|
| 1 | 教师工作台 | 教师角色 |
| 2 | 教学任务生成 | Agent + RAG + 图谱 |
| 3 | 教师编辑任务卡 | 任务模型 |
| 4 | 班级发布 | 班级模型 |
| 5 | 学生接收任务 | 学生任务列表 |
| 6 | 学情分析基础报表 | 学习行为数据 |

---

## 8. 赛事最小演示版本

| 编号 | 能力 | 原因 |
|------|------|------|
| M1 | Agent 指挥舱欢迎态 + 预设学习 | 解决学生不知道问什么的问题 |
| M2 | RAG 资料上传、发布、召回 | 体现真实知识库能力 |
| M3 | 专业回答带引用 | 满足内容专业性与可溯源 |
| M4 | 能力图谱局部路径 | 对齐岗位能力图谱场景 |
| M5 | 企业任务转学习任务卡 | 对齐岗位任务转学习任务场景 |
| M6 | 标注文件诊断 | 形成教学实训闭环 |
| M7 | 掌握度与补强推荐 | 对齐个性化自适应学习 |
| M8 | 管理员模型配置 | 支撑真实智能体运行 |

---

## 9. 推荐演示主线

```text
学生打开系统
  ↓
点击“语音标注入门”预设学习
  ↓
切换到“智能客服场景”
  ↓
Agent 生成学习计划
  ↓
RAG 召回客服语音标注规范
  ↓
图谱显示相关能力路径
  ↓
生成学习任务卡
  ↓
学生完成练习并上传 TextGrid / JSON 结果
  ↓
系统诊断错误
  ↓
展示引用依据、薄弱能力和补强路径
  ↓
保存诊断摘要并更新掌握度
```

---

## 10. 研发实现补充约束

详细遗漏点、边界条件和验证矩阵见：

- 标航智导-PRD-06研发可落地补充与边界条件.md

研发排期时，PRD-06 中的以下内容应视为 P0 交付约束：

| 约束 | 原因 |
|------|------|
| RAG 未审核资料不得进入学生端召回 | 避免专业错误和资料污染 |
| 专业回答无可靠召回时必须拒答 | 避免幻觉 |
| 写操作必须使用确认门 | 避免 Agent 越权修改用户状态 |
| 异步任务必须支持失败、重试和幂等 | 文档解析和索引不可避免失败 |
| 诊断原文件不持久化 | 降低隐私和合规风险 |
| 已发布资料只能归档，不能直接物理删除 | 保证历史引用可追溯 |
| 教师访问学生端或 RAG 管理能力必须为 403；内容管理员和系统管理员保留学生端，RAG 仅系统管理员 | 防止前端路由、HTTP API 与 Agent 工具的角色边界不一致 |
