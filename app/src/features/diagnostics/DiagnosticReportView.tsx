import type { TeachingRepository } from "../../data/repository";
import type { GraphEngine, RemediationPlan } from "../../graph/graphEngine";
import type {
  DiagnosticIssue,
  DiagnosticReport,
  DiagnosticSeverity,
} from "../../diagnostics/types";

export interface DiagnosticReportViewProps {
  report: DiagnosticReport;
  graphEngine?: GraphEngine;
  repository?: TeachingRepository;
  masteryForNode?(nodeId: string): number | null;
}

const SEVERITIES: readonly DiagnosticSeverity[] = [
  "severe",
  "moderate",
  "minor",
];

const SEVERITY_LABELS: Readonly<Record<DiagnosticSeverity, string>> = {
  severe: "严重问题",
  moderate: "中等问题",
  minor: "轻微问题",
};

const distinct = (values: readonly string[]): string[] => [...new Set(values)];

const issuesAtSeverity = (
  issues: readonly DiagnosticIssue[],
  severity: DiagnosticSeverity,
): readonly DiagnosticIssue[] => issues.filter((issue) => issue.severity === severity);

const planFor = (
  graphEngine: GraphEngine | undefined,
  capabilityId: string,
  masteryForNode: (nodeId: string) => number | null,
): RemediationPlan | null => {
  if (graphEngine === undefined) {
    return null;
  }
  try {
    return graphEngine.remediationPlan(capabilityId, masteryForNode);
  } catch {
    return null;
  }
};

export function DiagnosticReportView({
  report,
  graphEngine,
  repository,
  masteryForNode = () => null,
}: DiagnosticReportViewProps) {
  const capabilityIds = distinct(
    report.issues.flatMap((issue) => [...issue.capabilityRefs]),
  );

  return (
    <section className="diagnostic-report" aria-labelledby="diagnostic-report-title">
      <h2 id="diagnostic-report-title">诊断报告</h2>
      <p role="status">
        {report.status === "explanation_only"
          ? "辅助讲解模式：截图仅用于本地讲解，不计分也不更新掌握度。"
          : `诊断状态：${report.status}`}
      </p>

      {SEVERITIES.map((severity) => {
        const issues = issuesAtSeverity(report.issues, severity);
        if (issues.length === 0) {
          return null;
        }
        return (
          <section key={severity} aria-labelledby={`diagnostic-${severity}-title`}>
            <h3 id={`diagnostic-${severity}-title`}>
              {SEVERITY_LABELS[severity]}
            </h3>
            <ul aria-label={SEVERITY_LABELS[severity]}>
              {issues.map((issue) => (
                <li key={`${severity}-${issue.code}`}>
                  <p>{issue.message}</p>
                  {issue.ruleRefs.length > 0 ? (
                    <p>
                      规则依据：{issue.ruleRefs.map((ruleRef) => (
                        <code key={ruleRef}>{ruleRef}</code>
                      ))}
                    </p>
                  ) : null}
                  {issue.capabilityRefs.length > 0 ? (
                    <p>
                      能力引用：{issue.capabilityRefs.map((capabilityRef) => (
                        <code key={capabilityRef}>{capabilityRef}</code>
                      ))}
                    </p>
                  ) : null}
                  {issue.remediation.length > 0 ? (
                    <ul aria-label={`${issue.code}补强资源`}>
                      {issue.remediation.map((resource) => (
                        <li key={resource}>{resource}</li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        );
      })}

      {capabilityIds.map((capabilityId) => {
        const plan = planFor(graphEngine, capabilityId, masteryForNode);
        if (plan === null) {
          return (
            <p key={capabilityId} role="status">
              无法生成 {capabilityId} 的补强计划，请确认能力引用后重试。
            </p>
          );
        }
        if (plan.cycleDetected) {
          return (
            <p key={capabilityId} role="alert">
              检测到 PRE 环路，{capabilityId} 的按前置关系排序的补强计划不可执行。
            </p>
          );
        }
        return (
          <section key={capabilityId} aria-labelledby={`diagnostic-plan-${capabilityId}`}>
            <h3 id={`diagnostic-plan-${capabilityId}`}>按前置关系排序的补强计划</h3>
            {plan.steps.length === 0 ? (
              <p role="status">当前没有需要补强的前置能力。</p>
            ) : (
              <ol aria-label={`${capabilityId}补强步骤`}>
                {plan.steps.map((step) => {
                  const node = repository?.getNode(step.nodeId);
                  return (
                    <li key={step.nodeId}>
                      <strong>{node?.label ?? step.nodeId}</strong>
                      <span>（状态：{node?.status ?? "未知"}）</span>
                      <span>
                        {step.skipPractice ? "已掌握，可跳过练习" : "需要练习"}
                      </span>
                    </li>
                  );
                })}
              </ol>
            )}
          </section>
        );
      })}
    </section>
  );
}
