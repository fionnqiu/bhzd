import { beforeEach, describe, expect, it } from "vitest";

import {
  applyDiagnosticPenalty,
  applyExerciseScore,
  masteryBand,
} from "../../src/evaluation/mastery";
import {
  LEARNING_PROFILE_STORAGE_KEY,
  createProfileStore,
  type ProfileStorage,
} from "../../src/state/profileStore";

const CAPABILITY_ID = "CAP-AUD-TRANSCRIBE-PUNCT-001";
const SCENARIO_ID = "SCN-CUSTOMER-SERVICE-001";
const EVALUATION_VERSION = "1.1.0";
const FIRST_TIMESTAMP = "2026-07-14T01:02:03.000Z";
const SECOND_TIMESTAMP = "2026-07-14T04:05:06.000Z";

const fixedClock = (timestamp = FIRST_TIMESTAMP): (() => Date) =>
  () => new Date(timestamp);

class ControlledStorage implements ProfileStorage {
  readonly values = new Map<string, string>();
  readonly removedKeys: string[] = [];
  failGet = false;
  failSet = false;
  failRemove = false;

  getItem(key: string): string | null {
    if (this.failGet) {
      throw new Error("simulated getItem failure");
    }

    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    if (this.failSet) {
      throw new Error("simulated setItem failure");
    }

    this.values.set(key, value);
  }

  removeItem(key: string): void {
    if (this.failRemove) {
      throw new Error("simulated removeItem failure");
    }

    this.removedKeys.push(key);
    this.values.delete(key);
  }
}

const validStoredProfile = () => ({
  version: 1 as const,
  generalMastery: { [CAPABILITY_ID]: 0.61 },
  scenarioMastery: { [`${CAPABILITY_ID}::${SCENARIO_ID}`]: 0.46 },
  attempts: [
    {
      kind: "exercise" as const,
      capabilityId: CAPABILITY_ID,
      scenarioId: null,
      score: 1,
      evaluationVersion: EVALUATION_VERSION,
      timestamp: FIRST_TIMESTAMP,
      context: {
        lastMode: "course",
        lastScenario: SCENARIO_ID,
        lastUnit: "TU-AUDIO-001",
        lastNode: CAPABILITY_ID,
      },
    },
  ],
  lastMode: "course",
  lastScenario: SCENARIO_ID,
  lastUnit: "TU-AUDIO-001",
  lastNode: CAPABILITY_ID,
});

describe("mastery calculations", () => {
  it("uses the approved exercise formula and severity penalties", () => {
    expect(applyExerciseScore(0.4, 1)).toBeCloseTo(0.61);
    expect(applyDiagnosticPenalty(0.61, "severe")).toBeCloseTo(0.46);
    expect(applyDiagnosticPenalty(0.61, "moderate")).toBeCloseTo(0.53);
    expect(applyDiagnosticPenalty(0.61, "minor")).toBeCloseTo(0.58);
  });

  it("clamps calculated mastery to the unit interval", () => {
    expect(applyExerciseScore(0, 0)).toBe(0);
    expect(applyExerciseScore(1, 1)).toBe(1);
    expect(applyDiagnosticPenalty(0.01, "minor")).toBe(0);
  });

  it.each([
    [0, "beginner"],
    [0.399_999, "beginner"],
    [0.4, "needs_work"],
    [0.599_999, "needs_work"],
    [0.6, "consolidating"],
    [0.799_999, "consolidating"],
    [0.8, "mastered"],
    [1, "mastered"],
  ] as const)("maps %s to the %s band", (mastery, expected) => {
    expect(masteryBand(mastery)).toBe(expected);
  });

  it.each([
    ["NaN old mastery", () => applyExerciseScore(Number.NaN, 0.5)],
    ["infinite old mastery", () => applyExerciseScore(Infinity, 0.5)],
    ["negative old mastery", () => applyExerciseScore(-0.01, 0.5)],
    ["old mastery above one", () => applyExerciseScore(1.01, 0.5)],
  ])("rejects %s with a stable error", (_label, operation) => {
    expect(operation).toThrowError(
      new TypeError("oldMastery must be finite and within [0, 1]."),
    );
  });

  it.each([
    ["NaN score", Number.NaN],
    ["infinite score", Infinity],
    ["negative score", -0.01],
    ["score above one", 1.01],
  ])("rejects %s with a stable error", (_label, score) => {
    expect(() => applyExerciseScore(0.5, score)).toThrowError(
      new TypeError("score must be finite and within [0, 1]."),
    );
  });

  it("rejects unsupported diagnostic severity with a stable error", () => {
    expect(() =>
      Reflect.apply(applyDiagnosticPenalty, undefined, [0.5, "critical"]),
    ).toThrowError(
      new TypeError("severity must be one of: minor, moderate, severe."),
    );
  });

  it.each([Number.NaN, Infinity, -0.01, 1.01])(
    "rejects invalid mastery band input %s",
    (mastery) => {
      expect(() => masteryBand(mastery)).toThrowError(
        new TypeError("mastery must be finite and within [0, 1]."),
      );
    },
  );
});

describe("versioned learning profile", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("starts with one implicit anonymous version-1 profile", () => {
    const store = createProfileStore(localStorage, fixedClock());

    expect(store.snapshot()).toEqual({
      version: 1,
      generalMastery: {},
      scenarioMastery: {},
      attempts: [],
      lastMode: null,
      lastScenario: null,
      lastUnit: null,
      lastNode: null,
    });
    expect(store.getLoadError()).toBeNull();
  });

  it("isolates general and scenario mastery", () => {
    const store = createProfileStore(localStorage, fixedClock());

    store.recordExercise({
      capabilityId: CAPABILITY_ID,
      score: 1,
      scenarioId: null,
      evaluationVersion: EVALUATION_VERSION,
    });
    store.recordExercise({
      capabilityId: CAPABILITY_ID,
      score: 0,
      scenarioId: SCENARIO_ID,
      evaluationVersion: EVALUATION_VERSION,
    });

    const profile = store.snapshot();
    expect(profile.generalMastery[CAPABILITY_ID]).toBeCloseTo(0.35);
    expect(
      profile.scenarioMastery[`${CAPABILITY_ID}::${SCENARIO_ID}`],
    ).toBe(0);
    expect(Object.keys(profile.generalMastery)).toEqual([CAPABILITY_ID]);
    expect(Object.keys(profile.scenarioMastery)).toEqual([
      `${CAPABILITY_ID}::${SCENARIO_ID}`,
    ]);
  });

  it("records exercise and diagnostic attempts with timestamped context", () => {
    const timestamps = [FIRST_TIMESTAMP, SECOND_TIMESTAMP];
    const store = createProfileStore(localStorage, () =>
      new Date(timestamps.shift() ?? SECOND_TIMESTAMP),
    );
    store.setContext({
      lastMode: "course",
      lastScenario: SCENARIO_ID,
      lastUnit: "TU-AUDIO-001",
      lastNode: CAPABILITY_ID,
    });

    store.recordExercise({
      capabilityId: CAPABILITY_ID,
      score: 1,
      scenarioId: null,
      evaluationVersion: EVALUATION_VERSION,
    });
    store.recordDiagnostic({
      capabilityId: CAPABILITY_ID,
      severity: "severe",
      scenarioId: null,
      evaluationVersion: "diagnostic-2.0.0",
    });

    expect(store.snapshot().attempts).toEqual([
      {
        kind: "exercise",
        capabilityId: CAPABILITY_ID,
        scenarioId: null,
        score: 1,
        evaluationVersion: EVALUATION_VERSION,
        timestamp: FIRST_TIMESTAMP,
        context: {
          lastMode: "course",
          lastScenario: SCENARIO_ID,
          lastUnit: "TU-AUDIO-001",
          lastNode: CAPABILITY_ID,
        },
      },
      {
        kind: "diagnostic",
        capabilityId: CAPABILITY_ID,
        scenarioId: null,
        severity: "severe",
        evaluationVersion: "diagnostic-2.0.0",
        timestamp: SECOND_TIMESTAMP,
        context: {
          lastMode: "course",
          lastScenario: SCENARIO_ID,
          lastUnit: "TU-AUDIO-001",
          lastNode: CAPABILITY_ID,
        },
      },
    ]);
    expect(store.snapshot().generalMastery[CAPABILITY_ID]).toBeCloseTo(0.2);
  });

  it("updates only supplied context fields and persists them", () => {
    const store = createProfileStore(localStorage, fixedClock());
    store.setContext({
      lastMode: "graph",
      lastScenario: SCENARIO_ID,
    });
    store.setContext({
      lastUnit: "TU-AUDIO-001",
      lastNode: CAPABILITY_ID,
    });

    expect(store.snapshot()).toMatchObject({
      lastMode: "graph",
      lastScenario: SCENARIO_ID,
      lastUnit: "TU-AUDIO-001",
      lastNode: CAPABILITY_ID,
    });
    expect(
      createProfileStore(localStorage, fixedClock()).snapshot(),
    ).toMatchObject({
      lastMode: "graph",
      lastScenario: SCENARIO_ID,
      lastUnit: "TU-AUDIO-001",
      lastNode: CAPABILITY_ID,
    });
  });

  it("loads a persisted valid v1 profile in a new store instance", () => {
    const first = createProfileStore(localStorage, fixedClock());
    first.setContext({ lastMode: "course", lastNode: CAPABILITY_ID });
    first.recordExercise({
      capabilityId: CAPABILITY_ID,
      score: 1,
      scenarioId: SCENARIO_ID,
      evaluationVersion: EVALUATION_VERSION,
    });

    const expected = first.snapshot();
    const second = createProfileStore(localStorage, fixedClock());

    expect(second.snapshot()).toEqual(expected);
    expect(second.getLoadError()).toBeNull();
  });

  it("normalizes a valid stored v1 profile through runtime guards", () => {
    const profile = validStoredProfile();
    localStorage.setItem(
      LEARNING_PROFILE_STORAGE_KEY,
      JSON.stringify({ ...profile, ignoredFutureField: true }),
    );

    const store = createProfileStore(localStorage, fixedClock());

    expect(store.snapshot()).toEqual(profile);
    expect(store.getLoadError()).toBeNull();
  });

  it("recovers from invalid JSON without deleting the original value", () => {
    const corruptValue = "{not-json";
    localStorage.setItem(LEARNING_PROFILE_STORAGE_KEY, corruptValue);

    const store = createProfileStore(localStorage, fixedClock());

    expect(store.snapshot().generalMastery).toEqual({});
    expect(store.getLoadError()).toEqual({
      code: "invalid_json",
      message: "Stored learning profile is not valid JSON.",
    });
    expect(localStorage.getItem(LEARNING_PROFILE_STORAGE_KEY)).toBe(
      corruptValue,
    );
  });

  it.each([
    ["missing", { ...validStoredProfile(), version: undefined }],
    ["unsupported", { ...validStoredProfile(), version: 2 }],
  ])("recovers from a %s profile version and preserves storage", (_label, raw) => {
    const serialized = JSON.stringify(raw);
    localStorage.setItem(LEARNING_PROFILE_STORAGE_KEY, serialized);

    const store = createProfileStore(localStorage, fixedClock());

    expect(store.snapshot().attempts).toEqual([]);
    expect(store.getLoadError()).toEqual({
      code: "unsupported_version",
      message: "Stored learning profile uses an unsupported version.",
    });
    expect(localStorage.getItem(LEARNING_PROFILE_STORAGE_KEY)).toBe(serialized);
  });

  it("recovers from malformed profile fields and preserves storage", () => {
    const malformed = JSON.stringify({
      ...validStoredProfile(),
      generalMastery: { [CAPABILITY_ID]: "high" },
    });
    localStorage.setItem(LEARNING_PROFILE_STORAGE_KEY, malformed);

    const store = createProfileStore(localStorage, fixedClock());

    expect(store.snapshot().generalMastery).toEqual({});
    expect(store.getLoadError()).toEqual({
      code: "malformed_profile",
      message: "Stored learning profile is malformed.",
    });
    expect(localStorage.getItem(LEARNING_PROFILE_STORAGE_KEY)).toBe(malformed);
  });

  it("clears a recoverable load error on the first successful write", () => {
    localStorage.setItem(LEARNING_PROFILE_STORAGE_KEY, "broken");
    const store = createProfileStore(localStorage, fixedClock());
    expect(store.getLoadError()?.code).toBe("invalid_json");

    store.recordExercise({
      capabilityId: CAPABILITY_ID,
      score: 1,
      scenarioId: null,
      evaluationVersion: EVALUATION_VERSION,
    });

    expect(store.getLoadError()).toBeNull();
    expect(
      JSON.parse(localStorage.getItem(LEARNING_PROFILE_STORAGE_KEY) ?? "null"),
    ).toEqual(store.snapshot());
  });

  it("reset removes only this application's key and restores defaults", () => {
    localStorage.setItem("another.application", "keep-me");
    const store = createProfileStore(localStorage, fixedClock());
    store.recordExercise({
      capabilityId: CAPABILITY_ID,
      score: 1,
      scenarioId: null,
      evaluationVersion: EVALUATION_VERSION,
    });

    store.reset();

    expect(localStorage.getItem(LEARNING_PROFILE_STORAGE_KEY)).toBeNull();
    expect(localStorage.getItem("another.application")).toBe("keep-me");
    expect(store.snapshot().generalMastery).toEqual({});
    expect(store.snapshot().attempts).toEqual([]);
    expect(store.getLoadError()).toBeNull();
  });

  it("returns deeply frozen snapshots that cannot pollute internal state", () => {
    const store = createProfileStore(localStorage, fixedClock());
    store.setContext({ lastMode: "course" });
    store.recordExercise({
      capabilityId: CAPABILITY_ID,
      score: 1,
      scenarioId: null,
      evaluationVersion: EVALUATION_VERSION,
    });
    const before = store.snapshot();
    const attempt = before.attempts[0];
    if (attempt === undefined) {
      throw new Error("Expected a persisted attempt.");
    }

    expect(Object.isFrozen(before)).toBe(true);
    expect(Object.isFrozen(before.generalMastery)).toBe(true);
    expect(Object.isFrozen(before.attempts)).toBe(true);
    expect(Object.isFrozen(attempt)).toBe(true);
    expect(Object.isFrozen(attempt.context)).toBe(true);
    expect(Reflect.set(before.generalMastery, CAPABILITY_ID, 0.99)).toBe(false);
    expect(Reflect.set(attempt.context, "lastMode", "polluted")).toBe(false);
    expect(() =>
      Reflect.apply(Array.prototype.push, before.attempts, [attempt]),
    ).toThrow(TypeError);

    expect(store.snapshot()).toEqual(before);
  });

  it("does not live-sync external storage changes after construction", () => {
    const store = createProfileStore(localStorage, fixedClock());
    localStorage.setItem(
      LEARNING_PROFILE_STORAGE_KEY,
      JSON.stringify(validStoredProfile()),
    );

    expect(store.snapshot().generalMastery).toEqual({});
  });

  it("treats setItem as the transaction boundary", () => {
    const storage = new ControlledStorage();
    const store = createProfileStore(storage, fixedClock());
    store.recordExercise({
      capabilityId: CAPABILITY_ID,
      score: 1,
      scenarioId: null,
      evaluationVersion: EVALUATION_VERSION,
    });
    const before = store.snapshot();
    const storedBefore = storage.values.get(LEARNING_PROFILE_STORAGE_KEY);
    storage.failSet = true;

    expect(() =>
      store.recordDiagnostic({
        capabilityId: CAPABILITY_ID,
        severity: "minor",
        scenarioId: null,
        evaluationVersion: EVALUATION_VERSION,
      }),
    ).toThrowError(new Error("Failed to persist learning profile."));

    expect(store.snapshot()).toEqual(before);
    expect(storage.values.get(LEARNING_PROFILE_STORAGE_KEY)).toBe(storedBefore);
  });

  it("treats removeItem as the reset transaction boundary", () => {
    const storage = new ControlledStorage();
    storage.setItem("another.application", "keep-me");
    const store = createProfileStore(storage, fixedClock());
    store.recordExercise({
      capabilityId: CAPABILITY_ID,
      score: 1,
      scenarioId: null,
      evaluationVersion: EVALUATION_VERSION,
    });
    const before = store.snapshot();
    const storedBefore = storage.values.get(LEARNING_PROFILE_STORAGE_KEY);
    storage.failRemove = true;

    expect(() => store.reset()).toThrowError(
      new Error("Failed to reset learning profile."),
    );

    expect(store.snapshot()).toEqual(before);
    expect(storage.values.get(LEARNING_PROFILE_STORAGE_KEY)).toBe(storedBefore);
    expect(storage.values.get("another.application")).toBe("keep-me");
    expect(storage.removedKeys).toEqual([]);
  });

  it("surfaces getItem failures as a recoverable load error", () => {
    const storage = new ControlledStorage();
    storage.failGet = true;

    const store = createProfileStore(storage, fixedClock());

    expect(store.snapshot().attempts).toEqual([]);
    expect(store.getLoadError()).toEqual({
      code: "storage_read_failed",
      message: "Failed to read stored learning profile.",
    });
  });

  it("rejects an invalid clock before attempting persistence", () => {
    const storage = new ControlledStorage();
    const store = createProfileStore(storage, () => new Date(Number.NaN));

    expect(() =>
      store.recordExercise({
        capabilityId: CAPABILITY_ID,
        score: 1,
        scenarioId: null,
        evaluationVersion: EVALUATION_VERSION,
      }),
    ).toThrowError(new TypeError("Profile clock must return a valid Date."));
    expect(store.snapshot().attempts).toEqual([]);
    expect(storage.values.has(LEARNING_PROFILE_STORAGE_KEY)).toBe(false);
  });
});
