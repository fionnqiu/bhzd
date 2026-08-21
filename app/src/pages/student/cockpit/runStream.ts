/**
 * 运行事件流绑定器：把 SSE 事件翻译成状态机回调。
 *
 * 为什么从 useCockpitRun 拆出：事件名/payload 的接线是纯转发逻辑，
 * 独立后 hook 只剩状态归约；也让"接了哪些事件"在一处可读（蓝图 §7 契约）。
 * 断点续播/自动重连由 F0 的 RunEventStream 封装（after_seq），这里不碰传输。
 */
import {
  RunEventStream,
  type RunEventStreamOptions,
  type RunStreamExhausted,
  type RunStreamInterruption,
} from "../../../api/sse";
import type { AgentRunProgress, Citation, Confirmation, PlanStep, TaskDraft } from "../../../api/types";
import type { ExecutionKind, TraceEntry } from "./types";

const SENSITIVE_SUMMARY =
  /((?:authorization|proxy-authorization|cookie|set-cookie|api[_ -]?key|access[_ -]?token|token|secret|password|session[_ -]?id|diagnostic[_ -]?token)\s*[:=：]\s*)(?:bearer\s+)?[^\s,;；}]+/gi;

function safeSummary(value: string | null | undefined): string | null {
  const normalized = value?.replace(/\s+/g, " ").trim();
  if (!normalized) return null;
  const redacted = normalized
    .replace(SENSITIVE_SUMMARY, "$1已隐藏")
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, "授权信息：已隐藏");
  return redacted.slice(0, 240);
}

function safeExecutionKind(value: unknown): ExecutionKind {
  return value === "command" || value === "file" ? value : "tool";
}

/** 事件 → 状态机的回调集（由 hook 以 setState 实现） */
export interface RunStreamCallbacks {
  onRunStarted: (seq: number) => void;
  onProgress: (progress: AgentRunProgress, seq: number) => void;
  onPlan: (steps: PlanStep[], seq: number) => void;
  onDelta: (delta: string, seq: number) => void;
  /** tool.call.requested：新建轨迹行（running） */
  onToolRequested: (entry: TraceEntry, seq: number) => void;
  /** tool.call.completed：回填轨迹行（状态/耗时/是否写操作） */
  onToolCompleted: (
    update: {
      toolCallId: string;
      tool: string;
      executionKind: ExecutionKind;
      status: string;
      durationMs: number | null;
      isWrite: boolean;
      inputSummary: string | null;
      outputSummary: string | null;
      result: unknown;
    },
    seq: number,
  ) => void;
  onRetrievalStarted: (seq: number) => void;
  onRetrievalCompleted: (result: { hitCount: number; latencyMs: number }, seq: number) => void;
  onConfirmation: (confirmation: Confirmation, seq: number) => void;
  /** task.draft：任务草稿完整投影（生成/同步各一次，后写覆盖先写） */
  onTaskDraft: (draft: TaskDraft, seq: number) => void;
  onCitations: (citations: Citation[]) => void;
  onCompleted: (summary: string | null, seq: number) => void;
  onFailed: (error: string, seq: number) => void;
  /** A successful reconnect clears the temporary transport warning in the UI. */
  onConnected?: (lastSeq: number) => void;
  /** A retry is scheduled; state reconciliation must not assume the run failed. */
  onInterrupted?: (interruption: RunStreamInterruption) => void;
  /** The retry budget is over and the caller must offer a manual reconnect. */
  onExhausted?: (exhaustion: RunStreamExhausted) => void;
  /** 服务端 stream.end：流式气泡封口 */
  onEnd: () => void;
}

/** 打开 run 的 SSE 并绑定全部已知事件；返回流（调用方负责 close） */
export function attachRunStream(
  runId: string,
  cb: RunStreamCallbacks,
  options: Pick<RunEventStreamOptions, "afterSeq"> = {},
): RunEventStream {
  const stream = new RunEventStream(runId, {
    afterSeq: options.afterSeq,
    onConnected: cb.onConnected,
    onInterrupted: cb.onInterrupted,
    onExhausted: cb.onExhausted,
  });

  stream.on("run.started", (_p, seq) => cb.onRunStarted(seq));
  stream.on("run.progress", (p, seq) => cb.onProgress(p, seq));
  stream.on("plan.updated", (p, seq) => cb.onPlan(p.steps, seq));
  stream.on("message.delta", (p, seq) => cb.onDelta(p.delta, seq));
  stream.on("tool.call.requested", (p, seq) =>
    cb.onToolRequested(
      {
        id: p.tool_call_id,
        tool: p.tool,
        executionKind: safeExecutionKind(p.execution_kind),
        status: "running",
        durationMs: null,
        isWrite: p.permission === "write",
        // Older servers only expose args_summary, whose contents are not trusted
        // for display. New servers provide the bounded input_summary contract.
        inputSummary:
          safeSummary(p.input_summary) ?? (p.args_summary?.trim() ? "具体参数已隐藏" : null),
        outputSummary: null,
      },
      seq,
    ),
  );
  stream.on("tool.call.completed", (p, seq) =>
    cb.onToolCompleted(
      {
        toolCallId: p.tool_call_id,
        tool: p.tool,
        executionKind: safeExecutionKind(p.execution_kind),
        status: p.status,
        durationMs: p.duration_ms ?? null,
        isWrite: Boolean(p.is_write),
        inputSummary: null,
        outputSummary: safeSummary(p.output_summary),
        result: p.result,
      },
      seq,
    ),
  );
  stream.on("rag.retrieval.started", (_p, seq) => cb.onRetrievalStarted(seq));
  stream.on("rag.retrieval.completed", (p, seq) =>
    cb.onRetrievalCompleted({ hitCount: p.hit_count, latencyMs: p.latency_ms }, seq),
  );
  stream.on("confirmation.required", (p, seq) => cb.onConfirmation(p.confirmation, seq));
  stream.on("task.draft", (p, seq) => cb.onTaskDraft(p.draft, seq));
  stream.on("citation.attached", (p) => cb.onCitations(p.citations));
  stream.on("run.completed", (p, seq) => {
    cb.onCompleted(p.summary ?? null, seq);
  });
  stream.on("run.failed", (p, seq) =>
    // 后端已给中文话术；绝不展示堆栈（PRD-01 §3.5）
    cb.onFailed(p.error || "运行失败，请稍后重试", seq),
  );
  stream.onStreamEnd(cb.onEnd);
  return stream;
}
