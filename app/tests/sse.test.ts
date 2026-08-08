import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RunEventStream, RUN_STREAM_RETRY_DELAYS_MS } from "../src/api/sse";

type Listener = (event: Event) => void;

/** A controllable EventSource lets retry tests prove URL replay without network I/O. */
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  readyState = 0;
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  close = vi.fn(() => {
    this.readyState = 2;
  });
  private listeners = new Map<string, Set<Listener>>();

  constructor(public readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener): void {
    const handlers = this.listeners.get(type) ?? new Set<Listener>();
    handlers.add(listener);
    this.listeners.set(type, handlers);
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }

  emit(type: string, payload: Record<string, unknown> = {}): void {
    const event = new MessageEvent(type, { data: JSON.stringify(payload) });
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }

  fail(): void {
    this.readyState = 2;
    this.onerror?.(new Event("error"));
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("RunEventStream", () => {
  it("uses three bounded retries and resumes with the last received sequence", () => {
    const interruptions: Array<{ attempt: number | null; delay: number | null; seq: number }> = [];
    const exhausted = vi.fn();
    const stream = new RunEventStream("run-1", {
      onInterrupted: (event) =>
        interruptions.push({
          attempt: event.retryAttempt,
          delay: event.retryInMs,
          seq: event.lastSeq,
        }),
      onExhausted: exhausted,
    });
    const received = vi.fn();
    stream.on("message.delta", received);

    FakeEventSource.instances[0].emit("message.delta", { seq: 9, delta: "hello" });
    expect(received).toHaveBeenCalledWith({ seq: 9, delta: "hello" }, 9);

    for (const delay of RUN_STREAM_RETRY_DELAYS_MS) {
      FakeEventSource.instances.at(-1)!.fail();
      vi.advanceTimersByTime(delay);
      expect(FakeEventSource.instances.at(-1)!.url).toContain("after_seq=9");
    }
    FakeEventSource.instances.at(-1)!.fail();

    expect(FakeEventSource.instances).toHaveLength(4);
    expect(interruptions).toEqual([
      { attempt: 1, delay: 500, seq: 9 },
      { attempt: 2, delay: 1_000, seq: 9 },
      { attempt: 3, delay: 2_000, seq: 9 },
      { attempt: null, delay: null, seq: 9 },
    ]);
    expect(exhausted).toHaveBeenCalledWith({ reason: "error", attempts: 3, lastSeq: 9 });
  });

  it("refreshes the retry budget only after a persisted event, not a bare open", () => {
    const stream = new RunEventStream("run-budget");

    FakeEventSource.instances[0].fail();
    vi.advanceTimersByTime(500);
    FakeEventSource.instances[1].open();
    FakeEventSource.instances[1].fail();
    // The second failure still consumes the 1s tier because opening alone did
    // not prove that the browser received a persisted server event.
    vi.advanceTimersByTime(500);
    expect(FakeEventSource.instances).toHaveLength(2);
    vi.advanceTimersByTime(500);
    expect(FakeEventSource.instances).toHaveLength(3);

    FakeEventSource.instances[2].emit("run.started", { seq: 1 });
    FakeEventSource.instances[2].fail();
    vi.advanceTimersByTime(500);
    expect(FakeEventSource.instances).toHaveLength(4);
    stream.close();
  });

  it("delivers a persisted progress event once when a replay repeats its sequence", () => {
    const stream = new RunEventStream("run-progress");
    const received = vi.fn();
    stream.on("run.progress", received);

    FakeEventSource.instances[0].emit("run.progress", {
      seq: 3,
      phase: "planning",
      status: "running",
      title: "正在制定计划",
    });
    FakeEventSource.instances[0].emit("run.progress", {
      seq: 3,
      phase: "planning",
      status: "running",
      title: "这条重放不应重复显示",
    });

    expect(received).toHaveBeenCalledTimes(1);
    expect(received).toHaveBeenCalledWith(
      expect.objectContaining({ seq: 3, title: "正在制定计划" }),
      3,
    );
    expect(stream.lastSeq).toBe(3);
    stream.close();
  });

  it("converts an initial connection timeout into an exhausted stream", () => {
    const exhausted = vi.fn();
    const stream = new RunEventStream("run-2", {
      connectTimeoutMs: 100,
      reconnectDelaysMs: [],
      onExhausted: exhausted,
    });

    vi.advanceTimersByTime(100);

    expect(FakeEventSource.instances[0].close).toHaveBeenCalledOnce();
    expect(exhausted).toHaveBeenCalledWith({
      reason: "connect_timeout",
      attempts: 0,
      lastSeq: 0,
    });
    stream.close();
  });

  it("stops every timer when the server ends the stream or the caller closes it", () => {
    const ended = vi.fn();
    const endedStream = new RunEventStream("run-3", { connectTimeoutMs: 100 });
    endedStream.onStreamEnd(ended);
    FakeEventSource.instances[0].emit("stream.end");

    expect(ended).toHaveBeenCalledOnce();
    expect(FakeEventSource.instances[0].close).toHaveBeenCalledOnce();
    vi.advanceTimersByTime(10_000);
    expect(FakeEventSource.instances).toHaveLength(1);

    const closedStream = new RunEventStream("run-4", { connectTimeoutMs: 100 });
    closedStream.close();
    vi.advanceTimersByTime(10_000);
    expect(FakeEventSource.instances).toHaveLength(2);
  });
});
