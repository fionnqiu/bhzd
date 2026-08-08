import { forwardRef, type ButtonHTMLAttributes } from "react";
import Spinner from "./Spinner";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** 视觉变体：primary 主操作 / secondary 次操作 / ghost 弱操作 / danger 危险操作 */
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  /** 占满父容器（表单提交、窄栏操作） */
  block?: boolean;
  /** 提交中：禁用并显示 spinner，防重复点击产生重复写请求 */
  loading?: boolean;
}

/**
 * 通用按钮。所有写操作按钮在提交期间必须走 `loading` 而不是仅 disabled，
 * 让学生明确知道请求在进行中（PRD 交互反馈要求）。
 */
const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    size = "md",
    block = false,
    loading = false,
    disabled,
    className,
    children,
    ...rest
  },
  ref,
) {
  const classes = [
    "btn",
    `btn-${variant}`,
    size === "sm" ? "btn-sm" : "",
    size === "lg" ? "btn-lg" : "",
    block ? "btn-block" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button ref={ref} className={classes} disabled={disabled || loading} {...rest}>
      {loading ? <Spinner size={14} /> : null}
      {children}
    </button>
  );
});

export default Button;
