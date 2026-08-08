import type { LucideIcon } from "lucide-react";

export interface QuickCardProps {
  icon: LucideIcon;
  title: string;
  description: string;
  onClick: () => void;
}

/**
 * 欢迎态快捷入口卡（PRD-01 §3.3）。
 * 用 <button> 而非 <a>：点击触发的是动作（发运行/填模板/开上传），不是导航。
 */
export default function QuickCard({ icon: Icon, title, description, onClick }: QuickCardProps) {
  return (
    <button type="button" className="quick-card" onClick={onClick}>
      <span className="quick-card-icon" aria-hidden>
        <Icon size={20} />
      </span>
      <span className="quick-card-title">{title}</span>
      <span className="quick-card-desc">{description}</span>
    </button>
  );
}
