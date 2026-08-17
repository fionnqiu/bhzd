---
id: MAT-PLT-006
title: 资料审核与发布工作流（系统管理员视角）
version: v1.0.0
source: SRC-POLICY-DOC-LIFECYCLE-001
source_refs: SRC-POLICY-RAG-EVAL-001,SRC-POLICY-PUBLISH-001
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

# 资料审核与发布工作流（系统管理员视角）

本资料覆盖 BHZD 平台 RAG 资料从"待核验"到"已发布"的全流程。读者对象是系统管理员、内容审核者。

## 资料生命周期：核心定义

资料生命周期涵盖：草稿（draft）→ 审核中（reviewed）→ 已批准（approved）→ 已发布（published）→ 已弃用（deprecated）。

任何状态变更都必须留下变更日志和责任记录。

## 资料生命周期：草稿到审核

- 编辑者生成或整理文件，完成自检后落入草稿区。
- 草稿状态对应 `status=draft`、`visibility=admin`。
- 编辑者使用前必须通过 `verification_status=pending` 标识未完成。

## 资料生命周期：审核到批准

- 审核员完成基础人工审核，包括事实、授权、可见范围、检索问题。
- 审核员不得审核自己无法核验的专业结论。
- 审核通过后 `status` 改为 `reviewed`，`verification_status` 改为 `verified`。
- 此时允许 `visibility=teacher` 但不允许 `student`。

## 资料生命周期：批准到发布

- 拥有发布权限的系统管理员确认组合与门禁（按规则 5.4 节）。
- 系统管理员执行发布后，等待解析/切片/索引任务完成。
- 任务成功且状态变为 `published` 才算发布完成。
- 任何任务失败，资料退回修改。

## 资料生命周期：弃用

- 资料失效、错误或被替代时进入 `deprecated`。
- 弃用仍保留可检索，但只对 admin 可见。
- 弃用版本归档至 `_archive/materials/<id>/<version>/`。
- 替代关系写入 `replaces` 字段。

## 资料生命周期：常见误区

- 跳过审核直接发布。
- 在草稿状态下伪造审核字段。
- 不观察后台流水线，宣称"已发布"。
- 弃用时不保留旧版本与替代关系。

## 资料生命周期：示例与反例

正例（虚构示例）：AI 生成资料 → 审核员核验 → `reviewed` → 检索验收 3 道必测问题通过 → 系统管理员 `publish` → 数据库 `published`。

反例：未经检索验收就标记 `approved` 并对 `student` 开放，导致检索时无可信答案。

## 资料生命周期：来源说明

- 来源：`SRC-POLICY-DOC-LIFECYCLE-001` BHZD 项目内部"资料生命周期规范"，版本 1.0.0。
- 来源：`SRC-POLICY-RAG-EVAL-001` BHZD 项目内部"RAG 检索验收规范"，版本 1.0.0。
- 来源：`SRC-POLICY-PUBLISH-001` BHZD 项目内部"资料发布流程"，版本 1.0.0。
- 待核验：未核验不同发布环境下门禁条件的差异。
