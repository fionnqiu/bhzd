/**
 * 指挥舱运行状态机 hook（PRD-01 §3.5 六态：空白/计划中/工具调用中/等待确认/已完成/失败）。
 * SSE 接线在 runStream.ts，这里只做事件 → UI 状态的归约；
 * 新 run / 卸载 / 切换会话时统一 close 旧流，防止脏事件串台。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiRequestError, api } from "../../../api/client";
import type { RunEventStream } from "../../../api/sse";
import type {
  Citation,
  Confirmation,
  ConversationDetail,
  CreateRunResponse,
  PlanStep,
  RunDetail,
} from "../../../api/types";
import { useToast } from "../../../components";
import { attachRunStream } from "./runStream";
import { nextId } from "./types";
import type {
  ChatMessage,
  CockpitStatus,
  EmbeddedCardData,
  ScenarioSuggestion,
  StartRunOptions,
  TraceEntry,
} from "./types";

// 子组件可能只依赖类型：统一从 types.ts 出口，避免反向依赖 hook 实现
export type { ChatMessage, CockpitStatus, EmbeddedCardData, ScenarioSuggestion, StartRunOptions, TraceEntry } from "./types";

export function useCockpitRun(scenarioId: string) {
  const toast = useToast();
  const [status, setStatus] = useState<CockpitStatus>("idle");
  const [runId, setRunId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [planSteps, setPlanSteps] = useState<PlanStep[]>([]);
  const [trace, setTrace] = useState<TraceEntry[]>([]);
  const [cards, setCards] = useState<EmbeddedCardData[]>([]);
  const [citations, setCitations] = useState<Citation[]>([]);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<ScenarioSuggestion | null>(null);
  const [error, setError] = useState<string | null>(null);

  const streamRef = useRef<RunEventStream | null>(null);
  const runIdRef = useRef<string | null>(null);
  // A confirmation can be visible in two tabs.  Remember the request owner so
  // this tab sends at most one expiry request while awaiting the terminal SSE.
  const expiryRequestRef = useRef<string | null>(null);
  // A server can legitimately be a little behind the browser clock.  Keep one
  // retry timer per card so CONFIRMATION_NOT_EXPIRED cannot strand a disabled UI.
  const expiryRetryTimerRef = useRef<number | null>(null);
  const confirmationRef = useRef<Confirmation | null>(null);
  const expireRef = useRef<(target: Confirmation | null) => Promise<void>>(async () => {});
  // 最近一次输入：run.failed 后"重试"按原样重发（PRD-01 §3.5 可操作下一步）
  const lastInputRef = useRef<{ input: string; options: StartRunOptions } | null>(null);
  // 场景在流存活期间可能切换；ref 保证 start 闭包拿到的是当前值
  const scenarioRef = useRef(scenarioId);
  scenarioRef.current = scenarioId;
  const conversationIdRef = useRef<string | null>(null);
  conversationIdRef.current = conversationId;
  confirmationRef.current = confirmation;

  const closeStream = useCallback(() => {
    streamRef.current?.close();
    streamRef.current = null;
  }, []);

  const clearExpiryRetry = useCallback(() => {
    if (expiryRetryTimerRef.current !== null) {
      window.clearTimeout(expiryRetryTimerRef.current);
      expiryRetryTimerRef.current = null;
    }
    expiryRequestRef.current = null;
  }, []);

  const scheduleExpiryRetry = useCallback((target: Confirmation) => {
    if (expiryRetryTimerRef.current !== null) {
      window.clearTimeout(expiryRetryTimerRef.current);
    }
    // A one-second retry bounds traffic under a large clock skew but still lets
    // a just-early browser converge without user interaction.
    expiryRetryTimerRef.current = window.setTimeout(() => {
      expiryRetryTimerRef.current = null;
      if (confirmationRef.current?.id === target.id) {
        void expireRef.current(target);
      }
    }, 1_000);
  }, []);

  // 卸载时关闭 SSE（契约：主动 close 幂等，不再重连）
  useEffect(
    () => () => {
      closeStream();
      clearExpiryRetry();
    },
    [clearExpiryRetry, closeStream],
  );

  const appendDelta = useCallback((delta: string) => {
    const bubbleId = `asst-${runIdRef.current ?? "draft"}`;
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.id === bubbleId) {
        return [...prev.slice(0, -1), { ...last, content: last.content + delta }];
      }
      return [
        ...prev,
        { id: bubbleId, role: "assistant" as const, content: delta, streaming: true },
      ];
    });
  }, []);

  const attachStream = useCallback(
    (id: string) => {
      closeStream();
      streamRef.current = attachRunStream(id, {
        onPlan: setPlanSteps,
        onDelta: appendDelta,
        onToolRequested: (entry) => {
          setStatus("tool_running");
          setTrace((prev) => [...prev.filter((t) => t.id !== entry.id), entry]);
        },
        onToolCompleted: (update) => {
          setTrace((prev) =>
            prev.map((t) =>
              t.id === update.toolCallId
                ? {
                    ...t,
                    status: update.status,
                    durationMs: update.durationMs,
                    isWrite: update.isWrite,
                  }
                : t,
            ),
          );
          // 只对成功且有结果体的调用生成嵌入卡；失败调用留在轨迹里呈现
          if (update.status === "completed" && update.result != null) {
            setCards((prev) => [
              ...prev,
              { id: update.toolCallId, tool: update.tool, result: update.result },
            ]);
          }
        },
        onConfirmation: (c) => {
          clearExpiryRetry();
          setConfirmation(c);
          setStatus("awaiting_confirmation");
        },
        onCitations: (incoming) => {
          // 按文档+章节去重：多轮问答可能重复引用同一出处
          setCitations((prev) => {
            const seen = new Set(
              prev.map((c) => `${c.document_id}|${c.section_title ?? ""}`),
            );
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
        onCompleted: (text, hint) => {
          // A different tab can confirm, cancel, or expire this write.  The
          // terminal event is authoritative, so remove any stale local gate.
          clearExpiryRetry();
          setConfirmation(null);
          setConfirming(false);
          setStatus("completed");
          setSummary(text);
          if (hint) setSuggestion(hint);
        },
        onFailed: (message) => {
          // A failed apply resolves the server confirmation too.  Clear the
          // local gate before rendering the error so it cannot be retried into
          // a stale 409 response.
          clearExpiryRetry();
          setConfirmation(null);
          setConfirming(false);
          setStatus("failed");
          setError(message);
        },
        onEnd: () => {
          setMessages((prev) =>
            prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)),
          );
        },
      });
    },
    [appendDelta, clearExpiryRetry, closeStream],
  );

  /** 清空 run 级状态（新 run / 切换会话共用） */
  const clearRunState = useCallback(() => {
    clearExpiryRetry();
    setPlanSteps([]);
    setTrace([]);
    setCards([]);
    setCitations([]);
    setConfirmation(null);
    setSummary(null);
    setSuggestion(null);
    setError(null);
  }, [clearExpiryRetry]);

  const start = useCallback(
    async (input: string, options: StartRunOptions = {}) => {
      const text = input.trim();
      if (!text) return;
      closeStream();
      clearRunState();
      lastInputRef.current = { input: text, options };
      setMessages((prev) => [
        ...prev,
        { id: nextId("user"), role: "user", content: text },
      ]);
      setStatus("planning");
      try {
        const res = await api.post<CreateRunResponse>("/api/runs", {
          input: text,
          scenario_id: scenarioRef.current || null,
          data_type: options.dataType ?? null,
          conversation_id: conversationIdRef.current,
          attachment: options.attachment ?? null,
        });
        setRunId(res.run_id);
        runIdRef.current = res.run_id;
        setConversationId(res.conversation_id);
        attachStream(res.run_id);
      } catch (err) {
        setStatus("failed");
        setError(
          err instanceof ApiRequestError ? err.message : "网络异常，请稍后重试",
        );
      }
    },
    [attachStream, clearRunState, closeStream],
  );

  /** 失败重试：按最近一次输入原样重发 */
  const retry = useCallback(() => {
    const last = lastInputRef.current;
    if (last) void start(last.input, last.options);
  }, [start]);

  /** 410 后刷新 run：计划/轨迹/确认单与后端对齐（确认门过期需重新生成预览） */
  const refreshRun = useCallback(async () => {
    const id = runIdRef.current;
    if (!id) return;
    try {
      const detail = await api.get<RunDetail>(`/api/runs/${id}`);
      setPlanSteps(detail.plan?.steps ?? []);
      setTrace(
        detail.tool_calls.map((t) => ({
          id: t.id,
          tool: t.tool,
          status: t.status,
          durationMs: t.duration_ms,
          isWrite: t.is_write,
        })),
      );
      const pending = detail.confirmations[0] ?? null;
      setConfirmation(pending);
      if (detail.run.status === "waiting_confirmation") {
        setStatus("awaiting_confirmation");
      } else if (detail.run.status === "running") {
        setStatus("tool_running");
      } else if (detail.run.status === "failed") {
        clearExpiryRetry();
        setConfirmation(null);
        setConfirming(false);
        setStatus("failed");
        setError(detail.run.error || "运行失败，请稍后重试");
      } else {
        clearExpiryRetry();
        setConfirmation(null);
        setConfirming(false);
        setStatus("completed");
      }
    } catch {
      // 刷新失败不致命：流仍在，后续事件会推进状态
    }
  }, [clearExpiryRetry]);

  const confirm = useCallback(async () => {
    if (!confirmation) return;
    setConfirming(true);
    try {
      await api.post(`/api/confirmations/${confirmation.id}/confirm`, {});
      // 确认后编排器续跑计划，状态回到工具执行，等待 SSE 后续事件
      clearExpiryRetry();
      setConfirmation(null);
      setStatus("tool_running");
    } catch (err) {
      if (err instanceof ApiRequestError && err.status === 410) {
        // PRD-06 §6.4：过期后必须重新生成预览，防止基于旧状态写入
        toast.error("预览已过期，请重新生成");
        clearExpiryRetry();
        setConfirmation(null);
        await refreshRun();
      } else {
        toast.error(
          err instanceof ApiRequestError ? err.message : "操作失败，请稍后重试",
        );
      }
    } finally {
      setConfirming(false);
    }
  }, [clearExpiryRetry, confirmation, refreshRun, toast]);

  const cancel = useCallback(async () => {
    if (!confirmation) return;
    setConfirming(true);
    try {
      await api.post(`/api/confirmations/${confirmation.id}/cancel`, {});
      clearExpiryRetry();
      setConfirmation(null);
      // 取消即整轮完成、不落任何写（PRD 边界）；系统气泡如实告知
      setMessages((prev) => [
        ...prev,
        { id: nextId("sys"), role: "system", content: "已取消，未做任何更改" },
      ]);
      setStatus("completed");
    } catch (err) {
      if (err instanceof ApiRequestError && err.status === 410) {
        toast.error("预览已过期，请重新生成");
        clearExpiryRetry();
        setConfirmation(null);
        await refreshRun();
      } else {
        toast.error(
          err instanceof ApiRequestError ? err.message : "操作失败，请稍后重试",
        );
      }
    } finally {
      setConfirming(false);
    }
  }, [clearExpiryRetry, confirmation, refreshRun, toast]);

  /**
   * Resolve one expired confirmation without executing its write operation.
   *
   * The backend closes the tool, plan and run atomically.  Updating local state
   * from the response keeps this tab usable even if its SSE connection ended;
   * ``onCompleted`` above performs the same cleanup for another tab's request.
   */
  const expire = useCallback(async (target: Confirmation | null = confirmation) => {
    if (!target || expiryRequestRef.current === target.id) return;
    expiryRequestRef.current = target.id;
    try {
      const response = await api.post<{ status: string; summary?: string }>(
        `/api/confirmations/${target.id}/expire`,
        {},
      );
      const expiredSummary = response.summary ?? "预览已过期，未做任何修改，请重新发起操作。";
      clearExpiryRetry();
      setConfirmation((current) => (current?.id === target.id ? null : current));
      setStatus("completed");
      setSummary(expiredSummary);
    } catch (err) {
      // A browser clock can reach zero just before the server does.  Retry only
      // that safe 409; a competing tab still relies on its terminal SSE event.
      if (err instanceof ApiRequestError && err.code === "CONFIRMATION_NOT_EXPIRED") {
        expiryRequestRef.current = null;
        scheduleExpiryRetry(target);
        return;
      }
      if (!(err instanceof ApiRequestError) || err.status !== 409) {
        toast.error(
          err instanceof ApiRequestError ? err.message : "操作失败，请稍后重试",
        );
      }
      expiryRequestRef.current = null;
    }
  }, [clearExpiryRetry, confirmation, scheduleExpiryRetry, toast]);
  expireRef.current = expire;

  useEffect(() => {
    if (!confirmation || confirming) return;
    const expiresAt = new Date(confirmation.expires_at).getTime();
    if (Number.isNaN(expiresAt)) return;
    // Add a small buffer so a browser timer cannot arrive before the server's
    // ISO deadline and receive CONFIRMATION_NOT_EXPIRED.
    const delay = Math.max(0, expiresAt - Date.now()) + 10;
    const timer = window.setTimeout(() => {
      void expire(confirmation);
    }, delay);
    return () => window.clearTimeout(timer);
  }, [confirmation, confirming, expire]);

  /** 新会话：回到空白态（欢迎态），关闭旧流 */
  const reset = useCallback(() => {
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
      closeStream();
      clearRunState();
      setStatus("idle");
      setRunId(null);
      runIdRef.current = null;
      setConversationId(detail.id);
      setMessages(
        detail.messages
          .filter((m) => m.role !== "tool")
          .map((m) => ({
            id: m.id,
            role: m.role === "user" ? ("user" as const) : m.role === "system" ? ("system" as const) : ("assistant" as const),
            content: m.content,
          })),
      );
    },
    [clearRunState, closeStream],
  );

  const dismissSuggestion = useCallback(() => setSuggestion(null), []);

  return {
    status,
    runId,
    conversationId,
    messages,
    planSteps,
    trace,
    cards,
    citations,
    confirmation,
    confirming,
    summary,
    suggestion,
    error,
    start,
    retry,
    confirm,
    cancel,
    expire,
    reset,
    loadConversation,
    dismissSuggestion,
  };
}

export type CockpitRun = ReturnType<typeof useCockpitRun>;
