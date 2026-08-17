---
id: MAT-AUD-002
title: 音频方言识别任务的语言变体标签与覆盖度检查
version: v1.0.0
source: SRC-IPA-LANGUAGE-VARIETIES-001
source_refs: SRC-POLICY-AUDIO-DIALECT-001
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

# 音频方言识别任务的语言变体标签与覆盖度检查

本资料覆盖 BHZD 平台方言/语言变体识别任务的标签选择、覆盖度评估与跨地区方言处理。读者对象是方言标注员、教学管理员和质检工程师。

## 方言识别：核心定义

方言识别指对一段语音片段，给出主语言（language）与变体（variant）两类标签。变体包括官话方言（普通话、北京话、东北话等）、南方方言（粤语、闽南语、吴语）、少数民族语言（藏语、维吾尔语等）以及跨方言的语码转换（code-switching）。

本资料不规定某一具体方言清单，清单由项目词表下发。

## 方言识别：标签约定

- 单标签格式：`language_variant=zh-yue`、`language_variant=zh-cmn` 等 ISO 639-3 与变体后缀组合。
- 跨方言片段必须使用语码转换标记，例如 `code_switch=zh-yue<->zh-cmn` 并附加主次比例。
- 允许"未知方言"标签 `unknown_variant`，但要求至少一条可听证据描述音段特征。
- 禁止使用"普通话"等模糊写法的标签组合，除非题项声明统一接受该写法。

## 方言识别：覆盖度与一致性检查

方言任务上线前，必须完成：

- 每种方言至少 100 条样本的回放质检，错误率超过 5% 时重新培训标注员。
- 跨方言片段应至少 30 条样本；语码转换判定一致性（Cohen κ）应 ≥ 0.7。
- 不同方言之间混淆矩阵每周回看，重点关注高混淆对（如潮汕话与闽南语）。
- 录制设备差异（手机 vs 桌面麦）与背景噪音下的方言判定一致性单独评估。

覆盖度检查记录每个方言的样本量、混淆率与判断置信度，作为任务发布依据。

## 方言识别：边界条件

- 歌曲或戏剧片段：方言判定不替代语言识别，应按"主要唱词"判断。
- 中英混合：中文为主时使用 `zh-cmn<->en`，英文为主时反过来。
- 婴幼儿语言：音段不足以判断时记录 `low_confidence=true`，不要强行归类。
- 同一方言地区不同年龄段的差异：由"代际版本"字段标注，不另起方言。

## 方言识别：常见误区

- 把口音（accent）误判为方言：口音是次要特征，本任务关注主语言变体。
- 将方言词误认为新方言，导致词表持续扩张。
- 同时标注"潮汕话"和"闽南语"互斥组时不写入互斥说明。
- 不同录音设备造成误判差异时不记录设备 ID，事后无法溯源。

## 方言识别：示例与反例

正例（虚构示例）：一段 8 秒音频以粤语为主语，含 2 秒普通话插话。提交 `language_variant=zh-yue`、`code_switch=zh-yue<->zh-cmn`，并附插话时间区间。

反例：把同一段直接标 `zh-cmn` 并写注释"中间有粤语"，丢失方言核心证据，造成训练数据混淆。

## 方言识别：来源说明

- 来源：`SRC-IPA-LANGUAGE-VARIETIES-001` IPA 关于语言变体描述与 ISO 639 系列说明，访问 2026-07-12。
- 来源：`SRC-POLICY-AUDIO-DIALECT-001` BHZD 项目内部"方言/语言变体任务策略"，版本 1.0.0。
- 待核验：未核验所有地区的方言书写一致性。
