---
id: MAT-PLT-004
title: LLM 供应商协议规范与连接测试正确性
version: v1.0.0
source: SRC-POLICY-PROVIDER-001
source_refs: SRC-OPENAI-RESPONSES-001
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

# LLM 供应商协议规范与连接测试正确性

本资料介绍 BHZD 平台 LLM 供应商（provider）协议的统一规范、连接测试可靠性与故障诊断。读者对象是平台管理员、运维工程师。

## 供应商协议：核心定义

供应商协议是前端调用不同 LLM 提供商的统一中间层。BHZD 平台已统一为 3 类协议：

- `chat_completions`：OpenAI 风格聊天补全。
- `anthropic_messages`：Anthropic Messages 风格。
- `responses`：OpenAI Responses API（含推理模型）。

每类协议对应不同的请求 / 响应格式与流式约定。

## 供应商协议：连接测试正确性

历史上存在 `invalid_chat_response` 假阴性问题：

- 推理模型（o3、o4-mini）的首个 token 是思考内容，不在 `content` 字段。
- 流格式网关差异导致 `choices[0].delta` 路径略有不同。
- `max_tokens=1` 太小导致部分模型不产出任何文本。
- 网络层面流被提前关闭。

修复策略：

- `_first_text_delta()` 接受第一个非空 delta 即视为成功，含空串。
- 把探测 token 数从 1 提高到 4，给模型更多输出空间。
- 仍需在协议层验证模型确实返回了可用文本。

## 供应商协议：协议选择

- 推理模型选择 `responses` 协议。
- 普通聊天模型选择 `chat_completions` 协议。
- Anthropic 模型选择 `anthropic_messages` 协议。
- 已废弃的协议（如 `xunfei_xingchen`、`xunfei_spark`）被移除。

协议选择与模型能力对应，由数据库 `provider.protocol` 字段决定。

## 供应商协议：安全降级

- 流式响应异常：回退到非流式，提示用户。
- 协议不识别：返回明确错误，不允许静默猜测。
- 推理模型超时：自动重试 1 次，仍超时则提示用户换用普通模型。
- Provider 不可达：保留缓存回答 2 分钟，避免重复失败请求。

降级策略不得让用户感知 AI 链路细节。

## 供应商协议：连接测试必检项

每次新增或修改 provider，应测试：

- 健康检查 `/api/health` 通过。
- 极简提示词返回合法文本（区分大小写、空串判定）。
- 流式响应首 delta 在 2 秒内到达。
- 异常路径返回错误码而非空白响应。
- 协议重置后仍能返回一致结果。

## 供应商协议：常见误区

- 用最大 200 token 测试长上下文，忽略短探针差异。
- 把 `protocol` 字段当成能力开关使用。
- 不更新数据库 `provider.protocol` 字段，导致前端路由错误。
- 旧协议残留代码未清理，运维误切换。

## 供应商协议：来源说明

- 来源：`SRC-POLICY-PROVIDER-001` BHZD 项目内部"Provider 协议规范"，版本 1.0.0。
- 来源：`SRC-OPENAI-RESPONSES-001` OpenAI Responses API 官方文档。
- 待核验：未核验不同第三方网关对协议语义的微差。
