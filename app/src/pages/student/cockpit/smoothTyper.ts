/**
 * 平滑打字机：把 SSE 的突发 delta 缓冲起来，按固定帧节奏匀速吐出。
 *
 * 为什么需要它：message.delta 的到达节奏取决于网络与模型分片，直接
 * setMessages 会呈现"一顿一顿"的块状出现，且每个 token 触发一次整树
 * 重渲染。主流 agent（ChatGPT 等）的连续打字观感来自渲染节奏与传输
 * 节奏解耦——这里用一个小缓冲 + 定时帧实现同样的效果。
 *
 * 为什么用 setTimeout 而非 requestAnimationFrame：jsdom 测试中可以用假
 * 定时器确定性驱动，24ms 一帧对肉眼与渲染合并的效果与 rAF 等价。
 *
 * 硬约束：任何终态（完成/失败/断流/恢复回填）都必须先 flush() 再封口，
 * 保证缓冲里一个字都不丢；新 run 或切换会话前 dispose() 重置全部内部状态。
 */

export interface SmoothTyperOptions {
  /** 每帧最多回调一次：把当前应显示的全文交给渲染方（由调用方写入消息状态） */
  onRender: (text: string) => void;
  /**
   * 直通模式：delta 到达即整块渲染。用于测试环境（断言不需要等定时器）
   * 与 prefers-reduced-motion 用户（减少动态变化）。
   */
  instant?: boolean;
  /** 帧间隔（ms），默认 24ms */
  frameMs?: number;
  /** 基础速度（字符/秒），默认 48；中文阅读舒适区约 40–80 */
  charsPerSecond?: number;
}

export interface SmoothTyper {
  /** 追加一段原始 delta；缓冲模式下到下一帧才反映到 onRender */
  push: (delta: string) => void;
  /** 终态冲刷：立即渲染剩余全部内容并停表（内容零丢失的底线） */
  flush: () => void;
  /** 丢弃缓冲、停表并把已渲染计数清零（新 run / 切换会话 / 恢复回填前调用） */
  dispose: () => void;
  /** 仍在缓冲中、尚未渲染的字符数（测试与调试观测用） */
  readonly pendingCount: number;
}

const DEFAULT_FRAME_MS = 24;
const DEFAULT_CHARS_PER_SECOND = 48;
/** 英文吐字的词边界最大 lookahead，避免为找一个空格无限后延 */
const WORD_BOUNDARY_LOOKAHEAD = 8;

function isLatinWordChar(char: string | undefined): boolean {
  return char !== undefined && /[A-Za-z0-9]/.test(char);
}

/**
 * 当切点落在英文单词中间时把它顺延到词尾（有界）。中文没有词边界问题，
 * 逐字吐即是正确观感；硬切半个英文单词会造成肉眼可见的闪烁。
 */
function extendToWordBoundary(text: string, cut: number): number {
  if (cut >= text.length) return cut;
  if (!isLatinWordChar(text[cut - 1]) || !isLatinWordChar(text[cut])) return cut;
  let extended = cut;
  while (
    extended < text.length &&
    isLatinWordChar(text[extended]) &&
    extended - cut < WORD_BOUNDARY_LOOKAHEAD
  ) {
    extended += 1;
  }
  return extended;
}

export function createSmoothTyper(options: SmoothTyperOptions): SmoothTyper {
  const frameMs =
    typeof options.frameMs === "number" && options.frameMs > 0 ? options.frameMs : DEFAULT_FRAME_MS;
  const charsPerSecond =
    typeof options.charsPerSecond === "number" && options.charsPerSecond > 0
      ? options.charsPerSecond
      : DEFAULT_CHARS_PER_SECOND;
  const baseCharsPerFrame = Math.max(1, Math.round((charsPerSecond * frameMs) / 1000));
  const instant = options.instant === true;

  let rendered = "";
  let backlog = "";
  let timer: ReturnType<typeof setTimeout> | null = null;

  const emit = () => options.onRender(rendered);

  const stopTimer = () => {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  };

  const tick = () => {
    timer = null;
    if (!backlog) return;
    // 积压越多吐得越快：每帧至少吐积压的一半，网络突发（一次几百字符）
    // 在十余帧（约 250ms）内追平；低速流仍按基础节奏匀速前进。
    const count = Math.max(baseCharsPerFrame, Math.ceil(backlog.length / 2));
    const cut = extendToWordBoundary(backlog, Math.min(count, backlog.length));
    rendered += backlog.slice(0, cut);
    backlog = backlog.slice(cut);
    emit();
    if (backlog) {
      timer = setTimeout(tick, frameMs);
    }
  };

  return {
    push(delta: string) {
      if (!delta) return;
      if (instant) {
        rendered += delta;
        emit();
        return;
      }
      backlog += delta;
      if (timer === null) {
        timer = setTimeout(tick, frameMs);
      }
    },

    flush() {
      stopTimer();
      if (backlog) {
        rendered += backlog;
        backlog = "";
        emit();
      }
    },

    dispose() {
      stopTimer();
      backlog = "";
      rendered = "";
    },

    get pendingCount() {
      return backlog.length;
    },
  };
}
