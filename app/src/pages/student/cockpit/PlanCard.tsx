import type { PlanStep } from "../../../api/types";
import { AgentTaskList } from "../../../components";

/**
 * Render a server-issued plan inside the execution record rather than as a
 * second card. The plan is only shown after a real `plan.updated` event, so it
 * communicates an observable checklist instead of inferred model intent.
 */
export default function ExecutionPlan({ steps }: { steps: PlanStep[] }) {
  if (steps.length === 0) return null;

  // The shared list is deliberately fed only from `plan.updated` data, never
  // from a generated rationale, so its collapse control remains learner-safe.
  return <AgentTaskList steps={steps} title="今天的练习路径" testId="execution-plan" />;
}
