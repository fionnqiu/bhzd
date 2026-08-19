/**
 * 对话页运行状态机 hook（PRD-01 §3.5 六态：空白/计划中/工具调用中/等待确认/已完成/失败）。
 * SSE 接线在 runStream.ts，这里只做事件 → UI 状态的归约；
 * 新 run / 卸载 / 切换会话时统一 close 旧流，防止脏事件串台。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiRequestError, api } from "../../../api/client";
import { useToast } from "../../../components";
import type { RunEventStream } from "../../../api/sse";
import type {
  Citation,
  Confirmation,
  ConversationDetail,
  CreateRunResponse,
  MessageAttachment,
  PlanStep,
  RunDetail,
  ToolCall,
} from "../../../api/types";
import { attachRunStream } from "./runStream";
import { createSmoothTyper, type SmoothTyper } from "./smoothTyper";
import { actionLabel, toolLabel } from "./constants";
import { nextId } from "./types";
import type {
  ActivityEntry,
  ActivityStage,
  ActivityStatus,
  ChatAttachment,
  ChatMessage,
  CockpitStatus,
  EmbeddedCardData,
  StartRunOptions,
  TraceEntry,
} from "./types";

// 子组件可能只依赖类型：统一从 types.ts 出口，避免反向依赖 hook 实现
export type {
  ActivityEntry,
  ActivityStage,
  ActivityStatus,
  ChatMessage,
  CockpitStatus,
  EmbeddedCardData,
  StartRunOptions,
  TraceEntry,
} from "./types";

type StreamRecoveryState =
  | { kind: "reconnecting"; retryAttempt: number; retryInMs: number }
  | { kind: "disconnected"; message: string };

type ReconciliationSource = "manual" | "stream_end" | "interrupted" | "exhausted";

type ReconciledActivity = {
  key: string;
  activity: ActivityEntry;
};

const ACTIVITY_TEXT_LIMIT = 240;
const SENSITIVE_ACTIVITY_HEADER_VALUE =
  /((?:"|')?(?:authorization|proxy-authorization|cookie|set-cookie)(?:"|')?\s*[:=：]\s*)(?:"[^"]*"|'[^']*'|[^\r\n]+)/gi;
const SENSITIVE_ACTIVITY_VALUE =
  /((?:"|')?(?:api[_ -]?key|access[_ -]?token|token|secret|password|session[_ -]?id)(?:"|')?\s*[:=：]\s*)(?:"[^"]*"|'[^']*'|[^\s,，;；}\]]+)/gi;

/**
 * Progress messages originate from a safe backend contract, but this final UI
 * guard prevents an accidental credential-like value in a future summary from
 * becoming visible in the activity feed.
 */
function safeActivityText(value: string | null | undefined): string | undefined {
  const text = value?.replace(/\s+/g, " ").trim();
  if (!text) return undefined;
  // Header-like values can contain whitespace (for example `Basic <value>`)
  // or many cookie pairs, so hide the entire remainder before redacting the
  // smaller JSON/key-value forms below.
  const redacted = text
    .replace(SENSITIVE_ACTIVITY_HEADER_VALUE, "$1已隐藏")
    .replace(SENSITIVE_ACTIVITY_VALUE, "$1已隐藏")
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, "授权信息：已隐藏");
  return redacted.length > ACTIVITY_TEXT_LIMIT
    ? `${redacted.slice(0, ACTIVITY_TEXT_LIMIT - 1)}…`
    : redacted;
}

/**
 * 模块级的即时查询（非响应式）：smoothTyper 只需在建流那一刻判断一次，
 * 与 usePresence 的 useReducedMotion 同一媒体查询，但不需要订阅变化。
 */
function systemPrefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

const SENSITIVE_RESULT_KEY =
  /^(?:authorization|proxy-authorization|cookie|set-cookie|api[_ -]?key|access[_ -]?token|token|secret|password|session[_ -]?id|diagnostic[_ -]?token)$/i;

const TASK_SYNC_CONFIRMATION_COMMANDS = new Set([
  "同步到系统中",
  "同步到学习任务",
  "同步到学习任务中",
  "同步任务",
  "确认同步",
  "确认创建",
  "创建任务",
  "保存任务",
]);

/**
 * Recognize only short, explicit sync confirmations after removing harmless
 * whitespace and punctuation. Broader wording stays in the normal chat path
 * so the composer never turns a question into an unintended system write.
 */
export function isTaskSyncConfirmationCommand(input: string): boolean {
  const normalized = input.replace(/[\s，,。！!、]/g, "").toLowerCase();
  return TASK_SYNC_CONFIRMATION_COMMANDS.has(normalized);
}

/** Last-mile guard for typed result cards when an older server omits redaction. */
function safeToolResult(value: unknown, depth = 0): unknown {
  if (depth > 5) return "内容已省略";
  if (typeof value === "string") return safeActivityText(value) ?? "";
  if (Array.isArray(value))
    return value.slice(0, 40).map((item) => safeToolResult(item, depth + 1));
  if (value && typeof value === "object") {
    const projected: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>).slice(0, 40)) {
      projected[key] = SENSITIVE_RESULT_KEY.test(key) ? "已隐藏" : safeToolResult(item, depth + 1);
    }
    return projected;
  }
  return value;
}

function activityEntry(
  seq: number,
  stage: ActivityStage,
  status: ActivityStatus,
  message: string,
  options: Omit<ActivityEntry, "seq" | "stage" | "status" | "message"> = {},
): ActivityEntry {
  return {
    ...options,
    seq,
    eventSeq: seq,
    stage,
    status,
    message: safeActivityText(message) ?? "智能体正在处理任务",
    detail: safeActivityText(options.detail),
    inputSummary: safeActivityText(options.inputSummary),
    outputSummary: safeActivityText(options.outputSummary),
  };
}

function activityStatusForProgress(status: string): ActivityStatus {
  if (status === "waiting_confirmation") return "waiting";
  if (status === "completed" || status === "failed") return status;
  return "running";
}

function activityStatusForToolCall(status: string): ActivityStatus {
  if (status === "completed") return "completed";
  if (status === "awaiting_confirmation") return "waiting";
  if (status === "requested" || status === "running") return "running";
  return "failed";
}

function toolActivityMessage(tool: string, status: string): string {
  const label = toolLabel(tool);
  if (status === "completed") return `${label}已完成`;
  if (status === "awaiting_confirmation") return `${label}等待确认`;
  if (status === "requested" || status === "running") return `正在执行${label}`;
  return `${label}未完成`;
}

/**
 * Recovery reads contain durable tool rows but not their event sequence.  Give
 * missing rows a negative local sequence so a later SSE replay can update the
 * same tool lifecycle without colliding with a persisted event number.
 */
function recoveredToolActivity(toolCall: ToolCall, index: number): ActivityEntry {
  return activityEntry(
    -index - 1,
    "tool",
    activityStatusForToolCall(toolCall.status),
    toolActivityMessage(toolCall.tool, toolCall.status),
    {
      tool: toolCall.tool,
      toolCallId: toolCall.id,
      executionKind: toolCall.execution_kind ?? "tool",
      inputSummary: toolCall.input_summary,
      outputSummary: toolCall.output_summary,
      durationMs: toolCall.duration_ms,
      isWrite: toolCall.is_write,
    },
  );
}

function activityKey(entry: ActivityEntry): string | null {
  if (entry.activityId) return `progress:${entry.activityId}`;
  if (entry.toolCallId) return `tool:${entry.toolCallId}`;
  return null;
}

const HISTORICAL_VISIBLE_STAGES = new Set<ActivityStage>([
  "planning",
  "retrieval",
  "tool",
  "responding",
  "confirmation",
]);
const HISTORICAL_VISIBLE_STATUSES = new Set<ActivityStatus>([
  "running",
  "completed",
  "waiting",
  "failed",
]);

/**
 * Re-project the already redacted history DTO at the UI boundary. This keeps a
 * gradual backend rollout and malformed cached responses from recreating
 * hidden model-intent rows in the learner execution record.
 */
function historicalActivityMap(
  activitiesByRun: ConversationDetail["activities_by_run"],
): Record<string, ActivityEntry[]> {
  const history: Record<string, ActivityEntry[]> = {};
  if (!activitiesByRun) return history;

  for (const [runId, entries] of Object.entries(activitiesByRun)) {
    if (!runId || !Array.isArray(entries)) continue;
    const resolved: ActivityEntry[] = [];

    for (const entry of entries) {
      if (
        !Number.isSafeInteger(entry.seq) ||
        entry.seq < 1 ||
        typeof entry.message !== "string" ||
        !entry.message.trim() ||
        !HISTORICAL_VISIBLE_STAGES.has(entry.stage) ||
        !HISTORICAL_VISIBLE_STATUSES.has(entry.status) ||
        (entry.stage === "tool" && !entry.tool) ||
        (entry.stage === "responding" &&
          entry.activity_id !== `answer:${runId}` &&
          entry.activity_id !== `history-answer:${runId}`)
      ) {
        continue;
      }
      const eventSeq =
        typeof entry.event_seq === "number" &&
        Number.isSafeInteger(entry.event_seq) &&
        entry.event_seq >= entry.seq
          ? entry.event_seq
          : entry.seq;
      const projected = activityEntry(entry.seq, entry.stage, entry.status, entry.message, {
        eventSeq,
        activityId: entry.activity_id,
        detail: entry.detail,
        tool: entry.tool,
        executionKind: entry.execution_kind,
        toolCallId: entry.tool_call_id,
        inputSummary: entry.input_summary,
        outputSummary: entry.output_summary,
        durationMs: entry.duration_ms,
        isWrite: entry.is_write,
      });
      const key = activityKey(projected);
      const matchingIndex = key ? resolved.findIndex((item) => activityKey(item) === key) : -1;
      if (matchingIndex < 0) {
        resolved.push(projected);
        continue;
      }

      const existing = resolved[matchingIndex];
      // A persisted request/completion pair is one learner-visible lifecycle.
      // Keep the first event's placement beside its reply, while the newest
      // durable event supplies the terminal status and timing.
      if (eventSeq <= (existing.eventSeq ?? existing.seq)) continue;
      resolved[matchingIndex] = {
        ...existing,
        ...projected,
        seq: existing.seq,
        detail: projected.detail ?? existing.detail,
      };
    }

    if (resolved.length > 0) {
      history[runId] = resolved.sort((left, right) => left.seq - right.seq);
    }
  }
  return history;
}

function visiblePlanSteps(steps: PlanStep[]): PlanStep[] {
  // The timeline receives only server-issued titles and status values. RAG
  // steps remain visible as bounded process milestones, never raw hits.
  return steps;
}

function projectMessageAttachments(
  attachments: MessageAttachment[] | undefined,
): ChatAttachment[] | undefined {
  return attachments?.map((attachment) => ({
    id: attachment.id,
    name: attachment.name,
    kind: attachment.kind,
    mimeType: attachment.mime_type,
    size: attachment.size,
    thumbnailUrl: attachment.thumbnail_url ?? null,
  }));
}

function mergePersistedMessageAttachments(
  localAttachments: ChatAttachment[] | undefined,
  persistedAttachments: ChatAttachment[] | undefined,
): ChatAttachment[] | undefined {
  if (!persistedAttachments) return localAttachments;
  return persistedAttachments.map((attachment, index) => ({
    ...attachment,
    // Keep the transferred URL long enough for CockpitPage to revoke it. The
    // renderer always prefers thumbnailUrl, while a missing safe thumbnail can
    // still use this live image preview until the next history projection.
    previewUrl:
      attachment.kind === "image" ? (localAttachments?.[index]?.previewUrl ?? null) : null,
  }));
}

export function useCockpitRun() {
  const toast = useToast();
  const [status, setStatus] = useState<CockpitStatus>("idle");
  const [runId, setRunId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [planSteps, setPlanSteps] = useState<PlanStep[]>([]);
  const [trace, setTrace] = useState<TraceEntry[]>([]);
  const [activities, setActivities] = useState<ActivityEntry[]>([]);
  const [historicalActivitiesByRun, setHistoricalActivitiesByRun] = useState<
    Record<string, ActivityEntry[]>
  >({});
  const [reconciledActivity, setReconciledActivity] = useState<ReconciledActivity | null>(null);
  const [cards, setCards] = useState<EmbeddedCardData[]>([]);
  const [citations, setCitations] = useState<Citation[]>([]);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [streamRecovery, setStreamRecovery] = useState<StreamRecoveryState | null>(null);

  const streamRef = useRef<RunEventStream | null>(null);
  // Confirmation pauses the backend run but keeps its SSE subscription alive.
  // Track transport liveness separately from the object reference because an
  // exhausted or stream-ended instance still retains the durable replay cursor.
  const streamActiveRef = useRef(false);
  const runIdRef = useRef<string | null>(null);
  /**
   * 流式回复的平滑打字机（见 smoothTyper.ts）：SSE delta 先进缓冲，按帧匀速
   * 渲染到助手气泡；终态由 sealStreamingMessages 先 flush 再封口，一字不丢。
   * 测试与 prefers-reduced-motion 走 instant 直通（delta 到达即整块渲染）。
   */
  const typerRef = useRef<SmoothTyper | null>(null);
  // Terminal events do not always carry a reply body. Track whether this run
  // actually produced one so `run.completed` never invents an answer step.
  const assistantResponseObservedRef = useRef(false);
  // A recovery override stays visible only until a later persisted activity
  // arrives, so it cannot compete with the SSE sequence space.
  const activitySequenceRef = useRef(0);
  // Ignore a late status response from an older stream or an earlier retry.
  const reconciliationRequestRef = useRef(0);
  // Reconciliation GET failures are transport uncertainty, not proof that the
  // backend run failed. Retry a few times before showing a disconnected card.
  const reconciliationAttemptRef = useRef(0);
  const reconciliationRetryTimerRef = useRef<number | null>(null);
  // A confirmation can be visible in two tabs.  Remember the request owner so
  // this tab sends at most one expiry request while awaiting the terminal SSE.
  const expiryRequestRef = useRef<string | null>(null);
  // A server can legitimately be a little behind the browser clock.  Keep one
  // retry timer per card so CONFIRMATION_NOT_EXPIRED cannot strand a disabled UI.
  const expiryRetryTimerRef = useRef<number | null>(null);
  const confirmationRef = useRef<Confirmation | null>(null);
  // The confirm and cancel buttons are siblings. A ref closes the brief window
  // before React disables them, so one task preview cannot submit two writes.
  const confirmationActionRef = useRef<string | null>(null);
  // Composer submission is declared before the confirmation callback below.
  // A ref lets a typed confirmation phrase reuse that same guarded write path
  // without creating a second Agent run or duplicating confirmation logic.
  const confirmRef = useRef<() => Promise<void>>(async () => {});
  // UI buttons normally reflect `status`, but a ref closes the synchronous
  // double-submit window before React has committed the first planning state.
  const startInFlightRef = useRef(false);
  const expireRef = useRef<(target: Confirmation | null, signal?: AbortSignal) => Promise<void>>(
    async () => {},
  );
  // 最近一次输入：run.failed 后"重试"按原样重发（PRD-01 §3.5 可操作下一步）
  const lastInputRef = useRef<{ input: string; options: StartRunOptions } | null>(null);
  const conversationIdRef = useRef<string | null>(null);
  conversationIdRef.current = conversationId;
  confirmationRef.current = confirmation;

  const closeStream = useCallback(() => {
    streamRef.current?.close();
    streamRef.current = null;
    streamActiveRef.current = false;
  }, []);

  const clearExpiryRetry = useCallback(() => {
    if (expiryRetryTimerRef.current !== null) {
      window.clearTimeout(expiryRetryTimerRef.current);
      expiryRetryTimerRef.current = null;
    }
    expiryRequestRef.current = null;
  }, []);

  const clearReconcileRetry = useCallback(() => {
    if (reconciliationRetryTimerRef.current !== null) {
      window.clearTimeout(reconciliationRetryTimerRef.current);
      reconciliationRetryTimerRef.current = null;
    }
    reconciliationAttemptRef.current = 0;
  }, []);

  const scheduleExpiryRetry = useCallback((target: Confirmation, signal?: AbortSignal) => {
    if (expiryRetryTimerRef.current !== null) {
      window.clearTimeout(expiryRetryTimerRef.current);
    }
    // A one-second retry bounds traffic under a large clock skew but still lets
    // a just-early browser converge without user interaction.
    expiryRetryTimerRef.current = window.setTimeout(() => {
      expiryRetryTimerRef.current = null;
      if (confirmationRef.current?.id === target.id) {
        void expireRef.current(target, signal);
      }
    }, 1_000);
  }, []);

  // 卸载时关闭 SSE（契约：主动 close 幂等，不再重连）并停掉打字机定时器
  useEffect(
    () => () => {
      closeStream();
      typerRef.current?.dispose();
      clearExpiryRetry();
      clearReconcileRetry();
    },
    [clearExpiryRetry, clearReconcileRetry, closeStream],
  );

  useEffect(() => {
    // Terminal renders release the guard for retry/new-run actions.  A run that
    // is still reconnecting remains locked because the server may continue it.
    if (status === "idle" || status === "completed" || status === "failed") {
      startInFlightRef.current = false;
    }
  }, [status]);

  /**
   * 打字机帧回调：把当前应显示的全文写入助手气泡。气泡不存在时按 runId
   * 固定 id 新建（streaming: true 驱动打字光标），存在则原地更新内容；
   * 用 findIndex 而非只看末尾，避免工具卡插入顺序变化时漏更新。
   */
  const renderTyperFrame = useCallback((text: string) => {
    const bubbleId = `asst-${runIdRef.current ?? "draft"}`;
    setMessages((prev) => {
      const index = prev.findIndex((message) => message.id === bubbleId);
      if (index < 0) {
        return [
          ...prev,
          {
            id: bubbleId,
            runId: runIdRef.current,
            role: "assistant" as const,
            content: text,
            streaming: true,
          },
        ];
      }
      const existing = prev[index];
      if (existing.content === text) return prev;
      return [...prev.slice(0, index), { ...existing, content: text }, ...prev.slice(index + 1)];
    });
  }, []);

  const getTyper = useCallback(() => {
    if (!typerRef.current) {
      typerRef.current = createSmoothTyper({
        // 测试环境断言同步文本、reduced-motion 用户减少动态变化：两者都直通
        instant: import.meta.env.MODE === "test" || systemPrefersReducedMotion(),
        onRender: renderTyperFrame,
      });
    }
    return typerRef.current;
  }, [renderTyperFrame]);

  const appendDelta = useCallback(
    (delta: string) => {
      assistantResponseObservedRef.current = true;
      getTyper().push(delta);
    },
    [getTyper],
  );

  const advanceActivitySequence = useCallback((seq: number) => {
    activitySequenceRef.current = Math.max(activitySequenceRef.current, seq);
  }, []);

  const appendActivity = useCallback(
    (incoming: ActivityEntry) => {
      const incomingSequence = incoming.eventSeq ?? incoming.seq;
      advanceActivitySequence(incomingSequence);
      setReconciledActivity((current) => {
        if (!current) return null;
        const recoveredSequence = current.activity.eventSeq ?? current.activity.seq;
        return incomingSequence > recoveredSequence ? null : current;
      });
      setActivities((previous) => {
        const incomingKey = activityKey(incoming);
        if (incomingKey) {
          const matchingActivityIndex = previous.findIndex(
            (entry) => activityKey(entry) === incomingKey,
          );
          if (matchingActivityIndex >= 0) {
            const existing = previous[matchingActivityIndex];
            // Both tool calls and tagged model progress arrive as lifecycle frames.
            // Preserve their first position while the newest persisted event owns
            // the status, so reconnect replay cannot resurrect a finished row.
            if ((incoming.eventSeq ?? incoming.seq) <= (existing.eventSeq ?? existing.seq)) {
              return previous;
            }
            const updated = {
              ...existing,
              ...incoming,
              seq: existing.seq,
              detail: incoming.detail ?? existing.detail,
              tool: incoming.tool ?? existing.tool,
              toolCallId: incoming.toolCallId ?? existing.toolCallId,
              inputSummary: incoming.inputSummary ?? existing.inputSummary,
              outputSummary: incoming.outputSummary ?? existing.outputSummary,
              executionKind: incoming.executionKind ?? existing.executionKind,
              durationMs: incoming.durationMs ?? existing.durationMs,
              isWrite: incoming.isWrite ?? existing.isWrite,
            };
            return [
              ...previous.slice(0, matchingActivityIndex),
              updated,
              ...previous.slice(matchingActivityIndex + 1),
            ];
          }
        }
        // SSE replay can repeat an already persisted frame after reconnect. Insert
        // out-of-order frames by sequence so the visible audit stays chronological.
        if (previous.some((entry) => entry.seq === incoming.seq)) return previous;
        const insertionIndex = previous.findIndex((entry) => entry.seq > incoming.seq);
        if (insertionIndex < 0) return [...previous, incoming];
        return [...previous.slice(0, insertionIndex), incoming, ...previous.slice(insertionIndex)];
      });
    },
    [advanceActivitySequence],
  );

  const hydrateRecoveredTools = useCallback((toolCalls: ToolCall[]) => {
    setActivities((previous) => {
      const next = [...previous];
      for (const [index, toolCall] of toolCalls.entries()) {
        const recovered = recoveredToolActivity(toolCall, index);
        const matchingIndex = next.findIndex((entry) => entry.toolCallId === toolCall.id);
        if (matchingIndex < 0) {
          next.push(recovered);
          continue;
        }

        const existing = next[matchingIndex];
        // GET /runs is authoritative after a dropped stream. Preserve the
        // original visual position while replacing its lifecycle state and
        // retaining any richer summary received from SSE.
        next[matchingIndex] = {
          ...existing,
          ...recovered,
          seq: existing.seq,
          eventSeq: existing.eventSeq ?? recovered.eventSeq,
          detail: existing.detail ?? recovered.detail,
          inputSummary: recovered.inputSummary ?? existing.inputSummary,
          outputSummary: recovered.outputSummary ?? existing.outputSummary,
        };
      }
      return next.sort((left, right) => left.seq - right.seq);
    });
  }, []);

  const settleVisibleActivities = useCallback(
    (terminalStatus: Extract<ActivityStatus, "completed" | "failed">, terminalSeq: number) => {
      setActivities((previous) =>
        previous.map((activity) => {
          if (activity.status !== "running" && activity.status !== "waiting") return activity;
          // A terminal SSE frame can arrive after an earlier lifecycle frame was
          // lost during reconnect. Close that real activity in place instead of
          // appending a generic "work completed" row on every answer.
          const completionMessage =
            activity.stage === "responding"
              ? terminalStatus === "completed"
                ? "回答已生成"
                : "回答未完成"
              : activity.stage === "tool"
                ? `${toolLabel(activity.tool ?? "工具")}${
                    terminalStatus === "completed" ? "已完成" : "未完成"
                  }`
                : activity.stage === "confirmation"
                  ? terminalStatus === "completed"
                    ? "确认流程已结束"
                    : "确认流程未完成"
                  : activity.message;
          return {
            ...activity,
            // The terminal event is newer than every open lifecycle. Recording
            // that sequence prevents an old replay from restoring "进行中".
            eventSeq: Math.max(activity.eventSeq ?? activity.seq, terminalSeq),
            status: terminalStatus,
            message: completionMessage,
          };
        }),
      );
    },
    [],
  );

  const setReconciledCurrentActivity = useCallback(
    (
      key: string,
      stage: ActivityStage,
      status: ActivityStatus,
      message: string,
      detail?: string,
    ) => {
      setReconciledActivity((current) => {
        // A recovery GET can repeat while the connection settles. Deduplicate
        // by the durable confirmation/terminal key instead of UI copy, because
        // one run can legitimately stop at more than one confirmation gate.
        if (current?.key === key) return current;
        return {
          key,
          activity: activityEntry(activitySequenceRef.current, stage, status, message, { detail }),
        };
      });
    },
    [],
  );

  const appendConfirmationActivity = useCallback(
    (pendingConfirmation: Confirmation, seq: number) => {
      const detail = `待确认操作：${actionLabel(pendingConfirmation.action_type)}`;
      if (pendingConfirmation.tool_call_id) {
        // A write confirmation belongs to the tool that requested it. Keeping
        // one shared tool-call key prevents a second, competing "wait" row.
        appendActivity(
          activityEntry(
            seq,
            "tool",
            "waiting",
            `等待确认：${actionLabel(pendingConfirmation.action_type)}`,
            {
              toolCallId: pendingConfirmation.tool_call_id,
              detail,
              isWrite: true,
            },
          ),
        );
        return;
      }

      // Older persisted confirmations did not record a tool-call ID. Retain a
      // narrow fallback rather than hiding a required user decision altogether.
      appendActivity(
        activityEntry(seq, "confirmation", "waiting", "等待你的确认", {
          activityId: `confirmation:${pendingConfirmation.id}`,
          detail,
        }),
      );
    },
    [appendActivity],
  );

  const sealStreamingMessages = useCallback(() => {
    // 封面前先冲刷打字机缓冲：任何终态路径（完成/失败/断流/等待确认）
    // 都不允许丢字或留下半句残文。
    typerRef.current?.flush();
    setMessages((prev) =>
      prev.map((message) => (message.streaming ? { ...message, streaming: false } : message)),
    );
  }, []);

  const restoreAssistantMessage = useCallback((id: string, detail: RunDetail) => {
    const assistantMessage = detail.assistant_message;
    if (!assistantMessage?.content) return;
    // 恢复回填拿到的是服务端权威全文：丢弃打字机残余，防止晚到的帧
    // 把完整回复覆盖成旧的局部文本。
    typerRef.current?.dispose();
    assistantResponseObservedRef.current = true;

    setMessages((prev) => {
      const streamBubbleId = `asst-${id}`;
      const existingIndex = prev.findIndex(
        (message) => message.id === streamBubbleId || message.id === assistantMessage.id,
      );
      const restored: ChatMessage = {
        // A recovered reply belongs to the current turn even when no delta made
        // it to this tab. Keep the run-based id so ChatStream can place it after
        // the execution trace instead of interleaving it with prior history.
        id: streamBubbleId,
        runId: id,
        role: "assistant",
        content: assistantMessage.content,
        streaming: false,
      };
      if (existingIndex < 0) return [...prev, restored];
      return [...prev.slice(0, existingIndex), restored, ...prev.slice(existingIndex + 1)];
    });
  }, []);

  const reconcileRun = useCallback(
    async (id: string, source: ReconciliationSource): Promise<void> => {
      const requestId = ++reconciliationRequestRef.current;
      try {
        const detail = await api.get<RunDetail>(`/api/runs/${id}`);
        // A newer run, reconnect, or request owns the screen now; never let a
        // late response overwrite it with an older run's terminal state.
        if (runIdRef.current !== id || requestId !== reconciliationRequestRef.current) {
          return;
        }
        clearReconcileRetry();

        setPlanSteps(visiblePlanSteps(detail.plan?.steps ?? []));
        hydrateRecoveredTools(detail.tool_calls);
        setTrace(
          detail.tool_calls.map((toolCall) => ({
            id: toolCall.id,
            tool: toolCall.tool,
            status: toolCall.status,
            durationMs: toolCall.duration_ms,
            isWrite: toolCall.is_write,
            executionKind: toolCall.execution_kind ?? "tool",
            inputSummary: toolCall.input_summary ?? null,
            outputSummary: toolCall.output_summary ?? null,
          })),
        );
        restoreAssistantMessage(id, detail);

        const pendingConfirmation = detail.confirmations[0] ?? null;
        setConfirmation(pendingConfirmation);

        if (detail.run.status === "waiting_confirmation") {
          // Waiting for explicit write confirmation is a paused, non-terminal
          // run. Keep the stream alive so another tab or this tab can resume it.
          setStatus("awaiting_confirmation");
          setSummary(null);
          setError(null);
          setStreamRecovery(null);
          sealStreamingMessages();
          if (pendingConfirmation) {
            appendConfirmationActivity(pendingConfirmation, activitySequenceRef.current);
          } else {
            setReconciledCurrentActivity(
              "confirmation:pending",
              "confirmation",
              "waiting",
              "等待你的确认",
            );
          }
          return;
        }

        if (detail.run.status === "running") {
          setSummary(null);
          setError(null);
          setStatus(detail.plan?.steps?.length ? "tool_running" : "planning");
          if (source === "stream_end" || source === "exhausted") {
            setStreamRecovery({
              kind: "disconnected",
              message: "实时连接已中断，任务仍在服务器运行。",
            });
          }
          return;
        }

        clearExpiryRetry();
        setConfirmation(null);
        setConfirming(false);
        setStreamRecovery(null);
        sealStreamingMessages();
        closeStream();
        if (detail.run.status === "failed") {
          settleVisibleActivities("failed", activitySequenceRef.current);
          setReconciledActivity(null);
          setStatus("failed");
          setSummary(null);
          setError(detail.run.error || "运行失败，请稍后重试");
        } else {
          if (assistantResponseObservedRef.current) {
            appendActivity(
              activityEntry(activitySequenceRef.current, "responding", "completed", "回答已生成", {
                activityId: `answer:${id}`,
              }),
            );
          }
          settleVisibleActivities("completed", activitySequenceRef.current);
          setReconciledActivity(null);
          setStatus("completed");
          setError(null);
          setSummary(detail.summary ?? null);
        }
      } catch {
        if (
          runIdRef.current !== id ||
          requestId !== reconciliationRequestRef.current ||
          source === "manual"
        ) {
          return;
        }
        const attempt = reconciliationAttemptRef.current + 1;
        if (attempt <= 3) {
          reconciliationAttemptRef.current = attempt;
          setStreamRecovery({
            kind: "reconnecting",
            retryAttempt: attempt,
            retryInMs: 500,
          });
          reconciliationRetryTimerRef.current = window.setTimeout(() => {
            reconciliationRetryTimerRef.current = null;
            void reconcileRun(id, source);
          }, 500);
          return;
        }
        reconciliationAttemptRef.current = 0;
        // A state lookup failure is transport uncertainty, not evidence that
        // the server-side Agent run failed.
        setStreamRecovery({
          kind: "disconnected",
          message: "实时连接已中断，暂时无法确认任务状态。",
        });
      }
    },
    [
      clearExpiryRetry,
      clearReconcileRetry,
      closeStream,
      appendActivity,
      appendConfirmationActivity,
      hydrateRecoveredTools,
      setReconciledCurrentActivity,
      restoreAssistantMessage,
      sealStreamingMessages,
      settleVisibleActivities,
    ],
  );

  const attachStream = useCallback(
    (id: string, afterSeq?: number) => {
      closeStream();
      clearReconcileRetry();
      streamRef.current = attachRunStream(
        id,
        {
          // The start frame only proves that transport is live. It is not a
          // learner-visible model action, but its sequence still matters for recovery.
          onRunStarted: (seq) => advanceActivitySequence(seq),
          onProgress: (progress, seq) => {
            advanceActivitySequence(seq);
            // `understanding` is model interpretation and remains hidden. The
            // remaining stages are bounded, observable lifecycle summaries.
            if (progress.phase !== "planning" && progress.phase !== "synthesis") return;
            const stage: ActivityStage = progress.phase === "synthesis" ? "responding" : "planning";
            const activityId = progress.activity_id ?? `${progress.phase}:${id}`;
            appendActivity(
              activityEntry(
                seq,
                stage,
                activityStatusForProgress(progress.status),
                progress.title,
                {
                  activityId,
                  detail: progress.detail,
                },
              ),
            );
          },
          onPlan: (steps, seq) => {
            advanceActivitySequence(seq);
            setPlanSteps(visiblePlanSteps(steps));
          },
          onDelta: (delta, seq) => {
            advanceActivitySequence(seq);
            // Older servers can stream text without a synthesis frame. The
            // first real delta still proves that answer generation is underway.
            appendActivity(
              activityEntry(seq, "responding", "running", "正在生成回答", {
                activityId: `answer:${id}`,
              }),
            );
            appendDelta(delta);
          },
          onConnected: () => {
            streamActiveRef.current = true;
            setStreamRecovery(null);
          },
          onToolRequested: (entry, seq) => {
            setStatus("tool_running");
            setTrace((prev) => [...prev.filter((t) => t.id !== entry.id), entry]);
            appendActivity(
              activityEntry(seq, "tool", "running", toolActivityMessage(entry.tool, "running"), {
                tool: entry.tool,
                toolCallId: entry.id,
                executionKind: entry.executionKind,
                inputSummary: entry.inputSummary ?? undefined,
                isWrite: entry.isWrite,
              }),
            );
          },
          onToolCompleted: (update, seq) => {
            setTrace((prev) =>
              prev.map((t) =>
                t.id === update.toolCallId
                  ? {
                      ...t,
                      status: update.status,
                      executionKind: update.executionKind,
                      durationMs: update.durationMs,
                      isWrite: update.isWrite,
                      inputSummary: update.inputSummary,
                      outputSummary: update.outputSummary,
                    }
                  : t,
              ),
            );
            // 只对成功且有结果体的调用生成嵌入卡；失败调用留在轨迹里呈现
            if (update.status === "completed" && update.result != null) {
              setCards((prev) => [
                ...prev,
                { id: update.toolCallId, tool: update.tool, result: safeToolResult(update.result) },
              ]);
            }
            appendActivity(
              activityEntry(
                seq,
                "tool",
                activityStatusForToolCall(update.status),
                toolActivityMessage(update.tool, update.status),
                {
                  tool: update.tool,
                  toolCallId: update.toolCallId,
                  executionKind: update.executionKind,
                  inputSummary: update.inputSummary ?? undefined,
                  outputSummary: update.outputSummary ?? undefined,
                  isWrite: update.isWrite,
                  durationMs: update.durationMs,
                },
              ),
            );
          },
          // Retrieval events carry only a typed count and latency, rather than
          // arbitrary progress copy or retrieved document text.
          onRetrievalStarted: (seq) =>
            appendActivity(
              activityEntry(seq, "retrieval", "running", "正在检索相关资料", {
                activityId: `retrieval:${id}`,
              }),
            ),
          onRetrievalCompleted: (result, seq) =>
            appendActivity(
              activityEntry(seq, "retrieval", "completed", "资料检索完成", {
                activityId: `retrieval:${id}`,
                detail: `命中 ${result.hitCount} 条资料，耗时 ${result.latencyMs} ms`,
              }),
            ),
          onConfirmation: (c, seq) => {
            clearExpiryRetry();
            setConfirmation(c);
            setStatus("awaiting_confirmation");
            appendConfirmationActivity(c, seq);
          },
          onCitations: (incoming) => {
            // 按文档+章节去重：多轮问答可能重复引用同一出处
            setCitations((prev) => {
              const seen = new Set(prev.map((c) => `${c.document_id}|${c.section_title ?? ""}`));
              const merged = [...prev];
              for (const c of incoming) {
                const key = `${c.document_id}|${c.section_title ?? ""}`;
                if (!seen.has(key)) {
                  seen.add(key);
                  merged.push(c);
                }
              }
              return merged;
            });
          },
          onCompleted: (text, seq) => {
            // A different tab can confirm, cancel, or expire this write.  The
            // terminal event is authoritative, so remove any stale local gate.
            clearExpiryRetry();
            setConfirmation(null);
            setConfirming(false);
            setStreamRecovery(null);
            sealStreamingMessages();
            setStatus("completed");
            setSummary(text);
            if (assistantResponseObservedRef.current) {
              appendActivity(
                activityEntry(seq, "responding", "completed", "回答已生成", {
                  activityId: `answer:${id}`,
                }),
              );
            }
            settleVisibleActivities("completed", seq);
            setReconciledActivity(null);
          },
          onFailed: (message, seq) => {
            // A failed apply resolves the server confirmation too.  Clear the
            // local gate before rendering the error so it cannot be retried into
            // a stale 409 response.
            clearExpiryRetry();
            setConfirmation(null);
            setConfirming(false);
            setStreamRecovery(null);
            sealStreamingMessages();
            setStatus("failed");
            setError(message);
            settleVisibleActivities("failed", seq);
            setReconciledActivity(null);
          },
          onInterrupted: ({ retryAttempt, retryInMs }) => {
            if (retryAttempt !== null && retryInMs !== null) {
              setStreamRecovery({ kind: "reconnecting", retryAttempt, retryInMs });
            }
            clearReconcileRetry();
            void reconcileRun(id, "interrupted");
          },
          onExhausted: () => {
            streamActiveRef.current = false;
            setStreamRecovery({
              kind: "disconnected",
              message: "实时连接已中断，正在从服务器确认任务状态。",
            });
            clearReconcileRetry();
            void reconcileRun(id, "exhausted");
          },
          onEnd: () => {
            streamActiveRef.current = false;
            sealStreamingMessages();
            clearReconcileRetry();
            void reconcileRun(id, "stream_end");
          },
        },
        { afterSeq },
      );
      streamActiveRef.current = true;
    },
    [
      appendDelta,
      appendActivity,
      appendConfirmationActivity,
      advanceActivitySequence,
      clearExpiryRetry,
      clearReconcileRetry,
      closeStream,
      reconcileRun,
      sealStreamingMessages,
      settleVisibleActivities,
    ],
  );

  /** 清空 run 级状态（新 run / 切换会话共用） */
  const clearRunState = useCallback(() => {
    reconciliationRequestRef.current += 1;
    clearExpiryRetry();
    // 打字机随 run 生命周期归零：已渲染计数与缓冲都属于上一轮
    typerRef.current?.dispose();
    activitySequenceRef.current = 0;
    assistantResponseObservedRef.current = false;
    setPlanSteps([]);
    setTrace([]);
    setActivities([]);
    setHistoricalActivitiesByRun({});
    setReconciledActivity(null);
    setCards([]);
    setCitations([]);
    setConfirmation(null);
    setSummary(null);
    setError(null);
    setStreamRecovery(null);
    clearReconcileRetry();
  }, [clearExpiryRetry, clearReconcileRetry]);

  const start = useCallback(
    async (input: string, options: StartRunOptions = {}): Promise<boolean> => {
      const text = input.trim();
      if (!text) return false;
      const pendingConfirmation = confirmationRef.current;
      if (
        pendingConfirmation?.action_type === "task.create" &&
        isTaskSyncConfirmationCommand(text)
      ) {
        // Treat an explicit natural-language sync request as confirmation of
        // the already reviewed task card. This preserves the server's existing
        // preview/ownership/expiry checks instead of asking the model to act.
        setMessages((prev) => [...prev, { id: nextId("user"), role: "user", content: text }]);
        await confirmRef.current();
        return true;
      }
      if (startInFlightRef.current) return false;
      startInFlightRef.current = true;
      closeStream();
      clearRunState();
      // Drop the previous id before POST resolves so its late reconciliation
      // cannot overwrite this new conversation turn.
      runIdRef.current = null;
      setRunId(null);
      lastInputRef.current = { input: text, options };
      const localUserMessageId = nextId("user");
      setMessages((prev) => [
        ...prev,
        {
          id: localUserMessageId,
          role: "user",
          content: text,
          attachments: options.messageAttachments?.map((attachment) => ({ ...attachment })),
        },
      ]);
      setStatus("planning");
      try {
        const res = await api.post<CreateRunResponse>("/api/runs", {
          input: text,
          data_type: options.dataType ?? null,
          conversation_id: conversationIdRef.current,
          attachment: options.attachment ?? null,
          attachments: options.attachments ?? null,
        });
        setRunId(res.run_id);
        runIdRef.current = res.run_id;
        setConversationId(res.conversation_id);
        const persistedUserMessage = res.user_message;
        const persistedAttachments = projectMessageAttachments(persistedUserMessage?.attachments);
        setMessages((prev) =>
          prev.map((message) =>
            message.id === localUserMessageId
              ? {
                  ...message,
                  id: persistedUserMessage?.id ?? message.id,
                  runId: res.run_id,
                  content: persistedUserMessage?.content ?? message.content,
                  attachments: mergePersistedMessageAttachments(
                    message.attachments,
                    persistedAttachments,
                  ),
                }
              : message,
          ),
        );
        // POST success means the server created this run, so a local pending
        // row gives immediate feedback until its durable progress frame arrives.
        appendActivity(
          activityEntry(0, "planning", "running", "正在准备处理", {
            activityId: `planning:${res.run_id}`,
          }),
        );
        // The Composer owns temporary media state. Notify it only after this
        // response proves the server persisted the user turn and its attachments.
        options.onAccepted?.();
        attachStream(res.run_id);
        return true;
      } catch (err) {
        // A rejected create request never produced a durable turn. Remove its
        // optimistic row so retrying does not create a ghost duplicate that
        // disappears after the next history reload.
        setMessages((prev) => prev.filter((message) => message.id !== localUserMessageId));
        startInFlightRef.current = false;
        setStatus("failed");
        setError(err instanceof ApiRequestError ? err.message : "网络异常，请稍后重试");
        return false;
      }
    },
    [appendActivity, attachStream, clearRunState, closeStream],
  );

  /** 失败重试：按最近一次输入原样重发 */
  const retry = useCallback(() => {
    const last = lastInputRef.current;
    if (!last) return;
    if (runIdRef.current && last.options.attachments?.length) {
      // Media tokens are intentionally one-shot and the completed run may have
      // already discarded them. A retry must not fake success with a text-only
      // request or send an expired token; the learner can explicitly re-upload.
      toast.error("原附件已随上一轮处理，如需重新分析请重新上传文件。");
      return;
    }
    void start(last.input, last.options);
  }, [start, toast]);

  /** 410 后刷新 run：计划/轨迹/确认单与后端对齐（确认门过期需重新生成预览） */
  const refreshRun = useCallback(async () => {
    const id = runIdRef.current;
    if (!id) return;
    await reconcileRun(id, "manual");
  }, [reconcileRun]);

  const reconnect = useCallback(() => {
    const id = runIdRef.current;
    if (!id) return;
    // Preserve the persisted sequence when the user retries after all automatic
    // attempts were consumed, so previous deltas are not appended twice.
    const afterSeq = streamRef.current?.lastSeq ?? 0;
    setStreamRecovery({ kind: "reconnecting", retryAttempt: 0, retryInMs: 0 });
    attachStream(id, afterSeq);
    void reconcileRun(id, "manual");
  }, [attachStream, reconcileRun]);

  const confirm = useCallback(async () => {
    if (!confirmation || confirmationActionRef.current === confirmation.id) return;
    const confirmationId = confirmation.id;
    confirmationActionRef.current = confirmationId;
    setConfirming(true);
    try {
      await api.post(`/api/confirmations/${confirmationId}/confirm`, {});
      // 确认后编排器续跑计划，状态回到工具执行，等待 SSE 后续事件
      clearExpiryRetry();
      setConfirmation(null);
      setStatus("tool_running");
      // A recovered confirmation may have exhausted its original EventSource.
      // Reopen only that inactive transport from its durable cursor. A healthy
      // confirmation stream must remain attached while the backend resumes the
      // same run; closing it here creates a gap exactly when final events arrive.
      const id = runIdRef.current;
      if (id && !streamActiveRef.current) {
        const afterSeq = streamRef.current?.lastSeq ?? 0;
        attachStream(id, afterSeq);
      }
    } catch (err) {
      if (err instanceof ApiRequestError && err.status === 410) {
        // PRD-06 §6.4：过期后必须重新生成预览，防止基于旧状态写入
        clearExpiryRetry();
        setConfirmation(null);
        toast.error("预览已过期，请重新生成");
        await refreshRun();
      } else {
        toast.error(err instanceof ApiRequestError ? err.message : "操作失败，请稍后重试");
      }
    } finally {
      if (confirmationActionRef.current === confirmationId) {
        confirmationActionRef.current = null;
      }
      setConfirming(false);
    }
  }, [attachStream, clearExpiryRetry, confirmation, refreshRun, toast]);
  confirmRef.current = confirm;

  const cancel = useCallback(async () => {
    if (!confirmation || confirmationActionRef.current === confirmation.id) return;
    const confirmationId = confirmation.id;
    confirmationActionRef.current = confirmationId;
    setConfirming(true);
    try {
      await api.post(`/api/confirmations/${confirmationId}/cancel`, {});
      clearExpiryRetry();
      setConfirmation(null);
      // 取消即整轮完成、不落任何写（PRD 边界）；系统气泡如实告知
      setMessages((prev) => [
        ...prev,
        { id: nextId("sys"), role: "system", content: "已取消，未做任何更改" },
      ]);
      setStatus("completed");
      // A successful cancellation is terminal even when this tab misses the
      // later SSE frame. Close the visible confirmation instead of leaving it
      // labelled "等待确认" until a reconnect happens.
      settleVisibleActivities("completed", activitySequenceRef.current);
      setReconciledActivity(null);
    } catch (err) {
      if (err instanceof ApiRequestError && err.status === 410) {
        clearExpiryRetry();
        setConfirmation(null);
        toast.error("预览已过期，请重新生成");
        await refreshRun();
      } else {
        toast.error(err instanceof ApiRequestError ? err.message : "操作失败，请稍后重试");
      }
    } finally {
      if (confirmationActionRef.current === confirmationId) {
        confirmationActionRef.current = null;
      }
      setConfirming(false);
    }
  }, [clearExpiryRetry, confirmation, refreshRun, settleVisibleActivities, toast]);

  /**
   * Resolve one expired confirmation without executing its write operation.
   *
   * The backend closes the tool, plan and run atomically.  Updating local state
   * from the response keeps this tab usable even if its SSE connection ended;
   * ``onCompleted`` above performs the same cleanup for another tab's request.
   */
  const expire = useCallback(
    async (target: Confirmation | null = confirmation, signal?: AbortSignal) => {
      if (!target || signal?.aborted || expiryRequestRef.current === target.id) return;
      expiryRequestRef.current = target.id;
      try {
        const response = await api.post<{ status: string; summary?: string }>(
          `/api/confirmations/${target.id}/expire`,
          {},
          { signal },
        );
        if (signal?.aborted) {
          expiryRequestRef.current = null;
          return;
        }
        const expiredSummary = response.summary ?? "预览已过期，未做任何修改，请重新发起操作。";
        clearExpiryRetry();
        setConfirmation((current) => (current?.id === target.id ? null : current));
        setStatus("completed");
        setSummary(expiredSummary);
        // Expiry has the same terminal guarantee as cancellation. Use the last
        // durable sequence until the server's terminal event replaces this view.
        settleVisibleActivities("completed", activitySequenceRef.current);
        setReconciledActivity(null);
      } catch (err) {
        if (signal?.aborted) {
          expiryRequestRef.current = null;
          return;
        }
        // A browser clock can reach zero just before the server does.  Retry only
        // that safe 409; a competing tab still relies on its terminal SSE event.
        if (err instanceof ApiRequestError && err.code === "CONFIRMATION_NOT_EXPIRED") {
          expiryRequestRef.current = null;
          scheduleExpiryRetry(target, signal);
          return;
        }
        if (!(err instanceof ApiRequestError) || err.status !== 409) {
          toast.error(err instanceof ApiRequestError ? err.message : "操作失败，请稍后重试");
        }
        expiryRequestRef.current = null;
      }
    },
    [clearExpiryRetry, confirmation, scheduleExpiryRetry, settleVisibleActivities, toast],
  );
  expireRef.current = expire;

  useEffect(() => {
    if (!confirmation || confirming) return;
    const controller = new AbortController();
    const expiresAt = new Date(confirmation.expires_at).getTime();
    if (Number.isNaN(expiresAt)) return;
    // Add a small buffer so a browser timer cannot arrive before the server's
    // ISO deadline and receive CONFIRMATION_NOT_EXPIRED.
    const delay = Math.max(0, expiresAt - Date.now()) + 10;
    const timer = window.setTimeout(() => {
      void expire(confirmation, controller.signal);
    }, delay);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [confirmation, confirming, expire]);

  /** 新会话：回到空白态（欢迎态），关闭旧流 */
  const reset = useCallback(() => {
    if (startInFlightRef.current) return;
    closeStream();
    clearRunState();
    setMessages([]);
    setStatus("idle");
    setRunId(null);
    runIdRef.current = null;
    setConversationId(null);
  }, [clearRunState, closeStream]);

  /** 载入历史会话：tool 消息按契约隐藏（PRD 要求隐藏或折叠） */
  const loadConversation = useCallback(
    (detail: ConversationDetail) => {
      if (startInFlightRef.current) return;
      closeStream();
      clearRunState();
      setStatus("idle");
      setRunId(null);
      runIdRef.current = null;
      setConversationId(detail.id);
      setHistoricalActivitiesByRun(historicalActivityMap(detail.activities_by_run));
      setMessages(
        detail.messages
          .filter((m) => m.role !== "tool")
          .map((m) => ({
            id: m.id,
            runId: m.run_id,
            role:
              m.role === "user"
                ? ("user" as const)
                : m.role === "system"
                  ? ("system" as const)
                  : ("assistant" as const),
            content: m.content,
            attachments: projectMessageAttachments(m.attachments),
          })),
      );
    },
    [clearRunState, closeStream],
  );

  return {
    status,
    runId,
    conversationId,
    messages,
    planSteps,
    trace,
    activities,
    historicalActivitiesByRun,
    reconciledActivity: reconciledActivity?.activity ?? null,
    cards,
    citations,
    confirmation,
    confirming,
    summary,
    error,
    streamRecovery,
    start,
    retry,
    reconnect,
    refreshRun,
    confirm,
    cancel,
    expire,
    reset,
    loadConversation,
  };
}

export type CockpitRun = ReturnType<typeof useCockpitRun>;
