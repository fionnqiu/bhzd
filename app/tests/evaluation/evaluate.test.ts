import { describe, expect, it } from "vitest";

import type { ExtensibleFields, TeachingUnit } from "../../src/data/contracts";
import { teachingUnits } from "../../src/data/rawData";
import { evaluateExercise } from "../../src/evaluation/evaluate";

const isRecord = (value: unknown): value is ExtensibleFields =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const requireRecord = (value: unknown, label: string): ExtensibleFields => {
  if (!isRecord(value)) {
    throw new Error(`Expected ${label} to be an object.`);
  }

  return value;
};

const requireArray = (value: unknown, label: string): unknown[] => {
  if (!Array.isArray(value)) {
    throw new Error(`Expected ${label} to be an array.`);
  }

  return value;
};

const requireString = (value: unknown, label: string): string => {
  if (typeof value !== "string") {
    throw new Error(`Expected ${label} to be a string.`);
  }

  return value;
};

const requireStringArray = (value: unknown, label: string): string[] => {
  const values = requireArray(value, label);

  if (!values.every((item) => typeof item === "string")) {
    throw new Error(`Expected ${label} to contain strings.`);
  }

  return values;
};

const findUnit = (id: string): TeachingUnit => {
  const unit = teachingUnits.units.find((candidate) => candidate.id === id);

  if (unit === undefined) {
    throw new Error(`Missing canonical teaching unit ${id}.`);
  }

  return unit;
};

const findUnitByMethod = (method: string): TeachingUnit => {
  const unit = teachingUnits.units.find(
    (candidate) => candidate.exercise.evaluation.method === method,
  );

  if (unit === undefined) {
    throw new Error(`Missing canonical ${method} teaching unit.`);
  }

  return unit;
};

const cloneUnit = (unit: TeachingUnit): TeachingUnit => structuredClone(unit);

describe("deterministic exercise evaluator", () => {
  for (const unit of teachingUnits.units) {
    it(`accepts the declared answer for ${unit.id}`, () => {
      const evaluation = requireRecord(
        unit.exercise.evaluation,
        `${unit.id} evaluation`,
      );
      const passScore = evaluation.pass_score;
      const result = evaluateExercise(unit, unit.exercise.answer);

      expect(result.passed).toBe(true);
      expect(result.score).toBeGreaterThanOrEqual(
        typeof passScore === "number" ? passScore : 1,
      );
      expect(result.matched).toBe(
        evaluation.method === "allowed_answers" ? "allowed_answer" : "answer",
      );
      expect(result.ruleRefs).toEqual(unit.rule_refs);
      expect(result.capabilityRefs).toEqual(
        requireStringArray(
          unit.exercise.capability_refs,
          `${unit.id} capability_refs`,
        ),
      );
      expect(result.evaluationVersion).toBe(
        requireString(evaluation.version, `${unit.id} evaluation version`),
      );
      expect(result.dataVersion).toBe(unit.exercise.data_version);
      expect(result.manualReviewRequired).toBe(false);
      expect(result.errorType).toBeNull();
    });
  }

  it("returns the declared exact-answer feedback", () => {
    const unit = findUnitByMethod("exact_match");
    const evaluation = requireRecord(unit.exercise.evaluation, "evaluation");
    const result = evaluateExercise(unit, unit.exercise.answer);

    expect(result).toEqual({
      score: 1,
      passed: true,
      matched: "answer",
      errorType: null,
      feedback:
        typeof evaluation.correct_feedback === "string"
          ? evaluation.correct_feedback
          : "回答正确。",
      remediation: [],
      ruleRefs: unit.rule_refs,
      capabilityRefs: unit.exercise.capability_refs,
      dataVersion: unit.exercise.data_version,
      evaluationVersion: evaluation.version,
      manualReviewRequired: false,
    });
  });

  it("ignores object-key order during structural comparison", () => {
    const unit = findUnitByMethod("exact_match");
    const entries = Object.entries(unit.exercise.answer).reverse();
    const reorderedAnswer = Object.fromEntries(entries);

    expect(evaluateExercise(unit, reorderedAnswer).passed).toBe(true);
  });

  it("preserves array order during structural comparison", () => {
    const unit = findUnit("TU-IMAGE-POLYGON-VERTICES-001");
    const submission = structuredClone(unit.exercise.answer);
    const vertices = requireArray(
      submission.ordered_vertices,
      "ordered_vertices",
    );
    submission.ordered_vertices = [...vertices].reverse();

    const result = evaluateExercise(unit, submission);

    expect(result.passed).toBe(false);
    expect(result.matched).toBe("unclassified");
  });

  it("matches a declared diagnostic rule before grading an answer", () => {
    const unit = findUnitByMethod("exact_match");
    const evaluation = requireRecord(unit.exercise.evaluation, "evaluation");
    const rules = requireArray(evaluation.diagnostic_rules, "diagnostic_rules");
    const rule = requireRecord(rules[0], "diagnostic rule");

    const result = evaluateExercise(unit, rule.submission);

    expect(result).toMatchObject({
      score: 0,
      passed: false,
      matched: "diagnostic_rule",
      errorType: rule.error_type,
      feedback: rule.feedback,
      remediation: rule.remediation,
      manualReviewRequired:
        typeof rule.manual_review_required === "boolean"
          ? rule.manual_review_required
          : false,
    });
  });

  it("uses the fixed score and review state of a declared allowed answer", () => {
    const unit = findUnit("TU-TEXT-INTENT-AMBIGUITY-001");
    const evaluation = requireRecord(unit.exercise.evaluation, "evaluation");
    const allowed = requireArray(evaluation.allowed_answers, "allowed_answers");
    const partialAnswer = requireRecord(allowed[1], "partial allowed answer");

    const result = evaluateExercise(unit, partialAnswer.answer);

    expect(result).toEqual({
      score: partialAnswer.score,
      passed: false,
      matched: "allowed_answer",
      errorType: partialAnswer.error_type,
      feedback: partialAnswer.feedback,
      remediation: partialAnswer.remediation,
      ruleRefs: unit.rule_refs,
      capabilityRefs: unit.exercise.capability_refs,
      dataVersion: unit.exercise.data_version,
      evaluationVersion: evaluation.version,
      manualReviewRequired: true,
    });
  });

  it.each([
    ["TU-AUDIO-LANGUAGE-DIALECT-001", true],
    ["TU-IMAGE-RECT-BOUNDS-001", false],
  ])(
    "uses declared unmatched review state for %s",
    (unitId, expectedManualReview) => {
      const unit = findUnit(unitId);
      const result = evaluateExercise(unit, {
        unmatched_submission_for: unit.id,
      });

      expect(result).toMatchObject({
        score: 0,
        passed: false,
        matched: "unclassified",
        manualReviewRequired: expectedManualReview,
      });
    },
  );

  it("uses top-level remediation for legacy string incorrect feedback", () => {
    const unit = cloneUnit(findUnitByMethod("exact_match"));
    const evaluation = requireRecord(unit.exercise.evaluation, "evaluation");
    const errorTypes = requireStringArray(
      unit.exercise.error_types,
      "error_types",
    );
    evaluation.incorrect_feedback = "未命中声明答案。";
    evaluation.default_error_type = errorTypes[0];
    unit.remediation = ["返回规则讲解后重试。"];

    expect(evaluateExercise(unit, "unmatched")).toMatchObject({
      matched: "unclassified",
      errorType: errorTypes[0],
      feedback: "未命中声明答案。",
      remediation: ["返回规则讲解后重试。"],
    });
  });

  it("does not trim or case-normalize string submissions", () => {
    const unit = findUnit("TU-TEXT-DOCUMENT-CLASSIFY-001");

    const result = evaluateExercise(unit, { labels: ["SHIPPING_QUERY "] });

    expect(result.passed).toBe(false);
    expect(result.matched).toBe("unclassified");
  });

  it("compares primitive values strictly", () => {
    const unit = cloneUnit(findUnitByMethod("exact_match"));
    unit.exercise.answer = { value: 1 };

    expect(evaluateExercise(unit, { value: true }).passed).toBe(false);
  });

  it("does not mutate the unit or submission and returns independent arrays", () => {
    const unit = cloneUnit(findUnit("TU-TEXT-INTENT-AMBIGUITY-001"));
    const evaluation = requireRecord(unit.exercise.evaluation, "evaluation");
    const allowed = requireArray(evaluation.allowed_answers, "allowed_answers");
    const candidate = requireRecord(allowed[1], "allowed answer");
    const submission = structuredClone(candidate.answer);
    const unitSnapshot = structuredClone(unit);
    const submissionSnapshot = structuredClone(submission);

    const result = evaluateExercise(unit, submission);
    result.ruleRefs.push("KNG-MUTATION-PROBE");
    result.capabilityRefs.push("CAP-MUTATION-PROBE");
    result.remediation.push("mutation probe");

    expect(unit).toEqual(unitSnapshot);
    expect(submission).toEqual(submissionSnapshot);
  });

  it("throws a stable error when evaluation is missing", () => {
    const unit = cloneUnit(findUnitByMethod("exact_match"));
    Reflect.set(unit.exercise, "evaluation", null);

    expect(() => evaluateExercise(unit, unit.exercise.answer)).toThrowError(
      new TypeError("unit.exercise.evaluation must be an object"),
    );
  });

  it("throws a stable error for an unsupported evaluation method", () => {
    const unit = cloneUnit(findUnitByMethod("exact_match"));
    unit.exercise.evaluation.method = "fuzzy_match";

    expect(() => evaluateExercise(unit, unit.exercise.answer)).toThrowError(
      new TypeError("unsupported evaluation method: 'fuzzy_match'"),
    );
  });

  it("throws a stable error for malformed diagnostic rules", () => {
    const unit = cloneUnit(findUnitByMethod("exact_match"));
    unit.exercise.evaluation.diagnostic_rules = {};

    expect(() => evaluateExercise(unit, unit.exercise.answer)).toThrowError(
      new TypeError("diagnostic_rules must be a list"),
    );
  });

  it("does not treat a null diagnostic_rules field as omitted", () => {
    const unit = cloneUnit(findUnitByMethod("exact_match"));
    unit.exercise.evaluation.diagnostic_rules = null;

    expect(() => evaluateExercise(unit, unit.exercise.answer)).toThrowError(
      new TypeError("diagnostic_rules must be a list"),
    );
  });

  it("does not treat a null pass_score field as omitted", () => {
    const unit = cloneUnit(findUnitByMethod("allowed_answers"));
    unit.exercise.evaluation.pass_score = null;

    expect(() => evaluateExercise(unit, unit.exercise.answer)).toThrowError(
      new TypeError("unit.exercise.evaluation.pass_score must be numeric"),
    );
  });

  it("reports a stable numeric error for a string pass_score", () => {
    const unit = cloneUnit(findUnitByMethod("allowed_answers"));
    unit.exercise.evaluation.pass_score = "1";

    expect(() => evaluateExercise(unit, unit.exercise.answer)).toThrowError(
      new TypeError("unit.exercise.evaluation.pass_score must be numeric"),
    );
  });
});
