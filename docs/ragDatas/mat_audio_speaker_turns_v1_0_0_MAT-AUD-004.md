---
id: MAT-AUD-004
title: 音频说话人轮次与分离标注规则
version: v1.0.0
source: SRC-KALDI-DATA-PREP-001
source_refs: SRC-PRAAT-TEXTGRID-001,SRC-POLICY-AUDIO-DIARIZATION-001
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

# 音频说话人轮次与分离标注规则

本资料解释 BHZD 平台说话人轮次（speaker turn）标注与说话人分离（speaker diarization）任务的标签约定。读者对象是音频标注员、对话质检员与教学管理员。

## 说话人轮次：核心定义

说话人轮次指一段多人对话音频中，由同一说话人占据的连续语音区间。每个轮次有唯一 `speaker_id`，且同一说话人在同一会话的不同轮次共享相同 `speaker_id`。

说话人分离的最终产物是 `(start_ms, end_ms, speaker_id, transcript)` 四元组列表，按时间升序排列且互不重叠。

## 说话人轮次：标签约定

- `speaker_id` 使用题目下发的命名空间（如 `spk_001`、`spk_002`），不在数据中泄漏真实身份。
- 同一会话内的相同说话人必须保持同一 `speaker_id`，即使中间隔了其他说话人。
- 转写文本属于该说话人在该轮次的话语，不包含其他人插话。
- 跨轮次的同一说话人应使用相同 `speaker_id`，禁止引入 `spk_001_bis` 等变体。

## 说话人轮次：边界判定

边界判定按以下顺序识别：

1. 明显的说话人切换（音色、能量、共振峰明显变化）。
2. 同一说话人内超过 350 ms 的沉默区间。
3. 多人同时说话（overlap）时使用 `overlap_speakers` 字段记录重叠说话人列表。

仅靠音量变化不足以判定说话人切换；同一说话人在不同情绪下音量差异很大。

## 说话人轮次：说话人分离要求

说话人分离任务在常规轮次标注基础上额外要求：

- 同时说话区间必须拆为两条独立轮次，分别记录 `start_ms` 和 `end_ms`，并使用相同的重叠时间区间。
- 转写文本使用 `[overlap]` 标记不同说话人的重叠部分。
- 呼吸声、笑声等非语音事件可单独列为 `non_speech_event`，不计入轮次。
- 当连续语音超过 10 秒仍未检测到说话人切换，提示标注员复核，避免独白误判。

## 说话人轮次：常见误区

- 把同一说话人的两次发言错标为不同 `speaker_id`，破坏一致性。
- 把背景电视声或环境人声当作主轮次。
- 在重叠区间只标一个人，丢失多人对话信息。
- 使用真实姓名/电话作为 `speaker_id`，违反脱敏规则。

## 说话人轮次：示例与反例

正例（虚构示例）：客服电话中，客户在 0 至 5 秒说"你好"，客服在 5.4 至 10.2 秒回应"您好请问有什么可以帮您"。两段 `speaker_id` 分别为 `spk_client` 和 `spk_agent`。

反例：把同一段音频整体标为 `speaker=agent`，转写中掺杂客户发言，丢失轮次结构。

## 说话人轮次：来源说明

- 来源：`SRC-KALDI-DATA-PREP-001` Kaldi 数据准备文档关于 segments 与 speaker turn 段落。
- 来源：`SRC-PRAAT-TEXTGRID-001` Praat TextGrid 关于多说话人层级的说明。
- 来源：`SRC-POLICY-AUDIO-DIARIZATION-001` BHZD 项目内部"说话人分离任务策略"，版本 1.0.0。
- 待核验：未核验真实客服录音中 `overlap_speakers` 字段的兼容性。
