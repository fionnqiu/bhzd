---
id: MAT-PLT-002
title: RAG 查询改写与召回参数配置原则
version: v1.0.0
source: SRC-POLICY-QUERY-REWRITE-001
source_refs: SRC-POLICY-RAG-PARAMS-001
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

# RAG 查询改写与召回参数配置原则

本资料覆盖 BHZD 平台 RAG 子系统的查询改写机制、可调参数与安全降级策略。读者对象是平台管理员、RAG 工程师。

## 查询改写：核心定义

查询改写（Query Rewriting）指对用户的短查询或不完整查询，先由语言模型扩写为更易于检索的完整查询，再送入向量库检索。

它不是替代检索，而是补充语义信息以提升召回质量。

## 查询改写：触发条件

- 原始查询 token 数 ≤ 6。
- 原始查询完整度评分 < 0.6（由启发式判断）。
- 检索首轮结果 score < 0.35。
- 关闭模式（人工辅助浏览）下不触发。

任意条件成立时启用查询改写。

## 查询改写：扩写规则

- 保留原始实体名词，不替换或删除。
- 添加同义词 / 别名 / 编号，例如"宏平均 F1"扩为"宏平均 F1 macro-F1 公式 计算"。
- 不引入原问题中不存在的实体。
- 不替原问题做事实推断。

扩写后查询长度上限 80 token。

## 查询改写：可调参数

RAG 参数配置页允许调整：

- `top_k`：检索切片数量，默认 5，上限 50。
- `temperature`：LLM 生成温度，默认 0.2，仅在启用回答生成时有效。
- `top_p`：核采样阈值，默认 0.9。

不允许通过参数页调整的项（策略、Prompt、审核）由系统内置逻辑控制。

## 查询改写：安全降级

- 改写 API 异常：回退到原始查询，不阻塞主流程。
- 改写结果为空或异常 token：使用原始查询。
- 改写延迟过高（> 500ms）：跳过改写直接检索。
- 关闭开关 `query_rewrite_enabled=false`：完全跳过。

异常时不得向用户暴露错误细节。

## 查询改写：评估指标

- 召回率（Recall@5）：改写后正确切片出现在前 5 的比例。
- MRR（Mean Reciprocal Rank）：正确排名的平均倒数。
- 改写失败率：捕获异常 / 总调用次数。
- 改写延迟 P95。

每周末对比开关开启前后指标，作为调优依据。

## 查询改写：常见误区

- 改写引入原问题未提及的实体。
- 在不需要改写的长问题上强行改写，反而降低召回。
- 把 `temperature` 调到 1.0 让回答发挥，偏离事实。
- 改写失败不降级，导致整个会话卡顿。

## 查询改写：示例与反例

正例（虚构示例）：用户问"宏平均 F1 怎么算"，改写为"宏平均 F1 macro-F1 公式 计算 多分类"，召回到 `MAT-NLP-001` 第 1 节。

反例：用户问"宏平均 F1 怎么算"，改写为"宏平均 F1 在深度学习中的优点"，引入不存在的实体，召回结果跑偏。

## 查询改写：来源说明

- 来源：`SRC-POLICY-QUERY-REWRITE-001` BHZD 项目内部"查询改写规范"，版本 1.0.0。
- 来源：`SRC-POLICY-RAG-PARAMS-001` BHZD 项目内部"RAG 参数配置规范"，版本 1.0.0。
- 待核验：未核验不同语言下查询改写规则的稳定性。
