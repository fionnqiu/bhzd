import type { ReactNode } from "react";

export interface EmptyStateProps {
  title: string;
  /** 引导文案：告诉用户下一步能做什么（PRD 空态必须有引导） */
  hint?: string;
  /** 引导操作（按钮/链接） */
  action?: ReactNode;
}

/**
 * 空态（无插画版）：列表/面板无数据时的占位。
 * 不用图片是刻意的——教学产品空态重在引导动作，插画只增加加载成本。
 */
export default function EmptyState({ title, hint, action }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <div className="empty-state-title">{title}</div>
      {hint ? <p className="empty-state-hint">{hint}</p> : null}
      {action}
    </div>
  );
}
