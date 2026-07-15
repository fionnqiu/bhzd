import { useMemo } from "react";

import { masteryBand, type MasteryBand } from "../../evaluation/mastery";
import type { GraphNode } from "../../data/contracts";
import type { GraphEngine, RemediationPlan, RemediationStep } from "../../graph/graphEngine";
import type { LearningProfileSnapshot } from "../../state/profileStore";

export interface ProgressPanelProps {
  graphEngine: GraphEngine;
  profileSnapshot: LearningProfileSnapshot;
  targetNodeId?: string | null;
  /** The currently selected scenario. `null` means general mode. */
  scenarioId?: string | null;
  /** Alias used by the application shell; when provided it takes precedence. */
  selectedScenarioId?: string | null;
  nodes?: readonly GraphNode[];
}

type ProgressBand = "unlearned" | "needs_work" | "consolidating" | "mastered";

const BAND_LABELS: Readonly<Record<ProgressBand, string>> = {
  unlearned: "未学习",
  needs_work: "需补强",
  consolidating: "巩固中",
  mastered: "已掌握",
};

const BAND_ORDER: readonly ProgressBand[] = [
  "unlearned",
  "needs_work",
  "consolidating",
  "mastered",
];

const scenarioMasteryKey = (nodeId: string, scenarioId: string): string =>
  `${nodeId}::${scenarioId}`;

const readMastery = (
  profileSnapshot: LearningProfileSnapshot,
  nodeId: string,
  scenarioId: string | null,
): number | null => {
  if (scenarioId === null) {
    return profileSnapshot.generalMastery[nodeId] ?? null;
  }

  // Scenario progress is intentionally isolated. An absent scenario value is
  // unlearned, even when the general capability has a high score.
  return (
    profileSnapshot.scenarioMastery[scenarioMasteryKey(nodeId, scenarioId)] ??
    null
  );
};

const displayBand = (mastery: number | null): ProgressBand => {
  if (
    mastery === null ||
    !Number.isFinite(mastery) ||
    mastery < 0 ||
    mastery > 1
  ) {
    return "unlearned";
  }

  const band: MasteryBand = masteryBand(mastery);
  if (band === "beginner" || band === "needs_work") {
    return "needs_work";
  }
  return band;
};

const formatMastery = (mastery: number | null): string =>
  mastery === null
    ? "未学习（尚未测评）"
    : `${mastery.toFixed(2)}（${Math.round(mastery * 100)}%）`;

const emptyCounts = (): Record<ProgressBand, number> => ({
  unlearned: 0,
  needs_work: 0,
  consolidating: 0,
  mastered: 0,
});

const countsFor = (
  nodeIds: readonly string[],
  profileSnapshot: LearningProfileSnapshot,
  scenarioId: string | null,
): Record<ProgressBand, number> => {
  const counts = emptyCounts();
  for (const nodeId of nodeIds) {
    counts[displayBand(readMastery(profileSnapshot, nodeId, scenarioId))] += 1;
  }
  return counts;
};

type PlanState =
  | { kind: "idle" }
  | { kind: "unknown" }
  | { kind: "cycle"; plan: RemediationPlan }
  | { kind: "ready"; plan: RemediationPlan };

const planStateFor = (
  graphEngine: GraphEngine,
  profileSnapshot: LearningProfileSnapshot,
  targetNodeId: string | null,
  scenarioId: string | null,
): PlanState => {
  if (targetNodeId === null) {
    return { kind: "idle" };
  }

  try {
    const plan = graphEngine.remediationPlan(targetNodeId, (nodeId) =>
      readMastery(profileSnapshot, nodeId, scenarioId),
    );
    return plan.cycleDetected
      ? { kind: "cycle", plan }
      : { kind: "ready", plan };
  } catch {
    return { kind: "unknown" };
  }
};

interface BandSummaryProps {
  counts: Readonly<Record<ProgressBand, number>>;
  heading: string;
  scenario?: boolean;
}

function BandSummary({ counts, heading, scenario = false }: BandSummaryProps) {
  const headingId = scenario
    ? "graph-progress-scenario-title"
    : "graph-progress-general-title";

  return (
    <section
      className="graph-progress-panel__summary"
      role="group"
      aria-labelledby={headingId}
    >
      <h3 id={headingId}>{heading}</h3>
      <ul
        className="graph-progress-panel__bands"
        aria-label={`${heading}分级`}
      >
        {BAND_ORDER.map((band) => (
          <li key={band} data-band={band}>
            <span>{scenario ? `场景 · ${BAND_LABELS[band]}` : BAND_LABELS[band]}</span>
            <strong aria-label={`${heading}${BAND_LABELS[band]}数量`}>
              {counts[band]}
            </strong>
          </li>
        ))}
      </ul>
    </section>
  );
}

interface RemediationStepViewProps {
  nodeById: ReadonlyMap<string, GraphNode>;
  scenarioId: string | null;
  step: RemediationStep;
}

function RemediationStepView({
  nodeById,
  scenarioId,
  step,
}: RemediationStepViewProps) {
  const node = nodeById.get(step.nodeId);
  const label = node?.label ?? step.nodeId;
  const status = node?.status ?? "未知";
  const practiceLabel = step.skipPractice ? "跳过练习" : "需要练习";
  const scopeLabel =
    scenarioId === null ? "通用掌握度" : `场景掌握度（${scenarioId}）`;

  return (
    <li className="graph-progress-panel__step" data-node-id={step.nodeId}>
      <strong>{label}</strong>
      <span>节点 ID：{step.nodeId}</span>
      <span>节点状态：{status}</span>
      <span>
        {scopeLabel}：{formatMastery(step.mastery)}
      </span>
      <span>
        skipPractice={String(step.skipPractice)}（{practiceLabel}）
      </span>
    </li>
  );
}

export function ProgressPanel({
  graphEngine,
  profileSnapshot,
  targetNodeId = null,
  scenarioId: scenarioIdProp = null,
  selectedScenarioId,
  nodes = [],
}: ProgressPanelProps) {
  const scenarioId =
    selectedScenarioId === undefined ? scenarioIdProp : selectedScenarioId;

  const nodeById = useMemo(
    () => new Map(nodes.map((node) => [node.id, node] as const)),
    [nodes],
  );

  const planState = useMemo(
    () =>
      planStateFor(
        graphEngine,
        profileSnapshot,
        targetNodeId,
        scenarioId,
      ),
    [
      graphEngine,
      nodeById,
      profileSnapshot,
      scenarioId,
      targetNodeId,
    ],
  );

  const progressNodeIds = useMemo(() => {
    const ids = new Set<string>();
    for (const node of nodes) {
      ids.add(node.id);
    }

    if (nodes.length === 0) {
      for (const nodeId of Object.keys(profileSnapshot.generalMastery)) {
        ids.add(nodeId);
      }
      if (scenarioId !== null) {
        const suffix = `::${scenarioId}`;
        for (const key of Object.keys(profileSnapshot.scenarioMastery)) {
          if (key.endsWith(suffix)) {
            ids.add(key.slice(0, -suffix.length));
          }
        }
      }
    }

    if (planState.kind === "ready" || planState.kind === "cycle") {
      for (const step of planState.plan.steps) {
        ids.add(step.nodeId);
      }
    }
    return [...ids];
  }, [nodes, planState, profileSnapshot, scenarioId]);

  const generalCounts = useMemo(
    () => countsFor(progressNodeIds, profileSnapshot, null),
    [profileSnapshot, progressNodeIds],
  );
  const scenarioCounts = useMemo(
    () =>
      scenarioId === null
        ? null
        : countsFor(progressNodeIds, profileSnapshot, scenarioId),
    [profileSnapshot, progressNodeIds, scenarioId],
  );

  return (
    <section className="graph-progress-panel" aria-labelledby="graph-progress-title">
      <p className="eyebrow eyebrow--ink">LEARNING PROGRESS</p>
      <h2 id="graph-progress-title">学习进度</h2>

      <BandSummary heading="通用掌握度" counts={generalCounts} />
      {scenarioCounts === null ? (
        <p className="graph-progress-panel__scope">
          当前未选择具体场景，补强计划使用通用掌握度。
        </p>
      ) : (
        <BandSummary
          heading={`场景掌握度：${scenarioId}`}
          counts={scenarioCounts}
          scenario
        />
      )}

      {planState.kind === "idle" ? (
        <p className="graph-progress-panel__empty" role="status">
          选择节点后查看按前置关系排序的补强计划。
        </p>
      ) : planState.kind === "unknown" ? (
        <p className="graph-progress-panel__empty" role="status">
          未找到目标节点，请重新选择节点后查看补强计划。
        </p>
      ) : planState.kind === "cycle" ? (
        <div className="graph-progress-panel__cycle" role="alert">
          <p role="status">
            检测到 PRE 环路，补强计划不可执行，无法执行练习步骤。
          </p>
        </div>
      ) : (
        <div className="graph-progress-panel__plan">
          <h3>按前置关系排序的补强计划</h3>
          {planState.plan.steps.length === 0 ? (
            <p role="status">当前没有可执行的补强步骤。</p>
          ) : (
            <ol aria-label="补强步骤">
              {planState.plan.steps.map((step) => (
                <RemediationStepView
                  key={step.nodeId}
                  nodeById={nodeById}
                  scenarioId={scenarioId}
                  step={step}
                />
              ))}
            </ol>
          )}
        </div>
      )}
    </section>
  );
}
