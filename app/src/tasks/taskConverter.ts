import type { GraphNode } from "../data/contracts";
import { graph } from "../data/rawData";
import type {
  DeepReadonly,
  TeachingRepository,
} from "../data/repository";
import {
  createGraphEngine,
  type GraphEngine,
} from "../graph/graphEngine";
import {
  buildTaskCards,
  type TaskCard,
} from "./taskCardBuilder";
import {
  candidateLabels,
  detectDataType,
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

const findTargetCapability = (
  repository: TeachingRepository,
  taskNode: GraphNode,
): DeepReadonly<GraphNode> | null => {
  const relationCapability = repository
    .getIncomingEdges(taskNode.id)
    .find(
      (edge) =>
        edge.relation === "SUP" &&
        repository.getNode(edge.source)?.type === "CAP",
    );
  if (relationCapability !== undefined) {
    return repository.getNode(relationCapability.source) ?? null;
  }

  const primaryCapabilityRef = taskNode.primary_capability_ref;
  if (typeof primaryCapabilityRef !== "string") {
    return null;
  }

  const primaryCapability = repository.getNode(primaryCapabilityRef);
  return primaryCapability?.type === "CAP" ? primaryCapability : null;
};

const clarification = (
  missing: MissingField[],
  candidates: string[],
  appliedScenarioId: string | null,
  suggestedScenarioId: string | null,
): ConversionResult => ({
  kind: "clarification",
  missing,
  candidates,
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
    const dataTypeMatch = detectDataType(normalizedText);

    if (normalizedText.length === 0) {
      return clarification(
        ["data_type", "goal"],
        candidateLabels(null),
        currentScenarioId,
        suggestedScenarioId,
      );
    }

    if (dataTypeMatch === null) {
      return clarification(
        hasGoalMarker(normalizedText)
          ? ["data_type"]
          : ["data_type", "goal"],
        candidateLabels(null),
        currentScenarioId,
        suggestedScenarioId,
      );
    }

    const taskMatch = rankTaskMatches(normalizedText, dataTypeMatch.id)[0];
    if (taskMatch === undefined) {
      return clarification(
        ["goal"],
        candidateLabels(dataTypeMatch.id),
        currentScenarioId,
        suggestedScenarioId,
      );
    }

    const taskNode = getTaskNode(taskMatch.id);
    if (taskNode === undefined) {
      return clarification(
        ["goal"],
        candidateLabels(dataTypeMatch.id),
        currentScenarioId,
        suggestedScenarioId,
      );
    }

    const targetCapability = findTargetCapability(repository, taskNode);
    if (targetCapability === null) {
      return clarification(
        ["goal"],
        [`${taskNode.id}|${taskNode.label}`],
        currentScenarioId,
        suggestedScenarioId,
      );
    }

    const plan = graphEngine.remediationPlan(targetCapability.id, () => null);
    if (plan.cycleDetected) {
      return clarification(
        ["goal"],
        [`${taskNode.id}|${taskNode.label}`],
        currentScenarioId,
        suggestedScenarioId,
      );
    }

    const cards = buildTaskCards(
      repository,
      plan.steps.map(({ nodeId }) => nodeId),
      dataTypeMatch.id,
      currentScenarioId,
    );
    const targetCard = cards.at(-1);
    const matchEvidence = unique([
      `data_type:${dataTypeMatch.id}:${dataTypeMatch.keywords.join("+")}`,
      `task:${taskNode.id}:keywords=${taskMatch.keywords.join("+")};label=${taskNode.label};description=${taskNode.description};data_type=${dataTypeMatch.id}`,
      `capability:${targetCapability.id}:SUP:${taskNode.id};label=${targetCapability.label};description=${targetCapability.description}`,
      ...(targetCard?.knowledgeIds.map((knowledgeId) => {
        const knowledge = repository.getNode(knowledgeId);
        return `knowledge:${knowledgeId}:label=${knowledge?.label ?? ""};description=${knowledge?.description ?? ""}`;
      }) ?? []),
      ...(sceneMatch === null
        ? []
        : [
            `scenario:suggested:${sceneMatch.id}:keywords=${sceneMatch.keywords.join("+")}`,
          ]),
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
      appliedScenarioId: currentScenarioId,
      suggestedScenarioId,
    };
  };

  return Object.freeze({ convert });
};
