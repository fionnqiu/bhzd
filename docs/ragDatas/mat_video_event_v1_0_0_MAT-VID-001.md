---
id: MAT-VID-001
title: 视频行为事件标注的起止时间与分类规则
version: v1.0.0
source: SRC-ACTIVITYNET-001
source_refs: SRC-CHARADES-001,SRC-POLICY-VIDEO-EVENT-001
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

# 视频行为事件标注的起止时间与分类规则

本资料覆盖 BHZD 平台视频行为事件标注的事件定义、起止时间判定、分类一致性。读者对象是视频标注员、行为质检工程师、教学管理员。

## 行为事件标注：核心定义

行为事件指视频中具有明确起止时间、对应单一语义动作或状态的时间区间。每个事件用 `(start_time, end_time, label, confidence)` 四元组描述。

事件可重叠、嵌套或互斥，由任务词表显式声明。

## 行为事件标注：起止时间判定

- 起止时间采用 ISO 8601 字符串或毫秒整数，本项目默认毫秒整数 `[start_ms, end_ms)`。
- 起止判定按"动作可观察开始点"和"动作可观察结束点"。
- 同一动作可能被多镜头拍摄，应按事件实际起止时间跨镜头记录。
- 动作结束与下一动作开始重合时，前者 `end_ms` 等于后者 `start_ms`，不重叠。

## 行为事件标注：分类与互斥

- 互斥事件组（如 `sit | stand | walk`）在同一时间只能有一个标签。
- 非互斥事件组（如 `holding_object | looking_at_phone`）可在同一时间叠加。
- 多人物场景：每个事件绑定 `person_track_id`，避免动作张冠李戴。
- 跨类相似动作（如 `walk` 与 `run`）使用细颗粒字段如 `speed_hint`，不引入新标签。

## 行为事件标注：与外部数据集的关系

外部事实包括：

- ActivityNet 时间边界采用秒级浮点（外部事实）。
- Charades 时间边界采用秒级浮点并允许空事件（外部事实）。
- 本项目采用毫秒整数、左闭右开（本地约定）。
- 标注员不得将外部数据集的浮点字段直接搬入，应转换并四舍五入到毫秒。

## 行为事件标注：常见误区

- 用秒级浮点字段导致无法跨项目对齐。
- 多个事件起止时间交错但不互斥，导致计算 frame mAP 时逻辑混乱。
- 跨类相似动作新增独立标签，破坏词表。
- 动作起止判定过宽，把"刚要坐下"也纳入 `sit` 区间。

## 行为事件标注：示例与反例

正例（虚构示例）：从 0 至 10 秒视频，5 至 7 秒有人站立穿外套。事件 `start_ms=5000, end_ms=7000, label=put_on_jacket, person_track_id=t1`。

反例：把同一动作标 `start=4.8s, end=7.2s`，使用浮点字段，跨项目评测时精度丢失。

## 行为事件标注：来源说明

- 来源：`SRC-ACTIVITYNET-001` ActivityNet 时间字段说明。
- 来源：`SRC-CHARADES-001` Charades 视频行为标注格式说明。
- 来源：`SRC-POLICY-VIDEO-EVENT-001` BHZD 项目内部"视频行为事件策略"，版本 1.0.0。
- 待核验：未核验真实数据集 `put_on_*` 标签的细颗粒定义边界。
