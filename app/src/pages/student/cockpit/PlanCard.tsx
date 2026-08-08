import { CheckCircle2, Circle, ClipboardList, Loader2, PauseCircle, XCircle } from "lucide-react";
import type { PlanStep } from "../../../api/types";

const STEP_ICON: Record<string, { icon: typeof Circle; className: string; label: string }> = {
  pending: { icon: Circle, className: "plan-step-pending", label: "待执行" },
  running: { icon: Loader2, className: "plan-step-running", label: "执行中" },
  completed: { icon: CheckCircle2, className: "plan-step-done", label: "已完成" },
  failed: { icon: XCircle, className: "plan-step-failed", label: "未完成" },
  waiting_confirmation: {
    icon: PauseCircle,
    className: "plan-step-waiting",
    label: "等待确认",
  },
};

/**
 * Render a server-issued plan inside the execution record rather than as a
 * second card. The plan is only shown after a real `plan.updated` event, so it
 * communicates an observable checklist instead of inferred model intent.
 */
export default function ExecutionPlan({ steps }: { steps: PlanStep[] }) {
  if (steps.length === 0) return null;

  return (
    <section className="agent-execution-plan" data-testid="execution-plan">
      <div className="agent-execution-plan-heading">
        <ClipboardList aria-hidden="true" size={16} />
        <span>今天的练习路径</span>
        <span className="agent-execution-plan-count">{steps.length} 项</span>
      </div>
      <ol className="plan-steps">
        {steps.map((step) => {
          const meta = STEP_ICON[step.status] ?? STEP_ICON.pending;
          const Icon = meta.icon;
          return (
            <li key={step.id} className={`plan-step ${meta.className}`}>
              <Icon size={15} aria-label={meta.label} />
              <span>{step.title}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
