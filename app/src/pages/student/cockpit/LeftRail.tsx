/**
 * 学生工作栏中的会话入口：新会话与最近会话属于稳定导航，而不是
 * 需要额外打开的内容抽屉。删除确认仍由本组件负责，避免把破坏性操作
 * 直接暴露在窄小的会话行上。
 *
 * 注意：删除确认弹窗通过 portal 挂到 document.body。侧栏的玻璃材质
 * （backdrop-filter）会成为 fixed 后代的包含块，原地渲染会把全局模态
 * 禁锢在侧栏区域内（与 Select 下拉列表的 portal 同一处理思路）。
 */
import { MessageSquarePlus, Trash2 } from "lucide-react";
import { useState } from "react";
import { createPortal } from "react-dom";
import { Button, ConfirmDialog, IconButton } from "../../../components";
import type { Conversation } from "../../../api/types";

export interface LeftRailProps {
  conversations: Conversation[];
  activeConversationId: string | null;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void | Promise<boolean>;
  onNewConversation: () => void;
  /** 正在运行时锁定会话导航，避免关闭 SSE 后绕过并发限制。 */
  busy?: boolean;
  /** 持久工作栏首次拉取会话时的可访问加载态。 */
  loading?: boolean;
  /** 拉取或删除失败时保留在工作栏中的可恢复错误。 */
  error?: string | null;
  onRetry?: () => void;
}

export function WorkbenchNewSession({
  busy = false,
  onNewConversation,
}: Pick<LeftRailProps, "busy" | "onNewConversation">) {
  return (
    <Button
      id="newSessionButton"
      className="workbench-new-session"
      variant="secondary"
      size="sm"
      aria-label="新建会话"
      aria-describedby="newSessionKeyboardHint"
      title="新建会话"
      disabled={busy}
      onClick={onNewConversation}
    >
      <MessageSquarePlus size={16} aria-hidden="true" />
      <span className="workbench-new-session-label">新建会话</span>
      <kbd
        id="newSessionKeyboardHint"
        className="workbench-new-session-hint"
        aria-label="Ctrl K 快捷键提示，当前未绑定"
      >
        Ctrl K
      </kbd>
    </Button>
  );
}

export function WorkbenchRecentSessions({
  conversations,
  activeConversationId,
  onSelectConversation,
  onDeleteConversation,
  busy = false,
  loading = false,
  error = null,
  onRetry,
}: Omit<LeftRailProps, "onNewConversation">) {
  const [pendingDelete, setPendingDelete] = useState<Conversation | null>(null);

  return (
    <div
      className="workbench-session-list workbench-recent-sessions"
      aria-labelledby="recentSessionsTitle"
      data-testid="cockpit-conversation-panel"
    >
      <div className="workbench-session-heading">
        <span id="recentSessionsTitle" className="workbench-session-heading-label">
          最近会话
        </span>
        {conversations.length > 0 ? (
          <span
            className="workbench-session-count"
            aria-label={`共 ${conversations.length} 个会话`}
          >
            {conversations.length}
          </span>
        ) : null}
      </div>

      {loading && conversations.length === 0 ? (
        <p className="workbench-session-empty" role="status" aria-live="polite">
          正在加载会话…
        </p>
      ) : error && conversations.length === 0 ? (
        <div className="workbench-session-error" role="alert">
          <p>{error}</p>
          {onRetry ? (
            <Button type="button" variant="ghost" size="sm" onClick={onRetry} disabled={loading}>
              重试
            </Button>
          ) : null}
        </div>
      ) : conversations.length === 0 ? (
        <p className="workbench-session-empty">发送一个学习目标后，会话会出现在这里。</p>
      ) : (
        <div
          className="workbench-session-scroll workbench-recent-list"
          role="list"
          aria-label="最近会话列表"
        >
          {conversations.map((conversation) => {
            const title = conversation.title || "未命名会话";
            const active = conversation.id === activeConversationId;
            const updatedAt = new Date(conversation.updated_at).toLocaleDateString("zh-CN");
            return (
              <div
                key={conversation.id}
                className={`workbench-session-row${active ? " is-active is-current" : ""}`}
                role="listitem"
                data-current={active ? "true" : undefined}
              >
                {/* Keep the visual active state and aria-current on the same item. */}
                <button
                  type="button"
                  className="workbench-session-main"
                  aria-current={active ? "page" : undefined}
                  aria-label={`${active ? "当前会话" : "打开会话"}：${title}，更新于 ${updatedAt}`}
                  disabled={busy}
                  onClick={() => onSelectConversation(conversation.id)}
                >
                  <span className="workbench-session-title">{title}</span>
                  <span className="workbench-session-date">{updatedAt}</span>
                </button>
                <IconButton
                  className="workbench-session-delete"
                  aria-label={`删除会话 ${title}`}
                  title={`删除会话 ${title}`}
                  data-session-action="delete"
                  disabled={busy}
                  onClick={() => setPendingDelete(conversation)}
                >
                  <Trash2 size={14} aria-hidden="true" />
                </IconButton>
              </div>
            );
          })}
        </div>
      )}

      {error && conversations.length > 0 ? (
        <div className="workbench-session-error" role="alert">
          <p>{error}</p>
          {onRetry ? (
            <Button type="button" variant="ghost" size="sm" onClick={onRetry} disabled={loading}>
              重试
            </Button>
          ) : null}
        </div>
      ) : null}

      {typeof document === "undefined"
        ? null
        : createPortal(
            <ConfirmDialog
              open={pendingDelete !== null}
              title="删除会话"
              description={`确定删除会话“${pendingDelete?.title || "未命名会话"}”吗？会话中的消息将一并删除，该操作不可恢复。`}
              confirmText="删除"
              danger
              onCancel={() => setPendingDelete(null)}
              onConfirm={() => {
                if (pendingDelete) onDeleteConversation(pendingDelete.id);
                setPendingDelete(null);
              }}
            />,
            document.body,
          )}
    </div>
  );
}

/** Backward-compatible composition for focused tests and non-shell consumers. */
export default function LeftRail(props: LeftRailProps) {
  return (
    <>
      <WorkbenchNewSession busy={props.busy} onNewConversation={props.onNewConversation} />
      <WorkbenchRecentSessions {...props} />
    </>
  );
}
