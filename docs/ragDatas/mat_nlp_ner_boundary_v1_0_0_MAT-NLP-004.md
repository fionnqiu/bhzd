---
id: MAT-NLP-004
title: 命名实体识别（NER）中的 BIO 与 BIOES 标签边界规则
version: v1.0.0
source: SRC-LS-TEXT-LABELS-001
source_refs: SRC-CRF-NER-001
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

# 命名实体识别（NER）中的 BIO 与 BIOES 标签边界规则

本资料介绍 NER 任务中常见的 BIO 与 BIOES 标签体系，给出编码规则、跨片段处理、嵌套实体处理以及评估时的对齐方法。读者对象是标注员、标注平台工程师与教学管理员。

## NER 标签体系：核心定义

BIO 是一种把序列标注问题分成三类的编码方案：

- `B-X`：某实体类别 `X` 的起始 token。
- `I-X`：实体类别 `X` 的内部（非起始）token。
- `O`：不属于任何实体的 token。

BIOES 在 BIO 基础上扩展为：

- `B-X`：单 token 实体的开始（即该 token 构成完整实体）。
- `I-X`：实体内部 token。
- `E-X`：实体的结束 token。
- `S-X`：单 token 实体，独立成类。
- `O`：非实体。

BIOES 在严格评估时通常更稳定，但需要人工和模型都遵循同一约定。

## NER 标签：边界规则与对齐

- 连续两个相邻同类实体被另一个同类实体"打断"时，必须以 `B-X` 重新开始，而不是继续 `I-X`。
- 不同类别实体的边界必须严格分到 token 级，不允许多个 token 同时属于多个实体。
- 中文分词的边界与 NER 边界不必一致：如果分词把"北京大学"切成单字，仍应保留 4 字连续实体而不是强制对齐。

评估对齐采用"严格模式"（边界与类别都必须完全一致）和"宽松模式"（允许边界偏移 ±1 token）两种。BHZD 教学场景默认采用严格模式。

## NER 标签：嵌套实体处理

当一个实体出现在另一个实体内部时，称为嵌套实体。常见处理方式：

- 平面标注法：只标注最长或最外层实体，由任务定义决定选哪一个。
- 层级标注法：为每个层级分配独立标签，例如"机构/嵌套机构/嵌套嵌套机构"。
- 多输出层：在模型端输出多层标签，每层处理一种嵌套深度，但标注流程会很重。

BHZD 教学默认采用平面标注法并显式声明选哪一层，避免同一样本被不同标注员按不同层级归档。

## NER 标签：评估指标与混淆

NER 的 P/R/F1 通常使用 `seqeval`、`conlleval` 等脚本，按"实体级别"统计而非 token 级别。常见混淆：

- 用 token 级 accuracy 替代实体级 F1：高分 accuracy 但实体级 F1 很低，常见于非实体 token 占多数的句子。
- 用宽松匹配掩盖错配：当严格 F1 与宽松 F1 差距很大时说明边界错误多。
- 不一致的实体类别集合：训练集标签集合与测试集不一致会引发标签未声明错误。

## NER 标签：常见误区

- 把"机构 + 地名"嵌套实体同时标注到同一行的不同 token 上，造成解析时主键冲突。
- 在 `I-X` 后接 `O` 再接 `I-X`：实际是错误，应使用 `B-X` 重新开始。
- 拼写错误或词形变化被错认为新实体类别，使实体集合持续膨胀。
- 对中文长实体不切 token，直接把整段当一个实体，破坏评估器对齐规则。

## NER 标签：示例与反例

正例（虚构示例）：句子"小明在阿里巴巴北京公司工作"，标注 `小/B-PER 明/I-PER 在/O 阿/B-ORG 里/I-ORG 巴/I-ORG 巴/I-ORG 北/B-LOC 京/I-LOC 公/I-ORG 司/I-ORG 工/O 作/O`。

反例：把"阿里巴巴北京公司"整体标成 `B-ORG`，省去内部 token 处理，导致评估器无法识别内部边界，实体级 F1 下降。

## NER 标签：来源说明

- 来源：`SRC-LS-TEXT-LABELS-001` Label Studio 关于 NER 标签的基础说明，访问 2026-07-12。
- 来源：`SRC-CRF-NER-001` Lafferty 等人在 2001 年发表的 CRF 序列建模文献的 BIO 标注部分。
- 待核验：未核验不同评估脚本（`seqeval` 与 `conlleval`）对中文切词的边界处理差异。
