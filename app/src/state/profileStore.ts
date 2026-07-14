import {
  applyDiagnosticPenalty,
  applyExerciseScore,
  type DiagnosticSeverity,
} from "../evaluation/mastery";

export const LEARNING_PROFILE_STORAGE_KEY = "bhzd.learning-profile.v1";

export interface ProfileStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface ProfileContext {
  lastMode: string | null;
  lastScenario: string | null;
  lastUnit: string | null;
  lastNode: string | null;
}

interface AttemptBase {
  capabilityId: string;
  scenarioId: string | null;
  evaluationVersion: string;
  timestamp: string;
  context: ProfileContext;
}

export interface ExerciseAttempt extends AttemptBase {
  kind: "exercise";
  score: number;
}

export interface DiagnosticAttempt extends AttemptBase {
  kind: "diagnostic";
  severity: DiagnosticSeverity;
}

export type LearningAttempt = ExerciseAttempt | DiagnosticAttempt;

export interface LearningProfileV1 extends ProfileContext {
  version: 1;
  generalMastery: Record<string, number>;
  scenarioMastery: Record<string, number>;
  attempts: LearningAttempt[];
}

export interface ProfileContextSnapshot {
  readonly lastMode: string | null;
  readonly lastScenario: string | null;
  readonly lastUnit: string | null;
  readonly lastNode: string | null;
}

interface AttemptSnapshotBase {
  readonly capabilityId: string;
  readonly scenarioId: string | null;
  readonly evaluationVersion: string;
  readonly timestamp: string;
  readonly context: ProfileContextSnapshot;
}

export interface ExerciseAttemptSnapshot extends AttemptSnapshotBase {
  readonly kind: "exercise";
  readonly score: number;
}

export interface DiagnosticAttemptSnapshot extends AttemptSnapshotBase {
  readonly kind: "diagnostic";
  readonly severity: DiagnosticSeverity;
}

export type LearningAttemptSnapshot =
  | ExerciseAttemptSnapshot
  | DiagnosticAttemptSnapshot;

export interface LearningProfileSnapshot extends ProfileContextSnapshot {
  readonly version: 1;
  readonly generalMastery: Readonly<Record<string, number>>;
  readonly scenarioMastery: Readonly<Record<string, number>>;
  readonly attempts: readonly LearningAttemptSnapshot[];
}

export interface RecordExerciseInput {
  capabilityId: string;
  score: number;
  scenarioId: string | null;
  evaluationVersion: string;
}

export interface RecordDiagnosticInput {
  capabilityId: string;
  severity: DiagnosticSeverity;
  scenarioId: string | null;
  evaluationVersion: string;
}

export type ProfileContextUpdate = Partial<ProfileContext>;

export type ProfileLoadErrorCode =
  | "invalid_json"
  | "unsupported_version"
  | "malformed_profile"
  | "storage_read_failed";

export interface ProfileLoadError {
  readonly code: ProfileLoadErrorCode;
  readonly message: string;
}

export interface ProfileStore {
  snapshot(): LearningProfileSnapshot;
  getLoadError(): ProfileLoadError | null;
  recordExercise(input: RecordExerciseInput): void;
  recordDiagnostic(input: RecordDiagnosticInput): void;
  setContext(update: ProfileContextUpdate): void;
  reset(): void;
}

type ProfileClock = () => Date;

type ProfileLoadResult =
  | { readonly ok: true; readonly profile: LearningProfileV1 }
  | {
      readonly ok: false;
      readonly code: "unsupported_version" | "malformed_profile";
    };

const hasOwn = (value: object, key: string): boolean =>
  Object.prototype.hasOwnProperty.call(value, key);

const isPlainRecord = (value: unknown): value is Record<string, unknown> => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }

  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
};

const isNonEmptyString = (value: unknown): value is string =>
  typeof value === "string" && value.trim().length > 0;

const isNullableNonEmptyString = (value: unknown): value is string | null =>
  value === null || isNonEmptyString(value);

const isUnitIntervalNumber = (value: unknown): value is number =>
  typeof value === "number" &&
  Number.isFinite(value) &&
  value >= 0 &&
  value <= 1;

const isDiagnosticSeverity = (
  value: unknown,
): value is DiagnosticSeverity =>
  value === "minor" || value === "moderate" || value === "severe";

const createDefaultProfile = (): LearningProfileV1 => ({
  version: 1,
  generalMastery: {},
  scenarioMastery: {},
  attempts: [],
  lastMode: null,
  lastScenario: null,
  lastUnit: null,
  lastNode: null,
});

const cloneContext = (context: ProfileContext): ProfileContext => ({
  lastMode: context.lastMode,
  lastScenario: context.lastScenario,
  lastUnit: context.lastUnit,
  lastNode: context.lastNode,
});

const cloneAttempt = (attempt: LearningAttempt): LearningAttempt => {
  if (attempt.kind === "exercise") {
    return {
      kind: "exercise",
      capabilityId: attempt.capabilityId,
      scenarioId: attempt.scenarioId,
      score: attempt.score,
      evaluationVersion: attempt.evaluationVersion,
      timestamp: attempt.timestamp,
      context: cloneContext(attempt.context),
    };
  }

  return {
    kind: "diagnostic",
    capabilityId: attempt.capabilityId,
    scenarioId: attempt.scenarioId,
    severity: attempt.severity,
    evaluationVersion: attempt.evaluationVersion,
    timestamp: attempt.timestamp,
    context: cloneContext(attempt.context),
  };
};

const cloneProfile = (profile: LearningProfileV1): LearningProfileV1 => ({
  version: 1,
  generalMastery: { ...profile.generalMastery },
  scenarioMastery: { ...profile.scenarioMastery },
  attempts: profile.attempts.map(cloneAttempt),
  lastMode: profile.lastMode,
  lastScenario: profile.lastScenario,
  lastUnit: profile.lastUnit,
  lastNode: profile.lastNode,
});

const freezeContext = (
  context: ProfileContext,
): ProfileContextSnapshot =>
  Object.freeze({
    lastMode: context.lastMode,
    lastScenario: context.lastScenario,
    lastUnit: context.lastUnit,
    lastNode: context.lastNode,
  });

const freezeAttempt = (
  attempt: LearningAttempt,
): LearningAttemptSnapshot => {
  if (attempt.kind === "exercise") {
    return Object.freeze({
      kind: "exercise",
      capabilityId: attempt.capabilityId,
      scenarioId: attempt.scenarioId,
      score: attempt.score,
      evaluationVersion: attempt.evaluationVersion,
      timestamp: attempt.timestamp,
      context: freezeContext(attempt.context),
    });
  }

  return Object.freeze({
    kind: "diagnostic",
    capabilityId: attempt.capabilityId,
    scenarioId: attempt.scenarioId,
    severity: attempt.severity,
    evaluationVersion: attempt.evaluationVersion,
    timestamp: attempt.timestamp,
    context: freezeContext(attempt.context),
  });
};

const freezeSnapshot = (
  profile: LearningProfileV1,
): LearningProfileSnapshot => {
  const generalMastery = Object.freeze({ ...profile.generalMastery });
  const scenarioMastery = Object.freeze({ ...profile.scenarioMastery });
  const attempts = Object.freeze(profile.attempts.map(freezeAttempt));

  return Object.freeze({
    version: 1,
    generalMastery,
    scenarioMastery,
    attempts,
    lastMode: profile.lastMode,
    lastScenario: profile.lastScenario,
    lastUnit: profile.lastUnit,
    lastNode: profile.lastNode,
  });
};

const normalizeMasteryMap = (
  value: unknown,
): Record<string, number> | null => {
  if (!isPlainRecord(value)) {
    return null;
  }

  const normalized: Record<string, number> = {};
  for (const [key, mastery] of Object.entries(value)) {
    if (!isNonEmptyString(key) || !isUnitIntervalNumber(mastery)) {
      return null;
    }
    normalized[key] = mastery;
  }

  return normalized;
};

const normalizeContext = (value: unknown): ProfileContext | null => {
  if (!isPlainRecord(value)) {
    return null;
  }

  const { lastMode, lastScenario, lastUnit, lastNode } = value;
  if (
    !isNullableNonEmptyString(lastMode) ||
    !isNullableNonEmptyString(lastScenario) ||
    !isNullableNonEmptyString(lastUnit) ||
    !isNullableNonEmptyString(lastNode)
  ) {
    return null;
  }

  return { lastMode, lastScenario, lastUnit, lastNode };
};

const normalizeAttempt = (value: unknown): LearningAttempt | null => {
  if (!isPlainRecord(value)) {
    return null;
  }

  const context = normalizeContext(value.context);
  if (
    !isNonEmptyString(value.capabilityId) ||
    !isNullableNonEmptyString(value.scenarioId) ||
    !isNonEmptyString(value.evaluationVersion) ||
    !isNonEmptyString(value.timestamp) ||
    Number.isNaN(Date.parse(value.timestamp)) ||
    context === null
  ) {
    return null;
  }

  if (value.kind === "exercise" && isUnitIntervalNumber(value.score)) {
    return {
      kind: "exercise",
      capabilityId: value.capabilityId,
      scenarioId: value.scenarioId,
      score: value.score,
      evaluationVersion: value.evaluationVersion,
      timestamp: value.timestamp,
      context,
    };
  }

  if (value.kind === "diagnostic" && isDiagnosticSeverity(value.severity)) {
    return {
      kind: "diagnostic",
      capabilityId: value.capabilityId,
      scenarioId: value.scenarioId,
      severity: value.severity,
      evaluationVersion: value.evaluationVersion,
      timestamp: value.timestamp,
      context,
    };
  }

  return null;
};

const normalizeStoredProfile = (value: unknown): ProfileLoadResult => {
  if (!isPlainRecord(value)) {
    return { ok: false, code: "malformed_profile" };
  }
  if (value.version !== 1) {
    return { ok: false, code: "unsupported_version" };
  }

  const generalMastery = normalizeMasteryMap(value.generalMastery);
  const scenarioMastery = normalizeMasteryMap(value.scenarioMastery);
  const context = normalizeContext(value);
  if (
    generalMastery === null ||
    scenarioMastery === null ||
    context === null ||
    !Array.isArray(value.attempts)
  ) {
    return { ok: false, code: "malformed_profile" };
  }

  const attempts: LearningAttempt[] = [];
  for (const valueAttempt of value.attempts) {
    const attempt = normalizeAttempt(valueAttempt);
    if (attempt === null) {
      return { ok: false, code: "malformed_profile" };
    }
    attempts.push(attempt);
  }

  return {
    ok: true,
    profile: {
      version: 1,
      generalMastery,
      scenarioMastery,
      attempts,
      ...context,
    },
  };
};

const createLoadError = (
  code: ProfileLoadErrorCode,
  message: string,
): ProfileLoadError => Object.freeze({ code, message });

const loadProfile = (
  storage: ProfileStorage,
): {
  readonly profile: LearningProfileV1;
  readonly loadError: ProfileLoadError | null;
} => {
  let stored: string | null;
  try {
    stored = storage.getItem(LEARNING_PROFILE_STORAGE_KEY);
  } catch {
    return {
      profile: createDefaultProfile(),
      loadError: createLoadError(
        "storage_read_failed",
        "Failed to read stored learning profile.",
      ),
    };
  }

  if (stored === null) {
    return { profile: createDefaultProfile(), loadError: null };
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(stored);
  } catch {
    return {
      profile: createDefaultProfile(),
      loadError: createLoadError(
        "invalid_json",
        "Stored learning profile is not valid JSON.",
      ),
    };
  }

  const normalized = normalizeStoredProfile(parsed);
  if (!normalized.ok) {
    const message =
      normalized.code === "unsupported_version"
        ? "Stored learning profile uses an unsupported version."
        : "Stored learning profile is malformed.";
    return {
      profile: createDefaultProfile(),
      loadError: createLoadError(normalized.code, message),
    };
  }

  return { profile: normalized.profile, loadError: null };
};

const requireNonEmptyString = (value: unknown, field: string): string => {
  if (!isNonEmptyString(value)) {
    throw new TypeError(`${field} must be a non-empty string.`);
  }
  return value;
};

const requireNullableNonEmptyString = (
  value: unknown,
  field: string,
): string | null => {
  if (!isNullableNonEmptyString(value)) {
    throw new TypeError(`${field} must be null or a non-empty string.`);
  }
  return value;
};

const scenarioMasteryKey = (
  capabilityId: string,
  scenarioId: string,
): string => `${capabilityId}::${scenarioId}`;

export const createProfileStore = (
  storage: ProfileStorage,
  clock: ProfileClock = () => new Date(),
): ProfileStore => {
  const loaded = loadProfile(storage);
  let profile = loaded.profile;
  let loadError = loaded.loadError;

  const timestampNow = (): string => {
    const timestamp = clock();
    if (!(timestamp instanceof Date) || !Number.isFinite(timestamp.getTime())) {
      throw new TypeError("Profile clock must return a valid Date.");
    }
    return timestamp.toISOString();
  };

  const commit = (candidate: LearningProfileV1): void => {
    const serialized = JSON.stringify(candidate);
    try {
      storage.setItem(LEARNING_PROFILE_STORAGE_KEY, serialized);
    } catch {
      throw new Error("Failed to persist learning profile.");
    }

    profile = candidate;
    loadError = null;
  };

  const recordExercise = (input: RecordExerciseInput): void => {
    const capabilityId = requireNonEmptyString(
      input.capabilityId,
      "capabilityId",
    );
    const scenarioId = requireNullableNonEmptyString(
      input.scenarioId,
      "scenarioId",
    );
    const evaluationVersion = requireNonEmptyString(
      input.evaluationVersion,
      "evaluationVersion",
    );
    const candidate = cloneProfile(profile);
    const masteryMap =
      scenarioId === null
        ? candidate.generalMastery
        : candidate.scenarioMastery;
    const masteryKey =
      scenarioId === null
        ? capabilityId
        : scenarioMasteryKey(capabilityId, scenarioId);
    masteryMap[masteryKey] = applyExerciseScore(
      masteryMap[masteryKey] ?? 0,
      input.score,
    );
    candidate.attempts.push({
      kind: "exercise",
      capabilityId,
      scenarioId,
      score: input.score,
      evaluationVersion,
      timestamp: timestampNow(),
      context: cloneContext(candidate),
    });

    commit(candidate);
  };

  const recordDiagnostic = (input: RecordDiagnosticInput): void => {
    const capabilityId = requireNonEmptyString(
      input.capabilityId,
      "capabilityId",
    );
    const scenarioId = requireNullableNonEmptyString(
      input.scenarioId,
      "scenarioId",
    );
    const evaluationVersion = requireNonEmptyString(
      input.evaluationVersion,
      "evaluationVersion",
    );
    const candidate = cloneProfile(profile);
    const masteryMap =
      scenarioId === null
        ? candidate.generalMastery
        : candidate.scenarioMastery;
    const masteryKey =
      scenarioId === null
        ? capabilityId
        : scenarioMasteryKey(capabilityId, scenarioId);
    masteryMap[masteryKey] = applyDiagnosticPenalty(
      masteryMap[masteryKey] ?? 0,
      input.severity,
    );
    candidate.attempts.push({
      kind: "diagnostic",
      capabilityId,
      scenarioId,
      severity: input.severity,
      evaluationVersion,
      timestamp: timestampNow(),
      context: cloneContext(candidate),
    });

    commit(candidate);
  };

  const setContext = (update: ProfileContextUpdate): void => {
    if (!isPlainRecord(update)) {
      throw new TypeError("context update must be an object.");
    }

    const candidate = cloneProfile(profile);
    if (hasOwn(update, "lastMode")) {
      candidate.lastMode = requireNullableNonEmptyString(
        update.lastMode,
        "lastMode",
      );
    }
    if (hasOwn(update, "lastScenario")) {
      candidate.lastScenario = requireNullableNonEmptyString(
        update.lastScenario,
        "lastScenario",
      );
    }
    if (hasOwn(update, "lastUnit")) {
      candidate.lastUnit = requireNullableNonEmptyString(
        update.lastUnit,
        "lastUnit",
      );
    }
    if (hasOwn(update, "lastNode")) {
      candidate.lastNode = requireNullableNonEmptyString(
        update.lastNode,
        "lastNode",
      );
    }

    commit(candidate);
  };

  const reset = (): void => {
    try {
      storage.removeItem(LEARNING_PROFILE_STORAGE_KEY);
    } catch {
      throw new Error("Failed to reset learning profile.");
    }

    profile = createDefaultProfile();
    loadError = null;
  };

  const snapshot = (): LearningProfileSnapshot => freezeSnapshot(profile);

  const getLoadError = (): ProfileLoadError | null =>
    loadError === null
      ? null
      : createLoadError(loadError.code, loadError.message);

  return Object.freeze({
    snapshot,
    getLoadError,
    recordExercise,
    recordDiagnostic,
    setContext,
    reset,
  });
};
