import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

import type { ProfileStore } from "../state/profileStore";

export const DOMAIN_LABELS = {
  text: "文本",
  image: "图像",
  audio: "语音",
  video: "视频",
} as const;

export type Domain = keyof typeof DOMAIN_LABELS;

export const WORK_MODE_LABELS = {
  course: "课程",
  graph: "图谱",
  task: "任务转化",
  diagnostics: "标注诊断",
} as const;

export type WorkMode = keyof typeof WORK_MODE_LABELS;

export type AppProfileStore = Pick<
  ProfileStore,
  "snapshot" | "setContext" | "reset"
>;

interface AppContextValue {
  selectedDomain: Domain;
  selectedWorkMode: WorkMode;
  selectedScenarioId: string | null;
  profileError: string | null;
  selectDomain(domain: Domain): void;
  selectWorkMode(mode: WorkMode): void;
  selectScenario(scenarioId: string | null): void;
  resetLearningProfile(): boolean;
}

interface AppProviderProps {
  children: ReactNode;
  profileStore: AppProfileStore;
}

const AppContext = createContext<AppContextValue | null>(null);

const isWorkMode = (value: string | null): value is WorkMode =>
  value !== null && Object.hasOwn(WORK_MODE_LABELS, value);

export function AppProvider({ children, profileStore }: AppProviderProps) {
  const [initialProfile] = useState(() => profileStore.snapshot());
  const [selectedDomain, setSelectedDomain] = useState<Domain>("text");
  const [selectedWorkMode, setSelectedWorkMode] = useState<WorkMode>(() =>
    isWorkMode(initialProfile.lastMode) ? initialProfile.lastMode : "course",
  );
  const [selectedScenarioId, setSelectedScenarioId] = useState<string | null>(
    initialProfile.lastScenario,
  );
  const [profileError, setProfileError] = useState<string | null>(null);

  const selectDomain = useCallback((domain: Domain) => {
    setSelectedDomain(domain);
  }, []);

  const selectWorkMode = useCallback(
    (mode: WorkMode) => {
      setSelectedWorkMode(mode);
      try {
        profileStore.setContext({ lastMode: mode });
        setProfileError(null);
      } catch {
        setProfileError("学习状态保存失败，本次选择仍可继续使用。");
      }
    },
    [profileStore],
  );

  const selectScenario = useCallback(
    (scenarioId: string | null) => {
      setSelectedScenarioId(scenarioId);
      try {
        profileStore.setContext({ lastScenario: scenarioId });
        setProfileError(null);
      } catch {
        setProfileError("场景状态保存失败，本次选择仍可继续使用。");
      }
    },
    [profileStore],
  );

  const resetLearningProfile = useCallback((): boolean => {
    try {
      profileStore.reset();
    } catch {
      setProfileError("学习档案重置失败，请检查浏览器存储权限后重试。");
      return false;
    }

    setSelectedDomain("text");
    setSelectedWorkMode("course");
    setSelectedScenarioId(null);
    setProfileError(null);
    return true;
  }, [profileStore]);

  return (
    <AppContext.Provider
      value={{
        selectedDomain,
        selectedWorkMode,
        selectedScenarioId,
        profileError,
        selectDomain,
        selectWorkMode,
        selectScenario,
        resetLearningProfile,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useAppContext(): AppContextValue {
  const value = useContext(AppContext);

  if (value === null) {
    throw new Error("useAppContext must be used inside AppProvider.");
  }

  return value;
}
