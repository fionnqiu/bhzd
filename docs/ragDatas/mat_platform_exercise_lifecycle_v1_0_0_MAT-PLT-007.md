---
id: MAT-PLT-007
title: 教师视角下练习题生成、维护与质量保证
version: v1.0.0
source: SRC-POLICY-EXERCISE-001
source_refs: SRC-POLICY-GRADER-001,SRC-POLICY-IA-001
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

# 教师视角下练习题生成、维护与质量保证

本资料覆盖 BHZD 平台教师视角下的练习题生成流程、维护方法与质量保证。读者对象是教师、教学管理员。

## 练习题：核心定义

练习题是平台承载学习活动的最小单元，含题干、答案、评分 rubric、能力图谱关联和题目版本号。每道题必须独立可检索、独立可复用。

练习题归属于任务（task），并通过能力图谱节点关联到知识点。

## 练习题：生成方式

- 手动编写：教师在管理后台手动编写题干、答案与 rubric。
- AI 生成：教师点击"AI 生成"按钮，按选定知识点由系统生成初稿，教师审核后定稿。
- 模板化：复用已有模板并替换关键参数。

AI 生成初稿必须经教师审核，不允许"自动提交"路径。

## 练习题：题目类型

常见类型：

- 单选题：固定选项数 + 唯一正确答案。
- 多选题：固定选项数 + 多选正确答案。
- 填空题：文本片段，含多个空格。
- 论述题：自由作答，由 grader 异步评阅。
- 实操题：按操作步骤或代码运行结果评阅。

每类题型对应不同的评分字段与生成模板。

## 练习题：维护要点

- 题目版本号：`v主.次.修订`。
- 题目修订必须保留旧版本以便回看。
- 题目废弃通过 `deprecated=true`，归档至 `_archive/exercises/`。
- 题库抽样难度检查每月一次。

## 练习题：质量保证

- 抽样 5% 题目让审核员复核题干、答案、rubric 一致性。
- AI 评阅一致性（Cohen κ）≥ 0.7。
- 学生答题错误率统计：错答率超 30% 的题目应重审。
- 题库 ≥ 30 题/能力节点，确保难度梯度。

## 练习题：与 RAG 资料的关系

- 题目应在对应知识点的 RAG 资料中可检索到至少一段回答。
- 若资料缺失，应先补齐资料再上线题目。
- 题目更新可能导致旧答案失效，必须通知 RAG 检索可能失效。
- 题目与 RAG 资料的关联不强制双向，避免维护负担。

## 练习题：常见误区

- AI 生成题目直接发布，不经教师复核。
- 修订题干但不影响版本号，导致历史答案错配。
- 题库题量过少（<10 题/节点），难度不分层。
- 题目评分 rubric 模糊，导致 grader 与人工评审偏差大。

## 练习题：示例与反例

正例（虚构示例）：教师 AI 生成 5 道"宏平均 F1"练习题初稿，逐题审核改写 rubric 后发布；与 `MAT-NLP-001` 资料关联。

反例：直接采用 AI 输出，不改写 rubric，发布到 student 后评分与人工评审不一致。

## 练习题：来源说明

- 来源：`SRC-POLICY-EXERCISE-001` BHZD 项目内部"练习题规范"，版本 1.0.0。
- 来源：`SRC-POLICY-GRADER-001` BHZD 项目内部"grader 供应商规范"，版本 1.0.0。
- 来源：`SRC-POLICY-IA-001` BHZD 项目内部"标注员一致性策略"，版本 1.0.0。
- 待核验：未核验不同学科题目结构兼容性。
