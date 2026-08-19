/**
 * 学生能力分析（/teacher/analytics/students）。
 *
 * 班级聚合与个人学习记录分开呈现：进入本页时接受上层学情分析传入的 class_id，
 * 但不会预选学生，也不会在教师明确选择学生前请求或展示个人明细。
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { ClassInfo, Paginated, StudentRow } from "../../api/types";
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
import { dataTypeLabel, errMsg, fmtDateTime } from "./utils";

interface StudentMasteryRow {
  cap_id: string;
  cap_name: string;
  score: number;
  updated_at: string;
}

interface StudentTaskRow {
  id: string;
  title: string;
  status: string;
  source: string;
  score: number | null;
  updated_at: string;
}

interface MasteryEventRow {
  cap_id: string;
  old_score: number;
  new_score: number;
  source: string;
  created_at: string;
}

interface DiagnosticSummaryRow {
  id: string;
  file_format: string | null;
  data_type: string | null;
  error_count: number;
  severity_counts: Record<string, number>;
  created_at: string;
}

/** GET /api/teacher/analytics/students/{student_id}?class_id= 响应。 */
interface StudentAnalyticsDetail {
  student_id: string;
  class_id: string;
  mastery: StudentMasteryRow[];
  tasks: StudentTaskRow[];
  /** 未授权时为 null；diagnostics_note 说明授权状态。 */
  diagnostics: DiagnosticSummaryRow[] | null;
  diagnostics_note: string | null;
  /** 后端按新到旧返回，图表会在本地反转为时间正序。 */
  mastery_events: MasteryEventRow[];
}

const TREND_LINE_COLORS = ["#4f46e5", "#16a34a", "#d97706"];
const TREND_W = 360;
const TREND_H = 140;
const TREND_PAD_X = 12;
const TREND_PAD_Y = 14;

export default function StudentAnalyticsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClassId = searchParams.get("class_id") ?? "";
  const [classes, setClasses] = useState<ClassInfo[] | null>(null);
  const [classId, setClassId] = useState(queryClassId);
  const [classError, setClassError] = useState<string | null>(null);
  const [students, setStudents] = useState<StudentRow[]>([]);
  const [studentsLoading, setStudentsLoading] = useState(false);
  const [studentsError, setStudentsError] = useState<string | null>(null);
  const [studentId, setStudentId] = useState("");
  const [detail, setDetail] = useState<StudentAnalyticsDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailRetry, setDetailRetry] = useState(0);

  // A class passed from the aggregate page wins over the local default, so a teacher starts in
  // the same teaching context even when this page is opened through a copied link.
  useEffect(() => {
    if (queryClassId) {
      setStudentId("");
      setDetail(null);
      setDetailError(null);
      setClassId(queryClassId);
    }
  }, [queryClassId]);

  useEffect(() => {
    const controller = new AbortController();
    void api
      .get<Paginated<ClassInfo>>("/api/teacher/classes", undefined, { signal: controller.signal })
      .then((res) => {
        if (controller.signal.aborted) return;
        setClasses(res.items);
        setClassId((current) =>
          res.items.some((classInfo) => classInfo.id === current)
            ? current
            : (res.items[0]?.id ?? ""),
        );
      })
      .catch((err) => {
        if (!controller.signal.aborted) setClassError(errMsg(err, "班级列表加载失败"));
      });
    return () => controller.abort();
  }, []);

  // Reset the selected student before each roster request. This prevents a response from the
  // previous class from remaining visible or triggering a cross-class personal-data request.
  useEffect(() => {
    setStudentId("");
    setDetail(null);
    setDetailError(null);
    setStudentsError(null);
    if (!classId) {
      setStudents([]);
      setStudentsLoading(false);
      return;
    }
    const controller = new AbortController();
    setStudentsLoading(true);
    void api
      .get<Paginated<StudentRow>>(`/api/teacher/classes/${classId}/students`, undefined, {
        signal: controller.signal,
      })
      .then((res) => {
        if (!controller.signal.aborted) setStudents(res.items);
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          setStudents([]);
          setStudentsError(errMsg(err, "学生列表加载失败"));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setStudentsLoading(false);
      });
    return () => controller.abort();
  }, [classId]);

  const activeStudent = useMemo(
    () => students.find((student) => student.id === studentId) ?? null,
    [studentId, students],
  );

  // The detail endpoint includes protected individual records. It is intentionally gated by an
  // explicit student choice; the initial page load only retrieves class and roster metadata.
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
        { class_id: classId },
        { signal: controller.signal },
      )
      .then((res) => {
        if (!controller.signal.aborted) setDetail(res);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setDetailError(errMsg(err, "学生明细加载失败"));
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [classId, detailRetry, studentId]);

  const masteryColumns: Column<StudentMasteryRow>[] = [
    { key: "cap_name", title: "能力节点", width: "14rem" },
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

  const chooseClass = (nextClassId: string) => {
    // Clear the dependent selection in the same event as the class change; this prevents the
    // detail effect from briefly requesting the previous student's data for a new class.
    setStudentId("");
    setDetail(null);
    setDetailError(null);
    setClassId(nextClassId);
    setSearchParams(nextClassId ? { class_id: nextClassId } : {});
  };

  if (classError) return <ErrorState message={classError} />;
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
        hint="创建班级并邀请学生加入后，才能查看学生能力数据"
        action={<Link to="/teacher/classes">去新建班级</Link>}
      />
    );
  }

  const analyticsLink = classId
    ? `/teacher/analytics?class_id=${encodeURIComponent(classId)}`
    : "/teacher/analytics";

  return (
    <div className="teacher-workbench-page teacher-analytics-page teacher-student-analytics-page">
      <PageHeader
        title="学生能力分析"
        actions={
          <Link className="btn btn-secondary" to={analyticsLink}>
            返回学情分析
          </Link>
        }
      />

      <Card className="teacher-filter-surface mb-4">
        <div
          className="teacher-student-analytics-filter-row"
          role="group"
          aria-label="学生能力筛选条件"
        >
          <Select
            aria-label="班级"
            options={classes.map((classInfo) => ({ value: classInfo.id, label: classInfo.name }))}
            value={classId}
            onChange={(event) => chooseClass(event.target.value)}
          />
          <Select
            aria-label="学生"
            options={students.map((student) => ({
              value: student.id,
              label: `${student.name}（${student.email}）`,
            }))}
            placeholder={studentsLoading ? "正在加载学生…" : "请选择学生"}
            value={studentId}
            disabled={studentsLoading || students.length === 0}
            onChange={(event) => setStudentId(event.target.value)}
          />
        </div>
        {studentsError ? (
          <div className="mt-3">
            <ErrorState message={studentsError} />
          </div>
        ) : null}
      </Card>

      {!studentId ? (
        <EmptyState title="请选择学生" hint="选择学生后显示其详细能力数据" />
      ) : (
        <Card title={`${activeStudent?.name ?? "学生"} 的学习明细`}>
          {detailError && !detail ? (
            <ErrorState
              message={detailError}
              onRetry={() => setDetailRetry((count) => count + 1)}
            />
          ) : detailLoading || !detail ? (
            <div className="loading-block">
              <Spinner /> 正在加载学生明细…
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              <section>
                <h2 className="mb-2" style={{ fontSize: "var(--font-size-lg)" }}>
                  逐能力掌握度（{detail.mastery.length}）
                </h2>
                {detail.mastery.length === 0 ? (
                  <EmptyState title="暂无掌握度记录" />
                ) : (
                  <DataTable
                    ariaLabel="学生逐能力掌握度"
                    columns={masteryColumns}
                    rows={detail.mastery}
                    rowKey={(row) => row.cap_id}
                  />
                )}
              </section>

              <section>
                <h2 className="mb-2" style={{ fontSize: "var(--font-size-lg)" }}>
                  最近任务（{detail.tasks.length}）
                </h2>
                {detail.tasks.length === 0 ? (
                  <EmptyState title="暂无任务记录" />
                ) : (
                  <DataTable
                    ariaLabel="学生最近任务"
                    columns={taskColumns}
                    rows={detail.tasks}
                    rowKey={(row) => row.id}
                  />
                )}
              </section>

              <section>
                <h2 className="mb-2" style={{ fontSize: "var(--font-size-lg)" }}>
                  掌握度变化趋势
                </h2>
                {detail.mastery_events.length === 0 ? (
                  <p className="text-sm text-secondary">暂无掌握度变化记录</p>
                ) : (
                  <MasteryTrendChart
                    events={detail.mastery_events}
                    capNames={Object.fromEntries(
                      detail.mastery.map((mastery) => [mastery.cap_id, mastery.cap_name]),
                    )}
                  />
                )}
              </section>

              <section>
                <h2 className="mb-2" style={{ fontSize: "var(--font-size-lg)" }}>
                  诊断详情
                </h2>
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
                  <EmptyState title="暂无诊断记录" />
                ) : (
                  <ul className="flex flex-col gap-2">
                    {detail.diagnostics.map((diagnostic) => (
                      <li key={diagnostic.id} className="flex items-center justify-between gap-2">
                        <span>
                          {diagnostic.file_format ?? "未知格式"}
                          <span className="text-xs text-muted">
                            {" "}
                            · {dataTypeLabel(diagnostic.data_type)} ·{" "}
                            {fmtDateTime(diagnostic.created_at)}
                          </span>
                        </span>
                        <span className="flex items-center gap-2">
                          {(diagnostic.severity_counts.major ?? 0) > 0 ? (
                            <span className="badge badge-danger">
                              严重 {diagnostic.severity_counts.major}
                            </span>
                          ) : null}
                          {(diagnostic.severity_counts.minor ?? 0) > 0 ? (
                            <span className="badge badge-warning">
                              次要 {diagnostic.severity_counts.minor}
                            </span>
                          ) : null}
                          <strong>{diagnostic.error_count} 个错误</strong>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

/**
 * Draw only the three most frequently updated capabilities. More series make a 30-event history
 * unreadable, while this keeps the chart useful without adding a charting dependency.
 */
function MasteryTrendChart({
  events,
  capNames,
}: {
  events: MasteryEventRow[];
  capNames: Record<string, string>;
}) {
  const series = useMemo(() => {
    const byCapability = new Map<string, MasteryEventRow[]>();
    for (const event of events) {
      const current = byCapability.get(event.cap_id);
      if (current) current.push(event);
      else byCapability.set(event.cap_id, [event]);
    }
    return [...byCapability.entries()]
      .sort((left, right) => right[1].length - left[1].length)
      .slice(0, 3)
      .map(([capId, rows]) => {
        const ordered = [...rows].reverse();
        return {
          capId,
          values: [ordered[0].old_score, ...ordered.map((row) => row.new_score)],
        };
      });
  }, [events]);

  const xOf = (index: number, count: number) =>
    count <= 1 ? TREND_W / 2 : TREND_PAD_X + (index / (count - 1)) * (TREND_W - 2 * TREND_PAD_X);
  const yOf = (value: number) =>
    TREND_PAD_Y + (1 - Math.min(1, Math.max(0, value))) * (TREND_H - 2 * TREND_PAD_Y);

  return (
    <div>
      <svg
        viewBox={`0 0 ${TREND_W} ${TREND_H}`}
        style={{ width: "100%", maxWidth: 560, height: "auto", display: "block" }}
        role="img"
        aria-label="掌握度变化趋势图"
      >
        {[0, 0.5, 1].map((value) => (
          <line
            key={value}
            x1={TREND_PAD_X}
            x2={TREND_W - TREND_PAD_X}
            y1={yOf(value)}
            y2={yOf(value)}
            stroke="var(--color-border)"
            strokeDasharray={value === 0 ? undefined : "4 4"}
          />
        ))}
        {series.map((line, lineIndex) => (
          <g key={line.capId}>
            {line.values.length > 1 ? (
              <polyline
                fill="none"
                stroke={TREND_LINE_COLORS[lineIndex]}
                strokeWidth={2}
                points={line.values
                  .map((value, index) => `${xOf(index, line.values.length)},${yOf(value)}`)
                  .join(" ")}
              />
            ) : null}
            {line.values.map((value, index) => (
              <circle
                key={index}
                cx={xOf(index, line.values.length)}
                cy={yOf(value)}
                r={2.5}
                fill={TREND_LINE_COLORS[lineIndex]}
              />
            ))}
          </g>
        ))}
      </svg>
      <div className="flex gap-4 mt-2" style={{ flexWrap: "wrap" }}>
        {series.map((line, lineIndex) => (
          <span key={line.capId} className="text-xs text-secondary">
            <span
              style={{
                display: "inline-block",
                width: 10,
                height: 10,
                background: TREND_LINE_COLORS[lineIndex],
                marginRight: 4,
              }}
            />
            {capNames[line.capId] ?? line.capId}（最新{" "}
            {Math.round(line.values[line.values.length - 1] * 100)}%）
          </span>
        ))}
      </div>
    </div>
  );
}
