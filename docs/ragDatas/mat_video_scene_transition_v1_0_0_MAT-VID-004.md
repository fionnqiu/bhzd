---
id: MAT-VID-004
title: 视频场景切分与转场标注规则
version: v1.0.0
source: SRC-ACTIVITYNET-001
source_refs: SRC-VIDAT-001,SRC-POLICY-VIDEO-EVENT-001
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

# 视频场景切分与转场标注规则

本资料解释 BHZD 平台视频场景（shot / scene）切分与转场类型标注规则。读者对象是视频标注员、教学管理员。

## 视频场景切分：核心定义

视频场景切分是把连续视频按语义或视觉边界切成多个场景，每个场景可独立标注其内容与对象。转场（transition）指场景之间的衔接方式。

每个场景有 `scene_id`、起止时间、转场类型、场景内事件集合。

## 视频场景切分：转场类型

常见转场类型：

- `cut`：硬切，最常见的剪辑切换。
- `fade`：淡入淡出，亮度渐变。
- `dissolve`：溶解，前一画面与后一画面短暂叠加。
- `wipe`：扫换，下一画面逐渐替代前一画面。
- `motion`：运动转场，前后画面共享运动方向。

不同任务可能定义不同转场集合，以项目词表为准。

## 视频场景切分：边界判定

- 硬切：帧级别精确到变化首帧和末帧。
- 渐变转场：取亮度/颜色变化 ±50% 的中点作为边界。
- 镜头连续 2 秒以上视为同一场景。
- 镜头内运动不应被错判为切分。

边界偏差容忍度：1 帧。

## 视频场景切分：场景内对象

场景内对象标注：

- 每个对象仅在出现的场景中注册。
- 跨场景同对象使用 `entity_id` 串接。
- 在场景中消失的对象按 `disappearance_reason` 标注（出框 / 关闭镜头 / 遮挡 / 截断）。
- 短时消失 ≤ 2 秒且场景连续，仍视为同一对象。

## 视频场景切分：与事件标注的关系

- 事件可以跨越多个场景，事件层独立于场景层。
- 跨场景事件必须按场景拼接时间区间。
- 场景切分是数据预处理；事件标注是任务本体。
- 两者均依赖转场边界判定，但目标不同。

## 视频场景切分：常见误区

- 把物体快速运动当作场景切换。
- 渐变转场中错点边界过早或过晚。
- 场景内对象按场景 ID 重新计数，导致同对象多 ID。
- 把转场类型缺失写为 `unknown`，未做合理默认。

## 视频场景切分：示例与反例

正例（虚构示例）：2 分钟视频从室内镜头硬切到室外镜头。第一场景 0-50 秒（cut），第二场景 50-120 秒（cut）。

反例：把快速推拉镜头误判为 cut，导致后续对象一致性被打断。

## 视频场景切分：来源说明

- 来源：`SRC-ACTIVITYNET-001` ActivityNet 文档关于场景切分参考。
- 来源：`SRC-VIDAT-001` VidAT 平台视频标注工具文档。
- 来源：`SRC-POLICY-VIDEO-EVENT-001` BHZD 项目内部"视频行为事件策略"，版本 1.0.0。
- 待核验：未核验长视频中转场标注的一致性。
