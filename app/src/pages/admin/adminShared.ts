/**
 * 系统管理端共享工具（F4 私有）。
 *
 * 与 ragShared 同一思路：角色/协议/供应商角色 → 中文映射集中一处，
 * 事实来源是 006_admin.sql 的 CHECK 约束与 admin.py 的枚举常量。
 */

import { ApiRequestError } from "../../api/client";

/** 用户角色（users.role CHECK 约束；content_admin 已于 023 号迁移移除） */
export const ROLE_OPTIONS = [
  { value: "student", label: "学生" },
  { value: "teacher", label: "教师" },
  { value: "system_admin", label: "系统管理员" },
] as const;

export const ROLE_LABELS: Record<string, string> = Object.fromEntries(
  ROLE_OPTIONS.map((o) => [o.value, o.label]),
);

/** 供应商协议（provider_configs.protocol；PRD-04 §3.1） */
export const PROTOCOL_OPTIONS = [
  { value: "chat_completions", label: "Chat Completions" },
  { value: "anthropic_messages", label: "Anthropic Messages" },
  { value: "responses", label: "Responses" },
] as const;

export const PROTOCOL_LABELS: Record<string, string> = Object.fromEntries(
  PROTOCOL_OPTIONS.map((o) => [o.value, o.label]),
);

/** 供应商角色（provider_configs.role；同角色全局至多一个，admin.py 独占赋值） */
export const PROVIDER_ROLE_OPTIONS = [
  { value: "primary", label: "主模型" },
  { value: "fallback", label: "回退模型" },
  { value: "embedding", label: "嵌入模型" },
  { value: "rerank", label: "重排模型" },
  { value: "grader", label: "评阅模型" },
  { value: "none", label: "无" },
] as const;

export const PROVIDER_ROLE_LABELS: Record<string, string> = Object.fromEntries(
  PROVIDER_ROLE_OPTIONS.map((o) => [o.value, o.label]),
);

/** 后端 UTC ISO8601 → 本地可读时间 */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 后端统一错误体的中文 message 透传（与 ragShared.errText 同口径） */
export function errText(err: unknown, fallback = "操作失败，请稍后重试"): string {
  if (err instanceof ApiRequestError) return err.message;
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

/** 截断长文本 */
export function clamp(text: string, max = 120): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}
