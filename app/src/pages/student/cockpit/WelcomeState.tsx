/**
 * 学生工作台欢迎态。
 *
 * 欢迎态只提供目标的起点和继续入口；唯一真实的输入路径由 CockpitPage
 * 传入 Composer。这样快捷入口可以先让学生审阅目标，再决定是否发送。
 */
import {
  BookOpen,
  ClipboardCheck,
  FileText,
  ScanLine,
  Target,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

/** 快捷入口只能预填目标；上传是唯一需要直接打开文件选择器的例外。 */
export type QuickAction =
  { kind: "fill"; id: string; goal: string } | { kind: "upload"; id: "upload-diagnose" };

interface QuickLink {
  id: QuickAction["id"];
  icon: LucideIcon;
  label: string;
  action: QuickAction;
}

// Five primary starts deliberately mirror the approved workbench reference.
// Less-frequent routes remain available through the persistent student navigation.
const QUICK_LINKS: QuickLink[] = [
  {
    id: "text-intro",
    icon: FileText,
    label: "文本标注",
    action: { kind: "fill", id: "text-intro", goal: "我想学习文本标注入门" },
  },
  {
    id: "image-intro",
    icon: ScanLine,
    label: "图像标注",
    action: { kind: "fill", id: "image-intro", goal: "我想学习图像标注入门" },
  },
  {
    id: "upload-diagnose",
    icon: ClipboardCheck,
    label: "结果诊断",
    action: { kind: "upload", id: "upload-diagnose" },
  },
  {
    id: "weak-boost",
    icon: Target,
    label: "薄弱补强",
    action: { kind: "fill", id: "weak-boost", goal: "请按我的薄弱能力生成补强任务" },
  },
  {
    id: "rule-qa",
    icon: BookOpen,
    label: "规范问答",
    action: { kind: "fill", id: "rule-qa", goal: "请解释这条标注规范" },
  },
];

export interface WelcomeStateProps {
  /** 页面层决定预填或打开上传器，避免欢迎组件持有运行状态。 */
  onQuickAction: (action: QuickAction) => void;
  /** 由页面复用的唯一 Composer，视觉顺序严格位于 Hero 与快捷入口之间。 */
  composer: ReactNode;
  busy?: boolean;
}

export default function WelcomeState({ onQuickAction, composer, busy = false }: WelcomeStateProps) {
  return (
    <section className="welcome" data-testid="cockpit-welcome" aria-label="开始学习">
      <div className="welcome-hero">
        <div className="capability-mark" aria-hidden="true">
          {Array.from({ length: 27 }, (_, index) => (
            <span key={index} />
          ))}
        </div>
        <h1>标航智导</h1>
        <p>把学习目标交给指挥舱，生成清晰的练习路径、任务卡和诊断建议。</p>
      </div>

      {composer}

      <div className="welcome-quick-actions" aria-label="快捷入口">
        {QUICK_LINKS.map(({ id, icon: Icon, label, action }) => (
          <button
            key={id}
            type="button"
            className="welcome-quick-action"
            disabled={busy}
            onClick={() => onQuickAction(action)}
          >
            <Icon size={15} aria-hidden="true" />
            <span>{label}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
