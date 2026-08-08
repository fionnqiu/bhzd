import { forwardRef, type TextareaHTMLAttributes } from "react";

export interface TextareaProps
  extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean;
}

/** 多行输入（目标描述、驳回意见、提示词模板等）。 */
const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  function Textarea({ invalid = false, className, ...rest }, ref) {
    return (
      <textarea
        ref={ref}
        className={["textarea", invalid ? "textarea-error" : "", className ?? ""]
          .filter(Boolean)
          .join(" ")}
        {...rest}
      />
    );
  },
);

export default Textarea;
