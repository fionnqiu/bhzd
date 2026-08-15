import { useEffect, useRef, type ReactNode } from "react";
import IconButton from "./IconButton";
import { isTopmostFocusTrap, useFocusTrap } from "./useFocusTrap";
import { usePresence } from "./usePresence";

export interface DrawerProps {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  /** Optional persistent action area outside the drawer's scrollable content. */
  footer?: ReactNode;
  /** Lets form drawers opt into local layout rules without changing detail drawers. */
  bodyClassName?: string;
  footerClassName?: string;
  /**
   * The default keeps existing detail drawers unchanged. Cockpit panels can
   * opt into the opposite edge without introducing a second focus-trapped
   * surface implementation.
   */
  side?: "left" | "right";
}

/**
 * 右侧抽屉：图谱节点详情、工具结果"专注视图"（NF19 两级展示的第二级）
 * 等需要保留背景上下文的中等信息量内容。
 */
export default function Drawer({
  open,
  title,
  onClose,
  children,
  footer,
  bodyClassName,
  footerClassName,
  side = "right",
}: DrawerProps) {
  const { isPresent, motionState } = usePresence(open);
  const panelRef = useRef<HTMLElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const retainedContentRef = useRef<{
    children: ReactNode;
    title: ReactNode;
    footer: ReactNode;
  }>({ children, title, footer });

  // Detail drawers commonly clear their source object on close. Retaining the
  // previous content prevents the slide-out from becoming an empty surface.
  if (open) retainedContentRef.current = { children, title, footer };
  const content = open ? { children, title, footer } : retainedContentRef.current;

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
    <>
      <div
        className="drawer-overlay"
        data-motion-state={motionState}
        onClick={onClose}
        role="presentation"
      />
      <aside
        className={`drawer drawer-${side}`}
        data-motion-state={motionState}
        data-side={side}
        data-focus-trap="active"
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={typeof content.title === "string" ? content.title : undefined}
        tabIndex={-1}
      >
        <div className="drawer-header">
          <div className="drawer-title">{content.title}</div>
          <IconButton aria-label="关闭" onClick={onClose}>
            ×
          </IconButton>
        </div>
        <div className={["drawer-body", bodyClassName ?? ""].filter(Boolean).join(" ")}>
          {content.children}
        </div>
        {content.footer ? (
          <div className={["drawer-footer", footerClassName ?? ""].filter(Boolean).join(" ")}>
            {content.footer}
          </div>
        ) : null}
      </aside>
    </>
  );
}
