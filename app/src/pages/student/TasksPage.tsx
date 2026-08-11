/**
 * 学习任务列表页（PRD-01 §6.1）。
 *
 * 关键决策（为什么）：
 * - 状态/来源筛选走服务端参数（tasks.py list_tasks 契约）；关键词搜索在
 *   前端做——列表接口没有 q 参数，且任务量按学生维度有限，本地过滤更即时。
 * - 归档是软删除（PRD-06 §8.2/§12.2：不回滚已确认掌握度），因此教师发布
 *   任务也允许归档但展示「教师」徽标；列表默认不含已归档（后端口径），
 *   显式切到「已归档」筛选可见。
 * - 空态按 PRD-06 §7.2 给三条学习入口（预设/指挥舱/诊断），不展示空白页。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import type { Paginated, TaskStatus, TaskSummary } from "../../api/types";
import {
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  PageHeader,
  ProgressBar,
  SearchInput,
  Select,
  Spinner,
  StatusBadge,
  Tag,
  useToast,
} from "../../components";
import { useScenario } from "../../app/ScenarioContext";
import {
  capNameOf,
  dataTypeLabel,
  errMsg,
  taskSourceLabel,
  useCapNames,
} from "./shared";

/** 状态筛选 chips（PRD-01 §6.1 全部/未开始/进行中/待提交/已完成 + 后端扩展态） */
const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: "", label: "全部" },
  { value: "not_started", label: "未开始" },
  { value: "in_progress", label: "进行中" },
  // submitted = 已提交待确认掌握度，学生视角即"待提交反馈确认"，按 PRD 文案命名
  { value: "submitted", label: "待提交" },
  { value: "completed", label: "已完成" },
  { value: "paused", label: "已暂停" },
  { value: "archived", label: "已归档" },
];

const SOURCE_OPTIONS = [
  { value: "", label: "全部来源" },
  { value: "agent", label: "Agent 创建" },
  { value: "preset", label: "预设学习" },
  { value: "teacher", label: "教师发布" },
  { value: "diagnostic", label: "诊断补强" },
];

/** 状态 → 下一步操作文案（点击进详情页执行对应动作） */
const NEXT_ACTION: Record<TaskStatus, string> = {
  draft: "继续编辑",
  not_started: "开始任务",
  in_progress: "继续学习",
  submitted: "查看反馈",
  completed: "查看反馈",
  paused: "继续学习",
  archived: "查看",
};

/** POST /api/tasks/batch 的逐项结果（tasks.py batch_tasks；页内声明防并行改 types） */
interface BatchResult {
  id: string;
  ok: boolean;
  message: string;
}

interface BatchResponse {
  action: string;
  results: BatchResult[];
  succeeded: number;
  failed: number;
}

export default function TasksPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const { scenarios } = useScenario();
  const capNames = useCapNames();

  const [status, setStatus] = useState("");
  const [source, setSource] = useState("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState<TaskSummary[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<TaskSummary | null>(null);
  // 批量选择（PRD-01 §6.1 批量操作）：Set 存任务 id；已归档任务不可选（批量仅支持归档）
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchConfirmOpen, setBatchConfirmOpen] = useState(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<Paginated<TaskSummary>>("/api/tasks", {
        status: status || undefined,
        source: source || undefined,
      }, { signal });
      if (signal?.aborted) return;
      setItems(res.items);
      // 刷新后清单可能变化：直接清空选择，避免对已不可见的任务执行批量
      setSelected(new Set());
    } catch (err) {
      if (!signal?.aborted) setError(errMsg(err));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [status, source]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  /** 关键词过滤（前端，见文件头注释）：标题/目标子串匹配 */
  const visible = useMemo(() => {
    const keyword = q.trim().toLowerCase();
    if (!keyword) return items ?? [];
    return (items ?? []).filter((task) =>
      `${task.title} ${task.goal ?? ""}`.toLowerCase().includes(keyword),
    );
  }, [items, q]);

  const isFiltered = status !== "" || source !== "" || q.trim() !== "";

  const scenarioNameOf = (scenarioId: string | null): string =>
    scenarios.find((s) => s.id === (scenarioId ?? ""))?.name ?? "通用";

  /** 归档（软删除）：确认后调用归档端点并刷新列表 */
  const archiveTask = async () => {
    if (!archiveTarget) return;
    try {
      await api.post(`/api/tasks/${archiveTarget.id}/archive`);
      toast.success("任务已归档");
      setArchiveTarget(null);
      await load();
    } catch (err) {
      toast.error(errMsg(err));
    }
  };

  /** 当前可见且可参与批量归档的任务（已归档不可再归档，直接排除在选择外） */
  const selectable = useMemo(
    () => visible.filter((task) => task.status !== "archived"),
    [visible],
  );
  const allSelected = selectable.length > 0 && selectable.every((t) => selected.has(t.id));

  const toggleSelect = (taskId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });
  };

  const toggleSelectAll = () => {
    // 全选语义只覆盖"当前可见且可选"的行：筛选切换后批量范围与学生所见一致
    setSelected(allSelected ? new Set() : new Set(selectable.map((t) => t.id)));
  };

  /** 批量归档：逐条部分成功（后端口径），失败项以 toast 明细告知，成功项刷新列表 */
  const batchArchive = async () => {
    const ids = [...selected];
    if (ids.length === 0) return;
    try {
      const res = await api.post<BatchResponse>("/api/tasks/batch", {
        ids,
        action: "archive",
      });
      setBatchConfirmOpen(false);
      setSelected(new Set());
      if (res.failed === 0) {
        toast.success(`已批量归档 ${res.succeeded} 项任务`);
      } else {
        // 部分失败：逐条列出失败原因（任务名可读性优于 id）
        const titleOf = new Map((items ?? []).map((t) => [t.id, t.title]));
        const detail = res.results
          .filter((r) => !r.ok)
          .map((r) => `「${titleOf.get(r.id) ?? r.id}」${r.message}`)
          .join("；");
        toast.error(`已归档 ${res.succeeded} 项，${res.failed} 项失败：${detail}`);
      }
      await load();
    } catch (err) {
      toast.error(errMsg(err));
    }
  };

  return (
    <div>
      <PageHeader title="学习任务" sub="目标、预设、教师与诊断来源任务的统一闭环" />

      {/* 筛选区：状态 chips + 来源下拉 + 关键词（PRD-01 §6.1） */}
      <Card className="mb-4">
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 flex-wrap" role="group" aria-label="状态筛选">
            {STATUS_FILTERS.map((item) => (
              <button
                key={item.value}
                type="button"
                aria-pressed={status === item.value}
                className={`badge ${status === item.value ? "badge-primary" : "badge-neutral"}`}
                style={{ border: "none", cursor: "pointer" }}
                onClick={() => setStatus(item.value)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-2">
            <Select
              aria-label="来源筛选"
              value={source}
              options={SOURCE_OPTIONS}
              onChange={(e) => setSource(e.target.value)}
            />
            <SearchInput
              value={q}
              onChange={setQ}
              placeholder="搜索任务名称或目标"
              aria-label="任务搜索"
            />
          </div>
        </div>
      </Card>

      {/* 批量操作条：有勾选时出现；全选只覆盖当前可见且未归档的任务 */}
      {selectable.length > 0 ? (
        <Card className="mb-4">
          <div className="flex items-center gap-3 flex-wrap">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                aria-label="全选当前列表"
                checked={allSelected}
                onChange={toggleSelectAll}
              />
              全选
            </label>
            {selected.size > 0 ? (
              <>
                <span className="text-sm text-secondary">已选 {selected.size} 项</span>
                <Button size="sm" variant="secondary" onClick={() => setBatchConfirmOpen(true)}>
                  批量归档
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
                  取消选择
                </Button>
              </>
            ) : (
              <span className="text-xs text-muted">勾选任务后可批量归档</span>
            )}
          </div>
        </Card>
      ) : null}

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : loading && items === null ? (
        <div className="loading-block">
          <Spinner large /> 正在加载任务…
        </div>
      ) : visible.length === 0 ? (
        isFiltered ? (
          <EmptyState
            title="没有符合条件的任务"
            hint="试试切换状态/来源筛选或清空关键词"
            action={
              <Button
                variant="secondary"
                onClick={() => {
                  setStatus("");
                  setSource("");
                  setQ("");
                }}
              >
                清除筛选
              </Button>
            }
          />
        ) : (
          // PRD-06 §7.2 空态：给三条可执行入口而非空白页
          <EmptyState
            title="还没有学习任务"
            hint="从预设学习、教师任务或 Agent 指挥舱开始你的第一个学习任务"
            action={
              <div className="flex items-center gap-2 flex-wrap justify-center">
                <Link to="/presets" className="btn btn-primary">
                  去预设学习
                </Link>
                <Link to="/" className="btn btn-secondary">
                  打开 Agent 指挥舱
                </Link>
                <Link to="/" className="btn btn-secondary">
                  上传标注诊断
                </Link>
              </div>
            }
          />
        )
      ) : (
        <div className="grid grid-cols-2">
          {visible.map((task) => (
            <Card key={task.id}>
              <div className="flex flex-col gap-3">
                <div className="flex items-start justify-between gap-2">
                  <span className="flex items-start gap-2">
                    {task.status !== "archived" ? (
                      <input
                        type="checkbox"
                        aria-label={`选择任务 ${task.title}`}
                        checked={selected.has(task.id)}
                        onChange={() => toggleSelect(task.id)}
                        style={{ marginTop: 3 }}
                      />
                    ) : null}
                    <strong>{task.title}</strong>
                  </span>
                  <span className="flex items-center gap-2 flex-shrink-0">
                    {task.source === "teacher" ? (
                      // 教师任务不可删除只可归档（PRD-06 §8.2），徽标提示来源约束
                      <span className="badge badge-warning">教师</span>
                    ) : null}
                    <StatusBadge status={task.status} />
                  </span>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  <Tag>{taskSourceLabel(task.source)}</Tag>
                  <Tag>{dataTypeLabel(task.data_type)}</Tag>
                  <Tag>{scenarioNameOf(task.scenario_id)}</Tag>
                </div>
                {task.cap_ids.length > 0 ? (
                  <div className="flex items-center gap-2 flex-wrap">
                    {task.cap_ids.slice(0, 4).map((capId) => (
                      <Tag key={capId}>{capNameOf(capNames, capId)}</Tag>
                    ))}
                    {task.cap_ids.length > 4 ? (
                      <span className="text-xs text-muted">+{task.cap_ids.length - 4}</span>
                    ) : null}
                  </div>
                ) : null}
                <div className="flex items-center gap-3">
                  <div style={{ flex: 1 }}>
                    <ProgressBar value={task.progress} />
                  </div>
                  <span className="text-xs text-secondary">
                    进度 {Math.round(task.progress * 100)}%
                    {task.latest_score != null
                      ? ` · 最近得分 ${Math.round(task.latest_score * 100)}`
                      : ""}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <Button
                    size="sm"
                    onClick={() =>
                      navigate(`/tasks/${task.id}`, {
                        state: { returnTo: `${location.pathname}${location.search}` },
                      })
                    }
                  >
                    {NEXT_ACTION[task.status]}
                  </Button>
                  {task.status !== "archived" ? (
                    <Button variant="ghost" size="sm" onClick={() => setArchiveTarget(task)}>
                      归档
                    </Button>
                  ) : null}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* 归档二次确认（软删除；说明不回滚掌握度，PRD-06 §12.2） */}
      <ConfirmDialog
        open={archiveTarget !== null}
        title="归档任务"
        description={`归档后「${archiveTarget?.title ?? ""}」不再显示在默认列表中，可在「已归档」筛选中查看。已确认的掌握度不受影响。`}
        confirmText="确认归档"
        danger
        onConfirm={archiveTask}
        onCancel={() => setArchiveTarget(null)}
      />

      {/* 批量归档二次确认：与单个归档同口径（软删除，不回滚掌握度） */}
      <ConfirmDialog
        open={batchConfirmOpen}
        title="批量归档任务"
        description={`将归档已选的 ${selected.size} 项任务。归档后可在「已归档」筛选中查看，已确认的掌握度不受影响。`}
        confirmText="确认批量归档"
        danger
        onConfirm={batchArchive}
        onCancel={() => setBatchConfirmOpen(false)}
      />
    </div>
  );
}
