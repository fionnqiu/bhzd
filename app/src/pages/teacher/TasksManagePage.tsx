/**
 * 教师任务管理中心（/teacher/tasks）。
 *
 * Why: 任务发布表单需要较长的编辑流程，不能同时承担任务目录、状态筛选
 * 和入口导航；将目录独立出来后，教师可以先扫描草稿/已发布任务，再决定
 * 是继续编辑还是进入发布流程。
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Pencil, Plus, Send } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import type { Paginated, TeacherTask } from "../../api/types";
import {
  Button,
  Card,
  DataTable,
  EmptyState,
  ErrorState,
  PageHeader,
  StatusBadge,
  Tabs,
} from "../../components";
import type { Column } from "../../components/DataTable";
import { dataTypeLabel, errMsg, fmtDateTime } from "./utils";

type TaskFilter = "all" | "draft" | "published";

const FILTER_TABS = [
  { key: "all", label: "全部" },
  { key: "draft", label: "草稿" },
  { key: "published", label: "已发布" },
];

/** The API keeps the source row in `draft`; publication is represented by child copies. */
function taskDisplayStatus(task: TeacherTask): "draft" | "published" {
  return task.published_count > 0 || String(task.status) === "published" ? "published" : "draft";
}

function taskRoute(taskId: string): string {
  // IDs are generated server-side, but escaping here keeps this link safe if a legacy ID contains
  // a reserved path character.
  return `/teacher/tasks/${encodeURIComponent(taskId)}`;
}

export default function TasksManagePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<TeacherTask[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<TaskFilter>("all");

  useEffect(() => {
    const handoffId = new URLSearchParams(location.search).get("taskId")?.trim();
    if (!handoffId) return;
    // Teacher Agent links historically used /teacher/tasks?taskId=...; redirect that handoff to
    // the canonical edit route so old messages remain actionable after the directory split.
    navigate(`/teacher/tasks/${encodeURIComponent(handoffId)}`, { replace: true });
  }, [location.search, navigate]);

  const loadTasks = useCallback(async (signal?: AbortSignal) => {
    try {
      const response = await api.get<Paginated<TeacherTask>>("/api/teacher/tasks", undefined, {
        signal,
      });
      if (signal?.aborted) return;
      setTasks(response.items);
      setError(null);
    } catch (err) {
      if (!signal?.aborted) setError(errMsg(err, "任务列表加载失败"));
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadTasks(controller.signal);
    return () => controller.abort();
  }, [loadTasks]);

  const visibleTasks = useMemo(
    () => (tasks ?? []).filter((task) => filter === "all" || taskDisplayStatus(task) === filter),
    [filter, tasks],
  );

  const columns = useMemo<Column<TeacherTask>[]>(
    () => [
      {
        key: "title",
        title: "任务标题",
        render: (task) => (
          <Link className="teacher-task-title-link" to={taskRoute(task.id)}>
            {task.title}
          </Link>
        ),
      },
      {
        key: "data_type",
        title: "数据类型",
        render: (task) => dataTypeLabel(task.data_type),
      },
      {
        key: "published_count",
        title: "发布情况",
        render: (task) =>
          task.published_count > 0 ? `${task.published_count} 名学生` : "尚未发布",
      },
      {
        key: "status",
        title: "状态",
        render: (task) => <StatusBadge status={taskDisplayStatus(task)} />,
      },
      {
        key: "updated_at",
        title: "最近更新",
        render: (task) => fmtDateTime(task.updated_at),
      },
      {
        key: "actions",
        title: "操作",
        width: "12rem",
        render: (task) => {
          const href = taskRoute(task.id);
          const published = taskDisplayStatus(task) === "published";
          return (
            <div className="teacher-task-row-actions">
              <Link className="btn btn-ghost btn-sm" to={href} aria-label={`编辑 ${task.title}`}>
                <Pencil size={14} aria-hidden />
                编辑
              </Link>
              <Link
                className="btn btn-secondary btn-sm"
                to={href}
                aria-label={`${published ? "再次发布" : "发布"} ${task.title}`}
              >
                <Send size={14} aria-hidden />
                {published ? "再次发布" : "发布"}
              </Link>
            </div>
          );
        },
      },
    ],
    [],
  );

  const listContent =
    error !== null ? (
      <ErrorState message={error} onRetry={() => void loadTasks()} />
    ) : tasks === null ? (
      <DataTable ariaLabel="教师任务列表" columns={columns} rows={[]} loading empty="加载中…" />
    ) : visibleTasks.length === 0 ? (
      <EmptyState
        title={
          filter === "all" ? "还没有教学任务" : `暂无${filter === "draft" ? "草稿" : "已发布"}任务`
        }
        hint="创建一张任务卡后，可以在这里继续编辑并发布到班级。"
        action={
          <Button onClick={() => navigate("/teacher/tasks/new")}>
            <Plus size={16} aria-hidden />
            新建任务
          </Button>
        }
      />
    ) : (
      <DataTable
        ariaLabel="教师任务列表"
        columns={columns}
        rows={visibleTasks}
        rowKey={(task) => task.id}
        empty="暂无符合条件的任务"
        wrapperClassName="table-wrap-borderless"
      />
    );

  return (
    <div className="teacher-workbench-page teacher-task-manage-page">
      <PageHeader
        title="任务管理"
        actions={
          <Button onClick={() => navigate("/teacher/tasks/new")}>
            <Plus size={16} aria-hidden />
            新建任务
          </Button>
        }
      />

      <Card className="teacher-filter-surface teacher-task-manage-filter" title="任务状态">
        <Tabs
          tabs={FILTER_TABS}
          active={filter}
          onChange={(value) => setFilter(value as TaskFilter)}
        />
        <p className="text-sm text-secondary mt-3" aria-live="polite">
          {tasks === null ? "正在加载任务…" : `当前显示 ${visibleTasks.length} 项`}
        </p>
      </Card>

      <Card
        className="teacher-table-surface teacher-task-manage-table mt-4"
        title={`教学任务${tasks === null ? "" : `（${visibleTasks.length}）`}`}
      >
        {listContent}
      </Card>
    </div>
  );
}
