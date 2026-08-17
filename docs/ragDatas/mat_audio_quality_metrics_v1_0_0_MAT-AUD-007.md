---
id: MAT-AUD-007
title: 音频质量评估指标：信噪比、PESQ、STOI 的使用与判读
version: v1.0.0
source: SRC-POLICY-AUDIO-QUALITY-001
source_refs: SRC-KALDI-DATA-PREP-001
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

# 音频质量评估指标：信噪比、PESQ、STOI 的使用与判读

本资料解释 BHZD 平台音频质量评估的常用指标：信噪比、PESQ、STOI 的定义、计算与判读。读者对象是语音数据工程师、语音质检员。

## 音频质量指标：核心定义

- 信噪比（SNR / dB）：语音信号功率与背景噪声功率之比的对数。
- PESQ（Perceptual Evaluation of Speech Quality）：模拟人耳主观感知的客观指标，范围 -0.5 至 4.5。
- STOI（Short-Time Objective Intelligibility）：短时客观可懂度，范围 0 至 1。

三类指标各有侧重，不能互相替代。

## 音频质量指标：适用场景

| 指标 | 适用场景 | 不适用场景 |
| --- | --- | --- |
| SNR | 音频设备调试、噪声水平筛选 | 语音可懂度、主观自然度 |
| PESQ | 语音编解码评测、传输质量 | 强噪声环境下的语料筛选 |
| STOI | 听力辅助设备、可懂度评测 | 编码自然度、音乐保真 |

SNR 可作为入门筛选，PESQ/STOI 更贴近真实使用体验。

## 音频质量指标：判读区间

- SNR：`>= 25 dB` 视为清晰；`15-25 dB` 轻度噪声；`<15 dB` 不可用。
- PESQ：`>= 3.5` 良好；`2.5-3.5` 中等；`<2.5` 不可用。
- STOI：`>= 0.85` 优秀；`0.65-0.85` 可用；`<0.65` 影响业务。

任何单一指标不达，应进一步做人工听写复检。

## 音频质量指标：注意事项

- 同一音频应同时汇报至少 2 个指标。
- 编码引入失真不影响 SNR 但影响 PESQ。
- 强噪声会让 STOI 下降但不改变 PESQ。
- 在跨语种场景下 STOI 需要重新校准。

## 音频质量指标：常见误区

- 仅看 SNR 高就认为样本可用。
- 用 PESQ 比较压缩与非压缩音频。
- 不汇报具体数值，仅写"质量良好"。
- 跨数据集对比时使用不同指标。

## 音频质量指标：示例与反例

正例（虚构示例）：客服电话训练语料 SNR=30 dB、PESQ=3.8、STOI=0.92，三项均通过，用于训练。

反例：只汇报 SNR=30 dB 即认为可用，遗漏 PESQ 与 STOI，可能下游任务不达标。

## 音频质量指标：来源说明

- 来源：`SRC-POLICY-AUDIO-QUALITY-001` BHZD 项目内部"音频质量评估策略"，版本 1.0.0。
- 来源：`SRC-KALDI-DATA-PREP-001` Kaldi 数据准备文档。
- 待核验：未核验 PESQ/STOI 在极低比特率下的稳定性。
