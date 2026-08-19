/**
 * 班级详情（/teacher/classes/:id，PRD-02 §4：学生列表/邀请学生/学习状态/导出报表）。
 *
 * 关键决策（为什么）：
 * - 筛选分两层：掌握度区间走后端 query（mastery_min/max，0..1，页面输入用
 *   0-100 百分数再换算，符合教师填写习惯）；"任务完成状态"后端没有对应参数
 *   （status 参数是"在班/已退班"语义，见 teacher.py class_students），因此
 *   用行内的 completion_rate 在客户端过滤——语义真实且不伪造请求参数。
 * - 导出报表为纯前端 CSV（Blob 下载）：后端没有导出端点，PRD-06 §10.2 要求
 *   "不包含诊断原文件"，导出列只取学生行的聚合字段，天然满足。
 * - "学生学习状态"展开：后端没有按学生的逐任务明细端点，如实提供聚合视图
 *   抽屉 + 指向学情分析/任务页的入口，不编造逐任务数据。
 * - 抽屉内"查看诊断"（PRD-06 §15 #2）：学生授权后教师可见诊断摘要与逐条
 *   错误归因；未授权时后端 403 SHARE_NOT_GRANTED 是**预期业务结果**而非
 *   错误，展示"学生未授权"空态并说明学生可在个人中心开启，不弹错误提示。
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiRequestError, api } from "../../api/client";
import type { ClassDetail, StudentRow } from "../../api/types";
import {
  Button,
  Card,
  ConfirmDialog,
  DataTable,
  Drawer,
  EmptyState,
  ErrorState,
  Input,
  MasteryBadge,
  PageHeader,
  ProgressBar,
  Select,
  Spinner,
  StatusBadge,
  useToast,
  type Column,
} from "../../components";
import { errMsg, fmtDateTime, pct } from "./utils";

/* ------------------------------------------------ 诊断明细的页面本地类型
 * （api/types.ts 由并行代理维护，本页按 teacher.py student_diagnostics 与
 * diagnosis/rules.py 的错误条目结构自留一份） */
interface DiagnosticErrorRow {
  error_type: string;
  severity: string;
  user_value?: unknown;
  expected?: string;
  /** 规则中文名（rules.py RULE_NAMES） */
  rule?: string;
  cap_id?: string;
  suggestion?: string;
}

interface DiagnosticReportShape {
  errors?: DiagnosticErrorRow[];
  severity_counts?: Record<string, number>;
}

interface DiagnosticDetailRow {
  id: string;
  file_format: string | null;
  data_type: string | null;
  error_count: number;
  severity_counts: Record<string, number>;
  created_at: string;
  /** 授权后才附完整报告（report_json 展开），可能为 null */
  report?: DiagnosticReportShape | null;
}

/** 诊断查看的状态机：denied 与 error 分开——未授权是业务结果不是故障 */
type DiagState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "denied" }
  | { kind: "error"; message: string }
  | { kind: "ok"; items: DiagnosticDetailRow[] };

/** 任务完成状态筛选（客户端，基于 completion_rate 的真实分布） */
const COMPLETION_OPTIONS = [
  { value: "", label: "全部" },
  { value: "all_done", label: "已全部完成" },
  { value: "partial", label: "部分完成" },
  { value: "not_started", label: "尚未开始" },
];

function completionMatch(row: StudentRow, filter: string): boolean {
  if (filter === "all_done") return row.completion_rate === 1;
  if (filter === "partial") return row.completion_rate !== null && row.completion_rate < 1;
  if (filter === "not_started") return row.task_count === 0 || row.completion_rate === 0;
  return true;
}

/** 导出 CSV 的列定义（PRD-06 §10.2：仅聚合学情，不含诊断原文件） */
const CSV_HEADER = ["姓名", "邮箱", "任务数", "完成率", "平均掌握度", "最近活跃"];

function toCsv(rows: StudentRow[]): string {
  const escape = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  const lines = rows.map((r) =>
    [
      r.name,
      r.email,
      String(r.task_count),
      r.completion_rate === null ? "" : `${Math.round(r.completion_rate * 100)}%`,
      r.avg_mastery === null ? "" : `${Math.round(r.avg_mastery * 100)}%`,
      r.last_active ? fmtDateTime(r.last_active) : "",
    ]
      .map(escape)
      .join(","),
  );
  // BOM（\uFEFF）让 Excel 正确识别 UTF-8 中文，否则学生姓名会乱码
  return "﻿" + [CSV_HEADER.join(","), ...lines].join("\n");
}

export default function ClassDetailPage() {
  const { id = "" } = useParams();
  const toast = useToast();

  const [detail, setDetail] = useState<ClassDetail | null>(null);
  const [students, setStudents] = useState<StudentRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [studentsLoading, setStudentsLoading] = useState(false);

  // ---- 筛选：掌握度区间为"已应用"状态（点查询才发请求），完成状态即时本地过滤 ----
  const [minInput, setMinInput] = useState("");
  const [maxInput, setMaxInput] = useState("");
  const [appliedRange, setAppliedRange] = useState<{ min: string; max: string }>({
    min: "",
    max: "",
  });
  const [completionFilter, setCompletionFilter] = useState("");

  // ---- 邀请码 / 添加学生 / 学生抽屉 ----
  const [regenOpen, setRegenOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [enrolling, setEnrolling] = useState(false);
  const [activeStudent, setActiveStudent] = useState<StudentRow | null>(null);
  // ---- 抽屉内"查看诊断"（按需加载，不随抽屉打开自动请求——授权接口有
  // 三道闸，教师未必每次都想看诊断，避免无谓 403 刷审计/日志） ----
  const [diag, setDiag] = useState<DiagState>({ kind: "idle" });
  const [expandedReportId, setExpandedReportId] = useState<string | null>(null);

  /** 打开学生抽屉：同时重置上一位学生的诊断状态，避免串数据 */
  const openStudentDrawer = (row: StudentRow) => {
    setActiveStudent(row);
    setDiag({ kind: "idle" });
    setExpandedReportId(null);
  };

  /** 拉取当前学生的诊断摘要 + 报告（未授权 403 SHARE_NOT_GRANTED → denied 态） */
  const loadDiagnostics = async () => {
    if (!activeStudent) return;
    setDiag({ kind: "loading" });
    try {
      const res = await api.get<{ items: DiagnosticDetailRow[]; total: number; shared: boolean }>(
        `/api/teacher/classes/${id}/students/${activeStudent.id}/diagnostics`,
      );
      setDiag({ kind: "ok", items: res.items });
    } catch (err) {
      if (err instanceof ApiRequestError && err.code === "SHARE_NOT_GRANTED") {
        setDiag({ kind: "denied" });
      } else {
        setDiag({ kind: "error", message: errMsg(err, "诊断详情加载失败") });
      }
    }
  };

  const loadDetail = useCallback(
    async (signal?: AbortSignal) => {
      const res = await api.get<ClassDetail>(`/api/teacher/classes/${id}`, undefined, { signal });
      if (signal?.aborted) return;
      setDetail(res);
    },
    [id],
  );

  const loadStudents = useCallback(
    async (signal?: AbortSignal) => {
      setStudentsLoading(true);
      try {
        // 输入是 0-100 百分数，后端口径是 0..1 小数，换算在这里统一完成
        const min = appliedRange.min.trim() === "" ? undefined : Number(appliedRange.min) / 100;
        const max = appliedRange.max.trim() === "" ? undefined : Number(appliedRange.max) / 100;
        const res = await api.get<{ items: StudentRow[] }>(
          `/api/teacher/classes/${id}/students`,
          {
            mastery_min: Number.isFinite(min) ? min : undefined,
            mastery_max: Number.isFinite(max) ? max : undefined,
          },
          { signal },
        );
        if (signal?.aborted) return;
        setStudents(res.items);
      } catch (err) {
        if (!signal?.aborted) toast.error(errMsg(err, "学生列表加载失败"));
      } finally {
        if (!signal?.aborted) setStudentsLoading(false);
      }
    },
    [id, appliedRange, toast],
  );

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    void Promise.all([loadDetail(controller.signal), loadStudents(controller.signal)]).catch(
      (err) => {
        if (!controller.signal.aborted) setError(errMsg(err, "班级信息加载失败"));
      },
    );
    return () => controller.abort();
    // 首次加载后，掌握度筛选变化只刷新学生列表
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadStudents]);

  const regenerateInvite = async () => {
    try {
      const res = await api.post<{ id: string; invite_code: string }>(
        `/api/teacher/classes/${id}/invite`,
      );
      setDetail((d) => (d ? { ...d, invite_code: res.invite_code } : d));
      setRegenOpen(false);
      toast.success("邀请码已重新生成，旧码已失效");
    } catch (err) {
      toast.error(errMsg(err));
    }
  };

  const enroll = async () => {
    if (!email.trim()) return;
    setEnrolling(true);
    try {
      const res = await api.post<{ already_enrolled: boolean }>(
        `/api/teacher/classes/${id}/enroll`,
        { student_email: email.trim() },
      );
      // 后端幂等：已在班返回 already_enrolled，两种结果都要如实反馈
      if (res.already_enrolled) toast.info("该学生已在班级中");
      else toast.success("已添加学生");
      setEmail("");
      void loadStudents();
    } catch (err) {
      // 后端中文错误（如"未找到该学生账号，请确认学生已注册"）原样透出
      toast.error(errMsg(err));
    } finally {
      setEnrolling(false);
    }
  };

  const exportCsv = () => {
    if (!filtered.length) {
      toast.info("当前没有可导出的学生数据");
      return;
    }
    const blob = new Blob([toCsv(filtered)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${detail?.name ?? "班级"}-学情报表.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("报表已导出");
  };

  /** 掌握度区间过滤后的行再做完成状态本地过滤，才是最终展示集 */
  const filtered = useMemo(
    () => (students ?? []).filter((r) => completionMatch(r, completionFilter)),
    [students, completionFilter],
  );

  const columns: Column<StudentRow>[] = [
    { key: "name", title: "姓名" },
    { key: "email", title: "邮箱" },
    { key: "task_count", title: "学习任务数", width: "100px" },
    {
      key: "completion_rate",
      title: "完成率",
      width: "160px",
      render: (row) =>
        row.completion_rate === null ? (
          <span className="text-muted">暂无任务</span>
        ) : (
          <span className="flex items-center gap-2">
            <ProgressBar value={row.completion_rate} />
            <span className="text-sm text-secondary">{pct(row.completion_rate)}</span>
          </span>
        ),
    },
    {
      key: "avg_mastery",
      title: "平均掌握度",
      width: "150px",
      render: (row) => <MasteryBadge score={row.avg_mastery} />,
    },
    {
      key: "last_active",
      title: "最近活跃时间",
      width: "170px",
      render: (row) => fmtDateTime(row.last_active),
    },
    {
      key: "actions",
      title: "学习状态",
      width: "90px",
      render: (row) => (
        <Button variant="ghost" size="sm" onClick={() => openStudentDrawer(row)}>
          查看
        </Button>
      ),
    },
  ];

  // Keep detailed report content outside the compact row; the table only controls the aggregate action.
  const diagnosticColumns: Column<DiagnosticDetailRow>[] = [
    {
      key: "file_format",
      title: "文件格式",
      width: "10rem",
      render: (row) => row.file_format ?? "未知格式",
    },
    {
      key: "created_at",
      title: "时间",
      width: "11rem",
      render: (row) => <span className="text-sm text-muted">{fmtDateTime(row.created_at)}</span>,
    },
    {
      key: "error_count",
      title: "错误",
      width: "11rem",
      render: (row) => (
        <span className="flex items-center gap-2">
          {(row.severity_counts.major ?? 0) > 0 ? (
            <span className="badge badge-danger">严重 {row.severity_counts.major}</span>
          ) : null}
          {(row.severity_counts.minor ?? 0) > 0 ? (
            <span className="badge badge-warning">次要 {row.severity_counts.minor}</span>
          ) : null}
          <strong>{row.error_count}</strong>
        </span>
      ),
    },
    {
      key: "report",
      title: "报告",
      width: "8rem",
      render: (row) =>
        (row.report?.errors?.length ?? 0) > 0 ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setExpandedReportId((current) => (current === row.id ? null : row.id))}
          >
            {expandedReportId === row.id ? "收起" : "展开"}
          </Button>
        ) : (
          <span className="text-xs text-muted">无明细</span>
        ),
    },
  ];

  if (error && !detail) {
    return <ErrorState message={error} onRetry={() => void loadDetail()} />;
  }

  return (
    <div className="teacher-workbench-page teacher-class-detail-page">
      <PageHeader
        title={detail?.name ?? "班级详情"}
        sub={
          detail
            ? `创建于 ${fmtDateTime(detail.created_at)} · ${detail.student_count} 名学生`
            : undefined
        }
        actions={
          <Button variant="secondary" onClick={exportCsv} disabled={!students?.length}>
            导出报表
          </Button>
        }
      />

      {/* 班级信息：邀请码 + 重新生成（旧码立即失效，需二次确认） */}
      <div className="grid teacher-two-column mb-4">
        <Card title="邀请码">
          {detail ? (
            <div className="flex items-center gap-3 teacher-invite-row">
              <span
                className="font-mono"
                style={{ fontSize: "var(--font-size-xl)", fontWeight: 700 }}
              >
                {detail.invite_code}
              </span>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  void navigator.clipboard
                    .writeText(detail.invite_code)
                    .then(() => toast.success("邀请码已复制"))
                    .catch(() => toast.error("复制失败，请手动复制"));
                }}
              >
                复制
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setRegenOpen(true)}>
                重新生成
              </Button>
            </div>
          ) : null}
          <p className="text-sm text-secondary mt-2">
            分享给学生加入：学生在个人中心输入邀请码即可入班
          </p>
        </Card>

        {/* 邀请学生（邀请码之外的主动通道：按邮箱直接添加） */}
        <Card title="添加学生">
          <div className="flex items-center gap-2 teacher-enroll-row">
            <Input
              type="email"
              value={email}
              placeholder="学生注册邮箱，如 student@demo.bhzd"
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void enroll();
              }}
            />
            <Button onClick={() => void enroll()} loading={enrolling} disabled={!email.trim()}>
              添加
            </Button>
          </div>
          <p className="text-sm text-secondary mt-2">学生需已注册账号；重复添加不会重复入班</p>
        </Card>
      </div>

      {/* 筛选条：完成状态（本地）+ 掌握度区间（后端 query） */}
      <Card className="teacher-filter-surface mb-4">
        <div className="flex items-center gap-3" style={{ flexWrap: "wrap" }}>
          <Select
            options={COMPLETION_OPTIONS}
            value={completionFilter}
            onChange={(e) => setCompletionFilter(e.target.value)}
            aria-label="任务完成状态"
          />
          <div className="flex items-center gap-2">
            <span className="text-sm text-secondary">掌握度</span>
            <Input
              type="number"
              min={0}
              max={100}
              placeholder="最低 %"
              value={minInput}
              style={{ width: 100 }}
              onChange={(e) => setMinInput(e.target.value)}
            />
            <span className="text-muted">—</span>
            <Input
              type="number"
              min={0}
              max={100}
              placeholder="最高 %"
              value={maxInput}
              style={{ width: 100 }}
              onChange={(e) => setMaxInput(e.target.value)}
            />
            <Button
              variant="secondary"
              onClick={() => setAppliedRange({ min: minInput, max: maxInput })}
            >
              查询
            </Button>
          </div>
          <span className="text-xs text-muted">提示：掌握度区间不含暂无掌握度记录的学生</span>
        </div>
      </Card>

      {/* 学生列表 */}
      {/* Keep the table scroll viewport as the only border so dense class data reads as one surface. */}
      <Card
        title={`学生列表（${filtered.length} 人）`}
        padded={false}
        className="teacher-table-surface"
      >
        <DataTable
          ariaLabel="班级学生列表"
          columns={columns}
          rows={filtered}
          loading={studentsLoading && !students}
          empty="暂无符合条件的学生"
          wrapperClassName="table-wrap-borderless"
        />
      </Card>

      {/* 班级最近任务（真实字段，辅助判断班级学习状态） */}
      {detail && detail.recent_tasks.length > 0 ? (
        <Card title="最近任务" className="mt-4">
          <ul className="flex flex-col gap-2">
            {detail.recent_tasks.map((t) => (
              <li key={t.id} className="flex items-center justify-between">
                <span>{t.title}</span>
                <span className="flex items-center gap-3">
                  <span className="text-sm text-muted">
                    截止 {t.due_at ? fmtDateTime(t.due_at) : "未设置"}
                  </span>
                  <StatusBadge status={t.status} />
                </span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {/* 重新生成邀请码：旧码失效属不可逆后果，必须确认 */}
      <ConfirmDialog
        open={regenOpen}
        title="重新生成邀请码"
        description="重新生成后，旧邀请码将立即失效，尚未入班的学生需使用新码。确定继续吗？"
        confirmText="重新生成"
        onConfirm={regenerateInvite}
        onCancel={() => setRegenOpen(false)}
      />

      {/* 学生学习状态抽屉：后端无逐任务明细端点，如实展示聚合数据 + 引导入口 */}
      <Drawer
        open={activeStudent !== null}
        title={activeStudent ? `${activeStudent.name} 的学习状态` : ""}
        onClose={() => setActiveStudent(null)}
      >
        {activeStudent ? (
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <span className="text-secondary">学习任务数</span>
              <strong>{activeStudent.task_count}</strong>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-secondary">完成率</span>
              <strong>{pct(activeStudent.completion_rate)}</strong>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-secondary">平均掌握度</span>
              <MasteryBadge score={activeStudent.avg_mastery} />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-secondary">最近活跃</span>
              <span>{fmtDateTime(activeStudent.last_active)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-secondary">入班时间</span>
              <span>{fmtDateTime(activeStudent.joined_at)}</span>
            </div>

            {/* 诊断详情（PRD-06 §15 #2）：点击查看，授权与否如实展示 */}
            <div
              className="mt-2"
              style={{
                borderTop: "1px solid var(--color-border)",
                paddingTop: "var(--space-3)",
              }}
            >
              <div className="flex items-center justify-between mb-2">
                <strong>诊断详情</strong>
                {diag.kind !== "loading" ? (
                  <Button variant="secondary" size="sm" onClick={() => void loadDiagnostics()}>
                    {diag.kind === "ok" ? "刷新诊断" : "查看诊断"}
                  </Button>
                ) : null}
              </div>

              {diag.kind === "loading" ? (
                <div className="loading-block">
                  <Spinner size={16} /> 加载中…
                </div>
              ) : null}

              {diag.kind === "denied" ? (
                <EmptyState
                  title="学生未授权"
                  hint="该学生尚未授权教师查看诊断详情，学生可在个人中心开启「授权教师查看诊断」后重试"
                />
              ) : null}

              {diag.kind === "error" ? (
                <ErrorState message={diag.message} onRetry={() => void loadDiagnostics()} />
              ) : null}

              {diag.kind === "ok" ? (
                diag.items.length === 0 ? (
                  <EmptyState title="暂无诊断记录" />
                ) : (
                  <>
                    <DataTable
                      ariaLabel="学生诊断记录"
                      columns={diagnosticColumns}
                      rows={diag.items}
                      rowKey={(row) => row.id}
                    />

                    {/* 展开的报告：逐条错误归因（严重度徽章 + 规则 + 修改建议） */}
                    {expandedReportId
                      ? diag.items
                          .filter((d) => d.id === expandedReportId)
                          .map((d) => (
                            <ul key={d.id} className="flex flex-col gap-2 mt-2">
                              {(d.report?.errors ?? []).map((e, i) => (
                                <li
                                  key={i}
                                  style={{
                                    borderLeft: "3px solid var(--color-border)",
                                    paddingLeft: "var(--space-3)",
                                  }}
                                >
                                  <div className="flex items-center gap-2">
                                    <span
                                      className={`badge ${e.severity === "major" ? "badge-danger" : "badge-warning"}`}
                                    >
                                      {e.severity === "major" ? "严重" : "次要"}
                                    </span>
                                    <span className="font-mono text-sm">{e.error_type}</span>
                                  </div>
                                  {e.rule ? (
                                    <div className="text-sm mt-2">规则：{e.rule}</div>
                                  ) : null}
                                  {e.suggestion ? (
                                    <div className="text-sm text-secondary mt-2">
                                      建议：{e.suggestion}
                                    </div>
                                  ) : null}
                                </li>
                              ))}
                            </ul>
                          ))
                      : null}
                  </>
                )
              ) : null}
            </div>

            <p className="text-sm text-secondary mt-3">
              逐任务学习明细暂未在教师端开放，可在
              <Link to="/teacher/analytics"> 学情分析 </Link>
              查看班级维度数据，或在 <Link to="/teacher/tasks">任务发布</Link> 页跟进任务进度。
            </p>
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}
