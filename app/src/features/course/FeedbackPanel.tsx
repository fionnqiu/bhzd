import type { EvaluationResult } from "../../evaluation/evaluate";
import { masteryBand, type MasteryBand } from "../../evaluation/mastery";
import type { LearningProfileSnapshot } from "../../state/profileStore";

const MASTERY_BAND_LABELS: Readonly<Record<MasteryBand, string>> = {
  beginner: "入门",
  needs_work: "需加强",
  consolidating: "巩固中",
  mastered: "已掌握",
};

const scenarioMasteryKey = (
  capabilityId: string,
  scenarioId: string,
): string => `${capabilityId}::${scenarioId}`;

const scoreLabel = (score: number): string =>
  Number(score.toFixed(3)).toString();

interface MasteryRowsProps {
  capabilityRefs: readonly string[];
  values: Readonly<Record<string, number>>;
  scenarioId?: string;
}

function MasteryRows({
  capabilityRefs,
  values,
  scenarioId,
}: MasteryRowsProps) {
  return (
    <ul className="mastery-list">
      {capabilityRefs.map((capabilityId) => {
        const key =
          scenarioId === undefined
            ? capabilityId
            : scenarioMasteryKey(capabilityId, scenarioId);
        const value = values[key] ?? 0;
        const band = masteryBand(value);
        const percentage = Math.round(value * 100);

        return (
          <li key={key}>
            <div>
              <code>{capabilityId}</code>
              <span>{MASTERY_BAND_LABELS[band]}</span>
            </div>
            <progress
              value={value}
              max={1}
              aria-label={`${capabilityId} 掌握度 ${percentage}%`}
            />
            <strong>{percentage}%</strong>
          </li>
        );
      })}
    </ul>
  );
}

interface FeedbackPanelProps {
  result: EvaluationResult;
  profile: LearningProfileSnapshot;
  selectedScenarioId: string | null;
}

export function FeedbackPanel({
  result,
  profile,
  selectedScenarioId,
}: FeedbackPanelProps) {
  const outcome = result.manualReviewRequired
    ? "人工复核"
    : result.passed
      ? "通过"
      : result.matched === "unclassified"
        ? "未通过 · 未分类"
        : "未通过";
  const tone = result.manualReviewRequired
    ? "review"
    : result.passed
      ? "pass"
      : "fail";

  return (
    <section
      className={`feedback-panel feedback-panel--${tone}`}
      role="status"
      aria-label="自检反馈"
    >
      <div className="feedback-panel__header">
        <div>
          <p className="eyebrow eyebrow--ink">DETERMINISTIC FEEDBACK</p>
          <h3>{outcome}</h3>
        </div>
        <p className="feedback-panel__score">
          <span>得分</span>
          <strong>{scoreLabel(result.score)}</strong>
          <span>/ 1</span>
        </p>
      </div>

      <p className="feedback-panel__message">{result.feedback}</p>

      <dl className="feedback-panel__facts">
        <div>
          <dt>匹配类型</dt>
          <dd>{result.matched}</dd>
        </div>
        <div>
          <dt>错误类型</dt>
          <dd>{result.errorType ?? "无"}</dd>
        </div>
        <div>
          <dt>数据版本</dt>
          <dd>{result.dataVersion}</dd>
        </div>
        <div>
          <dt>评估版本</dt>
          <dd>{result.evaluationVersion}</dd>
        </div>
      </dl>

      <div className="feedback-panel__references">
        <div>
          <h4>本次规则依据</h4>
          <ul>
            {result.ruleRefs.map((ruleRef) => (
              <li key={ruleRef}>
                <code>{ruleRef}</code>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4>能力坐标</h4>
          <ul>
            {result.capabilityRefs.map((capabilityRef) => (
              <li key={capabilityRef}>
                <code>{capabilityRef}</code>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {result.remediation.length > 0 ? (
        <div className="feedback-panel__remediation">
          <h4>本次补强建议</h4>
          <ul>
            {result.remediation.map((item, index) => (
              <li key={`${index}-${item}`}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mastery-panel">
        <h3>掌握度</h3>
        <div className="mastery-panel__grid">
          <section aria-label="通用掌握度">
            <h4>通用掌握度</h4>
            <MasteryRows
              capabilityRefs={result.capabilityRefs}
              values={profile.generalMastery}
            />
          </section>
          <section aria-label="场景掌握度">
            <h4>场景掌握度</h4>
            {selectedScenarioId === null ? (
              <p>当前为通用场景，未写入场景掌握度。</p>
            ) : (
              <>
                <p>
                  当前场景：<code>{selectedScenarioId}</code>
                </p>
                <MasteryRows
                  capabilityRefs={result.capabilityRefs}
                  values={profile.scenarioMastery}
                  scenarioId={selectedScenarioId}
                />
              </>
            )}
          </section>
        </div>
      </div>
    </section>
  );
}
