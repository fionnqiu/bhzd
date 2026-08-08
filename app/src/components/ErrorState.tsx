import Button from "./Button";

export interface ErrorStateProps {
  /** 错误描述；缺省给通用文案。后端中文 message 直接传入即可 */
  message?: string;
  /** 重试回调（传入则显示重试按钮） */
  onRetry?: () => void;
}

/**
 * 加载失败态。
 * PRD-01 §3.5：失败页展示"原因 + 可操作下一步"，绝不暴露技术堆栈——
 * 因此只展示后端中文 message，不渲染 Error 对象细节。
 */
export default function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="empty-state">
      <div className="empty-state-title">加载失败</div>
      <p className="empty-state-hint">{message ?? "数据加载失败，请稍后重试"}</p>
      {onRetry ? (
        <Button variant="secondary" onClick={onRetry}>
          重试
        </Button>
      ) : null}
    </div>
  );
}
