import { useEffect, useRef, type ReactNode } from "react";
import IconButton from "./IconButton";
import { isTopmostFocusTrap, useFocusTrap } from "./useFocusTrap";
import { usePresence } from "./usePresence";

export interface ModalProps {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  /** 底部操作区（通常放取消/确认按钮） */
  footer?: ReactNode;
  /** 宽版（表单较多或需要并排布局时） */
  large?: boolean;
  children: ReactNode;
}

/**
 * 模态对话框。
 * 实现说明：不用原生 <dialog> 是为了与现有 CSS 类/动画体系保持一致；
 * Esc 关闭在这里统一处理，遮罩点击关闭交给调用方决定（危险操作弹窗
 * 通常不希望误触关闭，故默认不开）。
 */
export default function Modal({
  open,
  title,
  onClose,
  footer,
  large = false,
  children,
}: ModalProps) {
  const { isPresent, motionState } = usePresence(open);
  const panelRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const retainedContentRef = useRef({ children, footer, large, title });

  // Parents often clear their selected record at the same time as `open`.
  // Retain the last render so the dialog never exits as an empty surface.
  if (open) retainedContentRef.current = { children, footer, large, title };
  const content = open ? { children, footer, large, title } : retainedContentRef.current;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && panelRef.current && isTopmostFocusTrap(panelRef.current)) {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open || !isPresent) return;
    const activeElement = document.activeElement;
    if (activeElement instanceof HTMLElement && activeElement !== panelRef.current) {
      returnFocusRef.current = activeElement;
    }
    panelRef.current?.focus({ preventScroll: true });
  }, [isPresent, open]);

  useEffect(() => {
    if (isPresent) return;
    const returnFocusTarget = returnFocusRef.current;
    returnFocusRef.current = null;
    if (returnFocusTarget?.isConnected) returnFocusTarget.focus({ preventScroll: true });
  }, [isPresent]);

  useFocusTrap(panelRef, isPresent);

  if (!isPresent) return null;
  return (
    <div className="overlay" data-motion-state={motionState} role="presentation">
      <div
        className={["modal", content.large ? "modal-lg" : ""].filter(Boolean).join(" ")}
        data-motion-state={motionState}
        data-focus-trap="active"
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={typeof content.title === "string" ? content.title : undefined}
        tabIndex={-1}
      >
        <div className="modal-header">
          <div className="modal-title">{content.title}</div>
          <IconButton aria-label="关闭" onClick={onClose}>
            ×
          </IconButton>
        </div>
        <div className="modal-body">{content.children}</div>
        {content.footer ? <div className="modal-footer">{content.footer}</div> : null}
      </div>
    </div>
  );
}
