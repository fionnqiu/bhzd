import type { EvaluationResult } from "../evaluation/evaluate";
import { evaluateExercise } from "../evaluation/evaluate";
import type { TeachingUnit } from "../data/contracts";
import { graph, scenarios, sourceRegistry, teachingUnits } from "../data/rawData";
import { createRepository } from "../data/repository";
import { detectFormat } from "./detectFormat";
import { inspectJsonText } from "./json";
import { inspectTextGrid } from "./textGrid";
import type {
  DiagnosticContext,
  DiagnosticDependencies,
  DiagnosticEvaluator,
  DiagnosticFileLike,
  DiagnosticFormat,
  DiagnosticIssue,
  DiagnosticReport,
  DiagnosticRepository,
  DiagnosticSeverity,
} from "./types";
import { inspectVocXml } from "./vocXml";

export const MAX_DIAGNOSTIC_FILE_BYTES = 5 * 1024 * 1024;

const defaultRepository: DiagnosticRepository = createRepository({
  graph,
  scenarios,
  sourceRegistry,
  teachingUnits,
});

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const stringList = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];

const unique = (values: readonly string[]): string[] => [...new Set(values)];

const issue = (
  code: string,
  severity: DiagnosticSeverity,
  message: string,
  ruleRefs: readonly string[] = [],
  capabilityRefs: readonly string[] = [],
  remediation: readonly string[] = [],
): DiagnosticIssue => ({
  code,
  severity,
  message,
  ruleRefs: [...ruleRefs],
  capabilityRefs: [...capabilityRefs],
  remediation: [...remediation],
});

const cloneIssue = (
  candidate: DiagnosticIssue,
  ruleRefs: readonly string[],
  capabilityRefs: readonly string[],
): DiagnosticIssue =>
  issue(
    candidate.code,
    candidate.severity,
    candidate.message,
    unique([...ruleRefs, ...candidate.ruleRefs]),
    unique([...capabilityRefs, ...candidate.capabilityRefs]),
    candidate.remediation.length > 0
      ? [...candidate.remediation]
      : ["修复导出文件中的结构问题后重新上传。"],
  );

const freezeReport = (
  status: DiagnosticReport["status"],
  format: DiagnosticReport["format"],
  issues: readonly DiagnosticIssue[],
  masteryImpact: boolean,
  score: number | null,
  code?: string,
): DiagnosticReport => {
  const frozenIssues = issues.map((candidate) =>
    Object.freeze({
      code: candidate.code,
      severity: candidate.severity,
      message: candidate.message,
      ruleRefs: Object.freeze([...candidate.ruleRefs]),
      capabilityRefs: Object.freeze([...candidate.capabilityRefs]),
      remediation: Object.freeze([...candidate.remediation]),
    }),
  );
  const report: DiagnosticReport = {
    status,
    format,
    issues: Object.freeze(frozenIssues),
    masteryImpact,
    score,
    ...(code === undefined ? {} : { code }),
  };
  return Object.freeze(report);
};

const unitId = (unit: unknown): string | null =>
  isRecord(unit) && typeof unit.id === "string" ? unit.id : null;

const unitDataType = (unit: unknown): string | null =>
  isRecord(unit) && typeof unit.data_type === "string" ? unit.data_type : null;

const unitRefs = (unit: unknown): { ruleRefs: string[]; capabilityRefs: string[] } => {
  if (!isRecord(unit)) {
    return { ruleRefs: [], capabilityRefs: [] };
  }
  const ruleRefs = stringList(unit.rule_refs);
  const exercise = isRecord(unit.exercise) ? unit.exercise : undefined;
  const capabilityRefs = exercise === undefined ? [] : stringList(exercise.capability_refs);
  return { ruleRefs, capabilityRefs };
};

const isPublishedUnit = (unit: unknown): boolean =>
  isRecord(unit) && unit.review_status === "published" && unit.student_visible === true;

interface TargetResolution {
  readonly unit: unknown;
  readonly refs: { ruleRefs: string[]; capabilityRefs: string[] };
  readonly reason?: "missing" | "not_found" | "not_consumable" | "data_type_mismatch";
}

const resolveTarget = (
  context: DiagnosticContext | undefined,
  repository: DiagnosticRepository,
): TargetResolution => {
  const target = context?.targetUnitId;
  if (typeof target !== "string" || target.trim().length === 0) {
    return { unit: undefined, refs: { ruleRefs: [], capabilityRefs: [] }, reason: "missing" };
  }
  const targetId = target.trim();

  let candidate: unknown;
  try {
    candidate = repository.getUnit(targetId);
  } catch {
    return { unit: undefined, refs: { ruleRefs: [], capabilityRefs: [] }, reason: "not_found" };
  }
  if (candidate === undefined || candidate === null) {
    return { unit: undefined, refs: { ruleRefs: [], capabilityRefs: [] }, reason: "not_found" };
  }
  if (!isPublishedUnit(candidate)) {
    return {
      unit: candidate,
      refs: unitRefs(candidate),
      reason: "not_consumable",
    };
  }
  if (repository.listConsumableUnits !== undefined) {
    try {
      const consumable = repository.listConsumableUnits();
      if (!consumable.some((item) => unitId(item) === targetId)) {
        return {
          unit: candidate,
          refs: unitRefs(candidate),
          reason: "not_consumable",
        };
      }
    } catch {
      return {
        unit: candidate,
        refs: unitRefs(candidate),
        reason: "not_consumable",
      };
    }
  }
  if (
    typeof context?.dataType === "string" &&
    context.dataType.trim().length > 0 &&
    unitDataType(candidate) !== null &&
    unitDataType(candidate)?.trim().toLowerCase() !== context.dataType.trim().toLowerCase()
  ) {
    return {
      unit: candidate,
      refs: unitRefs(candidate),
      reason: "data_type_mismatch",
    };
  }
  return { unit: candidate, refs: unitRefs(candidate) };
};

const contextIssue = (
  resolution: TargetResolution,
  context: DiagnosticContext | undefined,
): DiagnosticIssue | null => {
  if (context === undefined) {
    return issue(
      "missing_context",
      "moderate",
      "A data type and published target teaching unit are required for semantic diagnosis.",
    );
  }
  switch (resolution.reason) {
    case "missing":
      return issue(
        "missing_target_context",
        "moderate",
        "Select a published target teaching unit before semantic diagnosis.",
      );
    case "not_found":
      return issue(
        "target_unit_not_found",
        "moderate",
        "The selected target teaching unit is not available.",
      );
    case "not_consumable":
      return issue(
        "target_unit_not_consumable",
        "severe",
        "Only published student-visible teaching units can affect mastery.",
      );
    case "data_type_mismatch":
      return issue(
        "data_type_mismatch",
        "moderate",
        "The selected target unit does not declare the requested data type.",
      );
    default:
      return null;
  }
};

const isTeachingUnit = (value: unknown): value is TeachingUnit => {
  if (!isRecord(value)) {
    return false;
  }
  const exercise = value.exercise;
  return (
    typeof value.id === "string" &&
    typeof value.data_type === "string" &&
    typeof value.title === "string" &&
    Array.isArray(value.learning_objectives) &&
    Array.isArray(value.prerequisites) &&
    Array.isArray(value.rule_refs) &&
    Array.isArray(value.source_refs) &&
    isRecord(exercise) &&
    typeof exercise.data_version === "string" &&
    typeof exercise.student_action === "string" &&
    isRecord(exercise.input) &&
    isRecord(exercise.answer) &&
    isRecord(exercise.evaluation) &&
    typeof value.review_status === "string" &&
    typeof value.student_visible === "boolean"
  );
};

const defaultEvaluatorFor = (targetId: string | null): DiagnosticEvaluator | undefined => {
  if (targetId === null) {
    return undefined;
  }
  return (unit: unknown, submission: unknown): EvaluationResult => {
    if (!isTeachingUnit(unit)) {
      throw new TypeError("Selected target unit does not satisfy the teaching-unit contract.");
    }
    return evaluateExercise(unit, submission);
  };
};

const targetIdFromContext = (context: DiagnosticContext | undefined): string | null => {
  const value = context?.targetUnitId;
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
};

const cloneForEvaluator = (unit: unknown): unknown => {
  try {
    return structuredClone(unit);
  } catch {
    return undefined;
  }
};

const evaluationIssue = (
  result: EvaluationResult,
  refs: { ruleRefs: string[]; capabilityRefs: string[] },
): DiagnosticIssue | null => {
  if (result.passed === true && result.matched !== "diagnostic_rule") {
    return null;
  }
  const score = typeof result.score === "number" && Number.isFinite(result.score)
    ? result.score
    : 0;
  const severity: DiagnosticSeverity =
    score <= 0.25 ? "severe" : score < 1 ? "moderate" : "minor";
  const code =
    result.matched === "unclassified"
      ? "unclassified_submission"
      : typeof result.errorType === "string"
        ? result.errorType
        : "incorrect_submission";
  const feedback = typeof result.feedback === "string" ? result.feedback : "";
  const remediation = stringList(result.remediation);
  return issue(
    code,
    severity,
    feedback || "提交未通过确定性练习判定。",
    unique([...refs.ruleRefs, ...stringList(result.ruleRefs)]),
    unique([...refs.capabilityRefs, ...stringList(result.capabilityRefs)]),
    remediation.length > 0
      ? remediation
      : ["按照目标单元的规则与补强步骤重新检查导出。"],
  );
};

const isValidScore = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;

const readFileText = (file: DiagnosticFileLike): Promise<string> => {
  const textMethod = file.text;
  if (typeof textMethod === "function") {
    return textMethod.call(file);
  }

  // jsdom versions used by unit tests do not yet expose File.text().  The
  // browser fallback remains local and is only reached when the standard
  // method is unavailable; production Chromium/Edge takes the first branch.
  if (typeof FileReader !== "undefined" && typeof Blob !== "undefined" && file instanceof Blob) {
    return new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        if (typeof reader.result === "string") {
          resolve(reader.result);
        } else {
          reject(new Error("FileReader did not return text."));
        }
      };
      reader.onerror = () => reject(reader.error ?? new Error("FileReader failed."));
      reader.readAsText(file);
    });
  }
  return Promise.reject(new Error("File.text is unavailable."));
};

const mergeRefs = (
  issues: readonly DiagnosticIssue[],
  refs: { ruleRefs: string[]; capabilityRefs: string[] },
): DiagnosticIssue[] => issues.map((candidate) => cloneIssue(candidate, refs.ruleRefs, refs.capabilityRefs));

const diagnosticDependencies = (
  context: DiagnosticContext | undefined,
  dependencies: DiagnosticDependencies | undefined,
): { repository: DiagnosticRepository; evaluator?: DiagnosticEvaluator } => ({
  repository:
    dependencies?.repository ??
    context?.dependencies?.repository ??
    context?.repository ??
    defaultRepository,
  evaluator:
    dependencies?.evaluator ??
    dependencies?.evaluateExercise ??
    context?.dependencies?.evaluator ??
    context?.dependencies?.evaluateExercise ??
    context?.evaluator ??
    context?.evaluateExercise ??
    defaultEvaluatorFor(targetIdFromContext(context)),
});

/**
 * Diagnose one local file.  The body is read exactly once and never persisted;
 * all returned arrays/objects are fresh frozen values.
 */
export const diagnoseFile = async (
  file: DiagnosticFileLike | null | undefined,
  context?: DiagnosticContext | null,
  dependencies?: DiagnosticDependencies,
): Promise<DiagnosticReport> => {
  const normalizedContext = context ?? undefined;
  if (file === null || file === undefined) {
    return freezeReport(
      "rejected",
      "unknown",
      [issue("missing_file", "severe", "No file was supplied for diagnosis.")],
      false,
      null,
      "missing_file",
    );
  }

  let size: number;
  try {
    size = file.size;
  } catch {
    return freezeReport(
      "rejected",
      "unknown",
      [issue("invalid_file_size", "severe", "The file size is not valid.")],
      false,
      null,
      "invalid_file_size",
    );
  }
  if (!Number.isFinite(size) || size < 0) {
    return freezeReport(
      "rejected",
      "unknown",
      [issue("invalid_file_size", "severe", "The file size is not valid.")],
      false,
      null,
      "invalid_file_size",
    );
  }
  if (size > MAX_DIAGNOSTIC_FILE_BYTES) {
    return freezeReport(
      "rejected",
      "unknown",
      [issue("file_too_large", "severe", "Files must be no larger than 5 MiB.")],
      false,
      null,
      "file_too_large",
    );
  }

  let detected: ReturnType<typeof detectFormat>;
  try {
    detected = detectFormat(file);
  } catch {
    return freezeReport(
      "rejected",
      "unknown",
      [issue("invalid_file_metadata", "severe", "The file metadata could not be read.")],
      false,
      null,
      "invalid_file_metadata",
    );
  }
  if (detected.conflict || detected.format === "unknown") {
    const code = detected.code ?? "unsupported_format";
    return freezeReport(
      "rejected",
      "unknown",
      [issue(code, "severe", "The file extension and MIME type do not identify a supported format.")],
      false,
      null,
      code,
    );
  }

  if (detected.format === "image") {
    return freezeReport(
      "explanation_only",
      "image",
      [
        issue(
          "screenshot_explanation_only",
          "minor",
          "Screenshots are available only for local explanation; upload a structured export for diagnosis.",
          [],
          [],
          ["Upload JSON, COCO JSON, VOC XML, or TextGrid export."],
        ),
      ],
      false,
      null,
    );
  }

  let text: string;
  try {
    text = await readFileText(file);
    if (typeof text !== "string") {
      throw new Error("File text must be a string.");
    }
  } catch {
    return freezeReport(
      "rejected",
      detected.format,
      [issue("file_read_failed", "severe", "The local file could not be read.")],
      false,
      null,
      "file_read_failed",
    );
  }

  const dependenciesResolved = diagnosticDependencies(normalizedContext, dependencies);
  const resolution = resolveTarget(normalizedContext, dependenciesResolved.repository);
  const refs = resolution.refs;
  const semanticContextIssue = contextIssue(resolution, normalizedContext);

  let parsedValue: unknown;
  let parserIssues: readonly DiagnosticIssue[] = [];
  let rejectedCode: string | undefined;
  let supportedTextGrid = true;
  let outputFormat: DiagnosticFormat = detected.format;

  if (detected.format === "json") {
    const inspection = inspectJsonText(text);
    parsedValue = inspection.value;
    parserIssues = inspection.issues;
    if (inspection.issues.some((candidate) => candidate.code === "corrupted_json")) {
      rejectedCode = "corrupted_json";
    } else if (inspection.issues.some((candidate) => candidate.code === "json_root_not_object")) {
      rejectedCode = "invalid_json_structure";
    }
    if (inspection.isCoco) {
      outputFormat = "coco";
    }
  } else if (detected.format === "textgrid") {
    const inspection = inspectTextGrid(text);
    parsedValue = text;
    parserIssues = inspection.issues;
    supportedTextGrid = inspection.supported;
  } else {
    const inspection = inspectVocXml(text);
    parsedValue = text;
    parserIssues = inspection.issues;
    rejectedCode = inspection.rejectedCode;
  }

  // The local variable is intentionally separate from metadata detection: JSON
  // may be promoted to COCO only after one parsed body.
  if (rejectedCode !== undefined) {
    return freezeReport(
      "rejected",
      outputFormat,
      mergeRefs(parserIssues, refs),
      false,
      null,
      rejectedCode,
    );
  }

  if (detected.format === "textgrid" && !supportedTextGrid) {
    const issues = mergeRefs(parserIssues, refs);
    return freezeReport(
      "manual_review",
      "textgrid",
      semanticContextIssue === null ? issues : [...issues, semanticContextIssue],
      false,
      null,
      "unsupported_textgrid_format",
    );
  }

  const enrichedParserIssues = mergeRefs(parserIssues, refs);
  if (resolution.reason !== undefined) {
    return freezeReport(
      "manual_review",
      outputFormat,
      semanticContextIssue === null
        ? enrichedParserIssues
        : [...enrichedParserIssues, semanticContextIssue],
      false,
      null,
      semanticContextIssue?.code ?? "manual_review_required",
    );
  }

  const evaluator = dependenciesResolved.evaluator;
  if (evaluator === undefined || parsedValue === undefined || resolution.unit === undefined) {
    const issues = enrichedParserIssues.length > 0
      ? enrichedParserIssues
      : [
          issue(
            "ground_truth_unavailable",
            "moderate",
            "No deterministic target evaluator is available for this export.",
            refs.ruleRefs,
            refs.capabilityRefs,
          ),
        ];
    return freezeReport("manual_review", outputFormat, issues, false, null, "manual_review_required");
  }

  const evaluatorInput = cloneForEvaluator(resolution.unit);
  if (evaluatorInput === undefined) {
    return freezeReport(
      "manual_review",
      outputFormat,
      [
        ...enrichedParserIssues,
        issue(
          "evaluation_context_unavailable",
          "moderate",
          "The selected teaching unit could not be safely copied for evaluation.",
          refs.ruleRefs,
          refs.capabilityRefs,
        ),
      ],
      false,
      null,
      "manual_review_required",
    );
  }

  let result: EvaluationResult;
  try {
    result = evaluator(evaluatorInput, parsedValue);
    if (!isRecord(result)) {
      throw new TypeError("Evaluator returned a non-object result.");
    }
  } catch {
    return freezeReport(
      "manual_review",
      outputFormat,
      [
        ...enrichedParserIssues,
        issue(
          "evaluation_failed",
          "moderate",
          "The selected teaching unit could not deterministically evaluate this response.",
          refs.ruleRefs,
          refs.capabilityRefs,
        ),
      ],
      false,
      null,
      "manual_review_required",
    );
  }

  const resultScore = isValidScore(result.score) ? result.score : null;
  const resultIssue = evaluationIssue(result, refs);
  const allIssues = resultIssue === null
    ? enrichedParserIssues
    : [...enrichedParserIssues, resultIssue];
  const deterministic =
    result.matched !== "unclassified" &&
    result.manualReviewRequired === false &&
    resultScore !== null;
  if (!deterministic) {
    return freezeReport(
      "manual_review",
      outputFormat,
      allIssues.length > 0
        ? allIssues
        : [
            issue(
              "unclassified_submission",
              "moderate",
              "The response did not match a deterministic answer or diagnostic rule.",
              refs.ruleRefs,
              refs.capabilityRefs,
            ),
          ],
      false,
      null,
      "manual_review_required",
    );
  }

  return freezeReport(
    "complete",
    outputFormat,
    allIssues,
    true,
    resultScore,
  );
};
