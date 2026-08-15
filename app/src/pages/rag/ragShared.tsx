/**
 * 系统管理端 RAG 领域共享工具，集中维护跨页面枚举与安全返回路径。
 *
 * 为什么集中在这里：状态/类型 → 中文文案 + 徽章色的映射横跨资料库、详情、
 * 任务队列、台账、发布审核五个页面，分散翻译必然不一致（与 F0 的
 * StatusBadge 同一思路）；后端枚举以 005_rag.sql 为唯一事实来源。
 */

import type { RagDocument, RagJob } from "../../api/types";
import { ApiRequestError } from "../../api/client";

/* ---------------------------------------------------------------- 枚举 → 中文 */

/** 数据类型（005_rag.sql data_types_json 元素） */
export const DATA_TYPE_OPTIONS = [
  { value: "text", label: "文本" },
  { value: "image", label: "图像" },
  { value: "audio", label: "语音" },
  { value: "video", label: "视频" },
] as const;

export const DATA_TYPE_LABELS: Record<string, string> = Object.fromEntries(
  DATA_TYPE_OPTIONS.map((o) => [o.value, o.label]),
);

/** 资料来源类型（rag_documents.source_type CHECK 约束） */
export const SOURCE_TYPE_OPTIONS = [
  { value: "textbook", label: "教材" },
  { value: "standard", label: "规范" },
  { value: "enterprise", label: "企业资料" },
  { value: "teacher", label: "教师自建" },
  { value: "competition", label: "比赛资料" },
  { value: "other", label: "其他" },
] as const;

export const SOURCE_TYPE_LABELS: Record<string, string> = Object.fromEntries(
  SOURCE_TYPE_OPTIONS.map((o) => [o.value, o.label]),
);

/** 授权状态（rag_documents.license_status；PRD-06 §4.2 发布守卫直接读它） */
export const LICENSE_OPTIONS = [
  { value: "authorized", label: "已授权" },
  { value: "internal", label: "内部资料" },
  { value: "pending", label: "待确认" },
  { value: "forbidden", label: "禁止" },
] as const;

export const LICENSE_LABELS: Record<string, string> = Object.fromEntries(
  LICENSE_OPTIONS.map((o) => [o.value, o.label]),
);

/** 可见范围（rag_documents.visibility） */
export const VISIBILITY_OPTIONS = [
  { value: "admin", label: "仅管理员" },
  { value: "teacher", label: "仅教师" },
  { value: "student", label: "学生可见" },
] as const;

export const VISIBILITY_LABELS: Record<string, string> = Object.fromEntries(
  VISIBILITY_OPTIONS.map((o) => [o.value, o.label]),
);

/** 管线阶段（rag_jobs.stage） */
export const STAGE_LABELS: Record<string, string> = {
  parse: "解析",
  chunk: "切片",
  index: "索引",
};

/** 审核动作（review_records.action CHECK 约束） */
export const REVIEW_ACTION_LABELS: Record<string, string> = {
  submit: "提交送审",
  approve: "通过发布（学生可见）",
  approve_teacher_only: "通过发布（仅教师）",
  reject: "驳回",
  archive: "归档",
  publish: "发布",
};

/** 台账授权状态（source_ledgers.authorization_status） */
export const LEDGER_AUTH_LABELS: Record<string, string> = {
  approved: "已批准",
  pending: "待审批",
  expired: "已过期",
  forbidden: "禁止",
};

/** 台账审核状态（source_ledgers.review_status） */
export const LEDGER_REVIEW_LABELS: Record<string, string> = {
  draft: "草稿",
  reviewed: "已审核",
  published: "已发布",
};

/* ---------------------------------------------------------------- 展示辅助 */

/** 后端 UTC ISO8601 → 本地可读时间（列表/详情统一格式） */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 任务耗时（rag_jobs started_at/finished_at；仍在跑则算到当前） */
export function fmtDuration(started: string | null, finished: string | null): string {
  if (!started) return "—";
  const start = new Date(started).getTime();
  const end = finished ? new Date(finished).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end)) return "—";
  const ms = Math.max(0, end - start);
  if (ms < 1000) return `${ms}ms`;
  const sec = Math.round(ms / 100) / 10;
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}分${Math.round(sec % 60)}秒`;
}

/**
 * 提取面向用户的错误文案：后端统一错误体的中文 message 原样透传
 * （PRD 错误口径：可理解、不暴露堆栈）；非后端错误给兜底文案。
 */
export function errText(err: unknown, fallback = "操作失败，请稍后重试"): string {
  if (err instanceof ApiRequestError) return err.message;
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

/**
 * 将 returnTo 限制在系统管理的 RAG 路径范围内，防止开放重定向。
 * 历史 /rag-admin 返回地址在这里归一化，避免新页面的返回按钮再次
 * 绕经兼容路由或重新暴露已删除门户的路径语义。
 */
export function safeRagReturnPath(value: unknown): string {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) {
    return "/admin/rag";
  }
  const parsed = new URL(value, "https://bhzd.invalid");
  const { pathname, search } = parsed;
  if (pathname === "/admin/rag" || pathname.startsWith("/admin/rag/")) {
    return `${pathname}${search}`;
  }
  if (pathname === "/rag-admin") return `/admin/rag${search}`;
  if (pathname === "/rag-admin/upload") return `/admin/rag/upload${search}`;
  if (pathname === "/rag-admin/search-test" || pathname === "/rag-admin/eval-cases") {
    return `/admin/rag/search-test${search}`;
  }

  const documentMatch = pathname.match(/^\/rag-admin\/documents\/([^/]+)(?:\/chunks)?$/);
  if (documentMatch) {
    return `/admin/rag/documents/${encodeURIComponent(documentMatch[1])}${search}`;
  }
  return "/admin/rag";
}

/** 截断长文本（表格/预览用） */
export function clamp(text: string, max = 120): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

/* ---------------------------------------------------------------- 派生徽章 */

/**
 * 审核状态徽章：底层只有一个 status 字段，"审核视角"按 PRD-03 §4.1 派生
 * （与后端 list_documents 的 review_status 过滤口径一致）。
 */
export function ReviewStatusBadge({ status }: { status: RagDocument["status"] }) {
  if (status === "review_pending") return <span className="badge badge-warning">待审核</span>;
  if (status === "published") return <span className="badge badge-success">已通过</span>;
  if (status === "rejected") return <span className="badge badge-danger">已驳回</span>;
  return <span className="badge badge-neutral">未送审</span>;
}

/**
 * 索引状态徽章：indexed 及其之后的状态都算"已索引"
 * （与后端 list_documents 的 index_status 过滤口径一致）；失败时挂 tooltip。
 */
export function IndexStatusBadge({ doc }: { doc: RagDocument }) {
  if (doc.status === "failed") {
    const tip = [doc.error_code, doc.error_message].filter(Boolean).join("：");
    return (
      <span className="badge badge-danger" title={tip || "处理失败"}>
        失败 ⓘ
      </span>
    );
  }
  if (["indexed", "review_pending", "published", "archived"].includes(doc.status)) {
    return <span className="badge badge-success">已索引</span>;
  }
  if (["parsing", "parsed", "chunking", "chunked", "indexing"].includes(doc.status)) {
    return <span className="badge badge-info">处理中</span>;
  }
  return <span className="badge badge-neutral">未索引</span>;
}

/** 授权状态徽章（资料 license_status；forbidden/pending 是发布守卫，给警示色） */
export function LicenseBadge({ status }: { status: RagDocument["license_status"] }) {
  const tone =
    status === "authorized"
      ? "success"
      : status === "internal"
        ? "info"
        : status === "pending"
          ? "warning"
          : "danger";
  return <span className={`badge badge-${tone}`}>{LICENSE_LABELS[status] ?? status}</span>;
}

/** 台账授权状态徽章（source_ledgers，独立枚举不复用资料徽章） */
export function LedgerAuthBadge({ status }: { status: string }) {
  const tone =
    status === "approved" ? "success" : status === "pending" ? "warning" : "danger";
  return (
    <span className={`badge badge-${tone}`}>{LEDGER_AUTH_LABELS[status] ?? status}</span>
  );
}

/** 从任务列表推导"当前是否有活动任务"（JobsPage 5s 轮询的启停条件） */
export function hasActiveJobs(jobs: RagJob[]): boolean {
  return jobs.some((j) => j.status === "queued" || j.status === "running");
}
