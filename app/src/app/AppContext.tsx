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
  "snapshot" | "getLoadError" | "setContext" | "reset"
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

const PROFILE_RECOVERY_GUIDANCE =
  "本地学习档案无法读取。当前选择只保留在内存中，不会覆盖原档案。请打开“重置学习档案”并确认重置后恢复保存。";

const PROFILE_RECOVERY_RESET_FAILURE =
  "本地学习档案无法读取，且重置失败。当前选择仍只保留在内存中；请检查浏览器存储权限后再次确认重置。";

interface InitialAppProfileState {
  readonly selectedWorkMode: WorkMode;
  readonly selectedScenarioId: string | null;
  readonly recoveryRequired: boolean;
  readonly profileError: string | null;
}

const recoveryProfileState = (): InitialAppProfileState => ({
  selectedWorkMode: "course",
  selectedScenarioId: null,
  recoveryRequired: true,
  profileError: PROFILE_RECOVERY_GUIDANCE,
});

const loadInitialProfileState = (
  profileStore: AppProfileStore,
): InitialAppProfileState => {
  try {
    if (profileStore.getLoadError() !== null) {
      return recoveryProfileState();
    }

    const snapshot = profileStore.snapshot();
    return {
      selectedWorkMode: isWorkMode(snapshot.lastMode)
        ? snapshot.lastMode
        : "course",
      selectedScenarioId: snapshot.lastScenario,
      recoveryRequired: false,
      profileError: null,
    };
  } catch {
    return recoveryProfileState();
  }
};

export function AppProvider({ children, profileStore }: AppProviderProps) {
  const [initialProfile] = useState(() =>
    loadInitialProfileState(profileStore),
  );
  const [selectedDomain, setSelectedDomain] = useState<Domain>("text");
  const [selectedWorkMode, setSelectedWorkMode] = useState<WorkMode>(
    initialProfile.selectedWorkMode,
  );
  const [selectedScenarioId, setSelectedScenarioId] = useState<string | null>(
    initialProfile.selectedScenarioId,
  );
  const [recoveryRequired, setRecoveryRequired] = useState(
    initialProfile.recoveryRequired,
  );
  const [profileError, setProfileError] = useState<string | null>(
    initialProfile.profileError,
  );

  const selectDomain = useCallback((domain: Domain) => {
    setSelectedDomain(domain);
  }, []);

  const selectWorkMode = useCallback(
    (mode: WorkMode) => {
      setSelectedWorkMode(mode);
      if (recoveryRequired) {
        return;
      }

      try {
        profileStore.setContext({ lastMode: mode });
        setProfileError(null);
      } catch {
        setProfileError("学习状态保存失败，本次选择仍可继续使用。");
      }
    },
    [profileStore, recoveryRequired],
  );

  const selectScenario = useCallback(
    (scenarioId: string | null) => {
      setSelectedScenarioId(scenarioId);
      if (recoveryRequired) {
        return;
      }

      try {
        profileStore.setContext({ lastScenario: scenarioId });
        setProfileError(null);
      } catch {
        setProfileError("场景状态保存失败，本次选择仍可继续使用。");
      }
    },
    [profileStore, recoveryRequired],
  );

  const resetLearningProfile = useCallback((): boolean => {
    try {
      profileStore.reset();
    } catch {
      setProfileError(
        recoveryRequired
          ? PROFILE_RECOVERY_RESET_FAILURE
          : "学习档案重置失败，请检查浏览器存储权限后重试。",
      );
      return false;
    }

    setSelectedDomain("text");
    setSelectedWorkMode("course");
    setSelectedScenarioId(null);
    setRecoveryRequired(false);
    setProfileError(null);
    return true;
  }, [profileStore, recoveryRequired]);

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
