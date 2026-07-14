// @vitest-environment node

import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import type { ExtensibleFields, TeachingUnit } from "../../src/data/contracts";
import { teachingUnits } from "../../src/data/rawData";
import { evaluateExercise } from "../../src/evaluation/evaluate";

interface PythonEvaluationResult {
  score: number;
  passed: boolean;
  rule_refs: string[];
  capability_refs: string[];
  error_type: string | null;
  feedback: string;
  remediation: string[];
  manual_review_required: boolean;
  data_version: string;
  evaluation_version: string;
}

const repoRoot = fileURLToPath(new URL("../../../", import.meta.url));

const isRecord = (value: unknown): value is ExtensibleFields =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === "string");

const isPythonEvaluationResult = (
  value: unknown,
): value is PythonEvaluationResult =>
  isRecord(value) &&
  typeof value.score === "number" &&
  typeof value.passed === "boolean" &&
  isStringArray(value.rule_refs) &&
  isStringArray(value.capability_refs) &&
  (typeof value.error_type === "string" || value.error_type === null) &&
  typeof value.feedback === "string" &&
  isStringArray(value.remediation) &&
  typeof value.manual_review_required === "boolean" &&
  typeof value.data_version === "string" &&
  typeof value.evaluation_version === "string";

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

const findUnitByMethod = (method: string): TeachingUnit => {
  const unit = teachingUnits.units.find(
    (candidate) => candidate.exercise.evaluation.method === method,
  );

  if (unit === undefined) {
    throw new Error(`Missing canonical ${method} teaching unit.`);
  }

  return unit;
};

const serializeSubmission = (submission: unknown): string => {
  const serialized = JSON.stringify(submission);

  if (serialized === undefined) {
    throw new Error("Parity submission is not JSON serializable.");
  }

  return serialized;
};

const evaluateWithPython = (
  unit: TeachingUnit,
  submission: unknown,
): PythonEvaluationResult => {
  const arguments_ = [
    "scripts/evaluate_exercise.py",
    "--unit-file",
    "data/curriculum/teaching-units.json",
    "--unit-id",
    unit.id,
    "--submission",
    serializeSubmission(submission),
  ];
  const execution = spawnSync("python", arguments_, {
    cwd: repoRoot,
    encoding: "utf8",
    maxBuffer: 1024 * 1024,
    shell: false,
    timeout: 15_000,
  });

  if (execution.error !== undefined) {
    throw new Error(
      `Python evaluator failed to start for ${unit.id}: ${execution.error.message}`,
    );
  }

  if (execution.status !== 0) {
    throw new Error(
      [
        `Python evaluator exited with status ${String(execution.status)} for ${unit.id}.`,
        `stderr: ${execution.stderr.trim() || "<empty>"}`,
        `stdout: ${execution.stdout.trim() || "<empty>"}`,
      ].join("\n"),
    );
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(execution.stdout);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(
      `Python evaluator returned invalid JSON for ${unit.id}: ${message}\nstdout: ${execution.stdout}`,
    );
  }

  if (!isPythonEvaluationResult(parsed)) {
    throw new Error(
      `Python evaluator returned an invalid result shape for ${unit.id}: ${execution.stdout}`,
    );
  }

  return parsed;
};

const expectPythonParity = (
  unit: TeachingUnit,
  submission: unknown,
): void => {
  const python = evaluateWithPython(unit, submission);
  const typescript = evaluateExercise(unit, submission);

  expect({
    score: typescript.score,
    passed: typescript.passed,
    rule_refs: typescript.ruleRefs,
    capability_refs: typescript.capabilityRefs,
    error_type: typescript.errorType,
    feedback: typescript.feedback,
    remediation: typescript.remediation,
    manual_review_required: typescript.manualReviewRequired,
    data_version: typescript.dataVersion,
    evaluation_version: typescript.evaluationVersion,
  }).toEqual(python);
};

describe("Python evaluator parity", () => {
  for (const unit of teachingUnits.units) {
    it(`matches Python for the declared answer of ${unit.id}`, () => {
      expectPythonParity(unit, unit.exercise.answer);
    });
  }

  for (const method of [
    "exact_match",
    "ordered_exact_match",
    "allowed_answers",
  ]) {
    const unit = findUnitByMethod(method);
    const evaluation = requireRecord(unit.exercise.evaluation, "evaluation");
    const diagnosticRules = requireArray(
      evaluation.diagnostic_rules,
      "diagnostic_rules",
    );
    const diagnostic = requireRecord(diagnosticRules[0], "diagnostic rule");

    it(`matches Python for a ${method} diagnostic submission`, () => {
      expectPythonParity(unit, diagnostic.submission);
    });

    it(`matches Python for a ${method} unmatched submission`, () => {
      expectPythonParity(unit, { unmatched_python_parity_method: method });
    });
  }

  it("matches Python for a partial allowed answer", () => {
    const unit = findUnitByMethod("allowed_answers");
    const evaluation = requireRecord(unit.exercise.evaluation, "evaluation");
    const allowedAnswers = requireArray(
      evaluation.allowed_answers,
      "allowed_answers",
    );
    const partialAnswer = requireRecord(allowedAnswers[1], "allowed answer");

    expectPythonParity(unit, partialAnswer.answer);
  });
});
