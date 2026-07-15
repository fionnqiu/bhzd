import type { EvaluationResult } from "../evaluation/evaluate";
import type { TeachingUnit } from "../data/contracts";

export type DiagnosticStatus =
  | "complete"
  | "manual_review"
  | "explanation_only"
  | "rejected";

export type DiagnosticFormat =
  | "json"
  | "coco"
  | "textgrid"
  | "voc"
  | "image"
  | "unknown";

export type DiagnosticSeverity = "minor" | "moderate" | "severe";

export interface DiagnosticIssue {
  readonly code: string;
  readonly severity: DiagnosticSeverity;
  readonly message: string;
  readonly ruleRefs: readonly string[];
  readonly capabilityRefs: readonly string[];
  readonly remediation: readonly string[];
}

export interface DiagnosticReport {
  readonly status: DiagnosticStatus;
  readonly format: DiagnosticFormat;
  readonly issues: readonly DiagnosticIssue[];
  readonly masteryImpact: boolean;
  readonly score: number | null;
  readonly code?: string;
}

/** The smallest file surface required by the browser-only parser. */
export interface DiagnosticFileLike {
  readonly name?: string;
  readonly type?: string;
  readonly size: number;
  text(): Promise<string>;
}

/**
 * Repository is intentionally structural here.  This keeps diagnostics usable
 * with the immutable repository as well as tiny test doubles, without giving
 * the parser a way to mutate canonical data.
 */
export interface DiagnosticRepository {
  getUnit(id: string): unknown;
  listConsumableUnits?(): readonly unknown[];
}

export type DiagnosticEvaluator = (
  unit: unknown,
  submission: unknown,
) => EvaluationResult;

export type DiagnosticExerciseEvaluator = (
  unit: TeachingUnit,
  submission: unknown,
) => EvaluationResult;

export interface DiagnosticDependencies {
  readonly repository?: DiagnosticRepository;
  /** A narrow adapter can be supplied for tests or another repository shape. */
  readonly evaluator?: DiagnosticEvaluator;
  /** Alias kept for callers that name the injected evaluator after the domain API. */
  readonly evaluateExercise?: DiagnosticExerciseEvaluator;
}

export interface DiagnosticContext {
  readonly dataType?: string | null;
  readonly targetUnitId?: string | null;
  readonly repository?: DiagnosticRepository;
  readonly evaluator?: DiagnosticEvaluator;
  readonly evaluateExercise?: DiagnosticExerciseEvaluator;
  readonly dependencies?: DiagnosticDependencies;
}

export interface DetectedFormat {
  readonly format: DiagnosticFormat;
  readonly conflict: boolean;
  readonly code?: "mime_extension_conflict" | "unsupported_extension";
}
