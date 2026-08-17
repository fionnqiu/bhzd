---
id: MAT-IMG-001
title: 图像矩形框标注的坐标规范与遮挡截断判定
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

# 图像矩形框标注的坐标规范与遮挡截断判定

本资料覆盖 BHZD 平台图像矩形框（bounding box）标注的坐标格式、遮挡截断判定与重叠规则。读者对象是图像标注员、视觉质检员与教学管理员。

## 矩形框标注：核心定义

矩形框标注使用 `[x_min, y_min, x_max, y_max]` 四元组描述目标在图像中的位置，采用"像素坐标、左上原点、`x_max`/`y_max` 排除在外"的约定。

任何标注都必须使用整数像素坐标。小数坐标（如 `x_min=10.5`）在本项目中不被接受。

## 矩形框标注：遮挡截断判定

遮挡（occlusion）与截断（truncation）是两个独立的状态字段，必须分开标注：

- `occluded=true` 表示目标存在但被其他物体遮挡 ≥ 30% 面积。仍按完整目标的标注范围画框，不要缩小到可见部分。
- `truncated=true` 表示目标部分离开图像边缘。仍按完整目标的标注范围画框，让 `x_min`/`y_min`/`x_max`/`y_max` 出现负数或超出图像宽高。
- 同时存在遮挡与截断时两个字段都为 `true`，不互相替代。

不要因为目标小就缩小框；尺寸小应反映在 `area` 派生字段或训练样本权重中。

## 矩形框标注：重叠与分组

多目标重叠时按以下顺序处理：

1. 同类别目标相互遮挡：分别画完整框，并在 `occluded=true` 处记录遮挡关系。
2. 不同类别遮挡：上层目标画完整框，下层目标的 `occluded=true`。
3. 强语义分组（如"车上的人"）：可使用 `group_id` 字段关联，不通过矩形框重叠解决。

矩形框不应"裁剪"到其他目标的边界——这会破坏评测的对齐语义。

## 矩形框标注：与外部格式边界

以下属于外部事实，不替本项目决定坐标约定：

- COCO 格式使用 `[x_min, y_min, width, height]` 而非两对角点（外部事实）。
- PASCAL VOC 使用 `[xmin, ymin, xmax, ymax]` 左上原点（外部事实）。
- BHZD 项目采用 `[x_min, y_min, x_max, y_max]` 整数像素、左上原点（本地约定）。
- 标注员不得混合使用不同格式字段；任何切换必须升级项目版本。

## 矩形框标注：常见误区

- 遮挡时缩小框，导致评测 IoU 下降。
- 截断时把 `x_max` 限制在图像边界处，丢失真实信息。
- 用小数坐标与现有数据合并，导致量化误差。
- 把遮挡与截断使用同一字段标注。

## 矩形框标注：示例与反例

正例（虚构示例）：行人横穿图像，左侧 30% 被垃圾桶遮挡，框 `[12, 100, 240, 380]` 加 `occluded=true, truncated=false`。

反例：行人框 `[12, 100, 200, 380]`，把被遮挡部分截掉，导致训练时模型学不到完整人类形态。

## 矩形框标注：来源说明

- 来源：`SRC-CVAT-BBOX-001` CVAT 文档关于矩形框字段定义。
- 来源：`SRC-COCO-ANNOTATIONS-001` COCO 标注格式官方说明。
- 来源：`SRC-POLICY-IMAGE-BBOX-001` BHZD 项目内部"矩形框与遮挡策略"，版本 1.0.0。
- 待核验：未核验真实工程实践中 IoU 阈值与遮挡比例的换算。
