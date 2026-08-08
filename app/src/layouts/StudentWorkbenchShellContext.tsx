import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiRequestError, api } from "../api/client";
import type { Conversation, Paginated } from "../api/types";

/** One-shot intent passed from a persistent sidebar to the Cockpit route. */
export type StudentWorkbenchSessionIntent =
  { sequence: number; kind: "new" } | { sequence: number; kind: "open"; conversationId: string };

type StudentWorkbenchSessionIntentInput =
  { kind: "new" } | { kind: "open"; conversationId: string };

interface StudentWorkbenchShellContextValue {
  studentWorkbenchSidebar: ReactNode;
  studentWorkbenchSidebarTop: ReactNode;
  studentWorkbenchCloseRequest: number;
  setStudentWorkbenchSidebar: (sidebar: ReactNode) => void;
  setStudentWorkbenchSidebarTop: (sidebar: ReactNode) => void;
  requestStudentWorkbenchSidebarClose: () => void;
  conversations: Conversation[];
  conversationsLoading: boolean;
  conversationsError: string | null;
  refreshConversations: (signal?: AbortSignal) => Promise<void>;
  activeConversationId: string | null;
  setActiveConversationId: (conversationId: string | null) => void;
  sessionActionsDisabled: boolean;
  setSessionActionsDisabled: (disabled: boolean) => void;
  sessionIntent: StudentWorkbenchSessionIntent | null;
  clearSessionIntent: (sequence: number) => void;
  requestNewConversation: () => void;
  requestOpenConversation: (conversationId: string) => void;
  removeConversation: (conversationId: string) => Promise<boolean>;
}

const noopSetStudentWorkbenchSidebar = (_sidebar: ReactNode) => {};
const noopRequestStudentWorkbenchSidebarClose = () => {};
const noopRefreshConversations = async (_signal?: AbortSignal) => {};
const noopSetActiveConversationId = (_conversationId: string | null) => {};
const noopSetSessionActionsDisabled = (_disabled: boolean) => {};
const noopClearSessionIntent = (_sequence: number) => {};
const noopRequestNewConversation = () => {};
const noopRequestOpenConversation = (_conversationId: string) => {};
const noopRemoveConversation = async (_conversationId: string) => false;

// A no-op default lets CockpitPage render in focused tests without requiring the
// authenticated student shell that normally owns the fixed sidebar.
const defaultValue: StudentWorkbenchShellContextValue = {
  studentWorkbenchSidebar: null,
  studentWorkbenchSidebarTop: null,
  studentWorkbenchCloseRequest: 0,
  setStudentWorkbenchSidebar: noopSetStudentWorkbenchSidebar,
  setStudentWorkbenchSidebarTop: noopSetStudentWorkbenchSidebar,
  requestStudentWorkbenchSidebarClose: noopRequestStudentWorkbenchSidebarClose,
  conversations: [],
  conversationsLoading: false,
  conversationsError: null,
  refreshConversations: noopRefreshConversations,
  activeConversationId: null,
  setActiveConversationId: noopSetActiveConversationId,
  sessionActionsDisabled: false,
  setSessionActionsDisabled: noopSetSessionActionsDisabled,
  sessionIntent: null,
  clearSessionIntent: noopClearSessionIntent,
  requestNewConversation: noopRequestNewConversation,
  requestOpenConversation: noopRequestOpenConversation,
  removeConversation: noopRemoveConversation,
};

export const StudentWorkbenchShellContext =
  createContext<StudentWorkbenchShellContextValue>(defaultValue);

export function useStudentWorkbenchShell(): StudentWorkbenchShellContextValue {
  return useContext(StudentWorkbenchShellContext);
}

export function useStudentWorkbenchSidebar(): (sidebar: ReactNode) => void {
  return useStudentWorkbenchShell().setStudentWorkbenchSidebar;
}

/** 注册需要位于共享导航之前的学生工作栏内容（如“新会话”主操作）。 */
export function useStudentWorkbenchSidebarTop(): (sidebar: ReactNode) => void {
  return useStudentWorkbenchShell().setStudentWorkbenchSidebarTop;
}

/** Requests that the shared shell close its compact navigation after a cockpit action. */
export function useStudentWorkbenchSidebarClose(): () => void {
  return useStudentWorkbenchShell().requestStudentWorkbenchSidebarClose;
}

interface StudentWorkbenchShellProviderProps {
  children: ReactNode;
}

/**
 * Persistent student session data is owned by the shell rather than Cockpit.
 * Route pages only consume an intent and keep their local SSE/run state, so
 * navigating to profile/tasks no longer removes the session rail.
 */
export function StudentWorkbenchShellProvider({ children }: StudentWorkbenchShellProviderProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [studentWorkbenchSidebar, setStudentWorkbenchSidebarState] = useState<ReactNode>(null);
  const [studentWorkbenchSidebarTop, setStudentWorkbenchSidebarTopState] =
    useState<ReactNode>(null);
  const [studentWorkbenchCloseRequest, setStudentWorkbenchCloseRequest] = useState(0);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationsLoading, setConversationsLoading] = useState(false);
  const [conversationsError, setConversationsError] = useState<string | null>(null);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [sessionActionsDisabled, setSessionActionsDisabled] = useState(false);
  const [sessionIntent, setSessionIntent] = useState<StudentWorkbenchSessionIntent | null>(null);
  const sessionIntentSequenceRef = useRef(0);
  const refreshRequestRef = useRef(0);
  const setStudentWorkbenchSidebar = useCallback((sidebar: ReactNode) => {
    setStudentWorkbenchSidebarState(sidebar);
  }, []);
  const setStudentWorkbenchSidebarTop = useCallback((sidebar: ReactNode) => {
    setStudentWorkbenchSidebarTopState(sidebar);
  }, []);
  const requestStudentWorkbenchSidebarClose = useCallback(() => {
    // A monotonically increasing signal reaches ShellLayout without coupling
    // sidebar slot content to the shell's private drawer state.
    setStudentWorkbenchCloseRequest((current) => current + 1);
  }, []);

  const refreshConversations = useCallback(async (signal?: AbortSignal) => {
    const requestId = ++refreshRequestRef.current;
    setConversationsLoading(true);
    setConversationsError(null);
    try {
      const response = await api.get<Paginated<Conversation>>("/api/conversations", undefined, {
        signal,
      });
      if (signal?.aborted || requestId !== refreshRequestRef.current) return;
      setConversations(response.items);
    } catch (error) {
      if (signal?.aborted || requestId !== refreshRequestRef.current) return;
      setConversationsError(
        error instanceof ApiRequestError ? error.message : "会话列表加载失败，请稍后重试",
      );
    } finally {
      if (!signal?.aborted && requestId === refreshRequestRef.current) {
        setConversationsLoading(false);
      }
    }
  }, []);

  // Load once for the whole student portal. The abort signal prevents a late
  // response from writing into a provider that was replaced by logout.
  useEffect(() => {
    const controller = new AbortController();
    void refreshConversations(controller.signal);
    return () => controller.abort();
  }, [refreshConversations]);

  const queueSessionIntent = useCallback(
    (intent: StudentWorkbenchSessionIntentInput) => {
      if (sessionActionsDisabled) return;
      const sequence = ++sessionIntentSequenceRef.current;
      setSessionIntent({ ...intent, sequence });
      requestStudentWorkbenchSidebarClose();
      // Keep the browser location canonical. If already on Cockpit, the
      // sequence change still wakes its consumer without a duplicate history
      // entry.
      if (location.pathname !== "/") navigate("/");
    },
    [location.pathname, navigate, requestStudentWorkbenchSidebarClose, sessionActionsDisabled],
  );

  const requestNewConversation = useCallback(() => {
    queueSessionIntent({ kind: "new" });
  }, [queueSessionIntent]);

  const requestOpenConversation = useCallback(
    (conversationId: string) => {
      if (!conversationId) return;
      queueSessionIntent({ kind: "open", conversationId });
    },
    [queueSessionIntent],
  );

  const clearSessionIntent = useCallback((sequence: number) => {
    setSessionIntent((current) => (current?.sequence === sequence ? null : current));
  }, []);

  const removeConversation = useCallback(
    async (conversationId: string): Promise<boolean> => {
      if (sessionActionsDisabled) return false;
      try {
        await api.delete(`/api/conversations/${conversationId}`);
        setConversations((current) =>
          current.filter((conversation) => conversation.id !== conversationId),
        );
        setConversationsError(null);
        const wasActive = activeConversationId === conversationId;
        if (wasActive) {
          setActiveConversationId(null);
          // Deleting the visible conversation returns the route to a clean
          // welcome state through the same one-shot path as "新建会话".
          queueSessionIntent({ kind: "new" });
        }
        await refreshConversations();
        return true;
      } catch (error) {
        setConversationsError(
          error instanceof ApiRequestError ? error.message : "删除会话失败，请稍后重试",
        );
        return false;
      }
    },
    [activeConversationId, queueSessionIntent, refreshConversations, sessionActionsDisabled],
  );

  const value = useMemo(
    () => ({
      studentWorkbenchSidebar,
      studentWorkbenchSidebarTop,
      studentWorkbenchCloseRequest,
      setStudentWorkbenchSidebar,
      setStudentWorkbenchSidebarTop,
      requestStudentWorkbenchSidebarClose,
      conversations,
      conversationsLoading,
      conversationsError,
      refreshConversations,
      activeConversationId,
      setActiveConversationId,
      sessionActionsDisabled,
      setSessionActionsDisabled,
      sessionIntent,
      clearSessionIntent,
      requestNewConversation,
      requestOpenConversation,
      removeConversation,
    }),
    [
      studentWorkbenchSidebar,
      studentWorkbenchSidebarTop,
      studentWorkbenchCloseRequest,
      setStudentWorkbenchSidebar,
      setStudentWorkbenchSidebarTop,
      requestStudentWorkbenchSidebarClose,
      conversations,
      conversationsLoading,
      conversationsError,
      refreshConversations,
      activeConversationId,
      sessionActionsDisabled,
      sessionIntent,
      clearSessionIntent,
      requestNewConversation,
      requestOpenConversation,
      removeConversation,
    ],
  );

  return (
    <StudentWorkbenchShellContext.Provider value={value}>
      {children}
    </StudentWorkbenchShellContext.Provider>
  );
}
