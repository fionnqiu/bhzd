# 标航智导教学智能体 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付覆盖文本、图像、语音、视频四类数据标注的图谱驱动教学智能体，并完成可验证的参赛材料。

**Architecture:** 教学单元和可溯源规则构成内容层；166 节点、240 边的 CAP/KNG/TSK/SCN/RES/CERT 图谱组织学习顺序与资源关系，通用规则是基础层而非 SCN。Web 教学应用与智能体只消费已发布的数据；场景以规则覆盖挂载，语音以六项能力实现最深入教学闭环，视频只复用标注原语扩展。

**Tech Stack:** 讯飞星辰 Agent 平台、Python 图谱与数据处理、JSON/GraphML、Web 可视化（vis-network 或同等实现）、经批准的前端运行时。

---

### Task 1: 建立内容来源与教学单元基线

**Files:**
- Create: `data/sources/source-registry.json`
- Create: `data/curriculum/teaching-units.json`
- Modify: `docs/教学内容与图谱数据规范.md`
- Test: `tests/content/test_teaching_units.py`

- [x] **Step 1: 为四类数据类型各登记至少一个已核验来源、一个教学单元、一个正反例和一个可判定练习；分离 `SRC-*` 来源与 `KNG-*` 教学概念。**
- [x] **Step 2: 运行 `python -m pytest tests/content/test_teaching_units.py -q`，验证必填字段、来源状态和练习判定规则；预期结果为全部通过。**
- [x] **Step 3: 审阅来源许可证与素材授权，记录不能发布的条目并从学生可见索引中排除。**

### Task 2: 构建并校验能力图谱

**Files:**
- Create: `data/graph/graph-catalog.json`
- Create: `data/graph/annotation-capability-graph.json`
- Create: `data/graph/annotation-capability-graph.graphml`
- Create: `scripts/build_graph.py`
- Create: `scripts/validate_graph.py`
- Test: `tests/graph/test_graph_integrity.py`

- [x] **Step 1: 从机器可读图谱目录确定性生成 CAP 40、KNG 60、TSK 20、SCN 4、RES 30、CERT 12 的 166 节点和 240 边，以及 PRE、ISA、SUP、REL、INSCN、MAPCERT 关系；图谱分类节点可处于 `draft` 或 `reviewed`，教学应用只消费同时为 `published`、学生可见且进入可见索引的教学单元链接。**
- [x] **Step 2: 运行 `python scripts/validate_graph.py data/graph/annotation-capability-graph.json`；预期输出包含唯一 ID、端点完整、PRE 无环、任务可回溯和场景覆盖规则检查全部通过。**
- [x] **Step 3: 运行 `python -m pytest tests/graph/test_graph_integrity.py -q`；预期结果为全部通过。**

### Task 3: 实现文本与图像教学基线

**Files:**
- Create: `data/curriculum/text/`
- Create: `data/curriculum/image/`
- Create: `tests/content/test_text_image_evaluation.py`
- Modify: `data/curriculum/teaching-units.json`

- [x] **Step 1: 为文本和图像分别实现规则讲解、正反例、练习、标准答案与错误反馈，并关联图谱能力节点。**
- [x] **Step 2: 运行 `python -m pytest tests/content/test_text_image_evaluation.py -q`；预期结果为相同输入始终得到相同判定和规则引用。**
- [x] **Step 3: 由未参与本批内容实现的独立 AI 审阅代理复核边界、遮挡和歧义样例，并按数据规范记录 `reviewer_type=ai_agent`、版本、结论、发现和剩余风险；只有 `decision=approved` 且剩余风险不阻断开发发布时才可将通过条目改为 `published`。不得表述为人工、教师或专家背书；正式赛事提交或真实学生发布仍须由人工领域专家确认。**

### Task 4: 实现语音深度教学链

**Files:**
- Create: `data/curriculum/audio/`
- Create: `data/assets/audio/`
- Create: `tests/content/test_audio_learning_path.py`
- Modify: `data/graph/annotation-capability-graph.json`

- [x] **Step 1: 建立转写与标点、说话人、语种/方言、情感与副语言、唤醒词/命令词、切割与对齐六项前置能力链及其练习。**
- [x] **Step 2: 运行 `python -m pytest tests/content/test_audio_learning_path.py -q`；预期结果为每项错误都能回链至规则、能力和补强资源。**
- [x] **Step 3: 使用授权音频完成一条“学习-练习-反馈-补强”录屏，并保留原始样例与许可记录。**

### Task 5: 扩展视频教学与场景规则

**Files:**
- Create: `data/curriculum/video/`
- Create: `data/scenarios/`
- Create: `tests/content/test_video_and_scenarios.py`
- Modify: `data/graph/annotation-capability-graph.json`

- [x] **Step 1: 增加视频帧标注、目标追踪、行为事件教学单元，复用统一练习和反馈结构。**
- [x] **Step 2: 为首批行业案例创建场景覆盖规则，声明支持的数据类型，并通过 `base_rule_ref`、`override_type`、SCN 与 INSCN 关系挂载。**
- [x] **Step 3: 运行 `python -m pytest tests/content/test_video_and_scenarios.py -q`；预期结果为场景改变规则或案例，不复制或破坏通用课程结构。**

### Task 6: 完成教学应用与诊断系统

**Files:**
- Create: `app/`
- Create: `evidence/user-trials/`
- Test: `tests/e2e/`

- [x] **Step 1: 在经批准的 Web 技术方案中实现课程入口、图谱导航、内容展示、练习、自检、任务转化卡、结构化文件诊断与路径推荐；截图不改变分数或掌握度。**
- [x] **Step 2: 运行各模块单元测试和端到端测试；预期结果为文本、图像、语音、视频、场景切换和诊断路径均可完成。**
- [ ] **Step 3: 组织 2-3 名师生试用，记录修订与复测结果。阻塞：尚未取得真实人工领域专家发布放行，以及 2-3 名真实参与者的试用、反馈、修订与复测记录。**

### Task 7: 产出操作文档与赛事提交包

**Prerequisite:**
- Task 6 已完成，且系统验证与试用证据可供引用。

**Files:**
- Create: `docs/操作手册.md`
- Create: `submission/`
- Reference: `docs/功能验收与赛事提交清单.md`

- [ ] **Step 1: 根据已验证的系统行为与试用证据编写操作手册，覆盖课程学习、图谱导航、练习、自检、文件诊断与学习路径推荐。**
- [ ] **Step 2: 按 `docs/功能验收与赛事提交清单.md` 制作四目录提交包，确保所有文档、视频、PDF 与版权说明引用真实的已验证成果。**
- [ ] **Step 3: 在干净环境启动作品并检查提交包的视频、PDF、大小、版权与文件唯一性；若发现系统缺陷，回退至 Task 6 修复后重新验证。**
