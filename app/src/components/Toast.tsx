import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";

export type ToastKind = "success" | "error" | "info";

export interface ToastContextValue {
  /** 保留提示调用契约；当前产品不再显示右上角浮层。 */
  toast: (kind: ToastKind, message: string) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

/**
 * 提供稳定的提示 API，但不再渲染右上角弹幕通知。
 *
 * 页面仍依赖 useToast 进行业务流程反馈；保留无操作实现可以避免逐页移除调用，
 * 同时确保右上角的全局浮层不会再次出现。
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const toast = useCallback((_kind: ToastKind, _message: string) => {
    // Keep callers harmlessly compatible while the visual notification surface is disabled.
  }, []);

  const value = useMemo<ToastContextValue>(
    () => ({
      toast,
      success: (m) => toast("success", m),
      error: (m) => toast("error", m),
      info: (m) => toast("info", m),
    }),
    [toast],
  );

  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>;
}

/** 访问 toast；必须在 ToastProvider 内使用 */
export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast 必须在 ToastProvider 内使用");
  return ctx;
}
