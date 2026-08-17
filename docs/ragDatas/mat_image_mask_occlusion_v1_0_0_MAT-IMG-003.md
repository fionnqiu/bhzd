---
id: MAT-IMG-003
title: 图像实例分割遮罩标注与遮挡截断的区分
version: v1.0.0
source: SRC-CVAT-MASK-001
source_refs: SRC-COCO-ANNOTATIONS-001,SRC-POLICY-IMAGE-SEGMENT-001
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

# 图像实例分割遮罩标注与遮挡截断的区分

本资料覆盖 BHZD 平台实例分割 mask 标注的格式、遮挡截断字段、嵌套目标处理。读者对象是实例分割标注员、视觉质检员和教学管理员。

## 实例分割遮罩：核心定义

实例分割遮罩是逐像素的二进制或标签图像。每个实例有独立 `instance_id`，多个实例共享同一类别标签但保持 `instance_id` 唯一。

存储格式采用 RLE（Run-Length Encoding）压缩的二进制 mask，避免 PNG 大文件开销。

## 实例分割遮罩：遮挡截断区分

遮挡截断字段独立标注：

- `occluded`：目标存在但被遮挡 ≥ 30% 像素。mask 仍按完整目标绘制。
- `truncated`：目标部分离开图像边缘。mask 仍按完整目标绘制，超出图像部分由 IoU 评估自动截断。
- `iscrowd`：目标密集小目标群，使用单独 RLE 编码降低误差。`iscrowd=true` 不代替遮挡截断字段。

任意状态下都应绘制完整目标 mask，不要为减少手绘工作量缩小范围。

## 实例分割遮罩：嵌套目标

- 同类别实例嵌套（如靠垫中的人）按两个独立 `instance_id` 标注，前景在上层。
- 不同类别嵌套（如车前行人）按可见边界标注完整 mask，遮挡目标也保留完整 mask。
- 婴儿轮廓边缘模糊时使用 `confidence` 字段记录不确定度，不使用模糊擦除。
- 同一图像出现 50 个以上同类小目标时使用 `iscrowd` 简化。

## 实例分割遮罩：与多边形的关系

- mask 比多边形更精细，适用于医学影像、遥感等需要像素级精度的场景。
- 标注员应从多边形入手，再用 mask 工具细化；不应直接在 mask 上画点。
- 自动化工具可基于 mask 自动生成多边形，但反之不成立。
- 多边形与 mask 共存时，mask 为权威标注，多边形仅作为辅助校验。

## 实例分割遮罩：常见误区

- 为减少工作量裁剪 mask 到可见区域。
- 嵌套目标合并为单个 instance。
- 用 `iscrowd` 替代遮挡字段。
- RLE 编码错误或使用旧版 COCO RLE 格式导致解码失败。

## 实例分割遮罩：示例与反例

正例（虚构示例）：一只被电线杆部分遮挡的猫，绘制完整猫形 mask 含电线杆像素，`occluded=true`，`truncated=false`。

反例：把猫的 mask 裁剪到电线杆左侧可见区域，丢失被遮挡的躯干特征，训练时模型无法识别完整猫形。

## 实例分割遮罩：来源说明

- 来源：`SRC-CVAT-MASK-001` CVAT 实例分割字段定义。
- 来源：`SRC-COCO-ANNOTATIONS-001` COCO 关于 `iscrowd` 与 RLE 编码说明。
- 来源：`SRC-POLICY-IMAGE-SEGMENT-001` BHZD 项目内部"实例分割策略"，版本 1.0.0。
- 待核验：未核验当前 RLE 编码格式与最新 COCO API 的兼容。
