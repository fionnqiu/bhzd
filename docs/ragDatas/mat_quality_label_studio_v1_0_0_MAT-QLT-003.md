---
id: MAT-QLT-003
title: Label Studio 文本分类项目创建与结果导出流程
version: v1.0.0
source: SRC-LS-TEXT-LABELS-001
source_refs: SRC-LS-PROJECT-SETUP-001
source_type: textbook
license_status: pending
data_types: text
visibility: admin
status: draft
verification_status: pending
language: zh-CN
authoring_method: collected-and-adapted
created_at: 2026-08-17
updated_at: 2026-08-17
owner: content-reviewer
review_due_at: 2026-08-24
replaces: none
---

# Label Studio 文本分类项目创建与结果导出流程

本资料介绍在 BHZD 教学场景下使用 Label Studio 创建文本分类项目、配置标签、导入任务并导出结果的标准流程。读者对象是教学管理员和标注员。

## Label Studio 项目：核心定义

Label Studio 是一个开源数据标注平台，支持文本、图像、音频、视频多种数据类型的标注。项目（Project）是标注任务的最小承载单位，包含标签配置、数据导入、标注员分配与导出。

本流程基于 Label Studio 1.10+ 版本。

## Label Studio 项目：创建步骤

1. 管理员登录后点击 Create Project，输入项目名称（建议使用业务线 + 任务类型 + 日期格式）。
2. 进入 Labeling Interface 配置页，选择文本分类模板或自定义 XML。
3. 配置 `<Labels name="label">` 节点，按词表从 `toLabel` 控制下拉或使用 `Choice` 多选。
4. 在 Settings → Data Import 上传 JSON / JSONL / CSV 数据，确保包含 `text` 字段。
5. 在 Instructions 中粘贴标注文档，包含定义、示例与边界。

创建项目时务必填写 Instructions，避免标注员靠主观判断。

## Label Studio 项目：标签配置示例

虚构示例模板：

```xml
<View>
  <Labels name="label" toName="text">
    <Label value="positive" background="#22c55e"/>
    <Label value="neutral" background="#a3a3a3"/>
    <Label value="negative" background="#ef4444"/>
  </Labels>
  <Text name="text" value="$text"/>
</View>
```

颜色仅用于提示，不是标签语义的一部分。

## Label Studio 项目：任务分配与角色

- Annotator：只能看到分配给自己的任务，无法查看其他标注员结果。
- Reviewer：可看到全部标注员结果，适合做质检。
- Manager：可创建项目、导入数据、导出结果。

BHZD 通常由系统管理员（Manager）创建项目，标注员（Annotator）执行标注，质检员（Reviewer）复核。

## Label Studio 项目：导出结果

导出时优先选择 JSON 格式；仅当下游需要 JSONL 或 CSV 时转换。

导出后的常见字段包括：

- `data.task_id`：原始任务 ID。
- `annotations[0].result`：包含标签值。
- `annotations[0].completed_by`：标注员 ID。
- `created_at` / `updated_at`：用于一致性分析。

导出文件应同时保留 SHA-256 校验值，避免后续处理时找不到原文件。

## Label Studio 项目：常见误区

- 在项目级别粘贴全部词表说明但未在 Instructions 中指向。
- 把"机器学习模型作为标注员"和人类标注员放同一视图。
- 导出 CSV 后丢失 `completed_by`，无法反查责任标注员。
- 项目名称使用 `Untitled project` 默认名，事后无法归档。

## Label Studio 项目：来源说明

- 来源：`SRC-LS-TEXT-LABELS-001` Label Studio 文档"Lables Tag for Labeling Regions"，访问 2026-07-12。
- 来源：`SRC-LS-PROJECT-SETUP-001` Label Studio 项目设置官方文档。
- 待核验：未核验 Label Studio 最新稳定版（1.18+）的字段命名是否完全一致。
