import type { ExtensibleFields, TeachingUnit } from "../data/contracts";

export type EvaluationMatch =
  | "diagnostic_rule"
  | "allowed_answer"
  | "answer"
  | "unclassified";

export interface EvaluationResult {
  score: number;
  passed: boolean;
  matched: EvaluationMatch;
  errorType: string | null;
  feedback: string;
  remediation: string[];
  ruleRefs: string[];
  capabilityRefs: string[];
  dataVersion: string;
  evaluationVersion: string;
  manualReviewRequired: boolean;
}

type EvaluationMethod =
  | "exact_match"
  | "ordered_exact_match"
  | "allowed_answers";

interface DiagnosticRule {
  submission: unknown;
  errorType: string;
  feedback: string;
  remediation: string[];
  manualReviewRequired: boolean;
}

interface AllowedAnswer {
  answer: unknown;
  score: number;
  manualReviewRequired: boolean;
  errorType: string | null;
  feedback: string;
  remediation: string[];
}

const isRecord = (value: unknown): value is ExtensibleFields =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isPlainRecord = (value: unknown): value is ExtensibleFields => {
  if (!isRecord(value)) {
    return false;
  }

  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
};

const hasOwn = (record: ExtensibleFields, key: string): boolean =>
  Object.prototype.hasOwnProperty.call(record, key);

const fail = (message: string): never => {
  throw new TypeError(message);
};

const requireRecord = (value: unknown, field: string): ExtensibleFields => {
  if (!isRecord(value)) {
    return fail(`${field} must be an object`);
  }

  return value;
};

const requireString = (value: unknown, field: string): string => {
  if (typeof value !== "string" || value.trim().length === 0) {
    return fail(`${field} must be a non-empty string`);
  }

  return value;
};

const requireStringList = (value: unknown, field: string): string[] => {
  if (!Array.isArray(value) || value.length === 0) {
    return fail(`${field} must be a non-empty list`);
  }

  const result: string[] = [];
  for (const item of value) {
    if (typeof item !== "string" || item.trim().length === 0) {
      return fail(`${field} must contain non-empty strings`);
    }
    result.push(item);
  }

  return result;
};

const requireUnitIntervalNumber = (value: unknown, field: string): number => {
  if (typeof value !== "number") {
    return fail(`${field} must be numeric`);
  }
  if (!Number.isFinite(value) || value < 0 || value > 1) {
    return fail(`${field} must be finite and within [0, 1]`);
  }

  return value;
};

const pythonRepr = (value: unknown): string => {
  if (value === null || value === undefined) {
    return "None";
  }
  if (typeof value === "string") {
    return `'${value.replaceAll("\\", "\\\\").replaceAll("'", "\\'")}'`;
  }
  if (typeof value === "boolean") {
    return value ? "True" : "False";
  }

  return String(value);
};

const requireMethod = (value: unknown): EvaluationMethod => {
  if (
    value !== "exact_match" &&
    value !== "ordered_exact_match" &&
    value !== "allowed_answers"
  ) {
    return fail(`unsupported evaluation method: ${pythonRepr(value)}`);
  }

  return value;
};

const assertJsonValue = (
  value: unknown,
  field: string,
  ancestors = new Set<object>(),
): void => {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean"
  ) {
    return;
  }

  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      fail(`${field} must be JSON-compatible`);
    }
    return;
  }

  if (typeof value !== "object") {
    return fail(`${field} must be JSON-compatible`);
  }

  if (ancestors.has(value)) {
    fail(`${field} must not contain circular references`);
  }
  ancestors.add(value);

  if (Array.isArray(value)) {
    for (const item of value) {
      assertJsonValue(item, field, ancestors);
    }
    ancestors.delete(value);
    return;
  }

  if (!isPlainRecord(value)) {
    return fail(`${field} must be JSON-compatible`);
  }

  for (const nested of Object.values(value)) {
    assertJsonValue(nested, field, ancestors);
  }
  ancestors.delete(value);
};

const deepEqualJson = (left: unknown, right: unknown): boolean => {
  if (left === right) {
    return true;
  }

  if (Array.isArray(left) || Array.isArray(right)) {
    if (!Array.isArray(left) || !Array.isArray(right)) {
      return false;
    }
    if (left.length !== right.length) {
      return false;
    }

    return left.every((item, index) => deepEqualJson(item, right[index]));
  }

  if (!isPlainRecord(left) || !isPlainRecord(right)) {
    return false;
  }

  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  if (leftKeys.length !== rightKeys.length) {
    return false;
  }

  return leftKeys.every(
    (key) => hasOwn(right, key) && deepEqualJson(left[key], right[key]),
  );
};

const validateDiagnosticRules = (
  evaluation: ExtensibleFields,
  errorTypes: readonly string[],
): DiagnosticRule[] => {
  const rawRules = hasOwn(evaluation, "diagnostic_rules")
    ? evaluation.diagnostic_rules
    : [];
  if (!Array.isArray(rawRules)) {
    return fail("diagnostic_rules must be a list");
  }

  if (rawRules.length > 0) {
    requireString(
      evaluation.diagnostic_precedence,
      "unit.exercise.evaluation.diagnostic_precedence",
    );
  }

  const rules: DiagnosticRule[] = [];
  const requiredFields = [
    "error_type",
    "feedback",
    "remediation",
    "submission",
  ];

  for (const [index, value] of rawRules.entries()) {
    const rule = requireRecord(value, `diagnostic_rules[${index}]`);
    const missing = requiredFields.find((field) => !hasOwn(rule, field));
    if (missing !== undefined) {
      fail(`diagnostic_rules[${index}] missing required field: ${missing}`);
    }

    assertJsonValue(rule.submission, `diagnostic_rules[${index}].submission`);
    if (
      rules.some((candidate) =>
        deepEqualJson(candidate.submission, rule.submission),
      )
    ) {
      fail("diagnostic_rules contains duplicate canonical submissions");
    }

    const errorType = rule.error_type;
    if (typeof errorType !== "string" || !errorTypes.includes(errorType)) {
      return fail(
        `diagnostic_rules[${index}].error_type must be declared in error_types`,
      );
    }

    const feedback = requireString(
      rule.feedback,
      `diagnostic_rules[${index}].feedback`,
    );
    const remediation = requireStringList(
      rule.remediation,
      `diagnostic_rules[${index}].remediation`,
    );
    const manualReview = hasOwn(rule, "manual_review_required")
      ? rule.manual_review_required
      : false;
    if (typeof manualReview !== "boolean") {
      return fail(
        `diagnostic_rules[${index}].manual_review_required must be boolean`,
      );
    }

    rules.push({
      submission: rule.submission,
      errorType,
      feedback,
      remediation,
      manualReviewRequired: manualReview,
    });
  }

  return rules;
};

const validateAllowedAnswers = (
  evaluation: ExtensibleFields,
  errorTypes: readonly string[],
): AllowedAnswer[] => {
  const rawAllowedAnswers = evaluation.allowed_answers;
  if (!Array.isArray(rawAllowedAnswers) || rawAllowedAnswers.length === 0) {
    return fail("allowed_answers evaluation requires at least one answer");
  }

  const allowedAnswers: AllowedAnswer[] = [];
  const requiredFields = [
    "answer",
    "error_type",
    "feedback",
    "manual_review_required",
    "remediation",
    "score",
  ];

  for (const [index, value] of rawAllowedAnswers.entries()) {
    const candidate = requireRecord(value, `allowed_answers[${index}]`);
    const missing = requiredFields.find((field) => !hasOwn(candidate, field));
    if (missing !== undefined) {
      fail(`allowed_answers[${index}] missing required field: ${missing}`);
    }

    assertJsonValue(candidate.answer, `allowed_answers[${index}].answer`);
    if (
      allowedAnswers.some((allowed) =>
        deepEqualJson(allowed.answer, candidate.answer),
      )
    ) {
      fail("allowed_answers contains duplicate canonical answers");
    }
    const score = requireUnitIntervalNumber(
      candidate.score,
      `allowed_answers[${index}].score`,
    );
    if (typeof candidate.manual_review_required !== "boolean") {
      return fail(
        `allowed_answers[${index}].manual_review_required must be boolean`,
      );
    }

    const errorType = candidate.error_type;
    if (
      errorType !== null &&
      (typeof errorType !== "string" || !errorTypes.includes(errorType))
    ) {
      return fail(
        `allowed_answers[${index}].error_type must be null or declared`,
      );
    }

    const feedback = requireString(
      candidate.feedback,
      `allowed_answers[${index}].feedback`,
    );
    const remediation = requireStringList(
      candidate.remediation,
      `allowed_answers[${index}].remediation`,
    );

    allowedAnswers.push({
      answer: candidate.answer,
      score,
      manualReviewRequired: candidate.manual_review_required,
      errorType,
      feedback,
      remediation,
    });
  }

  return allowedAnswers;
};

const pythonTruthiness = (value: unknown): boolean => {
  if (value === null || value === undefined) {
    return false;
  }
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    return value !== 0 && !Number.isNaN(value);
  }
  if (typeof value === "string" || Array.isArray(value)) {
    return value.length > 0;
  }
  if (isRecord(value)) {
    return Object.keys(value).length > 0;
  }

  return true;
};

const createBaseResult = (
  unit: TeachingUnit,
  exercise: ExtensibleFields,
  evaluation: ExtensibleFields,
): EvaluationResult => ({
  score: 0,
  passed: false,
  matched: "unclassified",
  errorType: null,
  feedback: "",
  remediation: [],
  ruleRefs: requireStringList(unit.rule_refs, "unit.rule_refs"),
  capabilityRefs: requireStringList(
    exercise.capability_refs,
    "unit.exercise.capability_refs",
  ),
  dataVersion: requireString(exercise.data_version, "unit.exercise.data_version"),
  evaluationVersion: requireString(
    evaluation.version,
    "unit.exercise.evaluation.version",
  ),
  manualReviewRequired: false,
});

const getDefaultErrorType = (
  evaluation: ExtensibleFields,
  errorTypes: readonly string[],
): unknown =>
  hasOwn(evaluation, "default_error_type")
    ? evaluation.default_error_type
    : errorTypes[0];

const createIncorrectResult = (
  unit: TeachingUnit,
  evaluation: ExtensibleFields,
  errorTypes: readonly string[],
  base: EvaluationResult,
): EvaluationResult => {
  const incorrectFeedback = evaluation.incorrect_feedback;
  let errorTypeValue: unknown;
  let feedback: string;
  let remediation: string[];

  if (isRecord(incorrectFeedback)) {
    errorTypeValue = hasOwn(incorrectFeedback, "error_type")
      ? incorrectFeedback.error_type
      : getDefaultErrorType(evaluation, errorTypes);
    feedback = requireString(
      incorrectFeedback.feedback,
      "unit.exercise.evaluation.incorrect_feedback.feedback",
    );
    remediation = requireStringList(
      incorrectFeedback.remediation,
      "unit.exercise.evaluation.incorrect_feedback.remediation",
    );
  } else {
    errorTypeValue = getDefaultErrorType(evaluation, errorTypes);
    feedback = requireString(
      incorrectFeedback,
      "unit.exercise.evaluation.incorrect_feedback",
    );
    remediation = requireStringList(unit.remediation, "unit.remediation");
  }

  if (
    typeof errorTypeValue !== "string" ||
    !errorTypes.includes(errorTypeValue)
  ) {
    return fail("incorrect_feedback.error_type must be declared in error_types");
  }

  return {
    ...base,
    errorType: errorTypeValue,
    feedback,
    remediation,
    manualReviewRequired: pythonTruthiness(
      evaluation.manual_review_on_unmatched,
    ),
  };
};

export const evaluateExercise = (
  unit: TeachingUnit,
  submission: unknown,
): EvaluationResult => {
  const exercise = requireRecord(unit.exercise, "unit.exercise");
  const evaluation = requireRecord(
    exercise.evaluation,
    "unit.exercise.evaluation",
  );
  const base = createBaseResult(unit, exercise, evaluation);
  const method = requireMethod(evaluation.method);
  const errorTypes = requireStringList(
    exercise.error_types,
    "unit.exercise.error_types",
  );
  const diagnosticRules = validateDiagnosticRules(evaluation, errorTypes);

  let allowedAnswers: AllowedAnswer[] = [];
  let passScore = 1;
  if (method === "allowed_answers") {
    allowedAnswers = validateAllowedAnswers(evaluation, errorTypes);
    passScore = requireUnitIntervalNumber(
      hasOwn(evaluation, "pass_score") ? evaluation.pass_score : 1,
      "unit.exercise.evaluation.pass_score",
    );
  }

  let answerValues: unknown[];
  if (method === "exact_match" || method === "ordered_exact_match") {
    if (!hasOwn(exercise, "answer")) {
      return fail("exact evaluation requires unit.exercise.answer");
    }
    assertJsonValue(exercise.answer, "unit.exercise.answer");
    answerValues = [exercise.answer];
  } else {
    answerValues = allowedAnswers.map((candidate) => candidate.answer);
  }

  if (
    diagnosticRules.some((rule) =>
      answerValues.some((answer) => deepEqualJson(rule.submission, answer)),
    )
  ) {
    return fail("diagnostic submission overlap with standard or allowed answer");
  }

  assertJsonValue(submission, "submission");

  for (const rule of diagnosticRules) {
    if (!deepEqualJson(rule.submission, submission)) {
      continue;
    }

    return {
      ...base,
      matched: "diagnostic_rule",
      errorType: rule.errorType,
      feedback: rule.feedback,
      remediation: [...rule.remediation],
      manualReviewRequired: rule.manualReviewRequired,
    };
  }

  if (method === "exact_match" || method === "ordered_exact_match") {
    if (deepEqualJson(submission, exercise.answer)) {
      const feedback = hasOwn(evaluation, "correct_feedback")
        ? requireString(
            evaluation.correct_feedback,
            "unit.exercise.evaluation.correct_feedback",
          )
        : "回答正确。";

      return {
        ...base,
        score: 1,
        passed: true,
        matched: "answer",
        feedback,
      };
    }

    return createIncorrectResult(unit, evaluation, errorTypes, base);
  }

  for (const candidate of allowedAnswers) {
    if (!deepEqualJson(candidate.answer, submission)) {
      continue;
    }

    return {
      ...base,
      score: candidate.score,
      passed:
        candidate.score >= passScore && !candidate.manualReviewRequired,
      matched: "allowed_answer",
      errorType: candidate.errorType,
      feedback: candidate.feedback,
      remediation: [...candidate.remediation],
      manualReviewRequired: candidate.manualReviewRequired,
    };
  }

  return createIncorrectResult(unit, evaluation, errorTypes, base);
};
