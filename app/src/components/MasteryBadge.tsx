import type { MasteryStatus } from "../api/types";

/** 阈值与后端 mastery/service.py 保持一致：≥0.8 已掌握 / <0.4 待加强 */
export const MASTERED_THRESHOLD = 0.8;
export const WEAK_THRESHOLD = 0.4;

/** 分数 → 掌握度档位（v3.0 §7.3.3 三色口径；null = 暂无数据） */
export function masteryStatusOf(score: number | null | undefined): MasteryStatus | "none" {
  if (score === null || score === undefined) return "none";
  if (score >= MASTERED_THRESHOLD) return "mastered";
  if (score < WEAK_THRESHOLD) return "weak";
  return "beginner";
}

const LABELS: Record<string, string> = {
  mastered: "已掌握",
  weak: "待加强",
  beginner: "初学",
  none: "暂无数据",
};

export interface MasteryBadgeProps {
  /** 掌握度分数 0..1；null/undefined 表示暂无记录 */
  score: number | null | undefined;
  /** 是否显示百分比文本（默认显示） */
  showPercent?: boolean;
}

/**
 * 掌握度色块 + 百分比。
 * 颜色与图谱页节点配色同一口径（绿=已掌握/橙=待加强/红=初学），
 * 学生跨页面看到的颜色语义必须一致，否则会造成认知冲突。
 */
export default function MasteryBadge({ score, showPercent = true }: MasteryBadgeProps) {
  const status = masteryStatusOf(score);
  return (
    <span className="mastery-badge" title={LABELS[status]}>
      <span className={`mastery-dot mastery-dot-${status}`} />
      {showPercent ? (
        <span>
          {status === "none" ? LABELS.none : `${Math.round((score ?? 0) * 100)}%`}
        </span>
      ) : null}
      <span className="text-muted text-xs">{LABELS[status]}</span>
    </span>
  );
}
