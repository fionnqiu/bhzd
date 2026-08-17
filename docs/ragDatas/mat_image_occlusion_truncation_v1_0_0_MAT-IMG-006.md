---
id: MAT-IMG-006
title: 图像遮挡与截断的双重边界判定与字段独立标注
version: v1.0.0
source: SRC-CVAT-BBOX-001
source_refs: SRC-COCO-ANNOTATIONS-001,SRC-POLICY-IMAGE-BBOX-001
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

# 图像遮挡与截断的双重边界判定与字段独立标注

本资料解释 BHZD 平台图像遮挡（occlusion）与截断（truncation）两个独立标注字段的语义差异、判定阈值与组合规则。读者对象是图像标注员、视觉质检员、教学管理员。

## 遮挡与截断：核心定义

遮挡指目标本身仍然存在于场景中，但被其他物体或目标遮住了部分像素。截断指目标的部分离开了图像边界，造成不可见。

二者是两个独立的判定维度，必须分别写入独立字段，不可合并到同一标志位。

## 遮挡与截断：判定阈值

遮挡判定通常按被遮挡像素占目标完整外接像素的比例：

- 被遮挡 ≥ 30% → `occluded=true`。
- 被遮挡 10% 至 30% → 由任务定义决定是否计入 `occluded=true`。
- 被遮挡 < 10% → `occluded=false`，按完整目标标注。

截断判定按目标离开图像边界的程度：

- 任意部位跨界（哪怕 1 像素） → `truncated=true`。
- 完全位于图像边界内 → `truncated=false`。
- 整段在图像外不计入标注，不写 `truncated` 而是删除该目标。

## 遮挡与截断：字段独立性

字段独立性按以下规则保证：

- `occluded` 与 `truncated` 互不影响，可以同时为 `true`。
- `occluded` 不替代 `iscrowd`；密集小目标仍使用 `iscrowd`。
- `truncated` 不替代"目标过小"或"目标位于图像角落"；只描述跨界。
- `truncated=true` 时 `occluded` 字段仍按遮挡独立判定。

例如一只手部在图像边缘同时被行人遮挡，应记 `occluded=true, truncated=true` 两个独立标志。

## 遮挡与截断：组合规则

| occluded | truncated | 含义 |
| --- | --- | --- |
| false | false | 完整可见目标，最简单 |
| true | false | 完整可见于图内，被其他目标遮挡 |
| false | true | 离开图像边缘，未被其他目标遮挡 |
| true | true | 同时存在遮挡与截断，最复杂 |

不论哪种组合，目标外接矩形框都按完整目标标注，不缩小、不裁剪。

## 遮挡与截断：常见误区

- 用 `occluded=true` 替代"目标被自己遮挡"。
- 把 `truncated=true` 写入目标在图像内但接近边界的样本。
- 删除被严重遮挡的目标，导致密集场景漏检。
- 用估算的可见边界替换完整矩形框。

## 遮挡与截断：示例与反例

正例（虚构示例）：行人头部正与图像上沿相切，并被前车遮挡 40% 面积。提交完整矩形框 `occluded=true, truncated=true`。

反例：仅标注可见头肩部，矩形缩小到局部，并把 `truncated` 字段留空，丢失遮挡截断的全部信息。

## 遮挡与截断：来源说明

- 来源：`SRC-CVAT-BBOX-001` CVAT 关于 `occluded` 与 `truncated` 字段定义。
- 来源：`SRC-COCO-ANNOTATIONS-001` COCO 关于 `iscrowd` 字段与遮挡示例说明。
- 来源：`SRC-POLICY-IMAGE-BBOX-001` BHZD 项目内部"矩形框与遮挡策略"，版本 1.0.0。
- 待核验：未核验不同实例分割场景中 occluded/truncated 的额外定义。
