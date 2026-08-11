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
import { X } from "lucide-react";

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

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

const TOAST_DURATION_MS = 3600;
const MAX_VISIBLE_TOASTS = 3;

/**
 * 应用级短时反馈。消息挂在根 Provider 上，跨路由保持一致，避免每个页面
 * 自己实现提示层；持续性的表单错误仍由页面内组件承载。
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextIdRef = useRef(0);
  const timersRef = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const toast = useCallback(
    (kind: ToastKind, message: string) => {
      const normalized = message.trim();
      if (!normalized) return;
      const id = ++nextIdRef.current;
      setItems((current) => [
        ...current,
        { id, kind, message: normalized },
      ].slice(-MAX_VISIBLE_TOASTS));
      const timer = setTimeout(() => dismiss(id), TOAST_DURATION_MS);
      timersRef.current.set(id, timer);
    },
    [dismiss],
  );

  useEffect(
    () => () => {
      timersRef.current.forEach((timer) => clearTimeout(timer));
      timersRef.current.clear();
    },
    [],
  );

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
      <div className="toast-viewport" data-testid="toast-viewport" aria-live="polite">
        {items.map((item) => (
          <div
            key={item.id}
            className={`toast toast-${item.kind}`}
            data-testid={`toast-${item.kind}`}
            role={item.kind === "error" ? "alert" : "status"}
          >
            <span className="toast-message">{item.message}</span>
            <button
              type="button"
              className="toast-close"
              aria-label="关闭提示"
              title="关闭提示"
              onClick={() => dismiss(item.id)}
            >
              <X size={16} aria-hidden="true" />
            </button>
          </div>
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
