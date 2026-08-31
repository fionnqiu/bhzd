/**
 * 教学任务发布（/teacher/tasks，PRD-02 §5 + PRD-06 §10.1）。
 *
 * 关键决策（为什么）：
 * - 发布前先落库再 publish：publish 端点是"复制数据库行"给学生（teacher.py
 *   publish_teacher_task 直接 INSERT row 的 JSON 列），若未保存的最新编辑不
 *   先 PATCH，学生拿到的会是旧内容。当前编辑器先保存任务元数据，再通过
 *   单一事务端点替换学习内容，最后才发起发布，避免逐行删除/写入造成丢稿。
 * - 已发布任务（published_count>0）的原件不能被学生副本"静默漂移"：后端
 *   PATCH 会自动生成 version+1 新记录（version_bumped），页面用横幅提前
 *   告知，并在保存后切换到新版本继续编辑。
 * - 任务正文只保留名称、描述、学习内容和练习；班级、截止时间和掌握度开关
 *   只在发布动作中传递，避免把发布范围误存为任务内容或元数据。
 * - 预览面板始终常驻渲染（PRD §5.4"发布前必须展示预览"）：表单任何编辑
 *   实时反映到右侧任务卡，而不是发布前才弹一次预览。
 * - "AI 生成任务卡"（PRD-02 §5.3）：POST /api/teacher/tasks/generate 返回
 *   的是不落库草稿，前端把它整体填入表单后**所有字段仍可编辑**，并用横幅
 *   如实展示 sources_note/notice 与 llm_used（模型润色/模板生成）——教师
 *   审核确认后才走既有的保存/发布链路，生成端点本身不产生任何数据。
 * - 已发布任务的截止时间单独 PATCH（due_at）：后端对已发布副本直接改截止
 *   并通知学生 + 审计，**不触发版本升级**（teacher.py patch_teacher_task
 *   的 due_change 分支），因此与内容编辑（会升版本）拆成两个独立入口。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Plus, Sparkles, Trash2, X } from "lucide-react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type {
  ClassInfo,
  GraphNode,
  Paginated,
  PublishTaskResponse,
  TaskContentGenerationSource,
  TaskContentStatus,
  TeacherTaskContentPayload,
  TaskKnowledgePoint,
  TeacherTask,
} from "../../api/types";
import {
  Button,
  Card,
  ErrorState,
  Field,
  Input,
  PageHeader,
  Select,
  Spinner,
  Textarea,
  useToast,
} from "../../components";
import { errMsg, fmtDateTime } from "./utils";

/* ---------------------------------------------------------------- 表单模型 */

interface CapPick {
  id: string;
  name: string;
}

interface StepRow {
  title: string;
  notes: string;
  commonErrors: string;
}

interface RubricRow {
  key: string;
  expected: string;
  weight: string;
}

interface FormState {
  /** 已落库任务 id；null = 尚未保存的新任务 */
  taskId: string | null;
  /** 已发布学生副本数（>0 时编辑会触发版本升级横幅） */
  publishedCount: number;
  title: string;
  goal: string;
  dataType: string;
  caps: CapPick[];
  steps: StepRow[];
  rubric: RubricRow[];
  knowledgePoints: TaskKnowledgePoint[];
  exercises: ExerciseDraft[];
  classId: string;
  dueAt: string;
  counts: boolean;
  /** Durable background lesson-generation state returned by the teacher API. */
  contentStatus: TaskContentStatus;
  contentGeneratedAt: string | null;
  contentGenerationSource: TaskContentGenerationSource;
  contentFailureReason: string | null;
  contentGenerationMessage: string | null;
  contentGenerationRetryCount: number;
  contentLastAttemptAt: string | null;
}

interface ExerciseDraft {
  id?: string;
  question: string;
  type: "open_ended" | "multiple_choice" | "true_false";
  options: string;
  reference_answer: string;
}

/** Keep legacy exercise rows from turning an uncontrolled API string into a form-select value. */
function normalizeExerciseType(value: unknown): ExerciseDraft["type"] {
  return value === "multiple_choice" || value === "true_false" ? value : "open_ended";
}

function emptyForm(): FormState {
  return {
    taskId: null,
    publishedCount: 0,
    title: "",
    goal: "",
    dataType: "",
    caps: [],
    steps: [],
    rubric: [],
    knowledgePoints: [],
    exercises: [],
    classId: "",
    dueAt: "",
    counts: true, // PRD-06 §10.1：计入掌握度由教师发布时选择，默认计入
    contentStatus: "none",
    contentGeneratedAt: null,
    contentGenerationSource: "none",
    contentFailureReason: null,
    contentGenerationMessage: null,
    contentGenerationRetryCount: 0,
    contentLastAttemptAt: null,
  };
}

/** Convert unknown persisted values into safe controlled-input text. */
function editorText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === undefined || value === null) return "";
  try {
    return JSON.stringify(value) ?? "";
  } catch {
    return String(value);
  }
}

/**
 * Read both current teacher-task steps and early Agent drafts.  The first
 * Agent release stored its explanatory text as `description`; the publisher
 * owns the same text as editable `notes`, so compatibility belongs at this
 * boundary rather than allowing a re-save to discard it.
 */
function stepRowFromTask(step: TeacherTask["steps"][number]): StepRow {
  const legacy = step as typeof step & { description?: unknown };
  return {
    title: editorText(step.title),
    notes: editorText(step.notes ?? legacy.description),
    commonErrors: editorText(step.common_errors),
  };
}

/**
 * Keep legacy Agent rubrics editable after handoff.  New drafts are normalized
 * server-side, but existing rows still use `criterion/description/points` and
 * would otherwise fail before the save request can be made.
 */
function rubricRowFromTask(rubric: NonNullable<TeacherTask["rubric"]>[number]): RubricRow {
  const legacy = rubric as typeof rubric & {
    criterion?: unknown;
    description?: unknown;
    points?: unknown;
  };
  return {
    key: editorText(rubric.key ?? legacy.criterion),
    expected: editorText(rubric.expected ?? legacy.description),
    weight: editorText(rubric.weight ?? legacy.points),
  };
}

/** 后端行 → 表单（cap 名称来自已拉取的 CAP 节点映射，缺席时回退 id） */
function formFromTask(task: TeacherTask, capNames: Record<string, string>): FormState {
  return {
    taskId: task.id,
    publishedCount: task.published_count,
    title: task.title,
    goal: task.goal ?? "",
    dataType: task.data_type ?? "",
    caps: task.cap_ids.map((cid) => ({ id: cid, name: capNames[cid] ?? cid })),
    steps: task.steps.map(stepRowFromTask),
    rubric: (task.rubric ?? []).map(rubricRowFromTask),
    knowledgePoints: task.knowledge_points ?? [],
    exercises: (task.exercises ?? []).map((exercise) => ({
      id: exercise.id,
      question: exercise.question,
      type: normalizeExerciseType(exercise.type),
      options: (exercise.options ?? []).join("\n"),
      reference_answer: exercise.reference_answer ?? "",
    })),
    // Agent drafts are already scoped to an owned class.  Preselecting it
    // removes a redundant step, but the teacher must still review and click
    // the separate publish action before any student record is created.
    classId: task.class_id ?? "",
    dueAt: "",
    counts: true,
    contentStatus: task.content_status ?? "none",
    contentGeneratedAt: task.content_generated_at ?? null,
    contentGenerationSource: task.content_generation_source ?? "none",
    contentFailureReason: task.content_failure_reason ?? null,
    contentGenerationMessage: task.content_generation_message ?? null,
    contentGenerationRetryCount: task.content_generation_retry_count ?? 0,
    contentLastAttemptAt: task.content_last_attempt_at ?? null,
  };
}

/** Keep the durable generation fields in one mapping so polling/retry responses cannot drift. */
function contentFieldsFromTask(task: TeacherTask): Pick<
  FormState,
  | "contentStatus"
  | "contentGeneratedAt"
  | "contentGenerationSource"
  | "contentFailureReason"
  | "contentGenerationMessage"
  | "contentGenerationRetryCount"
  | "contentLastAttemptAt"
> {
  return {
    contentStatus: task.content_status ?? "none",
    contentGeneratedAt: task.content_generated_at ?? null,
    contentGenerationSource: task.content_generation_source ?? "none",
    contentFailureReason: task.content_failure_reason ?? null,
    contentGenerationMessage: task.content_generation_message ?? null,
    contentGenerationRetryCount: task.content_generation_retry_count ?? 0,
    contentLastAttemptAt: task.content_last_attempt_at ?? null,
  };
}

/** An exercise is executable when it can render a student control, not merely when a row exists. */
function isExecutableExercise(exercise: ExerciseDraft): boolean {
  if (!exercise.question.trim()) return false;
  if (exercise.type !== "multiple_choice") return true;
  return exercise.options.split(/\r?\n/).some((option) => option.trim());
}

function contentSourceLabel(source: TaskContentGenerationSource): string {
  switch (source) {
    case "provider":
      return "模型生成";
    case "template":
      return "模板兜底";
    case "manual":
      return "教师维护";
    case "copied":
      return "从上一版本复制";
    default:
      return "尚未生成";
  }
}

/** Read the one-shot task handoff used when Teacher Agent opens the publisher. */
function taskIdFromNavigationState(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  const taskId = (value as { taskId?: unknown }).taskId;
  return typeof taskId === "string" && taskId.trim() ? taskId : null;
}

/** Query state keeps the Agent-to-publisher handoff recoverable after refresh. */
function taskIdFromSearch(search: string): string | null {
  const taskId = new URLSearchParams(search).get("taskId");
  return taskId && taskId.trim() ? taskId : null;
}

/* ------------------------------------------------ AI 生成草稿的页面本地类型
 * （api/types.ts 由并行代理维护，本页按 teacher.py generate_teacher_task 的
 * 返回结构自留一份。后端可能继续返回 resources/citations 供旧客户端使用，
 * 但当前任务编辑契约不再把它们映射为可编辑关联，避免重新引入资源入口。 */
interface GenerateTaskDraft {
  title: string;
  goal: string;
  description?: string;
  data_type: string | null;
  cap_ids: string[];
  caps: { cap_id: string; cap_name: string }[];
  steps: { title: string; description?: string }[];
  rubric: { criterion: string; description: string; points: number }[];
  knowledge_points?: { title: string; content: string }[];
  exercises?: {
    question: string;
    type: "open_ended" | "multiple_choice" | "true_false";
    options?: string[] | null;
    reference_answer?: string | null;
  }[];
  difficulty: number;
  est_minutes: number;
  /** 引用来源说明（无命中资料时提示需手动补资料），必须如实展示给教师 */
  sources_note: string;
  /** true=LLM 润色过标题/步骤；false=纯模板组装（PRD-06 §11.1 离线兜底） */
  llm_used: boolean;
  /** 召回侧提示，可能为 null。 */
  notice: string | null;
}

/** AI 草稿横幅内容（生成成功后挂在编辑器顶部，直到教师关闭或换任务） */
interface AiBannerState {
  sourcesNote: string;
  notice: string | null;
  llmUsed: boolean;
}

type ActionStatus = {
  kind: "info" | "success" | "error";
  message: string;
} | null;

/* ---------------------------------------------------------------- 页面 */

export default function TaskPublishPage() {
  const location = useLocation();
  const { taskId: routeTaskId } = useParams<{ taskId?: string }>();
  const toast = useToast();
  const routeHandoffId =
    routeTaskId ?? taskIdFromSearch(location.search) ?? taskIdFromNavigationState(location.state);
  // Query state survives reload and copied links; router state remains a
  // compatibility fallback for handoffs created before this repair.
  const agentTaskIdRef = useRef<string | null>(routeHandoffId);
  const [agentTaskHandoffError, setAgentTaskHandoffError] = useState<string | null>(null);
  const [agentTaskHandoffRetry, setAgentTaskHandoffRetry] = useState(0);

  // ---- 左栏：我的教学任务 ----
  const [tasks, setTasks] = useState<TeacherTask[] | null>(null);
  const [tasksError, setTasksError] = useState<string | null>(null);

  // ---- 基础数据：班级（发布设置）与 CAP 名称映射 ----
  const [classes, setClasses] = useState<ClassInfo[]>([]);
  const [capNames, setCapNames] = useState<Record<string, string>>({});

  // ---- 编辑器 ----
  const [form, setForm] = useState<FormState>(emptyForm);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [actionStatus, setActionStatus] = useState<ActionStatus>(null);
  const [contentRetrying, setContentRetrying] = useState(false);
  // ---- AI 生成 / 已发布任务截止时间调整 ----
  const [generating, setGenerating] = useState(false);
  const [aiBanner, setAiBanner] = useState<AiBannerState | null>(null);
  // dueEdit 与发布设置的 dueAt 分开：前者 PATCH 已发布副本（不升版本），
  // 后者是"发布到新班级"时的截止时间，语义不同不能复用同一个字段
  const [dueEdit, setDueEdit] = useState("");
  const [dueSaving, setDueSaving] = useState(false);

  // The list owns navigation, while this page remains usable at the legacy /teacher/tasks URL;
  // derive the heading from the route without changing the editor's existing form contract.
  const isNewRoute = location.pathname.endsWith("/new");
  const pageTitle = isNewRoute
    ? "新建教学任务"
    : routeTaskId || routeHandoffId
      ? "编辑教学任务"
      : "教学任务发布";

  // Manual description is the single editable source; AI generation consumes it
  // and fills the normal task fields without creating resource associations.
  const [manualText, setManualText] = useState("");

  const patchForm = (patch: Partial<FormState>) => setForm((f) => ({ ...f, ...patch }));

  const loadTasks = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await api.get<Paginated<TeacherTask>>("/api/teacher/tasks", undefined, {
        signal,
      });
      if (signal?.aborted) return;
      setTasks(res.items);
      setTasksError(null);
    } catch (err) {
      if (!signal?.aborted) setTasksError(errMsg(err, "任务列表加载失败"));
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadTasks(controller.signal);
    // 基础数据各自独立失败：某个可选数据源挂了不阻断编辑器
    void api
      .get<Paginated<ClassInfo>>("/api/teacher/classes", undefined, { signal: controller.signal })
      .then((res) => {
        if (!controller.signal.aborted) setClasses(res.items);
      })
      .catch(() => {
        if (!controller.signal.aborted) toast.error("班级列表加载失败，发布设置暂不可用");
      });
    void api
      .get<Paginated<GraphNode>>(
        "/api/graph/nodes",
        { type: "CAP", limit: 200 },
        { signal: controller.signal },
      )
      .then((res) => {
        if (controller.signal.aborted) return;
        const map: Record<string, string> = {};
        for (const n of res.items) map[n.id] = n.label;
        setCapNames(map);
      })
      .catch(() => undefined); // 名称回退为 id 展示
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadTasks]);

  useEffect(() => {
    const taskId = agentTaskIdRef.current;
    if (!taskId) return;
    const controller = new AbortController();
    setAgentTaskHandoffError(null);

    // Fetch the exact owned draft instead of depending on the task-list
    // timing.  This keeps an Agent handoff correct after refresh and when the
    // list is unavailable or later becomes paginated.
    void api
      .get<TeacherTask>(`/api/teacher/tasks/${taskId}`, undefined, { signal: controller.signal })
      .then((task) => {
        if (controller.signal.aborted) return;
        setForm(formFromTask(task, capNames));
        setErrors({});
        setAiBanner(null);
        setDueEdit("");
        agentTaskIdRef.current = null;
        void loadTasks();
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setAgentTaskHandoffError(errMsg(error, "无法加载 Agent 草稿，请重试"));
        }
      });
    return () => controller.abort();
  }, [agentTaskHandoffRetry, capNames, loadTasks]);

  useEffect(() => {
    const taskId = form.taskId;
    if (!taskId || form.contentStatus !== "generating") return;
    let active = true;
    // Generation is detached from the request that saved the task. Poll only
    // while it is in flight, then hydrate the generated rows once a terminal
    // state is observed; this keeps refreshes honest without overwriting edits.
    const refresh = () => {
      void api
        .get<TeacherTask>(`/api/teacher/tasks/${taskId}`)
        .then((task) => {
          if (!active || task.id !== taskId) return;
          setForm((current) => {
            if (current.taskId !== taskId) return current;
            const generatedRows =
              current.knowledgePoints.length === 0 && current.exercises.length === 0;
            return {
              ...current,
              ...contentFieldsFromTask(task),
              ...(generatedRows
                ? {
                    knowledgePoints: task.knowledge_points ?? [],
                    exercises: (task.exercises ?? []).map((exercise) => ({
                      id: exercise.id,
                      question: exercise.question,
                      type: normalizeExerciseType(exercise.type),
                      options: (exercise.options ?? []).join("\n"),
                      reference_answer: exercise.reference_answer ?? "",
                    })),
                  }
                : {}),
            };
          });
        })
        .catch(() => undefined);
    };
    const timer = window.setInterval(refresh, 2000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [form.contentStatus, form.taskId]);

  /* ------------------------------------------------ 手动输入与 AI 生成 */

  const fillFromManual = () => {
    if (!manualText.trim()) return;
    // MVP 手动组装（Agent 生成走对话页）：把企业任务描述落到学习目标，
    // 标题为空时取首行，减少重复誊写
    patchForm({
      goal: manualText.trim(),
      title: form.title || manualText.trim().split("\n")[0].slice(0, 50),
    });
    toast.info("已填入任务描述，请继续完善学习内容和练习");
  };

  /** 切换/新建任务时清掉与上一张任务卡绑定的瞬态（AI 横幅、截止调整输入） */
  const resetTransient = () => {
    setAiBanner(null);
    setDueEdit("");
    setActionStatus(null);
  };

  /**
   * AI 生成任务卡（PRD-02 §5.3）：草稿整体填入表单但保持全部可编辑。
   * 请求带上当前表单已选的数据类型作为显式提示，避免模型重复猜测。
   */
  const generateDraft = async () => {
    const description = manualText.trim();
    if (!description) return;
    setGenerating(true);
    try {
      const draft = await api.post<GenerateTaskDraft>("/api/teacher/tasks/generate", {
        description,
        data_type: form.dataType || undefined,
      });
      patchForm({
        title: draft.title,
        goal: draft.description ?? draft.goal,
        dataType: draft.data_type ?? "",
        caps: draft.caps.map((c) => ({ id: c.cap_id, name: c.cap_name })),
        steps: [],
        rubric: [],
        knowledgePoints: (draft.knowledge_points ?? []).map((point, index) => ({
          ...point,
          id: `draft-point-${index}`,
          sort_order: index,
          created_at: "",
          updated_at: "",
        })),
        exercises: (draft.exercises ?? []).map((exercise, index) => ({
          id: `draft-exercise-${index}`,
          question: exercise.question,
          type: exercise.type,
          options: (exercise.options ?? []).join("\n"),
          reference_answer: exercise.reference_answer ?? "",
        })),
      });
      // 生成带回的能力名并入名称映射，预览/芯片都能显示中文名而非裸 id
      setCapNames((m) => ({
        ...m,
        ...Object.fromEntries(draft.caps.map((c) => [c.cap_id, c.cap_name])),
      }));
      setAiBanner({
        sourcesNote: draft.sources_note,
        notice: draft.notice,
        llmUsed: draft.llm_used,
      });
      toast.success("AI 草稿已填入表单，请审核调整后再发布");
    } catch (err) {
      toast.error(errMsg(err, "AI 生成失败，请稍后重试"));
    } finally {
      setGenerating(false);
    }
  };

  /**
   * 调整已发布任务的截止时间：只 PATCH due_at，不触碰内容字段——后端会
   * 直接改写学生副本并通知学生 + 记审计，不生成新版本（见模块注释）。
   */
  const updatePublishedDue = async () => {
    if (!form.taskId || !dueEdit) return;
    setDueSaving(true);
    try {
      await api.patch<TeacherTask>(`/api/teacher/tasks/${form.taskId}`, {
        due_at: new Date(dueEdit).toISOString(),
      });
      toast.success("截止时间已更新，本班学生将收到调整通知");
      setDueEdit("");
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setDueSaving(false);
    }
  };

  /* ------------------------------------------------ 校验与提交 */

  const hasExecutableExercise = form.exercises.some(isExecutableExercise);

  /** Client-side structural validation; publishing additionally requires a class and executable practice. */
  const validate = (forPublish: boolean): boolean => {
    const next: Record<string, string> = {};
    if (!form.title.trim()) next.title = "任务名称不能为空";
    if (forPublish && !form.classId) next.classId = "发布前请选择班级";
    if (forPublish && !hasExecutableExercise) {
      next.exercises = "发布前请至少添加一道可执行练习题";
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const buildBody = () => ({
    title: form.title,
    description: form.goal.trim() || null,
    // Content rows are persisted immediately after this request. Deferring the
    // worker prevents a provider/template result from racing reviewed edits.
    defer_content_generation: true,
  });

  /** Persist both active content tables through the backend transaction. */
  const persistContent = async (taskId: string) => {
    // Empty rows are an intentional affordance while a teacher is composing.
    // Ignore those placeholders, but reject partially authored rows before the
    // request so the form never silently discards a teacher's text.
    const knowledgePoints = form.knowledgePoints.filter(
      (point) => point.title.trim() || point.content.trim(),
    );
    if (knowledgePoints.some((point) => !point.title.trim() || !point.content.trim())) {
      throw new Error("每项学习内容都需要填写标题和内容");
    }
    const exercises = form.exercises.filter(
      (exercise) =>
        exercise.question.trim() || exercise.options.trim() || exercise.reference_answer.trim(),
    );
    if (exercises.some((exercise) => !exercise.question.trim())) {
      throw new Error("每道练习都需要填写题目");
    }
    if (
      exercises.some(
        (exercise) =>
          exercise.type === "multiple_choice" &&
          exercise.options.split(/\r?\n/).every((option) => !option.trim()),
      )
    ) {
      throw new Error("选择题需要至少一个选项");
    }

    const payload: TeacherTaskContentPayload = {
      knowledge_points: knowledgePoints.map((point, index) => ({
        title: point.title.trim(),
        content: point.content.trim(),
        sort_order: index,
      })),
      exercises: exercises.map((exercise, index) => ({
        question: exercise.question.trim(),
        type: exercise.type,
        options: exercise.options
          .split(/\r?\n/)
          .map((item) => item.trim())
          .filter(Boolean),
        reference_answer: exercise.reference_answer.trim() || null,
        sort_order: index,
      })),
    };
    const persisted = await api.put<TeacherTask>(
      `/api/teacher/tasks/${taskId}/content`,
      payload,
    );
    // The response carries fresh row IDs after a replacement.  Keeping those
    // IDs in local state makes a later explicit save update the same task.
    const returnedPoints = Array.isArray(persisted.knowledge_points)
      ? persisted.knowledge_points
      : knowledgePoints;
    const returnedExercises = Array.isArray(persisted.exercises)
      ? persisted.exercises
      : exercises.map((exercise, index) => ({
          id: exercise.id ?? `draft-exercise-${index}`,
          question: exercise.question,
          type: exercise.type,
          options: exercise.options.split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
          reference_answer: exercise.reference_answer || null,
          sort_order: index,
          created_at: "",
          submission: null,
        }));
    return {
      knowledgePoints: returnedPoints,
      exercises: returnedExercises.map((exercise) => ({
        id: exercise.id,
        question: exercise.question,
        type: normalizeExerciseType(exercise.type),
        options: (exercise.options ?? []).join("\n"),
        reference_answer: exercise.reference_answer ?? "",
      })),
      contentFields: contentFieldsFromTask(persisted),
    };
  };

  /** 保存草稿（新建 POST / 编辑 PATCH）；返回落库后的任务（版本升级时是新 id） */
  const saveTask = async (): Promise<TeacherTask | null> => {
    const body = buildBody();
    const res = form.taskId
      ? await api.patch<TeacherTask>(`/api/teacher/tasks/${form.taskId}`, body)
      : await api.post<TeacherTask>("/api/teacher/tasks", body);
    // Establish the durable draft identity before the content request.  If the
    // atomic content replacement is rejected, the next click must PATCH this
    // draft instead of creating a second task and leaving the first orphaned.
    patchForm({
      taskId: res.id,
      publishedCount: res.published_count ?? form.publishedCount,
    });
    // version_bumped：原版本与学生副本保持不动，后续编辑落在 version+1 新记录上
    if (res.version_bumped) {
      toast.info(`已生成新版本 v${res.version}，不影响已开始的学生`);
    }
    const persistedContent = await persistContent(res.id);
    const hasAuthoredContent =
      persistedContent.knowledgePoints.length > 0 || persistedContent.exercises.length > 0;
    patchForm({
      taskId: res.id,
      publishedCount: res.published_count ?? form.publishedCount,
      knowledgePoints: persistedContent.knowledgePoints,
      exercises: persistedContent.exercises,
      ...(hasAuthoredContent
        ? {
            contentStatus: "done" as const,
            contentGeneratedAt: new Date().toISOString(),
            contentGenerationSource: "manual" as const,
            contentFailureReason: null,
            contentGenerationMessage: null,
            contentLastAttemptAt: res.content_last_attempt_at ?? null,
          }
        : persistedContent.contentFields),
    });
    // A blank saved draft retains the legacy automatic-generation behavior, but
    // only the initial `none` state is queued implicitly. Failed generations
    // require the explicit retry action so a teacher can see the failure first.
    if (!hasAuthoredContent && persistedContent.contentFields.contentStatus === "none") {
      try {
        const queued = await api.post<TeacherTask>(`/api/teacher/tasks/${res.id}/content/retry`);
        patchForm(contentFieldsFromTask(queued));
      } catch {
        // The task is still saved; the status panel exposes the next action.
      }
    }
    void loadTasks();
    return res;
  };

  const saveDraft = async () => {
    if (!validate(false)) {
      setActionStatus({ kind: "error", message: "请先补全任务名称和未完成的内容" });
      return;
    }
    setActionStatus({ kind: "info", message: "正在保存草稿…" });
    setSaving(true);
    try {
      await saveTask();
      toast.success("草稿已保存");
      setActionStatus({ kind: "success", message: "草稿已保存，学习内容和练习已同步" });
    } catch (err) {
      toast.error(errMsg(err));
      setActionStatus({ kind: "error", message: errMsg(err, "草稿保存失败，已保留当前输入") });
    } finally {
      setSaving(false);
    }
  };

  const retryContent = async () => {
    if (!form.taskId) return;
    setContentRetrying(true);
    try {
      const task = await api.post<TeacherTask>(`/api/teacher/tasks/${form.taskId}/content/retry`);
      patchForm({
        ...contentFieldsFromTask(task),
        ...(task.knowledge_points || task.exercises
          ? {
              knowledgePoints: task.knowledge_points ?? [],
              exercises: (task.exercises ?? []).map((exercise) => ({
                id: exercise.id,
                question: exercise.question,
                type: normalizeExerciseType(exercise.type),
                options: (exercise.options ?? []).join("\n"),
                reference_answer: exercise.reference_answer ?? "",
              })),
            }
          : {}),
      });
      toast.info("学习内容已重新排队，请稍候查看生成结果");
    } catch (err) {
      toast.error(errMsg(err, "学习内容暂时无法生成，请稍后重试"));
    } finally {
      setContentRetrying(false);
    }
  };

  const publish = async () => {
    if (!validate(true)) {
      setActionStatus({ kind: "error", message: "请先选择班级并补全可执行练习" });
      return;
    }
    setActionStatus({ kind: "info", message: "正在保存任务内容并发布…" });
    setPublishing(true);
    try {
      // 先保存再发布：publish 复制的是数据库行（见模块注释）
      const saved = await saveTask();
      if (!saved) return;
      const res = await api.post<PublishTaskResponse>(`/api/teacher/tasks/${saved.id}/publish`, {
        class_id: form.classId,
        due_at: form.dueAt ? new Date(form.dueAt).toISOString() : null,
        counts_toward_mastery: form.counts,
      });
      patchForm({
        publishedCount: (saved.published_count ?? form.publishedCount) + res.published,
      });
      toast.success(`已发布给 ${res.published} 名学生`);
      setActionStatus({ kind: "success", message: `已发布给 ${res.published} 名学生` });
      void loadTasks();
    } catch (err) {
      toast.error(errMsg(err));
      setActionStatus({ kind: "error", message: errMsg(err, "发布失败，已保留当前输入") });
    } finally {
      setPublishing(false);
    }
  };

  /* ------------------------------------------------ 动态行编辑 */

  // The selection list stays beside the preview so teachers can compare an existing task before
  // changing the draft. Keeping it separate also prevents a third visual column on wide screens.
  const taskSelection = (
    <Card
      className="teacher-task-selection"
      title="我的教学任务"
      actions={
        <Button
          size="sm"
          onClick={() => {
            // A deliberate new-task action must win over a slow handoff-detail response.
            agentTaskIdRef.current = null;
            setAgentTaskHandoffError(null);
            setForm(emptyForm());
            setErrors({});
            resetTransient();
          }}
        >
          新建任务
        </Button>
      }
    >
      {tasksError ? (
        <ErrorState message={tasksError} onRetry={() => void loadTasks()} />
      ) : tasks === null ? (
        <div className="loading-block">
          <Spinner /> 加载中…
        </div>
      ) : tasks.length === 0 ? (
        <p className="text-sm text-secondary">
          还没有教学任务，点击「新建任务」开始组装第一张任务卡。
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {tasks.map((task) => (
            <li key={task.id}>
              <button
                type="button"
                className="btn btn-ghost btn-block"
                style={{
                  justifyContent: "flex-start",
                  textAlign: "left",
                  height: "auto",
                  padding: "var(--space-2) var(--space-3)",
                  border:
                    form.taskId === task.id
                      ? "1px solid var(--color-primary-border)"
                      : "1px solid transparent",
                  background: form.taskId === task.id ? "var(--color-primary-soft)" : undefined,
                }}
                onClick={() => {
                  // Do not let an outstanding Agent handoff overwrite a task the teacher selected.
                  agentTaskIdRef.current = null;
                  setForm(formFromTask(task, capNames));
                  setErrors({});
                  setAgentTaskHandoffError(null);
                  resetTransient();
                }}
              >
                <span className="flex flex-col gap-1 w-full">
                  <span className="flex items-center justify-between">
                    <strong>{task.title}</strong>
                    {task.published_count > 0 ? (
                      <span className="badge badge-success">已发布 {task.published_count}</span>
                    ) : (
                      <span className="badge badge-neutral">草稿</span>
                    )}
                  </span>
                  <span className="text-xs text-muted">
                    v{task.version} · 更新于 {fmtDateTime(task.updated_at)}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );

  const contentStatusPanel = form.taskId ? (
    <div
      className="teacher-task-content-status"
      style={{
        padding: "var(--space-3) var(--space-4)",
        border: "1px solid var(--color-border)",
        borderRadius: "var(--radius-md)",
        background: "var(--color-surface)"
      }}
      role={form.contentStatus === "failed" ? "alert" : "status"}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2">
          <strong>学习内容生成</strong>
          <span
            className={`badge ${
              form.contentStatus === "failed"
                ? "badge-danger"
                : form.contentStatus === "done"
                  ? "badge-success"
                  : "badge-neutral"
            }`}
          >
            {form.contentStatus === "generating"
              ? "生成中"
              : form.contentStatus === "failed"
                ? "生成失败"
                : form.contentStatus === "done"
                  ? contentSourceLabel(form.contentGenerationSource)
                  : "待生成"}
          </span>
        </span>
        {form.contentStatus === "generating" ? <Spinner size={14} /> : null}
      </div>
      {form.contentStatus === "generating" ? (
        <p className="text-sm text-secondary mt-2">正在准备学习内容，页面会自动更新状态。</p>
      ) : null}
      {form.contentStatus === "failed" ? (
        <p className="text-sm text-danger mt-2">
          {form.contentFailureReason ?? "学习内容生成失败，请稍后重试"}
        </p>
      ) : null}
      {form.contentStatus === "done" && form.contentGenerationMessage ? (
        <p className="text-sm text-secondary mt-2">{form.contentGenerationMessage}</p>
      ) : null}
      {form.contentStatus === "done" && form.contentGenerationSource === "template" ? (
        <p className="text-sm text-warning mt-2">当前内容来自本地模板兜底，请审核后再发布。</p>
      ) : null}
      {form.contentGenerationRetryCount > 0 ? (
        <p className="text-xs text-muted mt-2">
          已重试 {form.contentGenerationRetryCount} 次
          {form.contentLastAttemptAt ? ` · 最近尝试 ${fmtDateTime(form.contentLastAttemptAt)}` : ""}
        </p>
      ) : null}
      {form.contentStatus === "none" || form.contentStatus === "failed" ? (
        <Button
          className="mt-3"
          size="sm"
          variant="secondary"
          loading={contentRetrying}
          onClick={() => void retryContent()}
        >
          {form.contentStatus === "failed" ? "重试生成" : "生成学习内容"}
        </Button>
      ) : null}
    </div>
  ) : null;

  // Publishing is kept next to the live preview: class and deadline choices are easier to review
  // against the student-facing card than when they sit at the end of the long editing column.
  const publishSettings = (
    <Card className="teacher-task-publish-settings" title="发布设置">
      <div className="grid teacher-task-publish-fields">
        <Field label="选择班级" required error={errors.classId}>
          <Select
            options={classes.map((c) => ({ value: c.id, label: c.name }))}
            placeholder="请选择班级"
            aria-label="选择班级"
            value={form.classId}
            invalid={!!errors.classId}
            onChange={(e) => patchForm({ classId: e.target.value })}
          />
        </Field>
        <Field label="截止时间">
          <Input
            type="datetime-local"
            value={form.dueAt}
            onChange={(e) => patchForm({ dueAt: e.target.value })}
          />
        </Field>
      </div>
      <label className="flex items-center gap-2 mt-2">
        <input
          type="checkbox"
          checked={form.counts}
          onChange={(e) => patchForm({ counts: e.target.checked })}
        />
        计入掌握度（学生完成本任务后按成绩更新能力掌握度）
      </label>

      {/* Published-task deadlines patch student copies directly, so this must not share the draft's versioned save path. */}
      {form.taskId && form.publishedCount > 0 ? (
        <div
          className="mt-3"
          style={{
            borderTop: "1px solid var(--color-border)",
            paddingTop: "var(--space-3)",
          }}
        >
          <Field label="调整已发布任务的截止时间">
            <div className="flex items-center gap-2">
              <Input
                type="datetime-local"
                aria-label="新的截止时间"
                value={dueEdit}
                onChange={(e) => setDueEdit(e.target.value)}
              />
              <Button
                variant="secondary"
                onClick={() => void updatePublishedDue()}
                loading={dueSaving}
                disabled={!dueEdit}
              >
                更新截止时间
              </Button>
            </div>
          </Field>
          <p className="text-xs text-muted mt-2">
            修改截止时间将通知本班学生并记录审计（不生成新版本）
          </p>
        </div>
      ) : null}

      <div className="flex gap-2 mt-4">
        <Button
          variant="secondary"
          onClick={() => void saveDraft()}
          loading={saving}
          disabled={publishing}
        >
          保存草稿
        </Button>
        <Button
          onClick={() => void publish()}
          loading={publishing}
          disabled={saving || !hasExecutableExercise}
          aria-describedby={!hasExecutableExercise ? "publish-exercise-requirement" : undefined}
        >
          发布
        </Button>
      </div>
      {!hasExecutableExercise ? (
        <p id="publish-exercise-requirement" className="text-sm text-danger mt-2" role="alert">
          {errors.exercises ?? "发布前请至少添加一道可执行练习题"}
        </p>
      ) : null}
      {!form.classId && form.title.trim() ? (
        <p className="text-sm text-danger mt-2" role="alert">
          {errors.classId ?? "发布前请选择班级"}
        </p>
      ) : null}
      {actionStatus ? (
        <p
          aria-label="发布结果"
          aria-live="polite"
          className={`text-sm mt-3 ${
            actionStatus.kind === "error"
              ? "text-danger"
              : actionStatus.kind === "success"
                ? "text-success"
                : "text-secondary"
          }`}
          role={actionStatus.kind === "error" ? "alert" : "status"}
        >
          {actionStatus.message}
        </p>
      ) : null}
    </Card>
  );

  /* ------------------------------------------------ 渲染 */

  return (
    <div className="teacher-workbench-page teacher-task-publish-page">
      <PageHeader
        title={pageTitle}
        actions={
          <Link className="btn btn-secondary" to="/teacher/tasks">
            <ArrowLeft size={16} aria-hidden />
            返回任务管理
          </Link>
        }
      />

      {agentTaskHandoffError ? (
        <ErrorState
          message={agentTaskHandoffError}
          onRetry={() => {
            setAgentTaskHandoffError(null);
            setAgentTaskHandoffRetry((current) => current + 1);
          }}
        />
      ) : null}

      {/* Two independent workspaces keep editing on the left and review/publishing on the right. */}
      <div className="teacher-task-publish-layout">
        {/* ============ 左栏：来源与任务内容编辑 ============ */}
        <div className="teacher-task-editor-layout">
          <div className="flex flex-col gap-4">
            {/* 已发布任务编辑提醒（PRD-06 §10.1：生成新版本，不覆盖学生任务） */}
            {form.publishedCount > 0 ? (
              <div
                style={{
                  padding: "var(--space-3) var(--space-4)",
                  background: "var(--color-warning-soft)",
                  border: "1px solid var(--color-warning)",
                  borderRadius: "var(--radius-md)",
                }}
              >
                修改已发布任务将生成新版本，不影响已开始的学生
              </div>
            ) : null}

            {/* 任务输入只保留手动描述与 AI 草稿生成；资源关联入口已移除，
                历史 DTO 中的 resources 仍可被读取但不会进入编辑状态或保存负载。 */}
            <Card title="任务输入">
              <div className="flex flex-col gap-3">
                <Textarea
                  rows={4}
                  value={manualText}
                  placeholder="粘贴或描述企业岗位任务，例如：对客服通话录音完成情感极性标注，要求区分投诉与咨询内容……"
                  onChange={(e) => setManualText(e.target.value)}
                />
                <div
                  className="text-sm text-secondary"
                  style={{
                    padding: "var(--space-3)",
                    background: "var(--color-info-soft)",
                    borderRadius: "var(--radius-md)",
                  }}
                >
                  AI 生成说明：基于任务描述生成任务名称、描述、学习内容和练习；
                  草稿不落库，填入表单后可继续编辑，审核确认后再保存或发布。
                </div>
                <div className="flex gap-2">
                  <Button
                    onClick={() => void generateDraft()}
                    loading={generating}
                    disabled={!manualText.trim()}
                  >
                    <Sparkles size={14} /> AI 生成任务卡
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={fillFromManual}
                    disabled={!manualText.trim()}
                  >
                    仅填入学习目标
                  </Button>
                </div>
              </div>
            </Card>

            {/* AI 草稿横幅（PRD-02 §5.3：生成结果必须经教师审核才发布，
                因此如实展示引用来源说明与生成方式徽章，不静默冒充人工内容） */}
            {aiBanner ? (
              <div
                role="status"
                style={{
                  padding: "var(--space-3) var(--space-4)",
                  background: "var(--color-info-soft)",
                  border: "1px solid var(--color-info)",
                  borderRadius: "var(--radius-md)",
                }}
              >
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2">
                    <strong>AI 草稿，请审核后发布</strong>
                    <span
                      className={`badge ${aiBanner.llmUsed ? "badge-primary" : "badge-neutral"}`}
                    >
                      {aiBanner.llmUsed ? "模型润色" : "模板生成"}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="icon-btn"
                    aria-label="关闭提示"
                    onClick={() => setAiBanner(null)}
                  >
                    <X size={14} />
                  </button>
                </div>
                <p className="text-sm text-secondary mt-2">{aiBanner.sourcesNote}</p>
                {aiBanner.notice ? (
                  <p className="text-sm text-secondary mt-2">{aiBanner.notice}</p>
                ) : null}
              </div>
            ) : null}

            {contentStatusPanel}

            {/* Active task authoring surface: name, description, learning content, practice. */}
            <Card title="任务内容">
              <Field label="任务名称" required error={errors.title}>
                <Input
                  value={form.title}
                  invalid={!!errors.title}
                  placeholder="例如：客服语音情感标注实战"
                  onChange={(e) => patchForm({ title: e.target.value })}
                />
              </Field>
              <Field label="任务描述">
                <Textarea
                  rows={3}
                  value={form.goal}
                  placeholder="说明学生要学习的主题、范围和预期结果"
                  onChange={(e) => patchForm({ goal: e.target.value })}
                />
              </Field>
              <Field label="学习内容">
                <div className="flex flex-col gap-3">
                  {form.knowledgePoints.map((point, index) => (
                    <div key={point.id} className="card-padded">
                      <div className="flex items-center gap-2">
                        <Input
                          value={point.title}
                          placeholder={`知识点 ${index + 1}`}
                          onChange={(event) =>
                            patchForm({
                              knowledgePoints: form.knowledgePoints.map((item) =>
                                item.id === point.id ? { ...item, title: event.target.value } : item,
                              ),
                            })
                          }
                        />
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`删除学习内容 ${index + 1}`}
                          onClick={() =>
                            patchForm({ knowledgePoints: form.knowledgePoints.filter((item) => item.id !== point.id) })
                          }
                        >
                          <Trash2 size={14} />
                        </Button>
                      </div>
                      <Textarea
                        className="mt-2"
                        rows={3}
                        value={point.content}
                        placeholder="填写这一知识点的学习内容"
                        onChange={(event) =>
                          patchForm({
                            knowledgePoints: form.knowledgePoints.map((item) =>
                              item.id === point.id ? { ...item, content: event.target.value } : item,
                            ),
                          })
                        }
                      />
                    </div>
                  ))}
                  <Button
                    variant="secondary"
                    onClick={() =>
                      patchForm({
                        knowledgePoints: [
                          ...form.knowledgePoints,
                          {
                            id: `draft-point-${Date.now()}`,
                            title: "",
                            content: "",
                            sort_order: form.knowledgePoints.length,
                            created_at: "",
                            updated_at: "",
                          },
                        ],
                      })
                    }
                  >
                    <Plus size={14} /> 添加学习内容
                  </Button>
                </div>
              </Field>

              <Field label="练习">
                <div className="flex flex-col gap-3">
                  {form.exercises.map((exercise, index) => (
                    <div key={exercise.id ?? index} className="card-padded">
                      <div className="flex items-center gap-2">
                        <Input
                          value={exercise.question}
                          placeholder={`练习题 ${index + 1}`}
                          onChange={(event) =>
                            patchForm({
                              exercises: form.exercises.map((item, itemIndex) =>
                                itemIndex === index ? { ...item, question: event.target.value } : item,
                              ),
                            })
                          }
                        />
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`删除练习 ${index + 1}`}
                          onClick={() => patchForm({ exercises: form.exercises.filter((_, itemIndex) => itemIndex !== index) })}
                        >
                          <Trash2 size={14} />
                        </Button>
                      </div>
                      <div className="grid grid-cols-2 mt-2">
                        <Select
                          aria-label={`练习 ${index + 1} 题型`}
                          value={exercise.type}
                          options={[
                            { value: "open_ended", label: "问答题" },
                            { value: "multiple_choice", label: "选择题" },
                            { value: "true_false", label: "判断题" },
                          ]}
                          onChange={(event) =>
                            patchForm({
                              exercises: form.exercises.map((item, itemIndex) =>
                                itemIndex === index
                                  ? { ...item, type: event.target.value as ExerciseDraft["type"] }
                                  : item,
                              ),
                            })
                          }
                        />
                        <Input
                          value={exercise.reference_answer}
                          placeholder="参考答案（仅教师可见）"
                          onChange={(event) =>
                            patchForm({
                              exercises: form.exercises.map((item, itemIndex) =>
                                itemIndex === index
                                  ? { ...item, reference_answer: event.target.value }
                                  : item,
                              ),
                            })
                          }
                        />
                      </div>
                      {exercise.type !== "open_ended" ? (
                        <Textarea
                          className="mt-2"
                          rows={3}
                          value={exercise.options}
                          placeholder="每行一个选项"
                          onChange={(event) =>
                            patchForm({
                              exercises: form.exercises.map((item, itemIndex) =>
                                itemIndex === index ? { ...item, options: event.target.value } : item,
                              ),
                            })
                          }
                        />
                      ) : null}
                    </div>
                  ))}
                  <Button
                    variant="secondary"
                    onClick={() =>
                      patchForm({
                        exercises: [
                          ...form.exercises,
                          {
                            id: `draft-exercise-${Date.now()}`,
                            question: "",
                            type: "open_ended",
                            options: "",
                            reference_answer: "",
                          },
                        ],
                      })
                    }
                  >
                    <Plus size={14} /> 添加练习
                  </Button>
                </div>
              </Field>

            </Card>
          </div>
        </div>

        {/* ============ 右栏：任务选择、预览与发布 ============ */}
        <aside className="teacher-task-review-layout">
          {taskSelection}

          {/* ============ 常驻预览（PRD §5.4：发布前必须展示预览） ============ */}
          <div className="teacher-task-preview">
            <Card title="任务卡预览">
              <p className="text-xs text-muted mb-3">
                发布前请确认预览内容，学生看到的就是这张任务卡
              </p>
              <h3>{form.title || "未命名任务"}</h3>
              {form.goal.trim() ? <p className="text-sm text-secondary mt-2">{form.goal}</p> : null}
              <div className="flex flex-col gap-3 mt-4">
                <section>
                  <h4>学习内容（{form.knowledgePoints.length}）</h4>
                  {form.knowledgePoints.length > 0 ? (
                    <ol className="flex flex-col gap-2 mt-2" style={{ listStyle: "decimal", paddingLeft: "var(--space-5)" }}>
                      {form.knowledgePoints.map((point) => (
                        <li key={point.id}>
                          <strong>{point.title || "未命名知识点"}</strong>
                          <p className="text-sm text-secondary mt-1">{point.content}</p>
                        </li>
                      ))}
                    </ol>
                  ) : <p className="text-sm text-muted mt-2">暂无学习内容</p>}
                </section>
                <section>
                  <h4>练习（{form.exercises.length}）</h4>
                  {form.exercises.length > 0 ? (
                    <ol className="flex flex-col gap-2 mt-2" style={{ listStyle: "decimal", paddingLeft: "var(--space-5)" }}>
                      {form.exercises.map((exercise, index) => (
                        <li key={exercise.id ?? index} className="text-sm">
                          {exercise.question || "未命名练习"}
                          <span className="text-xs text-muted">（{exercise.type === "multiple_choice" ? "选择题" : exercise.type === "true_false" ? "判断题" : "问答题"}）</span>
                        </li>
                      ))}
                    </ol>
                  ) : <p className="text-sm text-muted mt-2">暂无练习</p>}
                </section>
              </div>

              <h4 className="mt-4">发布信息</h4>
              <p className="text-sm text-secondary mt-2">
                班级：{classes.find((c) => c.id === form.classId)?.name ?? "未选择"}
                <br />
                截止：{form.dueAt ? fmtDateTime(new Date(form.dueAt).toISOString()) : "未设置"}
              </p>
            </Card>
          </div>
          {publishSettings}
        </aside>
      </div>
    </div>
  );
}
