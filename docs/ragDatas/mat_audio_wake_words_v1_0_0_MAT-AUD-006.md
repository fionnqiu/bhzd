---
id: MAT-AUD-006
title: 音频唤醒词与命令词检测的端点标注规则
version: v1.0.0
source: SRC-KALDI-DATA-PREP-001
source_refs: SRC-PRAAT-TEXTGRID-001,SRC-POLICY-AUDIO-WAKEWORD-001
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

# 音频唤醒词与命令词检测的端点标注规则

本资料覆盖 BHZD 平台智能音箱、车机、客服机器人的唤醒词与命令词检测任务的标注规则。读者对象是语音端点标注员、模型评测工程师和教学管理员。

## 唤醒词检测：核心定义

唤醒词（wake word）是一段预定义语音信号，用于激活智能设备进入聆听状态。命令词（command word）是唤醒后用户发出的具体操作短语。

两类标签分别写入 `wake_word_events` 与 `command_word_events`，不应合并到同一字段。

## 唤醒词检测：标签约定

- `wake_word_events`：每个事件包含 `label`、`start_ms`、`end_ms` 与 `confidence`。
- `label` 从题目给定的有限集合中选取（如 `["hi_xiaomi", "hey_assistant"]`）。
- `start_ms` 是词首个音素的可听起止；`end_ms` 是词末音素结束，二者均按 `[start_ms, end_ms)` 左闭右开约定。
- `confidence` 取值范围 `[0, 1]`，由标注员依据音频清晰度评估。
- `command_word_events` 除上述字段外，还应包含 `intent_label`，连接到任务意图词表。

## 唤醒词检测：端点判定

端点判定要点：

- 词首音素的起止按能量突然上升点（voice onset）确认，不按静音起止。
- 词末音素的结束按能量显著下降点（voice offset）确认，并加 30 至 80 ms 的尾音。
- 唤醒词发音模糊（背景噪声、设备差异）时按"最可能发音"标注，置 `confidence < 0.7`。
- 唤醒词被多次重复（如"嗨小爱嗨小爱"）按两次事件记录，区间连续。

## 唤醒词检测：误触发与拒识别记录

- 误触发（false wake）：音频不含唤醒词但模型触发，应记录为 `negative_sample`。
- 拒识别（miss）：音频包含唤醒词但未触发模型，应记录为 `missed_sample`。
- 误触发与拒识别样本比例各占总样本 5% 至 20% 时为正常训练分布；超出区间需复核设备与录制流程。

所有 `negative_sample` 与 `missed_sample` 必须保留原始音频哈希以便复核，不得删除。

## 唤醒词检测：常见误区

- 用静音起止作为唤醒词端点，导致端点过短。
- 唤醒词被部分截断时强行补全，丢失真实边界。
- 把唤醒后的命令词与唤醒词合并到同一区间，导致后续命令识别训练错位。
- 把 `confidence` 留空或恒为 1，导致评测无法区分高低质量样本。

## 唤醒词检测：示例与反例

正例（虚构示例）：3 秒音频"嗨小爱，打开灯"，唤醒词区间 0.2 至 0.9 秒，命令词区间 1.0 至 2.4 秒，意图 `turn_on_light`。

反例：把唤醒词写成 0 至 2.4 秒，命令词区间未单独标出，导致命令识别模型把唤醒词学进命令特征。

## 唤醒词检测：来源说明

- 来源：`SRC-KALDI-DATA-PREP-001` Kaldi 数据准备文档关于事件标签字段。
- 来源：`SRC-PRAAT-TEXTGRID-001` Praat TextGrid 关于多事件层级说明。
- 来源：`SRC-POLICY-AUDIO-WAKEWORD-001` BHZD 项目内部"唤醒词与命令词策略"，版本 1.0.0。
- 待核验：未核验真实智能音箱端点偏移数据与本约定是否完全一致。
