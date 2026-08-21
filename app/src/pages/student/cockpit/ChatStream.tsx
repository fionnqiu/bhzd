/**
 * 中部对话流（PRD-01 §3.2/§3.5）。
 *
 * 渲染顺序 = 学生感知顺序：受控处理记录 → 消息气泡 → 嵌入工具卡
 * → 失败块（中文原因 + 重试）。处理记录只承载经过
 * 脱敏的阶段和工具摘要，不能回流模型推理、提示词或原始工具载荷。
 * 欢迎态不在此处——空白态由页面直接渲染 WelcomeState（有消息才算"对话中"）。
 */
import { Fragment, useEffect, useRef } from "react";
import { Sparkles } from "lucide-react";
import { Button, Card } from "../../../components";
import MessageBubble from "./MessageBubble";
import EmbeddedCard from "./EmbeddedCard";
import TaskDraftSection from "./TaskDraftSection";
import ActivityTimeline from "./ActivityTimeline";
import LearningWorkflow from "./LearningWorkflow";
import ConfirmationGate from "./ConfirmationGate";
import { isStudentHiddenEmbeddedTool } from "./constants";
import type { CockpitRun } from "./useCockpitRun";
export interface ChatStreamProps {
  run: CockpitRun;
  /** 下一步建议“继续提问”→ 聚焦输入框 */
  onFocusComposer: () => void;
  /** Identifies the loaded transcript so each opened history starts at its newest turn. */
  conversationId: string | null;
  /** 任务卡「继续修改」：预填修订话术并聚焦（composer 状态由页面持有） */
  onPrefillComposer: (text: string) => void;
}

export interface ConversationInfoBarProps {
  conversationTitle: string;
}

/**
 * 页面级会话上下文头部。它由 CockpitPage 放在 transcript 滚动区之外，
 * 这样当前对话标题在阅读历史消息时仍固定在对话页面顶部。
 */
export function ConversationInfoBar({ conversationTitle }: ConversationInfoBarProps) {
  return (
    <div
      className="conversation-info-bar conversation-heading"
      role="status"
      aria-label="当前对话信息"
    >
      <Sparkles size={16} aria-hidden="true" />
      <strong>{conversationTitle}</strong>
    </div>
  );
}

/**
 * The transcript owns the scroll surface while the Composer remains its sibling.
 * This keeps the active input visible without pulling a reader through history.
 */
function pageScrollRegion(anchor: HTMLElement | null): HTMLElement | null {
  const transcript = anchor?.closest<HTMLElement>(".cockpit-content-scroll");
  if (transcript) return transcript;
  const mainContent = anchor?.closest<HTMLElement>(".main-content");
  if (mainContent) return mainContent;
  return document.scrollingElement instanceof HTMLElement ? document.scrollingElement : null;
}

export default function ChatStream({
  run,
  onFocusComposer,
  conversationId,
  onPrefillComposer,
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

  useEffect(() => {
    if (!conversationId) return;
    const scrollRegion = pageScrollRegion(bottomRef.current);
    if (!scrollRegion) return;

    // A selected history is a deliberate context switch, not a live update to
    // the previous transcript. Reset the follow preference and place its newest
    // turn in view once; later manual upward reading remains protected below.
    followBottomRef.current = true;
    scrollRegion.scrollTop = scrollRegion.scrollHeight;
  }, [conversationId]);

  // Safe activity and plan updates can increase the transcript before any
  // assistant token arrives. Include them in the same guarded follow rule so a
  // reader already at the bottom sees live progress, while the 48px preference
  // above still protects someone reading earlier messages.
  useEffect(() => {
    if (!pageScrollRegion(bottomRef.current) || !followBottomRef.current) return;
    // jsdom 未实现 scrollIntoView，可选调用兜底（测试环境直接跳过）。浏览器会让
    // 主页面滚动到锚点，而非再次创建消息列表内部的独立滚动条。
    bottomRef.current?.scrollIntoView?.({ block: "end" });
  }, [
    run.activities,
    run.cards,
    run.confirmation,
    run.confirming,
    run.error,
    run.historicalActivitiesByRun,
    run.messages,
    run.planSteps,
    run.reconciledActivity,
    run.status,
    run.streamRecovery,
  ]);

  // RAG execution remains available to the backend, but its
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
  // This bounded lifecycle copy replaces the former standalone thinking card. It
  // is deliberately passed only to the single execution record summary; raw model
  // reasoning never enters the transcript.
  const processingLabel =
    run.status === "planning"
      ? "正在整理学习目标"
      : run.status === "tool_running"
        ? "正在准备练习内容"
        : run.status === "awaiting_confirmation"
          ? "等待确认"
          : null;

  // 任务草稿按钮跟随产生它的回答（按 runId 关联），而不是漂在对话末尾；
  // 历史回放与流式新回答共用同一渲染入口。
  const renderTaskDraftSection = (runKey: string | null | undefined) => {
    if (!runKey) return null;
    const draft = run.taskDraftsByRun[runKey];
    if (!draft) return null;
    return (
      <TaskDraftSection
        draft={draft}
        onSync={() => run.syncTaskDraft(runKey, draft.id)}
        onRevise={() => onPrefillComposer("请修改刚才的学习任务：")}
      />
    );
  };

  return (
    <div className="chat-stream" data-testid="chat-stream">
      <div className="message-list" aria-live="polite" aria-relevant="additions text">
        {transcriptMessages.map((message) => (
          <Fragment key={message.id}>
            {message.role === "assistant" && message.runId ? (
              <LearningWorkflow
                activities={run.historicalActivitiesByRun[message.runId] ?? []}
                draft={run.taskDraftsByRun[message.runId] ?? null}
                live={false}
              />
            ) : null}
            {message.role === "assistant" && message.runId ? (
              <ActivityTimeline
                activities={run.historicalActivitiesByRun[message.runId] ?? []}
                activityGroupId={`history-${message.runId}`}
                live={false}
              />
            ) : null}
            <MessageBubble message={message} />
            {message.role === "assistant" ? renderTaskDraftSection(message.runId) : null}
          </Fragment>
        ))}

        {run.runId ? (
          // 任务流分组：步骤流 → 工具结果卡 → 确认卡 同属一条执行流水线，
          // 让"生成 → 预览 → 确认 → 同步到学习任务"的全过程对用户可见。
          <div className="run-flow" data-testid="run-flow">
            <LearningWorkflow
              activities={run.activities}
              planSteps={run.planSteps}
              draft={run.taskDraftsByRun[run.runId] ?? null}
              confirmation={run.confirmation}
              runStatus={run.status}
            />
            <ActivityTimeline
              activities={run.activities}
              planSteps={run.planSteps}
              currentActivity={run.reconciledActivity}
              activityGroupId={`live-${run.runId}`}
              processingLabel={processingLabel}
              live={isLive}
            />
            {visibleCards.map((card) => (
              <EmbeddedCard key={card.id} card={card} />
            ))}
            {run.confirmation ? (
              <ConfirmationGate
                confirmation={run.confirmation}
                confirming={run.confirming}
                onConfirm={run.confirm}
                onCancel={run.cancel}
              />
            ) : null}
          </div>
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

        {liveReply ? <MessageBubble message={liveReply} /> : null}

        {/* 草稿事件可能先于首个回答 delta 到达（草稿在最终合成前生成），
            因此入口独立于气泡渲染，回答出现后自然落在其下方。 */}
        {renderTaskDraftSection(run.runId)}

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

        <div ref={bottomRef} data-testid="chat-stream-bottom" />
      </div>
    </div>
  );
}
