import { beforeEach, describe, expect, it } from "vitest";

import {
  applyDiagnosticPenalty,
  applyExerciseScore,
  masteryBand,
  type DiagnosticSeverity,
} from "../../src/evaluation/mastery";
import {
  LEARNING_PROFILE_STORAGE_KEY,
  MAX_ATTEMPTS,
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
  setCalls = 0;
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
    this.setCalls += 1;
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

const storedExerciseAttempt = (index: number) => {
  const kind: "exercise" = "exercise";
  return {
    kind,
    capabilityId: `${CAPABILITY_ID}-${index}`,
    scenarioId: null,
    score: 1,
    evaluationVersion: EVALUATION_VERSION,
    timestamp: new Date(Date.UTC(2026, 0, 1, 0, 0, index)).toISOString(),
    context: {
      lastMode: "course",
      lastScenario: null,
      lastUnit: null,
      lastNode: `${CAPABILITY_ID}-${index}`,
    },
  };
};

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

  it("uses null-prototype mastery dictionaries from the default profile", () => {
    const profile = createProfileStore(localStorage, fixedClock()).snapshot();

    expect(Object.getPrototypeOf(profile.generalMastery)).toBeNull();
    expect(Object.getPrototypeOf(profile.scenarioMastery)).toBeNull();
    expect(profile.generalMastery.constructor).toBeUndefined();
    expect(profile.generalMastery.toString).toBeUndefined();
  });

  it("preserves prototype-named mastery keys through load, record, and reload", () => {
    const stored = {
      ...validStoredProfile(),
      generalMastery: Object.fromEntries([
        ["__proto__", 0.1],
        ["constructor", 0.2],
        ["toString", 0.3],
      ]),
      scenarioMastery: Object.fromEntries([
        ["__proto__::SCN-SAFE", 0.4],
        ["constructor::SCN-SAFE", 0.5],
        ["toString::SCN-SAFE", 0.6],
      ]),
    };
    localStorage.setItem(
      LEARNING_PROFILE_STORAGE_KEY,
      JSON.stringify(stored),
    );
    const store = createProfileStore(localStorage, fixedClock());

    for (const capabilityId of ["__proto__", "constructor", "toString"]) {
      store.recordExercise({
        capabilityId,
        score: 1,
        scenarioId: null,
        evaluationVersion: EVALUATION_VERSION,
      });
    }

    const reloaded = createProfileStore(localStorage, fixedClock()).snapshot();
    expect(Object.getPrototypeOf(reloaded.generalMastery)).toBeNull();
    expect(Object.getPrototypeOf(reloaded.scenarioMastery)).toBeNull();
    expect(Object.keys(reloaded.generalMastery)).toEqual([
      "__proto__",
      "constructor",
      "toString",
    ]);
    expect(reloaded.generalMastery.__proto__).toBeCloseTo(0.415);
    expect(reloaded.generalMastery.constructor).toBeCloseTo(0.48);
    expect(reloaded.generalMastery.toString).toBeCloseTo(0.545);
    expect(reloaded.scenarioMastery["__proto__::SCN-SAFE"]).toBe(0.4);
    expect(reloaded.scenarioMastery["constructor::SCN-SAFE"]).toBe(0.5);
    expect(reloaded.scenarioMastery["toString::SCN-SAFE"]).toBe(0.6);
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

  it.each([
    ["a::b", "c", "Scenario capabilityId must not contain \"::\"."],
    ["a", "b::c", "scenarioId must not contain \"::\"."],
  ])(
    "rejects ambiguous scenario mastery key inputs %s + %s without writing",
    (capabilityId, scenarioId, message) => {
      const storage = new ControlledStorage();
      const store = createProfileStore(storage, fixedClock());

      expect(() =>
        store.recordExercise({
          capabilityId,
          score: 1,
          scenarioId,
          evaluationVersion: EVALUATION_VERSION,
        }),
      ).toThrowError(new TypeError(message));
      expect(storage.setCalls).toBe(0);
      expect(store.snapshot().attempts).toEqual([]);
    },
  );

  it("allows the scenario delimiter in a general capability ID", () => {
    const store = createProfileStore(localStorage, fixedClock());

    store.recordExercise({
      capabilityId: "a::b",
      score: 1,
      scenarioId: null,
      evaluationVersion: EVALUATION_VERSION,
    });

    expect(store.snapshot().generalMastery["a::b"]).toBeCloseTo(0.35);
  });

  it("applies scenario-key delimiter validation to diagnostics", () => {
    const storage = new ControlledStorage();
    const store = createProfileStore(storage, fixedClock());

    expect(() =>
      store.recordDiagnostic({
        capabilityId: "a::b",
        severity: "minor",
        scenarioId: "c",
        evaluationVersion: EVALUATION_VERSION,
      }),
    ).toThrowError(
      new TypeError("Scenario capabilityId must not contain \"::\"."),
    );
    expect(storage.setCalls).toBe(0);
    expect(store.snapshot().attempts).toEqual([]);
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

  it("captures every exercise input accessor exactly once", () => {
    const reads = {
      capabilityId: 0,
      score: 0,
      scenarioId: 0,
      evaluationVersion: 0,
    };
    const input = {
      get capabilityId(): string {
        reads.capabilityId += 1;
        return reads.capabilityId === 1 ? CAPABILITY_ID : "";
      },
      get score(): number {
        reads.score += 1;
        return reads.score === 1 ? 1 : Number.NaN;
      },
      get scenarioId(): string | null {
        reads.scenarioId += 1;
        return reads.scenarioId === 1 ? null : SCENARIO_ID;
      },
      get evaluationVersion(): string {
        reads.evaluationVersion += 1;
        return reads.evaluationVersion === 1 ? EVALUATION_VERSION : "";
      },
    };
    const store = createProfileStore(localStorage, fixedClock());

    store.recordExercise(input);

    expect(reads).toEqual({
      capabilityId: 1,
      score: 1,
      scenarioId: 1,
      evaluationVersion: 1,
    });
    expect(store.snapshot().attempts[0]).toMatchObject({
      kind: "exercise",
      capabilityId: CAPABILITY_ID,
      score: 1,
      scenarioId: null,
      evaluationVersion: EVALUATION_VERSION,
    });
  });

  it("captures every diagnostic input accessor exactly once", () => {
    const reads = {
      capabilityId: 0,
      severity: 0,
      scenarioId: 0,
      evaluationVersion: 0,
    };
    const input = {
      get capabilityId(): string {
        reads.capabilityId += 1;
        return reads.capabilityId === 1 ? CAPABILITY_ID : "";
      },
      get severity(): DiagnosticSeverity {
        reads.severity += 1;
        return reads.severity === 1 ? "minor" : "severe";
      },
      get scenarioId(): string | null {
        reads.scenarioId += 1;
        return reads.scenarioId === 1 ? null : SCENARIO_ID;
      },
      get evaluationVersion(): string {
        reads.evaluationVersion += 1;
        return reads.evaluationVersion === 1 ? EVALUATION_VERSION : "";
      },
    };
    const store = createProfileStore(localStorage, fixedClock());

    store.recordDiagnostic(input);

    expect(reads).toEqual({
      capabilityId: 1,
      severity: 1,
      scenarioId: 1,
      evaluationVersion: 1,
    });
    expect(store.snapshot().attempts[0]).toMatchObject({
      kind: "diagnostic",
      capabilityId: CAPABILITY_ID,
      severity: "minor",
      scenarioId: null,
      evaluationVersion: EVALUATION_VERSION,
    });
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

  it("captures every supplied context accessor exactly once", () => {
    const reads = {
      lastMode: 0,
      lastScenario: 0,
      lastUnit: 0,
      lastNode: 0,
    };
    const update = {
      get lastMode(): string | null {
        reads.lastMode += 1;
        return reads.lastMode === 1 ? "course" : "";
      },
      get lastScenario(): string | null {
        reads.lastScenario += 1;
        return reads.lastScenario === 1 ? SCENARIO_ID : "";
      },
      get lastUnit(): string | null {
        reads.lastUnit += 1;
        return reads.lastUnit === 1 ? "TU-AUDIO-001" : "";
      },
      get lastNode(): string | null {
        reads.lastNode += 1;
        return reads.lastNode === 1 ? CAPABILITY_ID : "";
      },
    };
    const store = createProfileStore(localStorage, fixedClock());

    store.setContext(update);

    expect(reads).toEqual({
      lastMode: 1,
      lastScenario: 1,
      lastUnit: 1,
      lastNode: 1,
    });
    expect(store.snapshot()).toMatchObject({
      lastMode: "course",
      lastScenario: SCENARIO_ID,
      lastUnit: "TU-AUDIO-001",
      lastNode: CAPABILITY_ID,
    });
  });

  it("rejects an empty context update without writing or clearing loadError", () => {
    const storage = new ControlledStorage();
    storage.values.set(LEARNING_PROFILE_STORAGE_KEY, "broken");
    const store = createProfileStore(storage, fixedClock());

    expect(() => store.setContext({})).toThrowError(
      new TypeError("context update must include at least one known field."),
    );
    expect(storage.setCalls).toBe(0);
    expect(storage.values.get(LEARNING_PROFILE_STORAGE_KEY)).toBe("broken");
    expect(store.getLoadError()?.code).toBe("invalid_json");
  });

  it("rejects unknown context fields without writing or clearing loadError", () => {
    const storage = new ControlledStorage();
    storage.values.set(LEARNING_PROFILE_STORAGE_KEY, "broken");
    const store = createProfileStore(storage, fixedClock());
    const update = { lastMode: "course", unknown: "value" };

    expect(() => store.setContext(update)).toThrowError(
      new TypeError("context update contains unknown field: unknown."),
    );
    expect(storage.setCalls).toBe(0);
    expect(storage.values.get(LEARNING_PROFILE_STORAGE_KEY)).toBe("broken");
    expect(store.getLoadError()?.code).toBe("invalid_json");
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

  it("rejects parseable but non-canonical attempt timestamps", () => {
    const profile = validStoredProfile();
    profile.attempts[0].timestamp = "2026-07-14T01:02:03Z";
    const stored = JSON.stringify(profile);
    localStorage.setItem(LEARNING_PROFILE_STORAGE_KEY, stored);

    const store = createProfileStore(localStorage, fixedClock());

    expect(store.snapshot().attempts).toEqual([]);
    expect(store.getLoadError()?.code).toBe("malformed_profile");
    expect(localStorage.getItem(LEARNING_PROFILE_STORAGE_KEY)).toBe(stored);
  });

  it("retains only the latest attempts when loading an oversized profile", () => {
    const attempts = Array.from(
      { length: MAX_ATTEMPTS + 2 },
      (_value, index) => storedExerciseAttempt(index),
    );
    const profile = { ...validStoredProfile(), attempts };
    localStorage.setItem(
      LEARNING_PROFILE_STORAGE_KEY,
      JSON.stringify(profile),
    );

    const loaded = createProfileStore(localStorage, fixedClock()).snapshot();

    expect(loaded.attempts).toHaveLength(MAX_ATTEMPTS);
    expect(loaded.attempts[0]?.capabilityId).toBe(`${CAPABILITY_ID}-2`);
    expect(loaded.attempts.at(-1)?.capabilityId).toBe(
      `${CAPABILITY_ID}-${MAX_ATTEMPTS + 1}`,
    );
  });

  it("drops the oldest attempt before persisting a new boundary attempt", () => {
    const attempts = Array.from(
      { length: MAX_ATTEMPTS },
      (_value, index) => storedExerciseAttempt(index),
    );
    localStorage.setItem(
      LEARNING_PROFILE_STORAGE_KEY,
      JSON.stringify({ ...validStoredProfile(), attempts }),
    );
    const store = createProfileStore(localStorage, fixedClock(SECOND_TIMESTAMP));

    store.recordDiagnostic({
      capabilityId: CAPABILITY_ID,
      severity: "minor",
      scenarioId: null,
      evaluationVersion: EVALUATION_VERSION,
    });

    const profile = store.snapshot();
    const reloaded = createProfileStore(localStorage, fixedClock()).snapshot();
    expect(profile.attempts).toHaveLength(MAX_ATTEMPTS);
    expect(profile.attempts[0]?.capabilityId).toBe(`${CAPABILITY_ID}-1`);
    expect(profile.attempts.at(-1)).toMatchObject({
      kind: "diagnostic",
      capabilityId: CAPABILITY_ID,
      timestamp: SECOND_TIMESTAMP,
    });
    expect(reloaded.attempts).toEqual(profile.attempts);
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

  it.each([
    ["a proxied Date", () => new Proxy(new Date(FIRST_TIMESTAMP), {})],
    ["a Date-prototype impostor", () => Object.create(Date.prototype)],
  ])("rejects %s from the clock with a stable error", (_label, clock) => {
    const storage = new ControlledStorage();
    const store = createProfileStore(storage, clock);

    expect(() =>
      store.recordExercise({
        capabilityId: CAPABILITY_ID,
        score: 1,
        scenarioId: null,
        evaluationVersion: EVALUATION_VERSION,
      }),
    ).toThrowError(new TypeError("Profile clock must return a valid Date."));
    expect(store.snapshot().attempts).toEqual([]);
    expect(storage.setCalls).toBe(0);
  });

  it("uses Date intrinsics instead of overridden instance methods", () => {
    const timestamp = new Date(FIRST_TIMESTAMP);
    Object.defineProperties(timestamp, {
      getTime: {
        value: () => Number.NaN,
      },
      toISOString: {
        value: () => "malicious timestamp",
      },
    });
    const store = createProfileStore(localStorage, () => timestamp);

    store.recordExercise({
      capabilityId: CAPABILITY_ID,
      score: 1,
      scenarioId: null,
      evaluationVersion: EVALUATION_VERSION,
    });

    expect(store.snapshot().attempts[0]?.timestamp).toBe(FIRST_TIMESTAMP);
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
