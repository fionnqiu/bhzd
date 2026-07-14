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

interface PythonCommand {
  executable: string;
  prefixArguments: string[];
}

interface PythonProbeResult {
  compatible: boolean;
  failure: string;
}

type PythonCandidateProbe = (candidate: PythonCommand) => PythonProbeResult;

const repoRoot = fileURLToPath(new URL("../../../", import.meta.url));

const stripSurroundingQuotes = (value: string): string =>
  value.startsWith('"') && value.endsWith('"') ? value.slice(1, -1) : value;

const configuredPythonCommand = (value: string): PythonCommand => {
  const trimmed = value.trim();
  const withoutLauncherArgument = trimmed.replace(/\s+-3$/u, "");
  const executable = stripSurroundingQuotes(withoutLauncherArgument);
  const executableName = executable.replace(/^.*[\\/]/u, "").toLowerCase();
  const usesLauncherArgument =
    withoutLauncherArgument !== trimmed &&
    (executableName === "py" || executableName === "py.exe");

  return {
    executable: usesLauncherArgument ? executable : stripSurroundingQuotes(trimmed),
    prefixArguments: usesLauncherArgument ? ["-3"] : [],
  };
};

const pythonCandidates = (): PythonCommand[] => {
  const configured = process.env.PYTHON?.trim();
  const candidates: PythonCommand[] = [];
  if (configured !== undefined && configured.length > 0) {
    candidates.push(configuredPythonCommand(configured));
  }
  candidates.push(
    { executable: "python", prefixArguments: [] },
    { executable: "python3", prefixArguments: [] },
    { executable: "py", prefixArguments: ["-3"] },
  );

  const seen = new Set<string>();
  return candidates.filter((candidate) => {
    const key = JSON.stringify([candidate.executable, ...candidate.prefixArguments]);
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
};

const selectCompatiblePythonCommand = (
  candidates: readonly PythonCommand[],
  probe: PythonCandidateProbe,
): PythonCommand => {
  const failures: string[] = [];
  for (const candidate of candidates) {
    const result = probe(candidate);
    if (result.compatible) {
      return candidate;
    }
    failures.push(
      `${candidate.executable} ${candidate.prefixArguments.join(" ")}: ${result.failure}`,
    );
  }

  throw new Error(
    `No usable Python 3.11+ evaluator runtime found. ${failures.join("; ")}`,
  );
};

const pythonCompatibilityScript = [
  "import sys",
  "if sys.version_info < (3, 11):",
  "    raise SystemExit('Python 3.11+ required')",
  "import scripts.evaluate_exercise",
].join("\n");

const probePythonCandidate = (candidate: PythonCommand): PythonProbeResult => {
  const execution = spawnSync(
    candidate.executable,
    [...candidate.prefixArguments, "-c", pythonCompatibilityScript],
    {
      cwd: repoRoot,
      encoding: "utf8",
      shell: false,
      timeout: 5_000,
      windowsHide: true,
    },
  );
  if (execution.error === undefined && execution.status === 0) {
    return { compatible: true, failure: "" };
  }

  const output = [execution.stderr.trim(), execution.stdout.trim()]
    .filter((value) => value.length > 0)
    .join(" | ");
  return {
    compatible: false,
    failure:
      execution.error?.message ??
      `status ${String(execution.status)}${output.length > 0 ? `: ${output}` : ""}`,
  };
};

const resolvePythonCommand = (): PythonCommand =>
  selectCompatiblePythonCommand(pythonCandidates(), probePythonCandidate);

const pythonCommand = resolvePythonCommand();

const runPython = (arguments_: readonly string[], context: string): string => {
  const execution = spawnSync(
    pythonCommand.executable,
    [...pythonCommand.prefixArguments, ...arguments_],
    {
      cwd: repoRoot,
      encoding: "utf8",
      maxBuffer: 1024 * 1024,
      shell: false,
      timeout: 15_000,
      windowsHide: true,
    },
  );

  if (execution.error !== undefined) {
    throw new Error(
      `Python evaluator failed to start for ${context}: ${execution.error.message}`,
    );
  }

  if (execution.status !== 0) {
    throw new Error(
      [
        `Python evaluator exited with status ${String(execution.status)} for ${context}.`,
        `stderr: ${execution.stderr.trim() || "<empty>"}`,
        `stdout: ${execution.stdout.trim() || "<empty>"}`,
      ].join("\n"),
    );
  }

  return execution.stdout;
};

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

const parsePythonEvaluationResult = (
  stdout: string,
  context: string,
): PythonEvaluationResult => {
  let parsed: unknown;
  try {
    parsed = JSON.parse(stdout);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(
      `Python evaluator returned invalid JSON for ${context}: ${message}\nstdout: ${stdout}`,
    );
  }

  if (!isPythonEvaluationResult(parsed)) {
    throw new Error(
      `Python evaluator returned an invalid result shape for ${context}: ${stdout}`,
    );
  }

  return parsed;
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
  return parsePythonEvaluationResult(runPython(arguments_, unit.id), unit.id);
};

const commonTypeScriptResult = (
  result: ReturnType<typeof evaluateExercise>,
): PythonEvaluationResult => ({
  score: result.score,
  passed: result.passed,
  rule_refs: result.ruleRefs,
  capability_refs: result.capabilityRefs,
  error_type: result.errorType,
  feedback: result.feedback,
  remediation: result.remediation,
  manual_review_required: result.manualReviewRequired,
  data_version: result.dataVersion,
  evaluation_version: result.evaluationVersion,
});

const rawEvaluationScript = [
  "import base64, json, sys",
  "from scripts.evaluate_exercise import evaluate_unit, serialize_result",
  "unit = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))",
  "submission = json.loads(base64.b64decode(sys.argv[2]).decode('utf-8'))",
  "output = serialize_result(evaluate_unit(unit, submission))",
  "sys.stdout.buffer.write((output + '\\n').encode('utf-8'))",
].join("\n");

const rawEvaluationOutcomeScript = [
  "import base64, json, sys",
  "from scripts.evaluate_exercise import evaluate_unit",
  "unit = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))",
  "submission = json.loads(base64.b64decode(sys.argv[2]).decode('utf-8'))",
  "try:",
  "    evaluate_unit(unit, submission)",
  "except Exception as error:",
  "    output = json.dumps({'ok': False, 'message': str(error)}, ensure_ascii=False)",
  "else:",
  "    output = json.dumps({'ok': True}, ensure_ascii=False)",
  "sys.stdout.buffer.write((output + '\\n').encode('utf-8'))",
].join("\n");

const canonicalNumericAuditScript = [
  "import json, math",
  "from pathlib import Path",
  "from scripts.evaluate_exercise import canonical_json",
  "class RawInt(int):",
  "    def __new__(cls, token):",
  "        value = super().__new__(cls, token)",
  "        value.token = token",
  "        return value",
  "class RawFloat(float):",
  "    pass",
  "with Path('data/curriculum/teaching-units.json').open(encoding='utf-8') as handle:",
  "    document = json.load(handle, parse_int=RawInt, parse_float=RawFloat)",
  "issues = []",
  "def audit(value, path, target):",
  "    if isinstance(value, bool) or value is None or isinstance(value, str):",
  "        return",
  "    if isinstance(value, RawInt):",
  "        if value.token == '-0':",
  "            target.append(f'{path}: integer token -0 is unsupported')",
  "        elif abs(value) > 9007199254740991:",
  "            target.append(f'{path}: unsafe integer {value}')",
  "        return",
  "    if isinstance(value, RawFloat):",
  "        if not math.isfinite(value):",
  "            target.append(f'{path}: non-finite float')",
  "        elif value.is_integer():",
  "            target.append(f'{path}: integer-valued float {value!r}')",
  "        return",
  "    if isinstance(value, list):",
  "        for index, item in enumerate(value):",
  "            audit(item, f'{path}[{index}]', target)",
  "        return",
  "    if isinstance(value, dict):",
  "        for key, item in value.items():",
  "            audit(item, f'{path}.{key}', target)",
  "def audit_exercise(exercise, path):",
  "    if 'answer' in exercise:",
  "        audit(exercise['answer'], f'{path}.answer', issues)",
  "    evaluation = exercise.get('evaluation', {})",
  "    for index, rule in enumerate(evaluation.get('diagnostic_rules', [])):",
  "        audit(rule.get('submission'), f'{path}.evaluation.diagnostic_rules[{index}].submission', issues)",
  "    for index, candidate in enumerate(evaluation.get('allowed_answers', [])):",
  "        audit(candidate.get('answer'), f'{path}.evaluation.allowed_answers[{index}].answer', issues)",
  "for unit_index, unit in enumerate(document['units']):",
  "    audit_exercise(unit['exercise'], f'units[{unit_index}].exercise')",
  "    for variant_index, variant in enumerate(unit.get('practice_variants', [])):",
  "        audit_exercise(variant, f'units[{unit_index}].practice_variants[{variant_index}]')",
  "negative_zero_integer_issues = []",
  "negative_zero_integer = json.loads('-0', parse_int=RawInt, parse_float=RawFloat)",
  "audit(negative_zero_integer, 'probe', negative_zero_integer_issues)",
  "print(json.dumps({'issues': issues, 'negative_zero_integer_issues': negative_zero_integer_issues, 'one': canonical_json(1), 'one_float': canonical_json(1.0)}, ensure_ascii=False))",
].join("\n");

const evaluateRawWithPython = (
  rawUnit: string,
  rawSubmission: string,
  context: string,
): PythonEvaluationResult =>
  parsePythonEvaluationResult(
    runPython(
      [
        "-c",
        rawEvaluationScript,
        Buffer.from(rawUnit, "utf8").toString("base64"),
        Buffer.from(rawSubmission, "utf8").toString("base64"),
      ],
      context,
    ),
    context,
  );

const evaluateRawFailureWithPython = (
  rawUnit: string,
  rawSubmission: string,
  context: string,
): string => {
  const stdout = runPython(
    [
      "-c",
      rawEvaluationOutcomeScript,
      Buffer.from(rawUnit, "utf8").toString("base64"),
      Buffer.from(rawSubmission, "utf8").toString("base64"),
    ],
    context,
  );
  const parsed: unknown = JSON.parse(stdout);
  const outcome = requireRecord(parsed, `${context} outcome`);
  if (outcome.ok !== false || typeof outcome.message !== "string") {
    throw new Error(`Expected Python failure for ${context}, received: ${stdout}`);
  }
  return outcome.message;
};

const injectRawJsonToken = (
  value: unknown,
  marker: string,
  rawToken: string,
): string => {
  const serialized = serializeSubmission(value);
  const pieces = serialized.split(serializeSubmission(marker));
  if (pieces.length !== 2) {
    throw new Error(`Expected exactly one raw JSON marker ${marker}.`);
  }
  return `${pieces[0]}${rawToken}${pieces[1]}`;
};

const captureErrorMessage = (operation: () => unknown): string => {
  try {
    operation();
  } catch (error) {
    if (error instanceof Error) {
      return error.message;
    }
    throw error;
  }
  throw new Error("Expected operation to fail.");
};

const expectPythonParity = (
  unit: TeachingUnit,
  submission: unknown,
): void => {
  const python = evaluateWithPython(unit, submission);
  const typescript = evaluateExercise(unit, submission);

  expect(commonTypeScriptResult(typescript)).toEqual(python);
};

describe("Python evaluator parity", () => {
  it("skips an incompatible Python candidate and selects the next one", () => {
    const incompatible = {
      executable: "python-incompatible",
      prefixArguments: [],
    };
    const compatible = {
      executable: "python-compatible",
      prefixArguments: ["-X", "utf8"],
    };
    const probed: string[] = [];

    const selected = selectCompatiblePythonCommand(
      [incompatible, compatible],
      (candidate) => {
        probed.push(candidate.executable);
        return candidate === compatible
          ? { compatible: true, failure: "" }
          : { compatible: false, failure: "Python 3.11+ required" };
      },
    );

    expect(selected).toBe(compatible);
    expect(probed).toEqual(["python-incompatible", "python-compatible"]);
  });

  it("runs the resolved PYTHON or fallback interpreter without a shell", () => {
    expect(runPython(["-c", "print('ready')"], "interpreter probe").trim()).toBe(
      "ready",
    );
  });

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

  it("audits the canonical comparison numeric domain independently in Python", () => {
    const stdout = runPython(
      ["-c", canonicalNumericAuditScript],
      "canonical numeric audit",
    );
    const parsed: unknown = JSON.parse(stdout);
    const audit = requireRecord(parsed, "canonical numeric audit");

    expect(audit.issues).toEqual([]);
    expect(audit.negative_zero_integer_issues).toEqual([
      "probe: integer token -0 is unsupported",
    ]);
    expect(audit.one).toBe("1");
    expect(audit.one_float).toBe("1.0");
    expect(Object.is(1, 1.0)).toBe(true);
  });

  it("matches Python raw JSON signed-zero evaluation", () => {
    const unit = structuredClone(findUnitByMethod("exact_match"));
    const rawUnitView = structuredClone(unit);
    const marker = "__RAW_NEGATIVE_ZERO__";
    unit.exercise.answer = { value: -0 };
    rawUnitView.exercise.answer = { value: marker };
    const rawUnit = injectRawJsonToken(rawUnitView, marker, "-0.0");

    const negativePython = evaluateRawWithPython(
      rawUnit,
      '{"value":-0.0}',
      "negative-zero match",
    );
    const positivePython = evaluateRawWithPython(
      rawUnit,
      '{"value":0.0}',
      "positive-zero mismatch",
    );

    expect(commonTypeScriptResult(evaluateExercise(unit, { value: -0 }))).toEqual(
      negativePython,
    );
    expect(commonTypeScriptResult(evaluateExercise(unit, { value: 0 }))).toEqual(
      positivePython,
    );
    expect(positivePython.passed).toBe(false);
  });

  it("matches Python NaN truthiness outside comparison-bearing values", () => {
    const unit = structuredClone(findUnitByMethod("exact_match"));
    const rawUnitView = structuredClone(unit);
    const marker = "__RAW_NAN_TRUTHINESS__";
    unit.exercise.evaluation.manual_review_on_unmatched = Number.NaN;
    rawUnitView.exercise.evaluation.manual_review_on_unmatched = marker;
    const rawUnit = injectRawJsonToken(rawUnitView, marker, "NaN");
    const submission = { unmatched_nan_truthiness: true };
    const python = evaluateRawWithPython(
      rawUnit,
      serializeSubmission(submission),
      "NaN truthiness",
    );

    expect(commonTypeScriptResult(evaluateExercise(unit, submission))).toEqual(
      python,
    );
    expect(python.manual_review_required).toBe(true);
  });

  it("matches Python malformed diagnostic configuration errors by message", () => {
    const unit = structuredClone(findUnitByMethod("exact_match"));
    unit.exercise.evaluation.diagnostic_rules = null;
    const rawUnit = serializeSubmission(unit);
    const rawSubmission = serializeSubmission(unit.exercise.answer);
    const pythonMessage = evaluateRawFailureWithPython(
      rawUnit,
      rawSubmission,
      "null diagnostic_rules",
    );
    const typescriptMessage = captureErrorMessage(() =>
      evaluateExercise(unit, unit.exercise.answer),
    );

    expect(typescriptMessage).toBe(pythonMessage);
    expect(pythonMessage).toBe("diagnostic_rules must be a list");
  });
});
