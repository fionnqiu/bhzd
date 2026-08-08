import { cloneElement, isValidElement, useId, type ReactElement, type ReactNode } from "react";
import Input from "./Input";
import Select from "./Select";
import Textarea from "./Textarea";

export interface FieldProps {
  label: string;
  /** 必填标记（视觉上给红星，实际校验仍在提交逻辑里） */
  required?: boolean;
  /** 校验错误文本；存在时渲染并给控件加错误态 */
  error?: string;
  /** 辅助说明（格式要求、取值范围等） */
  hint?: string;
  children: ReactNode;
}

interface FieldControlProps {
  id?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean | "true" | "false";
  "aria-label"?: string;
  "aria-labelledby"?: string;
}

function isSingleFormControl(child: ReactNode): child is ReactElement<FieldControlProps> {
  return (
    isValidElement<FieldControlProps>(child) &&
    (child.type === Input ||
      child.type === Select ||
      child.type === Textarea ||
      child.type === "input" ||
      child.type === "select" ||
      child.type === "textarea")
  );
}

/**
 * 表单项容器：label + 控件 + hint/error。
 * 后端 422/400 返回的中文 message 应落到对应字段的 error 上，
 * 保持"错误出现在字段旁"的可读性（PRD 表单交互口径）。
 */
export default function Field({ label, required, error, hint, children }: FieldProps) {
  const fieldId = useId();
  const controlId = `${fieldId}-control`;
  const labelId = `${fieldId}-label`;
  const descriptionId = `${fieldId}-description`;
  const singleControl = isSingleFormControl(children);

  // Standard controls receive one stable label and description relationship in
  // this shared wrapper; complex field bodies keep their existing semantics.
  const control = singleControl
    ? cloneElement(children, {
        id: children.props.id ?? controlId,
        ...(children.props["aria-label"] || children.props["aria-labelledby"]
          ? {}
          : { "aria-labelledby": labelId }),
        ...(children.props["aria-describedby"] || !(error || hint)
          ? {}
          : { "aria-describedby": descriptionId }),
        ...(error && !children.props["aria-invalid"] ? { "aria-invalid": true } : {}),
      })
    : children;

  return (
    <div className="field">
      <label
        className="field-label"
        htmlFor={singleControl ? (children.props.id ?? controlId) : undefined}
        id={singleControl ? labelId : undefined}
      >
        {label}
        {required ? <span className="field-required">*</span> : null}
      </label>
      {control}
      {error ? (
        <span className="field-error-text" id={singleControl ? descriptionId : undefined}>
          {error}
        </span>
      ) : hint ? (
        <span className="field-hint" id={singleControl ? descriptionId : undefined}>
          {hint}
        </span>
      ) : null}
    </div>
  );
}
