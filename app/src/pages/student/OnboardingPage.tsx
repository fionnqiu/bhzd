/**
 * 入学引导页（/onboarding，v3.0 §11.1 首次使用流程）。
 *
 * 三步向导：① 方向与目标（专业 + 目标类型 chips + 目标一句话）→
 * ② 入学测评（8 题单选，全答完才可提交）→ ③ 结果页（得分 + 初始能力地图）。
 * 「稍后再测」调用 POST /api/onboarding/skip 后回首页；测评是一次性初始定位
 * （重复提交后端 409），完成后状态持久化在服务端，前端不另存标记。
 *
 * 为什么把 useOnboardingGate 放在本文件：门禁的数据源（GET assessment 的
 * status）与向导本页是同一端点，放一起保证"什么时候该来这页"只有一个事实
 * 来源；指挥舱等学生页只需一行 hook 调用即可接入强制测评。
 *
 * 类型说明：api/types.ts 由其他任务并行维护，本页 DTO 一律页内声明
 * （与后端 profile.py 的响应逐字段对齐）。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import {
  Button,
  Card,
  ErrorState,
  Field,
  Input,
  MasteryBadge,
  PageHeader,
  ProgressBar,
  Select,
  Spinner,
  useToast,
} from "../../components";
import { capNameOf, errMsg, useCapNames } from "./shared";

/* ---------------------------------------------------------------- 页内 DTO（对齐 profile.py） */

/** GET /api/onboarding/assessment 的下发题目（已剥离 answer_index，防作弊） */
export interface OnboardingQuestion {
  id: string;
  question: string;
  options: string[];
  cap_id: string;
  data_type: string;
}

export type OnboardingStatus = "not_started" | "completed" | "skipped";

export interface AssessmentResponse {
  status: OnboardingStatus;
  questions: OnboardingQuestion[];
  total: number;
  /** 已完成时回带的上次成绩摘要（score/correct/completed_at） */
  result?: { score: number | null; correct: number | null; completed_at: string | null };
}

/** mastery.service.apply_updates 的逐能力应用结果 */
export interface MasteryAppliedRow {
  cap_id: string;
  scenario_id: string;
  delta: number;
  old_score: number | null;
  new_score: number | null;
}

export interface AssessmentSubmitResponse {
  score: number;
  correct: number;
  total: number;
  mastery_applied: MasteryAppliedRow[];
  status: OnboardingStatus;
}

/* ---------------------------------------------------------------- 入学门禁 hook */

/**
 * 入学测评门禁：学生页挂载时查一次测评状态，not_started 即重定向 /onboarding。
 * completed/skipped 都不再由服务端返回 not_started，因此"完成后永不重定向"
 * 自然成立，前端无需本地标记；查询失败静默放过（网络抖动不该把学生锁在门外）。
 */
export function useOnboardingGate(): void {
  const navigate = useNavigate();
  useEffect(() => {
    const controller = new AbortController();
    api
      .get<AssessmentResponse>("/api/onboarding/assessment", undefined, { signal: controller.signal })
      .then((res) => {
        if (!controller.signal.aborted && res.status === "not_started") {
          navigate("/onboarding", { replace: true });
        }
      })
      .catch(() => {
        /* 门禁查询失败不阻断页面：下次进学生页会再查 */
      });
    return () => controller.abort();
  }, [navigate]);
}

/* ---------------------------------------------------------------- 常量 */

/** 专业方向预设（PRD 面向高职人工智能技术应用专业群；允许自由输入补充） */
const MAJOR_OPTIONS = [
  { value: "", label: "请选择专业方向" },
  { value: "人工智能技术应用", label: "人工智能技术应用" },
  { value: "大数据技术", label: "大数据技术" },
  { value: "软件技术", label: "软件技术" },
  { value: "计算机应用技术", label: "计算机应用技术" },
  { value: "custom", label: "其他（手动输入）" },
];

/** 目标类型 chips（单选：目标类型决定后续推荐口径的粗粒度分群） */
const GOAL_CHIPS = ["入门", "专项", "考证", "岗位"] as const;

type WizardStep = "goal" | "quiz" | "result";

export default function OnboardingPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const capNames = useCapNames();

  const [step, setStep] = useState<WizardStep>("goal");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [questions, setQuestions] = useState<OnboardingQuestion[]>([]);
  /** 已完成用户直接进入本页时展示的上次成绩（服务端回带，免重答） */
  const [completedResult, setCompletedResult] = useState<AssessmentResponse["result"]>(undefined);

  // ① 方向与目标
  const [majorChoice, setMajorChoice] = useState("");
  const [customMajor, setCustomMajor] = useState("");
  const [goalChip, setGoalChip] = useState<string>("");
  const [goalText, setGoalText] = useState("");

  // ② 测评作答（qid → 选项下标；提交体契约即 answers:{qid:index}）
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitResult, setSubmitResult] = useState<AssessmentSubmitResponse | null>(null);
  const [skipping, setSkipping] = useState(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<AssessmentResponse>("/api/onboarding/assessment", undefined, { signal });
      if (signal?.aborted) return;
      setQuestions(res.questions);
      if (res.status === "completed") {
        // 已完成：直接展示结果页（重答会被后端 409，不必让学生再填一遍）
        setCompletedResult(res.result);
        setStep("result");
      }
    } catch (err) {
      if (!signal?.aborted) setError(errMsg(err));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  /** 实际提交的专业：预设值或自由输入（custom 时取输入框内容） */
  const major = useMemo(
    () => (majorChoice === "custom" ? customMajor.trim() : majorChoice),
    [majorChoice, customMajor],
  );

  /** 提交给后端的 goal：目标类型 + 一句话拼成完整目标描述 */
  const goal = useMemo(() => {
    const parts = [goalChip, goalText.trim()].filter(Boolean);
    return parts.length > 0 ? parts.join("：") : undefined;
  }, [goalChip, goalText]);

  const answeredCount = Object.keys(answers).length;
  const allAnswered = questions.length > 0 && answeredCount === questions.length;

  /** 跳过测评（幂等）：标记 skipped 后回首页，门禁从此放行 */
  const skip = async () => {
    setSkipping(true);
    try {
      await api.post("/api/onboarding/skip");
      navigate("/", { replace: true });
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setSkipping(false);
    }
  };

  /** 提交测评：全答完才允许（每题对应一个能力的初始掌握度，漏答会拉低定位精度） */
  const submit = async () => {
    if (!allAnswered) return;
    setSubmitting(true);
    try {
      const res = await api.post<AssessmentSubmitResponse>("/api/onboarding/assessment", {
        answers,
        goal,
        major: major || undefined,
      });
      setSubmitResult(res);
      setStep("result");
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="loading-block">
        <Spinner large /> 正在加载入学引导…
      </div>
    );
  }
  if (error) {
    return <ErrorState message={error} onRetry={load} />;
  }

  return (
    <div>
      <PageHeader
        title="入学引导"
        sub="两步完成初始能力定位，让推荐从第一天起就适合你"
      />

      {/* 步骤指示（纯展示：步骤推进由按钮驱动，防跳步漏答） */}
      <div className="flex items-center gap-2 mb-4" aria-label="引导步骤">
        {[
          ["goal", "① 方向与目标"],
          ["quiz", "② 入学测评"],
          ["result", "③ 初始能力地图"],
        ].map(([key, label]) => (
          <span
            key={key}
            className={`badge ${step === key ? "badge-primary" : "badge-neutral"}`}
          >
            {label}
          </span>
        ))}
      </div>

      {step === "goal" ? (
        <Card title="方向与目标">
          <div className="flex flex-col gap-4">
            <Field label="专业方向" hint="选择你的专业，或选「其他」手动输入">
              <div className="flex flex-col gap-2">
                <Select
                  aria-label="专业方向"
                  value={majorChoice}
                  options={MAJOR_OPTIONS}
                  onChange={(e) => setMajorChoice(e.target.value)}
                />
                {majorChoice === "custom" ? (
                  <Input
                    aria-label="自定义专业"
                    placeholder="请输入你的专业方向"
                    value={customMajor}
                    onChange={(e) => setCustomMajor(e.target.value)}
                  />
                ) : null}
              </div>
            </Field>
            <Field label="目标类型" hint="你当前最主要的学习目标">
              <div className="flex items-center gap-2 flex-wrap" role="group" aria-label="目标类型">
                {GOAL_CHIPS.map((chip) => (
                  <button
                    key={chip}
                    type="button"
                    aria-pressed={goalChip === chip}
                    className={`badge ${goalChip === chip ? "badge-primary" : "badge-neutral"}`}
                    style={{ border: "none", cursor: "pointer" }}
                    onClick={() => setGoalChip(goalChip === chip ? "" : chip)}
                  >
                    {chip}
                  </button>
                ))}
              </div>
            </Field>
            <Field label="目标一句话" hint="选填，例如：三个月内掌握文本标注并通过 1+X 考试">
              <Input
                aria-label="目标一句话"
                placeholder="用一句话描述你的学习目标"
                value={goalText}
                onChange={(e) => setGoalText(e.target.value)}
              />
            </Field>
            <div className="flex items-center justify-between">
              <Button variant="ghost" loading={skipping} onClick={skip}>
                稍后再测
              </Button>
              <Button onClick={() => setStep("quiz")}>下一步：入学测评</Button>
            </div>
          </div>
        </Card>
      ) : null}

      {step === "quiz" ? (
        <Card title={`入学测评（共 ${questions.length} 题，全部作答后提交）`}>
          <div className="flex flex-col gap-4">
            {/* 作答进度：N/总数，与进度条同值（已答 4 题即 50%） */}
            <div className="flex items-center gap-3">
              <div style={{ flex: 1 }}>
                <ProgressBar value={questions.length ? answeredCount / questions.length : 0} />
              </div>
              <span className="text-xs text-secondary">
                已答 {answeredCount}/{questions.length}
              </span>
            </div>
            {questions.map((question, qIndex) => (
              <fieldset key={question.id} style={{ border: "none", margin: 0, padding: 0 }}>
                <legend className="text-sm mb-2" style={{ padding: 0 }}>
                  {qIndex + 1}. {question.question}
                </legend>
                <div className="flex flex-col gap-2" role="radiogroup" aria-label={`第 ${qIndex + 1} 题`}>
                  {question.options.map((option, oIndex) => (
                    <label key={oIndex} className="flex items-center gap-2 text-sm text-secondary">
                      <input
                        type="radio"
                        name={question.id}
                        checked={answers[question.id] === oIndex}
                        onChange={() =>
                          setAnswers((prev) => ({ ...prev, [question.id]: oIndex }))
                        }
                      />
                      {option}
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Button variant="ghost" onClick={() => setStep("goal")}>
                  上一步
                </Button>
                <Button variant="ghost" loading={skipping} onClick={skip}>
                  稍后再测
                </Button>
              </div>
              <Button loading={submitting} disabled={!allAnswered} onClick={submit}>
                {allAnswered ? "提交测评" : `还有 ${questions.length - answeredCount} 题未作答`}
              </Button>
            </div>
          </div>
        </Card>
      ) : null}

      {step === "result" ? (
        <Card title="测评结果">
          <div className="flex flex-col gap-4">
            {submitResult ? (
              <>
                <p className="text-sm">
                  本次得分：<strong>{submitResult.correct}</strong> / {submitResult.total} 题答对
                  （{Math.round(submitResult.score * 100)} 分）
                </p>
                <div>
                  <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                    初始能力地图
                  </h3>
                  <p className="text-xs text-muted mb-3">
                    根据你的作答生成的基础掌握度，后续练习与诊断会持续更新。
                  </p>
                  <ul className="flex flex-col gap-3">
                    {submitResult.mastery_applied.map((row) => (
                      <li key={`${row.cap_id}|${row.scenario_id}`}>
                        <div className="flex items-center justify-between gap-3 mb-2">
                          <span className="text-sm">{capNameOf(capNames, row.cap_id)}</span>
                          <MasteryBadge score={row.new_score} />
                        </div>
                        <ProgressBar value={row.new_score ?? 0} />
                      </li>
                    ))}
                  </ul>
                </div>
              </>
            ) : (
              // 历史已完成用户直接进本页：服务端只回带成绩摘要，如实展示不重答
              <p className="text-sm">
                你已完成入学测评
                {completedResult?.correct != null && completedResult?.score != null
                  ? `：答对 ${completedResult.correct} 题（${Math.round(completedResult.score * 100)} 分）`
                  : ""}
                。入学测评为一次性初始定位，可在个人中心查看最新能力地图。
              </p>
            )}
            <div className="flex items-center justify-end gap-2">
              <Button variant="secondary" onClick={() => navigate("/profile")}>
                查看能力地图
              </Button>
              <Button onClick={() => navigate("/")}>进入指挥舱</Button>
            </div>
          </div>
        </Card>
      ) : null}
    </div>
  );
}
