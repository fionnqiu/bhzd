import Button from "./Button";

export interface PaginationProps {
  /** 当前偏移（对应后端 ?offset） */
  offset: number;
  /** 每页条数（对应后端 ?limit） */
  limit: number;
  /** 总条数（后端分页响应的 total） */
  total: number;
  onChange: (offset: number) => void;
}

/**
 * 分页条。契约是 limit/offset（蓝图 §4），不是页码——页码只作展示，
 * 回调一律给 offset，页面直接拼进请求参数即可。
 */
export default function Pagination({ offset, limit, total, onChange }: PaginationProps) {
  if (total <= 0) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  return (
    <div className="flex items-center justify-between mt-4">
      <span className="text-sm text-secondary">
        共 {total} 条 · 第 {page} / {pages} 页
      </span>
      <div className="flex gap-2">
        <Button
          variant="secondary"
          size="sm"
          disabled={offset <= 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          上一页
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={offset + limit >= total}
          onClick={() => onChange(offset + limit)}
        >
          下一页
        </Button>
      </div>
    </div>
  );
}
