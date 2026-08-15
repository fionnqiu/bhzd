import { useEffect, useRef, useState, type ReactNode } from "react";
import Spinner from "./Spinner";

export interface Column<T> {
  /** 列键（也用作 React key 的一部分） */
  key: string;
  title: ReactNode;
  /** 单元格渲染；缺省取 row[key] */
  render?: (row: T, index: number) => ReactNode;
  /** 列宽提示（如 "120px" / "30%"） */
  width?: string;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  /** 行 key 提取（默认 row.id，后端 DTO 普遍有 id） */
  rowKey?: (row: T) => string;
  /** 空数据提示（null 结果请在上游先渲染 ErrorState/EmptyState） */
  empty?: ReactNode;
  /** 加载中：渲染 spinner 行而不清空已有数据，避免刷新时闪空。 */
  loading?: boolean;
  /** Optional class name for the scroll viewport when a page needs a local surface treatment. */
  wrapperClassName?: string;
  /** Names the table scroll region so identical table landmarks stay distinguishable. */
  ariaLabel: string;
}

/**
 * 通用数据表。只负责展示——分页/筛选状态由页面持有并通过 props 驱动，
 * 保持组件无状态以便各页面按自己的 API 参数组织请求。
 */
export default function DataTable<T extends object>({
  columns,
  rows,
  rowKey,
  empty = "暂无数据",
  loading = false,
  wrapperClassName,
  ariaLabel,
}: DataTableProps<T>) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const tableRef = useRef<HTMLTableElement>(null);
  const [hasHorizontalOverflow, setHasHorizontalOverflow] = useState(false);

  useEffect(() => {
    const viewport = viewportRef.current;
    const table = tableRef.current;
    if (!viewport || !table) return undefined;

    // Only overflowed tables need a keyboard stop; observe both surfaces as data and layout can change their widths.
    const syncHorizontalOverflow = () => {
      setHasHorizontalOverflow(viewport.scrollWidth > viewport.clientWidth);
    };

    syncHorizontalOverflow();
    window.addEventListener("resize", syncHorizontalOverflow);

    if (typeof ResizeObserver === "undefined") {
      return () => window.removeEventListener("resize", syncHorizontalOverflow);
    }

    const resizeObserver = new ResizeObserver(syncHorizontalOverflow);
    resizeObserver.observe(viewport);
    resizeObserver.observe(table);

    return () => {
      window.removeEventListener("resize", syncHorizontalOverflow);
      resizeObserver.disconnect();
    };
  }, [columns, rows]);

  return (
    <div
      ref={viewportRef}
      className={["table-wrap", wrapperClassName].filter(Boolean).join(" ")}
      role="region"
      aria-label={ariaLabel}
      tabIndex={hasHorizontalOverflow ? 0 : undefined}
    >
      <table ref={tableRef} className="table">
        {/* Colgroup keeps declared column widths aligned across headers and data cells. */}
        <colgroup>
          {columns.map((col) => (
            <col key={col.key} style={col.width ? { width: col.width } : undefined} />
          ))}
        </colgroup>
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} scope="col">
                {col.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            // Static reference rows do not always expose an id, so pages can provide rowKey instead.
            <tr key={rowKey ? rowKey(row) : ((row as { id?: string | number }).id ?? index)}>
              {columns.map((col) => (
                <td key={col.key}>
                  {col.render
                    ? col.render(row, index)
                    : ((row as Record<string, unknown>)[col.key] as ReactNode)}
                </td>
              ))}
            </tr>
          ))}
          {rows.length === 0 ? (
            <tr>
              <td className="table-empty" colSpan={columns.length}>
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <Spinner size={16} /> 加载中…
                  </span>
                ) : (
                  empty
                )}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
