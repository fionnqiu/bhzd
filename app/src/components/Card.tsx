import type { HTMLAttributes, ReactNode } from "react";

export interface CardProps
  extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  /** 卡片头（标题 + 右侧操作区）；不传则为纯内容卡 */
  title?: ReactNode;
  /** 头部右侧操作（按钮/链接） */
  actions?: ReactNode;
  /** 底部区（分页、次要操作） */
  footer?: ReactNode;
  /** 无 header 时是否给 body 加内边距（默认加） */
  padded?: boolean;
}

/** 内容卡片：页面信息分组的基础容器。 */
export default function Card({
  title,
  actions,
  footer,
  padded = true,
  className,
  children,
  ...rest
}: CardProps) {
  const hasHeader = title !== undefined || actions !== undefined;
  return (
    <div className={["card", className ?? ""].filter(Boolean).join(" ")} {...rest}>
      {hasHeader ? (
        <div className="card-header">
          <div className="card-title">{title}</div>
          {actions}
        </div>
      ) : null}
      <div className={hasHeader || padded ? "card-body" : undefined}>{children}</div>
      {footer ? <div className="card-footer">{footer}</div> : null}
    </div>
  );
}
