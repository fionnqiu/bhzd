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

export interface ScenarioApplication {
  scenarioId: string | null;
  dataType: string;
  rules: ScenarioRule[];
  appliedRules: AppliedScenarioRule[];
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

export const createScenarioEngine = (
  repository: TeachingRepository,
): ScenarioEngine => {
  const applyRules = (input: ApplyScenarioRulesInput): ScenarioApplication => {
    const dataType = input.dataType.trim().toLowerCase();
    let rules = cloneBaseRules(input.baseRules);
    const evidence: string[] = [];
    const appliedRules: AppliedScenarioRule[] = [];

    if (input.scenarioId === null) {
      return {
        scenarioId: null,
        dataType,
        rules,
        appliedRules,
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
        scenarioId: input.scenarioId,
        dataType,
        rules,
        appliedRules,
        evidence,
      };
    }

    const scenarioRecord: Record<string, unknown> = scenario;
    if (!hasPublishedState(scenarioRecord)) {
      return {
        scenarioId: input.scenarioId,
        dataType,
        rules,
        appliedRules,
        evidence,
      };
    }

    const rawOverrides = scenario.overrides;
    if (!Array.isArray(rawOverrides)) {
      return {
        scenarioId: input.scenarioId,
        dataType,
        rules,
        appliedRules,
        evidence,
      };
    }

    evidence.push(`scenario:${scenario.id}:published`);
    evidence.push(`scenario:${scenario.id}:declares:${dataType}`);

    for (const rawOverride of rawOverrides) {
      const override = readPublishedOverride(rawOverride);
      if (
        override === null ||
        override.dataType !== dataType ||
        !rules.some(({ id }) => id === override.baseRuleRef)
      ) {
        continue;
      }

      if (override.overrideType === "replace") {
        rules = rules.filter(({ id }) => id !== override.baseRuleRef);
      }

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
    }

    return {
      scenarioId: input.scenarioId,
      dataType,
      rules: rules.map((rule) => ({
        ...rule,
        sourceRefs: [...rule.sourceRefs],
      })),
      appliedRules: appliedRules.map((rule) => ({
        ...rule,
        evidence: [...rule.evidence],
      })),
      evidence: [...evidence],
    };
  };

  return Object.freeze({ applyRules });
};
