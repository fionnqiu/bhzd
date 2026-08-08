import type { ReactNode } from "react";

export interface PageHeaderProps {
  title: string;
  /** 副标题：一句话说明页面用途（中文） */
  sub?: string;
  /** 右侧操作区（主按钮/筛选器） */
  actions?: ReactNode;
}

/** 页面头部：标题 + 说明 + 操作，所有业务页面统一入口。 */
export default function PageHeader({ title, sub, actions }: PageHeaderProps) {
  return (
    <div className="page-header">
      <div>
        <h1 className="page-header-title">{title}</h1>
        {sub ? <p className="page-header-sub">{sub}</p> : null}
      </div>
      {actions ? <div className="page-header-actions">{actions}</div> : null}
    </div>
  );
}
