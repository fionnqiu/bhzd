export type DiagnosticSeverity = "minor" | "moderate" | "severe";

export type MasteryBand =
  | "beginner"
  | "needs_work"
  | "consolidating"
  | "mastered";

const DIAGNOSTIC_PENALTIES: Readonly<Record<DiagnosticSeverity, number>> = {
  minor: 0.03,
  moderate: 0.08,
  severe: 0.15,
};

const assertUnitInterval = (value: number, field: string): void => {
  if (!Number.isFinite(value) || value < 0 || value > 1) {
    throw new TypeError(`${field} must be finite and within [0, 1].`);
  }
};

const isDiagnosticSeverity = (
  value: unknown,
): value is DiagnosticSeverity =>
  value === "minor" || value === "moderate" || value === "severe";

const clamp = (value: number): number => Math.min(1, Math.max(0, value));

export const applyExerciseScore = (
  oldMastery: number,
  score: number,
): number => {
  assertUnitInterval(oldMastery, "oldMastery");
  assertUnitInterval(score, "score");

  return clamp(oldMastery + 0.35 * (score - oldMastery));
};

export const applyDiagnosticPenalty = (
  oldMastery: number,
  severity: DiagnosticSeverity,
): number => {
  assertUnitInterval(oldMastery, "oldMastery");
  if (!isDiagnosticSeverity(severity)) {
    throw new TypeError(
      "severity must be one of: minor, moderate, severe.",
    );
  }

  return clamp(oldMastery - DIAGNOSTIC_PENALTIES[severity]);
};

export const masteryBand = (mastery: number): MasteryBand => {
  assertUnitInterval(mastery, "mastery");

  if (mastery < 0.4) {
    return "beginner";
  }
  if (mastery < 0.6) {
    return "needs_work";
  }
  if (mastery < 0.8) {
    return "consolidating";
  }

  return "mastered";
};
