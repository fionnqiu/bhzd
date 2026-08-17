---
id: MAT-PLT-005
title: 学习任务的 AI 自动评阅与 grader 供应商角色
version: v1.0.0
source: SRC-POLICY-GRADER-001
source_refs: SRC-POLICY-AI-REVIEW-001
source_type: standard
license_status: pending
data_types: text
visibility: admin
status: draft
verification_status: pending
language: zh-CN
authoring_method: ai-generated-reviewed
created_at: 2026-08-17
updated_at: 2026-08-17
owner: content-reviewer
review_due_at: 2026-08-24
replaces: none
---

# 学习任务的 AI 自动评阅与 grader 供应商角色

本资料覆盖 BHZD 平台学习任务的 AI 自动评阅流程、`grader` 供应商角色与人工兜底。读者对象是平台管理员、教学管理员、运维工程师。

## AI 自动评阅：核心定义

AI 自动评阅（AI grading）指对学习任务中的练习题答案由专门的 `grader` 供应商模型进行异步打分，结果以结构化方式返回。

`grader` 与普通 `chat` 供应商不同，它只接收客观或半客观题目（如代码题、论述题关键词检查），不参与闲聊或知识问答。

## AI 自动评阅：触发流程

1. 学生提交任务答案，系统持久化到 `submitted_tasks` 表。
2. 异步任务根据题目的 `grading_mode` 字段选择 grader 或人工通道。
3. grader 供应商收到题目、参考答案、学生答案、评分 rubric，返回结构化结果。
4. 系统更新学生详情页 `auto_review_status`，并写入 `grading_records`。
5. 学生在 5 秒内可看到"评阅中"状态，完成后看到分数与评语。

异步任务与学生端交互解耦，避免接口阻塞。

## AI 自动评阅：评阅策略

- 客观题（单选、多选、填空）使用关键词匹配 + 数值比对。
- 半客观题（代码、SQL、配置）使用规则评分与示例测试。
- 主观题（论述、案例分析）使用 rubric 评分 + 关键点检查。
- 极端异常任务（如超长文本）回退到人工评审通道。

策略由题目元数据显式决定，不由 grader 模型自行选择。

## AI 自动评阅：安全降级

- grader 不可达：保留"待评阅"状态并通知教师手动处理。
- grader 返回异常 JSON：保留原始返回，重试 1 次，仍失败则交给人工。
- 评阅时长超过 30 秒：标记"评阅中"并允许后续拉取结果。
- 异常不得让用户看到原始 stack trace。

降级策略与 chat 供应商保持一致风格。

## AI 自动评阅：质量控制

- 抽样 5% 评阅结果由教师人工复核。
- 复核分差超过 2 分（10 分制）的样本记入"边界样本库"。
- 每月自动生成评阅一致性报告。
- 报告用于调整 rubric 与 grader 提示词。

## AI 自动评阅：与人工评审协作

- grader 与人工评审双通道互为冗余。
- 高风险题目（如认证评估）必须人工评审兜底。
- 同一题目在 grader 与人工结果不一致时，保留高置信度版本并在 audit log 中标记。
- 教师可一键将 grader 结果替换为人工结果。

## AI 自动评阅：常见误区

- 用 chat 供应商兼任 grader，导致不同提示词互相污染。
- 不暴露 `auto_review_status`，学生看不到进度。
- 异常评分被记录但未通知教师。
- 把所有题目都用 grader，导致主观题质量不可控。

## AI 自动评阅：来源说明

- 来源：`SRC-POLICY-GRADER-001` BHZD 项目内部"grader 供应商规范"，版本 1.0.0。
- 来源：`SRC-POLICY-AI-REVIEW-001` BHZD 项目内部"AI 评阅流程规范"，版本 1.0.0。
- 待核验：未核验在真实高并发下 grader 的延迟和稳定性。
