import type { GraphNode, TeachingUnit } from "../data/contracts";
import type {
  DeepReadonly,
  TeachingRepository,
} from "../data/repository";
import {
  createScenarioEngine,
  type ScenarioEngine,
  type ScenarioRule,
} from "../scenarios/scenarioEngine";
import { APPROVED_PRODUCT_METADATA } from "./productMetadata";

export interface TaskCardProvenance {
  roleSourceRef: string;
  sceneSourceRef: string;
}

export interface TaskCard {
  name: string;
  objectives: string[];
  role: string;
  scene: string;
  capabilityPath: string[];
  capabilityIds: string[];
  knowledgeIds: string[];
  certificateIds: string[];
  steps: string[];
  commonErrors: string[];
  resourceIds: string[];
  selfCheckItems: string[];
  teachingUnitIds: string[];
  scenarioRuleIds: string[];
  scenarioRules: ScenarioRule[];
  contentKind: "lesson" | "structure";
  provenance: TaskCardProvenance;
}

const unique = (values: readonly string[]): string[] => [...new Set(values)];

const stringArray = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];

const uniqueUnits = (
  units: readonly DeepReadonly<TeachingUnit>[],
): DeepReadonly<TeachingUnit>[] => {
  const seen = new Set<string>();
  const result: DeepReadonly<TeachingUnit>[] = [];

  for (const unit of units) {
    if (!seen.has(unit.id)) {
      seen.add(unit.id);
      result.push(unit);
    }
  }

  return result;
};

const collectCapabilityUnits = (
  repository: TeachingRepository,
  capabilityId: string,
): DeepReadonly<TeachingUnit>[] => {
  const units: DeepReadonly<TeachingUnit>[] = [
    ...repository.getConsumableUnitsForNode(capabilityId),
  ];

  for (const edge of repository.getOutgoingEdges(capabilityId)) {
    if (
      edge.relation === "SUP" &&
      repository.getNode(edge.target)?.type === "TSK"
    ) {
      units.push(...repository.getConsumableUnitsForNode(edge.target));
    }
  }

  return uniqueUnits(units);
};

const relationBackedUnitKnowledge = (
  repository: TeachingRepository,
  units: readonly DeepReadonly<TeachingUnit>[],
): string[] =>
  unique(
    units.flatMap((unit) =>
      unit.rule_refs.filter((ruleId) => {
        const node = repository.getNode(ruleId);
        return (
          node?.type === "KNG" &&
          repository
            .getOutgoingEdges(ruleId)
            .some(({ relation }) => relation === "ISA" || relation === "SUP")
        );
      }),
    ),
  );

const relatedNodeIds = (
  repository: TeachingRepository,
  capabilityId: string,
  nodeType: "KNG" | "RES",
): string[] =>
  unique(
    repository
      .getIncomingEdges(capabilityId)
      .filter(
        (edge) =>
          (edge.relation === "ISA" || edge.relation === "SUP") &&
          repository.getNode(edge.source)?.type === nodeType,
      )
      .map(({ source }) => source),
  );

const certificateIds = (
  repository: TeachingRepository,
  capabilityId: string,
): string[] =>
  unique(
    repository
      .getOutgoingEdges(capabilityId)
      .filter(
        (edge) =>
          edge.relation === "MAPCERT" &&
          repository.getNode(edge.target)?.type === "CERT",
      )
      .map(({ target }) => target),
  );

const lessonSteps = (
  units: readonly DeepReadonly<TeachingUnit>[],
  scenarioContents: readonly string[],
): string[] => {
  const publishedContent = unique(
    units.flatMap((unit) => [
      ...stringArray(unit.goals),
      ...unit.learning_objectives,
      unit.exercise.student_action,
      unit.title,
    ]),
  );
  const overrides = unique(scenarioContents);
  const baseLimit = Math.max(0, 9 - overrides.length);
  return unique([...publishedContent.slice(0, baseLimit), ...overrides]).slice(
    0,
    9,
  );
};

const structuralSteps = (node: DeepReadonly<GraphNode>): string[] =>
  unique([node.label, node.description, node.data_types.join(",")]).slice(0, 9);

const buildTaskCard = (
  repository: TeachingRepository,
  scenarioEngine: ScenarioEngine,
  capabilityId: string,
  capabilityPath: string[],
  dataType: string,
  scenarioId: string | null,
): TaskCard | null => {
  const capability = repository.getNode(capabilityId);
  if (capability === undefined || capability.type !== "CAP") {
    return null;
  }

  const units = collectCapabilityUnits(repository, capabilityId);
  const knowledgeIds = unique([
    ...relatedNodeIds(repository, capabilityId, "KNG"),
    ...relationBackedUnitKnowledge(repository, units),
  ]);
  const baseRules = knowledgeIds.flatMap((knowledgeId) => {
    const node = repository.getNode(knowledgeId);
    return node === undefined
      ? []
      : [
          {
            id: node.id,
            content: node.description,
            sourceRefs: [...node.source_refs],
          },
        ];
  });
  const scenarioApplication = scenarioEngine.applyRules({
    scenarioId,
    dataType,
    baseRules,
  });
  const scenarioRules = scenarioApplication.rules.filter(
    ({ origin }) => origin === "scenario",
  );
  const scenario = scenarioId === null ? undefined : repository.getScenario(scenarioId);
  const scenarioSourceRef =
    scenario === undefined
      ? undefined
      : APPROVED_PRODUCT_METADATA.scenarioDocuments[scenario.id];
  const hasSourcedScenario =
    scenario !== undefined && scenarioSourceRef !== undefined;
  const contentKind = units.length > 0 ? "lesson" : "structure";
  const objectives =
    contentKind === "lesson"
      ? unique(units.flatMap(({ learning_objectives: values }) => values))
      : [capability.description];
  const steps =
    contentKind === "lesson"
      ? lessonSteps(
          units,
          scenarioRules.map(({ content }) => content),
        )
      : structuralSteps(capability);

  return {
    name: units[0]?.title ?? capability.label,
    objectives,
    role: APPROVED_PRODUCT_METADATA.role.value,
    scene: hasSourcedScenario
      ? scenario.name
      : APPROVED_PRODUCT_METADATA.defaultScene.value,
    capabilityPath: [...capabilityPath],
    capabilityIds: [capabilityId],
    knowledgeIds,
    certificateIds: certificateIds(repository, capabilityId),
    steps,
    commonErrors: unique(
      units.flatMap((unit) => stringArray(unit.common_errors)),
    ),
    resourceIds: relatedNodeIds(repository, capabilityId, "RES"),
    selfCheckItems:
      contentKind === "lesson" ? [...objectives] : [capability.description],
    teachingUnitIds: units.map(({ id }) => id),
    scenarioRuleIds: scenarioApplication.appliedRules.map(
      ({ ruleId }) => ruleId,
    ),
    scenarioRules: scenarioRules.map((rule) => ({
      ...rule,
      sourceRefs: [...rule.sourceRefs],
    })),
    contentKind,
    provenance: {
      roleSourceRef: APPROVED_PRODUCT_METADATA.role.sourceRef,
      sceneSourceRef: hasSourcedScenario
        ? scenarioSourceRef
        : APPROVED_PRODUCT_METADATA.defaultScene.sourceRef,
    },
  };
};

export const buildTaskCards = (
  repository: TeachingRepository,
  orderedCapabilityIds: readonly string[],
  dataType: string,
  scenarioId: string | null,
): TaskCard[] => {
  const scenarioEngine = createScenarioEngine(repository);

  return orderedCapabilityIds.flatMap((capabilityId, index) => {
    const card = buildTaskCard(
      repository,
      scenarioEngine,
      capabilityId,
      orderedCapabilityIds.slice(0, index + 1),
      dataType,
      scenarioId,
    );
    return card === null ? [] : [card];
  });
};
