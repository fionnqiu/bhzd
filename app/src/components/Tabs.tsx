export interface TabItem {
  key: string;
  label: string;
}

export interface TabsProps {
  tabs: TabItem[];
  active: string;
  onChange: (key: string) => void;
  /** Optional accessible name when a page exposes more than one tab group. */
  ariaLabel?: string;
}

/**
 * 页签切换。只管理"哪个激活"的展示逻辑，面板内容仍由页面按 active
 * 条件渲染——页签数量少（2-5 个），不需要路由级拆分。
 */
export default function Tabs({ tabs, active, onChange, ariaLabel }: TabsProps) {
  return (
    <div className="tabs" role="tablist" aria-label={ariaLabel}>
      {tabs.map((tab) => (
        <button
          key={tab.key}
          role="tab"
          aria-selected={tab.key === active}
          className={["tab", tab.key === active ? "active" : ""].filter(Boolean).join(" ")}
          title={tab.label}
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
