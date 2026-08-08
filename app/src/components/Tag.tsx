import type { ReactNode } from "react";

/** 轻量标签：场景 id、数据类型、能力 id 等元信息的展示。 */
export default function Tag({ children }: { children: ReactNode }) {
  return <span className="tag">{children}</span>;
}
