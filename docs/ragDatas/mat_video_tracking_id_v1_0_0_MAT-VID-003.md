---
id: MAT-VID-003
title: 视频目标跟踪 ID 一致性与跨帧连续性规则
version: v1.0.0
source: SRC-MOT-CHALLENGE-001
source_refs: SRC-TRACKER-BENCHMARK-001,SRC-POLICY-VIDEO-TRACK-001
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

# 视频目标跟踪 ID 一致性与跨帧连续性规则

本资料覆盖 BHZD 平台多目标跟踪（MOT）任务的 ID 一致性、消失再现、短时遮挡处理。读者对象是视频标注员、MOT 质检员、教学管理员。

## 目标跟踪：核心定义

多目标跟踪指跨多帧为同一目标分配稳定 `track_id`。同一目标在不同帧中即使外观变化、姿态变化或短暂遮挡，仍保持同一 ID。

BHZD 项目采用稠密跟踪（Dense Tracking）+ 短时遮挡的简单重分配策略。

## 目标跟踪：ID 一致性规则

- 同一目标的 `track_id` 在时间轴上单调。
- ID 一旦分配，除非目标确认离开镜头，否则不要重新分配。
- ID 重用必须等原 ID 完全消失（≥ 1 秒）后再分配，避免误关联。
- 多人场景中每个人的 ID 全程不变，不因遮挡切换。

## 目标跟踪：消失再现与短遮挡

- 目标部分遮挡（≥ 30% 像素被遮挡）：保持原 `track_id`，并在遮挡帧保留预测框。
- 目标短暂离开镜头（≤ 1 秒）：保留原 `track_id`，使用预测框标注。
- 目标完全离开镜头 ≥ 1 秒后再次出现：分配新 `track_id` 并记录 `re_identified_from`。
- 目标消失期间不可在同一画面出现两次，避免"分身"。

## 目标跟踪：跨帧特征稳定性

外观特征在以下情况会变化，标注员仍需保持 ID：

- 人物转身导致面部不可见，仍保持原 ID。
- 服装变化（如脱外套）按任务说明决定是否保持 ID。
- 光照剧烈变化导致颜色差异大，按运动趋势判断。
- 多人重叠交错通过 `track_id` + 时间窗口内位置连续性判断。

## 目标跟踪：评估指标

跟踪任务使用以下评估指标：

- MOTA：多目标跟踪准确率，考虑 ID 切换、漏报、误报。
- IDF1：识别 F1，衡量 ID 一致性的核心指标。
- MOTP：多目标跟踪精度，衡量框定位精度。
- ID Switches：ID 切换次数，应尽量低。

BHZD 发布门槛为 MOTA ≥ 0.6、IDF1 ≥ 0.5、ID Switches ≤ 5% 总跟踪目标数。

## 目标跟踪：常见误区

- 目标被遮挡时分配新 ID。
- 短时离开镜头后用旧 ID 但不更新框，定位失真。
- 不同外观（如换装）直接换 ID，丢失同一目标。
- 评估时把遮挡区间误算为 ID Switches。

## 目标跟踪：示例与反例

正例（虚构示例）：两人在 5 至 15 秒前后走过镜头，目标 A 全程保持 ID=1，目标 B 全程保持 ID=2。

反例：目标 A 在 8 秒被目标 B 短暂遮挡后 ID 改为 3，导致后续轨迹断裂。

## 目标跟踪：来源说明

- 来源：`SRC-MOT-CHALLENGE-001` MOT Challenge 数据集评估指标说明。
- 来源：`SRC-TRACKER-BENCHMARK-001` MOT Benchmark 跟踪评估文档。
- 来源：`SRC-POLICY-VIDEO-TRACK-001` BHZD 项目内部"视频跟踪策略"，版本 1.0.0。
- 待核验：未核验真实 MOT 评测平台对 IDF1 计算的具体实现差异。
