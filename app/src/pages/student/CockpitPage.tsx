/**
 * Agent 指挥舱（/）——学生默认首页（PRD-01 §3，蓝图 §14）。
 *
 * 页面职责只有"编排"：消费学生壳发来的会话意图、管理对话区、欢迎入口
 * 的动作分派与诊断上传链路。会话列表和侧栏操作属于持久 StudentLayout，
 * 运行状态机在 useCockpitRun，上传链路在 useDiagnosticUpload，两者互不
 * 持有对方状态，避免确认门/流式气泡串台。
 *
 * 埋点分工（蓝图 §8）：前端只发 preset_clicked；goal_submitted /
 * diagnostic_uploaded / diagnostic_summary_saved 由后端路由写入，
 * 前端重复上报会双计数。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiRequestError, api } from "../../api/client";
import type { ConversationDetail, MasteryRecord, Paginated } from "../../api/types";
import { Button, Card, ConfirmDialog, ErrorState, useToast } from "../../components";
import { useStudentWorkbenchShell } from "../../layouts/StudentWorkbenchShellContext";
import { isTaskSyncConfirmationCommand, useCockpitRun } from "./cockpit/useCockpitRun";
import { useOnboardingGate } from "./OnboardingPage";
import { useDiagnosticUpload } from "./cockpit/useDiagnosticUpload";
import { useMediaUpload } from "./cockpit/useMediaUpload";
import WelcomeState, { type QuickAction } from "./cockpit/WelcomeState";
import ChatStream, { ConversationInfoBar } from "./cockpit/ChatStream";
import Composer, { type ComposerHandle } from "./cockpit/Composer";
import { DiagnosticReportContent } from "./cockpit/EmbeddedCard";
import { trackEvent } from "./cockpit/constants";
import type { ChatAttachment } from "./cockpit/types";
import "./cockpit/cockpit.css";

export default function CockpitPage() {
  // 入学测评门禁：未完成且未跳过的学生先进 /onboarding（v3.0 §11.1）
  useOnboardingGate();
  const toast = useToast();
  const run = useCockpitRun();
  const upload = useDiagnosticUpload();
  const mediaUpload = useMediaUpload();
  const { releasePersistedImagePreviews } = mediaUpload;
  // Keep the portal callbacks stable while the transcript receives streamed
  // updates; otherwise each activity frame would rebuild the outer sidebar.
  const { start, reset, loadConversation, conversationId, runId } = run;
  const sending = ["planning", "tool_running", "awaiting_confirmation"].includes(run.status);

  const [composerValue, setComposerValue] = useState("");
  // Keep the composer locked while an Agent run is active, except for the
  // exact text confirmation that completes an already reviewed task preview.
  const canConfirmTaskWithText =
    run.status === "awaiting_confirmation" &&
    run.confirmation?.action_type === "task.create" &&
    isTaskSyncConfirmationCommand(composerValue);
  const composerRef = useRef<ComposerHandle>(null);
  const refreshedRunRef = useRef<string | null>(null);
  const consumedSessionIntentRef = useRef<number | null>(null);
  const conversationLoadRequestRef = useRef(0);
  const {
    conversations,
    refreshConversations,
    setActiveConversationId,
    setSessionActionsDisabled,
    sessionIntent,
    clearSessionIntent,
  } = useStudentWorkbenchShell();

  // 快捷入口数据独立失败兜底为空列表，主流程不受辅助信息影响。
  const [mastery, setMastery] = useState<MasteryRecord[]>([]);
  const [saveConfirmOpen, setSaveConfirmOpen] = useState(false);

  useEffect(() => {
    // The durable thumbnail takes precedence in MessageBubble. Revoke the
    // transferred blob only after that URL reaches message state so a sent
    // image never flashes blank between Composer cleanup and history hydration.
    const persistedPreviewUrls = run.messages.flatMap((message) =>
      (message.attachments ?? []).flatMap((attachment) =>
        attachment.kind === "image" && attachment.thumbnailUrl && attachment.previewUrl
          ? [attachment.previewUrl]
          : [],
      ),
    );
    releasePersistedImagePreviews(persistedPreviewUrls);
  }, [releasePersistedImagePreviews, run.messages]);

  useEffect(() => {
    const controller = new AbortController();
    api
      .get<Paginated<MasteryRecord>>("/api/profile/mastery", undefined, {
        signal: controller.signal,
      })
      .then((res) => {
        if (!controller.signal.aborted) setMastery(res.items);
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    // The shell needs the real run lock before it can decide whether a global
    // new/open/delete action is safe. It owns the buttons; Cockpit owns SSE.
    setSessionActionsDisabled(sending);
  }, [sending, setSessionActionsDisabled]);

  useEffect(
    () => () => {
      // A route transition unmounts Cockpit. Clear the derived lock so a
      // stale local hook cannot leave the persistent navigation disabled.
      setSessionActionsDisabled(false);
    },
    [setSessionActionsDisabled],
  );

  useEffect(() => {
    if (conversationId) setActiveConversationId(conversationId);
  }, [conversationId, setActiveConversationId]);

  useEffect(() => {
    // A run can append to an existing conversation, so runId (rather than
    // conversationId) is the durable change signal for refreshing its title
    // and updated_at in the fixed student rail.
    if (!runId) {
      refreshedRunRef.current = null;
      return;
    }
    if (refreshedRunRef.current === runId) return;
    refreshedRunRef.current = runId;
    void refreshConversations();
  }, [refreshConversations, runId]);

  /** 薄弱能力（升序取前 5）：仅用于让预填的补强目标带上真实学习上下文。 */
  const weakCaps = useMemo(
    () => [...mastery].sort((a, b) => a.score - b.score).slice(0, 5),
    [mastery],
  );

  const sendGoal = useCallback(
    async (goal: string): Promise<boolean> => {
      const attachments = mediaUpload.attachments.map(({ attachment_token }) => ({
        attachment_token,
      }));
      const messageAttachments: ChatAttachment[] = mediaUpload.attachments.map((attachment) => ({
        id: attachment.attachment_token,
        name: attachment.name,
        kind: attachment.kind,
        mimeType: attachment.mime_type,
        size: attachment.size,
        previewUrl: attachment.previewUrl,
      }));
      const started = await start(
        goal,
        attachments.length
          ? {
              attachments,
              messageAttachments,
              // `start` also invokes this after a create-request retry succeeds.
              // That keeps the Composer and persisted user row in one ownership flow.
              onAccepted: mediaUpload.consume,
            }
          : undefined,
      );
      // Keep local cards after a rejected run request so the learner can retry
      // with the same files. `onAccepted` clears them only after server acceptance.
      return started;
    },
    [mediaUpload.attachments, mediaUpload.consume, start],
  );

  const handleComposerUpload = useCallback(
    (files: File[]) => {
      // The Composer is a conversation surface: every supported selection,
      // including JSON/TextGrid/XML, must become current-turn Agent context.
      void mediaUpload.upload(files);
    },
    [mediaUpload.upload],
  );

  const handleDiagnosticUpload = useCallback(
    (file: File) => {
      // Diagnostics retain their report-and-confirm workflow only when the
      // learner deliberately enters through the dedicated quick action.
      void upload.upload(file);
    },
    [upload.upload],
  );

  /**
   * 欢迎态快捷入口只预填文本并交回学生确认；上传需要用户选取真实文件，
   * 因而是唯一直接打开系统文件选择器的入口。
   */
  const handleQuickAction = useCallback(
    (action: QuickAction) => {
      switch (action.kind) {
        case "fill": {
          trackEvent("preset_clicked", { preset_id: action.id, source: "welcome" });
          const weakest = weakCaps[0];
          const goal =
            action.id === "weak-boost" && weakest
              ? `我想补强薄弱能力「${weakest.cap_name}」，请生成针对性练习任务`
              : action.goal;
          setComposerValue(goal);
          composerRef.current?.focus();
          break;
        }
        case "upload":
          trackEvent("preset_clicked", { preset_id: "upload-diagnose", source: "welcome" });
          composerRef.current?.openDiagnosticPicker();
          break;
      }
    },
    [weakCaps],
  );

  const handleSelectConversation = useCallback(
    async (id: string) => {
      if (sending) return;
      const requestId = ++conversationLoadRequestRef.current;
      try {
        const detail = await api.get<ConversationDetail>(`/api/conversations/${id}`);
        // A global rail stays interactive across pages. Ignore a late detail
        // response when the learner chose a newer conversation in the meantime.
        if (requestId !== conversationLoadRequestRef.current) return;
        loadConversation(detail);
        setActiveConversationId(detail.id);
        // The Composer changes variant after loading a transcript. Defer focus
        // until the persistent input has mounted in its conversation position.
        requestAnimationFrame(() => composerRef.current?.focus());
      } catch (err) {
        if (requestId !== conversationLoadRequestRef.current) return;
        toast.error(err instanceof ApiRequestError ? err.message : "会话加载失败，请稍后重试");
      }
    },
    [loadConversation, sending, setActiveConversationId, toast],
  );

  const handleNewConversation = useCallback(() => {
    if (sending) return;
    // Invalidate a pending detail read before restoring the clean welcome state.
    conversationLoadRequestRef.current += 1;
    reset();
    setComposerValue("");
    setActiveConversationId(null);
    toast.success("已开始新会话");
    requestAnimationFrame(() => composerRef.current?.focus());
  }, [reset, sending, setActiveConversationId, toast]);

  useEffect(() => {
    if (!sessionIntent || consumedSessionIntentRef.current === sessionIntent.sequence) return;
    consumedSessionIntentRef.current = sessionIntent.sequence;
    clearSessionIntent(sessionIntent.sequence);
    if (sessionIntent.kind === "new") {
      handleNewConversation();
      return;
    }
    void handleSelectConversation(sessionIntent.conversationId);
  }, [clearSessionIntent, handleNewConversation, handleSelectConversation, sessionIntent]);

  /** 生成补强计划：diagnostic_token 经 attachment 传给编排器（runs.py 支持） */
  const handleBoostFromDiagnosis = useCallback(() => {
    const token = upload.report?.diagnostic_token;
    if (!token) return;
    upload.dismiss();
    void start("根据刚才的诊断结果生成补强计划", {
      attachment: { diagnostic_token: token },
    });
  }, [start, upload]);

  const showWelcome = run.status === "idle" && run.messages.length === 0;
  const conversationTitle = useMemo(
    () =>
      conversations.find((conversation) => conversation.id === conversationId)?.title?.trim() ||
      "学习会话",
    [conversationId, conversations],
  );
  const renderComposer = (variant: "default" | "hero") => (
    <Composer
      ref={composerRef}
      variant={variant}
      value={composerValue}
      onChange={setComposerValue}
      onSend={() => {
        const text = composerValue.trim();
        if (!text) return;
        void sendGoal(text).then((started) => {
          // Do not discard a failed message. It may reference attachments
          // that remain selected specifically so the learner can retry.
          if (started) setComposerValue("");
        });
      }}
      onUpload={handleComposerUpload}
      onDiagnosticUpload={handleDiagnosticUpload}
      sending={sending}
      allowSendWhileSending={canConfirmTaskWithText}
      uploading={upload.uploading || mediaUpload.uploading}
      uploadingAttachments={mediaUpload.uploadingAttachments}
      mediaAttachments={mediaUpload.attachments}
      onRemoveMedia={mediaUpload.remove}
      onLoadDocumentPreview={mediaUpload.loadDocumentPreview}
    />
  );
  return (
    <div className="cockpit cockpit-workbench">
      {/* Keep the title band outside the constrained conversation column so it
          can span the full main area without being clipped by the scroll shell. */}
      {showWelcome ? null : <ConversationInfoBar conversationTitle={conversationTitle} />}
      <div className={`cockpit-center${showWelcome ? " cockpit-center-welcome" : ""}`}>
        {/* Welcome intentionally owns the visual Hero -> Prompt -> quick-link order.
            Once a transcript exists, the Composer returns outside the scroller so
            long histories never push the active input out of reach. */}
        <div
          className="cockpit-content-scroll"
          data-testid="cockpit-scroll-region"
          role="region"
          aria-label="对话内容"
        >
          {/* The outer region owns vertical scrolling; this inner stack only
              lays out transcript content so the Composer remains a sibling. */}
          <div className="cockpit-content-inner" data-testid="cockpit-content-inner">
            {showWelcome ? (
              <WelcomeState
                onQuickAction={handleQuickAction}
                composer={renderComposer("hero")}
                busy={sending}
              />
            ) : (
              <ChatStream
                run={run}
                onFocusComposer={() => composerRef.current?.focus()}
                conversationId={conversationId}
              />
            )}

            {upload.report ? (
              <Card
                title="诊断报告"
                className="embedded-card"
                data-testid="diagnostic-report"
                actions={
                  <Button variant="ghost" size="sm" onClick={upload.dismiss}>
                    关闭
                  </Button>
                }
              >
                <DiagnosticReportContent report={upload.report} />
                <div className="flex gap-2 mt-4">
                  {/* 保存摘要会写掌握度：先弹确认展示 old→new（PRD-01 §7 验收） */}
                  <Button size="sm" onClick={() => setSaveConfirmOpen(true)}>
                    保存诊断摘要
                  </Button>
                  <Button size="sm" variant="secondary" onClick={handleBoostFromDiagnosis}>
                    生成补强计划
                  </Button>
                </div>
              </Card>
            ) : null}
          </div>
        </div>

        {showWelcome ? null : renderComposer("default")}
      </div>

      <ConfirmDialog
        open={saveConfirmOpen}
        title="保存诊断摘要"
        description={`将保存本次诊断摘要并按以下预览更新掌握度：\n${(
          upload.report?.mastery_preview ?? []
        )
          .map(
            (m) =>
              `${m.cap_id}：${Math.round((m.old_score ?? 0) * 100)}% → ${Math.round(
                (m.new_score ?? 0) * 100,
              )}%`,
          )
          .join("\n")}`}
        confirmText="保存"
        onCancel={() => setSaveConfirmOpen(false)}
        onConfirm={async () => {
          const ok = await upload.saveSummary();
          if (ok) setSaveConfirmOpen(false);
        }}
      />
    </div>
  );
}
