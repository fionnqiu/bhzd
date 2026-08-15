/**
 * 学习任务详情页（PRD-01 §6.2 + v3.0 §7.5.2）。
 *
 * 闭环：开始（not_started→in_progress）→ 练习区作答 → 提交（确定性评分，
 * 返回 score/feedback/mastery_preview，不落掌握度）→ 反馈区展示逐项对错
 * + 掌握度变化预览 → 学生「确认更新掌握度」→ apply-mastery 落库
 * （PRD-06 §8.3：预览先于写入，学生确认才生效；按 attempt 幂等）。
 *
 * 关键决策（为什么）：
 * - 练习题渲染对 practice_json 做宽容解析（questions/samples/checklist 任一
 *   存在即渲染）；无练习题时按 rubric 键出题但**绝不展示 expected**——
 *   那是评分答案，提前展示会破坏练习有效性。
 * - 能力 chips 的掌握度取 /api/profile/mastery 的统一能力记录
 *   通用记录（PRD-06 §8.4 冲突口径的展示侧实现）。
 * - mastery_updated 埋点由后端 apply-mastery 端点上报，前端不重复发。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type {
  ApplyMasteryResponse,
  MasteryRecord,
  Paginated,
  SubmitTaskResponse,
  TaskDetail,
  TaskSummary,
} from "../../api/types";
import {
  Button,
  Card,
  DataTable,
  EmptyState,
  ErrorState,
  Input,
  MasteryBadge,
  PageHeader,
  ProgressBar,
  Spinner,
  StatusBadge,
  Tag,
  Textarea,
  useToast,
  type Column,
} from "../../components";
import {
  dataTypeLabel,
  errMsg,
  formatDateTime,
  MasteryPreviewList,
  taskSourceLabel,
  useCapNames,
} from "./shared";

/* ---------------------------------------------------------------- 练习区解析 */

interface PracticeQuestion {
  key: string;
  prompt: string;
  hint?: string;
}

/**
 * 从 practice_json 提取练习题；结构随任务来源（Agent/预设/教师）而不同，
 * 做宽容解析：questions: [{key, prompt|question|title, hint?}]。
 * 无练习题定义时按 rubric 键出题（不展示 expected，见文件头注释）。
 */
function extractQuestions(detail: TaskDetail): PracticeQuestion[] {
  const practice = detail.practice;
  const rawQuestions = practice?.["questions"];
  if (Array.isArray(rawQuestions)) {
    return rawQuestions.map((q, index) => {
      const item = (q ?? {}) as Record<string, unknown>;
      return {
        key: String(item.key ?? `q${index + 1}`),
        prompt: String(item.prompt ?? item.question ?? item.title ?? `题目 ${index + 1}`),
        hint: item.hint == null ? undefined : String(item.hint),
      };
    });
  }
  // During a rolling backend upgrade, an older API can still expose the
  // historical object-shaped rubric. Treat it as no fallback questions until
  // the server's student-safe array DTO is available instead of blanking the page.
  const rubric = Array.isArray(detail.rubric) ? detail.rubric : [];
  return rubric.map((item) => ({
    key: item.key,
    prompt: `请作答：${item.key}`,
  }));
}

/** 自检清单（practice.checklist: string[]；勾选状态仅本地，不参与评分） */
function extractChecklist(detail: TaskDetail): string[] {
  const raw = detail.practice?.["checklist"];
  return Array.isArray(raw) ? raw.map(String) : [];
}

/** 标注样本（practice.samples：对象数组原样 JSON 预览，供学生对照作答） */
function extractSamples(detail: TaskDetail): unknown[] {
  const raw = detail.practice?.["samples"];
  return Array.isArray(raw) ? raw : [];
}

/**
 * 将详情中的持久化提交还原为提交接口形状，避免刷新后丢失反馈和确认入口。
 * 只有服务端已完成评分的尝试会进入该载荷，评分答案不会随 rubric 预先下发。
 */
function feedbackFromLatestAttempt(detail: TaskDetail): SubmitTaskResponse | null {
  const attempt = detail.latest_attempt;
  if (!attempt) return null;
  return {
    attempt_id: attempt.id,
    score: attempt.score ?? 0,
    feedback: attempt.feedback,
    mastery_preview: attempt.mastery_preview,
    status: detail.status,
  };
}

/** 持久化答案允许数字等输入类型，表单统一还原成字符串以保持受控输入稳定。 */
function answersFromLatestAttempt(detail: TaskDetail): Record<string, string> {
  const answers = detail.latest_attempt?.answers ?? {};
  return Object.fromEntries(
    Object.entries(answers).map(([key, value]) => [key, value == null ? "" : String(value)]),
  );
}

/**
 * Keep task-detail return links inside the SPA. Navigation state is supplied by
 * another page, so reject protocol-relative/external values before handing it
 * to React Router and retain the task list as the fallback destination.
 */
function safeTaskReturnPath(value: unknown): string {
  if (
    typeof value !== "string" ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    value.includes("\0")
  ) {
    return "/tasks";
  }
  return value;
}

/**
 * Normalize responses from older task-detail deployments at the API boundary.
 *
 * The learning-content migration adds array fields to the DTO, but users can
 * still have a page open against a backend that has not reloaded yet (or have
 * a historical fixture without those keys). Supplying stable empty arrays here
 * keeps the new content surface additive and prevents a legacy response from
 * blanking the whole task page.
 */
function normalizeTaskDetail(value: TaskDetail): TaskDetail {
  const raw = value as TaskDetail & { linked?: Partial<TaskDetail["linked"]> };
  const linked = raw.linked ?? {};
  return {
    ...raw,
    content_status: raw.content_status ?? "none",
    cap_ids: Array.isArray(raw.cap_ids) ? raw.cap_ids : [],
    caps: Array.isArray(raw.caps) ? raw.caps : [],
    steps: Array.isArray(raw.steps) ? raw.steps : [],
    resources: Array.isArray(raw.resources) ? raw.resources : [],
    attempts: Array.isArray(raw.attempts) ? raw.attempts : [],
    linked: {
      certificates: Array.isArray(linked.certificates) ? linked.certificates : [],
      knowledge: Array.isArray(linked.knowledge) ? linked.knowledge : [],
      graph_resources: Array.isArray(linked.graph_resources) ? linked.graph_resources : [],
    },
    knowledge_points: Array.isArray(raw.knowledge_points) ? raw.knowledge_points : [],
    exercises: Array.isArray(raw.exercises) ? raw.exercises : [],
  };
}

/** Card keeps its existing visual header while this page exposes a real section hierarchy. */
function TaskSectionTitle({ children }: { children: string }) {
  return <h2 className="task-detail-section-title">{children}</h2>;
}

/* ---------------------------------------------------------------- 页面 */

export default function TaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const toast = useToast();
  const capNames = useCapNames();
  const returnTo = safeTaskReturnPath((location.state as { returnTo?: unknown } | null)?.returnTo);

  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // cap → score，用于能力 chips 的 MasteryBadge。
  const [masteryMap, setMasteryMap] = useState<Map<string, number>>(new Map());

  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<SubmitTaskResponse | null>(null);
  const [applied, setApplied] = useState(false);
  const [applying, setApplying] = useState(false);
  const [starting, setStarting] = useState(false);
  const [exerciseAnswers, setExerciseAnswers] = useState<Record<string, string>>({});
  const [exerciseSubmitting, setExerciseSubmitting] = useState<string | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!id) return;
      setLoading(true);
      setError(null);
      try {
        const res = await api.get<TaskDetail>(`/api/tasks/${id}`, undefined, { signal });
        if (signal?.aborted) return;
        // Hydrate the persisted attempt in the same state turn as the detail
        // response. A follow-up effect briefly rendered empty controlled inputs
        // and could overwrite an in-page edit after unrelated detail changes.
        const normalized = normalizeTaskDetail(res);
        const restored = feedbackFromLatestAttempt(normalized);
        setDetail(normalized);
        setAnswers(restored ? answersFromLatestAttempt(normalized) : {});
        setFeedback(restored);
        setApplied(res.latest_attempt?.mastery_applied ?? false);
      } catch (err) {
        if (!signal?.aborted) setError(errMsg(err));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [id],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  // 掌握度记录：能力 chips 着色用；失败降级空映射（chips 显示"暂无数据"）
  useEffect(() => {
    const controller = new AbortController();
    api
      .get<Paginated<MasteryRecord>>("/api/profile/mastery", undefined, {
        signal: controller.signal,
      })
      .then((res) => {
        if (controller.signal.aborted) return;
        setMasteryMap(new Map(res.items.map((r) => [r.cap_id, r.score])));
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!id || detail?.content_status !== "generating") return;
    const timer = window.setInterval(() => {
      void api
        .get<TaskDetail>(`/api/tasks/${id}`)
        .then((next) => setDetail(normalizeTaskDetail(next)))
        .catch(() => {});
    }, 2000);
    return () => {
      window.clearInterval(timer);
    };
  }, [detail?.content_status, id]);

  const questions = useMemo(() => (detail ? extractQuestions(detail) : []), [detail]);
  const checklist = useMemo(() => (detail ? extractChecklist(detail) : []), [detail]);
  const samples = useMemo(() => (detail ? extractSamples(detail) : []), [detail]);

  const generateContent = async () => {
    if (!detail) return;
    try {
      await api.post("/api/tasks/start-learning", {
        cap_node_id: detail.cap_ids[0] ?? detail.id,
        generate_content: true,
        // An explicit ID prevents a duplicate capability task from receiving
        // this detail page's generation request during retries.
        task_id: detail.id,
      });
      const refreshed = await api.get<TaskDetail>(`/api/tasks/${detail.id}`);
      setDetail(normalizeTaskDetail(refreshed));
    } catch (err) {
      toast.error(errMsg(err));
    }
  };

  const submitGeneratedExercise = async (exerciseId: string) => {
    const answer = exerciseAnswers[exerciseId]?.trim();
    if (!answer) return;
    setExerciseSubmitting(exerciseId);
    try {
      await api.post(`/api/tasks/${detail?.id}/exercises/${exerciseId}/submit`, { answer });
      const refreshed = await api.get<TaskDetail>(`/api/tasks/${detail?.id}`);
      setDetail(normalizeTaskDetail(refreshed));
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setExerciseSubmitting(null);
    }
  };

  // Feedback and attempt rows stay single-line; the shared table viewport handles narrow screens.
  const feedbackColumns: Column<SubmitTaskResponse["feedback"][number]>[] = [
    { key: "key", title: "题目", width: "10rem" },
    {
      key: "expected",
      title: "期望值",
      width: "12rem",
      render: (item) => (item.expected == null ? "—" : String(item.expected)),
    },
    {
      key: "got",
      title: "你的答案",
      width: "12rem",
      render: (item) => (item.got == null || item.got === "" ? "（未作答）" : String(item.got)),
    },
    {
      key: "result",
      title: "结果",
      width: "8rem",
      render: (item) => (
        <span className={`badge ${item.ok ? "badge-success" : "badge-danger"}`}>
          {item.ok ? "正确" : "待改进"}
        </span>
      ),
    },
    { key: "hint", title: "提示", width: "16rem" },
  ];

  const attemptColumns: Column<TaskDetail["attempts"][number]>[] = [
    {
      key: "attempt_number",
      title: "次数",
      width: "8rem",
      render: (attempt) => `第 ${attempt.attempt_number} 次`,
    },
    {
      key: "score",
      title: "得分",
      width: "8rem",
      render: (attempt) => (attempt.score == null ? "—" : `${Math.round(attempt.score * 100)} 分`),
    },
    {
      key: "mastery_applied",
      title: "掌握度",
      width: "8rem",
      render: (attempt) => (attempt.mastery_applied ? "已更新" : "未确认"),
    },
    {
      key: "created_at",
      title: "时间",
      width: "11rem",
      render: (attempt) => formatDateTime(attempt.created_at),
    },
  ];

  /** 能力掌握度查询使用统一能力记录。 */
  const capScore = (capId: string): number | null => {
    return masteryMap.get(capId) ?? null;
  };

  /** 开始/继续任务（not_started|paused → in_progress） */
  const startTask = async () => {
    if (!id) return;
    setStarting(true);
    try {
      const res = await api.post<TaskSummary>(`/api/tasks/${id}/start`);
      setDetail((prev) => (prev ? { ...prev, status: res.status, progress: res.progress } : prev));
      toast.success("任务已开始，完成练习后提交答案");
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setStarting(false);
    }
  };

  /** 提交答案 → 确定性评分反馈（掌握度只给预览不落库） */
  const submitAnswers = async () => {
    if (!id) return;
    setSubmitting(true);
    try {
      const res = await api.post<SubmitTaskResponse>(`/api/tasks/${id}/submit`, { answers });
      setFeedback(res);
      setApplied(false);
      setDetail((prev) => {
        if (!prev) return prev;
        const createdAt = new Date().toISOString();
        const attemptNumber =
          Math.max(0, ...prev.attempts.map((attempt) => attempt.attempt_number)) + 1;
        // Keep the local DTO aligned with the reload response so the feedback title,
        // confirmation button, and attempt table do not wait for a full page reload.
        const latestAttempt = {
          id: res.attempt_id,
          attempt_number: attemptNumber,
          score: res.score,
          mastery_applied: false,
          created_at: createdAt,
          answers: { ...answers },
          feedback: res.feedback,
          mastery_preview: res.mastery_preview,
        };
        return {
          ...prev,
          status: res.status,
          progress: res.status === "submitted" ? 0.9 : prev.progress,
          latest_score: res.score,
          latest_attempt: latestAttempt,
          attempts: [
            {
              id: latestAttempt.id,
              attempt_number: latestAttempt.attempt_number,
              score: latestAttempt.score,
              mastery_applied: latestAttempt.mastery_applied,
              created_at: latestAttempt.created_at,
            },
            ...prev.attempts,
          ],
        };
      });
      toast.success(`已提交，得分 ${Math.round(res.score * 100)} 分`);
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setSubmitting(false);
    }
  };

  /** 学生确认后把掌握度预览落库（按 attempt 幂等，重复点击不重复加分） */
  const applyMastery = async () => {
    if (!id || !feedback) return;
    const countsTowardMastery = detail?.counts_toward_mastery ?? false;
    setApplying(true);
    try {
      const res = await api.post<ApplyMasteryResponse>(`/api/tasks/${id}/apply-mastery`, {
        attempt_id: feedback.attempt_id,
      });
      toast.success(
        res.already_applied
          ? "掌握度此前已更新过"
          : countsTowardMastery
            ? "掌握度已更新"
            : "任务已确认",
      );
      setApplied(true);
      setMasteryMap((prev) => {
        const next = new Map(prev);
        for (const change of res.applied) {
          if (change.new_score != null) {
            next.set(change.cap_id, change.new_score);
          }
        }
        return next;
      });
      setDetail((prev) => {
        if (!prev) return prev;
        // The confirmation response is authoritative. Updating only its attempt
        // keeps the completed state usable even if a later background refresh fails.
        const latestAttempt = prev.latest_attempt;
        const confirmedLatestAttempt =
          latestAttempt?.id === feedback.attempt_id
            ? {
                ...latestAttempt,
                mastery_applied: true,
                mastery_preview: [],
              }
            : latestAttempt;
        return {
          ...prev,
          status: res.status,
          progress: res.status === "completed" ? 1 : prev.progress,
          latest_attempt: confirmedLatestAttempt,
          attempts: prev.attempts.map((attempt) =>
            attempt.id === feedback.attempt_id ? { ...attempt, mastery_applied: true } : attempt,
          ),
        };
      });
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setApplying(false);
    }
  };

  if (loading) {
    return (
      <div className="loading-block">
        <Spinner large /> 正在加载任务…
      </div>
    );
  }
  if (error || !detail) {
    return <ErrorState message={error ?? "任务不存在"} onRetry={load} />;
  }

  const canPractice = detail.status === "in_progress" || detail.status === "submitted";
  const scoreTone = (score: number): "success" | "warning" | "danger" =>
    score >= 0.8 ? "success" : score >= 0.4 ? "warning" : "danger";
  const taskProgressTone: "primary" | "success" | "warning" =
    detail.status === "completed" ? "success" : detail.status === "paused" ? "warning" : "primary";
  const practiceStatusNote =
    detail.status === "submitted"
      ? "本次作答已提交。你可以核对反馈后确认完成，也可以修改答案后再次提交。"
      : detail.status === "completed"
        ? "任务已完成，已保留最近一次作答与反馈供回顾。"
        : null;

  return (
    <div>
      <PageHeader
        title={detail.title}
        sub={detail.goal ?? undefined}
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            {/* Keep the originating task-list filters available without requiring a long-page scroll. */}
            <Link to={returnTo} className="btn btn-ghost btn-sm">
              返回任务列表
            </Link>
            {detail.status === "not_started" || detail.status === "paused" ? (
              <Button loading={starting} onClick={startTask}>
                {detail.status === "paused" ? "继续任务" : "开始任务"}
              </Button>
            ) : null}
          </div>
        }
      />

      {/* 任务概览（名称、目标、关联岗位与证书、版本）。 */}
      <Card title={<TaskSectionTitle>任务概览</TaskSectionTitle>} className="mb-4">
        <div className="flex flex-col gap-3">
          <div className="task-detail-meta flex items-center gap-2 flex-wrap">
            <StatusBadge status={detail.status} />
            <span className="text-xs text-muted">来源</span>
            <Tag>{taskSourceLabel(detail.source)}</Tag>
            {detail.source === "teacher" ? (
              <span className="badge badge-warning" aria-label="由教师发布的任务">
                教师任务
              </span>
            ) : null}
            <Tag>{dataTypeLabel(detail.data_type)}</Tag>
            <Tag>{detail.counts_toward_mastery ? "计入掌握度" : "不计入掌握度"}</Tag>
            <span className="text-xs text-muted">版本 v{detail.version}</span>
            <span className="text-xs text-secondary">
              截止：{detail.due_at ? formatDateTime(detail.due_at) : "未设置"}
            </span>
          </div>
          <div
            className="task-detail-progress flex flex-col gap-2"
            role="group"
            aria-label="任务学习进度"
          >
            <div className="task-detail-progress-heading flex items-center justify-between gap-2">
              <span className="text-sm text-secondary">学习进度</span>
              <strong className="text-sm">{Math.round(detail.progress * 100)}%</strong>
            </div>
            <ProgressBar value={detail.progress} tone={taskProgressTone} />
            <div className="flex items-center gap-3 flex-wrap text-xs text-muted">
              <span>创建于 {formatDateTime(detail.created_at)}</span>
              <span>最近更新 {formatDateTime(detail.updated_at)}</span>
            </div>
          </div>
          {detail.caps.length > 0 ? (
            <div className="flex flex-col gap-2">
              <span className="text-sm text-secondary">关联能力</span>
              {detail.caps.map((cap) => (
                <span key={cap.cap_id} className="flex items-center justify-between gap-2">
                  <Link to={`/graph?node=${cap.cap_id}`} className="text-sm">
                    {cap.cap_name}
                  </Link>
                  <MasteryBadge score={capScore(cap.cap_id)} />
                </span>
              ))}
            </div>
          ) : null}
          {detail.linked.certificates.length > 0 ? (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm text-secondary">关联证书</span>
              {detail.linked.certificates.map((cert) => (
                <Tag key={cert.id}>{cert.name}</Tag>
              ))}
            </div>
          ) : null}
          {detail.linked.knowledge.length > 0 ? (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm text-secondary">关联岗位/知识</span>
              {detail.linked.knowledge.map((kng) => (
                <Tag key={kng.id}>{kng.name}</Tag>
              ))}
            </div>
          ) : null}
          {detail.linked.graph_resources.length > 0 ? (
            <div className="flex items-center gap-2 flex-wrap">
              {/* These tags are graph reference aids, not substitutes for task resources. */}
              <span className="text-sm text-secondary">图谱参考资源</span>
              {detail.linked.graph_resources.map((resource) => (
                <Tag key={resource.id}>{resource.name}</Tag>
              ))}
            </div>
          ) : null}
        </div>
      </Card>

      {/* Keep generated knowledge points as the only learning-content section; exercises live in the practice area below. */}
      <Card title={<TaskSectionTitle>学习内容</TaskSectionTitle>} className="mb-4">
        {detail.content_status === "generating" ? (
          <div className="flex items-center gap-2 text-sm text-muted" role="status">
            <Spinner /> 正在生成学习内容，请稍候…
          </div>
        ) : detail.content_status === "failed" ? (
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-danger">学习内容暂时不可用，请稍后重试。</p>
            <Button size="sm" variant="secondary" onClick={() => void generateContent()}>
              重试生成
            </Button>
          </div>
        ) : detail.content_status === "none" ? (
          // Older task rows are queued by the detail endpoint as they are
          // first opened. Keep this fallback passive so students never need
          // to discover or press a second generation button.
          <div className="flex items-center gap-2 text-sm text-muted" role="status">
            <Spinner /> 学习内容已自动排队，正在准备中，请稍候…
          </div>
        ) : (
          detail.knowledge_points.length > 0 ? (
            <div>
              <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                知识点
              </h3>
              <ol className="flex flex-col gap-3">
                {detail.knowledge_points.map((point, index) => (
                  <li key={point.id} className="card-padded">
                    <strong>
                      {index + 1}. {point.title}
                    </strong>
                    <p className="text-sm text-secondary mt-2" style={{ whiteSpace: "pre-wrap" }}>
                      {point.content}
                    </p>
                  </li>
                ))}
              </ol>
            </div>
          ) : (
            <EmptyState title="暂无知识点" />
          )
        )}
      </Card>

      {/* 操作步骤（含注意事项/常见错误，v3.0 §7.5.2） */}
      {detail.steps.length > 0 ? (
        <Card title={<TaskSectionTitle>操作步骤</TaskSectionTitle>} className="mb-4">
          <ol className="flex flex-col gap-4">
            {detail.steps.map((step, index) => (
              <li key={index}>
                <div className="flex items-center gap-2">
                  <span className="badge badge-primary">{index + 1}</span>
                  <strong className="text-sm">{step.title}</strong>
                </div>
                {step.description ? (
                  <p className="text-sm text-secondary mt-2">{step.description}</p>
                ) : null}
                {step.notes ? (
                  <p className="text-xs mt-2" style={{ color: "var(--color-warning)" }}>
                    注意事项：{step.notes}
                  </p>
                ) : null}
                {step.common_errors ? (
                  <p className="text-xs mt-2" style={{ color: "var(--color-danger)" }}>
                    常见错误：{step.common_errors}
                  </p>
                ) : null}
              </li>
            ))}
          </ol>
        </Card>
      ) : null}

      {/* 练习区：样本对照 + 作答 + 自检清单 + 提交 */}
      <Card title={<TaskSectionTitle>练习区</TaskSectionTitle>} className="mb-4">
        <div className="flex flex-col gap-4">
          {practiceStatusNote ? (
            <p className="task-detail-status-note" role="status">
              {practiceStatusNote}
            </p>
          ) : null}
          {samples.length > 0 ? (
            <div>
              <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                标注样本
              </h3>
              {samples.map((sample, index) => (
                <pre
                  key={index}
                  className="font-mono text-xs card-padded card mb-2"
                  style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}
                >
                  {typeof sample === "string" ? sample : JSON.stringify(sample, null, 2)}
                </pre>
              ))}
            </div>
          ) : null}
          {/* AI-generated exercises share the same practice surface as legacy task questions. */}
          {detail.exercises.length > 0 ? (
            <div>
              <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                AI 练习
              </h3>
              <div className="flex flex-col gap-4">
                {detail.exercises.map((exercise, index) => (
                  <div key={exercise.id} className="card-padded">
                    <p className="text-sm">
                      <strong>
                        {index + 1}. {exercise.question}
                      </strong>
                    </p>
                    {exercise.options?.length ? (
                      <ul className="text-sm text-secondary mt-2">
                        {exercise.options.map((option) => (
                          <li key={option}>{option}</li>
                        ))}
                      </ul>
                    ) : null}
                    <Textarea
                      aria-label={`AI 练习 ${index + 1} 答案`}
                      value={exerciseAnswers[exercise.id] ?? ""}
                      disabled={!canPractice}
                      onChange={(event) =>
                        setExerciseAnswers((previous) => ({
                          ...previous,
                          [exercise.id]: event.target.value,
                        }))
                      }
                    />
                    <Button
                      size="sm"
                      className="mt-2"
                      loading={exerciseSubmitting === exercise.id}
                      disabled={!canPractice || !exerciseAnswers[exercise.id]?.trim()}
                      onClick={() => void submitGeneratedExercise(exercise.id)}
                    >
                      提交 AI 练习
                    </Button>
                    {exercise.submission?.grade_status === "done" ? (
                      <p className="text-sm mt-2" role="status">
                        得分：{exercise.submission.score}/100 {exercise.submission.feedback}
                      </p>
                    ) : null}
                    {exercise.submission?.grade_status === "failed" ? (
                      <p className="text-sm text-warning mt-2" role="status">
                        AI 评阅暂不可用，请稍后重试。
                      </p>
                    ) : null}
                    {exercise.submission &&
                    ["pending", "grading"].includes(exercise.submission.grade_status) ? (
                      <p className="text-sm text-muted mt-2" role="status">
                        正在评阅…
                      </p>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {questions.length === 0 && detail.exercises.length === 0 ? (
            <p className="text-sm text-secondary">
              该任务没有预设练习题，完成学习后可直接提交，系统将按完成情况评分。
            </p>
          ) : (
            questions.map((question, index) => {
              const inputId = `task-answer-${detail.id}-${index}`;
              const hintId = `${inputId}-hint`;
              return (
                <div key={`${question.key}-${index}`}>
                  <label className="field-label" htmlFor={inputId}>
                    {question.prompt}
                  </label>
                  {question.hint ? (
                    <p id={hintId} className="field-hint mb-2">
                      {question.hint}
                    </p>
                  ) : null}
                  {question.prompt.length > 40 ? (
                    <Textarea
                      id={inputId}
                      aria-describedby={question.hint ? hintId : undefined}
                      value={answers[question.key] ?? ""}
                      disabled={!canPractice}
                      onChange={(e) =>
                        setAnswers((prev) => ({ ...prev, [question.key]: e.target.value }))
                      }
                    />
                  ) : (
                    <Input
                      id={inputId}
                      aria-describedby={question.hint ? hintId : undefined}
                      value={answers[question.key] ?? ""}
                      disabled={!canPractice}
                      onChange={(e) =>
                        setAnswers((prev) => ({ ...prev, [question.key]: e.target.value }))
                      }
                    />
                  )}
                </div>
              );
            })
          )}
          {checklist.length > 0 ? (
            <div>
              <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                自检清单
              </h3>
              <div className="flex flex-col gap-2">
                {checklist.map((item, index) => (
                  <label
                    key={`${item}-${index}`}
                    className="task-detail-checklist-item flex items-center gap-2 text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={checks[item] ?? false}
                      disabled={!canPractice}
                      onChange={(e) => setChecks((prev) => ({ ...prev, [item]: e.target.checked }))}
                    />
                    {item}
                  </label>
                ))}
              </div>
            </div>
          ) : null}
          {questions.length > 0 || checklist.length > 0 ? (
            <div>
              <Button loading={submitting} disabled={!canPractice} onClick={submitAnswers}>
                {detail.status === "submitted" ? "重新提交" : "提交答案"}
              </Button>
            </div>
          ) : null}
        </div>
      </Card>

      {/* 反馈区：得分 + 逐项反馈 + 掌握度预览（提交后出现） */}
      {feedback ? (
        <Card
          title={
            <TaskSectionTitle>
              {detail.latest_attempt?.id === feedback.attempt_id ? "最近提交反馈" : "本次提交反馈"}
            </TaskSectionTitle>
          }
          className="mb-4"
        >
          <div className="flex flex-col gap-4">
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-secondary">本次得分</span>
                <strong>{Math.round(feedback.score * 100)} 分</strong>
              </div>
              <ProgressBar value={feedback.score} tone={scoreTone(feedback.score)} />
            </div>
            {feedback.feedback.length > 0 ? (
              <DataTable
                ariaLabel="任务逐项反馈"
                columns={feedbackColumns}
                rows={feedback.feedback}
                rowKey={(item) => item.key}
              />
            ) : null}
            <div>
              <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                掌握度变化预览
              </h3>
              <MasteryPreviewList changes={feedback.mastery_preview} capNames={capNames} />
              <div className="mt-3">
                <Button
                  variant="secondary"
                  loading={applying}
                  disabled={applied || detail.status !== "submitted"}
                  onClick={applyMastery}
                >
                  {applied
                    ? detail.counts_toward_mastery
                      ? "掌握度已更新"
                      : "任务已确认"
                    : feedback.mastery_preview.length > 0
                      ? "确认更新掌握度"
                      : "确认完成任务"}
                </Button>
              </div>
            </div>
          </div>
        </Card>
      ) : null}

      {/* 提交历史 */}
      {detail.attempts.length > 0 ? (
        <Card title={<TaskSectionTitle>提交记录</TaskSectionTitle>} className="mb-4">
          <DataTable
            ariaLabel="任务提交记录"
            columns={attemptColumns}
            rows={detail.attempts}
            rowKey={(attempt) => attempt.id}
          />
        </Card>
      ) : null}

      {/* 下一步推荐：回图谱看前置、回预设继续路径（PRD-01 §6.2 反馈区） */}
      <Card title={<TaskSectionTitle>下一步推荐</TaskSectionTitle>}>
        <div className="flex items-center gap-2 flex-wrap">
          {detail.caps[0] ? (
            <Link to={`/graph?node=${detail.caps[0].cap_id}`} className="btn btn-secondary btn-sm">
              在图谱中查看「{detail.caps[0].cap_name}」
            </Link>
          ) : null}
          <Link to="/presets" className="btn btn-secondary btn-sm">
            继续预设学习
          </Link>
          <Link to={returnTo} className="btn btn-ghost btn-sm">
            返回任务列表
          </Link>
        </div>
      </Card>
    </div>
  );
}
