import type { TeachingRepository } from "../../data/repository";

const SCENARIO_IDS = [
  "SCN-MEDICAL-001",
  "SCN-CUSTOMER-SERVICE-001",
  "SCN-IN-VEHICLE-001",
  "SCN-CONTENT-SAFETY-001",
] as const;

export interface ScenarioSwitcherProps {
  repository: Pick<TeachingRepository, "getScenario">;
  currentScenarioId: string | null;
  dataType: string | null;
  onSelectScenario: (scenarioId: string | null) => void;
}

export function ScenarioSwitcher({
  repository,
  currentScenarioId,
  dataType,
  onSelectScenario,
}: ScenarioSwitcherProps) {
  const scenarios = SCENARIO_IDS.flatMap((scenarioId) => {
    const scenario = repository.getScenario(scenarioId);
    return scenario?.review_status === "published" &&
      scenario.student_visible === true
      ? [scenario]
      : [];
  });

  return (
    <section
      className="scenario-switcher"
      role="group"
      aria-labelledby="scenario-switcher-title"
    >
      <h2 id="scenario-switcher-title">场景切换</h2>
      <p>选择场景只会切换规则上下文，不会自动应用任务转化建议。</p>
      <div className="scenario-switcher__options">
        <button
          type="button"
          aria-pressed={currentScenarioId === null}
          onClick={() => onSelectScenario(null)}
        >
          通用场景
        </button>
        {scenarios.map((scenario) => {
          const disabled =
            dataType !== null &&
            !scenario.supported_data_types.includes(dataType);

          return (
            <button
              key={scenario.id}
              type="button"
              aria-pressed={currentScenarioId === scenario.id}
              disabled={disabled}
              aria-describedby={
                disabled ? `scenario-support-${scenario.id}` : undefined
              }
              onClick={() => onSelectScenario(scenario.id)}
            >
              {scenario.name}
              {disabled ? (
                <span id={`scenario-support-${scenario.id}`}>
                  （当前数据类型不支持）
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    </section>
  );
}
