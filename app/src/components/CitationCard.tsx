import type { Citation } from "../api/types";
import Tag from "./Tag";

export interface CitationCardProps {
  citation: Citation;
  /** 序号（引用列表中的展示编号，从 1 开始） */
  index?: number;
  /** 点击行为（跳转资料详情/预览），不传则纯展示 */
  onClick?: () => void;
}

/**
 * 引用来源卡（PRD-01 §8）：文档名 + 章节 + 页码 + 版本。
 * 学生端 DTO 不含 chunk_id/上传人（PRD-06 §4.5），本组件也不接收这些字段——
 * 内部检索结果含有 chunk_id 时应使用专用 DTO 展示，不要复用本组件。
 */
export default function CitationCard({ citation, index, onClick }: CitationCardProps) {
  const pages =
    citation.page_start != null
      ? citation.page_end != null && citation.page_end !== citation.page_start
        ? `第 ${citation.page_start}-${citation.page_end} 页`
        : `第 ${citation.page_start} 页`
      : null;
  const body = (
    <>
      <div className="citation-card-title">
        {index !== undefined ? `[${index}] ` : ""}
        {citation.title}
      </div>
      <div className="citation-card-meta">
        {[
          citation.section_title ? `章节：${citation.section_title}` : null,
          pages,
          `版本：v${citation.version}`,
        ]
          .filter(Boolean)
          .join(" · ")}
      </div>
    </>
  );
  if (onClick) {
    return (
      <button type="button" className="citation-card w-full" onClick={onClick}>
        {body}
      </button>
    );
  }
  return (
    <div className="citation-card">
      {body}
      <div className="mt-2">
        <Tag>相关度 {citation.score.toFixed(2)}</Tag>
      </div>
    </div>
  );
}
