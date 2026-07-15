import { useEffect, useRef, useState } from "react";

import { useAppContext } from "../../app/AppContext";
import { Button } from "../../components/Button";
import type {
  Exercise,
  ExtensibleFields,
  TeachingUnit,
} from "../../data/contracts";
import {
  evaluateExercise,
  type EvaluationResult,
} from "../../evaluation/evaluate";
import { AudioAsset } from "./AudioAsset";
import { FeedbackPanel } from "./FeedbackPanel";
import { createLearnerSafeExampleProjection } from "./learnerSafeExample";
import { StructuredResponseEditor } from "./StructuredResponseEditor";

const isRecord = (value: unknown): value is ExtensibleFields =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const hasContent = (value: unknown): boolean => {
  if (value === null || value === undefined) {
    return false;
  }
  if (Array.isArray(value) || typeof value === "string") {
    return value.length > 0;
  }
  if (isRecord(value)) {
    return Object.keys(value).length > 0;
  }
  return true;
};

const formatStructuredValue = (value: unknown): string => {
  try {
    const formatted = JSON.stringify(value, null, 2);
    return formatted ?? String(value);
  } catch {
    return "[无法显示的结构化教学数据]";
  }
};

interface ListSectionProps {
  title: string;
  items: readonly string[];
  className?: string;
}

function ListSection({ title, items, className }: ListSectionProps) {
  if (items.length === 0) {
    return null;
  }

  return (
    <section className={className ?? "lesson-section"}>
      <h2>{title}</h2>
      <ul className="lesson-list">
        {items.map((item, index) => (
          <li key={`${index}-${item}`}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

interface StructuredSectionProps {
  title: string;
  value: unknown;
  className?: string;
}

function StructuredSection({
  title,
  value,
  className,
}: StructuredSectionProps) {
  if (!hasContent(value)) {
    return null;
  }

  return (
    <section className={className ?? "lesson-section"}>
      <h2>{title}</h2>
      <pre className="structured-data">{formatStructuredValue(value)}</pre>
    </section>
  );
}

const safePracticeExercise = (value: unknown): ExtensibleFields | null => {
  if (!isRecord(value)) {
    return null;
  }

  const safeKeys = [
    "exercise_id",
    "exercise_type",
    "asset_ref",
    "representation",
    "manifest_resolution",
    "input",
    "student_action",
    "response_space",
    "data_version",
    "pass_condition",
    "capability_refs",
    "error_types",
    "asset_authorization",
  ] as const;
  const safe: ExtensibleFields = {};

  for (const key of safeKeys) {
    if (Object.prototype.hasOwnProperty.call(value, key)) {
      safe[key] = value[key];
    }
  }

  return safe;
};

const safePracticeVariants = (value: unknown): ExtensibleFields[] => {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map(safePracticeExercise)
    .filter((item): item is ExtensibleFields => item !== null);
};

const POLICY_SECTIONS = [
  ["boundary_cases", "边界案例"],
  ["visibility_policy", "可见性策略"],
  ["instance_policy", "实例策略"],
  ["validation_precedence", "校验优先级"],
  ["timebase_policy", "时间基准策略"],
  ["related_primitives", "相关基础能力"],
] as const;

interface LessonViewProps {
  unit: TeachingUnit;
  focusOnMount?: boolean;
  onBack(): void;
}

export function LessonView({
  unit,
  focusOnMount = false,
  onBack,
}: LessonViewProps) {
  const {
    selectedScenarioId,
    profileSnapshot,
    recordExercises,
  } = useAppContext();
  const [result, setResult] = useState<EvaluationResult | null>(null);
  const [evaluationError, setEvaluationError] = useState<string | null>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const goals = Array.isArray(unit.goals) ? unit.goals : [];
  const practiceVariants = safePracticeVariants(unit.practice_variants);
  const responseSpace =
    unit.exercise.response_space ??
    (isRecord(unit.exercise.evaluation)
      ? unit.exercise.evaluation.response_space
      : undefined);

  useEffect(() => {
    if (focusOnMount) {
      titleRef.current?.focus();
    }
  }, [focusOnMount]);

  const evaluateSubmission = (submission: unknown) => {
    let nextResult: EvaluationResult;
    try {
      nextResult = evaluateExercise(unit, submission);
    } catch {
      setResult(null);
      setEvaluationError(
        "本题自检配置暂时不可用。你的答案仍保留在编辑器中，请稍后重试。",
      );
      return;
    }

    setEvaluationError(null);
    setResult(nextResult);

    if (
      nextResult.matched === "unclassified" ||
      nextResult.manualReviewRequired
    ) {
      return;
    }

    recordExercises(
      nextResult.capabilityRefs.map((capabilityId) => ({
        capabilityId,
        score: nextResult.score,
        scenarioId: selectedScenarioId,
        evaluationVersion: nextResult.evaluationVersion,
      })),
    );
  };

  return (
    <article className="lesson-view">
      <div className="lesson-view__header">
        <Button variant="quiet" onClick={onBack}>
          返回课程列表
        </Button>
        <div className="lesson-view__title">
          <p className="eyebrow eyebrow--ink">LESSON FIX / {unit.data_type}</p>
          <h1 ref={titleRef} tabIndex={-1}>
            {unit.title}
          </h1>
          <p className="lesson-view__id">{unit.id}</p>
        </div>
        <dl className="lesson-view__status">
          <div>
            <dt>发布状态</dt>
            <dd>{unit.review_status}</dd>
          </div>
          <div>
            <dt>学生可见</dt>
            <dd>{unit.student_visible ? "是" : "否"}</dd>
          </div>
          {typeof unit.capability_key === "string" ? (
            <div>
              <dt>能力键</dt>
              <dd>{unit.capability_key}</dd>
            </div>
          ) : null}
        </dl>
      </div>

      <div className="lesson-view__content">
        <section className="lesson-section lesson-section--objectives">
          <h2>学习目标</h2>
          {goals.length > 0 ? (
            <>
              <h3>课程目标</h3>
              <ul className="lesson-list">
                {goals.map((goal, index) => (
                  <li key={`${index}-${goal}`}>{goal}</li>
                ))}
              </ul>
            </>
          ) : null}
          <h3>可验证学习目标</h3>
          <ul className="lesson-list">
            {unit.learning_objectives.map((objective, index) => (
              <li key={`${index}-${objective}`}>{objective}</li>
            ))}
          </ul>
        </section>

        <ListSection title="先修能力" items={unit.prerequisites} />

        <section className="lesson-section lesson-section--references">
          <h2>规则依据</h2>
          <dl className="reference-grid">
            <div>
              <dt>规则引用</dt>
              <dd>
                <ul>
                  {unit.rule_refs.map((ruleRef) => (
                    <li key={ruleRef}>
                      <code>{ruleRef}</code>
                    </li>
                  ))}
                </ul>
              </dd>
            </div>
            <div>
              <dt>来源引用</dt>
              <dd>
                <ul>
                  {unit.source_refs.map((sourceRef) => (
                    <li key={sourceRef}>
                      <code>{sourceRef}</code>
                    </li>
                  ))}
                </ul>
              </dd>
            </div>
          </dl>
        </section>

        <StructuredSection title="规则说明" value={unit.rule_explanation} />

        {POLICY_SECTIONS.map(([key, label]) => (
          <StructuredSection key={key} title={label} value={unit[key]} />
        ))}

        <StructuredSection
          title="正例"
          value={createLearnerSafeExampleProjection(unit.positive_examples)}
        />
        <StructuredSection
          title="反例"
          value={createLearnerSafeExampleProjection(unit.negative_examples)}
        />

        <section className="lesson-section lesson-section--exercise">
          <div className="lesson-section__heading">
            <div>
              <p className="eyebrow eyebrow--ink">ACTIVE EXERCISE</p>
              <h2>结构化练习</h2>
            </div>
            <dl>
              <div>
                <dt>数据版本</dt>
                <dd>{unit.exercise.data_version}</dd>
              </div>
              {typeof unit.exercise.exercise_type === "string" ? (
                <div>
                  <dt>练习类型</dt>
                  <dd>{unit.exercise.exercise_type}</dd>
                </div>
              ) : null}
            </dl>
          </div>

          <section className="exercise-block">
            <h3>资产与授权</h3>
            <AudioAsset dataType={unit.data_type} exercise={unit.exercise} />
          </section>

          <section className="exercise-block">
            <h3>练习输入</h3>
            <pre className="structured-data">
              {formatStructuredValue(unit.exercise.input)}
            </pre>
          </section>

          <section className="exercise-block">
            <h3>学员动作</h3>
            <p>{unit.exercise.student_action}</p>
          </section>

          <section className="exercise-block">
            <h3>通过条件</h3>
            <p>
              {typeof unit.exercise.pass_condition === "string"
                ? unit.exercise.pass_condition
                : formatStructuredValue(unit.exercise.pass_condition)}
            </p>
          </section>

          <StructuredSection title="响应空间" value={responseSpace} />
          <section className="exercise-block exercise-block--protocol">
            <h3>评估方式</h3>
            <p>
              提交后由本地确定性评估器核对结构化答案；数据版本、评估版本与规则结果会在反馈中显示。
            </p>
          </section>

          <StructuredResponseEditor
            key={unit.id}
            answerTemplate={unit.exercise.answer}
            responseSpace={responseSpace}
            onSubmit={evaluateSubmission}
            onEdit={() => {
              setResult(null);
              setEvaluationError(null);
            }}
          />

          {evaluationError !== null ? (
            <p className="evaluation-error" role="alert">
              {evaluationError}
            </p>
          ) : null}

          {result !== null ? (
            <FeedbackPanel
              result={result}
              profile={profileSnapshot}
              selectedScenarioId={selectedScenarioId}
            />
          ) : null}
        </section>

        <StructuredSection title="练习变体" value={practiceVariants} />
        <ListSection title="常见错误" items={
          Array.isArray(unit.common_errors)
            ? unit.common_errors.filter(
                (item): item is string => typeof item === "string",
              )
            : []
        } />
        <ListSection title="补强建议" items={
          Array.isArray(unit.remediation)
            ? unit.remediation.filter(
                (item): item is string => typeof item === "string",
              )
            : []
        } />
        <StructuredSection title="学习路径" value={unit.learning_path} />

        <section className="lesson-section lesson-section--review">
          <h2>内容复核</h2>
          <p>
            已关联 {Array.isArray(unit.review_records) ? unit.review_records.length : 0}
            条内部复核记录。这里只展示发布结论，不显示内部评估载荷。
          </p>
          <dl>
            <div>
              <dt>复核结论</dt>
              <dd>{unit.review_status}</dd>
            </div>
          </dl>
        </section>
      </div>
    </article>
  );
}
