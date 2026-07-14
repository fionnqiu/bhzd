import type { TeachingRepository } from "../data/repository";

export interface ScenarioRule {
  id: string;
  content: string;
  sourceRefs: string[];
  origin: "base" | "scenario";
  baseRuleRef: string | null;
}

export interface BaseScenarioRule {
  readonly id: string;
  readonly content: string;
  readonly sourceRefs: readonly string[];
}

export interface AppliedScenarioRule {
  ruleId: string;
  baseRuleRef: string;
  overrideType: "add" | "replace";
  evidence: string[];
}

export interface ScenarioRuleConflict {
  baseRuleRef: string;
  ruleIds: string[];
  reason: "multiple_replace";
}

export interface ScenarioApplication {
  scenarioId: string | null;
  scenarioName: string | null;
  dataType: string;
  rules: ScenarioRule[];
  appliedRules: AppliedScenarioRule[];
  conflicts: ScenarioRuleConflict[];
  evidence: string[];
}

export interface ApplyScenarioRulesInput {
  readonly scenarioId: string | null;
  readonly dataType: string;
  readonly baseRules: readonly BaseScenarioRule[];
}

export interface ScenarioEngine {
  applyRules(input: ApplyScenarioRulesInput): ScenarioApplication;
}

interface PublishedOverride {
  ruleId: string;
  dataType: string;
  baseRuleRef: string;
  overrideType: "add" | "replace";
  content: string;
  sourceRefs: string[];
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === "string");

const hasPublishedState = (record: Record<string, unknown>): boolean => {
  for (const field of ["publication_state", "publication_status"] as const) {
    const value = record[field];
    if (value !== undefined && value !== "published") {
      return false;
    }
  }

  return true;
};

const readPublishedOverride = (value: unknown): PublishedOverride | null => {
  if (!isRecord(value) || value.review_status !== "published") {
    return null;
  }
  if (!hasPublishedState(value)) {
    return null;
  }

  const {
    rule_id: ruleId,
    data_type: dataType,
    base_rule_ref: baseRuleRef,
    override_type: overrideType,
    content,
    source_refs: sourceRefs,
  } = value;

  if (
    typeof ruleId !== "string" ||
    typeof dataType !== "string" ||
    typeof baseRuleRef !== "string" ||
    (overrideType !== "add" && overrideType !== "replace") ||
    typeof content !== "string" ||
    !isStringArray(sourceRefs)
  ) {
    return null;
  }

  return {
    ruleId,
    dataType,
    baseRuleRef,
    overrideType,
    content,
    sourceRefs: [...sourceRefs],
  };
};

const cloneBaseRules = (
  baseRules: readonly BaseScenarioRule[],
): ScenarioRule[] =>
  baseRules.map((rule) => ({
    id: rule.id,
    content: rule.content,
    sourceRefs: [...rule.sourceRefs],
    origin: "base",
    baseRuleRef: null,
  }));

const compareIds = (left: string, right: string): number =>
  left < right ? -1 : left > right ? 1 : 0;

export const createScenarioEngine = (
  repository: TeachingRepository,
): ScenarioEngine => {
  const applyRules = (input: ApplyScenarioRulesInput): ScenarioApplication => {
    const dataType = input.dataType.trim().toLowerCase();
    let rules = cloneBaseRules(input.baseRules);
    const evidence: string[] = [];
    const appliedRules: AppliedScenarioRule[] = [];
    const conflicts: ScenarioRuleConflict[] = [];

    if (input.scenarioId === null) {
      return {
        scenarioId: null,
        scenarioName: null,
        dataType,
        rules,
        appliedRules,
        conflicts,
        evidence,
      };
    }

    const scenario = repository.getScenario(input.scenarioId);
    if (
      scenario === undefined ||
      scenario.review_status !== "published" ||
      scenario.student_visible !== true ||
      !scenario.supported_data_types.includes(dataType)
    ) {
      return {
        scenarioId: null,
        scenarioName: null,
        dataType,
        rules,
        appliedRules,
        conflicts,
        evidence,
      };
    }

    const scenarioRecord: Record<string, unknown> = scenario;
    if (!hasPublishedState(scenarioRecord)) {
      return {
        scenarioId: null,
        scenarioName: null,
        dataType,
        rules,
        appliedRules,
        conflicts,
        evidence,
      };
    }

    evidence.push(`scenario:${scenario.id}:published`);
    evidence.push(`scenario:${scenario.id}:declares:${dataType}`);

    const baseRuleIds = new Set(input.baseRules.map(({ id }) => id));
    const overrideGroups = new Map<string, PublishedOverride[]>();
    const rawOverrides = Array.isArray(scenario.overrides)
      ? scenario.overrides
      : [];
    for (const rawOverride of rawOverrides) {
      const override = readPublishedOverride(rawOverride);
      if (
        override === null ||
        override.dataType !== dataType ||
        !baseRuleIds.has(override.baseRuleRef)
      ) {
        continue;
      }
      const group = overrideGroups.get(override.baseRuleRef);
      if (group === undefined) {
        overrideGroups.set(override.baseRuleRef, [override]);
      } else {
        group.push(override);
      }
    }

    const applyOverride = (override: PublishedOverride): void => {
      rules.push({
        id: override.ruleId,
        content: override.content,
        sourceRefs: [...override.sourceRefs],
        origin: "scenario",
        baseRuleRef: override.baseRuleRef,
      });

      const ruleEvidence = [
        `override:${override.ruleId}:published`,
        `override:${override.ruleId}:data_type:${dataType}`,
        `override:${override.ruleId}:${override.overrideType}:${override.baseRuleRef}`,
      ];
      appliedRules.push({
        ruleId: override.ruleId,
        baseRuleRef: override.baseRuleRef,
        overrideType: override.overrideType,
        evidence: ruleEvidence,
      });
      evidence.push(...ruleEvidence);
    };

    const baseRuleOrder = new Map(
      input.baseRules.map(({ id }, index) => [id, index]),
    );
    const orderedGroups = [...overrideGroups.entries()].sort(
      ([left], [right]) =>
        (baseRuleOrder.get(left) ?? Number.MAX_SAFE_INTEGER) -
          (baseRuleOrder.get(right) ?? Number.MAX_SAFE_INTEGER) ||
        compareIds(left, right),
    );

    for (const [baseRuleRef, group] of orderedGroups) {
      const orderedOverrides = [...group].sort((left, right) =>
        compareIds(left.ruleId, right.ruleId),
      );
      const replacements = orderedOverrides.filter(
        ({ overrideType }) => overrideType === "replace",
      );
      if (replacements.length > 1) {
        const ruleIds = replacements.map(({ ruleId }) => ruleId);
        conflicts.push({
          baseRuleRef,
          ruleIds,
          reason: "multiple_replace",
        });
        evidence.push(
          `override_conflict:${baseRuleRef}:multiple_replace:${ruleIds.join("+")}`,
        );
        continue;
      }

      const replacement = replacements[0];
      if (replacement !== undefined) {
        rules = rules.filter(({ id }) => id !== baseRuleRef);
        applyOverride(replacement);
      }
      for (const addition of orderedOverrides.filter(
        ({ overrideType }) => overrideType === "add",
      )) {
        applyOverride(addition);
      }
    }

    return {
      scenarioId: scenario.id,
      scenarioName: scenario.name,
      dataType,
      rules: rules.map((rule) => ({
        ...rule,
        sourceRefs: [...rule.sourceRefs],
      })),
      appliedRules: appliedRules.map((rule) => ({
        ...rule,
        evidence: [...rule.evidence],
      })),
      conflicts: conflicts.map((conflict) => ({
        ...conflict,
        ruleIds: [...conflict.ruleIds],
      })),
      evidence: [...evidence],
    };
  };

  return Object.freeze({ applyRules });
};
