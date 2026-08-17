---
id: MAT-AUD-005
title: 音频转写断句与标点标注规则
version: v1.0.0
source: SRC-KALDI-DATA-PREP-001
source_refs: SRC-PRAAT-TEXTGRID-001,SRC-POLICY-AUDIO-PUNCT-001
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

# 音频转写断句与标点标注规则

本资料覆盖 BHZD 平台音频转写任务中的断句、标点恢复与不可识别片段标记。读者对象是转写标注员、教学管理员与质检员。

## 转写断句：核心定义

断句（sentence segmentation）是把连续转写文本按语音活动切分为若干句，并保留每句对应的语音起止区间。标点（punctuation）则是按语义、语气为每句恢复常见标点符号。

断句与标点恢复不是同一回事：先断句，再标点；二者在时序对齐上各自独立。

## 转写断句：断句判定

断句应满足以下任一条件：

- 句子间出现超过 200 ms 的静音。
- 出现明显的语气停顿（句末语调上扬/下降）。
- 上下文提供了语义结束信号（动词完成、疑问助词等）。

短句不强行合并；标点恢复按断句结果独立进行。

## 转写断句：标点约定

BHZD 平台使用以下标点集合：

- 中文句末标点：`。？！` 三种，按语气选择。
- 中文内部标点：`，、；：""''「」`。
- 英文标点与中文混用时按当前片段主语言选择集合，但同一句不混用两套。
- 语气词"嗯""呃""哦"不作为独立标点处理，也不打括号，由转写文本本身保留。

## 转写断句：不可识别片段

遇到不可识别片段（背景噪声、音乐盖过人声等）时应：

- 在文本位置写入 `[unintelligible]` 占位符，长度不超过 5 个汉字或对应音段时间。
- 时间戳保留到毫秒，记录此区间的 `start_ms` 与 `end_ms`。
- 若整段都不可识别，整段转写置为 `[unintelligible]` 并标注原因（背景音乐/失真/极低音量）。
- 同一区间的占位符不应替换为问号、省略号或推测性文字。

## 转写断句：常见误区

- 在语气词前后强行加句号，影响下游句法分析。
- 把省略号写成长串"……..."超过 6 个点。
- 跨语种文本混用全角和半角标点。
- 把 [unintelligible] 当作疑问词处理，掩盖真实数据问题。

## 转写断句：示例与反例

正例（虚构示例）：3 秒音频"嗯，今天天气不错，对吧？"。转写为"嗯，今天天气不错，对吧？"，按断句为"嗯，今天天气不错，对吧？"或更细粒度的两句。

反例：把同一段写成"嗯今天天气不错对吧"无标点，或写成"嗯...今天天气不错对吧？"使用省略号代替语气词，丢失原始停顿信息。

## 转写断句：来源说明

- 来源：`SRC-KALDI-DATA-PREP-001` Kaldi 数据准备文档关于转写文本字段的说明。
- 来源：`SRC-PRAAT-TEXTGRID-001` Praat TextGrid 关于 text tier 转写规则。
- 来源：`SRC-POLICY-AUDIO-PUNCT-001` BHZD 项目内部"音频转写标点策略"，版本 1.0.0。
- 待核验：未核验英文转写时大小写与缩写规则。
