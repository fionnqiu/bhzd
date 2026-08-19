import { useEffect, useRef, type ReactNode } from "react";
import { animate, type AnimationPlaybackControls } from "motion";
import IconButton from "./IconButton";
import { isTopmostFocusTrap, useFocusTrap } from "./useFocusTrap";
import { usePresence, useReducedMotion } from "./usePresence";

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

/* ------------------------------------------------------------------ *
 * iOS 式拖拽关闭（参照 Apple《Designing Fluid Interfaces》）
 * - 1:1 跟踪：面板跟手，不吸附中心；10px 迟滞后才确认拖拽意图
 * - 速度交接：松手速度直接作为 spring 初速度，拖拽与动画之间无接缝
 * - 动量投影：按指数衰减投影落点决定去留，而不是看松手位置
 * - 橡皮筋：反向拖过停靠边时施加渐进阻力，不做硬截止
 * - 可中断：spring 进行中再次按下，从当前屏幕位置接管，不回跳
 * ------------------------------------------------------------------ */

/** Apple 公开示例里的动量投影：指数衰减，d≈0.998 接近滚动手感 */
function projectMomentum(initialVelocity: number, decelerationRate = 0.998): number {
  return ((initialVelocity / 1000) * decelerationRate) / (1 - decelerationRate);
}

/** 越过边界后的渐进阻力：拖得越远，面板跟随得越少 */
function rubberband(overshoot: number, dimension: number, constant = 0.55): number {
  return (overshoot * dimension * constant) / (dimension + constant * Math.abs(overshoot));
}

/** 拖拽确认前的位移迟滞，避免把点按误判为拖拽 */
const DRAG_HYSTERESIS_PX = 10;
/** 投影落点超过面板宽度该比例即判定为“甩出去关闭” */
const DISMISS_PROJECTED_RATIO = 0.35;

interface DragSample {
  x: number;
  t: number;
}

interface DragState {
  pointerId: number;
  startClientX: number;
  /** 确认拖拽那一刻的位移（迟滞内的路程不计入手势） */
  commitDx: number;
  committed: boolean;
  /** 确认拖拽时面板的屏幕位移（抓住动画中段也能无跳变接管） */
  baseVisualX: number;
  samples: DragSample[];
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
  const reducedMotion = useReducedMotion();
  const panelRef = useRef<HTMLElement>(null);
  const dragRef = useRef<DragState | null>(null);
  /** 进行中的回弹/关闭弹簧：再次按下时必须能停掉它（可中断性） */
  const flightRef = useRef<AnimationPlaybackControls | null>(null);
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

  // 卸载时停掉可能仍在运行的回弹/关闭 spring，避免操作已卸载的节点
  useEffect(() => {
    return () => {
      flightRef.current?.stop();
      flightRef.current = null;
      dragRef.current = null;
    };
  }, []);

  // 新一轮打开：清掉拖拽关闭留下的内联状态，恢复 CSS 动画驱动
  useEffect(() => {
    const panel = panelRef.current;
    if (!panel || !open) return;
    delete panel.dataset.dragDismissed;
    panel.style.transform = "";
    panel.style.animation = "";
    panel.style.opacity = "";
  }, [open, motionState]);

  useFocusTrap(panelRef, isPresent);

  /** 沿关闭轴的屏幕位移：停靠时为 0，向关闭方向拖为正（左右抽屉通用） */
  const visualX = (panel: HTMLElement): number => {
    const rect = panel.getBoundingClientRect();
    return side === "right" ? rect.right - window.innerWidth : -rect.left;
  };

  const overlayOf = (panel: HTMLElement): HTMLElement | null =>
    panel.parentElement?.querySelector<HTMLElement>(".drawer-overlay") ?? null;

  const handleDragStart = (e: React.PointerEvent<HTMLElement>) => {
    // 只响应主指针；关闭按钮等交互件不参与拖拽
    if (e.button !== 0 || motionState !== "open") return;
    if ((e.target as HTMLElement).closest("button, a")) return;
    const panel = panelRef.current;
    if (!panel) return;

    // 中断正在进行的回弹/关闭 spring——从当前屏幕位置接管，而不是从目标值重来
    flightRef.current?.stop();
    flightRef.current = null;
    delete panel.dataset.dragDismissed;
    panel.style.opacity = "";
    dragRef.current = {
      pointerId: e.pointerId,
      startClientX: e.clientX,
      commitDx: 0,
      committed: false,
      baseVisualX: 0,
      samples: [{ x: e.clientX, t: performance.now() }],
    };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const handleDragMove = (e: React.PointerEvent<HTMLElement>) => {
    const drag = dragRef.current;
    const panel = panelRef.current;
    if (!drag || !panel || e.pointerId !== drag.pointerId) return;

    const dx = e.clientX - drag.startClientX;
    if (!drag.committed) {
      // 迟滞：位移足够才确认这是拖拽，并记住面板此刻的屏幕位置
      if (Math.abs(dx) < DRAG_HYSTERESIS_PX) return;
      drag.committed = true;
      drag.commitDx = dx;
      drag.baseVisualX = visualX(panel);
      // CSS 进场/回弹动画会覆盖内联样式，接管前先停掉它
      panel.style.animation = "none";
    }

    const dir = side === "right" ? 1 : -1;
    let x = drag.baseVisualX + (dx - drag.commitDx) * dir;
    // 反向拖过停靠边：橡皮筋阻力而不是硬停（“响应还在，但到底了”）
    if (x < 0) x = -rubberband(-x, panel.offsetWidth);
    panel.style.transform = `translateX(${dir * x}px)`;

    // 遮罩随手势同步变淡：因果反馈必须与动作同帧
    const overlay = overlayOf(panel);
    if (overlay) overlay.style.opacity = String(Math.max(0, 1 - x / panel.offsetWidth));

    drag.samples.push({ x: e.clientX, t: performance.now() });
    if (drag.samples.length > 6) drag.samples.shift();
  };

  const handleDragEnd = (e: React.PointerEvent<HTMLElement>) => {
    const drag = dragRef.current;
    const panel = panelRef.current;
    if (!drag || !panel || e.pointerId !== drag.pointerId) return;
    dragRef.current = null;
    if (!drag.committed) return;

    const dir = side === "right" ? 1 : -1;
    const width = panel.offsetWidth;
    const x = visualX(panel);

    // 从最近 100ms 的采样估算松手速度（px/s，沿关闭轴为正）
    const now = performance.now();
    const recent = drag.samples.filter((s) => now - s.t <= 100);
    const first = recent[0] ?? drag.samples[0];
    const last = drag.samples[drag.samples.length - 1];
    const dt = Math.max(1, last.t - first.t);
    const velocity = ((last.x - first.x) / dt) * 1000 * dir;

    const overlay = overlayOf(panel);
    const clearInline = () => {
      panel.style.transform = "";
      panel.style.animation = "";
      panel.style.opacity = "";
      if (overlay) overlay.style.opacity = "";
    };

    // 动量投影决定去向：甩得快即使没过半也关，慢拖过半也关
    const projected = x + projectMomentum(velocity);
    const shouldDismiss = projected > width * DISMISS_PROJECTED_RATIO || x > width * 0.6;

    if (shouldDismiss) {
      if (reducedMotion) {
        // 减弱动效：不做弹簧飞行，直接走标准关闭路径
        clearInline();
        onClose();
        return;
      }
      // 标记后 CSS 退出动画停播，避免与 JS 弹簧重复驱动同一变换
      panel.dataset.dragDismissed = "true";
      // 速度交接：关闭动画从指尖速度继续，无接缝
      const flight = animate(panel, { x: dir * (width + 32), opacity: 0 }, {
        type: "spring",
        bounce: 0,
        duration: 0.45,
        velocity,
      });
      flightRef.current = flight;
      // 若飞行途中被再次按下接管（flightRef 被清空），就不要再触发关闭
      void flight.then(() => {
        if (flightRef.current === flight) {
          flightRef.current = null;
          onClose();
        }
      });
      return;
    }

    if (reducedMotion) {
      clearInline();
      return;
    }
    // 回弹：带一点 bounce，因为手势本身携带动量（Apple：有动量才允许过冲）
    if (overlay) overlay.style.opacity = "";
    const snapBack = animate(panel, { x: 0 }, {
      type: "spring",
      bounce: 0.25,
      duration: 0.5,
      velocity,
    });
    flightRef.current = snapBack;
    void snapBack.then(() => {
      if (flightRef.current === snapBack) {
        flightRef.current = null;
        clearInline();
      }
    });
  };

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
        {/* 头部即拖拽手柄：向关闭方向拖动可甩出关闭（iOS sheet 手势） */}
        <div
          className="drawer-header"
          onPointerDown={handleDragStart}
          onPointerMove={handleDragMove}
          onPointerUp={handleDragEnd}
          onPointerCancel={handleDragEnd}
        >
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
