---
id: MAT-MUL-001
title: 音视频多模态对齐标注的时戳同步与跨模态参考
version: v1.0.0
source: SRC-POLICY-MULTIMODAL-ALIGN-001
source_refs: SRC-KALDI-DATA-PREP-001,SRC-POLICY-AUDIO-SEGMENT-001,SRC-ACTIVITYNET-001
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

# 音视频多模态对齐标注的时戳同步与跨模态参考

本资料覆盖 BHZD 平台多模态（音视频同步、人脸与文本、姿态与语音）标注任务的时戳同步、跨模态参考与错误处理。读者对象是多模态标注员、教学管理员。

## 多模态对齐：核心定义

多模态对齐指同一素材多通道（音、视频、文本、传感器）的同一对象标注出时间一致的语义。多模态对齐的关键是"同一时间点的多通道参考"，而不是"每个模态独立标注"。

对齐采用毫秒整数时间戳 `[start_ms, end_ms)`，跨模态必须使用统一时钟。

## 多模态对齐：时钟同步

- 统一时钟：以视频帧率为基准，音频按帧率换算毫秒偏移。
- 误差容忍度：音视频偏移 ≤ 80 ms；其他模态 ≤ 100 ms。
- 偏移计算：使用轨道起始差 + 时间戳差；不允许每段单独计算。
- 时钟校准：在每段素材开头至少 200 ms 的"同步标定"区间，由标注员对齐到 0 ms。

## 多模态对齐：跨模态参考

不同模态的同一对象应使用同一 `entity_id`：

- 视频中说话人与音频中说话人绑定到 `entity_id`。
- 关键点姿态与目标 ID 绑定到 `entity_id`。
- 文本对话与说话人转写按 `entity_id` 关联。
- 多模态标签与单模态标签通过 `entity_id` 串成事件链。

`entity_id` 与说话人分离的 `speaker_id` 可以并存，按任务要求决定。

## 多模态对齐：边界与跨镜头

- 跨镜头连续动作：保留 `entity_id`，只重新登记镜头边界。
- 跨模态时间戳不一致：按视频时间戳为准，音频按比例推算。
- 字幕与语音错位：以音频真实时间戳为准，字幕作为参考。
- 出现明显配音误差：单独记录 `dub_error=true`，不删除原标注。

## 多模态对齐：常见误区

- 每个模态独立标注，最后人工对齐，误差不收敛。
- 视频按帧号、音频按毫秒，跨模态对齐需手工换算。
- 把字幕当作语音，不校对实际音频内容。
- 跨镜头改变 `entity_id`，丢失同一对象连续性。

## 多模态对齐：示例与反例

正例（虚构示例）：新闻片段中人物说话，"你好"音频区间 `[1230, 1680)` ms，对应视频嘴部动作 `[1220, 1680)` ms，文本转写同样在 `[1230, 1680)` ms。

反例：把音频 `[1230, 1680)`、视频 `[1220, 1680)`、文本 `[1240, 1700)` 各自独立标注，事后无法对齐。

## 多模态对齐：来源说明

- 来源：`SRC-POLICY-MULTIMODAL-ALIGN-001` BHZD 项目内部"多模态对齐策略"，版本 1.0.0。
- 来源：`SRC-KALDI-DATA-PREP-001` Kaldi 音频时段文档。
- 来源：`SRC-POLICY-AUDIO-SEGMENT-001` BHZD 音频分段策略。
- 来源：`SRC-ACTIVITYNET-001` ActivityNet 时间字段说明。
- 待核验：未核验多模态数据集真实版的 `entity_id` 字段命名。
