import PageHeader from "./PageHeader";
import Card from "./Card";

export interface PlaceholderPageProps {
  /** 页面中文名（与导航一致） */
  title: string;
  /** 该页将承载的功能说明（给后续实现者与评审看的范围锚点） */
  description: string;
}

/**
 * 占位页（F0 骨架专用）。
 *
 * 为什么做成组件：27 个业务页面在骨架阶段只是"标题 + 说明"的桩，
 * 统一渲染保证桩页形态一致；后续波次（F1-F4）**整文件替换**对应页面
 * 文件即可，无需触碰路由与本组件。
 */
export default function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  return (
    <div>
      <PageHeader title={title} sub={description} />
      <Card>
        <div className="empty-state">
          <div className="empty-state-title">模块建设中</div>
          <p className="empty-state-hint">
            该页面将在后续迭代中实现，当前为骨架占位。
          </p>
        </div>
      </Card>
    </div>
  );
}
