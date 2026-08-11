import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleDashed,
  Loader2,
  MessageSquareText,
  Search,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import { AgentOrb } from "../../../components";
import type { PlanStep } from "../../../api/types";
import { toolLabel } from "./constants";
import ExecutionPlan from "./PlanCard";
import type { ActivityEntry, ActivityStage, ActivityStatus, ExecutionKind } from "./types";

const STAGE_LABELS: Partial<Record<ActivityStage, string>> = {
  planning: "执行计划",
  retrieval: "资料检索",
  tool: "实际操作",
  responding: "回答生成",
  confirmation: "待确认",
};

const EXECUTION_KIND_LABELS: Record<ExecutionKind, string> = {
  tool: "工具调用",
  command: "命令执行",
  file: "文件操作",
};

const STATUS_LABELS: Record<ActivityStatus, string> = {
  running: "进行中",
  completed: "已完成",
  waiting: "等待确认",
  failed: "未完成",
};

// The event store can retain legacy or future provider stages. Rendering only
// this explicit set ensures the student record never turns an internal phase
// such as understanding, thinking, or analysis into visible progress copy.
const STUDENT_VISIBLE_STAGES = new Set<ActivityStage>([
  "planning",
  "retrieval",
  "tool",
  "responding",
  "confirmation",
]);

type ActivityBlock =
  { kind: "entry"; entry: ActivityEntry } | { kind: "tools"; entries: ActivityEntry[] };

function executionKindLabel(kind: ExecutionKind | undefined): string {
  return EXECUTION_KIND_LABELS[kind ?? "tool"];
}

function ActivityIcon({
  stage,
  status,
  size = 16,
}: Pick<ActivityEntry, "stage" | "status"> & { size?: number }) {
  const Icon =
    status === "failed"
      ? CircleAlert
      : status === "completed"
        ? CheckCircle2
        : stage === "responding"
          ? MessageSquareText
          : stage === "retrieval"
            ? Search
            : stage === "confirmation"
              ? ShieldCheck
              : stage === "tool"
                ? Wrench
                : status === "running"
                  ? Loader2
                  : CircleDashed;
  return <Icon aria-hidden="true" size={size} />;
}

function activityKey(entry: ActivityEntry): string {
  if (entry.toolCallId) return `tool:${entry.toolCallId}`;
  if (entry.activityId) return `activity:${entry.activityId}`;
  return `event:${entry.stage}:${entry.seq}`;
}

function groupActivityBlocks(entries: ActivityEntry[]): ActivityBlock[] {
  const blocks: ActivityBlock[] = [];
  for (const entry of entries) {
    const previous = blocks[blocks.length - 1];
    if (entry.stage === "tool" && previous?.kind === "tools") {
      previous.entries.push(entry);
    } else if (entry.stage === "tool") {
      blocks.push({ kind: "tools", entries: [entry] });
    } else {
      blocks.push({ kind: "entry", entry });
    }
  }
  return blocks;
}

/**
 * The activity type retains legacy values so old persisted events can still be
 * decoded, but only observable operations are allowed into the student record.
 */
function isStudentHiddenActivity(activity: ActivityEntry): boolean {
  return !STUDENT_VISIBLE_STAGES.has(activity.stage);
}

function toolGroupLabel(entries: ActivityEntry[]): string {
  const names = [...new Set(entries.map((entry) => toolLabel(entry.tool ?? "受控操作")))];
  const nameSummary = names.slice(0, 3).join("、");
  const suffix = names.length > 3 ? `等 ${names.length} 项` : nameSummary;
  const hasRunning = entries.some((entry) => entry.status === "running");
  const hasWaiting = entries.some((entry) => entry.status === "waiting");
  const hasFailed = entries.some((entry) => entry.status === "failed");
  if (hasWaiting) return `等待确认：${suffix}`;
  if (hasFailed) return `有未完成操作：${suffix}`;
  if (hasRunning) return `正在执行：${suffix}`;
  return `已完成 ${entries.length} 项操作${suffix ? ` · ${suffix}` : ""}`;
}

function ActivityRow({
  activity,
  detailSeqAttribute = "data-activity-seq",
  animateArrival = false,
}: {
  activity: ActivityEntry;
  detailSeqAttribute?: "data-activity-seq" | "data-activity-detail-seq";
  animateArrival?: boolean;
}) {
  const stageLabel =
    activity.stage === "tool"
      ? executionKindLabel(activity.executionKind)
      : STAGE_LABELS[activity.stage];
  // Input and output summaries are intentionally absent from this presentation.
  // Even a bounded summary can drift toward prompts, arguments, or raw results;
  // the lifecycle label and duration are sufficient learner-facing progress.
  return (
    <div
      className={[
        "agent-activity-row",
        `agent-activity-row-${activity.status}`,
        activity.stage === "retrieval" ? "agent-activity-row-retrieval" : "",
        activity.stage === "tool" ? "agent-activity-row-operation" : "",
        animateArrival ? "agent-activity-row-arriving" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      {...{ [detailSeqAttribute]: activity.eventSeq ?? activity.seq }}
    >
      <span className="agent-activity-row-icon">
        <ActivityIcon stage={activity.stage} status={activity.status} />
      </span>
      <div className="agent-activity-row-content">
        <div className="agent-activity-row-primary">
          {stageLabel ? <span className="agent-activity-stage">{stageLabel}</span> : null}
          {/* Keep each lifecycle state beside the operation it describes so
              completed rows do not form a detached status column. */}
          <span className={`agent-activity-status agent-activity-status-${activity.status}`}>
            {STATUS_LABELS[activity.status]}
          </span>
          <span>{activity.message}</span>
        </div>
        {activity.detail ? <p className="agent-activity-detail">{activity.detail}</p> : null}
        {activity.tool ? (
          <p className="agent-activity-meta">
            {toolLabel(activity.tool)}
            {activity.isWrite ? " · 写操作" : " · 只读"}
            {activity.durationMs != null ? ` · ${activity.durationMs}ms` : ""}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function ToolGroup({
  entries,
  live,
  arrivingActivityKeys,
}: {
  entries: ActivityEntry[];
  live: boolean;
  arrivingActivityKeys: ReadonlySet<string>;
}) {
  const groupKey = `tools-${entries[0]?.seq ?? "empty"}`;
  const hasAttentionState = entries.some(
    (entry) =>
      entry.status === "running" || entry.status === "waiting" || entry.status === "failed",
  );
  const [openOverride, setOpenOverride] = useState<boolean | null>(null);
  // A live trace should read like a continuous terminal log; completed and
  // historical groups compact only after the run becomes terminal.
  const open = openOverride ?? (live || hasAttentionState);
  const summary = toolGroupLabel(entries);

  if (entries.length === 1) {
    return (
      <ActivityRow
        activity={entries[0]}
        animateArrival={arrivingActivityKeys.has(activityKey(entries[0]))}
      />
    );
  }

  return (
    <div className="agent-tool-group" data-tool-group={groupKey}>
      <button
        type="button"
        className="agent-tool-group-toggle"
        aria-expanded={open}
        aria-controls={`${groupKey}-details`}
        onClick={() => setOpenOverride(!open)}
      >
        {open ? (
          <ChevronDown aria-hidden="true" size={15} />
        ) : (
          <ChevronRight aria-hidden="true" size={15} />
        )}
        <span className="agent-tool-group-summary">{summary}</span>
        <span className="agent-tool-group-count">{entries.length} 条</span>
      </button>
      {open ? (
        <div id={`${groupKey}-details`} className="agent-tool-group-details">
          {entries.map((entry) => (
            <ActivityRow
              key={`${entry.seq}-${entry.toolCallId ?? entry.tool ?? "tool"}`}
              activity={entry}
              detailSeqAttribute="data-activity-detail-seq"
              animateArrival={arrivingActivityKeys.has(activityKey(entry))}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
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

function recordSummary(
  current: ActivityEntry | null,
  live: boolean,
  hasPlan: boolean,
  processingLabel?: string,
): string {
  const terminal = !live && (current?.status === "completed" || current?.status === "failed");
  if (terminal) {
    if (current?.status === "failed") {
      return "处理未完成";
    }
    return "处理完成";
  }
  if (current) return current.message;
  if (processingLabel) return processingLabel;
  return hasPlan ? "执行清单已就绪" : "等待可见执行事件";
}

function recordStageLabel(
  current: ActivityEntry | null,
  live: boolean,
  hasPlan: boolean,
  processingLabel?: string,
): string {
  if (!live && current?.status === "completed") return "处理过程";
  if (!live && current?.status === "failed") return "处理过程";
  if (!current && processingLabel) return "处理中";
  if (!current) return hasPlan ? "执行清单" : "处理过程";
  if (current.stage === "tool") return executionKindLabel(current.executionKind);
  return STAGE_LABELS[current.stage] ?? "处理过程";
}

/**
 * The single student-facing source for verified Agent work. It intentionally
 * projects plans, tool lifecycles, confirmations, and answer generation only;
 * raw reasoning, payloads, and fabricated progress never reach this component.
 * Planning and retrieval use only bounded server-issued progress summaries. A live
 * processing label is accepted as a fallback so the same record can replace the
 * former standalone thinking/status widget before the first visible event arrives.
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
  /** A server-issued plan belongs to the same execution record, never a second card. */
  planSteps?: PlanStep[];
  /** A recovery status can be newer than the last locally received SSE frame. */
  currentActivity?: ActivityEntry | null;
  /** Distinguishes historical controls from adjacent runs with matching sequence values. */
  activityGroupId?: string;
  /** A safe run-state label shown in the same record before an event arrives. */
  processingLabel?: string | null;
  /** New live records start expanded; historical records stay compact. */
  live?: boolean;
}) {
  const [open, setOpen] = useState(live);
  const recordStateRef = useRef({ activityGroupId, live });
  const seenActivityKeysRef = useRef<Set<string> | null>(null);
  const generatedId = useId();
  useLayoutEffect(() => {
    const previous = recordStateRef.current;
    // Keep the current turn open when it settles so the reviewed lifecycle
    // summary remains visible beside the answer, while historical records stay
    // compact and a learner's manual fold choice is preserved.
    if (previous.activityGroupId !== activityGroupId || (!previous.live && live)) {
      setOpen(true);
    }
    recordStateRef.current = { activityGroupId, live };
  }, [activityGroupId, live]);
  const visibleActivities = useMemo(
    () => mergeVisibleActivities(activities, currentActivity),
    [activities, currentActivity],
  );
  const activityKeys = useMemo(() => visibleActivities.map(activityKey), [visibleActivities]);
  const arrivingActivityKeys = useMemo(() => {
    const seenActivityKeys = seenActivityKeysRef.current;
    if (!live || !seenActivityKeys) return new Set<string>();
    return new Set(activityKeys.filter((key) => !seenActivityKeys.has(key)));
  }, [activityKeys, live]);
  useEffect(() => {
    // Stable lifecycle identities prevent status updates from replaying an
    // arrival animation; only a genuinely new visible activity gets one.
    seenActivityKeysRef.current = new Set(activityKeys);
  }, [activityKeys]);
  const blocks = useMemo(() => groupActivityBlocks(visibleActivities), [visibleActivities]);
  const current = visibleActivities[visibleActivities.length - 1] ?? null;
  const toolCount = visibleActivities.filter((activity) => activity.stage === "tool").length;
  const hasPlan = planSteps.length > 0;

  if (!current && !hasPlan && !processingLabel) return null;

  const summaryStatus: ActivityStatus =
    !live && current?.status === "failed"
      ? "failed"
      : !live && current?.status === "completed"
        ? "completed"
        : (current?.status ?? "running");
  const detailsId = `agent-execution-details-${activityGroupId ?? generatedId}`;
  const summary = recordSummary(current, live, hasPlan, processingLabel ?? undefined);
  const stageLabel = recordStageLabel(current, live, hasPlan, processingLabel ?? undefined);
  // The orb communicates the currently safe, observable lifecycle phase. It
  // deliberately never represents or reveals private model reasoning.
  const orbPhase =
    summaryStatus === "completed"
      ? "finalizing"
      : current?.stage === "retrieval"
        ? "retrieving"
        : current?.stage === "responding"
          ? "generating"
          : "preparing";

  return (
    <section
      className={`agent-execution-record agent-execution-record-${summaryStatus}`}
      aria-label="智能体执行记录"
      aria-live={live ? "polite" : undefined}
      aria-relevant={live ? "additions text" : undefined}
      data-activity-group={activityGroupId}
      data-testid="agent-activity-timeline"
    >
      <button
        type="button"
        className={`agent-current-action agent-execution-summary agent-current-action-${summaryStatus}`}
        data-testid="agent-current-action"
        data-activity-seq={current?.eventSeq ?? current?.seq}
        aria-expanded={open}
        aria-controls={detailsId}
        aria-label={`${summary}，${open ? "收起" : "展开"}执行记录`}
        title={`${open ? "收起" : "展开"}执行记录`}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="agent-current-action-icon">
          {summaryStatus === "running" || summaryStatus === "completed" ? (
            <AgentOrb phase={orbPhase} />
          ) : current ? (
            <ActivityIcon stage={current.stage} status={summaryStatus} size={16} />
          ) : (
            <Wrench aria-hidden="true" size={16} />
          )}
        </span>
        <span className="agent-current-action-copy">
          <span className="agent-current-action-stage">{stageLabel}</span>
          <span className="agent-current-action-title" title={summary}>
            {summary}
          </span>
        </span>
        <span className={`agent-activity-status agent-activity-status-${summaryStatus}`}>
          {STATUS_LABELS[summaryStatus]}
        </span>
        {toolCount > 0 ? (
          <span className="agent-activity-summary-count">{toolCount} 项操作</span>
        ) : null}
        {open ? (
          <ChevronDown className="agent-current-action-chevron" aria-hidden="true" size={15} />
        ) : (
          <ChevronRight className="agent-current-action-chevron" aria-hidden="true" size={15} />
        )}
      </button>

      <div
        id={detailsId}
        className="agent-activity-expanded agent-execution-spine"
        hidden={!open}
        aria-hidden={!open}
      >
        {open ? (
          <>
            {hasPlan ? <ExecutionPlan steps={planSteps} /> : null}
            {blocks.length > 0 ? (
              <div className="agent-activity-history" data-testid="agent-activity-history">
                <div className="agent-activity-history-heading">
                  <span>实际执行</span>
                  <span>{visibleActivities.length} 条记录</span>
                </div>
                <div className="agent-activity-history-list">
                  {blocks.map((block) =>
                    block.kind === "tools" ? (
                      <ToolGroup
                        key={`tools-${block.entries[0]?.seq ?? "empty"}`}
                        entries={block.entries}
                        live={live}
                        arrivingActivityKeys={arrivingActivityKeys}
                      />
                    ) : (
                      <ActivityRow
                        key={activityKey(block.entry)}
                        activity={block.entry}
                        animateArrival={arrivingActivityKeys.has(activityKey(block.entry))}
                      />
                    ),
                  )}
                </div>
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </section>
  );
}
