/**
 * Controlled SSE subscription for one Agent run.
 *
 * EventSource retries forever by default, which can leave a run visually stuck
 * after a proxy or auth failure.  This wrapper owns reconnection so callers can
 * reconcile against the authoritative run resource once the finite budget ends.
 */
import type { AgentEventPayloads, AgentEventType } from "./types";

const KNOWN_EVENTS: AgentEventType[] = [
  "run.started",
  "run.progress",
  "message.delta",
  "plan.updated",
  "tool.call.requested",
  "tool.call.completed",
  "rag.retrieval.started",
  "rag.retrieval.completed",
  "citation.attached",
  "confirmation.required",
  "task.draft",
  "run.completed",
  "run.failed",
  "run.usage",
];

const STREAM_END = "stream.end";

/** Three bounded reconnects keep a transient proxy reset recoverable without an endless spinner. */
export const RUN_STREAM_RETRY_DELAYS_MS = [500, 1_000, 2_000] as const;
/** A connection that never opens must be treated like a broken stream, not a permanent planning state. */
export const RUN_STREAM_CONNECT_TIMEOUT_MS = 8_000;

export type RunStreamDisruptionReason = "error" | "connect_timeout";

export interface RunStreamInterruption {
  reason: RunStreamDisruptionReason;
  /** The reconnect number being scheduled, starting at one. Null means the budget is exhausted. */
  retryAttempt: number | null;
  retryInMs: number | null;
  lastSeq: number;
}

export interface RunStreamExhausted {
  reason: RunStreamDisruptionReason;
  attempts: number;
  lastSeq: number;
}

export interface RunEventStreamOptions {
  /** Resume after this persisted event sequence number. */
  afterSeq?: number;
  /** Override only for tests or a future product-level retry policy. */
  reconnectDelaysMs?: readonly number[];
  /** Guard each EventSource connection attempt, including the initial one. */
  connectTimeoutMs?: number;
  onConnected?: (lastSeq: number) => void;
  onInterrupted?: (interruption: RunStreamInterruption) => void;
  onExhausted?: (exhaustion: RunStreamExhausted) => void;
}

type Handler = (payload: never, seq: number) => void;

/**
 * A replayable SSE subscription.  Every manual reconnect keeps `after_seq`
 * aligned with the last persisted event, preventing duplicate deltas.
 */
export class RunEventStream {
  private es: EventSource | null = null;
  private _lastSeq: number;
  private closed = false;
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private connectTimer: ReturnType<typeof setTimeout> | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private streamEndHandlers = new Set<() => void>();
  private readonly retryDelaysMs: readonly number[];
  private readonly connectTimeoutMs: number;

  constructor(
    private readonly runId: string,
    private readonly options: RunEventStreamOptions = {},
  ) {
    this._lastSeq = options.afterSeq ?? 0;
    this.retryDelaysMs = (options.reconnectDelaysMs ?? RUN_STREAM_RETRY_DELAYS_MS).filter(
      (delay) => Number.isFinite(delay) && delay >= 0,
    );
    this.connectTimeoutMs =
      typeof options.connectTimeoutMs === "number" &&
      Number.isFinite(options.connectTimeoutMs) &&
      options.connectTimeoutMs > 0
        ? options.connectTimeoutMs
        : RUN_STREAM_CONNECT_TIMEOUT_MS;
    this.connect();
  }

  /** Exposed so a user-triggered reconnect can continue from the same sequence. */
  get lastSeq(): number {
    return this._lastSeq;
  }

  on<K extends AgentEventType>(
    type: K,
    handler: (payload: AgentEventPayloads[K], seq: number) => void,
  ): () => void {
    let set = this.handlers.get(type);
    if (!set) {
      set = new Set();
      this.handlers.set(type, set);
    }
    const typedHandler = handler as Handler;
    set.add(typedHandler);
    return () => set?.delete(typedHandler);
  }

  onStreamEnd(handler: () => void): () => void {
    this.streamEndHandlers.add(handler);
    return () => this.streamEndHandlers.delete(handler);
  }

  /** Closing is idempotent and always clears every pending timer. */
  close(): void {
    this.closed = true;
    this.clearTimers();
    this.closeEventSource();
  }

  private connect(): void {
    if (this.closed) return;

    this.reconnectTimer = null;
    const es = new EventSource(`/api/runs/${this.runId}/events?after_seq=${this._lastSeq}`);
    this.es = es;

    const dispatch = (type: string) => (event: MessageEvent) => {
      if (this.closed || this.es !== es) return;
      let payload: { seq?: number } & Record<string, unknown>;
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      const persistedSeq =
        typeof payload.seq === "number" && Number.isFinite(payload.seq) ? payload.seq : null;
      const seq = persistedSeq ?? this._lastSeq;
      if (persistedSeq !== null) {
        // A replay can race a reconnect even with after_seq. Dropping it here
        // keeps every consumer, including the activity timeline, idempotent.
        if (persistedSeq <= this._lastSeq) return;
        this._lastSeq = Math.max(this._lastSeq, persistedSeq);
        // A persisted event proves that this connection is useful.  Only then
        // is it safe to refresh the retry budget for a later transient reset.
        this.clearConnectTimer();
        this.reconnectAttempt = 0;
      }
      for (const handler of this.handlers.get(type) ?? []) {
        (handler as (value: unknown, sequence: number) => void)(payload, seq);
      }
    };

    for (const type of KNOWN_EVENTS) {
      es.addEventListener(type, dispatch(type));
    }

    es.addEventListener(STREAM_END, () => {
      if (this.closed || this.es !== es) return;
      const handlers = [...this.streamEndHandlers];
      this.close();
      for (const handler of handlers) handler();
    });

    es.onopen = () => {
      if (this.closed || this.es !== es) return;
      this.clearConnectTimer();
      this.options.onConnected?.(this._lastSeq);
    };

    es.onerror = () => this.handleDisruption(es, "error");
    this.connectTimer = setTimeout(() => {
      // Some intermediary failures never dispatch EventSource.onerror.  The
      // timeout converts that silent failure into the same bounded recovery.
      if (!this.closed && this.es === es && es.readyState !== 1) {
        this.handleDisruption(es, "connect_timeout");
      }
    }, this.connectTimeoutMs);
  }

  private handleDisruption(es: EventSource, reason: RunStreamDisruptionReason): void {
    if (this.closed || this.es !== es) return;

    this.clearConnectTimer();
    this.es = null;
    // Explicitly close the native source before scheduling ours, otherwise its
    // opaque automatic retry can race a manual replay connection.
    es.close();

    const delay = this.retryDelaysMs[this.reconnectAttempt];
    if (delay === undefined) {
      this.closed = true;
      this.options.onInterrupted?.({
        reason,
        retryAttempt: null,
        retryInMs: null,
        lastSeq: this._lastSeq,
      });
      this.options.onExhausted?.({
        reason,
        attempts: this.reconnectAttempt,
        lastSeq: this._lastSeq,
      });
      return;
    }

    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
    this.options.onInterrupted?.({
      reason,
      retryAttempt: this.reconnectAttempt,
      retryInMs: delay,
      lastSeq: this._lastSeq,
    });
  }

  private clearTimers(): void {
    this.clearConnectTimer();
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private clearConnectTimer(): void {
    if (this.connectTimer !== null) {
      clearTimeout(this.connectTimer);
      this.connectTimer = null;
    }
  }

  private closeEventSource(): void {
    const current = this.es;
    this.es = null;
    current?.close();
  }
}
