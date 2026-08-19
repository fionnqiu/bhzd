/**
 * 执行过程步骤流（PRD-01 §3.2/§3.5）。
 *
 * 以 plan.updated 下发的服务端计划为骨架，把工具调用生命周期归并成单一
 * 步骤列表：每步只呈现状态图标 + 服务端步骤标题，辅助信息（检索命中数、
 * 等待确认提示）作为次级行；没有计划的 run 退回扁平活动行。
 * 该组件是学生安全的生命周期投影：模型推理、提示词、原始工具载荷绝不进入。
 */
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleDashed,
  Loader2,
  ShieldCheck,
} from "lucide-react";
import type { PlanStep } from "../../../api/types";
import type { ActivityEntry, ActivityStage, ActivityStatus } from "./types";

/** 步骤可见状态：pending 仅存在于尚未启动的计划步，其余与活动生命周期一致。 */
type StepStatus = "pending" | ActivityStatus;

interface StepRow {
  key: string;
  title: string;
  status: StepStatus;
  /** 次级说明（如检索命中数、等待确认提示），保持一句以内。 */
  sub?: string;
}

// 事件存储里可能留有历史/未来 provider 阶段。只渲染这个显式集合，确保
// understanding/thinking 等内部阶段永远不会变成学生可见的进度文案。
const STUDENT_VISIBLE_STAGES = new Set<ActivityStage>([
  "planning",
  "retrieval",
  "tool",
  "responding",
  "confirmation",
]);

function isStudentHiddenActivity(activity: ActivityEntry): boolean {
  return !STUDENT_VISIBLE_STAGES.has(activity.stage);
}

function activityKey(entry: ActivityEntry): string {
  if (entry.toolCallId) return `tool:${entry.toolCallId}`;
  if (entry.activityId) return `activity:${entry.activityId}`;
  return `event:${entry.stage}:${entry.seq}`;
}

/** plan.updated 的步骤状态词汇跨版本不固定，统一折叠到五种可见状态。 */
function normalizePlanStatus(status: string): StepStatus {
  if (status === "running" || status === "in_progress" || status === "active") return "running";
  if (status === "waiting" || status === "waiting_confirmation") return "waiting";
  if (status === "completed" || status === "done" || status === "success") return "completed";
  if (status === "failed" || status === "error") return "failed";
  return "pending";
}

/** 检索 detail 形如"命中 N 条资料，耗时 X ms"：耗时属开发向信息，只保留前半句。 */
function firstSegment(detail: string | undefined): string | undefined {
  return detail?.split("，")[0]?.trim() || undefined;
}

function mergeVisibleActivities(
  activities: ActivityEntry[],
  currentActivity: ActivityEntry | null,
): ActivityEntry[] {
  const byKey = new Map<string, ActivityEntry>();
  for (const activity of [...activities, ...(currentActivity ? [currentActivity] : [])]) {
    if (isStudentHiddenActivity(activity)) continue;
    const key = activityKey(activity);
    const existing = byKey.get(key);
    if (!existing || (activity.eventSeq ?? activity.seq) >= (existing.eventSeq ?? existing.seq)) {
      byKey.set(key, existing ? { ...existing, ...activity, seq: existing.seq } : activity);
    }
  }
  return [...byKey.values()].sort((left, right) => left.seq - right.seq);
}

/**
 * 计划步骤与活动事件合并成步骤行。已启动的步骤以匹配工具活动的生命周期为准
 * （确认门打开/终态收口都先在工具活动上落地），未启动的以 plan.updated 状态
 * 为准；rag.search 步骤下挂检索命中数；不匹配任何计划步骤的工具活动追加在
 * 末尾，不隐藏任何真实工作。
 */
function buildStepRows(planSteps: PlanStep[], visibleActivities: ActivityEntry[]): StepRow[] {
  if (planSteps.length === 0) {
    return visibleActivities.map((activity) => ({
      key: activityKey(activity),
      title: activity.message,
      status: activity.status,
      sub: firstSegment(activity.detail),
    }));
  }
  const claimed = new Set<string>();
  const rows: StepRow[] = [];
  for (const step of planSteps) {
    const toolActivities = visibleActivities.filter(
      (activity) => activity.toolCallId && activity.tool === step.tool,
    );
    toolActivities.forEach((activity) => claimed.add(activityKey(activity)));
    const latest = toolActivities[toolActivities.length - 1];
    const status: StepStatus = latest ? latest.status : normalizePlanStatus(step.status);
    let sub: string | undefined;
    if (status === "waiting") {
      sub = "等待你的确认";
    } else if (step.tool === "rag.search") {
      const retrieval = visibleActivities.find(
        (activity) => activity.stage === "retrieval" && activity.status === "completed",
      );
      sub = firstSegment(retrieval?.detail);
    }
    rows.push({ key: `plan:${step.id}`, title: step.title, status, sub });
  }
  for (const activity of visibleActivities) {
    if (!activity.toolCallId || claimed.has(activityKey(activity))) continue;
    rows.push({
      key: activityKey(activity),
      title: activity.message,
      status: activity.status,
      sub: firstSegment(activity.detail),
    });
  }
  return rows;
}

function StepIcon({ status, size = 15 }: { status: StepStatus; size?: number }) {
  const Icon =
    status === "failed"
      ? CircleAlert
      : status === "completed"
        ? CheckCircle2
        : status === "waiting"
          ? ShieldCheck
          : status === "running"
            ? Loader2
            : CircleDashed;
  return <Icon aria-hidden="true" size={size} />;
}

/**
 * 学生可见的唯一执行过程出口。有意只投影计划、工具生命周期、确认与回答
 * 生成这些可观测阶段。运行成功结束后自动收成单行摘要（答案成为视觉主体），
 * 失败保持展开便于定位；每组只自动折叠一次，用户手动展开/收起优先。
 */
export default function ActivityTimeline({
  activities,
  planSteps = [],
  currentActivity = null,
  activityGroupId,
  processingLabel,
  live = true,
}: {
  activities: ActivityEntry[];
  /** 服务端计划即步骤流骨架，绝不渲染第二个"计划卡"。 */
  planSteps?: PlanStep[];
  /** 断流恢复态可能新于本地最后一帧 SSE。 */
  currentActivity?: ActivityEntry | null;
  /** 区分相邻 run 的历史控件，避免 seq 撞车。 */
  activityGroupId?: string;
  /** 首个可见事件到达前的安全运行标签。 */
  processingLabel?: string | null;
  /** 新的 live 记录初始展开；历史记录保持折叠。 */
  live?: boolean;
}) {
  const [open, setOpen] = useState(live);
  const recordStateRef = useRef({ activityGroupId, live });
  // 每个记录组只自动折叠一次：之后用户手动展开/收起的选择优先于任何重渲染。
  const settledGroupRef = useRef<string | null>(null);
  const seenRowKeysRef = useRef<Set<string> | null>(null);
  const generatedId = useId();
  useLayoutEffect(() => {
    const previous = recordStateRef.current;
    // 新一轮运行（组 id 变化或从历史态回到 live）始终展开。
    if (previous.activityGroupId !== activityGroupId || (!previous.live && live)) {
      setOpen(true);
    }
    recordStateRef.current = { activityGroupId, live };
  }, [activityGroupId, live]);
  const visibleActivities = useMemo(
    () => mergeVisibleActivities(activities, currentActivity),
    [activities, currentActivity],
  );
  const rows = useMemo(
    () => buildStepRows(planSteps, visibleActivities),
    [planSteps, visibleActivities],
  );
  const rowKeys = useMemo(() => rows.map((row) => row.key), [rows]);
  const arrivingRowKeys = useMemo(() => {
    const seenRowKeys = seenRowKeysRef.current;
    if (!live || !seenRowKeys) return new Set<string>();
    return new Set(rowKeys.filter((key) => !seenRowKeys.has(key)));
  }, [rowKeys, live]);
  useEffect(() => {
    // 稳定的行身份防止状态更新重播到达动画；只有真正新增的行才有动画。
    seenRowKeysRef.current = new Set(rowKeys);
  }, [rowKeys]);

  const hasFailure = rows.some((row) => row.status === "failed");
  const currentRow = rows.find((row) => row.status === "running" || row.status === "waiting");
  const summaryStatus: ActivityStatus = hasFailure
    ? "failed"
    : !live
      ? "completed"
      : rows.some((row) => row.status === "waiting")
        ? "waiting"
        : "running";

  useEffect(() => {
    // 主流 agent 行为：运行成功结束后自动收成单行摘要；失败保持展开。
    // 历史记录初始即折叠，幂等无影响。
    if (live || summaryStatus !== "completed") return;
    const groupKey = activityGroupId ?? generatedId;
    if (settledGroupRef.current === groupKey) return;
    settledGroupRef.current = groupKey;
    setOpen(false);
  }, [activityGroupId, generatedId, live, summaryStatus]);

  if (rows.length === 0 && !processingLabel) return null;

  const summaryText = (() => {
    if (!live) {
      return summaryStatus === "failed" ? "执行未完成" : `已完成 ${rows.length} 步`;
    }
    if (currentRow) {
      return currentRow.status === "waiting"
        ? `等待确认：${currentRow.title}`
        : `正在${currentRow.title}`;
    }
    if (processingLabel) return processingLabel;
    // 计划步骤全部完成、回复仍在流式输出中的间隙。
    if (rows.length > 0) return "正在生成回答";
    return "正在处理";
  })();

  const detailsId = `agent-steps-${activityGroupId ?? generatedId}`;
  const summaryTitle = `${summaryText}，${open ? "收起" : "展开"}执行过程`;

  return (
    <section
      className={`agent-steps-record agent-steps-record-${summaryStatus}`}
      aria-label="执行过程"
      aria-live={live ? "polite" : undefined}
      aria-relevant={live ? "additions text" : undefined}
      data-activity-group={activityGroupId}
      data-testid="agent-activity-timeline"
    >
      <button
        type="button"
        className={`agent-steps-summary agent-steps-summary-${summaryStatus}`}
        data-testid="agent-current-action"
        aria-expanded={open}
        aria-controls={detailsId}
        aria-label={summaryTitle}
        title={summaryTitle}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="agent-steps-summary-icon">
          <StepIcon status={summaryStatus} size={16} />
        </span>
        <span className="agent-steps-summary-text">{summaryText}</span>
        {open ? (
          <ChevronDown className="agent-steps-summary-chevron" aria-hidden="true" size={15} />
        ) : (
          <ChevronRight className="agent-steps-summary-chevron" aria-hidden="true" size={15} />
        )}
      </button>

      {open && rows.length > 0 ? (
        <ol className="agent-steps" id={detailsId} data-testid="agent-steps">
          {rows.map((row) => (
            <li
              key={row.key}
              className={[
                "agent-step",
                `agent-step-${row.status}`,
                arrivingRowKeys.has(row.key) ? "agent-step-arriving" : "",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              <span className="agent-step-icon">
                <StepIcon status={row.status} />
              </span>
              <span className="agent-step-body">
                <span className="agent-step-title">{row.title}</span>
                {row.sub ? <span className="agent-step-sub">{row.sub}</span> : null}
              </span>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
