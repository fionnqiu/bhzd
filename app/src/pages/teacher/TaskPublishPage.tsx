/**
 * 教学任务发布（/teacher/tasks，PRD-02 §5 + PRD-06 §10.1）。
 *
 * 关键决策（为什么）：
 * - 发布前先落库再 publish：publish 端点是"复制数据库行"给学生（teacher.py
 *   publish_teacher_task 直接 INSERT row 的 JSON 列），若未保存的最新编辑不
 *   先 PATCH，学生拿到的会是旧内容——所以"发布"按钮内部总是先保存草稿。
 * - 已发布任务（published_count>0）的原件不能被学生副本"静默漂移"：后端
 *   PATCH 会自动生成 version+1 新记录（version_bumped），页面用横幅提前
 *   告知，并在保存后切换到新版本继续编辑。
 * - 能力节点≥1 + 来源资料≥1 是 PRD-02 §5.4 硬约束，前端先做客户端校验
 *   （错误落在字段旁），后端 400（CAPS_REQUIRED/RESOURCES_REQUIRED）兜底
 *   时原样透出中文 message。
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

import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, Sparkles, Trash2, X } from "lucide-react";
import { api } from "../../api/client";
import type {
  Citation,
  ClassInfo,
  GraphNode,
  Paginated,
  Preset,
  PublishTaskResponse,
  TeacherResource,
  TeacherTask,
} from "../../api/types";
import {
  Button,
  Card,
  CitationCard,
  ErrorState,
  Field,
  Input,
  PageHeader,
  SearchInput,
  Select,
  Spinner,
  Tabs,
  Tag,
  Textarea,
  useToast,
} from "../../components";
import { DATA_TYPE_OPTIONS, dataTypeLabel, errMsg, fmtDateTime } from "./utils";

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

interface ResourceRow {
  type: string; // rag_document / teaching_unit / link
  title: string;
  refId?: string;
  url?: string;
  citation?: Citation;
}

interface FormState {
  /** 已落库任务 id；null = 尚未保存的新任务 */
  taskId: string | null;
  /** 已发布学生副本数（>0 时编辑会触发版本升级横幅） */
  publishedCount: number;
  title: string;
  goal: string;
  dataType: string;
  scenarioId: string;
  caps: CapPick[];
  steps: StepRow[];
  rubric: RubricRow[];
  resources: ResourceRow[];
  classId: string;
  dueAt: string;
  counts: boolean;
}

function emptyForm(): FormState {
  return {
    taskId: null,
    publishedCount: 0,
    title: "",
    goal: "",
    dataType: "",
    scenarioId: "",
    caps: [],
    steps: [],
    rubric: [],
    resources: [],
    classId: "",
    dueAt: "",
    counts: true, // PRD-06 §10.1：计入掌握度由教师发布时选择，默认计入
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
    scenarioId: task.scenario_id ?? "",
    caps: task.cap_ids.map((cid) => ({ id: cid, name: capNames[cid] ?? cid })),
    steps: task.steps.map((s) => ({
      title: s.title ?? "",
      notes: s.notes ?? "",
      commonErrors: s.common_errors ?? "",
    })),
    rubric: (task.rubric ?? []).map((r) => ({
      key: r.key,
      expected: typeof r.expected === "string" ? r.expected : JSON.stringify(r.expected),
      weight: r.weight === undefined ? "" : String(r.weight),
    })),
    resources: task.resources.map((r) => ({
      type: r.type,
      title: r.title,
      refId: r.ref_id,
      url: typeof r.url === "string" ? r.url : undefined,
      citation: r.citation as Citation | undefined,
    })),
    classId: "",
    dueAt: "",
    counts: true,
  };
}

type SourceTab = "manual" | "rag" | "preset" | "history";

const SOURCE_TABS = [
  { key: "manual", label: "手动输入岗位任务" },
  { key: "rag", label: "从已发布资料选择" },
  { key: "preset", label: "从预设模板选择" },
  { key: "history", label: "从历史任务复制" },
];

const RESOURCE_TYPE_LABELS: Record<string, string> = {
  rag_document: "RAG 资料",
  teaching_unit: "教学单元",
  link: "外部链接",
};

/* ------------------------------------------------ AI 生成草稿的页面本地类型
 * （api/types.ts 由并行代理维护，本页按 teacher.py generate_teacher_task 的
 * 返回结构自留一份；generate 响应里 resources[i] 与 citations[i] 同源同序——
 * 都来自 hits[:5]，所以按下标配对把结构化引用装回资源行） */
interface GenerateTaskDraft {
  title: string;
  goal: string;
  data_type: string | null;
  scenario_id: string | null;
  cap_ids: string[];
  caps: { cap_id: string; cap_name: string }[];
  steps: { title: string; description?: string }[];
  resources: { type: string; ref_id?: string; title: string; citation?: string }[];
  citations: Citation[];
  rubric: { criterion: string; description: string; points: number }[];
  difficulty: number;
  est_minutes: number;
  /** 引用来源说明（无命中资料时提示需手动补资料），必须如实展示给教师 */
  sources_note: string;
  /** true=LLM 润色过标题/步骤；false=纯模板组装（PRD-06 §11.1 离线兜底） */
  llm_used: boolean;
  /** 召回侧提示（如场景冲突降权），可能为 null */
  notice: string | null;
}

/** AI 草稿横幅内容（生成成功后挂在编辑器顶部，直到教师关闭或换任务） */
interface AiBannerState {
  sourcesNote: string;
  notice: string | null;
  llmUsed: boolean;
}

/* ---------------------------------------------------------------- 页面 */

export default function TaskPublishPage() {
  const toast = useToast();

  // ---- 左栏：我的教学任务 ----
  const [tasks, setTasks] = useState<TeacherTask[] | null>(null);
  const [tasksError, setTasksError] = useState<string | null>(null);

  // ---- 基础数据：班级（发布设置）、场景（SCN 节点）、CAP 名称映射 ----
  const [classes, setClasses] = useState<ClassInfo[]>([]);
  const [scenarios, setScenarios] = useState<GraphNode[]>([]);
  const [capNames, setCapNames] = useState<Record<string, string>>({});

  // ---- 编辑器 ----
  const [form, setForm] = useState<FormState>(emptyForm);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  // ---- AI 生成 / 已发布任务截止时间调整 ----
  const [generating, setGenerating] = useState(false);
  const [aiBanner, setAiBanner] = useState<AiBannerState | null>(null);
  // dueEdit 与发布设置的 dueAt 分开：前者 PATCH 已发布副本（不升版本），
  // 后者是"发布到新班级"时的截止时间，语义不同不能复用同一个字段
  const [dueEdit, setDueEdit] = useState("");
  const [dueSaving, setDueSaving] = useState(false);

  // ---- 任务来源四个页签的局部状态 ----
  const [sourceTab, setSourceTab] = useState<SourceTab>("manual");
  const [manualText, setManualText] = useState("");
  // 注意（为什么 value 不是受控同步）：SearchInput 的防抖在 inner!==value 时才
  // 触发 onSearch（见组件实现），若父级在 onChange 里同步 value，两者恒等、
  // 防抖永不触发。因此这两个状态只保存"已提交的搜索词"，输入过程由组件自管。
  const [ragQuery, setRagQuery] = useState("");
  const [ragResults, setRagResults] = useState<TeacherResource[] | null>(null);
  const [ragSearching, setRagSearching] = useState(false);
  const [presets, setPresets] = useState<Preset[] | null>(null);
  const [capQuery, setCapQuery] = useState("");
  const [capResults, setCapResults] = useState<GraphNode[]>([]);

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
        { type: "SCN", limit: 100 },
        { signal: controller.signal },
      )
      .then((res) => {
        if (!controller.signal.aborted) setScenarios(res.items);
      })
      .catch(() => undefined); // 场景下拉留空即可
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

  /* ------------------------------------------------ 来源页签的数据加载 */

  const searchRagDocs = useCallback(
    async (q: string, signal?: AbortSignal) => {
      setRagSearching(true);
      try {
        // Teachers only need an attachable published-material catalog, not the RAG management API.
        const res = await api.get<Paginated<TeacherResource>>(
          "/api/teacher/resources",
          {
            q: q || undefined,
            limit: 10,
            offset: 0,
          },
          { signal },
        );
        if (signal?.aborted) return;
        setRagResults(res.items);
      } catch (err) {
        if (!signal?.aborted) toast.error(errMsg(err, "资料搜索失败"));
      } finally {
        if (!signal?.aborted) setRagSearching(false);
      }
    },
    [toast],
  );

  // 切到 RAG 页签时先拉一批默认结果，避免面对空白不知所措
  useEffect(() => {
    if (sourceTab !== "rag" || ragResults !== null) return;
    const controller = new AbortController();
    void searchRagDocs("", controller.signal);
    return () => controller.abort();
  }, [sourceTab, ragResults, searchRagDocs]);

  useEffect(() => {
    if (sourceTab !== "preset" || presets !== null) return;
    const controller = new AbortController();
    void api
      .get<Paginated<Preset>>("/api/presets", undefined, { signal: controller.signal })
      .then((res) => {
        if (!controller.signal.aborted) setPresets(res.items);
      })
      .catch((err) => {
        if (!controller.signal.aborted) toast.error(errMsg(err, "预设模板加载失败"));
      });
    return () => controller.abort();
  }, [sourceTab, presets, toast]);

  const searchCaps = useCallback(
    async (q: string, signal?: AbortSignal) => {
      try {
        const res = await api.get<Paginated<GraphNode>>(
          "/api/graph/nodes",
          {
            q: q || undefined,
            type: "CAP",
            limit: 10,
          },
          { signal },
        );
        if (signal?.aborted) return;
        setCapResults(res.items);
      } catch (err) {
        if (!signal?.aborted) toast.error(errMsg(err, "能力节点搜索失败"));
      }
    },
    [toast],
  );

  /* ------------------------------------------------ 来源页签的动作 */

  const fillFromManual = () => {
    if (!manualText.trim()) return;
    // MVP 手动组装（Agent 生成走指挥舱）：把企业任务描述落到学习目标，
    // 标题为空时取首行，减少重复誊写
    patchForm({
      goal: manualText.trim(),
      title: form.title || manualText.trim().split("\n")[0].slice(0, 50),
    });
    toast.info("已填入学习目标，请继续完善步骤与资源");
  };

  /** 切换/新建任务时清掉与上一张任务卡绑定的瞬态（AI 横幅、截止调整输入） */
  const resetTransient = () => {
    setAiBanner(null);
    setDueEdit("");
  };

  /**
   * AI 生成任务卡（PRD-02 §5.3）：草稿整体填入表单但保持全部可编辑。
   * 请求带上当前表单已选的数据类型/场景作为显式提示——后端"显式参数优先
   * 于意图识别"，教师先选好了就不让模型再猜一遍。
   */
  const generateDraft = async () => {
    const description = manualText.trim();
    if (!description) return;
    setGenerating(true);
    try {
      const draft = await api.post<GenerateTaskDraft>("/api/teacher/tasks/generate", {
        description,
        scenario_id: form.scenarioId || undefined,
        data_type: form.dataType || undefined,
      });
      patchForm({
        title: draft.title,
        goal: draft.goal,
        dataType: draft.data_type ?? "",
        scenarioId: draft.scenario_id ?? "",
        caps: draft.caps.map((c) => ({ id: c.cap_id, name: c.cap_name })),
        // 后端步骤字段是 description，表单行口径是 notes（注意事项），在此对齐
        steps: draft.steps.map((s) => ({
          title: s.title ?? "",
          notes: s.description ?? "",
          commonErrors: "",
        })),
        // 后端评分项是 criterion/description/points，表单行是 key/expected/weight
        rubric: draft.rubric.map((r) => ({
          key: r.criterion,
          expected: r.description,
          weight: String(r.points),
        })),
        resources: draft.resources.map((r, i) => ({
          type: r.type,
          title: r.title,
          refId: r.ref_id,
          // citations[i] 与 resources[i] 同源同序（见类型注释），装回结构化
          // 引用后预览区才能渲染 CitationCard；缺席时退化为普通资源卡
          citation: draft.citations[i],
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

  const addRagResource = (doc: TeacherResource) => {
    if (form.resources.some((r) => r.refId === doc.id)) {
      toast.info("该资料已在资源列表中");
      return;
    }
    const citation: Citation = {
      document_id: doc.id,
      title: doc.title,
      section_title: null,
      page_start: null,
      page_end: null,
      version: doc.version,
      score: 1,
    };
    patchForm({
      resources: [
        ...form.resources,
        { type: "rag_document", title: doc.title, refId: doc.id, citation },
      ],
    });
  };

  const applyPreset = (preset: Preset) => {
    patchForm({
      title: form.title || preset.title,
      goal: preset.goal,
      dataType: preset.data_type,
      scenarioId: preset.scenario_id ?? "",
      caps: preset.caps.map((c) => ({ id: c.cap_id, name: c.cap_name })),
      // 预设的教学单元天然是"步骤 + 资源"的来源（PRD §5.2 模板预填）
      steps: preset.units.map((u) => ({ title: u.title, notes: "", commonErrors: "" })),
      resources: preset.units.map((u) => ({
        type: "teaching_unit",
        title: u.title,
        refId: u.unit_id,
      })),
    });
    toast.info(`已按模板「${preset.title}」填充，可按需调整`);
  };

  const copyFromHistory = (task: TeacherTask) => {
    const copied = formFromTask(task, capNames);
    patchForm({
      ...copied,
      taskId: null, // 复制=新草稿，不覆盖原任务
      publishedCount: 0,
      title: `${task.title}（副本）`,
    });
    toast.info("已从历史任务复制内容");
  };

  /* ------------------------------------------------ 校验与提交 */

  /** PRD-02 §5.4 客户端校验；forPublish 时额外要求选择班级 */
  const validate = (forPublish: boolean): boolean => {
    const next: Record<string, string> = {};
    if (!form.title.trim()) next.title = "任务名称不能为空";
    if (form.caps.length === 0) next.caps = "任务必须至少关联一个能力节点";
    if (form.resources.length === 0) next.resources = "任务必须至少关联一个来源资料";
    if (forPublish && !form.classId) next.classId = "发布前请选择班级";
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const buildBody = () => ({
    title: form.title.trim(),
    goal: form.goal.trim() || null,
    data_type: form.dataType || null,
    scenario_id: form.scenarioId || null,
    cap_ids: form.caps.map((c) => c.id),
    steps: form.steps
      .filter((s) => s.title.trim())
      .map((s) => ({
        title: s.title.trim(),
        notes: s.notes.trim() || undefined,
        common_errors: s.commonErrors.trim() || undefined,
      })),
    resources: form.resources.map((r) => ({
      type: r.type,
      title: r.title,
      ref_id: r.refId,
      url: r.url,
      citation: r.citation,
    })),
    rubric: form.rubric.length
      ? form.rubric
          .filter((r) => r.key.trim())
          .map((r) => ({
            key: r.key.trim(),
            expected: r.expected,
            weight: r.weight.trim() === "" ? undefined : Number(r.weight),
          }))
      : null,
  });

  /** 保存草稿（新建 POST / 编辑 PATCH）；返回落库后的任务（版本升级时是新 id） */
  const saveTask = async (): Promise<TeacherTask | null> => {
    const body = buildBody();
    const res = form.taskId
      ? await api.patch<TeacherTask>(`/api/teacher/tasks/${form.taskId}`, body)
      : await api.post<TeacherTask>("/api/teacher/tasks", body);
    // version_bumped：原版本与学生副本保持不动，后续编辑落在 version+1 新记录上
    if (res.version_bumped) {
      toast.info(`已生成新版本 v${res.version}，不影响已开始的学生`);
    }
    patchForm({ taskId: res.id, publishedCount: res.published_count });
    void loadTasks();
    return res;
  };

  const saveDraft = async () => {
    if (!validate(false)) return;
    setSaving(true);
    try {
      await saveTask();
      toast.success("草稿已保存");
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setSaving(false);
    }
  };

  const publish = async () => {
    if (!validate(true)) return;
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
      patchForm({ publishedCount: saved.published_count + res.published });
      toast.success(`已发布给 ${res.published} 名学生`);
      void loadTasks();
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setPublishing(false);
    }
  };

  /* ------------------------------------------------ 动态行编辑 */

  const updateStep = (i: number, patch: Partial<StepRow>) =>
    patchForm({ steps: form.steps.map((s, idx) => (idx === i ? { ...s, ...patch } : s)) });
  const updateRubric = (i: number, patch: Partial<RubricRow>) =>
    patchForm({ rubric: form.rubric.map((r, idx) => (idx === i ? { ...r, ...patch } : r)) });

  const scenarioName = useMemo(
    () => scenarios.find((s) => s.id === form.scenarioId)?.label,
    [scenarios, form.scenarioId],
  );

  /* ------------------------------------------------ 渲染 */

  return (
    <div className="teacher-workbench-page teacher-task-publish-page">
      <PageHeader
        title="教学任务发布"
        sub="把企业岗位任务转化为课堂任务，发布到班级后学生即可执行"
      />

      {/* The outer grid keeps task selection available while the editor remains fluid. */}
      <div className="teacher-task-publish-layout">
        {/* ============ 左栏：我的教学任务 ============ */}
        <Card
          title="我的教学任务"
          actions={
            <Button
              size="sm"
              onClick={() => {
                setForm(emptyForm());
                setErrors({});
                resetTransient();
              }}
            >
              新建教学任务
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
              还没有教学任务，点击「新建教学任务」开始组装第一张任务卡。
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
                      setForm(formFromTask(task, capNames));
                      setErrors({});
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

        {/* ============ 右区：编辑器 + 常驻预览 ============ */}
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

            {/* 任务来源（PRD §5.2 四种来源） */}
            <Card title="任务来源">
              <Tabs
                tabs={SOURCE_TABS}
                active={sourceTab}
                onChange={(k) => setSourceTab(k as SourceTab)}
              />

              {sourceTab === "manual" ? (
                <div className="mt-3 flex flex-col gap-3">
                  <Textarea
                    rows={4}
                    value={manualText}
                    placeholder="粘贴或描述企业岗位任务，例如：对客服通话录音完成情感极性标注，要求区分投诉与咨询场景……"
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
                    AI 生成说明：基于任务描述召回知识库规范并定位能力节点，生成
                    标题/目标/步骤/评分规则/资源引用的完整草稿；草稿不落库，填入
                    表单后可继续编辑，审核确认后再保存或发布。
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
              ) : null}

              {sourceTab === "rag" ? (
                <div className="mt-3 flex flex-col gap-2">
                  <SearchInput
                    value={ragQuery}
                    onChange={() => undefined /* 见上方状态注释：输入过程由组件自管 */}
                    onSearch={(q, signal) => {
                      setRagQuery(q);
                      void searchRagDocs(q, signal);
                    }}
                    placeholder="搜索已发布资料…"
                  />
                  {ragSearching ? (
                    <div className="loading-block">
                      <Spinner /> 搜索中…
                    </div>
                  ) : (
                    <ul className="flex flex-col gap-2">
                      {(ragResults ?? []).map((doc) => (
                        <li key={doc.id} className="flex items-center justify-between gap-2">
                          <span>
                            {doc.title}
                            <span className="text-xs text-muted"> · v{doc.version}</span>
                          </span>
                          <Button size="sm" variant="secondary" onClick={() => addRagResource(doc)}>
                            添加
                          </Button>
                        </li>
                      ))}
                      {ragResults !== null && ragResults.length === 0 ? (
                        <li className="text-sm text-secondary">没有匹配的已发布资料</li>
                      ) : null}
                    </ul>
                  )}
                </div>
              ) : null}

              {sourceTab === "preset" ? (
                <div className="mt-3">
                  {presets === null ? (
                    <div className="loading-block">
                      <Spinner /> 加载中…
                    </div>
                  ) : (
                    <ul className="flex flex-col gap-2">
                      {presets.map((preset) => (
                        <li key={preset.id} className="flex items-center justify-between gap-2">
                          <span>
                            {preset.title}
                            <span className="text-xs text-muted">
                              {" "}
                              · {dataTypeLabel(preset.data_type)} · 难度 {preset.difficulty} · 约{" "}
                              {preset.est_minutes} 分钟
                            </span>
                          </span>
                          <Button size="sm" variant="secondary" onClick={() => applyPreset(preset)}>
                            使用模板
                          </Button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ) : null}

              {sourceTab === "history" ? (
                <div className="mt-3">
                  {(tasks ?? []).length === 0 ? (
                    <p className="text-sm text-secondary">暂无历史任务可复制</p>
                  ) : (
                    <ul className="flex flex-col gap-2">
                      {(tasks ?? []).map((task) => (
                        <li key={task.id} className="flex items-center justify-between gap-2">
                          <span>
                            {task.title}
                            <span className="text-xs text-muted"> · v{task.version}</span>
                          </span>
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => copyFromHistory(task)}
                          >
                            复制
                          </Button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ) : null}
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

            {/* 任务内容编辑（PRD §5.2 教师编辑：目标/步骤/资源/评分规则） */}
            <Card title="任务内容">
              <Field label="任务名称" required error={errors.title}>
                <Input
                  value={form.title}
                  invalid={!!errors.title}
                  placeholder="例如：客服语音情感标注实战"
                  onChange={(e) => patchForm({ title: e.target.value })}
                />
              </Field>
              <Field label="学习目标">
                <Textarea
                  rows={3}
                  value={form.goal}
                  placeholder="完成本任务后学生应达到的目标"
                  onChange={(e) => patchForm({ goal: e.target.value })}
                />
              </Field>
              <div className="grid teacher-task-fields">
                <Field label="数据类型">
                  <Select
                    options={DATA_TYPE_OPTIONS}
                    placeholder="不限"
                    value={form.dataType}
                    onChange={(e) => patchForm({ dataType: e.target.value })}
                  />
                </Field>
                <Field label="行业场景">
                  <Select
                    options={scenarios.map((s) => ({ value: s.id, label: s.label }))}
                    placeholder="通用 / 不限"
                    value={form.scenarioId}
                    onChange={(e) => patchForm({ scenarioId: e.target.value })}
                  />
                </Field>
              </div>

              {/* 关联能力（必填 ≥1）：搜索图谱 CAP 节点，芯片式多选 */}
              <Field
                label="关联能力"
                required
                error={errors.caps}
                hint="从能力图谱搜索并添加，至少 1 个"
              >
                <div className="flex flex-wrap gap-2 mb-2">
                  {form.caps.map((cap) => (
                    <span key={cap.id} className="tag flex items-center gap-1">
                      {cap.name}
                      <button
                        type="button"
                        aria-label={`移除 ${cap.name}`}
                        className="icon-btn"
                        style={{ padding: 0, width: 16, height: 16 }}
                        onClick={() =>
                          patchForm({ caps: form.caps.filter((c) => c.id !== cap.id) })
                        }
                      >
                        <X size={12} />
                      </button>
                    </span>
                  ))}
                </div>
                <SearchInput
                  value={capQuery}
                  onChange={() => undefined /* 见上方状态注释：输入过程由组件自管 */}
                  onSearch={(q, signal) => {
                    setCapQuery(q);
                    void searchCaps(q, signal);
                  }}
                  placeholder="搜索能力节点…"
                />
                <ul className="flex flex-col gap-1 mt-2">
                  {capResults
                    .filter((n) => !form.caps.some((c) => c.id === n.id))
                    .map((node) => (
                      <li key={node.id} className="flex items-center justify-between">
                        <span className="text-sm">{node.label}</span>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => {
                            patchForm({ caps: [...form.caps, { id: node.id, name: node.label }] });
                            setCapNames((m) => ({ ...m, [node.id]: node.label }));
                          }}
                        >
                          <Plus size={14} /> 添加
                        </Button>
                      </li>
                    ))}
                </ul>
              </Field>

              {/* 操作步骤（动态行：说明 + 注意事项 + 常见错误） */}
              <Field label="操作步骤">
                <div className="flex flex-col gap-3">
                  {form.steps.map((step, i) => (
                    <div
                      key={i}
                      style={{
                        border: "1px solid var(--color-border)",
                        borderRadius: "var(--radius-md)",
                        padding: "var(--space-3)",
                      }}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm text-secondary">步骤 {i + 1}</span>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`删除步骤 ${i + 1}`}
                          onClick={() =>
                            patchForm({ steps: form.steps.filter((_, idx) => idx !== i) })
                          }
                        >
                          <Trash2 size={14} />
                        </Button>
                      </div>
                      <Input
                        value={step.title}
                        placeholder="步骤说明（必填）"
                        onChange={(e) => updateStep(i, { title: e.target.value })}
                      />
                      <div className="grid teacher-task-step-fields mt-2">
                        <Input
                          value={step.notes}
                          placeholder="注意事项"
                          onChange={(e) => updateStep(i, { notes: e.target.value })}
                        />
                        <Input
                          value={step.commonErrors}
                          placeholder="常见错误"
                          onChange={(e) => updateStep(i, { commonErrors: e.target.value })}
                        />
                      </div>
                    </div>
                  ))}
                  <Button
                    variant="secondary"
                    onClick={() =>
                      patchForm({
                        steps: [...form.steps, { title: "", notes: "", commonErrors: "" }],
                      })
                    }
                  >
                    <Plus size={14} /> 添加步骤
                  </Button>
                </div>
              </Field>

              {/* 评分规则（动态行：评分项 + 期望 + 权重） */}
              <Field label="评分规则">
                <div className="flex flex-col gap-2">
                  {form.rubric.map((item, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <Input
                        value={item.key}
                        placeholder="评分项，如 accuracy"
                        onChange={(e) => updateRubric(i, { key: e.target.value })}
                      />
                      <Input
                        value={item.expected}
                        placeholder="期望值，如 ≥0.9"
                        onChange={(e) => updateRubric(i, { expected: e.target.value })}
                      />
                      <Input
                        type="number"
                        value={item.weight}
                        placeholder="权重"
                        style={{ width: 90 }}
                        onChange={(e) => updateRubric(i, { weight: e.target.value })}
                      />
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`删除评分项 ${i + 1}`}
                        onClick={() =>
                          patchForm({ rubric: form.rubric.filter((_, idx) => idx !== i) })
                        }
                      >
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  ))}
                  <Button
                    variant="secondary"
                    onClick={() =>
                      patchForm({ rubric: [...form.rubric, { key: "", expected: "", weight: "" }] })
                    }
                  >
                    <Plus size={14} /> 添加评分项
                  </Button>
                </div>
              </Field>

              {/* 学习资源（必填 ≥1）：RAG 资料 / 模板单元 / 手动链接 */}
              <Field
                label="学习资源"
                required
                error={errors.resources}
                hint="RAG 资料会带引用信息展示给学生"
              >
                <ul className="flex flex-col gap-2 mb-2">
                  {form.resources.map((res, i) => (
                    <li key={i} className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-2">
                        <Tag>{RESOURCE_TYPE_LABELS[res.type] ?? res.type}</Tag>
                        <span>{res.title}</span>
                        {res.url ? <span className="text-xs text-muted">{res.url}</span> : null}
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`移除资源 ${res.title}`}
                        onClick={() =>
                          patchForm({ resources: form.resources.filter((_, idx) => idx !== i) })
                        }
                      >
                        <Trash2 size={14} />
                      </Button>
                    </li>
                  ))}
                </ul>
                <ManualResourceAdder
                  onAdd={(title, url) =>
                    patchForm({ resources: [...form.resources, { type: "link", title, url }] })
                  }
                />
              </Field>
            </Card>

            {/* 发布设置（PRD §5.2：班级 / 截止时间 / 是否计入掌握度） */}
            <Card title="发布设置">
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

              {/* 已发布任务的截止时间调整（PRD-06 §10.1）：与上面的"发布到新
                  班级"截止时间相互独立——这里 PATCH 已发学生副本，不升版本 */}
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
                <Button variant="secondary" onClick={() => void saveDraft()} loading={saving}>
                  保存草稿
                </Button>
                <Button onClick={() => void publish()} loading={publishing}>
                  发布
                </Button>
              </div>
            </Card>
          </div>

          {/* ============ 常驻预览（PRD §5.4：发布前必须展示预览） ============ */}
          <div className="teacher-task-preview">
            <Card title="任务卡预览">
              <p className="text-xs text-muted mb-3">
                发布前请确认预览内容，学生看到的就是这张任务卡
              </p>
              <h3>{form.title.trim() || "未命名任务"}</h3>
              {form.goal.trim() ? <p className="text-sm text-secondary mt-2">{form.goal}</p> : null}
              <div className="flex flex-wrap gap-2 mt-3">
                <Tag>{dataTypeLabel(form.dataType)}</Tag>
                <Tag>{form.scenarioId ? (scenarioName ?? form.scenarioId) : "通用场景"}</Tag>
                <Tag>{form.counts ? "计入掌握度" : "不计入掌握度"}</Tag>
              </div>

              <h4 className="mt-4">关联能力（{form.caps.length}）</h4>
              {form.caps.length === 0 ? (
                <p className="text-sm text-danger">尚未关联能力节点（发布必需）</p>
              ) : (
                <div className="flex flex-wrap gap-2 mt-2">
                  {form.caps.map((c) => (
                    <Tag key={c.id}>{c.name}</Tag>
                  ))}
                </div>
              )}

              <h4 className="mt-4">
                操作步骤（{form.steps.filter((s) => s.title.trim()).length}）
              </h4>
              <ol
                className="flex flex-col gap-2 mt-2"
                style={{ listStyle: "decimal", paddingLeft: "var(--space-5)" }}
              >
                {form.steps
                  .filter((s) => s.title.trim())
                  .map((s, i) => (
                    <li key={i}>
                      <div>{s.title}</div>
                      {s.notes.trim() ? (
                        <div className="text-xs text-secondary">注意：{s.notes}</div>
                      ) : null}
                      {s.commonErrors.trim() ? (
                        <div className="text-xs text-secondary">常见错误：{s.commonErrors}</div>
                      ) : null}
                    </li>
                  ))}
              </ol>

              {form.rubric.some((r) => r.key.trim()) ? (
                <>
                  <h4 className="mt-4">评分规则</h4>
                  <ul className="flex flex-col gap-1 mt-2">
                    {form.rubric
                      .filter((r) => r.key.trim())
                      .map((r, i) => (
                        <li key={i} className="text-sm">
                          {r.key}：{r.expected || "—"}
                          {r.weight.trim() ? `（权重 ${r.weight}）` : ""}
                        </li>
                      ))}
                  </ul>
                </>
              ) : null}

              <h4 className="mt-4">学习资源（{form.resources.length}）</h4>
              {form.resources.length === 0 ? (
                <p className="text-sm text-danger">尚未添加来源资料（发布必需）</p>
              ) : (
                <div className="flex flex-col gap-2 mt-2">
                  {form.resources.map((res, i) =>
                    res.citation ? (
                      <CitationCard key={i} citation={res.citation} index={i + 1} />
                    ) : (
                      <div key={i} className="citation-card">
                        <div className="citation-card-title">
                          [{i + 1}] {res.title}
                        </div>
                        <div className="citation-card-meta">
                          {RESOURCE_TYPE_LABELS[res.type] ?? res.type}
                          {res.url ? ` · ${res.url}` : ""}
                        </div>
                      </div>
                    ),
                  )}
                </div>
              )}

              <h4 className="mt-4">发布信息</h4>
              <p className="text-sm text-secondary mt-2">
                班级：{classes.find((c) => c.id === form.classId)?.name ?? "未选择"}
                <br />
                截止：{form.dueAt ? fmtDateTime(new Date(form.dueAt).toISOString()) : "未设置"}
              </p>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}

/** 手动添加外部链接资源（标题 + URL 两行输入，内部管理自己的草稿态） */
function ManualResourceAdder({ onAdd }: { onAdd: (title: string, url: string) => void }) {
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  return (
    <div className="flex items-center gap-2 teacher-resource-adder">
      <Input value={title} placeholder="资源标题" onChange={(e) => setTitle(e.target.value)} />
      <Input value={url} placeholder="链接 URL（可选）" onChange={(e) => setUrl(e.target.value)} />
      <Button
        variant="secondary"
        disabled={!title.trim()}
        onClick={() => {
          onAdd(title.trim(), url.trim());
          setTitle("");
          setUrl("");
        }}
      >
        <Plus size={14} /> 添加资源
      </Button>
    </div>
  );
}
