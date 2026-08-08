/**
 * 中部对话流（PRD-01 §3.2/§3.5）。
 *
 * 渲染顺序 = 学生感知顺序：受控处理记录 → 消息气泡 → 嵌入工具卡
 * → 场景切换建议 → 失败块（中文原因 + 重试）。处理记录只承载经过
 * 脱敏的阶段和工具摘要，不能回流模型推理、提示词或原始工具载荷。
 * 欢迎态不在此处——空白态由页面直接渲染 WelcomeState（有消息才算"对话中"）。
 */
import { Fragment, useEffect, useRef } from "react";
import { Sparkles } from "lucide-react";
import { Button, Card } from "../../../components";
import MessageBubble from "./MessageBubble";
import EmbeddedCard from "./EmbeddedCard";
import ActivityTimeline from "./ActivityTimeline";
import { isStudentHiddenEmbeddedTool } from "./constants";
import type { CockpitRun } from "./useCockpitRun";
import RightRail from "./RightRail";

export interface ChatStreamProps {
  run: CockpitRun;
  conversationTitle: string;
  scenarioName: string;
  /** 下一步建议"继续提问"→ 聚焦输入框 */
  onFocusComposer: () => void;
  /** 场景切换建议确认（PRD-06 §7.3：用户点击才切，绝不自动切） */
  onAcceptSuggestion: (scenarioId: string) => void;
}

/**
 * The conversation no longer owns an inner scrollbar.  Resolve the shell's
 * page-level main surface so streaming can follow only when the reader is
 * already near the bottom of the actual page.
 */
function pageScrollRegion(anchor: HTMLElement | null): HTMLElement | null {
  const mainContent = anchor?.closest<HTMLElement>(".main-content");
  if (mainContent) return mainContent;
  return document.scrollingElement instanceof HTMLElement ? document.scrollingElement : null;
}

export default function ChatStream({
  run,
  conversationTitle,
  scenarioName,
  onFocusComposer,
  onAcceptSuggestion,
}: ChatStreamProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const followBottomRef = useRef(true);

  useEffect(() => {
    const scrollRegion = pageScrollRegion(bottomRef.current);
    if (!scrollRegion) return;

    const updateFollowPreference = () => {
      const remaining =
        scrollRegion.scrollHeight - scrollRegion.scrollTop - scrollRegion.clientHeight;
      // A small tolerance absorbs fractional layout and scrollbar rounding while
      // still respecting a reader who deliberately moved away from the bottom.
      followBottomRef.current = remaining <= 48;
    };

    updateFollowPreference();
    scrollRegion.addEventListener("scroll", updateFollowPreference, { passive: true });
    return () => scrollRegion.removeEventListener("scroll", updateFollowPreference);
  }, []);

  // Message and visible-card references change for streamed replies and tool
  // outputs. Follow them without pulling readers away from historical content.
  useEffect(() => {
    if (!pageScrollRegion(bottomRef.current) || !followBottomRef.current) return;
    // jsdom 未实现 scrollIntoView，可选调用兜底（测试环境直接跳过）。浏览器会让
    // 主页面滚动到锚点，而非再次创建消息列表内部的独立滚动条。
    bottomRef.current?.scrollIntoView?.({ block: "end" });
  }, [
    run.cards,
    run.error,
    run.messages,
    run.status,
    run.streamRecovery,
    run.suggestion,
    run.confirmation,
    run.confirming,
    run.citations,
  ]);

  // RAG execution remains available to the backend and citation panel, but its
  // intermediate cards duplicate the answer rather than help the learner act.
  const visibleCards = run.cards.filter((card) => !isStudentHiddenEmbeddedTool(card.tool));
  const liveReplyId = run.runId ? `asst-${run.runId}` : null;
  const liveReply = liveReplyId
    ? (run.messages.find((message) => message.id === liveReplyId) ?? null)
    : null;
  // Keep the current turn's reply after tool cards so the conversation remains
  // chronological without inserting internal execution events between replies.
  const transcriptMessages = liveReply
    ? run.messages.filter((message) => message.id !== liveReply.id)
    : run.messages;
  const isLive = ["planning", "tool_running", "awaiting_confirmation"].includes(run.status);

  return (
    <div className="chat-stream" data-testid="chat-stream">
      <div className="conversation-heading" aria-label="当前会话">
        <Sparkles size={16} aria-hidden="true" />
        <strong>{conversationTitle}</strong>
        <span>· 当前场景：{scenarioName}</span>
      </div>

      <div className="message-list" aria-live="polite" aria-relevant="additions text">
        {transcriptMessages.map((message) => (
          <Fragment key={message.id}>
            {message.role === "assistant" && message.runId ? (
              <ActivityTimeline
                activities={run.historicalActivitiesByRun[message.runId] ?? []}
                activityGroupId={`history-${message.runId}`}
                live={false}
              />
            ) : null}
            <MessageBubble message={message} />
          </Fragment>
        ))}

        {run.runId ? (
          <ActivityTimeline
            activities={run.activities}
            planSteps={run.planSteps}
            currentActivity={run.reconciledActivity}
            activityGroupId={`live-${run.runId}`}
            live={isLive}
          />
        ) : null}

        {run.streamRecovery ? (
          <Card
            title={
              run.streamRecovery.kind === "reconnecting" ? "正在恢复实时连接" : "实时连接已中断"
            }
            className="stream-recovery"
            data-testid="stream-recovery"
          >
            <p role="status">
              {run.streamRecovery.kind === "reconnecting"
                ? run.streamRecovery.retryAttempt > 0
                  ? `连接暂时中断，正在尝试第 ${run.streamRecovery.retryAttempt}/3 次重新连接。`
                  : "正在重新连接服务器，请稍候。"
                : run.streamRecovery.message}
            </p>
            <div className="flex gap-2 mt-2">
              <Button size="sm" onClick={run.reconnect}>
                重新连接
              </Button>
              <Button size="sm" variant="ghost" onClick={() => void run.refreshRun()}>
                查询最新状态
              </Button>
            </div>
          </Card>
        ) : null}

        {visibleCards.map((card) => (
          <EmbeddedCard key={card.id} card={card} />
        ))}

        {liveReply ? <MessageBubble message={liveReply} /> : null}

        {/* Keep confirmation and citations before the anchor so new runtime
            context is included in the same bottom-following scroll transaction. */}
        <RightRail run={run} />

        {run.status === "failed" ? (
          <Card title="运行失败" className="run-failed" data-testid="run-failed">
            {/* 后端中文话术原样展示；绝不渲染堆栈（PRD-01 §3.5） */}
            <p>{run.error ?? "运行失败，请稍后重试"}</p>
            <div className="flex gap-2 mt-2">
              <Button size="sm" onClick={run.retry}>
                重试
              </Button>
              <Button size="sm" variant="ghost" onClick={onFocusComposer}>
                修改后再发
              </Button>
            </div>
          </Card>
        ) : null}

        {run.suggestion ? (
          <Card title="场景建议" className="scenario-hint" data-testid="scenario-suggestion">
            <p>{run.suggestion.message}</p>
            <div className="flex gap-2 mt-2">
              <Button
                size="sm"
                onClick={() => {
                  onAcceptSuggestion(run.suggestion!.suggested_scenario_id);
                  run.dismissSuggestion();
                }}
              >
                切换到该场景
              </Button>
              <Button size="sm" variant="ghost" onClick={run.dismissSuggestion}>
                暂不切换
              </Button>
            </div>
          </Card>
        ) : null}

        <div ref={bottomRef} data-testid="chat-stream-bottom" />
      </div>
    </div>
  );
}
