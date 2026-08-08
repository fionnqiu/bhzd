import type {
  RagDocumentStatus,
  RagJobStatus,
  RunStatus,
  TaskStatus,
} from "../api/types";

type BadgeTone =
  | "neutral"
  | "primary"
  | "success"
  | "warning"
  | "danger"
  | "info";

/**
 * 状态 → 中文文案 + 颜色映射。
 *
 * 为什么集中在这里：任务/资料/管线/运行四套状态机横跨 F1-F4 四个前端
 * 代理的页面，各自翻译必然不一致；统一映射保证同一状态全站同文同色。
 * 未收录的状态原样显示英文并给 neutral 色（新增状态时后端先上线也能兜住）。
 */
const STATUS_MAP: Record<string, { label: string; tone: BadgeTone }> = {
  // 学习任务状态机（tasks.py `_TRANSITIONS`）
  draft: { label: "草稿", tone: "neutral" },
  not_started: { label: "未开始", tone: "neutral" },
  in_progress: { label: "进行中", tone: "primary" },
  submitted: { label: "已提交", tone: "info" },
  completed: { label: "已完成", tone: "success" },
  paused: { label: "已暂停", tone: "warning" },
  archived: { label: "已归档", tone: "neutral" },
  // RAG 资料状态机（005_rag.sql rag_documents.status）
  parsing: { label: "解析中", tone: "info" },
  parsed: { label: "已解析", tone: "info" },
  chunking: { label: "切片中", tone: "info" },
  chunked: { label: "已切片", tone: "info" },
  indexing: { label: "索引中", tone: "info" },
  indexed: { label: "已索引", tone: "info" },
  review_pending: { label: "待审核", tone: "warning" },
  published: { label: "已发布", tone: "success" },
  rejected: { label: "已驳回", tone: "danger" },
  expired: { label: "已过期", tone: "danger" },
  failed: { label: "失败", tone: "danger" },
  // 管线任务（rag_jobs.status）
  queued: { label: "排队中", tone: "neutral" },
  running: { label: "运行中", tone: "info" },
  succeeded: { label: "成功", tone: "success" },
  cancelled: { label: "已取消", tone: "neutral" },
  // Agent 运行（agent_runs.status）
  waiting_confirmation: { label: "等待确认", tone: "warning" },
  // 确认单（pending_confirmations.status）
  pending: { label: "待确认", tone: "warning" },
  confirmed: { label: "已确认", tone: "success" },
};

export interface StatusBadgeProps {
  status:
    | TaskStatus
    | RagDocumentStatus
    | RagJobStatus
    | RunStatus
    | string;
}

/** 状态徽章：任意业务状态 → 中文彩色徽章。 */
export default function StatusBadge({ status }: StatusBadgeProps) {
  const entry = STATUS_MAP[status] ?? { label: status, tone: "neutral" as BadgeTone };
  return <span className={`badge badge-${entry.tone}`}>{entry.label}</span>;
}
