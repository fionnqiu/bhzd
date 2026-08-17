---
id: MAT-PLT-003
title: 能力图谱与知识点生成的触发流程
version: v1.0.0
source: SRC-POLICY-CAPABILITY-GRAPH-001
source_refs: SRC-POLICY-TASK-CONTENT-001
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

# 能力图谱与知识点生成的触发流程

本资料介绍 BHZD 平台能力图谱节点与学习任务对应的知识点自动生成流程。读者对象是教学管理员、平台工程师。

## 能力图谱：核心定义

能力图谱（capability graph）是按业务能力维度组织的有向图结构。节点代表能力（或技能），边代表依赖或递进关系。每个能力节点可绑定若干知识点（knowledge points）和练习题。

知识点的生成由 `generate_content=true` 标志异步触发。

## 能力图谱：触发流程

1. 教师在能力图谱管理页点击"开始学习"，传入 `generate_content=true`。
2. 系统读取节点绑定的 `capability_key` 与词表，查找相关 RAG 资料与历史资料。
3. 异步任务产生 5 至 8 个由浅入深的知识点，按节点依赖排序。
4. 同时生成配套练习题（选择题、填空题、实操题）。
5. 知识点与题目进入 `status=done` 后，学生端可访问。

异步任务在后台执行，不阻塞教师页操作。

## 能力图谱：知识点质量约束

- 每个知识点 ≤ 500 字符，便于检索与展示。
- 知识点内必须包含 1 个具体可学到的能力与 1 个判定条件。
- 知识点与 RAG 资料之间建立 `source_refs` 关联，便于溯源。
- 同一节点生成的知识点去重，避免重复概念。

## 能力图谱：异常处理

- 知识库无可用切片时，任务返回 `no_chunks_error`，教师可以选择等待或手动编写。
- LLM 生成失败时，记录失败原因，回退到手动模式。
- 异步任务运行超时（> 5 分钟），自动重试 1 次，仍失败则通知教师。
- 异常状态保留在 `task.status` 中，方便审计。

## 能力图谱：与练习题的关系

- 同一节点下练习题与知识点共享 `node_id`。
- 练习题难度按知识点深度分级（初级、进阶、综合）。
- 练习题答案通过 `grader` 供应商异步 AI 评阅。
- 评阅结果在学生详情页可看到 `auto_review_status`。

## 能力图谱：常见误区

- 同步触发知识点生成，导致教师页面卡顿。
- 知识点不绑定 source，事后无法溯源。
- 同一节点生成过多知识点（> 12 个），造成认知负担。
- 异步任务失败不通知教师。

## 能力图谱：来源说明

- 来源：`SRC-POLICY-CAPABILITY-GRAPH-001` BHZD 项目内部"能力图谱规范"，版本 1.0.0。
- 来源：`SRC-POLICY-TASK-CONTENT-001` BHZD 项目内部"任务学习内容规范"，版本 1.0.0。
- 待核验：未核验异步任务在真实高并发下的稳定性。
