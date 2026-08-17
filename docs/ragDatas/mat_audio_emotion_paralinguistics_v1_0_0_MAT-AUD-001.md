---
id: MAT-AUD-001
title: 音频情感与副语言事件的双轨标注规则
version: v1.0.0
source: SRC-W3C-EMOTIONML-001
source_refs: SRC-KALDI-DATA-PREP-001,SRC-PRAAT-TEXTGRID-001,SRC-POLICY-AUDIO-TASK4-001
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

# 音频情感与副语言事件的双轨标注规则

本资料解释 BHZD 平台 audio 任务的双轨标注约定：同一音频片段分别提交"整体情感标签"与"带时间边界的副语言事件"。读者对象是音频标注员、质检工程师和教学管理员。

## 双轨标注：核心定义

双轨标注指同一音频在同一题项中要给出两类不重叠的结果：

- 整体情感标签 `emotion_label`：从题目给定的有限集合中选取一个表示整段片段的主导情感。
- 副语言事件列表 `paralinguistic_events`：包含 laughter、sigh、cough、cry 等可听非语音事件，每个事件带有毫秒级区间 `[start_ms, end_ms)`，采用左闭右开约定。

两类结果不可合并到同一字段，也不能互相包含。

## 双轨标注：标签与时间约定

- `emotion_label` 必须从题目下发的 `allowed_emotion_labels` 中选取，例如 `["joy", "neutral", "sadness"]`，不允许自定义新情感。
- `paralinguistic_events` 的每个事件必须包含 `label`、`start_ms`、`end_ms`。`end_ms` 必须大于 `start_ms`，区间长度建议 ≥ 50 ms 且 ≤ 该片段剩余时长。
- 时间精度以毫秒为最小单位；使用整数，不使用小数或帧号。
- 区间不允许超过片段总长度；超过会被判为时间错配。

## 双轨标注：常见边界情况

- 录音中存在笑声但同时是积极情感：情感标签记 `joy`，事件列表中加 `laughter` 区间，二者不重复但可同时出现。
- 长时间旁白中插入单次咳嗽：情感仍按整体选取，咳嗽作独立事件，区间按实际起止填写。
- 同时存在多种情绪：选择主导情绪并记录 `secondary_emotion_hint` 用于教学复盘（仍不混入事件列表）。
- 时间戳错位：若 `start_ms/end_ms` 与可听证据不匹配，应直接判退，不要自动修正。

## 双轨标注：与外部格式的边界

以下事实属于外部文档说明，不替本练习决定具体标签枚举或时间端点：

- EmotionML 支持类别或维度结构表达情感（外部事实）。
- Kaldi segments 与 Praat TextGrid 区间支持开始和结束时间（外部事实）。
- 本项目采用双轨提交、`[start_ms, end_ms)` 左闭右开、毫秒整数属于本地项目策略，不是行业统一标准。

标注员不得把外部格式当作本任务的现成标签集合；任何替代方案必须升级项目词表。

## 双轨标注：示例与反例

正例（虚构示例）：3.6 秒音频"太好了，终于完成了"，可见上扬音调和 2.5 至 3.1 秒笑声。提交 `emotion_label=joy`、`events=[{label: laughter, start_ms: 2500, end_ms: 3100}]`。

反例：把 laughter 写进 `emotion_label` 或把 emotion 写进 `paralinguistic_events` 列表，导致后续训练数据无法分离两类特征；或把 `[start_ms: 2500, end_ms: 3100]` 写成 `[2.5, 3.1]`，超出毫秒整数约定。

## 双轨标注：常见误区

- 将"轻松语调"理解成 emotion 类别维度，混入了副语言事件。
- 区间起点使用 0 而非实际可听开始时间。
- 在 `end_ms` 上加 1 ms 形成闭区间，破坏左闭右开约定。
- 不区分发声强度差异，统一打同一副语言事件。

## 双轨标注：来源说明

- 来源：`SRC-W3C-EMOTIONML-001` W3C EmotionML 1.0 规范，"Representation of Emotion" 章节，访问 2026-07-12。
- 来源：`SRC-KALDI-DATA-PREP-001` Kaldi 数据准备文档关于 segments 时段约定部分。
- 来源：`SRC-PRAAT-TEXTGRID-001` Praat TextGrid 时间区间表示规范。
- 来源：`SRC-POLICY-AUDIO-TASK4-001` BHZD 项目内部"audio 任务 4 双轨标注策略"，版本 1.0.0。
- 待核验：未核验真实 W3C EmotionML 文档中关于 category/dimension 取值的最新表述。
