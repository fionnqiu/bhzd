/**
 * 学情分析（/teacher/analytics，PRD-02 §6 + PRD-06 §10.2）。
 *
 * 数据口径（为什么）：
 * - 所有数字直接渲染 GET /api/teacher/analytics 的聚合结果（后端从 mastery /
 *   task_attempts / diagnostic_summaries 真实计算，PRD-02 §6.3"干预建议必须
 *   基于真实学习数据"），前端不做任何二次估算。
 * - 班级是必选筛选（PRD §6.2）：列表加载后自动选中第一个班级再发分析请求，
 *   避免"全班级混合"视图冲淡单个课堂的问题信号。
 * - "学生个人能力地图"：选择学生后调 GET /api/teacher/analytics/students/{id}
 *   ?class_id= 拿逐学生明细（掌握度/最近任务/掌握度事件/诊断摘要），在下方
 *   整宽区域渲染真实明细；诊断明细遵循 PRD-06 §15 #2——未授权时后端回
 *   diagnostics=null + diagnostics_note，前端如实展示"未授权"提示而不伪造数据。
 * - 图表全部手写 CSS/SVG（契约禁用新依赖，不引图表库）。
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { Analytics, ClassInfo, Paginated, StudentRow } from "../../api/types";
import {
  Card,
  DataTable,
  EmptyState,
  ErrorState,
  MasteryBadge,
  PageHeader,
  ProgressBar,
  Select,
  Spinner,
  StatusBadge,
  type Column,
} from "../../components";
import {
  ANALYTICS_RANGE_OPTIONS,
  DATA_TYPE_OPTIONS,
  TASK_SOURCE_OPTIONS,
  dataTypeLabel,
  errMsg,
  fmtDateTime,
  pct,
} from "./utils";
import type { GraphNode } from "../../api/types";

/* ------------------------------------------------ 学生明细的页面本地类型
 * （api/types.ts 由并行代理维护，本页按 teacher.py student_analytics_detail
 * 的返回结构自留一份） */
interface StudentMasteryRow {
  cap_id: string;
  cap_name: string;
  /** '' = 通用掌握度（蓝图 §5 口径） */
  scenario_id: string;
  score: number;
  updated_at: string;
}

interface StudentTaskRow {
  id: string;
  title: string;
  status: string;
  source: string;
  /** 该任务最近一次提交得分（0..1），无提交为 null */
  score: number | null;
  updated_at: string;
}

interface MasteryEventRow {
  cap_id: string;
  scenario_id: string;
  old_score: number;
  new_score: number;
  source: string;
  created_at: string;
}

interface DiagnosticSummaryRow {
  id: string;
  file_format: string | null;
  data_type: string | null;
  scenario_id: string | null;
  error_count: number;
  severity_counts: Record<string, number>;
  created_at: string;
}

/** GET /api/teacher/analytics/students/{student_id}?class_id= 响应 */
interface StudentAnalyticsDetail {
  student_id: string;
  class_id: string;
  mastery: StudentMasteryRow[];
  tasks: StudentTaskRow[];
  /** 未授权时为 null（diagnostics_note 带说明），授权后为摘要数组（PRD-06 §15 #2） */
  diagnostics: DiagnosticSummaryRow[] | null;
  diagnostics_note: string | null;
  /** 新→旧最多 30 条；画趋势图需自行反转为旧→新 */
  mastery_events: MasteryEventRow[];
}

/** 掌握度分数 → 热力色块背景（绿 120° → 红 0°，连续渐变，低饱和保证文字可读） */
function heatColor(score: number): string {
  const hue = Math.round(score * 120);
  return `hsl(${hue} 65% 82%)`;
}

/** 趋势图单日柱高上限（px），超过的值按最大值归一 */
const TREND_MAX_H = 120;

export default function AnalyticsPage() {
  // ---- 筛选条件（班级必选；其余可空=不过滤） ----
  const [classes, setClasses] = useState<ClassInfo[] | null>(null);
  const [classError, setClassError] = useState<string | null>(null);
  const [classId, setClassId] = useState("");
  const [dataType, setDataType] = useState("");
  const [scenarioId, setScenarioId] = useState("");
  const [source, setSource] = useState("");
  const [range, setRange] = useState("30d");
  const [scenarios, setScenarios] = useState<GraphNode[]>([]);

  // ---- 分析结果与学生列表（个人能力地图的选择集） ----
  const [data, setData] = useState<Analytics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [students, setStudents] = useState<StudentRow[]>([]);
  const [studentId, setStudentId] = useState("");
  // ---- 选中学生的逐人明细（独立加载，失败不影响班级聚合面板） ----
  const [detail, setDetail] = useState<StudentAnalyticsDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  // 重试计数：studentId 不变时点"重试"也要重新发请求，所以 effect 依赖它
  const [detailRetry, setDetailRetry] = useState(0);

  // 班级列表 + 场景词表（SCN 节点）挂载时拉一次
  useEffect(() => {
    const controller = new AbortController();
    void api
      .get<Paginated<ClassInfo>>("/api/teacher/classes", undefined, { signal: controller.signal })
      .then((res) => {
        if (controller.signal.aborted) return;
        setClasses(res.items);
        // 班级必选：默认选中第一个，触发后续分析请求
        if (res.items.length > 0) setClassId((cur) => cur || res.items[0].id);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setClassError(errMsg(err, "班级列表加载失败"));
      });
    void api
      .get<Paginated<GraphNode>>(
        "/api/graph/nodes",
        { type: "SCN", limit: 100 },
        { signal: controller.signal },
      )
      .then((res) => {
        if (!controller.signal.aborted) setScenarios(res.items);
      })
      .catch(() => undefined); // 场景筛选词表缺席时只少一个可选项，不阻断页面
    return () => controller.abort();
  }, []);

  const loadAnalytics = useCallback(
    async (signal?: AbortSignal) => {
      if (!classId) return;
      setLoading(true);
      setError(null);
      try {
        const res = await api.get<Analytics>(
          "/api/teacher/analytics",
          {
            class_id: classId,
            data_type: dataType || undefined,
            scenario_id: scenarioId || undefined,
            source: source || undefined,
            range,
          },
          { signal },
        );
        if (signal?.aborted) return;
        setData(res);
      } catch (err) {
        if (!signal?.aborted) setError(errMsg(err, "学情数据加载失败"));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [classId, dataType, scenarioId, source, range],
  );

  // 任一筛选变化即重新聚合（请求轻量，且教师调筛选是探索式操作）
  useEffect(() => {
    const controller = new AbortController();
    void loadAnalytics(controller.signal);
    return () => controller.abort();
  }, [loadAnalytics]);

  // 个人地图的学生选择集随班级走（与分析请求独立，失败只影响这一个面板）
  useEffect(() => {
    setStudentId("");
    if (!classId) {
      setStudents([]);
      return;
    }
    const controller = new AbortController();
    void api
      .get<Paginated<StudentRow>>(`/api/teacher/classes/${classId}/students`, undefined, {
        signal: controller.signal,
      })
      .then((res) => {
        if (!controller.signal.aborted) setStudents(res.items);
      })
      .catch(() => {
        if (!controller.signal.aborted) setStudents([]);
      });
    return () => controller.abort();
  }, [classId]);

  const activeStudent = useMemo(
    () => students.find((s) => s.id === studentId) ?? null,
    [students, studentId],
  );

  // 选中学生后拉逐人明细；stale 标记防快速切换学生时旧响应覆盖新选择
  useEffect(() => {
    setDetail(null);
    setDetailError(null);
    if (!studentId || !classId) {
      setDetailLoading(false);
      return;
    }
    const controller = new AbortController();
    setDetailLoading(true);
    void api
      .get<StudentAnalyticsDetail>(
        `/api/teacher/analytics/students/${studentId}`,
        {
          class_id: classId,
        },
        { signal: controller.signal },
      )
      .then((res) => {
        if (controller.signal.aborted) return;
        setDetail(res);
        setDetailLoading(false);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setDetailError(errMsg(err, "学生明细加载失败"));
        setDetailLoading(false);
      });
    return () => controller.abort();
  }, [studentId, classId, detailRetry]);

  /** 场景 id → 中文名（'' = 通用掌握度；词表缺席时原样显示 id 兜底） */
  const scenarioNameOf = useCallback(
    (scenarioId: string) =>
      scenarioId === ""
        ? "通用"
        : (scenarios.find((s) => s.id === scenarioId)?.label ?? scenarioId),
    [scenarios],
  );

  // These columns intentionally use stable minimum widths so small panels scroll horizontally.
  const heatmapColumns: Column<Analytics["heatmap"][number]>[] = [
    { key: "cap_name", title: "能力节点", width: "14rem" },
    {
      key: "avg_score",
      title: "平均掌握度",
      width: "8rem",
      render: (row) => (
        <span
          className="font-mono text-sm"
          style={{
            display: "inline-block",
            minWidth: 56,
            textAlign: "center",
            padding: "2px 6px",
            borderRadius: "var(--radius-sm)",
            background: heatColor(row.avg_score),
          }}
        >
          {Math.round(row.avg_score * 100)}%
        </span>
      ),
    },
    { key: "weak_count", title: "薄弱人数", width: "7rem" },
    { key: "student_count", title: "覆盖人数", width: "7rem" },
  ];

  const masteryColumns: Column<StudentMasteryRow>[] = [
    { key: "cap_name", title: "能力节点", width: "14rem" },
    {
      key: "scenario_id",
      title: "场景",
      width: "8rem",
      render: (row) => scenarioNameOf(row.scenario_id),
    },
    {
      key: "score",
      title: "掌握度",
      width: "16rem",
      render: (row) => (
        <span className="flex items-center gap-2">
          <MasteryBadge score={row.score} />
          <ProgressBar
            value={row.score}
            tone={row.score < 0.4 ? "danger" : row.score < 0.8 ? "warning" : "success"}
          />
        </span>
      ),
    },
    {
      key: "updated_at",
      title: "更新时间",
      width: "11rem",
      render: (row) => <span className="text-sm text-muted">{fmtDateTime(row.updated_at)}</span>,
    },
  ];

  const taskColumns: Column<StudentTaskRow>[] = [
    { key: "title", title: "任务", width: "16rem" },
    {
      key: "status",
      title: "状态",
      width: "8rem",
      render: (row) => <StatusBadge status={row.status} />,
    },
    {
      key: "score",
      title: "最近得分",
      width: "8rem",
      render: (row) => (row.score === null ? "—" : `${Math.round(row.score * 100)}%`),
    },
    {
      key: "updated_at",
      title: "更新时间",
      width: "11rem",
      render: (row) => <span className="text-sm text-muted">{fmtDateTime(row.updated_at)}</span>,
    },
  ];

  // 趋势图归一基准：取提交/完成的最大值，空数据时给 1 防止除零
  const trendMax = useMemo(
    () => Math.max(1, ...(data?.trend.flatMap((d) => [d.submissions, d.completions]) ?? [1])),
    [data],
  );

  if (classError) {
    return <ErrorState message={classError} />;
  }
  if (classes === null) {
    return (
      <div className="loading-block" style={{ minHeight: "40vh" }}>
        <Spinner large /> 正在加载…
      </div>
    );
  }
  if (classes.length === 0) {
    return (
      <EmptyState
        title="还没有班级"
        hint="创建班级并邀请学生加入后，才能查看学情分析"
        action={<Link to="/teacher/classes">去新建班级</Link>}
      />
    );
  }

  return (
    <div className="teacher-workbench-page teacher-analytics-page">
      <PageHeader title="学情分析" sub="基于班级真实学习数据的薄弱定位与教学干预建议" />

      {/* 筛选条（PRD §6.2 五项；班级必选，已自动选中第一个） */}
      <Card className="teacher-filter-surface mb-4">
        <div className="flex items-center gap-3" style={{ flexWrap: "wrap" }}>
          <Select
            aria-label="班级"
            options={classes.map((c) => ({ value: c.id, label: c.name }))}
            value={classId}
            onChange={(e) => setClassId(e.target.value)}
          />
          <Select
            aria-label="数据类型"
            options={DATA_TYPE_OPTIONS}
            placeholder="全部数据类型"
            value={dataType}
            onChange={(e) => setDataType(e.target.value)}
          />
          <Select
            aria-label="行业场景"
            options={scenarios.map((s) => ({ value: s.id, label: s.label }))}
            placeholder="全部场景"
            value={scenarioId}
            onChange={(e) => setScenarioId(e.target.value)}
          />
          <Select
            aria-label="任务来源"
            options={TASK_SOURCE_OPTIONS}
            placeholder="全部来源"
            value={source}
            onChange={(e) => setSource(e.target.value)}
          />
          <Select
            aria-label="时间范围"
            options={ANALYTICS_RANGE_OPTIONS}
            value={range}
            onChange={(e) => setRange(e.target.value)}
          />
          {loading ? <Spinner size={16} /> : null}
        </div>
      </Card>

      {/* 样本量提示（PRD-06 §10.2：少于 3 人聚合仅供参考） */}
      {data?.sample_warning ? (
        <div
          role="alert"
          style={{
            padding: "var(--space-3) var(--space-4)",
            marginBottom: "var(--space-4)",
            background: "var(--color-warning-soft)",
            border: "1px solid var(--color-warning)",
            borderRadius: "var(--radius-md)",
          }}
        >
          班级学生少于 3 人，聚合数据仅供参考
        </div>
      ) : null}

      {error && !data ? (
        <ErrorState message={error} onRetry={() => void loadAnalytics()} />
      ) : !data ? (
        <div className="loading-block">
          <Spinner large /> 正在统计…
        </div>
      ) : (
        <>
          <div className="grid teacher-two-column mb-4">
            {/* 班级能力热力图：色块深浅=平均掌握度，红=薄弱（与图谱配色同口径） */}
            <Card
              title={`班级能力热力图（前 ${Math.min(10, data.heatmap.length)} 项）`}
              className="teacher-table-surface"
            >
              {data.heatmap.length === 0 ? (
                <EmptyState title="暂无掌握度数据" hint="学生完成练习后将在此呈现班级能力分布" />
              ) : (
                <DataTable
                  ariaLabel="班级能力热力图"
                  columns={heatmapColumns}
                  rows={data.heatmap.slice(0, 10)}
                  rowKey={(row) => row.cap_id}
                  wrapperClassName="table-wrap-borderless"
                />
              )}
            </Card>

            {/* 学生个人能力地图：选择学生 + 个人聚合速览；逐能力明细在下方整宽区 */}
            <Card title="学生个人能力地图">
              {students.length === 0 ? (
                <EmptyState title="班级暂无学生" hint="学生入班后即可查看个人学习数据" />
              ) : (
                <div className="flex flex-col gap-3">
                  <Select
                    aria-label="选择学生"
                    options={students.map((s) => ({
                      value: s.id,
                      label: `${s.name}（${s.email}）`,
                    }))}
                    placeholder="选择学生查看个人数据"
                    value={studentId}
                    onChange={(e) => setStudentId(e.target.value)}
                  />
                  {activeStudent ? (
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center justify-between">
                        <span className="text-secondary">平均掌握度</span>
                        <MasteryBadge score={activeStudent.avg_mastery} />
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-secondary">任务完成率</span>
                        <strong>{pct(activeStudent.completion_rate)}</strong>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-secondary">最近活跃</span>
                        <span>{fmtDateTime(activeStudent.last_active)}</span>
                      </div>
                      <p className="text-xs text-muted">
                        逐能力掌握度、最近任务与诊断摘要见下方明细区
                      </p>
                    </div>
                  ) : (
                    <p className="text-sm text-secondary">选择学生后展示其逐能力学习明细</p>
                  )}
                </div>
              )}
            </Card>
          </div>

          {/* 学生个人明细（整宽）：掌握度表格 / 最近任务 / 掌握度趋势 / 诊断摘要 */}
          {studentId ? (
            <Card title={`${activeStudent?.name ?? "学生"} 的学习明细`} className="mb-4">
              {detailError && !detail ? (
                <ErrorState message={detailError} onRetry={() => setDetailRetry((n) => n + 1)} />
              ) : detailLoading || !detail ? (
                <div className="loading-block">
                  <Spinner /> 正在加载学生明细…
                </div>
              ) : (
                <div className="flex flex-col gap-4">
                  {/* 逐能力掌握度（含场景维度；色块口径与 MasteryBadge 阈值一致） */}
                  <section>
                    <h4 className="mb-2">逐能力掌握度（{detail.mastery.length}）</h4>
                    {detail.mastery.length === 0 ? (
                      <EmptyState title="暂无掌握度记录" hint="学生完成练习或诊断后将在此呈现" />
                    ) : (
                      <DataTable
                        ariaLabel="学生逐能力掌握度"
                        columns={masteryColumns}
                        rows={detail.mastery}
                        rowKey={(row) => `${row.cap_id}|${row.scenario_id}`}
                      />
                    )}
                  </section>

                  {/* 最近任务（后端已按更新时间倒序截到 20 条） */}
                  <section>
                    <h4 className="mb-2">最近任务（{detail.tasks.length}）</h4>
                    {detail.tasks.length === 0 ? (
                      <EmptyState
                        title="暂无任务记录"
                        hint="发布任务到班级后，学生任务将在此出现"
                      />
                    ) : (
                      <DataTable
                        ariaLabel="学生最近任务"
                        columns={taskColumns}
                        rows={detail.tasks}
                        rowKey={(row) => row.id}
                      />
                    )}
                  </section>

                  {/* 掌握度变化趋势（mastery_events 新→旧，组件内反转为旧→新画线） */}
                  <section>
                    <h4 className="mb-2">掌握度变化趋势</h4>
                    {detail.mastery_events.length === 0 ? (
                      <p className="text-sm text-secondary">暂无掌握度变化记录</p>
                    ) : (
                      <MasteryTrendChart
                        events={detail.mastery_events}
                        capNames={Object.fromEntries(
                          detail.mastery.map((m) => [m.cap_id, m.cap_name]),
                        )}
                      />
                    )}
                  </section>

                  {/* 诊断摘要（PRD-06 §15 #2：未授权只展示提示，不展示数据） */}
                  <section>
                    <h4 className="mb-2">诊断详情</h4>
                    {detail.diagnostics === null ? (
                      <div
                        className="text-sm text-secondary"
                        style={{
                          padding: "var(--space-3) var(--space-4)",
                          background: "var(--color-warning-soft)",
                          border: "1px solid var(--color-warning)",
                          borderRadius: "var(--radius-md)",
                        }}
                      >
                        <strong>该学生未授权诊断详情</strong>
                        <p className="mt-2">
                          {detail.diagnostics_note ??
                            "学生可在个人中心开启「授权教师查看诊断」后，此处将展示其诊断摘要"}
                        </p>
                      </div>
                    ) : detail.diagnostics.length === 0 ? (
                      <EmptyState title="暂无诊断记录" hint="学生上传文件完成诊断后将在此汇总" />
                    ) : (
                      <ul className="flex flex-col gap-2">
                        {detail.diagnostics.map((d) => (
                          <li key={d.id} className="flex items-center justify-between gap-2">
                            <span>
                              {d.file_format ?? "未知格式"}
                              <span className="text-xs text-muted">
                                {" "}
                                · {dataTypeLabel(d.data_type)} · {fmtDateTime(d.created_at)}
                              </span>
                            </span>
                            <span className="flex items-center gap-2">
                              {(d.severity_counts.major ?? 0) > 0 ? (
                                <span className="badge badge-danger">
                                  严重 {d.severity_counts.major}
                                </span>
                              ) : null}
                              {(d.severity_counts.minor ?? 0) > 0 ? (
                                <span className="badge badge-warning">
                                  次要 {d.severity_counts.minor}
                                </span>
                              ) : null}
                              <strong>{d.error_count} 个错误</strong>
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                </div>
              )}
            </Card>
          ) : null}

          {/* 任务完成趋势：纯 CSS 双系列柱状图（提交 vs 完成） */}
          <Card title="任务完成趋势" className="mb-4">
            {data.trend.length === 0 ? (
              <EmptyState title="暂无任务活动" hint="统计期内没有提交或完成记录" />
            ) : (
              <div>
                <div className="flex gap-4 mb-2">
                  <span className="text-xs text-secondary">
                    <span
                      style={{
                        display: "inline-block",
                        width: 10,
                        height: 10,
                        background: "var(--color-primary)",
                        marginRight: 4,
                      }}
                    />
                    提交次数
                  </span>
                  <span className="text-xs text-secondary">
                    <span
                      style={{
                        display: "inline-block",
                        width: 10,
                        height: 10,
                        background: "var(--color-success)",
                        marginRight: 4,
                      }}
                    />
                    完成数
                  </span>
                </div>
                <div
                  className="flex items-end gap-2"
                  style={{ height: TREND_MAX_H + 32, alignItems: "flex-end" }}
                >
                  {data.trend.slice(-14).map((day) => (
                    <div
                      key={day.date}
                      className="flex flex-col items-center gap-1"
                      style={{ flex: 1, minWidth: 0 }}
                      title={`${day.date}：提交 ${day.submissions} 次，完成 ${day.completions} 项`}
                    >
                      <div className="flex items-end gap-1" style={{ height: TREND_MAX_H }}>
                        <div
                          style={{
                            width: 12,
                            height: (day.submissions / trendMax) * TREND_MAX_H,
                            background: "var(--color-primary)",
                            borderRadius: "2px 2px 0 0",
                          }}
                        />
                        <div
                          style={{
                            width: 12,
                            height: (day.completions / trendMax) * TREND_MAX_H,
                            background: "var(--color-success)",
                            borderRadius: "2px 2px 0 0",
                          }}
                        />
                      </div>
                      <span className="text-xs text-muted">{day.date.slice(5)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Card>

          <div className="grid teacher-two-column mb-4">
            {/* 高频错误统计（诊断摘要聚合；严重度用徽章区分干预优先级） */}
            <Card title="高频错误统计">
              {data.top_errors.length === 0 ? (
                <EmptyState title="暂无错误统计" hint="学生提交诊断后将在此聚合高频错误类型" />
              ) : (
                <ul className="flex flex-col gap-2">
                  {data.top_errors.map((err) => (
                    <li key={err.error_type} className="flex items-center justify-between">
                      <span className="font-mono text-sm">{err.error_type}</span>
                      <span className="flex items-center gap-2">
                        {err.major > 0 ? (
                          <span className="badge badge-danger">严重 {err.major}</span>
                        ) : null}
                        {err.minor > 0 ? (
                          <span className="badge badge-warning">次要 {err.minor}</span>
                        ) : null}
                        <strong>{err.count} 次</strong>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            {/* 场景掌握度对比：分组横条（通用 + 各行业场景） */}
            <Card title="场景掌握度对比">
              {data.scenario_comparison.length === 0 ? (
                <EmptyState
                  title="暂无场景数据"
                  hint="学生在场景任务中产生掌握度记录后将在此对比"
                />
              ) : (
                <div className="flex flex-col gap-3">
                  {data.scenario_comparison.map((scn) => (
                    <div key={scn.scenario_id || "general"}>
                      <div className="flex items-center justify-between mb-2">
                        <span>{scn.scenario_name}</span>
                        <span className="text-sm text-secondary">
                          {Math.round(scn.avg_score * 100)}% · {scn.student_count} 人
                        </span>
                      </div>
                      <ProgressBar
                        value={scn.avg_score}
                        tone={
                          scn.avg_score < 0.6
                            ? "danger"
                            : scn.avg_score < 0.8
                              ? "warning"
                              : "success"
                        }
                      />
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>

          {/* 教学干预建议：后端规则化生成（只引用真实数字），空态如实展示 */}
          <Card title="教学干预建议">
            {data.suggestions.length === 0 ? (
              <EmptyState
                title="数据积累中"
                hint="完成更多学习任务与诊断后，将基于真实数据生成针对性建议"
              />
            ) : (
              <div className="flex flex-col gap-2">
                {data.suggestions.map((s, i) => (
                  <div key={i} className="teacher-suggestion-row">
                    {s}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------ 掌握度趋势迷你折线图 */

/** 折线颜色按系列索引轮换（手写 SVG，遵守"不引图表库"约束；取主题同族色） */
const TREND_LINE_COLORS = ["#4f46e5", "#16a34a", "#d97706"];
const TREND_W = 360;
const TREND_H = 140;
const TREND_PAD_X = 12;
const TREND_PAD_Y = 14;

/**
 * 掌握度事件 → 迷你 SVG 折线（每个能力一条线）。
 *
 * 为什么只画事件数最多的 3 个能力：mastery_events 最多 30 条且混着多个
 * cap，全画上线条互相压盖反而读不出趋势；教师最关心的是"变化最频繁的
 * 那几个能力在涨还是跌"。
 */
function MasteryTrendChart({
  events,
  capNames,
}: {
  events: MasteryEventRow[];
  /** cap_id → 中文名（来自同一载荷的 mastery 行；事件本身不带名称） */
  capNames: Record<string, string>;
}) {
  // 按 cap 分组（新→旧），取 Top3 后反转为旧→新，并补上最旧事件的
  // old_score 作为起点——否则折线看不出"从哪个分数涨/跌过来"
  const series = useMemo(() => {
    const byCap = new Map<string, MasteryEventRow[]>();
    for (const e of events) {
      const arr = byCap.get(e.cap_id);
      if (arr) arr.push(e);
      else byCap.set(e.cap_id, [e]);
    }
    return [...byCap.entries()]
      .sort((a, b) => b[1].length - a[1].length)
      .slice(0, 3)
      .map(([capId, rows]) => {
        const ordered = [...rows].reverse();
        return {
          capId,
          values: [ordered[0].old_score, ...ordered.map((r) => r.new_score)],
        };
      });
  }, [events]);

  /** x 坐标：每条线按自己的点数均布（不同能力事件数不同，各自归一） */
  const xOf = (i: number, n: number) =>
    n <= 1 ? TREND_W / 2 : TREND_PAD_X + (i / (n - 1)) * (TREND_W - 2 * TREND_PAD_X);
  /** y 坐标：分数 0..1 映射到画布（y 轴向下，所以用 1-v 翻转） */
  const yOf = (v: number) =>
    TREND_PAD_Y + (1 - Math.min(1, Math.max(0, v))) * (TREND_H - 2 * TREND_PAD_Y);

  return (
    <div>
      <svg
        viewBox={`0 0 ${TREND_W} ${TREND_H}`}
        style={{ width: "100%", maxWidth: 560, height: "auto", display: "block" }}
        role="img"
        aria-label="掌握度变化趋势图"
      >
        {/* 0% / 50% / 100% 参考线，帮助读出绝对水平而非只看相对起伏 */}
        {[0, 0.5, 1].map((v) => (
          <line
            key={v}
            x1={TREND_PAD_X}
            x2={TREND_W - TREND_PAD_X}
            y1={yOf(v)}
            y2={yOf(v)}
            stroke="var(--color-border)"
            strokeDasharray={v === 0 ? undefined : "4 4"}
          />
        ))}
        {series.map((s, si) => (
          <g key={s.capId}>
            {s.values.length > 1 ? (
              <polyline
                fill="none"
                stroke={TREND_LINE_COLORS[si]}
                strokeWidth={2}
                points={s.values.map((v, i) => `${xOf(i, s.values.length)},${yOf(v)}`).join(" ")}
              />
            ) : null}
            {s.values.map((v, i) => (
              <circle
                key={i}
                cx={xOf(i, s.values.length)}
                cy={yOf(v)}
                r={2.5}
                fill={TREND_LINE_COLORS[si]}
              />
            ))}
          </g>
        ))}
      </svg>
      <div className="flex gap-4 mt-2" style={{ flexWrap: "wrap" }}>
        {series.map((s, si) => (
          <span key={s.capId} className="text-xs text-secondary">
            <span
              style={{
                display: "inline-block",
                width: 10,
                height: 10,
                background: TREND_LINE_COLORS[si],
                marginRight: 4,
              }}
            />
            {capNames[s.capId] ?? s.capId}（最新 {Math.round(s.values[s.values.length - 1] * 100)}
            %）
          </span>
        ))}
      </div>
    </div>
  );
}
