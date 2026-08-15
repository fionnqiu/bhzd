# 真实验证阶段报告（2026-08-15）

## 范围与边界

- 本轮按已确认的缩减范围执行：浏览器视觉走查、学生试用前置检查、隔离语料检索基线与参数对比。
- **Responses Provider 协约验收仍暂停**。本报告没有把模拟适配器、健康检查或本地 SSE 测试当作真实 Provider 连通证明。
- 未停止、重启或改动既有 `8787`、`5173`、`5174` 服务；隔离后端使用临时端口 `8788` 和数据库备份。

## 环境与证据

- 隔离数据库：`C:\Users\fionnqiu\AppData\Local\Temp\bhzd-real-validation-20260815\bhzd.sqlite`，由运行时 SQLite Backup API 生成；检索矩阵以只读 URI 打开。
- 隔离后端：`127.0.0.1:8788`，PID `52724`，健康检查 `200 OK`。
- 浏览器 E2E 使用隔离 API 目标运行，修复旧选择器/旧入口契约后结果为 **4 passed**（登录页、预设详情、能力图谱、教师工作台）。
- 认证后视觉证据：
  - `screenshots/login-desktop.png`
  - `screenshots/login-mobile.png`
  - `screenshots/e2e-trace-*.jpeg`（四条隔离 E2E 流程）
  - `screenshots/graph-live-desktop.png`
  - `screenshots/graph-live-mobile.png`
- 能力图谱在等待数据后桌面和移动视口均渲染 166 个节点；新鲜浏览器页的控制台错误数为 0，`/api/auth/session`、`/api/graph/overview`、`/api/conversations` 均返回 200。早先截图中的空白画布属于数据尚未完成渲染，不作为最终视觉结论。
- 登录页、欢迎页、预设详情抽屉和教师工作台未发现明显遮挡、横向溢出或断裂布局。实时图谱截图通过既有 `5173 -> 8787` 本地服务做视觉复核，不能替代隔离后端的 Provider 验收。

## 隔离语料 Top-K 基线

只读备份包含 `1204` 个文档、`8504` 个切片和 `20` 个评测用例。运行时设置为：`chunk_size=500`、`chunk_overlap=80`、`top_k=5`、`score_threshold=0.35`、hybrid 开启、rerank 关闭、query rewrite 关闭。备份中唯一启用的 Provider 是 `anthropic_messages` 的 primary，未配置 embedding 角色；本次检索实际使用 `local-hash-bow-512`，没有外部 Provider 调用。

| Top-K | 目标文档命中率 | 平均文档 Recall | MRR | 平均延迟 | P95 延迟 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 20/20 (100%) | 100% | 1.000 | 229.32 ms | 241 ms |
| 5 | 20/20 (100%) | 100% | 1.000 | 227.05 ms | 248 ms |
| 7 | 20/20 (100%) | 100% | 1.000 | 220.82 ms | 233 ms |
| 8 | 20/20 (100%) | 100% | 1.000 | 220.60 ms | 229 ms |

每个 K 先预热 1 次，再完整运行 3 轮（每个 K 共 60 次调用）；表中延迟为 retriever 返回的单次测量值，独立 wall-clock 统计的均值约为 233.15/231.12/224.17/224.12 ms（K=3/5/7/8）。

在这组隔离种子评测集上，Top-3 已覆盖全部目标文档，增大到 5/7/8 没有可观测召回收益。该结果只能作为当前备份的回归基线，不能外推到真实生产语料或宣称完成参数调优。

### 阈值敏感性（仅进程内对比）

保持同一 Top-5 检索结果，仅替换内存中的阈值：

| 阈值 | 检索目标命中率 | 高于阈值的用例 |
| ---: | ---: | ---: |
| 0.25 | 20/20 (100%) | 19/20 (95%) |
| 0.30 | 20/20 (100%) | 18/20 (90%) |
| 0.35（当前） | 20/20 (100%) | 14/20 (70%) |
| 0.40 | 20/20 (100%) | 11/20 (55%) |
| 0.45 | 20/20 (100%) | 5/20 (25%) |

当前阈值下低于阈值但目标文档仍排第一的 6 条问题及最高分为：负例样本不能删除（0.2200）、考试一级错误（0.2991）、错误等级（0.3164）、语音切分时长（0.3470）、NER F1（0.3308）、PRODUCT 判定（0.3266）。这说明本小样本首先暴露的是阈值与拒答策略的敏感性，而不是 Top-K 不足；是否调整阈值必须由真实标注集、误答成本和领域负责人共同决定，本轮不改配置。

## 学生试用前置检查

`evidence/user-trials/trial-protocol.md` 仍为 `awaiting_human_domain_release_and_participants`。缺少 `release_approval_ref`、真实参与者角色及 consent/authorization reference、记录者身份，因此本轮**未开始、未伪造、未生成真实学生试用记录**。现有 Playwright 流程只记为隔离种子演示浏览器验收，不能替代正式参与者试用。

## 待后续授权/环境验收

1. Responses Provider 的真实密钥、模型和网络连接测试，以及真实 Responses 流式浏览器渲染。
2. 经批准的真实学生参与者试用和复测记录。
3. 使用真实标注语料、明确误答成本和标注集的 chunk/overlap、Top-K、embedding、prompt、temperature 对比。

## 本轮教师任务与自动内容回归

- 在现有本地登录会话中打开 `/teacher/tasks`，实际新建任务、关联能力、选择班级并点击发布；任务列表随后显示“已发布”和 `1 名学生`。
- 只读核对 SQLite 中该教师原件与学生副本的 `content_status` 均为 `done`，证明教师创建与发布路径都进入自动内容生成队列。
- 学生任务详情的浏览器截图显示“学习内容已自动排队，正在准备中，请稍候…”，页面不再提供“开始生成学习内容”按钮；失败态仍保留重试入口。
- 学生 Agent 对话输入框在 `390×844` 与 `1280×720` 视口均满足发送按钮右/下边界与输入框相同，且页面无水平溢出，确认发送按钮位于输入框右下角。
- 新增视觉证据：`screenshots/teacher-task-publish-regression.png`、`screenshots/student-task-auto-generation.png`、`screenshots/student-task-content-status.png`。

这仍是本地演示数据和已登录会话回归，不等同于正式学生试用或真实 Provider/Responses 协约验收；后两项按当前授权边界继续保持未验收。
