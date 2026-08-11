import { useEffect, useState } from "react";
import Button from "./Button";
import Input from "./Input";
import Select from "./Select";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100].map((size) => ({
  value: String(size),
  label: `${size} 条/页`,
}));

export interface PaginationProps {
  /** 当前偏移（对应后端 ?offset） */
  offset: number;
  /** 每页条数（对应后端 ?limit） */
  limit: number;
  /** 总条数（后端分页响应的 total） */
  total: number;
  onChange: (offset: number) => void;
  /** 由页面接收新的每页条数并重置 offset，避免请求参数与展示脱节。 */
  onLimitChange?: (limit: number) => void;
}

/**
 * 分页条。契约是 limit/offset（蓝图 §4），不是页码——页码只作展示，
 * 回调一律给 offset，页面直接拼进请求参数即可。
 */
export default function Pagination({ offset, limit, total, onChange, onLimitChange }: PaginationProps) {
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  const [pageInput, setPageInput] = useState(String(page));

  // 外部翻页或页大小改变后同步输入框，防止用户看到过期页码。
  useEffect(() => {
    setPageInput(String(page));
  }, [page]);

  const jumpToPage = () => {
    const target = Number(pageInput);
    if (!Number.isInteger(target) || target < 1 || target > pages) {
      setPageInput(String(page));
      return;
    }
    onChange((target - 1) * limit);
  };

  if (total <= 0) return null;

  return (
    <div className="flex items-center justify-between gap-3 mt-4" style={{ flexWrap: "wrap" }}>
      <span className="text-sm text-secondary">
        共 {total} 条 · 第 {page} / {pages} 页
      </span>
      <div className="flex items-center gap-2" style={{ flexWrap: "wrap" }}>
        {onLimitChange ? (
          <div style={{ width: 140 }}>
            <Select
              aria-label="每页显示条数"
              className="pagination-page-size"
              value={String(limit)}
              options={PAGE_SIZE_OPTIONS}
              onChange={(event) => onLimitChange(Number(event.target.value))}
            />
          </div>
        ) : null}
        <form
          className="flex items-center gap-2"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            jumpToPage();
          }}
        >
          <Input
            aria-label="跳转到第几页"
            className="pagination-page-input"
            type="number"
            inputMode="numeric"
            min={1}
            max={pages}
            value={pageInput}
            onChange={(event) => setPageInput(event.target.value)}
            style={{ width: 76 }}
          />
          <Button type="submit" variant="secondary" size="sm">
            跳转
          </Button>
        </form>
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
