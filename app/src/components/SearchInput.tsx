import { useEffect, useRef, useState } from "react";
import Input from "./Input";

export interface SearchInputProps {
  /** 受控值 */
  value: string;
  /** 输入变化（本地受控） */
  onChange: (value: string) => void;
  /** 防抖后触发搜索（通常接请求）；不传则只走 onChange */
  /** The effect-owned signal lets an API-backed search stop when its debounce owner is replaced. */
  onSearch?: (value: string, signal?: AbortSignal) => void;
  placeholder?: string;
  /** 防抖毫秒数（默认 300） */
  debounceMs?: number;
}

/**
 * 搜索输入框（防抖）。
 * 防抖而不是回车触发：资料库/用户列表等页面输入即筛选是 PRD 交互预期，
 * 同时避免每个按键都打一次请求。
 */
export default function SearchInput({
  value,
  onChange,
  onSearch,
  placeholder = "搜索…",
  debounceMs = 300,
}: SearchInputProps) {
  const [inner, setInner] = useState(value);
  const onSearchRef = useRef(onSearch);
  const pendingSearchRef = useRef(false);
  const hasSearch = Boolean(onSearch);
  onSearchRef.current = onSearch;

  // 外部值变化（如清空筛选）时同步内部态
  useEffect(() => setInner(value), [value]);

  useEffect(() => {
    if (!pendingSearchRef.current || !onSearchRef.current) return;
    // The timer and request share a controller so a new query cannot leave stale work in flight.
    const controller = new AbortController();
    const timer = setTimeout(() => {
      pendingSearchRef.current = false;
      onSearchRef.current?.(inner, controller.signal);
    }, debounceMs);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [inner, debounceMs, hasSearch]);

  return (
    <Input
      type="search"
      value={inner}
      placeholder={placeholder}
      onChange={(e) => {
        // Only user edits should start a request; parent-driven value sync is display-only.
        pendingSearchRef.current = true;
        setInner(e.target.value);
        onChange(e.target.value);
      }}
    />
  );
}
