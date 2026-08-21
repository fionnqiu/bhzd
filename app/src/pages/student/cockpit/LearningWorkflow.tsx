/**
 * 学习任务业务流程轨道。
 *
 * ActivityTimeline 负责展示安全的执行事件；这里把同一批事件翻译成学生
 * 能直接理解的业务阶段。只在检测到任务草稿或任务域工具时显示，避免普通
 * 问答被误标成学习任务。历史消息使用持久化活动和草稿投影重建同一条轨道。
 */
import { CheckCircle2, CircleAlert, CircleDashed, Loader2, ShieldCheck } from "lucide-react";
import type { Confirmation, PlanStep, TaskDraft } from "../../../api/types";
import type { ActivityEntry, CockpitStatus } from "./types";

type WorkflowStepStatus = "pending" | "running" | "completed" | "waiting" | "failed";

interface WorkflowStep {
  id: string;
  title: string;
  status: WorkflowStepStatus;
  detail?: string;
}

const TASK_TOOLS = new Set(["learning.task.auto_create", "task.create", "task.preview"]);

const FOLLOW_UP_TOOLS = new Set(["learning.exercise.review", "learning.mastery.sync"]);

function latestToolStatus(
  activities: ActivityEntry[],
  tools: Set<string>,
): ActivityEntry | undefined {
  return [...activities]
    .filter((activity) => !!activity.tool && tools.has(activity.tool))
    .sort((left, right) => (left.eventSeq ?? left.seq) - (right.eventSeq ?? right.seq))
    .at(-1);
}

function isActive(status: CockpitStatus | undefined): boolean {
  return status === "planning" || status === "tool_running" || status === "awaiting_confirmation";
}

function stepStatusFromActivity(activity: ActivityEntry | undefined): WorkflowStepStatus {
  if (!activity) return "pending";
  return activity.status;
}

function stepIcon(status: WorkflowStepStatus) {
  if (status === "failed") return CircleAlert;
  if (status === "completed") return CheckCircle2;
  if (status === "waiting") return ShieldCheck;
  if (status === "running") return Loader2;
  return CircleDashed;
}

function buildSteps({
  activities,
  planSteps = [],
  draft,
  confirmation,
  runStatus,
  live,
}: LearningWorkflowProps): WorkflowStep[] | null {
  const taskActivity = latestToolStatus(activities, TASK_TOOLS);
  const followUpActivity = latestToolStatus(activities, FOLLOW_UP_TOOLS);
  const hasTaskSignal =
    !!draft ||
    confirmation?.action_type === "task.create" ||
    planSteps.some((step) => !!step.tool && TASK_TOOLS.has(step.tool)) ||
    activities.some((activity) => !!activity.tool && TASK_TOOLS.has(activity.tool));

  if (!hasTaskSignal) return null;

  const hasActivity = activities.length > 0 || planSteps.length > 0 || !!draft;
  const taskFailed = taskActivity?.status === "failed" || runStatus === "failed";
  const goalStatus: WorkflowStepStatus = taskFailed
    ? "failed"
    : draft || hasActivity
      ? "completed"
      : isActive(runStatus)
        ? "running"
        : "pending";
  const planStatus: WorkflowStepStatus = taskFailed
    ? "failed"
    : draft || planSteps.length > 0 || activities.some((activity) => activity.stage === "planning")
      ? "completed"
      : isActive(runStatus)
        ? "running"
        : "pending";
  const contentStatus: WorkflowStepStatus = draft
    ? "completed"
    : taskActivity
      ? stepStatusFromActivity(taskActivity)
      : taskFailed
        ? "failed"
        : isActive(runStatus)
          ? "running"
          : "pending";
  const waitingStatus: WorkflowStepStatus =
    draft?.status === "synced"
      ? "completed"
      : confirmation || draft?.status === "draft"
        ? "waiting"
        : taskActivity?.status === "failed" || runStatus === "failed"
          ? "failed"
          : "pending";
  const createdStatus: WorkflowStepStatus =
    draft?.status === "synced"
      ? "completed"
      : taskActivity?.status === "completed" && taskActivity.tool !== "task.preview"
        ? "completed"
        : taskFailed
          ? "failed"
          : "pending";

  const steps: WorkflowStep[] = [
    { id: "goal", title: "记录学习目标", status: goalStatus },
    { id: "plan", title: "制定学习计划", status: planStatus },
    {
      id: "content",
      title: "生成知识点与练习",
      status: contentStatus,
      detail: draft ? `已生成 ${draft.cards.length} 张任务卡` : undefined,
    },
    {
      id: "confirm",
      title: "等待你的确认",
      status: waitingStatus,
      detail: waitingStatus === "waiting" ? "确认后才会写入学习任务" : undefined,
    },
    { id: "created", title: "任务已创建", status: createdStatus },
  ];

  // 评分和掌握度同步只有在后端确实发出对应工具事件后才显示，避免给学生
  // 暗示尚未发生的自动操作；这也让历史回放保持事件事实而不是 UI 推测。
  if (followUpActivity) {
    steps.push({
      id: "mastery",
      title: "评分并同步掌握度",
      status: stepStatusFromActivity(followUpActivity),
      detail: followUpActivity.status === "completed" ? "仅使用成功评分的练习结果" : undefined,
    });
  }

  // A historical task draft is not a live execution even when its originating
  // run has no terminal status in the old conversation projection.
  if (!live && draft?.status === "synced") {
    for (const step of steps) {
      if (step.id !== "mastery") step.status = "completed";
    }
  }
  return steps;
}

export interface LearningWorkflowProps {
  activities: ActivityEntry[];
  planSteps?: PlanStep[];
  draft?: TaskDraft | null;
  confirmation?: Confirmation | null;
  runStatus?: CockpitStatus;
  live?: boolean;
}

export default function LearningWorkflow({
  activities,
  planSteps = [],
  draft = null,
  confirmation = null,
  runStatus,
  live = true,
}: LearningWorkflowProps) {
  const steps = buildSteps({
    activities,
    planSteps,
    draft,
    confirmation,
    runStatus,
    live,
  });
  if (!steps) return null;

  const completedCount = steps.filter((step) => step.status === "completed").length;
  const current = steps.find((step) => step.status === "running" || step.status === "waiting");
  const title = current
    ? current.title
    : completedCount === steps.length
      ? "学习任务已创建"
      : live
        ? "正在处理学习任务"
        : "学习任务流程";

  return (
    <section
      className="learning-workflow"
      aria-label="学习任务生成进度"
      data-testid="learning-workflow"
      data-status={current?.status ?? (completedCount === steps.length ? "completed" : "pending")}
    >
      <header className="learning-workflow-header">
        <span className="learning-workflow-heading">学习任务流程</span>
        <strong>{title}</strong>
        <span className="learning-workflow-count">
          {completedCount}/{steps.length} 已完成
        </span>
      </header>
      <ol className={`learning-workflow-track learning-workflow-track-${steps.length}`}>
        {steps.map((step, index) => {
          const Icon = stepIcon(step.status);
          return (
            <li
              className={`learning-workflow-step learning-workflow-step-${step.status}`}
              key={step.id}
              data-testid={`learning-workflow-step-${step.id}`}
            >
              <span className="learning-workflow-marker" aria-hidden="true">
                <Icon size={15} />
              </span>
              <span className="learning-workflow-step-copy">
                <span className="learning-workflow-step-title">{step.title}</span>
                {step.detail ? (
                  <span className="learning-workflow-step-detail">{step.detail}</span>
                ) : null}
              </span>
              {index < steps.length - 1 ? (
                <span className="learning-workflow-connector" aria-hidden="true" />
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
