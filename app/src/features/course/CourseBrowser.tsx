import { useEffect, useId, useMemo, useRef } from "react";

import {
  DOMAIN_LABELS,
  type Domain,
} from "../../app/AppContext";
import { Button } from "../../components/Button";
import type { TeachingUnit } from "../../data/contracts";
import type {
  ConsumableUnitSource,
  ConsumableUnitSummary,
} from "../dashboard/Dashboard";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isStringList = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === "string");

export const isConsumableTeachingUnit = (
  summary: ConsumableUnitSummary,
): summary is TeachingUnit => {
  const unit: unknown = summary;
  if (!isRecord(unit) || !isRecord(unit.exercise)) {
    return false;
  }

  return (
    typeof unit.id === "string" &&
    unit.id.trim().length > 0 &&
    typeof unit.data_type === "string" &&
    typeof unit.title === "string" &&
    unit.title.trim().length > 0 &&
    unit.review_status === "published" &&
    unit.student_visible === true &&
    isStringList(unit.learning_objectives) &&
    isStringList(unit.prerequisites) &&
    isStringList(unit.rule_refs) &&
    isStringList(unit.source_refs) &&
    typeof unit.exercise.data_version === "string" &&
    isRecord(unit.exercise.input) &&
    typeof unit.exercise.student_action === "string" &&
    isRecord(unit.exercise.answer) &&
    isRecord(unit.exercise.evaluation)
  );
};

interface CourseBrowserProps {
  repository: ConsumableUnitSource;
  domain: Domain;
  focusUnitId?: string | null;
  onFocusRestored?(): void;
  onOpenUnit(unit: TeachingUnit): void;
}

export function CourseBrowser({
  repository,
  domain,
  focusUnitId = null,
  onFocusRestored,
  onOpenUnit,
}: CourseBrowserProps) {
  const headingId = useId();
  const courseButtonRefs = useRef(new Map<string, HTMLButtonElement>());
  const units = useMemo(
    () =>
      repository
        .listConsumableUnits()
        .filter(isConsumableTeachingUnit)
        .filter((unit) => unit.data_type === domain),
    [domain, repository],
  );
  const domainLabel = DOMAIN_LABELS[domain];

  useEffect(() => {
    if (focusUnitId === null) {
      return;
    }

    const trigger = courseButtonRefs.current.get(focusUnitId);
    if (trigger === undefined) {
      return;
    }

    trigger.focus();
    onFocusRestored?.();
  }, [focusUnitId, onFocusRestored]);

  return (
    <section className="course-browser" aria-labelledby={headingId}>
      <div className="course-browser__header">
        <div>
          <p className="eyebrow eyebrow--ink">COURSE FIX / {domain.toUpperCase()}</p>
          <h1 id={headingId}>{domainLabel}课程航线</h1>
        </div>
        <p className="course-browser__count">
          <strong>{units.length}</strong>
          <span>个已发布单元</span>
        </p>
      </div>

      <p className="course-browser__lede">
        选择一个教学单元，沿规则说明、结构化练习、确定性反馈与掌握度记录完成闭环。
      </p>

      {units.length === 0 ? (
        <p className="course-browser__empty" role="status">
          当前数据域没有可安全打开的完整已发布课程。
        </p>
      ) : (
        <ol className="course-list">
          {units.map((unit, index) => (
            <li key={unit.id} className="course-card">
              <span className="course-card__index" aria-hidden="true">
                {String(index + 1).padStart(2, "0")}
              </span>
              <div className="course-card__body">
                <p className="course-card__id">{unit.id}</p>
                <h2>{unit.title}</h2>
                <p>
                  {unit.learning_objectives[0] ??
                    "进入课程查看完整教学目标与练习说明。"}
                </p>
                <dl className="course-card__facts">
                  <div>
                    <dt>规则</dt>
                    <dd>{unit.rule_refs.length}</dd>
                  </div>
                  <div>
                    <dt>先修</dt>
                    <dd>{unit.prerequisites.length}</dd>
                  </div>
                  <div>
                    <dt>数据版本</dt>
                    <dd>{unit.exercise.data_version}</dd>
                  </div>
                </dl>
              </div>
              <Button
                ref={(element) => {
                  if (element === null) {
                    courseButtonRefs.current.delete(unit.id);
                  } else {
                    courseButtonRefs.current.set(unit.id, element);
                  }
                }}
                variant="primary"
                aria-label={`打开课程：${unit.title}`}
                onClick={() => onOpenUnit(unit)}
              >
                进入课程
              </Button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
