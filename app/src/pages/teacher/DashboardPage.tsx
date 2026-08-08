/**
 * 教师工作台（/teacher，PRD-02 §3）。
 *
 * 数据口径（为什么）：
 * - 班级概览/薄弱 Top5/待办来自 GET /api/teacher/dashboard（后端已按
 *   class_teachers 隔离，只含自己带的班级，PRD-02 §3.2"只展示有权限班级"）。
 * - "最近任务"不在 dashboard 载荷里，复用 GET /api/teacher/tasks
 *   （后端按 updated_at 倒序）取前 5 条，保证展示的是真实数据而非另造口径。
 * - PRD §3.1 的"学生异常诊断"待办在后端 dashboard/todos 中没有对应数据
 *   （analytics.top_errors 属于学情接口），按契约"无数据则如实隐藏"不渲染，
 *   避免展示一个永远为 0 的伪指标。
 */

import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { BarChart3, ClipboardList } from "lucide-react";
import { api } from "../../api/client";
import type { TeacherDashboard, TeacherTask } from "../../api/types";
import {
  Card,
  EmptyState,
  ErrorState,
  PageHeader,
  ProgressBar,
  Spinner,
  StatusBadge,
} from "../../components";
import { avgOf, fmtDateTime, pct } from "./utils";

/** 任务卡片右上角的发布状态：原件恒为 draft，发布状态由学生副本数推导（teacher.py） */
function TaskStateBadge({ task }: { task: TeacherTask }) {
  if (task.published_count > 0) {
    return <span className="badge badge-success">已发布 {task.published_count} 人</span>;
  }
  return <StatusBadge status={task.status} />;
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<TeacherDashboard | null>(null);
  const [recentTasks, setRecentTasks] = useState<TeacherTask[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      // 两个请求互不依赖，并行拉取；任一失败整体进错误态（工作台是聚合页，
      // 半份数据比明确的重试入口更容易误导）
      const [dash, tasks] = await Promise.all([
        api.get<TeacherDashboard>("/api/teacher/dashboard", undefined, { signal }),
        api.get<{ items: TeacherTask[] }>("/api/teacher/tasks", undefined, { signal }),
      ]);
      if (signal?.aborted) return;
      setData(dash);
      setRecentTasks(tasks.items.slice(0, 5));
    } catch (err) {
      if (!signal?.aborted) {
        setError(err instanceof Error ? err.message : "数据加载失败，请稍后重试");
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  if (loading && !data) {
    return (
      <div className="loading-block" style={{ minHeight: "40vh" }}>
        <Spinner large /> 正在加载工作台…
      </div>
    );
  }
  if (error && !data) {
    return <ErrorState message={error} onRetry={load} />;
  }
  if (!data) return null;

  // ---- 顶部统计卡：全部由 dashboard 真实字段聚合（null 不参与均值）----
  const studentTotal = data.classes.reduce((n, c) => n + c.student_count, 0);
  const completionRate = avgOf(data.classes.map((c) => c.task_completion_rate));
  const avgMastery = avgOf(data.classes.map((c) => c.avg_mastery));
  const stats: { label: string; value: string; hint?: string }[] = [
    { label: "班级数", value: String(data.classes.length) },
    { label: "学生总数", value: String(studentTotal) },
    { label: "任务完成率", value: pct(completionRate) },
    { label: "平均掌握度", value: pct(avgMastery) },
  ];

  return (
    <div className="teacher-workbench-page teacher-dashboard-page">
      <PageHeader title="教师工作台" sub="班级学习概览、薄弱能力排行与待办事项一览" />

      {/* 班级概览统计卡（PRD-02 §3.1） */}
      <div className="grid teacher-dashboard-stats mb-4">
        {stats.map((s) => (
          <Card key={s.label}>
            <div className="text-sm text-secondary">{s.label}</div>
            <div style={{ fontSize: "var(--font-size-2xl)", fontWeight: 700 }}>{s.value}</div>
          </Card>
        ))}
      </div>

      <div className="grid teacher-two-column mb-4">
        {/* 高频薄弱能力 Top5（验收：首页可见班级薄弱能力 Top 5） */}
        <Card title="高频薄弱能力 Top 5">
          {data.weak_caps_top5.length === 0 ? (
            <EmptyState
              title="暂无薄弱能力数据"
              hint="学生完成练习或诊断后，低于薄弱线的能力将在此呈现"
            />
          ) : (
            <ul className="flex flex-col gap-3">
              {data.weak_caps_top5.map((cap) => (
                <li key={cap.cap_id}>
                  <div className="flex items-center justify-between mb-2">
                    <span>{cap.cap_name}</span>
                    <span className="text-sm text-secondary">
                      平均 {Math.round(cap.avg_score * 100)}% · {cap.student_count} 人薄弱
                    </span>
                  </div>
                  {/* 薄弱线 0.6（teacher.py WEAK_LINE）：分数越低越红，用档位色提示干预优先级 */}
                  <ProgressBar
                    value={cap.avg_score}
                    tone={cap.avg_score < 0.4 ? "danger" : "warning"}
                  />
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* RAG 审核已移至系统管理端；教师工作台只展示自己的教学任务待办。 */}
        <Card title="待办事项">
          <div className="flex flex-col gap-3">
            <Link to="/teacher/tasks" style={{ color: "inherit" }}>
              <div className="teacher-action-row">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ClipboardList size={18} />
                    <span>待发布任务（草稿）</span>
                  </div>
                  <strong>{data.todos.unpublished_teacher_tasks}</strong>
                </div>
              </div>
            </Link>
          </div>
        </Card>
      </div>

      {/* 最近任务（自己的教学任务原件，按更新时间倒序取 5 条） */}
      <Card title="最近任务" actions={<Link to="/teacher/tasks">查看全部</Link>} className="mb-4">
        {recentTasks.length === 0 ? (
          <EmptyState
            title="还没有教学任务"
            hint="创建任务并发布到班级后，学生即可在任务列表中看到"
            action={<Link to="/teacher/tasks">去新建教学任务</Link>}
          />
        ) : (
          <ul className="flex flex-col gap-2">
            {recentTasks.map((task) => (
              <li key={task.id}>
                <Link
                  to="/teacher/tasks"
                  className="flex items-center justify-between"
                  style={{ color: "inherit" }}
                >
                  <span className="flex items-center gap-2">
                    {task.title}
                    <span className="text-xs text-muted">v{task.version}</span>
                  </span>
                  <span className="flex items-center gap-3">
                    <span className="text-sm text-muted">
                      更新于 {fmtDateTime(task.updated_at)}
                    </span>
                    <TaskStateBadge task={task} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* 教师快捷入口只保留教学工作流，RAG 管理由系统管理员在独立门户执行。 */}
      <Card title="快捷入口" className="teacher-quick-actions">
        <div className="grid teacher-quick-action-grid">
          {[
            { label: "新建教学任务", to: "/teacher/tasks", icon: ClipboardList },
            { label: "查看学情", to: "/teacher/analytics", icon: BarChart3 },
          ].map((entry) => (
            <button
              key={entry.label}
              type="button"
              className="btn btn-secondary btn-block"
              onClick={() => navigate(entry.to)}
            >
              <entry.icon size={16} style={{ marginRight: 6, verticalAlign: -3 }} />
              {entry.label}
            </button>
          ))}
        </div>
      </Card>
    </div>
  );
}
