/**
 * 预设学习页（PRD-01 §4）。
 *
 * 交互闭环（验收：≤3 次点击开始任务）：
 *   路径卡（点击1）→ 抽屉「开始学习」（点击2）→ 确认门「确认创建」（点击3）
 *   → POST /api/confirmations/{id}/confirm → 任务落库 → 跳转任务列表。
 *
 * 两个刻意取舍（为什么）：
 * - 分组在前端做：API 返回平铺列表（无分组字段），按 PRD-01 §4.2 的
 *   新手/岗位胜任/证书备考/薄弱补强四区在前端归类；薄弱区依赖
 *   weak_count 个性化字段（presets.py 按薄弱数倒序返回）。
 * - 「学习目标」筛选在前端做：后端 goal 参数是对 goal 长句的子串匹配，
 *   PRD 的四个关键词（入门/专项/考证/岗位任务）并不出现在 goal 文本里，
 *   透传只会得到空列表，故按分组语义在前端过滤；数据类型/难度/具体场景
 *   仍走服务端查询参数（契约见蓝图 §6.3）。
 *
 * 埋点说明：preset_clicked 由后端在 POST /api/presets/{id}/start 内上报，
 * 前端不重复发（避免扭曲 preset_start_rate 的分母，见 shared.tsx trackEvent）。
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import type {
  Paginated,
  Preset,
  PresetStartResponse,
} from "../../api/types";
import {
  Button,
  Card,
  Drawer,
  EmptyState,
  ErrorState,
  MasteryBadge,
  Modal,
  PageHeader,
  Select,
  Spinner,
  Tag,
  useToast,
} from "../../components";
import { useScenario } from "../../app/ScenarioContext";
import {
  capNameOf,
  dataTypeLabel,
  errMsg,
  useCapNames,
} from "./shared";

/* ---------------------------------------------------------------- 分组与筛选 */

type PresetGroupKey = "newbie" | "job" | "cert" | "weak";

/** 分组展示顺序与 PRD-01 §4.2 一致 */
const GROUPS: { key: PresetGroupKey; title: string; sub: string }[] = [
  { key: "newbie", title: "新手路径", sub: "零基础与低难度入门" },
  { key: "job", title: "岗位胜任路径", sub: "面向具体岗位场景的能力组合" },
  { key: "cert", title: "证书备考路径", sub: "对标 1+X 等证书考点" },
  { key: "weak", title: "薄弱补强路径", sub: "根据你的掌握度个性化推荐" },
];

/**
 * 预设 → 分组。优先级：薄弱补强（个性化）> 证书 > 新手（低难度）> 岗位。
 * 每条路径只进入一个分组，避免同卡重复出现造成选择困惑。
 */
function groupOf(preset: Preset): PresetGroupKey {
  if (preset.weak_count > 0) return "weak";
  if (/证书|考证|1\+X/i.test(`${preset.title}${preset.goal}`)) return "cert";
  return preset.difficulty <= 2 ? "newbie" : "job";
}

const GOAL_OPTIONS = [
  { value: "", label: "全部目标" },
  { value: "newbie", label: "入门" },
  { value: "special", label: "专项" },
  { value: "cert", label: "考证" },
  { value: "job", label: "岗位任务" },
];

/** 学习目标筛选（前端语义映射，原因见文件头注释） */
function matchGoal(preset: Preset, goal: string): boolean {
  if (!goal) return true;
  if (goal === "special") {
    // 专项 = 面向特定数据类型的专项能力路径（考证除外）
    return groupOf(preset) !== "cert" && preset.data_type !== "general";
  }
  return groupOf(preset) === goal;
}

/** 场景筛选特殊值：通用（后端 scenario_id=null 的路径无法用语义参数表达，前端补判） */
const GENERAL_SCENARIO = "general";

const DIFFICULTY_OPTIONS = [
  { value: "", label: "全部难度" },
  ...[1, 2, 3, 4, 5].map((d) => ({ value: String(d), label: `难度 ${"★".repeat(d)}` })),
];

const DATA_TYPE_OPTIONS = [
  { value: "", label: "全部类型" },
  { value: "text", label: "文本" },
  { value: "image", label: "图像" },
  { value: "audio", label: "语音" },
  { value: "video", label: "视频" },
];

/* ---------------------------------------------------------------- 页面 */

interface StartState {
  confirmationId: string;
  preview: PresetStartResponse["preview"];
}

export default function PresetsPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const { scenarios } = useScenario();
  const capNames = useCapNames();

  const [filters, setFilters] = useState({ dataType: "", scenario: "", goal: "", difficulty: "" });
  const [items, setItems] = useState<Preset[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [drawerId, setDrawerId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Preset | null>(null);
  const [showMastered, setShowMastered] = useState(false);

  const [startState, setStartState] = useState<StartState | null>(null);
  const [starting, setStarting] = useState(false);
  const [confirming, setConfirming] = useState(false);

  // 列表拉取：数据类型/具体场景/难度走服务端参数（蓝图 §6.3 契约）
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api
      .get<Paginated<Preset>>("/api/presets", {
        data_type: filters.dataType || undefined,
        scenario_id:
          filters.scenario && filters.scenario !== GENERAL_SCENARIO
            ? filters.scenario
            : undefined,
        difficulty: filters.difficulty ? Number(filters.difficulty) : undefined,
      }, { signal: controller.signal })
      .then((res) => {
        if (!controller.signal.aborted) setItems(res.items);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errMsg(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [filters.dataType, filters.scenario, filters.difficulty]);

  /** 前端补滤：通用场景（scenario_id=null）+ 学习目标语义（见文件头注释） */
  const visible = useMemo(
    () =>
      (items ?? []).filter((preset) => {
        if (filters.scenario === GENERAL_SCENARIO && preset.scenario_id) return false;
        return matchGoal(preset, filters.goal);
      }),
    [items, filters.scenario, filters.goal],
  );

  const grouped = useMemo(
    () =>
      GROUPS.map((group) => ({
        ...group,
        items: visible.filter((preset) => groupOf(preset) === group.key),
      })).filter((group) => group.items.length > 0),
    [visible],
  );

  const scenarioNameOf = (scenarioId: string | null): string =>
    scenarios.find((s) => s.id === (scenarioId ?? ""))?.name ?? "通用";

  const resetFilters = () =>
    setFilters({ dataType: "", scenario: "", goal: "", difficulty: "" });

  /** 打开路径详情抽屉（点击1）；mastered 折叠态每次重置，保证"已掌握默认折叠" */
  const openPreset = async (presetId: string) => {
    setDrawerId(presetId);
    setDetail(null);
    setShowMastered(false);
    try {
      setDetail(await api.get<Preset>(`/api/presets/${presetId}`));
    } catch (err) {
      toast.error(errMsg(err));
      setDrawerId(null);
    }
  };

  /** 开始学习（点击2）：走确认门生成首个任务预览（后端此时不上库任务） */
  const startPreset = async () => {
    if (!detail) return;
    setStarting(true);
    try {
      const res = await api.post<PresetStartResponse>(`/api/presets/${detail.id}/start`);
      setStartState({ confirmationId: res.confirmation.id, preview: res.preview });
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setStarting(false);
    }
  };

  /** 取消确认门：通知后端作废确认单（PRD：取消不改变任何学习状态） */
  const cancelStart = async () => {
    if (!startState) return;
    try {
      await api.post(`/api/confirmations/${startState.confirmationId}/cancel`);
    } catch {
      /* 确认单可能已过期，本地照常关闭 */
    }
    setStartState(null);
    toast.info("已取消，未做任何更改");
  };

  /** 确认创建（点击3）：任务真正落库后跳任务列表 */
  const confirmStart = async () => {
    if (!startState) return;
    setConfirming(true);
    try {
      await api.post(`/api/confirmations/${startState.confirmationId}/confirm`);
      toast.success("学习任务已创建，去学习吧");
      setStartState(null);
      navigate("/tasks");
    } catch (err) {
      toast.error(errMsg(err));
      setConfirming(false);
    }
  };

  // 抽屉内能力分区：未掌握（薄弱优先）平铺，已掌握默认折叠（PRD-01 §4.4）
  const activeCaps = (detail?.caps ?? []).filter((c) => c.mastery_status !== "mastered");
  const masteredCaps = (detail?.caps ?? []).filter((c) => c.mastery_status === "mastered");
  const preview = startState?.preview ?? null;

  return (
    <div>
      <PageHeader
        title="预设学习"
        sub="围绕数据类型、行业场景与证书目标组织的学习路径，薄弱能力优先推荐"
      />

      {/* 顶部筛选（PRD-01 §4.2）：四维过滤 */}
      <Card className="mb-4">
        <div className="grid grid-cols-4">
          <Select
            aria-label="数据类型筛选"
            value={filters.dataType}
            options={DATA_TYPE_OPTIONS}
            onChange={(e) => setFilters((f) => ({ ...f, dataType: e.target.value }))}
          />
          <Select
            aria-label="行业场景筛选"
            value={filters.scenario}
            options={[
              { value: "", label: "全部场景" },
              { value: GENERAL_SCENARIO, label: "通用" },
              ...scenarios
                .filter((s) => s.id !== "")
                .map((s) => ({ value: s.id, label: s.name })),
            ]}
            onChange={(e) => setFilters((f) => ({ ...f, scenario: e.target.value }))}
          />
          <Select
            aria-label="学习目标筛选"
            value={filters.goal}
            options={GOAL_OPTIONS}
            onChange={(e) => setFilters((f) => ({ ...f, goal: e.target.value }))}
          />
          <Select
            aria-label="难度筛选"
            value={filters.difficulty}
            options={DIFFICULTY_OPTIONS}
            onChange={(e) => setFilters((f) => ({ ...f, difficulty: e.target.value }))}
          />
        </div>
      </Card>

      {error ? (
        <ErrorState message={error} onRetry={resetFilters} />
      ) : loading ? (
        <div className="loading-block">
          <Spinner large /> 正在加载学习路径…
        </div>
      ) : visible.length === 0 ? (
        // 空筛选结果（PRD-06 §7.2 空态必须有引导动作）
        <EmptyState
          title="没有符合条件的预设路径"
          hint="试试放宽筛选条件，或从全部路径中重新选择"
          action={
            <Button variant="secondary" onClick={resetFilters}>
              清除筛选
            </Button>
          }
        />
      ) : (
        grouped.map((group) => (
          <section key={group.key} className="mb-6">
            <h2 className="mb-2" style={{ fontSize: "var(--font-size-lg)" }}>
              {group.title}
            </h2>
            <p className="text-sm text-secondary mb-3">{group.sub}</p>
            <div className="grid grid-cols-3">
              {group.items.map((preset) => (
                <div
                  key={preset.id}
                  className="card card-padded"
                  role="button"
                  tabIndex={0}
                  style={{ cursor: "pointer" }}
                  onClick={() => openPreset(preset.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") openPreset(preset.id);
                  }}
                >
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <strong>{preset.title}</strong>
                    {preset.weak_count > 0 ? (
                      <span className="badge badge-weak">薄弱 {preset.weak_count} 项</span>
                    ) : null}
                  </div>
                  <p className="text-sm text-secondary mb-3">{preset.description}</p>
                  <div className="flex items-center gap-2 flex-wrap">
                    <Tag>{dataTypeLabel(preset.data_type)}</Tag>
                    <Tag>{scenarioNameOf(preset.scenario_id)}</Tag>
                    <span className="text-xs" aria-label={`难度 ${preset.difficulty}`}>
                      {"★".repeat(preset.difficulty)}
                      {"☆".repeat(Math.max(0, 5 - preset.difficulty))}
                    </span>
                    <span className="text-xs text-muted">约 {preset.est_minutes} 分钟</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))
      )}

      {/* 路径详情抽屉（点击卡片后；含开始学习入口） */}
      <Drawer
        open={drawerId !== null}
        title={detail?.title ?? "路径详情"}
        onClose={() => setDrawerId(null)}
      >
        {detail === null ? (
          <div className="loading-block">
            <Spinner /> 加载中…
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-secondary">{detail.description}</p>
            <div className="flex items-center gap-2 flex-wrap">
              <Tag>{dataTypeLabel(detail.data_type)}</Tag>
              <Tag>{scenarioNameOf(detail.scenario_id)}</Tag>
              <span className="text-xs">
                难度 {"★".repeat(detail.difficulty)}
              </span>
              <span className="text-xs text-muted">预计 {detail.est_minutes} 分钟</span>
            </div>
            <div>
              <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                学习目标
              </h3>
              <p className="text-sm">{detail.goal}</p>
              <p className="text-xs text-muted mt-2">适合：{detail.recommended_for}</p>
            </div>
            <div>
              <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                关联能力
              </h3>
              <div className="flex flex-col gap-2">
                {activeCaps.map((cap) => (
                  <span key={cap.cap_id} className="flex items-center justify-between gap-2">
                    <span className="text-sm">{cap.cap_name}</span>
                    <MasteryBadge score={cap.score} />
                  </span>
                ))}
              </div>
              {masteredCaps.length > 0 ? (
                <div className="mt-2">
                  <Button variant="ghost" size="sm" onClick={() => setShowMastered((v) => !v)}>
                    已掌握 {masteredCaps.length} 项（{showMastered ? "收起" : "展开"}）
                  </Button>
                  {showMastered ? (
                    <div className="flex flex-col gap-2 mt-2">
                      {masteredCaps.map((cap) => (
                        <span key={cap.cap_id} className="flex items-center justify-between gap-2">
                          <span className="text-sm text-secondary">{cap.cap_name}</span>
                          <MasteryBadge score={cap.score} />
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
            <div>
              <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                学习单元
              </h3>
              <ol className="flex flex-col gap-2">
                {detail.units.map((unit, index) => (
                  <li key={unit.unit_id} className="flex items-center gap-2">
                    <span className="badge badge-neutral">{index + 1}</span>
                    <span className="text-sm">{unit.title}</span>
                    {unit.data_type ? <Tag>{dataTypeLabel(unit.data_type)}</Tag> : null}
                  </li>
                ))}
              </ol>
            </div>
            <Button block loading={starting} onClick={startPreset}>
              开始学习
            </Button>
          </div>
        )}
      </Drawer>

      {/* 确认门：预览首个任务卡，确认后才真正创建（PRD-06 §6.4 写操作可控） */}
      <Modal
        open={startState !== null}
        title="确认创建学习任务"
        onClose={cancelStart}
        footer={
          <>
            <Button variant="ghost" onClick={cancelStart} disabled={confirming}>
              取消
            </Button>
            <Button loading={confirming} onClick={confirmStart}>
              确认创建
            </Button>
          </>
        }
      >
        {preview ? (
          <div className="flex flex-col gap-3">
            <div>
              <strong>{preview.title}</strong>
              <div className="flex items-center gap-2 flex-wrap mt-2">
                <Tag>{dataTypeLabel(preview.data_type)}</Tag>
                <Tag>{scenarioNameOf(preview.scenario_id ?? null)}</Tag>
              </div>
            </div>
            {preview.goal ? <p className="text-sm text-secondary">目标：{preview.goal}</p> : null}
            {preview.steps && preview.steps.length > 0 ? (
              <div>
                <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                  学习步骤
                </h3>
                <ol className="flex flex-col gap-2">
                  {preview.steps.map((step, index) => (
                    <li key={index} className="text-sm">
                      {index + 1}. {step.title}
                    </li>
                  ))}
                </ol>
              </div>
            ) : null}
            {preview.cap_ids && preview.cap_ids.length > 0 ? (
              <div className="flex items-center gap-2 flex-wrap">
                {preview.cap_ids.map((capId) => (
                  <Tag key={capId}>{capNameOf(capNames, capId)}</Tag>
                ))}
              </div>
            ) : null}
            <p className="text-xs text-muted">
              确认后将创建首个学习任务（30 分钟内确认有效），任务其余单元将在后续学习中逐步解锁。
            </p>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
