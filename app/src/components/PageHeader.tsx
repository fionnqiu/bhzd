import { useEffect, useRef, type ReactNode } from "react";
import { PanelLeft } from "lucide-react";
import { useDesktopSidebar } from "../layouts/DesktopSidebarContext";

export interface PageHeaderProps {
  title: string;
  /** 副标题：一句话说明页面用途（中文） */
  sub?: string;
  /** 右侧操作区（主按钮/筛选器） */
  actions?: ReactNode;
}

/** 页面头部：标题 + 说明 + 操作，所有业务页面统一入口。 */
export default function PageHeader({ title, sub, actions }: PageHeaderProps) {
  const { showExpandControl, sidebarId, expandDesktopSidebar } = useDesktopSidebar();
  const expandControlRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // Collapsing removes the rail's trigger. Move focus to the replacement in
    // this header so keyboard users stay in the same visual control row.
    if (showExpandControl) expandControlRef.current?.focus({ preventScroll: true });
  }, [showExpandControl]);

  return (
    <div
      className={["page-header", showExpandControl ? "page-header-has-sidebar-expand" : ""]
        .filter(Boolean)
        .join(" ")}
    >
      {showExpandControl ? (
        <button
          type="button"
          className="icon-btn page-header-sidebar-expand"
          aria-label="展开导航"
          aria-controls={sidebarId}
          aria-expanded={false}
          title="展开导航"
          ref={expandControlRef}
          onClick={expandDesktopSidebar}
        >
          <PanelLeft size={20} aria-hidden />
        </button>
      ) : null}
      <div className="page-header-copy">
        <h1 className="page-header-title">{title}</h1>
        {sub ? <p className="page-header-sub">{sub}</p> : null}
      </div>
      {actions ? <div className="page-header-actions">{actions}</div> : null}
    </div>
  );
}
