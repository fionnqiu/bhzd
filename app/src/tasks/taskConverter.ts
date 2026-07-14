import { graph } from "../data/rawData";
import type { TeachingRepository } from "../data/repository";
import {
  createGraphEngine,
  type GraphEngine,
} from "../graph/graphEngine";
import { createScenarioEngine } from "../scenarios/scenarioEngine";
import {
  buildTaskCards,
  type TaskCard,
} from "./taskCardBuilder";
import {
  candidateLabels,
  detectDataTypeMatches,
  detectScenario,
  getTaskNode,
  hasGoalMarker,
  normalizeTaskText,
  rankTaskMatches,
} from "./taskKeywords";

export type { TaskCard } from "./taskCardBuilder";

type MissingField = "data_type" | "goal";

export type ConversionResult =
  | {
      kind: "clarification";
      missing: MissingField[];
      candidates: string[];
      matchEvidence: string[];
      appliedScenarioId: string | null;
      suggestedScenarioId: string | null;
    }
  | {
      kind: "cards";
      cards: TaskCard[];
      matchEvidence: string[];
      appliedScenarioId: string | null;
      suggestedScenarioId: string | null;
    };

export interface TaskConverter {
  convert(text: string, currentScenarioId: string | null): ConversionResult;
}

const canonicalGraphEngine = createGraphEngine(graph);

const unique = (values: readonly string[]): string[] => [...new Set(values)];

export type CapabilityRelationKind = "SUP" | "primary_capability_ref";

export type CapabilitySelection =
  | {
      kind: "selected";
      capabilityId: string;
      relationKind: CapabilityRelationKind;
      evidence: string[];
    }
  | {
      kind: "ambiguous" | "missing";
      candidates: string[];
      evidence: string[];
    };

const capabilityCandidate = (
  repository: TeachingRepository,
  capabilityId: string,
): string => {
  const capability = repository.getNode(capabilityId);
  return `${capabilityId}|${capability?.label ?? capabilityId}`;
};

export const selectTaskCapability = (
  repository: TeachingRepository,
  taskId: string,
): CapabilitySelection => {
  const taskNode = repository.getNode(taskId);
  if (taskNode === undefined || taskNode.type !== "TSK") {
    return {
      kind: "missing",
      candidates: [],
      evidence: [`capability_selection:missing_task:${taskId}`],
    };
  }

  const supCapabilityIds = unique(
    repository
      .getIncomingEdges(taskNode.id)
      .filter(
        (edge) =>
          edge.relation === "SUP" &&
          repository.getNode(edge.source)?.type === "CAP",
      )
      .map(({ source }) => source),
  );

  const primaryCapabilityRef = taskNode.primary_capability_ref;
  const primaryCapability =
    typeof primaryCapabilityRef === "string" &&
    repository.getNode(primaryCapabilityRef)?.type === "CAP"
      ? primaryCapabilityRef
      : null;

  if (supCapabilityIds.length === 0 && primaryCapability !== null) {
    return {
      kind: "selected",
      capabilityId: primaryCapability,
      relationKind: "primary_capability_ref",
      evidence: [
        `capability_selection:primary_capability_ref:${primaryCapability}`,
      ],
    };
  }

  if (supCapabilityIds.length === 1) {
    const capabilityId = supCapabilityIds[0];
    if (capabilityId === undefined) {
      return {
        kind: "missing",
        candidates: [],
        evidence: [`capability_selection:missing:${taskId}`],
      };
    }
    if (primaryCapability !== null && primaryCapability !== capabilityId) {
      const candidates = unique([capabilityId, primaryCapability]);
      return {
        kind: "ambiguous",
        candidates: candidates.map((id) => capabilityCandidate(repository, id)),
        evidence: [
          `capability_selection:ambiguous:${candidates.join("+")}`,
        ],
      };
    }

    return {
      kind: "selected",
      capabilityId,
      relationKind: "SUP",
      evidence: [
        primaryCapability === capabilityId
          ? `capability_selection:SUP:${capabilityId}:primary_capability_ref`
          : `capability_selection:SUP:${capabilityId}`,
      ],
    };
  }

  if (
    supCapabilityIds.length > 1 &&
    primaryCapability !== null &&
    supCapabilityIds.includes(primaryCapability)
  ) {
    return {
      kind: "selected",
      capabilityId: primaryCapability,
      relationKind: "SUP",
      evidence: [
        `capability_selection:SUP:${primaryCapability}:primary_capability_ref`,
      ],
    };
  }

  const candidateIds = unique([
    ...supCapabilityIds,
    ...(primaryCapability === null ? [] : [primaryCapability]),
  ]);
  if (candidateIds.length > 0) {
    return {
      kind: "ambiguous",
      candidates: candidateIds.map((id) => capabilityCandidate(repository, id)),
      evidence: [
        `capability_selection:ambiguous:${candidateIds.join("+")}`,
      ],
    };
  }

  return {
    kind: "missing",
    candidates: [],
    evidence: [`capability_selection:missing:${taskId}`],
  };
};

const clarification = (
  missing: MissingField[],
  candidates: string[],
  appliedScenarioId: string | null,
  suggestedScenarioId: string | null,
  matchEvidence: string[] = [],
): ConversionResult => ({
  kind: "clarification",
  missing,
  candidates,
  matchEvidence,
  appliedScenarioId,
  suggestedScenarioId,
});

export const createTaskConverter = (
  repository: TeachingRepository,
  graphEngine: GraphEngine = canonicalGraphEngine,
): TaskConverter => {
  const convert = (
    text: string,
    currentScenarioId: string | null,
  ): ConversionResult => {
    const normalizedText = normalizeTaskText(text);
    const sceneMatch = detectScenario(normalizedText);
    const suggestedScenarioId =
      sceneMatch !== null && sceneMatch.id !== currentScenarioId
        ? sceneMatch.id
        : null;
    const dataTypeMatches = detectDataTypeMatches(normalizedText);

    if (normalizedText.length === 0) {
      return clarification(
        ["data_type", "goal"],
        candidateLabels(null),
        null,
        suggestedScenarioId,
      );
    }

    if (dataTypeMatches.length === 0) {
      return clarification(
        hasGoalMarker(normalizedText)
          ? ["data_type"]
          : ["data_type", "goal"],
        candidateLabels(null),
        null,
        suggestedScenarioId,
      );
    }

    if (dataTypeMatches.length > 1) {
      return clarification(
        ["data_type"],
        unique(
          dataTypeMatches.flatMap(({ id }) => candidateLabels(id)),
        ),
        null,
        suggestedScenarioId,
        dataTypeMatches.map(
          ({ id, keywords }) =>
            `data_type_ambiguous:${id}:${keywords.join("+")}`,
        ),
      );
    }

    const dataTypeMatch = dataTypeMatches[0];
    if (dataTypeMatch === undefined) {
      return clarification(
        ["data_type"],
        candidateLabels(null),
        null,
        suggestedScenarioId,
      );
    }

    const scenarioApplication = createScenarioEngine(repository).applyRules({
      scenarioId: currentScenarioId,
      dataType: dataTypeMatch.id,
      baseRules: [],
    });
    const appliedScenarioId = scenarioApplication.scenarioId;

    const taskMatch = rankTaskMatches(normalizedText, dataTypeMatch.id)[0];
    if (taskMatch === undefined) {
      return clarification(
        ["goal"],
        candidateLabels(dataTypeMatch.id),
        appliedScenarioId,
        suggestedScenarioId,
      );
    }

    const taskNode = getTaskNode(taskMatch.id);
    if (taskNode === undefined) {
      return clarification(
        ["goal"],
        candidateLabels(dataTypeMatch.id),
        appliedScenarioId,
        suggestedScenarioId,
      );
    }

    const capabilitySelection = selectTaskCapability(repository, taskNode.id);
    if (capabilitySelection.kind !== "selected") {
      return clarification(
        ["goal"],
        capabilitySelection.candidates.length > 0
          ? capabilitySelection.candidates
          : [`${taskNode.id}|${taskNode.label}`],
        appliedScenarioId,
        suggestedScenarioId,
        capabilitySelection.evidence,
      );
    }
    const targetCapability = repository.getNode(
      capabilitySelection.capabilityId,
    );
    if (targetCapability === undefined || targetCapability.type !== "CAP") {
      return clarification(
        ["goal"],
        [`${taskNode.id}|${taskNode.label}`],
        appliedScenarioId,
        suggestedScenarioId,
        capabilitySelection.evidence,
      );
    }

    const plan = graphEngine.remediationPlan(targetCapability.id, () => null);
    if (plan.cycleDetected) {
      return clarification(
        ["goal"],
        [`${taskNode.id}|${taskNode.label}`],
        appliedScenarioId,
        suggestedScenarioId,
      );
    }

    const cards = buildTaskCards(
      repository,
      plan.steps.map(({ nodeId }) => nodeId),
      dataTypeMatch.id,
      appliedScenarioId,
    );
    const targetCard = cards.at(-1);
    const matchEvidence = unique([
      `data_type:${dataTypeMatch.id}:${dataTypeMatch.keywords.join("+")}`,
      `task:${taskNode.id}:keywords=${taskMatch.keywords.join("+")};label=${taskNode.label};description=${taskNode.description};data_type=${dataTypeMatch.id}`,
      ...capabilitySelection.evidence,
      `capability:${targetCapability.id}:${capabilitySelection.relationKind}:${taskNode.id};label=${targetCapability.label};description=${targetCapability.description}`,
      ...(targetCard?.knowledgeIds.map((knowledgeId) => {
        const knowledge = repository.getNode(knowledgeId);
        return `knowledge:${knowledgeId}:label=${knowledge?.label ?? ""};description=${knowledge?.description ?? ""}`;
      }) ?? []),
      ...(sceneMatch === null
        ? []
        : [
            `scenario:suggested:${sceneMatch.id}:keywords=${sceneMatch.keywords.join("+")}`,
          ]),
      ...scenarioApplication.evidence,
      ...cards.flatMap(({ matchEvidence }) => matchEvidence),
      ...cards.flatMap(({ scenarioRules }) =>
        scenarioRules.map(
          ({ id, baseRuleRef }) =>
            `scenario:applied:${id}:base_rule_ref=${baseRuleRef ?? ""}`,
        ),
      ),
    ]);

    return {
      kind: "cards",
      cards,
      matchEvidence,
      appliedScenarioId,
      suggestedScenarioId,
    };
  };

  return Object.freeze({ convert });
};
