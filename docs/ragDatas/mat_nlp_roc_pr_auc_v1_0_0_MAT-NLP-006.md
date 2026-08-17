---
id: MAT-NLP-006
title: 文本分类中 ROC-AUC 与 PR-AUC 的判读与场景选择
version: v1.0.0
source: SRC-SKL-METRICS-001
source_refs: SRC-POLICY-CLASSIFY-001
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

# 文本分类中 ROC-AUC 与 PR-AUC 的判读与场景选择

本资料解释 ROC-AUC、PR-AUC 的定义、差别与适用场景，以及在类别不平衡文本任务中如何选择指标。读者对象是分类算法工程师、教学管理员。

## ROC-AUC 与 PR-AUC：核心定义

- ROC-AUC：受试者工作特征曲线下面积，衡量排序能力，对类别不均衡相对不敏感。
- PR-AUC：精确率-召回率曲线下面积，聚焦正类样本表现，对类别比例敏感。

二者都基于分类器输出的"分数"或"概率"排序，不同阈值得到 (TPR, FPR) 或 (Precision, Recall) 曲线，曲线下面积即 AUC。

## ROC-AUC 与 PR-AUC：场景选择

ROC-AUC 适用：

- 类别相对均衡，正负样本接近。
- 关注整体排序能力，不针对稀有正类。
- 业务允许较高假阳性率。

PR-AUC 适用：

- 类别极不平衡（如欺诈< 0.1%）。
- 关注正类查得率与误报率。
- 误报成本远高于漏报成本。

多数文本分类任务正负样本比例悬殊，PR-AUC 更能反映模型对少数类的实际表现。

## ROC-AUC 与 PR-AUC：判读注意点

- AUC=0.5 视为随机；AUC=1.0 视为完美。
- 类别不平衡时 ROC-AUC 容易虚高，应同时给 PR-AUC。
- 同一任务的 AUC 必须同源（同一验证集、同一阈值列表）。
- 引入 `average_precision_score` 时确认 `average='macro'/'micro'` 字段一致。

## ROC-AUC 与 PR-AUC：常见误区

- 用 ROC-AUC 替代 PR-AUC 报告不平衡任务。
- 不汇报 95% 置信区间，单点数值掩盖不确定性。
- 跨模型比较时使用不同阈值列表。
- 把曲线下面积等价于"准确率提升 X%"。

## ROC-AUC 与 PR-AUC：示例与反例

正例（虚构示例）：邮件分类任务，正样本占比 0.5%。ROC-AUC=0.95，PR-AUC=0.78，能反映少数类性能。

反例：仅汇报 ROC-AUC=0.95，未给 PR-AUC；实际上 PR-AUC 仅 0.40，模型对真实正类样本查不全。

## ROC-AUC 与 PR-AUC：来源说明

- 来源：`SRC-SKL-METRICS-001` scikit-learn 文档"Quantifying the quality of predictions"。
- 来源：`SRC-POLICY-CLASSIFY-001` BHZD 项目内部"文本分类边界与词表治理策略"。
- 待核验：未核验多标签场景下 ROC-AUC / PR-AUC 的具体扩展。
