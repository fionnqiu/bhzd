import { useEffect, useMemo, useRef, useState } from "react";

import type { TeachingRepository } from "../../data/repository";
import type { GraphEngine } from "../../graph/graphEngine";
import {
  createTaskConverter,
  type ConversionResult,
} from "../../tasks/taskConverter";
import { ScenarioSwitcher } from "../scenarios/ScenarioSwitcher";
import { TaskCardView } from "./TaskCardView";

export interface TaskConverterViewProps {
  repository: TeachingRepository;
  graphEngine: GraphEngine;
  currentScenarioId: string | null;
  dataType: string | null;
  onSelectScenario?: (scenarioId: string | null) => void;
  onApplyScenario?: (scenarioId: string) => void;
}

const MISSING_FIELD_LABELS: Readonly<Record<string, string>> = {
  data_type: "数据类型",
  goal: "任务目标",
};

interface ScenarioSuggestionProps {
  scenarioId: string;
  repository: Pick<TeachingRepository, "getScenario">;
  onConfirm?: (scenarioId: string) => void;
  onDismiss: () => void;
}

function ScenarioSuggestion({
  scenarioId,
  repository,
  onConfirm,
  onDismiss,
}: ScenarioSuggestionProps) {
  const scenario = repository.getScenario(scenarioId);
  const name = scenario?.name ?? scenarioId;

  return (
    <section className="task-converter__scenario-suggestion" aria-label="场景建议">
      <p role="status" aria-live="polite">
        检测到场景建议：{name}。建议切换到{name}场景；仍保持当前场景，确认后才会切换。
      </p>
      {onConfirm === undefined ? null : (
        <button
          type="button"
          aria-label={`确认应用场景：${name}`}
          onClick={() => onConfirm(scenarioId)}
        >
          确认应用建议
        </button>
      )}
      <button type="button" onClick={onDismiss}>
        取消场景建议
      </button>
    </section>
  );
}

interface ClarificationViewProps {
  result: Extract<ConversionResult, { kind: "clarification" }>;
}

function ClarificationView({ result }: ClarificationViewProps) {
  return (
    <section className="task-converter__clarification" aria-labelledby="task-clarification-title">
      <h2 id="task-clarification-title">需要补充信息</h2>
      <p role="status" aria-live="polite">
        请明确{result.missing.map((field) => MISSING_FIELD_LABELS[field]).join("、")}。
      </p>
      {result.candidates.length > 0 ? (
        <ul aria-label="可选匹配项">
          {result.candidates.map((candidate) => (
            <li key={candidate}>{candidate}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function MatchEvidence({ evidence }: { evidence: readonly string[] }) {
  if (evidence.length === 0) {
    return null;
  }

  return (
    <section className="task-converter__evidence" aria-labelledby="task-evidence-title">
      <h2 id="task-evidence-title">匹配证据</h2>
      <ul aria-label="匹配证据">
        {evidence.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

export function TaskConverterView({
  repository,
  graphEngine,
  currentScenarioId,
  dataType,
  onSelectScenario,
  onApplyScenario,
}: TaskConverterViewProps) {
  const converter = useMemo(
    () => createTaskConverter(repository, graphEngine),
    [graphEngine, repository],
  );
  const [taskDescription, setTaskDescription] = useState("");
  const [result, setResult] = useState<ConversionResult | null>(null);
  const [dismissedSuggestionId, setDismissedSuggestionId] = useState<string | null>(
    null,
  );
  const previousScenarioIdRef = useRef(currentScenarioId);

  const suggestedScenarioId =
    result?.suggestedScenarioId !== null &&
    result?.suggestedScenarioId !== undefined &&
    result.suggestedScenarioId !== dismissedSuggestionId
      ? result.suggestedScenarioId
      : null;
  const matchedDataType = result?.matchedDataType ?? null;
  const suggestedScenario =
    suggestedScenarioId === null
      ? undefined
      : repository.getScenario(suggestedScenarioId);
  const availableSuggestedScenarioId =
    suggestedScenario?.review_status === "published" &&
    suggestedScenario.student_visible === true
      ? suggestedScenarioId
      : null;
  const suggestedScenarioIsSupported =
    availableSuggestedScenarioId !== null &&
    matchedDataType !== null &&
    suggestedScenario?.supported_data_types.includes(matchedDataType) === true;

  useEffect(() => {
    if (previousScenarioIdRef.current === currentScenarioId) {
      return;
    }

    previousScenarioIdRef.current = currentScenarioId;
    if (result !== null) {
      setDismissedSuggestionId(null);
      setResult(converter.convert(taskDescription, currentScenarioId));
    }
  }, [converter, currentScenarioId, result, taskDescription]);

  const convertTask = () => {
    setDismissedSuggestionId(null);
    setResult(converter.convert(taskDescription, currentScenarioId));
  };

  const confirmScenario = (scenarioId: string) => {
    const scenario = repository.getScenario(scenarioId);
    if (
      matchedDataType === null ||
      scenario?.review_status !== "published" ||
      scenario.student_visible !== true ||
      !scenario.supported_data_types.includes(matchedDataType)
    ) {
      return;
    }

    setResult(converter.convert(taskDescription, scenarioId));
    onApplyScenario?.(scenarioId);
    setDismissedSuggestionId(scenarioId);
  };

  const selectScenario = (scenarioId: string | null) => {
    onSelectScenario?.(scenarioId);
    if (result !== null) {
      setDismissedSuggestionId(null);
      setResult(converter.convert(taskDescription, scenarioId));
    }
  };

  return (
    <section className="task-converter" aria-labelledby="task-converter-title">
      <h1 id="task-converter-title">企业任务转化</h1>
      {onSelectScenario === undefined ? null : (
        <ScenarioSwitcher
          repository={repository}
          currentScenarioId={currentScenarioId}
          dataType={dataType}
          onSelectScenario={selectScenario}
        />
      )}
      <label htmlFor="enterprise-task-description">企业任务描述</label>
      <textarea
        id="enterprise-task-description"
        value={taskDescription}
        onChange={(event) => setTaskDescription(event.target.value)}
      />
      <button type="button" onClick={convertTask}>
        生成学习任务卡
      </button>

      {availableSuggestedScenarioId === null ? null : (
        <ScenarioSuggestion
          scenarioId={availableSuggestedScenarioId}
          repository={repository}
          onConfirm={
            onApplyScenario === undefined || !suggestedScenarioIsSupported
              ? undefined
              : confirmScenario
          }
          onDismiss={() =>
            setDismissedSuggestionId(availableSuggestedScenarioId)
          }
        />
      )}

      {result?.kind === "clarification" ? (
        <ClarificationView result={result} />
      ) : null}
      {result === null ? null : <MatchEvidence evidence={result.matchEvidence} />}
      {result?.kind === "cards" ? (
        <section className="task-converter__cards" aria-labelledby="task-plan-title">
          <h2 id="task-plan-title">按前置关系排序的补强计划</h2>
          {result.cards.map((card, index) => (
            <TaskCardView key={`${index}-${card.name}`} card={card} position={index + 1} />
          ))}
        </section>
      ) : null}
    </section>
  );
}
