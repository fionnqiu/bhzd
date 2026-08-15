import { forwardRef, type ButtonHTMLAttributes } from "react";

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** 无障碍名（图标按钮无文字，必须提供） */
  "aria-label": string;
}

/** 纯图标按钮：表格行操作、弹窗/抽屉关闭等密集布局。 */
const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  function IconButton({ className, children, ...rest }, ref) {
    return (
      <button
        ref={ref}
        className={["icon-btn", className ?? ""].filter(Boolean).join(" ")}
        {...rest}
      >
        {children}
      </button>
    );
  },
);

export default IconButton;
