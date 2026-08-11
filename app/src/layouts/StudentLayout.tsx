import { ListTodo, Map, Route, Bell } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { usePresence } from "../components/usePresence";
import { WorkbenchNewSession, WorkbenchRecentSessions } from "../pages/student/cockpit/LeftRail";
import ShellLayout, { type NavItem } from "./ShellLayout";
import {
  StudentWorkbenchShellProvider,
  useStudentWorkbenchShell,
} from "./StudentWorkbenchShellContext";

/** 学生端导航保留学习入口；诊断上传与结果展示已内置于 Agent 工作台。 */
const NAV_ITEMS: NavItem[] = [
  { to: "/presets", label: "预设学习", icon: Route },
  { to: "/graph", label: "能力图谱", icon: Map },
  { to: "/tasks", label: "学习任务", icon: ListTodo },
];

/* ---------------------------------------------------------------- 站内通知 */

/** GET /api/notifications 列表项（notifications.py `_notification_dto`；页内声明防并行改 types） */
interface NotificationItem {
  id: string;
  type: string;
  title: string;
  body: string | null;
  ref_type: string | null;
  ref_id: string | null;
  read_at: string | null;
  created_at: string;
}

/** 通知类型 → 中文名（后端 type 为自由字符串，未知类型兜底"通知"） */
const NOTIFICATION_TYPE_LABELS: Record<string, string> = {
  task_assigned: "任务",
  task_feedback: "反馈",
  task_reminder: "提醒",
  class: "班级",
  system: "系统",
};

function notificationTypeLabel(type: string): string {
  return NOTIFICATION_TYPE_LABELS[type] ?? "通知";
}

/** ISO → 本地短格式（布局文件自洽，不反向依赖页面层 shared） */
function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

const UNREAD_POLL_MS = 30_000;
const RECENT_LIMIT = 10;

/**
 * 全局通知铃铛：未读角标 30s 轮询 + 最近 10 条下拉。
 *
 * 为什么轮询而非推送：平台没有 WebSocket/SSE 通道，30s 轮询 unread-count
 * （极轻 COUNT 查询）是当前架构下成本最低的准实时方案；面板打开时立即拉
 * 最近列表，保证点开即最新。点击任务类通知直接跳任务详情并顺手标已读。
 */
function NotificationBell({ navigationDisabled = false }: { navigationDisabled?: boolean }) {
  const navigate = useNavigate();
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const notificationPresence = usePresence(open);

  const refreshUnread = useCallback((signal?: AbortSignal) => {
    api
      .get<{ unread: number }>("/api/notifications/unread-count", undefined, { signal })
      .then((res) => {
        if (!signal?.aborted) setUnread(res.unread);
      })
      .catch(() => {
        /* 角标失败静默：下一轮轮询自愈，绝不影响固定入口可用性 */
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    refreshUnread(controller.signal);
    const timer = window.setInterval(() => refreshUnread(controller.signal), UNREAD_POLL_MS);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [refreshUnread]);

  // 点击铃铛外部收起面板（与 ShellLayout 下拉同一交互口径）
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  /** 打开面板：拉最近 10 条（新→旧）；失败保留旧列表，下次重开再试 */
  const toggleOpen = () => {
    const next = !open;
    setOpen(next);
    if (!next) return;
    setLoadingList(true);
    api
      .get<{ items: NotificationItem[] }>("/api/notifications", { limit: RECENT_LIMIT })
      .then((res) => setItems(res.items))
      .catch(() => {})
      .finally(() => setLoadingList(false));
  };

  /** 单条点击：标已读（幂等）+ 本地即时更新；任务类通知跳任务详情 */
  // A live Cockpit owns the SSE lifecycle, so task notices remain read-only
  // until it reaches a terminal state; non-routing system notices remain usable.
  const openItem = async (item: NotificationItem) => {
    if (navigationDisabled && item.ref_type === "task" && item.ref_id) return;
    if (item.read_at === null) {
      api
        .post(`/api/notifications/${item.id}/read`)
        .then(() => refreshUnread())
        .catch(() => {});
      setItems((prev) =>
        prev.map((n) => (n.id === item.id ? { ...n, read_at: new Date().toISOString() } : n)),
      );
      setUnread((prev) => Math.max(0, prev - 1));
    }
    if (item.ref_type === "task" && item.ref_id) {
      setOpen(false);
      navigate(`/tasks/${item.ref_id}`);
    }
  };

  /** 全部已读：一键清零后同步列表与角标 */
  const markAllRead = async () => {
    try {
      await api.post("/api/notifications/read-all");
      setItems((prev) =>
        prev.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })),
      );
      setUnread(0);
    } catch {
      /* 失败由下一轮轮询兜底 */
    }
  };

  return (
    <div className="dropdown" ref={rootRef} style={{ position: "relative" }}>
      <button
        type="button"
        className="icon-btn"
        aria-label={`通知${unread > 0 ? `（${unread} 条未读）` : ""}`}
        title="通知"
        onClick={toggleOpen}
        style={{ position: "relative" }}
      >
        <Bell size={18} />
        {unread > 0 ? (
          <span
            className="badge badge-danger"
            style={{
              position: "absolute",
              top: -6,
              right: -8,
              padding: "0 5px",
              fontSize: 11,
              lineHeight: "16px",
              minWidth: 16,
            }}
          >
            {unread > 99 ? "99+" : unread}
          </span>
        ) : null}
      </button>
      {notificationPresence.isPresent ? (
        <div
          className="dropdown-menu student-workbench-notification-menu"
          data-motion-state={notificationPresence.motionState}
          style={{ right: 0, left: "auto" }}
        >
          <div
            className="dropdown-item"
            style={{ cursor: "default", justifyContent: "space-between" }}
          >
            <strong className="text-sm">通知</strong>
            <button type="button" className="btn btn-ghost btn-sm" onClick={markAllRead}>
              全部已读
            </button>
          </div>
          <div className="dropdown-divider" />
          {loadingList && items.length === 0 ? (
            <div className="dropdown-item text-sm text-secondary" style={{ cursor: "default" }}>
              正在加载…
            </div>
          ) : items.length === 0 ? (
            <div className="dropdown-item text-sm text-secondary" style={{ cursor: "default" }}>
              暂无通知
            </div>
          ) : (
            items.map((item) => (
              <button
                key={item.id}
                type="button"
                className="dropdown-item"
                style={{ alignItems: "flex-start", textAlign: "left" }}
                disabled={navigationDisabled && item.ref_type === "task" && Boolean(item.ref_id)}
                onClick={() => openItem(item)}
              >
                <span className="badge badge-neutral" style={{ flexShrink: 0 }}>
                  {notificationTypeLabel(item.type)}
                </span>
                <span style={{ flex: 1 }}>
                  {/* 未读加粗：读态差异是一眼可辨的扫描线索 */}
                  <span
                    className="text-sm"
                    style={{ fontWeight: item.read_at === null ? 600 : 400, display: "block" }}
                  >
                    {item.title}
                  </span>
                  <span className="text-xs text-muted">{formatTime(item.created_at)}</span>
                </span>
              </button>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}

/**
 * Student shell: the notification stays globally reachable as a fixed action,
 * while the Composer owns the ScenarioContext control next to the message it affects.
 */
function StudentLayoutContent() {
  const {
    studentWorkbenchSidebar,
    studentWorkbenchSidebarTop,
    studentWorkbenchCloseRequest,
    conversations,
    conversationsLoading,
    conversationsError,
    refreshConversations,
    activeConversationId,
    sessionActionsDisabled,
    requestNewConversation,
    requestOpenConversation,
    removeConversation,
  } = useStudentWorkbenchShell();
  return (
    <ShellLayout
      portalKey="student"
      variant="student-workbench"
      studentWorkbenchSidebar={
        <>
          {studentWorkbenchSidebar}
          <WorkbenchRecentSessions
            conversations={conversations}
            activeConversationId={activeConversationId}
            loading={conversationsLoading}
            error={conversationsError}
            busy={sessionActionsDisabled}
            onSelectConversation={requestOpenConversation}
            onDeleteConversation={removeConversation}
            onRetry={() => void refreshConversations()}
          />
        </>
      }
      studentWorkbenchSidebarTop={
        <>
          <WorkbenchNewSession
            busy={sessionActionsDisabled}
            onNewConversation={requestNewConversation}
          />
          {studentWorkbenchSidebarTop}
        </>
      }
      studentWorkbenchCloseRequest={studentWorkbenchCloseRequest}
      studentWorkbenchNavigationDisabled={sessionActionsDisabled}
      portalName="学生端"
      navItems={NAV_ITEMS}
      // Keep notifications outside the document flow so route content does not need a toolbar.
      studentWorkbenchFloatingActions={
        <NotificationBell navigationDisabled={sessionActionsDisabled} />
      }
    />
  );
}

/** The provider keeps global session navigation mounted while ShellLayout renders route outlets. */
export default function StudentLayout() {
  return (
    <StudentWorkbenchShellProvider>
      <StudentLayoutContent />
    </StudentWorkbenchShellProvider>
  );
}
