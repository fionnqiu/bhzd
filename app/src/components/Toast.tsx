import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type ReactNode,
} from "react";

export type ToastKind = "success" | "error" | "info" | "warning";

export interface ToastContextValue {
  /** 在应用级提示队列中加入一条短时消息。 */
  toast: (kind: ToastKind, message: string) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
  warning: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

/**
 * 保留应用级 toast API 的兼容层，但不再渲染右上角浮层。
 *
 * 页面内状态、错误区和通知中心承载持久反馈；让这个 provider 保持可调用
 * 可以避免旧页面在迁移期间崩溃，同时遵守工作台不插入瞬时覆盖层的交互约定。
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const toast = useCallback((_kind: ToastKind, _message: string) => {
    // Intentionally empty: callers retain the stable API while visible feedback
    // is provided by persistent page state or the notification center.
  }, []);

  const value = useMemo<ToastContextValue>(
    () => ({
      toast,
      success: (m) => toast("success", m),
      error: (m) => toast("error", m),
      info: (m) => toast("info", m),
      warning: (m) => toast("warning", m),
    }),
    [toast],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
    </ToastContext.Provider>
  );
}

/** 访问 toast；必须在 ToastProvider 内使用 */
export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast 必须在 ToastProvider 内使用");
  return ctx;
}
