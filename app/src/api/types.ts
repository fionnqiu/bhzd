/**
 * API DTO 契约（蓝图 §6 的前端镜像）。
 *
 * 为什么这份文件以 **后端路由代码** 而不是蓝图表格为准：集成中发现多处
 * 实现偏差（如 ToolCall 用 `tool` 而非 `tool_name`、图谱节点用 `label`
 * 而非 `name`），后端是唯一事实来源。每个接口都标注了对应路由文件，
 * 后续后端改动时按图索骥同步即可。
 */

/* ================================================================ 通用 */

export type Role = "student" | "teacher" | "system_admin";

/** UserDTO（routers/auth.py `_user_dto`） */
export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
  status: "active" | "disabled";
  email_verified: boolean;
}

/** 分页响应（蓝图 §4：`?limit&offset` → `{items,total}`） */
export interface Paginated<T> {
  items: T[];
  total: number;
}

/** 统一错误体（errors.py：`{"error":{"code","message","details?"}}`） */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    /** Optional recovery metadata, such as auth rate-limit wait seconds. */
    details?: Record<string, unknown>;
  };
}

/** GET /api/auth/session 与 POST /api/auth/login 的响应（auth.py） */
export interface SessionResponse {
  user: User;
  csrf_token: string;
}

/* ================================================================ 认证 */

export interface RegisterResponse {
  user: User;
  message: string;
}

export interface ForgotPasswordResponse {
  message: string;
  /** 仅开发模式回显（同上） */
  dev_reset_token?: string;
}

export interface MessageResponse {
  message: string;
}

/* ================================================================ Agent */

export interface Conversation {
  id: string;
  title: string | null;
  data_type: string | null;
  created_at: string;
  updated_at: string;
}

export type MessageRole = "user" | "assistant" | "system" | "tool";

/** Durable metadata for a learner-visible attachment; file bytes stay off the conversation DTO. */
export interface MessageAttachment {
  id: string;
  ordinal: number;
  name: string;
  kind: "image" | "document" | "audio" | "video";
  mime_type: string;
  size: number;
  /** Relative, owner-scoped URL for a derived image thumbnail only. */
  thumbnail_url?: string | null;
}

export interface Message {
  id: string;
  run_id: string | null;
  role: MessageRole;
  content: string;
  created_at: string;
  /** Optional so conversations saved before attachment persistence remain readable. */
  attachments?: MessageAttachment[];
}

/**
 * A server-projected, learner-visible activity. The conversation endpoint
 * deliberately omits raw SSE payloads, model reasoning, tool arguments, and
 * tool results so historical replay cannot widen the browser data surface.
 */
export interface ConversationActivityEntry {
  seq: number;
  event_seq?: number;
  activity_id?: string;
  stage: "understanding" | "planning" | "tool" | "responding" | "confirmation";
  status: "running" | "completed" | "waiting" | "failed";
  message: string;
  detail?: string;
  tool?: string;
  tool_call_id?: string;
  execution_kind?: "tool" | "command" | "file";
  input_summary?: string;
  output_summary?: string;
  duration_ms?: number | null;
  is_write?: boolean;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
  /**
   * Optional during rollout so legacy conversations with no stored visible
   * activities remain a faithful transcript instead of gaining synthetic rows.
   */
  activities_by_run?: Record<string, ConversationActivityEntry[]>;
  /**
   * 历史会话中的任务草稿投影（run_id → 最新草稿），
   * 回答底部的预览/同步按钮据此复原；旧服务端可能缺失该键。
   */
  task_drafts_by_run?: Record<string, TaskDraft>;
}

export type RunStatus = "running" | "waiting_confirmation" | "completed" | "failed" | "cancelled";

/** 运行概要（GET /api/runs/{id} 的 run 键，runs.py） */
export interface AgentRun {
  id: string;
  conversation_id: string;
  status: RunStatus;
  input_text: string;
  data_type: string | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export type ToolCallStatus =
  "requested" | "running" | "completed" | "failed" | "awaiting_confirmation" | "cancelled";

/**
 * 工具调用 DTO（runs.py `tool_calls` 列表项）。
 * 注意键名是 `tool` 而非蓝图 §5 表头里的 tool_name——以后端为准。
 */
export interface ToolCall {
  id: string;
  tool: string;
  permission: "read" | "write";
  status: ToolCallStatus;
  /** Raw arguments/results are intentionally omitted from recovery responses. */
  execution_kind?: "tool" | "command" | "file";
  input_summary?: string;
  output_summary?: string;
  duration_ms: number | null;
  is_write: boolean;
  created_at: string;
  completed_at: string | null;
}

export type ConfirmationStatus = "pending" | "confirmed" | "cancelled" | "expired";

/** 确认门 DTO（runs.py / confirmations.py；预览键为 `preview`） */
export interface Confirmation {
  id: string;
  tool_call_id?: string;
  action_type: string;
  preview: Record<string, unknown> | null;
  status: ConfirmationStatus;
  expires_at: string;
  created_at: string;
  run_id?: string;
}

/**
 * Agent 任务草稿卡（task_drafts 投影；形状与后端 build_task_card 对齐）。
 * 与旧确认门任务卡同一存储契约。
 */
export interface TaskDraftCard {
  title?: string;
  goal?: string;
  description?: string;
  data_type?: string | null;
  cap_ids?: string[];
  cap_names?: { cap_id: string; name: string }[];
  knowledge_points?: { title?: string; content?: string }[];
  exercises?: {
    question?: string;
    type?: string;
    options?: string[];
    reference_answer?: string;
  }[];
  est_minutes?: number;
}

/**
 * task.draft 事件与会话详情的草稿投影。每次状态变化（生成/同步）都以
 * 完整投影重发，回放取最后一条即当前状态。
 */
export interface TaskDraft {
  id: string;
  status: "draft" | "synced";
  source: string;
  cards: TaskDraftCard[];
  task_ids: string[];
  created_at?: string;
  synced_at?: string | null;
}

/** POST /api/task-drafts/{id}/sync 响应（tasks.py） */
export interface TaskDraftSyncResponse {
  draft_id: string;
  status: "synced";
  task_ids: string[];
  tasks: TaskSummary[];
  already_synced: boolean;
}

export interface PlanStep {
  id: string;
  title: string;
  status: string;
  /** Optional during gradual SSE rollout; current runs include it for UI filtering. */
  tool?: string;
}

/**
 * User-safe Agent progress reported while a run is active. This deliberately
 * models work stages rather than hidden reasoning or provider internals.
 */
/** Backend phase names are intentionally coarse and exclude hidden reasoning. */
export type AgentRunProgressPhase =
  "understanding" | "planning" | "tool" | "retrieval" | "synthesis" | "confirmation" | "system";

export type AgentRunProgressStatus = "running" | "completed" | "waiting_confirmation" | "failed";

export interface AgentRunProgress {
  seq: number;
  /**
   * Stable identity for one learner-visible progress lifecycle. Older servers
   * omit it, so clients must not invent a visible activity from an untagged frame.
   */
  activity_id?: string;
  phase: AgentRunProgressPhase;
  status: AgentRunProgressStatus;
  /** Deterministic, user-facing copy; never a model chain of thought. */
  title: string;
  /** Optional redacted context that excludes prompts, tool payloads, and secrets. */
  detail?: string;
}

/** GET /api/runs/{id} 完整响应（runs.py） */
export interface RunDetail {
  run: AgentRun;
  /** 计划 JSON（含 steps），未完成规划时为 null */
  plan: { steps?: PlanStep[]; [key: string]: unknown } | null;
  tool_calls: ToolCall[];
  /** 仅 pending 状态的确认单 */
  confirmations: Confirmation[];
  /** Terminal SSE payload projected into recovery reads; optional for old servers. */
  summary?: string | null;
  /**
   * SSE 中断后由服务端运行详情返回的最终助手消息。
   * 可选字段让旧服务端在渐进发布期间仍保持兼容。
   */
  assistant_message?: Message | null;
}

export interface CreateRunResponse {
  run_id: string;
  conversation_id: string;
  /** Present on current servers so the optimistic user row can adopt durable attachment URLs. */
  user_message?: Message;
}

/** POST /api/runs/attachments response; bytes remain server-side and expire quickly. */
export interface RunAttachmentResponse {
  attachment_token: string;
  name: string;
  mime_type: string;
  kind: "image" | "video" | "audio" | "document";
  size: number;
  expires_at: number;
}

/** Owner-scoped parsed text returned only for an active document preview. */
export interface RunAttachmentPreviewResponse {
  name: string;
  mime_type: string;
  content: string;
  truncated: boolean;
}

/** POST /api/confirmations/{id}/confirm 响应（confirmations.py） */
export interface ConfirmResponse {
  status: "confirmed";
  result: unknown;
}

export interface CancelConfirmationResponse {
  status: "cancelled";
}

/* ------------------------------------------------ SSE 事件（agent/events.py 常量，蓝图 §7） */

/**
 * 事件名 → payload 类型映射。服务端把 seq 合并进 data JSON
 * （runs.py：`{"seq": row["seq"], **payload}`），故每个 payload 都带 seq。
 */
export interface AgentEventPayloads {
  "run.started": { seq: number };
  "run.progress": AgentRunProgress;
  "message.delta": { seq: number; delta: string };
  "plan.updated": { seq: number; steps: PlanStep[] };
  "tool.call.requested": {
    seq: number;
    tool_call_id: string;
    tool: string;
    permission: "read" | "write";
    execution_kind?: "tool" | "command" | "file";
    input_summary?: string;
    args_summary?: string;
  };
  "tool.call.completed": {
    seq: number;
    tool_call_id: string;
    tool: string;
    status: string;
    duration_ms?: number;
    is_write?: number | boolean;
    execution_kind?: "tool" | "command" | "file";
    output_summary?: string;
    result?: unknown;
  };
  "rag.retrieval.started": { seq: number };
  "rag.retrieval.completed": { seq: number; hit_count: number; latency_ms: number };
  "citation.attached": { seq: number; citations: Citation[] };
  "confirmation.required": { seq: number; confirmation: Confirmation };
  /** 任务草稿完整投影（生成/同步各一次，后写覆盖先写；agent/task_drafts.py） */
  "task.draft": { seq: number; draft: TaskDraft };
  "run.completed": { seq: number; summary?: string };
  "run.failed": { seq: number; error: string };
  "run.usage": {
    seq: number;
    prompt_tokens?: number;
    completion_tokens?: number;
    model?: string;
  };
}

export type AgentEventType = keyof AgentEventPayloads;

/** 仅传输层的收尾标记（不落库），前端据此停止重连 */
export const STREAM_END_EVENT = "stream.end";

/* ================================================================ 掌握度 */

/** 掌握度状态（v3.0 §7.3.3 图谱配色口径；阈值见 mastery/service.py：≥0.8 掌握 / <0.4 待加强） */
export type MasteryStatus = "mastered" | "weak" | "beginner";

/** 掌握度预览/应用项（mastery/service.py preview_from_deltas / apply_updates） */
export interface MasteryChange {
  cap_id: string;
  delta: number;
  old_score: number | null;
  new_score: number | null;
}

/** GET /api/profile/mastery 列表项（mastery/service.py get_mastery + profile.py 能力名称） */
export interface MasteryRecord {
  cap_id: string;
  cap_name: string;
  score: number;
  source: string | null;
  updated_at: string;
}

/* ================================================================ 预设 */

export interface PresetCap {
  cap_id: string;
  cap_name: string;
  mastery_status: MasteryStatus;
  score: number | null;
}

export interface PresetUnit {
  unit_id: string;
  title: string;
  data_type?: string | null;
  goals?: string[];
}

/**
 * PresetDTO（presets.py `_preset_dto`）：蓝图 §6.3 字段 +
 * 个性化扩展（caps/units/mastered_collapsed/weak_count）。
 */
export interface Preset {
  id: string;
  title: string;
  description: string;
  data_type: string;
  goal: string;
  difficulty: number;
  est_minutes: number;
  cap_ids: string[];
  unit_ids: string[];
  recommended_for: string;
  caps: PresetCap[];
  units: PresetUnit[];
  /** 全部能力已掌握 → 前端默认折叠能力区（PRD-01 §4.4） */
  mastered_collapsed: boolean;
  weak_count: number;
}

/** 任务预览载荷（presets.py start / Agent task.preview 共用形状） */
export interface TaskPreview {
  title: string;
  goal?: string | null;
  /** New task cards expose a description while `goal` remains legacy-compatible. */
  description?: string | null;
  data_type?: string | null;
  cap_ids?: string[];
  steps?: TaskStep[];
  resources?: TaskResource[];
  /** Preview-only lesson content, used before the task rows are persisted. */
  knowledge_points?: Array<{ title: string; content?: string }>;
  exercises?: Array<{
    question: string;
    type?: "open_ended" | "multiple_choice" | "true_false" | string;
    options?: string[] | null;
  }>;
  /** An explicit staged Agent request renders each independent task preview. */
  stages?: TaskPreview[];
  source?: string;
  preset_id?: string;
  counts_toward_mastery?: number | boolean;
  [key: string]: unknown;
}

/** POST /api/presets/{id}/start 响应（presets.py） */
export interface PresetStartResponse {
  confirmation: {
    id: string;
    action_type: string;
    status: ConfirmationStatus;
    expires_at: string;
    run_id: string;
  };
  preview: TaskPreview;
}

/* ================================================================ 图谱 */

/**
 * 图谱节点（data/graph JSON 原样 + graphx/loader 规范化）。
 * 注意：名称字段是 `label`（蓝图写作 name，源文件实为 label，loader 不改名）。
 * 登录后 CAP 节点额外携带 mastery_status/mastery_score（graph.py overview）。
 */
export interface GraphNode {
  id: string;
  label: string;
  description?: string;
  data_types?: string[];
  type: "CAP" | "CERT" | "KNG" | "RES" | "TSK" | string;
  status?: string;
  source_refs?: unknown[];
  mastery_status?: MasteryStatus;
  mastery_score?: number | null;
  [key: string]: unknown;
}

/** 图谱边（源文件字段为 relation；loader 规范化时补 `type` 同值） */
export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
  type?: string;
  label?: string;
  metadata?: Record<string, unknown>;
}

export interface GraphOverview {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

/** 图谱详情投影出的可分配课程；仅包含已发布、学生可见且可消费的教学单元。 */
export interface GraphLearningMaterial {
  type: "teaching_unit";
  ref_id: string;
  title: string;
}

/** GET /api/graph/nodes/{id}（graphx/reason.py node_detail + graph.py 叠加 mastery） */
export interface GraphNodeDetail extends GraphNode {
  prerequisites: GraphNode[];
  knowledge: GraphNode[];
  resources: GraphNode[];
  tasks: GraphNode[];
  certificates: GraphNode[];
  related: GraphNode[];
  /** 图谱路由已完成可见性校验，供“开始学习”直接写入任务材料。 */
  learning_materials?: GraphLearningMaterial[];
  /** 仅登录用户查询 CAP 节点时存在 */
  mastery?: {
    score: number;
    source: string | null;
    updated_at: string;
    mastery_status: MasteryStatus;
  }[];
}

/** GET /api/graph/pre-path（graph.py；name 在节点无 name 字段时回退为 id） */
export interface PrePathResponse {
  target_id: string;
  path: { id: string; name: string; type: string | undefined }[];
  skipped_mastered: string[];
}

/* ================================================================ 学习任务 */

export type TaskStatus =
  "draft" | "not_started" | "in_progress" | "submitted" | "completed" | "paused" | "archived";

export type TaskSource = "agent" | "preset" | "teacher" | "diagnostic";
export type TaskContentStatus = "none" | "generating" | "done" | "failed";
/** Durable origin of the current task lesson; template is an explicit local fallback. */
export type TaskContentGenerationSource = "none" | "provider" | "template" | "manual" | "copied";

export interface TaskStep {
  title: string;
  description?: string;
  notes?: string;
  common_errors?: string;
  [key: string]: unknown;
}

export interface TaskResource {
  type: string;
  title: string;
  ref_id?: string;
  citation?: unknown;
  [key: string]: unknown;
}

export interface RubricItem {
  key: string;
  expected: unknown;
  weight?: number;
  hint?: string;
}

/** 学生任务详情中的评分项；服务端会剥离内部 expected 答案键。 */
export interface StudentRubricItem {
  key: string;
  weight?: number;
  hint?: string;
}

/** 学生详情只接受可渲染的练习字段；评分答案继续留在服务端 practice_json。 */
export interface StudentTaskPracticeQuestion {
  key?: string;
  prompt?: string;
  question?: string;
  title?: string;
  hint?: string;
  type?: "open_ended" | "multiple_choice" | "true_false" | string;
  options?: string[];
}

export interface StudentTaskPractice {
  questions?: StudentTaskPracticeQuestion[];
  samples?: unknown[];
  checklist?: string[];
}

/** 列表项 DTO（tasks.py `_task_summary`） */
export interface TaskSummary {
  id: string;
  title: string;
  goal: string | null;
  /** Active task description; goal remains for rolling API compatibility. */
  description?: string | null;
  data_type: string | null;
  cap_ids: string[];
  source: TaskSource;
  status: TaskStatus;
  /** Explicit Agent progress when present; legacy rows use status fallback. */
  progress: number;
  latest_score: number | null;
  counts_toward_mastery: boolean;
  due_at: string | null;
  created_at: string;
  updated_at: string;
  content_status: TaskContentStatus;
}

export interface TaskKnowledgePoint {
  id: string;
  title: string;
  content: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface TaskExerciseSubmission {
  id: string;
  answer: string;
  grade_status: "pending" | "grading" | "done" | "failed";
  score: number | null;
  feedback: string | null;
  graded_at: string | null;
  created_at: string;
  /** Safe retry metadata; provider diagnostics never leave the server. */
  grade_failure_reason?: string | null;
  retry_count?: number;
  retry_limit?: number;
  can_retry?: boolean;
  manual_review_required?: boolean;
}

export interface TaskExerciseReview {
  id: string;
  score: number;
  feedback: string;
  provider_role: "grader" | string;
  created_at: string;
}

export interface TaskExercise {
  id: string;
  question: string;
  type: "open_ended" | "multiple_choice" | "true_false" | string;
  options: string[] | null;
  sort_order: number;
  created_at: string;
  submission: TaskExerciseSubmission | null;
  reviews?: TaskExerciseReview[];
}

export interface TaskAttempt {
  id: string;
  attempt_number: number;
  score: number | null;
  mastery_applied: number | boolean;
  created_at: string;
}

/** GET /api/tasks/{id}（tasks.py task_detail） */
export interface TaskDetail extends TaskSummary {
  steps: TaskStep[];
  resources: TaskResource[];
  rubric: StudentRubricItem[] | null;
  practice: StudentTaskPractice | null;
  caps: { cap_id: string; cap_name: string }[];
  linked: {
    certificates: { id: string; name: string }[];
    knowledge: { id: string; name: string }[];
    graph_resources: { id: string; name: string }[];
  };
  teacher_id: string | null;
  class_id: string | null;
  version: number;
  parent_task_id: string | null;
  attempts: TaskAttempt[];
  /** 最近一次提交，用于刷新后恢复作答、反馈和待确认的掌握度预览。 */
  latest_attempt: TaskLatestAttempt | null;
  content_generated_at: string | null;
  knowledge_points: TaskKnowledgePoint[];
  exercises: TaskExercise[];
}

export interface FeedbackItem {
  key: string;
  expected: unknown;
  got: unknown;
  ok: boolean;
  hint: string;
}

/** GET /api/tasks/{id} 的最近提交恢复载荷（只属于当前学生）。 */
export interface TaskLatestAttempt extends TaskAttempt {
  mastery_applied: boolean;
  answers: Record<string, unknown>;
  feedback: FeedbackItem[];
  mastery_preview: MasteryChange[];
}

/** POST /api/tasks/{id}/submit（tasks.py） */
export interface SubmitTaskResponse {
  attempt_id: string;
  score: number | null;
  feedback: FeedbackItem[];
  mastery_preview: MasteryChange[];
  status: TaskStatus;
}

/** POST /api/tasks/{id}/apply-mastery（tasks.py；幂等重放时 already_applied=true） */
export interface ApplyMasteryResponse {
  applied: MasteryChange[];
  already_applied: boolean;
  status: TaskStatus;
}

/* ================================================================ 诊断 */

export type Severity = "major" | "minor";

/** 诊断错误项（diagnosis/rules.py `_err` + engine 归因/引用拼接） */
export interface DiagnosticErrorItem {
  error_type: string;
  severity: Severity;
  user_value: unknown;
  expected: string;
  rule: string;
  cap_id: string;
  suggestion: string;
  cap_name?: string;
  /** RAG 召回的规则依据（无召回时缺省，PRD-06 §9.2 不编造） */
  citations?: Citation[];
}

export interface SeverityCounts {
  major: number;
  minor: number;
}

/** 补强计划（diagnosis/engine.py `_build_plan`） */
export interface DiagnosticPlan {
  weak_caps: { cap_id: string; cap_name: string }[];
  pre_path: string[];
  resources: {
    type: string;
    unit_id: string;
    title: string;
    data_type: string | null;
  }[];
  tasks: string[];
}

/** DiagnosticReportDTO（diagnosis/engine.py diagnose；蓝图 §6.3 最低结构） */
export interface DiagnosticReport {
  file_format: string;
  sample_count: number;
  precheck: { fields: string[]; warnings: string[] };
  errors: DiagnosticErrorItem[];
  severity_counts: SeverityCounts;
  weak_cap_ids: string[];
  mastery_preview: MasteryChange[];
  plan: DiagnosticPlan;
  notice: string | null;
  /** 由路由层补写的请求上下文（engine 不含） */
  data_type?: string | null;
}

/** POST /api/diagnostics 响应 = 报告 + 内存缓存令牌（30min 有效） */
export interface DiagnosticUploadResponse extends DiagnosticReport {
  diagnostic_token: string;
}

/** POST /api/diagnostics/save-summary 响应（diagnostics.py） */
export interface SaveSummaryResponse {
  summary_id: string;
  mastery_applied: MasteryChange[];
}

/** 历史摘要列表项（diagnostics.py list_summaries；不含完整报告） */
export interface DiagnosticSummary {
  id: string;
  file_format: string;
  data_type: string | null;
  error_count: number;
  severity_counts: SeverityCounts;
  weak_cap_ids: string[];
  created_at: string;
}

/* ================================================================ 个人中心 */

/** GET /api/profile（profile.py profile_overview） */
export interface ProfileOverview {
  user: { id: string; email: string; name: string; role: Role };
  /** 状态 → 数量（learning_tasks GROUP BY status） */
  task_counts: Record<string, number>;
  recent_diagnostic_summaries: {
    id: string;
    file_format: string;
    error_count: number;
    created_at: string;
  }[];
  growth: {
    cap_id: string;
    cap_name: string;
    old_score: number;
    new_score: number;
    source: string;
    created_at: string;
  }[];
  /** P1 规划项，MVP 恒为空数组（profile.py 如实返回） */
  favorites: unknown[];
  favorites_note: string;
  /** 当前仍在籍的班级；退出班级后由 profile.py 过滤掉历史 enrollment。 */
  classes: ProfileClass[];
}

export interface ProfileClass {
  id: string;
  name: string;
  joined_at: string;
}

/** POST /api/student/join-class（profile.py） */
export interface JoinClassResponse {
  class_id: string;
  class_name: string;
  joined_at: string;
  already_enrolled: boolean;
}

/** DELETE /api/student/classes/{class_id} */
export interface LeaveClassResponse {
  class_id: string;
  class_name: string;
  message: string;
}

/* ================================================================ RAG 问答 */

/**
 * CitationDTO（蓝图 §6.4）：学生端不含 chunk_id/上传人。
 * 可信等级不在 DTO 里——PRD-01 §8 的"可信等级"由 license/visibility
 * 在管理端体现，学生端引用卡只展示文档/章节/页码/版本。
 */
export interface Citation {
  document_id: string;
  title: string;
  section_title: string | null;
  page_start: number | null;
  page_end: number | null;
  version: string;
  score: number;
}

/** RagAnswerDTO（rag/retriever.py RagAnswer dataclass asdict） */
export interface RagAnswer {
  answer: string;
  steps: string[];
  notes: string[];
  followups: string[];
  citations: Citation[];
  related_cap_ids: string[];
  /** 无召回/低于阈值 → true，此时 answer 为拒答说明，绝不编造（AC6） */
  refused: boolean;
  notice: string | null;
}

/* ================================================================ RAG 管理 */

export type RagDocumentStatus =
  | "draft"
  | "parsing"
  | "parsed"
  | "chunking"
  | "chunked"
  | "indexing"
  | "indexed"
  | "review_pending"
  | "published"
  | "rejected"
  | "archived"
  | "expired"
  | "failed";

/** 资料 DTO（rag_admin.py `_doc_dto`；JSON 列已展开为数组） */
export interface RagDocument {
  id: string;
  title: string;
  file_type: string;
  source_type: string;
  source_name: string;
  source_url: string | null;
  source_ledger_id: string | null;
  version: string;
  license_status: "authorized" | "internal" | "pending" | "forbidden";
  data_types: string[];
  cap_ids: string[];
  visibility: "admin" | "teacher" | "student";
  status: RagDocumentStatus;
  file_hash: string | null;
  error_code: string | null;
  error_message: string | null;
  process_version: number;
  created_by: string;
  created_at: string;
  updated_at: string;
  published_at: string | null;
  expires_at: string | null;
  /** 仅列表/详情响应携带 */
  chunk_count?: number;
}

/** 切片 DTO（rag_admin.py `_chunk_dto`） */
export interface RagChunk {
  id: string;
  document_id: string;
  chunk_index: number;
  content: string;
  summary: string | null;
  keywords: string[];
  page_start: number | null;
  page_end: number | null;
  section_title: string | null;
  token_count: number;
  embedding_model: string | null;
  metadata: Record<string, unknown>;
  status: "active" | "disabled";
  process_version: number;
}

export type RagJobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

/** 管线任务 DTO（rag_admin.py `_job_dto`；params 已剥离大块产物） */
export interface RagJob {
  id: string;
  document_id: string;
  stage: "parse" | "chunk" | "index";
  status: RagJobStatus;
  idempotency_key: string | null;
  progress: number;
  error_code: string | null;
  error_message: string | null;
  attempt: number;
  params: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ReviewRecord {
  id: string;
  action: "submit" | "approve" | "approve_teacher_only" | "reject" | "archive" | "publish" | string;
  comment: string | null;
  reviewer_id: string;
  created_at: string;
}

/** GET /api/rag/documents/{id}（rag_admin.py get_document） */
export interface DocumentDetailResponse {
  document: RagDocument;
  jobs: RagJob[];
  /** 最近一次解析的敏感信息标志（无解析任务时为 null） */
  sensitive_flags: Record<string, unknown> | null;
  ledger: SourceLedger | null;
  review_records: ReviewRecord[];
}

/** 上传/重处理响应（rag_admin.py upload_document / _reprocess） */
export interface DocumentPipelineResponse {
  document: RagDocument;
  jobs: RagJob[];
  run?: Record<string, unknown>;
  enqueued_job_ids?: string[];
}

/** 来源台账 DTO + 风险提示（rag_admin.py `_ledger_dto`，PRD-03 §9） */
export interface SourceLedger {
  id: string;
  source_code: string;
  name: string;
  publisher: string | null;
  source_type: string | null;
  version: string | null;
  authorization_status: "approved" | "pending" | "expired" | "forbidden";
  valid_from: string | null;
  valid_to: string | null;
  related_document_ids: string[];
  review_status: "draft" | "reviewed" | "published";
  notes: string | null;
  created_at: string;
  updated_at: string;
  risk_expired: boolean;
  risk_unauthorized: boolean;
  risk_no_documents: boolean;
}

/** 保留管理检索 API 的命中 DTO（rag_admin.py `_hit_debug_dict`；含 chunk_id）。 */
export interface SearchTestHit {
  chunk_id: string;
  document_id: string;
  title: string;
  section_title: string | null;
  page_start: number | null;
  page_end: number | null;
  version: string;
  content: string;
  score: number;
  rerank_score: number | null;
}

/** Explicit retrieval strategies shared by the retained management API and student answers. */
export type RagRetrievalMode = "vector" | "keyword" | "hybrid";

/** POST /api/rag/query；学生问答与保留管理检索 API 复用同一检索形状。 */
export interface RagQueryRequest {
  question: string;
  data_type?: string | null;
  published_only?: boolean;
  document_ids?: string[] | null;
  mode?: RagRetrievalMode | null;
  top_k?: number | null;
  /** Per-request nucleus override; only meaningful for vector mode. */
  retrieval_top_p?: number | null;
}

/** POST /api/rag/search-test（保留兼容 API；rag_admin.py search_test）。 */
export interface SearchTestResult {
  vector_results: SearchTestHit[];
  reranked_results: SearchTestHit[];
  /** 未启用重排时的说明（启用时为 null） */
  rerank_note: string | null;
  below_threshold: boolean;
  notice: string | null;
  diagnostics: {
    latency_ms: number;
    embedding_model: string | null;
    rerank_model: string | null;
    /** Effective vector / keyword / hybrid mode for this run. */
    retrieval_mode?: "vector" | "keyword" | "hybrid";
    /** Per-run vector-only nucleus override; distinct from answer top_p. */
    retrieval_top_p?: number | null;
    /** Selected set is echoed so an ad-hoc console run cannot be mislabeled. */
    eval_set_id?: string | null;
    filters: Record<string, unknown>;
    prompt_template_version: string;
  };
  /** save=true 时返回新评测用例 id */
  saved_case_id?: string;
}

export interface EvalCase {
  id: string;
  question: string;
  expected_answer: string | null;
  must_hit_document_ids: string[];
  must_hit_chunk_ids: string[];
  filters: Record<string, unknown>;
  eval_set_id?: string | null;
  /** Compatibility alias accepted by the API during the test-set migration. */
  test_set_id?: string | null;
  created_by: string;
  created_at: string;
}

/** Named regression collection for saved recall test cases. */
export interface EvalSet {
  id: string;
  name: string;
  description: string | null;
  case_count: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface EvalCaseResult {
  case_id: string;
  question: string;
  refused: boolean;
  hit_document_ids: string[];
  hit_chunk_ids: string[];
  recall_hit: boolean | null;
  citation_ok: boolean | null;
  refusal_ok: boolean | null;
  faithfulness: number | null;
  latency_ms: number;
}

/** 评测指标（rag_admin.py run_eval；无样本的指标为 null） */
export interface EvalMetrics {
  recall_at_k: number | null;
  citation_accuracy: number | null;
  refusal_accuracy: number | null;
  answer_faithfulness: number | null;
  latency_ms_avg: number | null;
  case_count: number;
}

export interface EvalRun {
  id: string;
  status: "running" | "completed" | "failed";
  metrics: EvalMetrics | null;
  case_results: EvalCaseResult[];
  eval_set_id?: string | null;
  test_set_id?: string | null;
  created_by?: string;
  created_at?: string;
  finished_at?: string | null;
}

/* ================================================================ 教师端 */

/** GET /api/teacher/dashboard（teacher.py dashboard） */
export interface TeacherDashboard {
  classes: {
    id: string;
    name: string;
    student_count: number;
    /** 无任务时为 null */
    task_completion_rate: number | null;
    avg_mastery: number | null;
  }[];
  weak_caps_top5: {
    cap_id: string;
    cap_name: string;
    avg_score: number;
    student_count: number;
  }[];
  todos: {
    unpublished_teacher_tasks: number;
  };
}

/** Published RAG material exposed to teachers only for attaching a resource to a teaching task. */
export interface TeacherResource {
  id: string;
  title: string;
  version: string;
}

/** GET /api/teacher/classes 列表项 */
export interface ClassInfo {
  id: string;
  name: string;
  invite_code: string;
  student_count: number;
  recent_task_title: string | null;
  created_at: string;
}

/** GET /api/teacher/classes/{id} */
export interface ClassDetail {
  id: string;
  name: string;
  invite_code: string;
  student_count: number;
  avg_mastery: number | null;
  recent_tasks: {
    id: string;
    title: string;
    status: TaskStatus;
    due_at: string | null;
    created_at: string;
  }[];
  created_at: string;
}

/** GET /api/teacher/classes/{id}/students 列表项 */
export interface StudentRow {
  id: string;
  name: string;
  email: string;
  task_count: number;
  completion_rate: number | null;
  avg_mastery: number | null;
  last_active: string | null;
  joined_at: string;
  left_at: string | null;
}

/** 教师任务 DTO（teacher.py `_teacher_task_dto`；原件即 learning_tasks 行） */
export interface TeacherTask {
  id: string;
  title: string;
  goal: string | null;
  description?: string | null;
  data_type: string | null;
  cap_ids: string[];
  steps: TaskStep[];
  resources: TaskResource[];
  rubric: RubricItem[] | null;
  practice: Record<string, unknown> | null;
  status: TaskStatus;
  /** Agent 草稿的来源班级；手动创建的教师草稿可为空。 */
  class_id: string | null;
  version: number;
  parent_task_id: string | null;
  /** 已发布的学生副本份数（发布状态由副本数推导） */
  published_count: number;
  /** 任务创建后自动生成的 AI 学习内容状态。旧服务端缺省为 none。 */
  content_status?: TaskContentStatus;
  content_generated_at?: string | null;
  /** Provider success, deterministic fallback, manually reviewed, or copied content. */
  content_generation_source?: TaskContentGenerationSource;
  /** Safe, actionable summary when background generation could not finish. */
  content_failure_reason?: string | null;
  /** Safe explanation for a successful template fallback that still needs review. */
  content_generation_message?: string | null;
  /** Explicit failed-generation retries; the initial generation does not increment it. */
  content_generation_retry_count?: number;
  content_last_attempt_at?: string | null;
  knowledge_points?: TaskKnowledgePoint[];
  exercises?: Array<TaskExercise & { reference_answer?: string | null }>;
  created_at: string;
  updated_at: string;
  /** 仅 PATCH 响应携带：有学生副本时编辑产生 version+1 新记录 */
  version_bumped?: boolean;
}

/** POST /api/teacher/tasks/{id}/publish 响应 */
export interface PublishTaskResponse {
  published: number;
  class_id: string;
}

/** GET /api/teacher/analytics（teacher.py analytics；数字全部来自真实学习数据） */
export interface Analytics {
  heatmap: {
    cap_id: string;
    cap_name: string;
    avg_score: number;
    weak_count: number;
    student_count: number;
  }[];
  trend: { date: string; submissions: number; completions: number }[];
  top_errors: { error_type: string; count: number; major: number; minor: number }[];
  suggestions: string[];
  student_count: number;
  /** 学生 <3 人时为 true（PRD-06 §10.2 样本过小提示） */
  sample_warning: boolean;
}

/** GET /api/rag/review-queue 列表项（仅 system_admin） */
export interface ReviewQueueItem {
  id: string;
  title: string;
  uploader_name: string | null;
  source_type: string;
  data_types: string[];
  submitted_at: string;
}

/* ================================================================ 系统管理 */

export type ProviderProtocol = "chat_completions" | "anthropic_messages" | "responses";

export type ProviderRole = "primary" | "fallback" | "embedding" | "rerank" | "grader" | "none";

/**
 * Provider DTO；一个供应商可以承担多个 roles，但每个 role 在运行时只
 * 对应一个模型。服务端仍返回 role 作为旧客户端的首角色投影。
 */
export interface ProviderConfig {
  id: string;
  name: string;
  protocol: ProviderProtocol;
  base_url: string;
  model: string;
  role: ProviderRole;
  roles: ProviderRole[];
  enabled: boolean;
  timeout_seconds: number;
  extra: Record<string, unknown>;
  api_key_set: boolean;
  api_key_masked: string;
  last_test: ProviderTestResult | null;
  created_at: string;
  updated_at: string;
}

/** POST /api/admin/providers/{id}/test（agent/providers.py test_provider） */
export interface ProviderTestResult {
  ok: boolean;
  latency_ms: number;
  model: string;
  /** 安全短码，不含密钥/URL */
  error: string | null;
  tested_at: string;
}

/** 模型发现的安全投影：仅返回可展示的标识，不回传供应商原始响应。 */
export interface ProviderModelOption {
  id: string;
  label: string;
}

/** POST provider discover-models 的临时结果；API Key 只用于本次服务端请求。 */
export interface ProviderModelDiscoveryResult {
  /**
   * False means the configured provider does not expose model discovery. The
   * protocol itself remains valid and the administrator can enter a model name.
   */
  supported: boolean;
  models: ProviderModelOption[];
}

/** GET/PATCH /api/admin/rag-settings（admin.py `_rag_settings_dto`；布尔已转换） */
export interface RagSettings {
  id: number;
  chunk_size: number;
  chunk_overlap: number;
  title_inherit: boolean;
  top_k: number;
  score_threshold: number;
  temperature: number;
  top_p: number;
  hybrid_search: boolean;
  rerank_enabled: boolean;
  query_rewrite_enabled: boolean;
  updated_at: string;
  updated_by: string | null;
}

/** GET /api/admin/users 列表项（admin.py `_admin_user_dto`） */
export interface AdminUser {
  id: string;
  email: string;
  name: string;
  role: Role;
  status: "active" | "disabled";
  email_verified: boolean;
  created_at: string;
}

/** POST /api/admin/users/{id}/reset-password（临时密码仅此一次可见） */
export interface AdminResetPasswordResponse {
  temporary_password: string;
  message: string;
}

/** GET /api/admin/audit-logs 列表项（before/after 已 JSON 展开） */
export interface AuditLog {
  id: string;
  actor_id: string | null;
  actor_role: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  before: unknown;
  after: unknown;
  ip: string | null;
  user_agent: string | null;
  created_at: string;
}

/** 运营指标（admin.py `_build_metrics`；无样本指标为 null，见 note） */
export interface Metrics {
  tool_call_success_rate: Record<string, { total: number; success_rate: number }> | null;
  rag_retrieval_hit_rate: number | null;
  rag_refusal_rate: number | null;
  task_creation_conversion: number | null;
  preset_start_rate: number | null;
  diagnostic_success_rate: number | null;
  mastery_confirm_rate: number | null;
  model_failure_rate_by_provider: Record<
    string,
    {
      name: string;
      runs_total: number;
      runs_failed: number;
      run_failure_rate: number | null;
      last_test_ok: boolean | null;
    }
  > | null;
  /** Runtime health counters; zero is a real count, while rates stay null without telemetry. */
  login_success_today: number;
  login_failure_today: number;
  active_sessions: number;
  api_success_rate_24h: number | null;
  provider_latency_avg_ms: number | null;
}

/** GET /api/admin/metrics */
export interface MetricsResponse {
  metrics: Metrics;
  note: string;
}

/* ================================================================ 埋点 */

/** POST /api/events 响应（events.py，202） */
export interface EventsAcceptedResponse {
  accepted: number;
}
