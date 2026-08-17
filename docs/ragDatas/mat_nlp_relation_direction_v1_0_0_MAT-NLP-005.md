---
id: MAT-NLP-005
title: 关系抽取任务中的关系方向、实体角色与冲突判定
version: v1.0.0
source: SRC-TACRED-001
source_refs: SRC-SEM-EVAL-001,SRC-POLICY-RELATION-001
source_type: textbook
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

# 关系抽取任务中的关系方向、实体角色与冲突判定

本资料解释 BHZD 平台关系抽取任务的关系类型方向、实体角色、冲突判定与评估方法。读者对象是文本标注员、教学管理员、关系抽取工程师。

## 关系抽取：核心定义

关系抽取（Relation Extraction, RE）指从文本中识别两个或多个实体之间的关系，并给出关系类型、方向、置信度。

BHZD 平台采用有向关系模式 `(subject, relation, object)` 三元组，方向由 schema 显式声明。

## 关系抽取：关系方向

- `relation` 是有向的："A 是 B 的创始人" 与 "B 的创始人是 A" 是同一关系，但方向相反。
- 对称关系（如"配偶"）在 schema 中标记 `is_symmetric=true` 时，无方向信息。
- 不对称关系标注时必须明确主体与客体；颠倒会导致评测错误。
- 同一对实体可能存在多种关系（如同时是"竞争对手"与"合作伙伴"），按 schema 多标签记录。

混淆方向会直接降低 F1，请在校准时特别关注。

## 关系抽取：实体角色与角色约束

不同关系对主体/客体有角色约束：

- `born_in(subject=person, object=location)`：不允许主体是组织。
- `acquired(subject=company, object=company)`：主体与客体必须都是组织。
- `headquartered_in(subject=org, object=location)`：客体必须是地点。

违反角色约束的关系即使表面合理也不应标注，应放入"边界样本库"。

## 关系抽取：冲突判定

同一对实体被多次标注时，按以下规则处理：

- 同一关系类型：保留置信度最高；置信度相同保留人工复核。
- 不同关系类型：除非 schema 允许多标签，否则记为冲突并由质检员决定。
- 关系相反（如 `parent_of` 与 `child_of`）：保留两版本，由质检员决定。
- 冲突结果记录在 `relation_conflict_log`，不删除原始标注。

## 关系抽取：与外部数据集的关系

- TACRED 提供 42 类关系定义（外部事实）。
- SemEval-2010 Task 8 提供 19 类关系（外部事实）。
- BHZD 项目采用何种关系集合由词表决定，不是行业默认。
- 标注员不得把外部数据集的关系直接搬入，必须按 schema 标注。

## 关系抽取：常见误区

- 主体与客体颠倒。
- 角色约束未严格遵守。
- 同一关系在不同样本中允许非对称误标。
- 删除冲突样本而非记录冲突。

## 关系抽取：示例与反例

正例（虚构示例）："马云创立了阿里巴巴"，标 `(subject=马云, relation=founder_of, object=阿里巴巴)`。

反例：同一句标 `(subject=阿里巴巴, relation=founder_of, object=马云)`，方向颠倒导致评测 F1 下降。

## 关系抽取：来源说明

- 来源：`SRC-TACRED-001` TACRED 关系抽取数据集说明。
- 来源：`SRC-SEM-EVAL-001` SemEval-2010 Task 8 关系抽取任务说明。
- 来源：`SRC-POLICY-RELATION-001` BHZD 项目内部"关系抽取任务策略"，版本 1.0.0。
- 待核验：未核验具体关系 schema 与外部数据集的最新对齐情况。
