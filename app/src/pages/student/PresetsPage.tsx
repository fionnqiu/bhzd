/**
 * 预设学习页（PRD-01 §4）。
 *
 * 交互闭环（验收：≤3 次点击开始任务）：
 *   推荐卡（点击1）→ 抽屉「生成任务」（点击2）→ 确认门「确认创建」（点击3）
 *   → POST /api/confirmations/{id}/confirm → 任务落库 → 跳转任务列表。
 *
 * 两个刻意取舍（为什么）：
 * - 分组在前端做：API 返回平铺列表（无分组字段），按 PRD-01 §4.2 的
 *   入门/岗位/薄弱能力三区在前端归类；薄弱区依赖
 *   weak_count 个性化字段（presets.py 按薄弱数倒序返回）。
 * - 筛选只暴露数据类型；目标和难度仍服务于内部分组，避免把
 *   内部教学分组规则变成额外的用户决策负担。
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
import {
  dataTypeLabel,
  errMsg,
} from "./shared";

/* ---------------------------------------------------------------- 分组与筛选 */

type PresetGroupKey = "newbie" | "job" | "weak";

/** 分组展示顺序与 PRD-01 §4.2 一致 */
const GROUPS: { key: PresetGroupKey; title: string }[] = [
  { key: "newbie", title: "入门推荐" },
  { key: "job", title: "岗位推荐" },
  { key: "weak", title: "薄弱能力推荐" },
];

/**
 * 预设 → 分组。优先级：薄弱能力（个性化）> 入门（低难度）> 岗位。
 * 每条路径只进入一个分组，避免同卡重复出现造成选择困惑。
 */
function groupOf(preset: Preset): PresetGroupKey {
  if (preset.weak_count > 0) return "weak";
  return preset.difficulty <= 2 ? "newbie" : "job";
}

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

  const [filters, setFilters] = useState({ dataType: "" });
  const [items, setItems] = useState<Preset[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [drawerId, setDrawerId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Preset | null>(null);
  const [showMastered, setShowMastered] = useState(false);

  const [startState, setStartState] = useState<StartState | null>(null);
  const [starting, setStarting] = useState(false);
  const [confirming, setConfirming] = useState(false);

  // 只把数据类型作为显式筛选，目标/难度继续服务于内部分组和详情。
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api
      .get<Paginated<Preset>>("/api/presets", {
        data_type: filters.dataType || undefined,
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
  }, [filters.dataType]);

  const visible = useMemo(() => items ?? [], [items]);

  const grouped = useMemo(
    () =>
      GROUPS.map((group) => ({
        ...group,
        items: visible.filter((preset) => groupOf(preset) === group.key),
      })).filter((group) => group.items.length > 0),
    [visible],
  );

  const resetFilters = () =>
    setFilters({ dataType: "" });

  /** 打开推荐详情抽屉；mastered 折叠态每次重置。 */
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
        title="学习推荐"
      />

      {/* 顶部筛选（PRD-01 §4.2）：只保留数据类型 */}
      <Card className="mb-4">
        <div className="grid grid-cols-1">
          <Select
            aria-label="数据类型筛选"
            value={filters.dataType}
            options={DATA_TYPE_OPTIONS}
            onChange={(e) => setFilters((f) => ({ ...f, dataType: e.target.value }))}
          />
        </div>
      </Card>

      {error ? (
        <ErrorState message={error} onRetry={resetFilters} />
      ) : loading ? (
        <div className="loading-block">
          <Spinner large /> 正在加载学习推荐…
        </div>
      ) : visible.length === 0 ? (
        // 空筛选结果（PRD-06 §7.2 空态必须有引导动作）
        <EmptyState
          title="没有符合条件的学习推荐"
          hint="试试放宽筛选条件，或从全部推荐中重新选择"
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
                    {/* Difficulty stays in groupOf above, but is deliberately not a list-card cue. */}
                    <span className="text-xs text-muted">约 {preset.est_minutes} 分钟</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))
      )}

      {/* 推荐详情抽屉：每次确认只创建一个任务，不承诺后续路径。 */}
      <Drawer
        open={drawerId !== null}
        title={detail?.title ?? "推荐详情"}
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
              {/* Difficulty remains an internal grouping signal, not a learner-facing detail. */}
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
              生成任务
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
            </div>
            {preview.description || preview.goal ? (
              <p className="text-sm text-secondary">{preview.description ?? preview.goal}</p>
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
