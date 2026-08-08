import { forwardRef, type InputHTMLAttributes } from "react";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** 校验失败样式（配合 Field 的 error 文本） */
  invalid?: boolean;
}

/** 文本输入框。通常与 Field 组合使用以获得 label/error 布局。 */
const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { invalid = false, className, ...rest },
  ref,
) {
  return (
    <input
      ref={ref}
      className={["input", invalid ? "input-error" : "", className ?? ""]
        .filter(Boolean)
        .join(" ")}
      {...rest}
    />
  );
});

export default Input;
