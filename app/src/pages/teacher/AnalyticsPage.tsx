/**
 * 学情分析（/teacher/analytics，PRD-02 §6 + PRD-06 §10.2）。
 *
 * 数据口径（为什么）：
 * - 所有数字直接渲染 GET /api/teacher/analytics 的聚合结果（后端从 mastery /
 *   task_attempts / 已发布任务练习提交真实计算，PRD-02 §6.3"干预建议必须
 *   基于真实学习数据"），前端不做任何二次估算。
 * - 班级是必选筛选（PRD §6.2）：列表加载后自动选中第一个班级再发分析请求，
 *   避免"全班级混合"视图冲淡单个课堂的问题信号。
 * - 学生个人能力分析已拆至 /teacher/analytics/students；本页只提供班级聚合，并通过
 *   class_id 把当前班级筛选传给个人分析页，避免聚合和逐学生明细互相干扰。
 * - 图表全部手写 CSS/SVG（契约禁用新依赖，不引图表库）。
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type {
  Analytics,
  ClassInfo,
  Paginated,
  TeacherErrorAnalysis,
} from "../../api/types";
import {
  Card,
  DataTable,
  EmptyState,
  ErrorState,
  PageHeader,
  Select,
  Spinner,
  type Column,
} from "../../components";
import {
  ANALYTICS_RANGE_OPTIONS,
  DATA_TYPE_OPTIONS,
  TASK_SOURCE_OPTIONS,
  errMsg,
} from "./utils";

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
  const [source, setSource] = useState("");
  const [range, setRange] = useState("30d");

  // ---- 班级聚合结果 ----
  const [data, setData] = useState<Analytics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 班级列表挂载时拉一次，后续分析请求复用已选班级。
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
            source: source || undefined,
            range,
          },
          // AI-backed analysis may need longer than the generic 10s request
          // budget; the filter spinner remains visible until this bounded call
          // settles or the user changes the filter.
          { signal, timeoutMs: 30_000 },
        );
        if (signal?.aborted) return;
        setData(res);
      } catch (err) {
        if (!signal?.aborted) setError(errMsg(err, "学情数据加载失败"));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [classId, dataType, source, range],
  );

  // 任一筛选变化即重新聚合（请求轻量，且教师调筛选是探索式操作）
  useEffect(() => {
    const controller = new AbortController();
    void loadAnalytics(controller.signal);
    return () => controller.abort();
  }, [loadAnalytics]);

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

  // 趋势图归一基准：取提交/完成的最大值，空数据时给 1 防止除零
  const trendMax = useMemo(
    () => Math.max(1, ...(data?.trend.flatMap((d) => [d.submissions, d.completions]) ?? [1])),
    [data],
  );

  /** Keep older rolling responses readable while the backend adds analysis metadata. */
  const errorAnalysis: TeacherErrorAnalysis = data?.error_analysis ?? {
    source: "none",
    sample_count: 0,
    generated_at: null,
    provider_model: null,
    notice: null,
  };

  const errorAnalysisLabel =
    errorAnalysis.source === "ai"
      ? "AI 动态分析"
      : errorAnalysis.source === "fallback"
        ? "本地降级统计"
        : "暂无分析";

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
      <PageHeader
        title="学情分析"
        actions={
          <Link
            className="btn btn-secondary"
            to={
              classId
                ? `/teacher/analytics/students?class_id=${encodeURIComponent(classId)}`
                : "/teacher/analytics/students"
            }
          >
            学生能力分析
          </Link>
        }
      />

      {/* 筛选条（PRD §6.2 五项；班级必选，已自动选中第一个）。两行显式分组，避免宽度变化导致筛选项随机换行。 */}
      <Card className="teacher-filter-surface mb-4">
        <div className="teacher-analytics-filter-grid" role="group" aria-label="学情筛选条件">
          <div className="teacher-analytics-filter-row teacher-analytics-filter-row-primary">
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
          </div>
          <div className="teacher-analytics-filter-row teacher-analytics-filter-row-secondary">
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
            {loading ? (
              <span className="teacher-analytics-filter-loading" role="status" aria-label="正在加载">
                <Spinner size={16} />
              </span>
            ) : null}
          </div>
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
          <div className="mb-4">
            {/* 班级能力热力图：色块深浅=平均掌握度，红=薄弱（与图谱配色同口径） */}
            <Card
              title={`班级能力热力图（前 ${Math.min(10, data.heatmap.length)} 项）`}
              className="teacher-table-surface"
            >
              {data.heatmap.length === 0 ? (
                <EmptyState title="暂无掌握度数据" />
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

          </div>

          {/* 任务完成趋势：纯 CSS 双系列柱状图（提交 vs 完成） */}
          <Card title="任务完成趋势" className="mb-4">
            {data.trend.length === 0 ? (
              <EmptyState title="暂无任务活动" />
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
            {/* 高频错误只来自已发布任务提交；元数据如实标出 AI 或本地降级来源。 */}
            <Card title="高频错误统计">
              <div
                aria-label="错误分析来源"
                className="text-xs text-secondary mb-3"
                role="status"
              >
                <span>{errorAnalysisLabel}</span>
                {errorAnalysis.sample_count > 0
                  ? ` · ${errorAnalysis.sample_count} 个低分练习样本`
                  : ""}
              </div>
              {errorAnalysis.notice ? (
                <p className="text-xs text-secondary mb-3">{errorAnalysis.notice}</p>
              ) : null}
              {data.top_errors.length === 0 ? (
                <EmptyState title="暂无错误统计" />
              ) : (
                <ul className="flex flex-col gap-3">
                  {data.top_errors.map((err) => (
                    <li key={err.error_type} className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <strong className="text-sm">{err.label || err.error_type}</strong>
                        {err.label && err.label !== err.error_type ? (
                          <span className="font-mono text-xs text-muted block">{err.error_type}</span>
                        ) : null}
                        {err.affected_students !== undefined || err.task_ids !== undefined ? (
                          <span className="text-xs text-secondary block mt-1">
                            影响 {err.affected_students ?? 0} 名学生 · {err.task_ids?.length ?? 0} 个任务
                          </span>
                        ) : null}
                        {err.suggestion ? (
                          <span className="text-xs text-secondary block mt-1">建议：{err.suggestion}</span>
                        ) : null}
                      </div>
                      <span className="flex items-center gap-2 shrink-0">
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

          </div>

          {/* 教学干预建议：后端规则化生成（只引用真实数字），空态如实展示 */}
          <Card title="教学干预建议">
            {data.suggestions.length === 0 ? (
              <EmptyState
                title="数据积累中"
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
