import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { usePresence } from "./usePresence";

export type ToastKind = "success" | "error" | "info";

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

export interface ToastContextValue {
  /** 弹出一条提示（4 秒自动消失） */
  toast: (kind: ToastKind, message: string) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const TOAST_DURATION_MS = 4000;

function ToastItemView({ item, onDismiss }: { item: ToastItem; onDismiss: (id: number) => void }) {
  const [open, setOpen] = useState(true);
  const { isPresent, motionState } = usePresence(open);

  useEffect(() => {
    if (!open) return;
    const timeoutId = window.setTimeout(() => setOpen(false), TOAST_DURATION_MS);
    return () => window.clearTimeout(timeoutId);
  }, [open]);

  useEffect(() => {
    if (!isPresent) onDismiss(item.id);
  }, [isPresent, item.id, onDismiss]);

  if (!isPresent) return null;
  return (
    <div className={`toast toast-${item.kind}`} data-motion-state={motionState}>
      <div className="toast-body">{item.message}</div>
      <button className="icon-btn toast-close" aria-label="关闭提示" onClick={() => setOpen(false)}>
        ×
      </button>
    </div>
  );
}

/**
 * 全局轻提示。
 *
 * 为什么放在根级 Provider 而不是页面各自渲染：操作反馈（保存成功/失败）
 * 可能发生在任何组件层级，统一出口避免每个页面重复造 toast 状态；
 * 后端返回的中文 message 应原样透传给 error toast（错误话术后端统一）。
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback((kind: ToastKind, message: string) => {
    const id = Date.now() + Math.random();
    setItems((prev) => [...prev, { id, kind, message }]);
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

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-container" aria-live="polite">
        {items.map((item) => (
          <ToastItemView key={item.id} item={item} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/** 访问 toast；必须在 ToastProvider 内使用 */
export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast 必须在 ToastProvider 内使用");
  return ctx;
}
