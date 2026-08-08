# 标航智导项目长期记忆

## 项目定位
- 名称：标航智导——图谱驱动的数据标注能力教学智能体
- 目标：中国大学生计算机设计大赛（数媒游戏与交互类）参赛作品
- 核心：数据标注教学智能体；图谱驱动教学（非普通问答机器人）
- 教学覆盖：文本/图像/语音/视频四类标注；首批4场景（医疗/客服/车载/内容安全）
- 产品定义文档：`docs/标航智导.md`（v2.0 目标架构）

## 技术栈
- 前端：React 19 + TypeScript + Vite 7 + vis-network（图谱可视化）+ lucide-react；源码在 `app/src`
- 后端：Python + FastAPI + Pydantic + SQLite + LangGraph（Agent 编排）；源码在 `server/bhzd_py`
- 安全：Argon2id 密码哈希、AES-256-GCM 模型密钥加密、CSRF 防护、HttpOnly Cookie 会话
- 路由注意：管理员路径是 `/amdin`（故意拼写，非 /admin），见 `app/src/app/router.tsx`

## 数据资产（已完成）
- 能力图谱 v1：166 节点（CAP 40/KNG 60/TSK 20/SCN 4/RES 30/CERT 12）× 240 边
  - 6 类关系：PRE/ISA/SUP/REL/INSCN/MAPCERT
  - 文件：`data/graph/annotation-capability-graph.json` + `.graphml`
  - 构建脚本：`scripts/build_graph.py`，从 `graph-catalog.json` 生成
- 课程：`data/curriculum/`（audio/image/text/video + legacy）
- 场景：`data/scenarios/`（medical/customer-service/in-vehicle/content-safety）
- 来源台账：`data/sources/source-registry.json`
- 知识库首批 62 条规范（见 docs 第10章）

## 实现状态（2026-07-23 分析）
- ✅ Phase 1 已完成：课程/图谱/任务转化/文件诊断/确定性练习/本地学习状态（Web 教学应用，约5580行TS/TSX）
- ✅ Phase 2 部分完成：
  - FastAPI 服务 + SQLite 持久化基线（app.py 437行 + repositories.py 466行）
  - 用户认证 API（注册/登录/会话/登出），但 verify-email/forgot/reset 是 stub
  - 单一管理员 `/amdin` + Provider CRUD API + 前端配置 UI（AdminPage 446行）
  - 对话/运行/确认 API（SSE 事件流）
- ⚠️ 骨架/Stub：
  - Agent 编排：`agent/graph.py` 仅 LangGraph 状态图骨架（receive_message→echo→complete，或消息含"task.create"走确认），未接真实 LLM
- ❌ 待实现：
  - 四类模型协议适配器（星辰/星火/Chat Completions/Anthropic Messages）真实调用
  - Agent 工具网关（课程检索/图谱推理/任务预览/诊断预览的工具 schema 封装）
  - SMTP 真实邮件发送
  - Phase 3 赛事提交材料（PPT/视频/概要表 PDF）
- 前端测试：app/tests 下有 admin/agent/router/auth 测试（vitest）+ e2e（playwright）

## 关键约定（AGENTS.md）
- 任何新任务前必须先给出任务简报待用户审批，才能改文件
- 文档变更要追加 `docs/logs/document-changelog.md`
- 每个 Codex 任务要追加 `E:\ObsidianWorkSpace\logs\codex\Work Log YYYY-MM-DD.md`

## 讯飞星辰平台发布方向（D2，2026-07-27 澄清）
- 用户明确目标：**把标航智导 agent 发布到讯飞星辰平台**（上架为平台智能体/可调用），不是"用星火当模型大脑"。
- 平台能力：自定义创建智能体（画布 + Agent智能决策节点）、知识库上传、自定义插件（现有HTTP接口参数化登记）、自定义MCP Server托管、发布为API/星火App/公众号。
- 工作流发布后可经 Workflow Open API 调用：`POST https://xingchen-api.xf-yun.com/workflow/v1/chat/completions`，鉴权 `Bearer {API_KEY}:{API_SECRET}`。
- 关键取舍：发布到平台 = 以平台范式重建智能体（角色设定+知识库+工具），**不能上传整套 FastAPI+React 栈**。
- 后端 4 工具（课程检索/图谱推理/任务预览/诊断）保留自托管，封装为自定义插件或 MCP Server 挂载到平台智能体，保留差异化。
- React UI / vis-network 图谱可视化 / LangGraph 编排不在平台内；保留自托管应用作富演示，平台智能体作附加渠道。
