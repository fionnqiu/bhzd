import { Ban, CheckCircle2, Circle, Loader2, PauseCircle, XCircle } from "lucide-react";
import { Card } from "../../../components";
import type { PlanStep } from "../../../api/types";

/**
 * Agent 计划卡（PRD-01 §3.5"计划中"态）。
 * 步骤状态来自 plan.updated 事件（orchestrator 的 pending/waiting/completed/failed），
 * 图标映射集中在此，新增状态默认按"待执行"兜住。
 */
const STEP_ICON: Record<string, { icon: typeof Circle; className: string; label: string }> = {
  pending: { icon: Circle, className: "plan-step-pending", label: "待执行" },
  running: { icon: Loader2, className: "plan-step-running", label: "进行中" },
  waiting: { icon: PauseCircle, className: "plan-step-waiting", label: "等待确认" },
  completed: { icon: CheckCircle2, className: "plan-step-done", label: "已完成" },
  failed: { icon: XCircle, className: "plan-step-failed", label: "失败" },
  // A cancelled write never ran; distinguish it from an execution failure.
  cancelled: { icon: Ban, className: "plan-step-cancelled", label: "已取消" },
};

export default function PlanCard({ steps }: { steps: PlanStep[] }) {
  if (steps.length === 0) return null;
  return (
    <Card title="执行计划" className="plan-card" data-testid="plan-card">
      <ol className="plan-steps">
        {steps.map((step) => {
          const meta = STEP_ICON[step.status] ?? STEP_ICON.pending;
          const Icon = meta.icon;
          return (
            <li key={step.id} className={`plan-step ${meta.className}`}>
              <Icon size={16} aria-label={meta.label} />
              <span>{step.title}</span>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
