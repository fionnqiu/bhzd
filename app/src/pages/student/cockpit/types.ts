/**
 * 指挥舱状态类型（从 useCockpitRun 拆出，供 hook 与各子组件共用）。
 * 独立成文件的原因：子组件只需要类型，不该反向依赖 hook 实现。
 */

/** PRD-01 §3.5 六态：空白/计划中/工具调用中/等待确认/已完成/失败 */
export type CockpitStatus =
  "idle" | "planning" | "tool_running" | "awaiting_confirmation" | "completed" | "failed";

/**
 * UI attachment metadata deliberately excludes the transient upload token and
 * file body. `previewUrl` is browser-only and is replaced by `thumbnailUrl`
 * once the persisted conversation projection is available.
 */
export interface ChatAttachment {
  id: string;
  name: string;
  kind: "image" | "document" | "audio" | "video";
  mimeType: string;
  size: number;
  thumbnailUrl?: string | null;
  previewUrl?: string | null;
}

export interface ChatMessage {
  id: string;
  /** Associates persisted historical work with the assistant reply it produced. */
  runId?: string | null;
  role: "user" | "assistant" | "system";
  content: string;
  /** Absent on older messages and assistant replies without learner uploads. */
  attachments?: ChatAttachment[];
  /** 流式输出中（message.delta 还在到达），用于打字光标样式 */
  streaming?: boolean;
}

/** Tool lifecycle classification; command/file remain reserved for future tools. */
export type ExecutionKind = "tool" | "command" | "file";

/** 执行轨迹行（tool.call.requested/completed 事件归并） */
export interface TraceEntry {
  id: string;
  tool: string;
  executionKind: ExecutionKind;
  status: string;
  durationMs: number | null;
  isWrite: boolean;
  /** Server-projected summaries; source arguments/results never enter UI state. */
  inputSummary: string | null;
  outputSummary: string | null;
}

/**
 * UI activity stages remain decodable for SSE replay and confirmation recovery,
 * but are not rendered as execution records in the student conversation.
 */
export type ActivityStage =
  | "understanding"
  | "planning"
  | "tool"
  | "retrieval"
  | "responding"
  | "confirmation"
  | "completed"
  | "failed";

export type ActivityStatus = "running" | "completed" | "waiting" | "failed";

/**
 * A persisted-event activity row. `seq` is the stable ordering and dedupe key
 * across SSE reconnects, while all text is limited to user-safe summaries.
 */
export interface ActivityEntry {
  seq: number;
  /** Latest persisted event consumed for this visible row; tool lifecycles update one row in place. */
  eventSeq?: number;
  /** Stable backend progress identity; separate from a tool call because replies have no tool id. */
  activityId?: string;
  stage: ActivityStage;
  status: ActivityStatus;
  message: string;
  detail?: string;
  tool?: string;
  executionKind?: ExecutionKind;
  /** Lets a requested/completed tool pair stay as one safe, inspectable activity. */
  toolCallId?: string;
  inputSummary?: string;
  outputSummary?: string;
  durationMs?: number | null;
  isWrite?: boolean;
}

/** 嵌入工具结果卡（tool.call.completed 的受控 result 投影，按工具分派） */
export interface EmbeddedCardData {
  id: string;
  tool: string;
  result: unknown;
}

export interface StartRunOptions {
  dataType?: string | null;
  /** 诊断补强等流程的附件（runs.py RunCreate.attachment → 编排器读取） */
  attachment?: Record<string, unknown> | null;
  /** New multi-file envelope; the server keeps the legacy `attachment` path. */
  attachments?: { attachment_token: string }[] | null;
  /**
   * Browser-side attachment snapshot for the outgoing message. It never enters
   * the provider payload and lets the UI retain its local image preview until
   * the durable message projection supplies an authenticated thumbnail URL.
   */
  messageAttachments?: ChatAttachment[];
  /**
   * Runs only after the server has accepted this turn. Keeping this browser-only
   * callback beside the token envelope lets a retry consume the same Composer
   * draft exactly once, without sending UI-only data to the API.
   */
  onAccepted?: () => void;
}

let msgSeq = 0;
/** 本地消息 id（用户/系统气泡；助手气泡按 runId 固定以便流式拼接） */
export function nextId(prefix: string): string {
  msgSeq += 1;
  return `${prefix}-${msgSeq}`;
}
