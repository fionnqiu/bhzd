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
 * - 能力 chips 的掌握度取 /api/profile/mastery：任务场景记录优先，缺省回退
 *   通用记录（PRD-06 §8.4 冲突口径的展示侧实现）。
 * - mastery_updated 埋点由后端 apply-mastery 端点上报，前端不重复发。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type {
  ApplyMasteryResponse,
  Citation,
  MasteryRecord,
  Paginated,
  SubmitTaskResponse,
  TaskDetail,
  TaskSummary,
} from "../../api/types";
import {
  Button,
  Card,
  CitationCard,
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
import { useScenario } from "../../app/ScenarioContext";
import {
  capNameOf,
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
  return (detail.rubric ?? []).map((item) => ({
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

/** 学习材料类型中文名（resources_json.type 各来源取值不一，兜底原样展示） */
const RESOURCE_TYPE_LABELS: Record<string, string> = {
  teaching_unit: "教学单元",
  micro_course: "微课",
  rag_citation: "RAG 引用",
  document: "规范文档",
  example: "示例案例",
};

function resourceTypeLabel(type: string): string {
  return RESOURCE_TYPE_LABELS[type] ?? type;
}

/* ---------------------------------------------------------------- 页面 */

export default function TaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();
  const { scenarios } = useScenario();
  const capNames = useCapNames();

  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // cap|scenario → score，用于能力 chips 的 MasteryBadge（口径见文件头注释）
  const [masteryMap, setMasteryMap] = useState<Map<string, number>>(new Map());

  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<SubmitTaskResponse | null>(null);
  const [applied, setApplied] = useState(false);
  const [applying, setApplying] = useState(false);
  const [starting, setStarting] = useState(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<TaskDetail>(`/api/tasks/${id}`, undefined, { signal });
      if (signal?.aborted) return;
      setDetail(res);
    } catch (err) {
      if (!signal?.aborted) setError(errMsg(err));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  // 掌握度记录：能力 chips 着色用；失败降级空映射（chips 显示"暂无数据"）
  useEffect(() => {
    const controller = new AbortController();
    api
      .get<Paginated<MasteryRecord>>("/api/profile/mastery", undefined, { signal: controller.signal })
      .then((res) => {
        if (controller.signal.aborted) return;
        setMasteryMap(
          new Map(res.items.map((r) => [`${r.cap_id}|${r.scenario_id}`, r.score])),
        );
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);

  const questions = useMemo(() => (detail ? extractQuestions(detail) : []), [detail]);
  const checklist = useMemo(() => (detail ? extractChecklist(detail) : []), [detail]);
  const samples = useMemo(() => (detail ? extractSamples(detail) : []), [detail]);

  const scenarioNameOf = (scenarioId: string | null): string =>
    scenarios.find((s) => s.id === (scenarioId ?? ""))?.name ?? "通用";

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

  /** 能力掌握度查询：任务场景记录优先，回退通用记录（PRD-06 §8.4） */
  const capScore = (capId: string): number | null => {
    const scenarioId = detail?.scenario_id ?? "";
    return masteryMap.get(`${capId}|${scenarioId}`) ?? masteryMap.get(`${capId}|`) ?? null;
  };

  /** 开始/继续任务（not_started|paused → in_progress） */
  const startTask = async () => {
    if (!id) return;
    setStarting(true);
    try {
      const res = await api.post<TaskSummary>(`/api/tasks/${id}/start`);
      setDetail((prev) => (prev ? { ...prev, status: res.status } : prev));
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
      setDetail((prev) => (prev ? { ...prev, status: res.status } : prev));
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
    setApplying(true);
    try {
      const res = await api.post<ApplyMasteryResponse>(`/api/tasks/${id}/apply-mastery`, {
        attempt_id: feedback.attempt_id,
      });
      toast.success(res.already_applied ? "掌握度此前已更新过" : "掌握度已更新");
      setApplied(true);
      await load(); // 刷新状态（completed）与提交历史
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

  return (
    <div>
      <PageHeader
        title={detail.title}
        sub={detail.goal ?? undefined}
        actions={
          detail.status === "not_started" || detail.status === "paused" ? (
            <Button loading={starting} onClick={startTask}>
              {detail.status === "paused" ? "继续任务" : "开始任务"}
            </Button>
          ) : undefined
        }
      />

      {/* 任务概览（PRD-01 §6.2：名称/目标/场景/关联岗位与证书/版本） */}
      <Card title="任务概览" className="mb-4">
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 flex-wrap">
            <StatusBadge status={detail.status} />
            <Tag>{taskSourceLabel(detail.source)}</Tag>
            {detail.source === "teacher" ? (
              <span className="badge badge-warning">教师</span>
            ) : null}
            <Tag>{dataTypeLabel(detail.data_type)}</Tag>
            <Tag>{scenarioNameOf(detail.scenario_id)}</Tag>
            <span className="text-xs text-muted">版本 v{detail.version}</span>
            {detail.due_at ? (
              <span className="text-xs text-secondary">截止：{formatDateTime(detail.due_at)}</span>
            ) : null}
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
        </div>
      </Card>

      {/* 学习材料（RAG 引用走 CitationCard，其余按类型分行展示） */}
      {detail.resources.length > 0 ? (
        <Card title="学习材料" className="mb-4">
          <div className="flex flex-col gap-2">
            {detail.resources.map((resource, index) =>
              resource.citation ? (
                <CitationCard
                  key={index}
                  citation={resource.citation as Citation}
                  index={index + 1}
                />
              ) : (
                <div key={index} className="flex items-center gap-2">
                  <span className="badge badge-info">{resourceTypeLabel(resource.type)}</span>
                  <span className="text-sm">{resource.title}</span>
                </div>
              ),
            )}
          </div>
        </Card>
      ) : null}

      {/* 操作步骤（含注意事项/常见错误，v3.0 §7.5.2） */}
      {detail.steps.length > 0 ? (
        <Card title="操作步骤" className="mb-4">
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
      <Card title="练习区" className="mb-4">
        {detail.status === "not_started" || detail.status === "paused" ? (
          <EmptyState title="任务尚未开始" hint="点击右上角「开始任务」后即可作答" />
        ) : (
          <div className="flex flex-col gap-4">
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
            {questions.length === 0 ? (
              <p className="text-sm text-secondary">
                该任务没有预设练习题，完成学习后可直接提交，系统将按完成情况评分。
              </p>
            ) : (
              questions.map((question) => (
                <div key={question.key}>
                  <label className="field-label">{question.prompt}</label>
                  {question.hint ? (
                    <p className="field-hint mb-2">{question.hint}</p>
                  ) : null}
                  {question.prompt.length > 40 ? (
                    <Textarea
                      value={answers[question.key] ?? ""}
                      disabled={!canPractice}
                      onChange={(e) =>
                        setAnswers((prev) => ({ ...prev, [question.key]: e.target.value }))
                      }
                    />
                  ) : (
                    <Input
                      value={answers[question.key] ?? ""}
                      disabled={!canPractice}
                      onChange={(e) =>
                        setAnswers((prev) => ({ ...prev, [question.key]: e.target.value }))
                      }
                    />
                  )}
                </div>
              ))
            )}
            {checklist.length > 0 ? (
              <div>
                <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                  自检清单
                </h3>
                <div className="flex flex-col gap-2">
                  {checklist.map((item) => (
                    <label key={item} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={checks[item] ?? false}
                        onChange={(e) =>
                          setChecks((prev) => ({ ...prev, [item]: e.target.checked }))
                        }
                      />
                      {item}
                    </label>
                  ))}
                </div>
              </div>
            ) : null}
            <div>
              <Button
                loading={submitting}
                disabled={!canPractice}
                onClick={submitAnswers}
              >
                {detail.status === "submitted" ? "重新提交" : "提交答案"}
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* 反馈区：得分 + 逐项反馈 + 掌握度预览（提交后出现） */}
      {feedback ? (
        <Card title="任务反馈" className="mb-4">
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
                  disabled={applied}
                  onClick={applyMastery}
                >
                  {applied ? "掌握度已更新" : "确认更新掌握度"}
                </Button>
              </div>
            </div>
          </div>
        </Card>
      ) : null}

      {/* 提交历史 */}
      {detail.attempts.length > 0 ? (
        <Card title="提交记录" className="mb-4">
          <DataTable
            ariaLabel="任务提交记录"
            columns={attemptColumns}
            rows={detail.attempts}
            rowKey={(attempt) => attempt.id}
          />
        </Card>
      ) : null}

      {/* 下一步推荐：回图谱看前置、回预设继续路径（PRD-01 §6.2 反馈区） */}
      <Card title="下一步推荐">
        <div className="flex items-center gap-2 flex-wrap">
          {detail.caps[0] ? (
            <Link to={`/graph?node=${detail.caps[0].cap_id}`} className="btn btn-secondary btn-sm">
              在图谱中查看「{detail.caps[0].cap_name}」
            </Link>
          ) : null}
          <Link to="/presets" className="btn btn-secondary btn-sm">
            继续预设学习
          </Link>
          <Link to="/tasks" className="btn btn-ghost btn-sm">
            返回任务列表
          </Link>
        </div>
      </Card>
    </div>
  );
}
