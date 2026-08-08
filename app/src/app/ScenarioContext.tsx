/**
 * 当前场景上下文（PRD-01 §3.2 顶栏"当前场景选择器"）。
 *
 * 场景集合与 data/graph/annotation-capability-graph.json 的 SCN 节点一一对应
 * （'' = 通用掌握度口径，mastery 表 scenario_id=''，见蓝图 §5 004_learning）。
 * 选择持久化到 localStorage：学生跨页/跨会话保持同一场景上下文，Agent 运行、
 * RAG 问答、诊断上传默认携带它（各页面取 `scenarioId` 作为请求参数）。
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export interface ScenarioOption {
  id: string;
  name: string;
}

/** 场景选项（id 与图谱 SCN 节点一致；顺序即下拉展示顺序） */
export const SCENARIOS: ScenarioOption[] = [
  { id: "", name: "通用" },
  { id: "SCN-CUSTOMER-SERVICE-001", name: "智能客服标注" },
  { id: "SCN-IN-VEHICLE-001", name: "车载语音标注" },
  { id: "SCN-MEDICAL-001", name: "医疗数据标注" },
  { id: "SCN-CONTENT-SAFETY-001", name: "内容安全审核" },
];

const STORAGE_KEY = "bhzd.scenario_id";

export interface ScenarioContextValue {
  /** 当前场景 id（'' = 通用） */
  scenarioId: string;
  scenarioName: string;
  scenarios: ScenarioOption[];
  setScenarioId: (id: string) => void;
}

const ScenarioContext = createContext<ScenarioContextValue | null>(null);

function readInitial(): string {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    // 只接受合法场景 id：防止手写 localStorage 把脏值带进请求参数
    if (saved !== null && SCENARIOS.some((s) => s.id === saved)) return saved;
  } catch {
    /* localStorage 不可用（隐私模式等）时退回通用场景 */
  }
  return "";
}

export function ScenarioProvider({ children }: { children: ReactNode }) {
  const [scenarioId, setScenarioIdState] = useState<string>(readInitial);

  const setScenarioId = useCallback((id: string) => {
    setScenarioIdState(id);
    try {
      localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* 同上：持久化失败不影响本次选择 */
    }
  }, []);

  const value = useMemo<ScenarioContextValue>(() => {
    const current = SCENARIOS.find((s) => s.id === scenarioId);
    return {
      scenarioId,
      scenarioName: current?.name ?? "通用",
      scenarios: SCENARIOS,
      setScenarioId,
    };
  }, [scenarioId, setScenarioId]);

  return (
    <ScenarioContext.Provider value={value}>{children}</ScenarioContext.Provider>
  );
}

/** 访问当前场景；必须在 ScenarioProvider 内使用 */
export function useScenario(): ScenarioContextValue {
  const ctx = useContext(ScenarioContext);
  if (!ctx) throw new Error("useScenario 必须在 ScenarioProvider 内使用");
  return ctx;
}
