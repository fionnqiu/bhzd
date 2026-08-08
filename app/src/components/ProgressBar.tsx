export interface ProgressBarProps {
  /** 0..1 或 0..100（自动归一：>1 视为百分数） */
  value: number;
  /** 颜色语义：默认主色； mastery 场景建议按分数档位传色 */
  tone?: "primary" | "success" | "warning" | "danger";
}

/** 进度条（任务进度、管线进度）。 */
export default function ProgressBar({ value, tone = "primary" }: ProgressBarProps) {
  const percent = Math.max(0, Math.min(100, value > 1 ? value : value * 100));
  return (
    <div
      className="progress"
      role="progressbar"
      aria-valuenow={Math.round(percent)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={["progress-bar", tone !== "primary" ? `progress-bar-${tone}` : ""]
          .filter(Boolean)
          .join(" ")}
        // Scaling a full-width fill stays on the compositor and avoids a layout
        // recalculation whenever live or saved progress changes.
        style={{ "--progress-scale": percent / 100 } as CSSProperties}
      />
    </div>
  );
}
import type { CSSProperties } from "react";
