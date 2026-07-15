import {
  lazy,
  Suspense,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import { Button } from "../components/Button";
import { Panel } from "../components/Panel";
import {
  createRepository,
} from "../data/repository";
import {
  graph,
  scenarios,
  sourceRegistry,
  teachingUnits,
} from "../data/rawData";
import {
  countConsumableUnitsByDomain,
  Dashboard,
  type ConsumableUnitSource,
} from "../features/dashboard/Dashboard";
import {
  CourseBrowser,
  isConsumableTeachingUnit,
} from "../features/course/CourseBrowser";
import {
  DiagnosticView,
  type DiagnosticMasteryInput,
} from "../features/diagnostics/DiagnosticView";
import { LessonView } from "../features/course/LessonView";
import type { GraphLessonRepository } from "../features/graph/lessonLinks";
import { TaskConverterView } from "../features/tasks/TaskConverterView";
import { createGraphEngine } from "../graph/graphEngine";
import {
  createProfileStore,
  type LearningProfileSnapshot,
  type ProfileStorage,
  type RecordDiagnosticInput,
  type RecordExerciseInput,
} from "../state/profileStore";
import {
  AppProvider,
  DOMAIN_LABELS,
  WORK_MODE_LABELS,
  useAppContext,
  type AppProfileStore,
  type Domain,
  type WorkMode,
} from "./AppContext";

const canonicalRepository = createRepository({
  graph,
  scenarios,
  sourceRegistry,
  teachingUnits,
});
const canonicalGraphEngine = createGraphEngine(graph);
const GraphWorkspace = lazy(
  () => import("../features/graph/GraphWorkspace"),
);

const browserStorage: ProfileStorage = {
  getItem: (key) => window.localStorage.getItem(key),
  setItem: (key, value) => window.localStorage.setItem(key, value),
  removeItem: (key) => window.localStorage.removeItem(key),
};

const MODE_DETAILS: ReadonlyArray<{
  id: WorkMode;
  coordinate: string;
  title: string;
  description: string;
  pending: string;
}> = [
  {
    id: "course",
    coordinate: "BRG 018°",
    title: "课程航线",
    description: "按数据域进入已发布的教学单元，建立规则、练习与反馈的连续闭环。",
    pending: "课程内容将在下一阶段接入。当前可先确认数据域与学习航向。",
  },
  {
    id: "graph",
    coordinate: "BRG 092°",
    title: "图谱航线",
    description: "从能力、知识与任务关系观察图谱关联，定位可继续探索的节点。",
    pending: "知识图谱入口已就位，节点网络与关系详情将在后续接入。",
  },
  {
    id: "task",
    coordinate: "BRG 184°",
    title: "任务转化航线",
    description: "把企业标注需求整理为可核验的学习任务与能力证据。",
    pending: "任务转化入口已就位，输入与任务卡工作区将在后续接入。",
  },
  {
    id: "diagnostics",
    coordinate: "BRG 276°",
    title: "标注诊断航线",
    description: "在本地检查结构化标注导出，返回可恢复的问题定位线索。",
    pending: "诊断入口已就位，文件检查与结果面板将在后续接入。",
  },
];

const MODE_INDEX = new Map(
  MODE_DETAILS.map(({ id }, index) => [id, index] as const),
);

export const masteryForScenario = (
  profileSnapshot: LearningProfileSnapshot,
  scenarioId: string | null,
  capabilityId: string,
): number | null => {
  const mastery =
    scenarioId === null
      ? profileSnapshot.generalMastery[capabilityId]
      : profileSnapshot.scenarioMastery[`${capabilityId}::${scenarioId}`];

  return mastery ?? null;
};

export const applyDiagnosticMastery = (
  input: DiagnosticMasteryInput,
  scenarioId: string | null,
  recordExercises: (inputs: readonly RecordExerciseInput[]) => boolean,
  recordDiagnostics: (inputs: readonly RecordDiagnosticInput[]) => boolean,
): boolean => {
  if (input.kind === "exercise") {
    return recordExercises(
      input.capabilityIds.map((capabilityId) => ({
        capabilityId,
        score: input.score,
        scenarioId,
        evaluationVersion: "diagnostic-v1",
      })),
    );
  }

  return recordDiagnostics(
    input.entries.map(({ capabilityId, severity }) => ({
      capabilityId,
      severity,
      scenarioId,
      evaluationVersion: "diagnostic-v1",
    })),
  );
};

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

const listFocusableElements = (container: HTMLElement): HTMLElement[] =>
  Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) =>
      element.tabIndex >= 0 &&
      !element.hidden &&
      element.getAttribute("aria-hidden") !== "true",
  );

export interface AppProps {
  repository?: ConsumableUnitSource;
  profileStore?: AppProfileStore;
}

interface ApplicationShellProps {
  repository: ConsumableUnitSource;
}

function ApplicationShell({ repository }: ApplicationShellProps) {
  const {
    selectedDomain,
    selectedWorkMode,
    selectedScenarioId,
    selectedUnitId,
    profileSnapshot,
    profileError,
    selectDomain,
    selectNode,
    selectScenario,
    selectWorkMode,
    selectUnit,
    recordDiagnostics,
    recordExercises,
    resetLearningProfile,
  } = useAppContext();
  const [resetOpen, setResetOpen] = useState(false);
  const [resetNotice, setResetNotice] = useState<string | null>(null);
  const [unknownPersistedNodeId] = useState<string | null>(() => {
    const candidate = profileSnapshot.lastNode;
    return candidate !== null && !graph.nodes.some((node) => node.id === candidate)
      ? candidate
      : null;
  });
  const [graphTargetNodeId, setGraphTargetNodeId] = useState<string | null>(() => {
    const candidate = profileSnapshot.lastNode;
    return candidate !== null && graph.nodes.some((node) => node.id === candidate)
      ? candidate
      : null;
  });
  const resetButtonRef = useRef<HTMLButtonElement>(null);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const resetDialogRef = useRef<HTMLDivElement>(null);
  const resetWasOpenRef = useRef(false);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const openedCourseTriggerIdRef = useRef<string | null>(null);
  const pendingCourseFocusRestoreRef = useRef<string | null>(null);
  const unknownNodeCleanupRef = useRef(false);
  const listedUnits = useMemo(
    () => repository.listConsumableUnits(),
    [repository],
  );
  const counts = useMemo(
    () => countConsumableUnitsByDomain(listedUnits),
    [listedUnits],
  );
  const selectableUnits = useMemo(
    () => listedUnits.filter(isConsumableTeachingUnit),
    [listedUnits],
  );
  const graphRepository = useMemo<GraphLessonRepository>(
    () => ({
      // The application-supplied consumable index remains authoritative even
      // when canonical graph lookup helpers discover link candidates.
      listConsumableUnits: () => selectableUnits,
      getNode: (nodeId) => canonicalRepository.getNode(nodeId),
      getIncomingEdges: (nodeId) =>
        canonicalRepository.getIncomingEdges(nodeId),
      getOutgoingEdges: (nodeId) =>
        canonicalRepository.getOutgoingEdges(nodeId),
      getConsumableUnitsForNode: (nodeId) =>
        canonicalRepository.getConsumableUnitsForNode(nodeId),
    }),
    [selectableUnits],
  );
  const selectedUnit =
    selectedUnitId === null
      ? null
      : selectableUnits.find(
          (unit) =>
            unit.id === selectedUnitId && unit.data_type === selectedDomain,
        ) ?? null;
  const diagnosticTargetUnitId =
    selectedUnit?.id ??
    selectableUnits.find((unit) => unit.data_type === selectedDomain)?.id ??
    null;

  const domainLabel = DOMAIN_LABELS[selectedDomain];
  const scenarioLabel = selectedScenarioId ?? "通用场景";
  const activeMode =
    MODE_DETAILS[MODE_INDEX.get(selectedWorkMode) ?? 0] ?? MODE_DETAILS[0];

  const openGraphLesson = (unit: (typeof selectableUnits)[number]) => {
    if (!Object.hasOwn(DOMAIN_LABELS, unit.data_type)) {
      return;
    }
    openedCourseTriggerIdRef.current = unit.id;
    pendingCourseFocusRestoreRef.current = null;
    selectWorkMode("course");
    selectDomain(unit.data_type as Domain);
    selectUnit(unit.id);
  };

  const handleGraphNodeSelection = (nodeId: string | null) => {
    setGraphTargetNodeId(nodeId);
    selectNode(nodeId);
  };

  useEffect(() => {
    if (unknownPersistedNodeId === null || unknownNodeCleanupRef.current) {
      return;
    }

    unknownNodeCleanupRef.current = true;
    selectNode(null);
  }, [selectNode, unknownPersistedNodeId]);

  useEffect(() => {
    if (resetOpen) {
      resetWasOpenRef.current = true;
      cancelButtonRef.current?.focus();
      const previousDocumentOverflow =
        document.documentElement.style.overflow;
      const previousBodyOverflow = document.body.style.overflow;
      document.documentElement.style.overflow = "hidden";
      document.body.style.overflow = "hidden";

      const containFocus = (event: FocusEvent) => {
        const dialog = resetDialogRef.current;
        const target = event.target;
        if (
          dialog !== null &&
          target instanceof Node &&
          !dialog.contains(target)
        ) {
          (listFocusableElements(dialog)[0] ?? dialog).focus();
        }
      };

      document.addEventListener("focusin", containFocus);
      return () => {
        document.removeEventListener("focusin", containFocus);
        document.documentElement.style.overflow = previousDocumentOverflow;
        document.body.style.overflow = previousBodyOverflow;
      };
    }

    if (!resetWasOpenRef.current) {
      return;
    }

    resetWasOpenRef.current = false;
    resetButtonRef.current?.focus();
  }, [resetOpen]);

  const closeResetDialog = () => {
    setResetOpen(false);
  };

  const confirmReset = () => {
    const reset = resetLearningProfile();
    setGraphTargetNodeId(null);
    setResetOpen(false);
    setResetNotice(reset ? "学习档案已重置，航线已返回文本课程。" : null);
  };

  const handleResetDialogKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeResetDialog();
      return;
    }

    if (event.key !== "Tab") {
      return;
    }

    const dialog = resetDialogRef.current;
    if (dialog === null) {
      return;
    }

    const focusableElements = listFocusableElements(dialog);
    const firstFocusable = focusableElements[0];
    const lastFocusable = focusableElements.at(-1);
    const activeElement = document.activeElement;

    if (firstFocusable === undefined || lastFocusable === undefined) {
      event.preventDefault();
      dialog.focus();
      return;
    }

    if (
      event.shiftKey &&
      (activeElement === firstFocusable || !dialog.contains(activeElement))
    ) {
      event.preventDefault();
      lastFocusable.focus();
      return;
    }

    if (
      !event.shiftKey &&
      (activeElement === lastFocusable || !dialog.contains(activeElement))
    ) {
      event.preventDefault();
      firstFocusable.focus();
    }
  };

  const activateMode = (index: number) => {
    const mode = MODE_DETAILS[index];
    if (mode === undefined) {
      return;
    }

    selectWorkMode(mode.id);
    tabRefs.current[index]?.focus();
  };

  const handleModeKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) => {
    let nextIndex: number | null = null;

    switch (event.key) {
      case "ArrowRight":
        nextIndex = (index + 1) % MODE_DETAILS.length;
        break;
      case "ArrowLeft":
        nextIndex = (index - 1 + MODE_DETAILS.length) % MODE_DETAILS.length;
        break;
      case "Home":
        nextIndex = 0;
        break;
      case "End":
        nextIndex = MODE_DETAILS.length - 1;
        break;
      default:
        return;
    }

    event.preventDefault();
    activateMode(nextIndex);
  };

  return (
    <div className="app-shell">
      <div
        className="app-content"
        inert={resetOpen ? true : undefined}
        aria-hidden={resetOpen ? true : undefined}
      >
        <a className="skip-link" href="#main-content">
          跳到主要内容
        </a>

        <header className="app-header">
          <div className="brand-lockup" aria-label="标航智导">
            <span className="brand-lockup__mark" aria-hidden="true">
              <span />
            </span>
            <span className="brand-lockup__copy">
              <span>ANNOTATION NAVIGATOR</span>
              <strong>标航智导</strong>
            </span>
            <span className="preview-badge">开发预览</span>
          </div>

          <nav className="mode-navigation" aria-label="工作模式">
            <div role="tablist" aria-label="主工作模式" className="mode-tabs">
              {MODE_DETAILS.map((mode, index) => {
                const selected = selectedWorkMode === mode.id;

                return (
                  <button
                    key={mode.id}
                    ref={(element) => {
                      tabRefs.current[index] = element;
                    }}
                    id={`mode-${mode.id}-tab`}
                    className="mode-tab"
                    type="button"
                    role="tab"
                    aria-selected={selected}
                    aria-controls="mode-panel"
                    tabIndex={selected ? 0 : -1}
                    onClick={() => activateMode(index)}
                    onKeyDown={(event) => handleModeKeyDown(event, index)}
                  >
                    {WORK_MODE_LABELS[mode.id]}
                  </button>
                );
              })}
            </div>
          </nav>

          <dl className="header-position" aria-label="当前位置">
            <div>
              <dt>数据域</dt>
              <dd>{domainLabel}</dd>
            </div>
            <div>
              <dt>场景</dt>
              <dd>{scenarioLabel}</dd>
            </div>
          </dl>
        </header>

        <div className="workspace">
          <aside className="workspace__domains" aria-label="课程域导航">
            <Dashboard
              counts={counts}
              selectedDomain={selectedDomain}
              onSelectDomain={selectDomain}
            />
          </aside>

          <main id="main-content" className="workspace__main" tabIndex={-1}>
            <Panel
              id="mode-panel"
              role="tabpanel"
              aria-labelledby={`mode-${selectedWorkMode}-tab`}
              tone="paper"
              className="chart-room"
            >
              {selectedWorkMode === "course" ? (
                selectedUnit === null ? (
                  <CourseBrowser
                    repository={repository}
                    domain={selectedDomain}
                    focusUnitId={pendingCourseFocusRestoreRef.current}
                    onFocusRestored={() => {
                      pendingCourseFocusRestoreRef.current = null;
                    }}
                    onOpenUnit={(unit) => {
                      if (
                        selectableUnits.some(
                          (candidate) =>
                            candidate.id === unit.id &&
                            candidate.data_type === selectedDomain,
                        )
                      ) {
                        openedCourseTriggerIdRef.current = unit.id;
                        pendingCourseFocusRestoreRef.current = null;
                        selectUnit(unit.id);
                      }
                    }}
                  />
                ) : (
                  <LessonView
                    key={selectedUnit.id}
                    unit={selectedUnit}
                    focusOnMount={
                      openedCourseTriggerIdRef.current === selectedUnit.id
                    }
                    onBack={() => {
                      pendingCourseFocusRestoreRef.current =
                        openedCourseTriggerIdRef.current;
                      selectUnit(null);
                    }}
                  />
                )
              ) : selectedWorkMode === "graph" ? (
                <div className="graph-workspace">
                  <div className="chart-room__coordinate" aria-hidden="true">
                    LAT 31.2304 N&nbsp;&nbsp; / &nbsp;&nbsp;LON 121.4737 E
                  </div>
                  <div className="chart-room__heading">
                    <div>
                      <p className="eyebrow eyebrow--ink">
                        {activeMode.coordinate} / {domainLabel}域
                      </p>
                      <h1>
                        {domainLabel}
                        <span>{activeMode.title}</span>
                      </h1>
                    </div>
                    <span className="route-state">
                      <span aria-hidden="true" /> 航向已锁定
                    </span>
                  </div>
                  <p className="chart-room__lede">{activeMode.description}</p>
                  <Suspense
                    fallback={
                      <p
                        className="graph-workspace__loading"
                        role="status"
                        aria-live="polite"
                        aria-label="正在加载图谱工作区…"
                      >
                        正在加载图谱工作区…
                      </p>
                    }
                  >
                    <GraphWorkspace
                      repository={graphRepository}
                      profileSnapshot={profileSnapshot}
                      scenarioId={selectedScenarioId}
                      initialNodeId={graphTargetNodeId}
                      graphEngine={canonicalGraphEngine}
                      graphDocument={graph}
                      onSelectNode={handleGraphNodeSelection}
                      onOpenUnit={openGraphLesson}
                    />
                  </Suspense>
                </div>
              ) : (
                <div className="feature-workspace">
                  <div className="chart-room__coordinate" aria-hidden="true">
                    LAT 31.2304 N&nbsp;&nbsp; / &nbsp;&nbsp;LON 121.4737 E
                  </div>

                  <div className="chart-room__heading">
                    <div>
                      <p className="eyebrow eyebrow--ink">
                        {activeMode.coordinate} / {domainLabel}域
                      </p>
                      <h1>
                        {domainLabel}
                        <span>{activeMode.title}</span>
                      </h1>
                    </div>
                    <span className="route-state">
                      <span aria-hidden="true" /> 航向已锁定
                    </span>
                  </div>

                  <p className="chart-room__lede">{activeMode.description}</p>

                  {selectedWorkMode === "task" ? (
                    <TaskConverterView
                      repository={canonicalRepository}
                      graphEngine={canonicalGraphEngine}
                      currentScenarioId={selectedScenarioId}
                      dataType={selectedDomain}
                      onSelectScenario={selectScenario}
                      onApplyScenario={selectScenario}
                    />
                  ) : (
                    <DiagnosticView
                      dataType={selectedDomain}
                      targetUnitId={diagnosticTargetUnitId}
                      repository={canonicalRepository}
                      graphEngine={canonicalGraphEngine}
                      masteryForNode={(capabilityId) =>
                        masteryForScenario(
                          profileSnapshot,
                          selectedScenarioId,
                          capabilityId,
                        )
                      }
                      onApplyMastery={(input) => {
                        applyDiagnosticMastery(
                          input,
                          selectedScenarioId,
                          recordExercises,
                          recordDiagnostics,
                        );
                      }}
                    />
                  )}
                </div>
              )}
            </Panel>
          </main>

          <aside className="workspace__status" aria-label="航线状态">
            <Panel tone="dark" className="status-panel">
              <div className="panel-heading">
                <p className="eyebrow">NAVIGATION FIX</p>
                <h2>当前航线</h2>
              </div>

              <dl className="position-list">
                <div>
                  <dt>数据域</dt>
                  <dd>{domainLabel}</dd>
                </div>
                <div>
                  <dt>工作模式</dt>
                  <dd>{WORK_MODE_LABELS[selectedWorkMode]}</dd>
                </div>
                <div>
                  <dt>场景</dt>
                  <dd>{scenarioLabel}</dd>
                </div>
                <div>
                  <dt>内容信号</dt>
                  <dd className="signal-value">
                    <span aria-hidden="true" /> {counts[selectedDomain]} 个单元
                  </dd>
                </div>
              </dl>

              <div className="legend" aria-label="状态图例">
                <p>航图图例</p>
                <span>
                  <i className="legend__mastery" aria-hidden="true" /> 可用内容
                </span>
                <span>
                  <i className="legend__bearing" aria-hidden="true" /> 当前航向
                </span>
                <span>
                  <i className="legend__error" aria-hidden="true" /> 需处理错误
                </span>
              </div>

              {profileError !== null ? (
                <p className="profile-message profile-message--error" role="alert">
                  {profileError}
                </p>
              ) : null}
              {resetNotice !== null ? (
                <p className="profile-message" role="status">
                  {resetNotice}
                </p>
              ) : null}

              <Button
                ref={resetButtonRef}
                variant="quiet"
                fullWidth
                onClick={() => {
                  setResetNotice(null);
                  setResetOpen(true);
                }}
              >
                重置学习档案
              </Button>
              <p className="reset-note">仅清除本应用保存在此浏览器中的学习档案。</p>
            </Panel>
          </aside>
        </div>
      </div>

      {resetOpen ? (
        <div className="dialog-backdrop">
          <div
            ref={resetDialogRef}
            className="reset-dialog"
            role="alertdialog"
            tabIndex={-1}
            aria-modal="true"
            aria-labelledby="reset-dialog-title"
            aria-describedby="reset-dialog-description"
            onKeyDown={handleResetDialogKeyDown}
          >
            <p className="eyebrow eyebrow--ink">PROFILE RESET</p>
            <h2 id="reset-dialog-title">确认重置学习档案</h2>
            <p id="reset-dialog-description">
              掌握度、练习记录和最近航向将从本浏览器清除。其他站点数据不会受到影响。
            </p>
            <div className="reset-dialog__actions">
              <Button ref={cancelButtonRef} variant="quiet" onClick={closeResetDialog}>
                取消
              </Button>
              <Button variant="danger" onClick={confirmReset}>
                确认重置
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function App({
  repository = canonicalRepository,
  profileStore,
}: AppProps) {
  const [resolvedProfileStore] = useState<AppProfileStore>(() =>
    profileStore ?? createProfileStore(browserStorage),
  );
  const resolveUnitDomain = useMemo(() => {
    const domainByUnitId = new Map<string, Domain>();
    for (const unit of repository
      .listConsumableUnits()
      .filter(isConsumableTeachingUnit)) {
      if (Object.hasOwn(DOMAIN_LABELS, unit.data_type)) {
        domainByUnitId.set(unit.id, unit.data_type as Domain);
      }
    }

    return (unitId: string): Domain | null =>
      domainByUnitId.get(unitId) ?? null;
  }, [repository]);
  const isScenarioSupported = useMemo(
    () => (scenarioId: string, domain: Domain): boolean =>
      canonicalRepository
        .getScenario(scenarioId)
        ?.supported_data_types.includes(domain) ?? false,
    [],
  );

  return (
    <AppProvider
      profileStore={resolvedProfileStore}
      resolveUnitDomain={resolveUnitDomain}
      isScenarioSupported={isScenarioSupported}
    >
      <ApplicationShell repository={repository} />
    </AppProvider>
  );
}
