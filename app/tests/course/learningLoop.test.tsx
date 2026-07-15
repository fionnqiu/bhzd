import "@testing-library/jest-dom/vitest";

import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/app/App";
import type { TeachingUnit } from "../../src/data/contracts";
import { teachingUnits } from "../../src/data/rawData";
import { createLearnerSafeExampleProjection } from "../../src/features/course/learnerSafeStructured";
import { createEmptyResponseShape } from "../../src/features/course/StructuredResponseEditor";
import {
  createProfileStore,
  type LearningProfileSnapshot,
  type ProfileStorage,
  type ProfileStore,
} from "../../src/state/profileStore";

class MemoryStorage implements ProfileStorage {
  readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }
}

const createSnapshot = (
  overrides: Partial<LearningProfileSnapshot> = {},
): LearningProfileSnapshot => ({
  version: 1,
  generalMastery: {},
  scenarioMastery: {},
  attempts: [],
  lastMode: null,
  lastScenario: null,
  lastUnit: null,
  lastNode: null,
  ...overrides,
});

const createTestStore = (
  overrides: Partial<ProfileStore> = {},
): ProfileStore => ({
  snapshot: () => createSnapshot(),
  getLoadError: () => null,
  recordExercise: vi.fn(),
  recordDiagnostic: vi.fn(),
  setContext: vi.fn(),
  reset: vi.fn(),
  ...overrides,
});

const domainButtonNames = {
  text: "文本课程，5 个可学习单元",
  image: "图像课程，5 个可学习单元",
  audio: "语音课程，6 个可学习单元",
  video: "视频课程，3 个可学习单元",
} as const;

const findUnit = (id: string): TeachingUnit => {
  const unit = teachingUnits.units.find((candidate) => candidate.id === id);
  if (unit === undefined) {
    throw new Error(`Missing canonical teaching unit ${id}.`);
  }
  return unit;
};

const openLesson = (title: string): void => {
  fireEvent.click(
    screen.getByRole("button", { name: new RegExp(title, "u") }),
  );
};

const getLessonSection = (heading: string): HTMLElement => {
  const section = screen
    .getByRole("heading", { name: heading })
    .closest("section");
  if (section === null) {
    throw new Error(`Missing lesson section ${heading}.`);
  }
  return section;
};

afterEach(() => {
  cleanup();
});

describe("course learning loop", () => {
  it("moves focus into an opened lesson and restores it to the triggering course card", () => {
    render(<App profileStore={createTestStore()} />);
    const courseName = "校验封闭文本标签集";
    const trigger = screen.getByRole("button", {
      name: `打开课程：${courseName}`,
    });

    trigger.focus();
    fireEvent.click(trigger);

    const lessonHeading = screen.getByRole("heading", { name: courseName });
    expect(lessonHeading).toHaveAttribute("tabindex", "-1");
    expect(lessonHeading).toHaveFocus();
    expect(document.activeElement).not.toBe(document.body);

    fireEvent.click(
      screen.getByRole("button", { name: "返回课程列表" }),
    );

    const restoredTrigger = screen.getByRole("button", {
      name: `打开课程：${courseName}`,
    });
    expect(restoredTrigger).toHaveFocus();
    expect(document.activeElement).not.toBe(document.body);
  });

  it("evaluates a structured text answer and records general mastery", () => {
    const profileStore = createProfileStore(
      new MemoryStorage(),
      () => new Date("2026-07-15T04:00:00.000Z"),
    );
    render(<App profileStore={profileStore} />);

    fireEvent.click(
      screen.getByRole("button", {
        name: "文本课程，5 个可学习单元",
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: /校验封闭文本标签集/ }),
    );

    const editor = screen.getByRole("textbox", { name: "结构化答案" });
    expect(JSON.parse((editor as HTMLTextAreaElement).value)).toEqual({
      labels: [""],
    });
    expect(editor).not.toHaveValue(expect.stringContaining("negative"));

    fireEvent.change(editor, {
      target: { value: '{"labels":["negative"]}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交自检" }));

    expect(screen.getByRole("status")).toHaveTextContent("通过");
    expect(screen.getByRole("status")).toHaveTextContent("回答正确");
    expect(screen.getByText("规则依据")).toBeVisible();
    expect(screen.getByText("掌握度")).toBeVisible();
    expect(
      screen.getByRole("progressbar", {
        name: "CAP-TXT-LABEL-VALIDATE-001 掌握度 35%",
      }),
    ).toHaveValue(0.35);

    const snapshot = profileStore.snapshot();
    expect(snapshot.attempts).toHaveLength(1);
    expect(snapshot.attempts[0]).toMatchObject({
      kind: "exercise",
      capabilityId: "CAP-TXT-LABEL-VALIDATE-001",
      scenarioId: null,
      score: 1,
      evaluationVersion: "1.1.0",
    });
    expect(snapshot.generalMastery["CAP-TXT-LABEL-VALIDATE-001"]).toBeCloseTo(
      0.35,
    );
    expect(snapshot.scenarioMastery).toEqual({});
  });

  it("keeps invalid JSON recoverable and does not write mastery", () => {
    const profileStore = createProfileStore(new MemoryStorage());
    render(<App profileStore={profileStore} />);
    openLesson("校验封闭文本标签集");

    const editor = screen.getByRole("textbox", { name: "结构化答案" });
    fireEvent.change(editor, { target: { value: '{"labels":[' } });
    fireEvent.click(screen.getByRole("button", { name: "提交自检" }));

    expect(screen.getByRole("alert")).toHaveTextContent("JSON");
    expect(screen.getByRole("alert")).toHaveTextContent("语法");
    expect(editor).toHaveValue('{"labels":[');
    expect(profileStore.snapshot().attempts).toHaveLength(0);
    expect(profileStore.snapshot().generalMastery).toEqual({});
    expect(profileStore.snapshot().scenarioMastery).toEqual({});
  });

  it("shows deterministic diagnostic feedback and records a classified failure", () => {
    const profileStore = createProfileStore(new MemoryStorage());
    render(<App profileStore={profileStore} />);
    openLesson("校验封闭文本标签集");

    fireEvent.change(
      screen.getByRole("textbox", { name: "结构化答案" }),
      { target: { value: '{"labels":["neutral"]}' } },
    );
    fireEvent.click(screen.getByRole("button", { name: "提交自检" }));

    const feedback = screen.getByRole("status");
    expect(feedback).toHaveTextContent("未通过");
    expect(feedback).toHaveTextContent("label_not_in_configured_set");
    expect(feedback).toHaveTextContent(
      "neutral 不属于本题 configured_labels",
    );
    expect(feedback).toHaveTextContent("只提交 positive 或 negative");
    expect(profileStore.snapshot().attempts).toHaveLength(1);
    expect(profileStore.snapshot().attempts[0]).toMatchObject({
      kind: "exercise",
      score: 0,
      capabilityId: "CAP-TXT-LABEL-VALIDATE-001",
    });
  });

  it("shows deterministic fallback feedback without recording an unclassified result", () => {
    const profileStore = createProfileStore(new MemoryStorage());
    render(<App profileStore={profileStore} />);
    openLesson("校验封闭文本标签集");

    fireEvent.change(
      screen.getByRole("textbox", { name: "结构化答案" }),
      { target: { value: '{"labels":[]}' } },
    );
    fireEvent.click(screen.getByRole("button", { name: "提交自检" }));

    const feedback = screen.getByRole("status");
    expect(feedback).toHaveTextContent("未分类");
    expect(feedback).toHaveTextContent(
      "提交未同时满足候选标签、封闭词表、单标签基数和原样匹配政策",
    );
    expect(profileStore.snapshot().attempts).toHaveLength(0);
    expect(profileStore.snapshot().generalMastery).toEqual({});
  });

  it("shows a manual-review partial score and remediation without recording mastery", () => {
    const profileStore = createProfileStore(new MemoryStorage());
    render(<App profileStore={profileStore} />);
    openLesson("处理意图歧义与允许答案集");

    fireEvent.change(
      screen.getByRole("textbox", { name: "结构化答案" }),
      {
        target: {
          value: JSON.stringify({
            primary_intent: null,
            candidate_intents: ["refund_status", "order_status"],
            ambiguity: "unresolved",
          }),
        },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "提交自检" }));

    const feedback = screen.getByRole("status");
    expect(feedback).toHaveTextContent("人工复核");
    expect(feedback).toHaveTextContent("0.5");
    expect(feedback).toHaveTextContent(
      "已完整保留两个候选意图并明确声明优先级未解决",
    );
    expect(feedback).toHaveTextContent("保持 primary_intent 为 null");
    expect(profileStore.snapshot().attempts).toHaveLength(0);
    expect(profileStore.snapshot().generalMastery).toEqual({});
    expect(profileStore.snapshot().scenarioMastery).toEqual({});
  });

  it("passes the selected scenario to every classified capability record", () => {
    const recordExercise = vi.fn();
    const scenarioId = "SCN-CUSTOMER-SERVICE-001";
    const store = createTestStore({
      snapshot: () => createSnapshot({ lastScenario: scenarioId }),
      recordExercise,
    });
    render(<App profileStore={store} />);
    openLesson("校验封闭文本标签集");

    fireEvent.change(
      screen.getByRole("textbox", { name: "结构化答案" }),
      { target: { value: '{"labels":["negative"]}' } },
    );
    fireEvent.click(screen.getByRole("button", { name: "提交自检" }));

    expect(recordExercise).toHaveBeenCalledOnce();
    expect(recordExercise).toHaveBeenCalledWith({
      capabilityId: "CAP-TXT-LABEL-VALIDATE-001",
      score: 1,
      scenarioId,
      evaluationVersion: "1.1.0",
    });
    expect(screen.getByText("通用掌握度")).toBeVisible();
    expect(screen.getByText("场景掌握度")).toBeVisible();
  });

  it("keeps hidden evaluator payloads out of the lesson before submission", () => {
    render(<App profileStore={createTestStore()} />);
    openLesson("处理意图歧义与允许答案集");

    const editor = screen.getByRole("textbox", { name: "结构化答案" });
    expect(JSON.parse((editor as HTMLTextAreaElement).value)).toEqual({
      primary_intent: "",
      candidate_intents: [""],
      ambiguity: "",
    });
    expect(editor).not.toHaveValue(expect.stringContaining("refund_status"));
    expect(document.body).not.toHaveTextContent("resolved_by_explicit_refund");
    expect(document.body).not.toHaveTextContent("billing_issue");
    expect(document.body).not.toHaveTextContent("diagnostic_precedence");
    expect(document.body).not.toHaveTextContent("pass_score");
    expect(document.body).not.toHaveTextContent(
      "已完整保留两个候选意图并明确声明优先级未解决",
    );
    expect(
      screen.queryByRole("button", { name: "载入标准结构示例" }),
    ).not.toBeInTheDocument();
  });

  it("shows learner-safe example context without pre-submit answers or evaluation payloads", () => {
    const unit = structuredClone(
      findUnit("TU-AUDIO-EMOTION-PARALINGUISTICS-001"),
    );
    const positiveExamples = unit.positive_examples;
    if (!Array.isArray(positiveExamples)) {
      throw new Error("Expected canonical positive examples.");
    }
    const firstPositive = positiveExamples[0];
    if (typeof firstPositive !== "object" || firstPositive === null) {
      throw new Error("Expected a canonical positive example object.");
    }
    const positiveInput = (firstPositive as Record<string, unknown>).input;
    if (typeof positiveInput !== "object" || positiveInput === null) {
      throw new Error("Expected canonical positive example input.");
    }
    Object.assign(positiveInput, {
      learner_context: {
        note: "经审核的嵌套输入上下文",
        answer: "LEAKED_ANSWER_SENTINEL",
        allowed_answers: ["LEAKED_ALLOWED_ANSWER_SENTINEL"],
        diagnostic_submission: "LEAKED_DIAGNOSTIC_SENTINEL",
        evaluation: { version: "LEAKED_EVALUATION_SENTINEL" },
        pass_score: 0.91,
        diagnostic_precedence: ["LEAKED_PRECEDENCE_SENTINEL"],
      },
    });
    Object.assign(firstPositive, {
      fault_model: "LEAKED_FAULT_MODEL_SENTINEL",
      internal_review_payload: "LEAKED_UNKNOWN_TOP_LEVEL_SENTINEL",
    });

    render(
      <App
        repository={{ listConsumableUnits: () => [unit] }}
        profileStore={createTestStore()}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "语音课程，1 个可学习单元",
      }),
    );
    openLesson("分轨标注语音情感与副语言事件");

    const positiveSection = screen
      .getByRole("heading", { name: "正例" })
      .closest("section");
    const negativeSection = screen
      .getByRole("heading", { name: "反例" })
      .closest("section");
    if (positiveSection === null || negativeSection === null) {
      throw new Error("Expected example sections.");
    }
    const exampleText = `${positiveSection.textContent ?? ""}${negativeSection.textContent ?? ""}`;

    expect(positiveSection).toHaveTextContent("emo-example-001");
    expect(positiveSection).toHaveTextContent("经审核的嵌套输入上下文");
    expect(positiveSection).toHaveTextContent(
      "笑声作为独立事件保留区间；整体情感依据本题可听证据和本地枚举提交 joy。",
    );
    expect(positiveSection).toHaveTextContent("SRC-POLICY-AUDIO-TASK4-001");

    for (const hiddenValue of [
      '"expected"',
      '"submitted"',
      '"answer"',
      '"allowed_answers"',
      '"diagnostic_submission"',
      '"evaluation"',
      '"pass_score"',
      '"diagnostic_precedence"',
      "emotion_event_conflation",
      "LEAKED_ANSWER_SENTINEL",
      "LEAKED_ALLOWED_ANSWER_SENTINEL",
      "LEAKED_DIAGNOSTIC_SENTINEL",
      "LEAKED_EVALUATION_SENTINEL",
      "LEAKED_PRECEDENCE_SENTINEL",
      "LEAKED_FAULT_MODEL_SENTINEL",
      "LEAKED_UNKNOWN_TOP_LEVEL_SENTINEL",
    ]) {
      expect(exampleText).not.toContain(hiddenValue);
    }
  });

  it("sanitizes policy structures and raw pass criteria across canonical image lessons", () => {
    render(<App profileStore={createTestStore()} />);
    fireEvent.click(
      screen.getByRole("button", { name: domainButtonNames.image }),
    );

    openLesson("区分遮挡与画面截断");
    const boundaryCases = getLessonSection("边界案例");
    expect(boundaryCases).toHaveTextContent(
      "目标轮廓在画面内闭合，但中段被前景栏杆遮住",
    );
    expect(boundaryCases).not.toHaveTextContent('"expected"');
    expect(getLessonSection("规则说明")).toHaveTextContent(
      "两个条件独立判断",
    );
    expect(getLessonSection("通过条件")).not.toHaveTextContent("score ==");
    fireEvent.click(
      screen.getByRole("button", { name: "返回课程列表" }),
    );

    openLesson("判定关键点可见性");
    const visibilityPolicy = getLessonSection("可见性策略");
    expect(visibilityPolicy).toHaveTextContent(
      "画面内关键点缺少足以区分直接可见与前景遮挡的证据",
    );
    expect(visibilityPolicy).not.toHaveTextContent('"submission"');
    expect(visibilityPolicy).not.toHaveTextContent('"decision": "unknown"');
    const exerciseInput = getLessonSection("练习输入");
    expect(exerciseInput).toHaveTextContent('"hidden_region": "left_knee"');
    expect(exerciseInput).toHaveTextContent('"allowed_visibility_values"');
    expect(getLessonSection("通过条件")).not.toHaveTextContent("score ==");
    fireEvent.click(
      screen.getByRole("button", { name: "返回课程列表" }),
    );

    openLesson("规范多边形有序顶点");
    expect(
      screen.queryByRole("heading", { name: "校验优先级" }),
    ).not.toBeInTheDocument();
    expect(getLessonSection("规则说明")).toHaveTextContent(
      "多边形至少包含 3 个互异顶点",
    );
    expect(document.body).not.toHaveTextContent("score == 1.0");
  });

  it("redacts canonical scoring and diagnostic-order clauses from rule instructions", () => {
    render(<App profileStore={createTestStore()} />);

    openLesson("处理意图歧义与允许答案集");
    const intentRules = getLessonSection("规则说明");
    expect(intentRules).toHaveTextContent(
      "Label Studio Choices 候选文档仅说明可配置和提交选项",
    );
    expect(intentRules).toHaveTextContent(
      "若两个意图均被识别但优先级未解决",
    );
    expect(intentRules).not.toHaveTextContent("refund_status 为满分主意图");
    expect(intentRules).not.toHaveTextContent("固定得 0.5 分");
    fireEvent.click(
      screen.getByRole("button", { name: "返回课程列表" }),
    );

    fireEvent.click(
      screen.getByRole("button", { name: domainButtonNames.image }),
    );
    openLesson("规范多边形有序顶点");
    const polygonRules = getLessonSection("规则说明");
    expect(polygonRules).toHaveTextContent("多边形至少包含 3 个互异顶点");
    expect(polygonRules).not.toHaveTextContent("校验顺序固定为");
    expect(polygonRules).not.toHaveTextContent("首个失败项为错误码");
  });

  it("sanitizes learner inputs, response spaces, paths, and practice variants", () => {
    render(<App profileStore={createTestStore()} />);
    fireEvent.click(
      screen.getByRole("button", { name: domainButtonNames.audio }),
    );

    openLesson("按可听证据标注语种与方言");
    const languageResponseSpace = getLessonSection("响应空间");
    expect(languageResponseSpace).toHaveTextContent(
      '"configured_bcp47_labels"',
    );
    expect(languageResponseSpace).toHaveTextContent("cmn");
    expect(languageResponseSpace).not.toHaveTextContent(
      '"recognized_submissions"',
    );
    expect(languageResponseSpace).not.toHaveTextContent("standard_answer");
    expect(languageResponseSpace).not.toHaveTextContent('"unmatched_behavior"');

    const languageVariants = getLessonSection("练习变体");
    expect(languageVariants).toHaveTextContent("完整可辨识普通话句子");
    expect(languageVariants).toHaveTextContent('"configured_labels"');
    for (const hiddenValue of [
      '"submitted"',
      '"ordered_error_precedence"',
      '"pass_condition"',
      '"error_types"',
      "zh-Hans-CN",
      "score ==",
    ]) {
      expect(languageVariants).not.toHaveTextContent(hiddenValue);
    }
    expect(getLessonSection("通过条件")).not.toHaveTextContent("score ==");
    fireEvent.click(
      screen.getByRole("button", { name: "返回课程列表" }),
    );

    openLesson("分轨标注语音情感与副语言事件");
    const emotionVariants = getLessonSection("练习变体");
    expect(emotionVariants).toHaveTextContent("emo-review-001");
    expect(emotionVariants).toHaveTextContent('"allowed_emotion_labels"');
    for (const hiddenValue of [
      '"candidate_annotation"',
      '"declared_by"',
      "evaluation.allowed_answers",
      '"pass_condition"',
      "score ==",
    ]) {
      expect(emotionVariants).not.toHaveTextContent(hiddenValue);
    }
    const learningPath = getLessonSection("学习路径");
    expect(learningPath).toHaveTextContent('"remediation_resource_refs"');
    expect(learningPath).not.toHaveTextContent('"error_type"');
    fireEvent.click(
      screen.getByRole("button", { name: "返回课程列表" }),
    );

    fireEvent.click(
      screen.getByRole("button", { name: domainButtonNames.video }),
    );
    openLesson("按行为本体标注视频事件区间");
    const videoResponseSpace = getLessonSection("响应空间");
    expect(videoResponseSpace).toHaveTextContent('"allowed_event_types"');
    expect(videoResponseSpace).toHaveTextContent("door_entry");
    expect(videoResponseSpace).not.toHaveTextContent(
      '"unmatched_submission_handling"',
    );
  });

  it("rejects normalized and suffixed answer-policy keys without dropping safe evidence", () => {
    expect(
      createLearnerSafeExampleProjection([
        {
          id: "SAFE-EXAMPLE-001",
          input: {
            safe_evidence: "SAFE_EVIDENCE_SENTINEL",
            hidden_region: "left_wrist",
            "expected.value": "LEAKED_EXPECTED_SENTINEL",
            "answer/value": "LEAKED_ANSWER_SENTINEL",
            answer1: "LEAKED_SUFFIXED_ANSWER_SENTINEL",
            passScore: 0.9,
            passCondition1: "LEAKED_PASS_CONDITION_SENTINEL",
            diagnostic2: "LEAKED_DIAGNOSTIC_SENTINEL",
            "evaluation.payload": "LEAKED_EVALUATION_SENTINEL",
            ordered_error_precedence: ["LEAKED_PRECEDENCE_SENTINEL"],
            recognized_submissions: ["LEAKED_SUBMISSION_SENTINEL"],
            unmatchedBehavior1: "LEAKED_UNMATCHED_SENTINEL",
            errorType1: "LEAKED_ERROR_TYPE_SENTINEL",
            candidate_annotation: "LEAKED_CANDIDATE_SENTINEL",
          },
        },
      ]),
    ).toEqual([
      {
        id: "SAFE-EXAMPLE-001",
        input: {
          safe_evidence: "SAFE_EVIDENCE_SENTINEL",
          hidden_region: "left_wrist",
        },
      },
    ]);
  });

  it("makes every published lesson reachable with a type-shaped empty editor", () => {
    render(<App profileStore={createTestStore()} />);

    for (const domain of ["text", "image", "audio", "video"] as const) {
      fireEvent.click(
        screen.getByRole("button", { name: domainButtonNames[domain] }),
      );
      const expectedUnits = teachingUnits.units.filter(
        (unit) => unit.data_type === domain,
      );
      const cards = screen.getAllByRole("button", {
        name: /打开课程：/,
      });
      expect(cards).toHaveLength(expectedUnits.length);

      for (const unit of expectedUnits) {
        openLesson(unit.title);
        expect(
          screen.getByRole("heading", { name: unit.title }),
        ).toBeVisible();
        const editor = screen.getByRole("textbox", {
          name: "结构化答案",
        }) as HTMLTextAreaElement;
        expect(() => JSON.parse(editor.value)).not.toThrow();
        expect(JSON.parse(editor.value)).not.toEqual(unit.exercise.answer);
        expect(
          screen.queryByRole("button", { name: "载入标准结构示例" }),
        ).not.toBeInTheDocument();
        fireEvent.click(
          screen.getByRole("button", { name: "返回课程列表" }),
        );
      }
    }
  });

  it("preserves one recursive empty item skeleton for object-array answers", () => {
    const cases = [
      {
        domain: "text" as const,
        title: "按字符偏移标注实体边界",
        expected: {
          entities: [{ label: "", start: 0, end: 0, text: "" }],
        },
        forbiddenValues: ["PERSON", "王芳"],
      },
      {
        domain: "image" as const,
        title: "判定关键点可见性",
        expected: {
          annotations: [
            {
              case_id: "",
              visibility: "",
              coordinates: { x: 0, y: 0 },
            },
          ],
        },
        forbiddenValues: ["KP-VISIBLE", "visible"],
      },
      {
        domain: "video" as const,
        title: "按行为本体标注视频事件区间",
        expected: {
          events: [
            {
              event_type: "",
              participant_track_ids: [""],
              start_ms: 0,
              end_ms: 0,
            },
          ],
        },
        forbiddenValues: ["door_entry", "person-01"],
      },
      {
        domain: "video" as const,
        title: "用稳定轨迹 ID 连接跨帧目标观察",
        expected: {
          tracks: [
            {
              track_id: "",
              observation_ids: [""],
              occluded_frame_indices: [0],
            },
          ],
        },
        forbiddenValues: ["trk_01", "obs-20-a"],
      },
    ];

    render(<App profileStore={createTestStore()} />);

    expect(createEmptyResponseShape({ events: [] })).toEqual({ events: [] });

    for (const testCase of cases) {
      fireEvent.click(
        screen.getByRole("button", {
          name: domainButtonNames[testCase.domain],
        }),
      );
      openLesson(testCase.title);

      const editor = screen.getByRole("textbox", {
        name: "结构化答案",
      }) as HTMLTextAreaElement;
      expect(JSON.parse(editor.value)).toEqual(testCase.expected);
      for (const originalValue of testCase.forbiddenValues) {
        expect(editor).not.toHaveValue(expect.stringContaining(originalValue));
      }

      fireEvent.click(
        screen.getByRole("button", { name: "返回课程列表" }),
      );
    }
  });

  it("renders declared pedagogy and safe instructional metadata", () => {
    render(<App profileStore={createTestStore()} />);
    fireEvent.click(
      screen.getByRole("button", { name: domainButtonNames.audio }),
    );
    openLesson("切割话语并对齐文本时间戳");

    for (const heading of [
      "学习目标",
      "先修能力",
      "规则依据",
      "规则说明",
      "时间基准策略",
      "正例",
      "反例",
      "练习输入",
      "学员动作",
      "通过条件",
      "练习变体",
      "常见错误",
      "补强建议",
      "学习路径",
      "资产与授权",
    ]) {
      expect(screen.getByRole("heading", { name: heading })).toBeVisible();
    }
    expect(screen.getByText("数据版本")).toBeVisible();
    expect(screen.getByText("1.1.1")).toBeVisible();
    expect(document.body).not.toHaveTextContent(
      "第一个片段引用了不存在于本题的录音 ID",
    );
  });

  it("filters incomplete and draft repository entries while preserving supplied counts", () => {
    const published = findUnit("TU-TEXT-LABEL-VOCAB-001");
    const draft = structuredClone(published);
    draft.id = "TU-DRAFT-TEST-001";
    draft.title = "不应开放的草稿课程";
    draft.review_status = "draft";
    const repository = {
      listConsumableUnits: () => [
        published,
        draft,
        { data_type: "text" },
      ],
    };

    render(
      <App repository={repository} profileStore={createTestStore()} />,
    );

    expect(
      screen.getByRole("button", {
        name: "文本课程，3 个可学习单元",
      }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: /校验封闭文本标签集/ }),
    ).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: /不应开放的草稿课程/ }),
    ).not.toBeInTheDocument();
  });

  it("restores a valid last lesson but never restores a draft lesson", () => {
    const published = findUnit("TU-TEXT-LABEL-VOCAB-001");
    const draft = structuredClone(published);
    draft.id = "TU-DRAFT-RESTORE-001";
    draft.title = "不可恢复的草稿课程";
    draft.review_status = "draft";
    const repository = { listConsumableUnits: () => [published, draft] };
    const { unmount } = render(
      <App
        repository={repository}
        profileStore={createTestStore({
          snapshot: () => createSnapshot({ lastUnit: published.id }),
        })}
      />,
    );

    expect(screen.getByRole("heading", { name: published.title })).toBeVisible();
    unmount();

    render(
      <App
        repository={repository}
        profileStore={createTestStore({
          snapshot: () => createSnapshot({ lastUnit: draft.id }),
        })}
      />,
    );
    expect(
      screen.queryByRole("heading", { name: draft.title }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /校验封闭文本标签集/ }),
    ).toBeEnabled();
  });

  it("restores a valid non-text last lesson with its matching domain", () => {
    const audioUnit = findUnit("TU-AUDIO-SEGMENTATION-ALIGNMENT-001");
    render(
      <App
        profileStore={createTestStore({
          snapshot: () => createSnapshot({ lastUnit: audioUnit.id }),
        })}
      />,
    );

    expect(
      screen.getByRole("heading", { name: audioUnit.title }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: domainButtonNames.audio }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("clears persisted lastUnit when returning to the course list", () => {
    const setContext = vi.fn();
    render(
      <App profileStore={createTestStore({ setContext })} />,
    );
    const unit = findUnit("TU-TEXT-LABEL-VOCAB-001");
    openLesson(unit.title);
    fireEvent.click(
      screen.getByRole("button", { name: "返回课程列表" }),
    );

    expect(setContext).toHaveBeenNthCalledWith(1, { lastUnit: unit.id });
    expect(setContext).toHaveBeenNthCalledWith(2, { lastUnit: null });
  });

  it("clears persisted lastUnit when switching course domains", () => {
    const setContext = vi.fn();
    render(
      <App profileStore={createTestStore({ setContext })} />,
    );
    const unit = findUnit("TU-TEXT-LABEL-VOCAB-001");
    openLesson(unit.title);
    fireEvent.click(
      screen.getByRole("button", { name: domainButtonNames.image }),
    );

    expect(setContext).toHaveBeenNthCalledWith(1, { lastUnit: unit.id });
    expect(setContext).toHaveBeenNthCalledWith(2, { lastUnit: null });
  });

  it("returns to the newly selected domain list from an open lesson", () => {
    render(<App profileStore={createTestStore()} />);
    openLesson("校验封闭文本标签集");
    expect(
      screen.getByRole("heading", { name: "校验封闭文本标签集" }),
    ).toBeVisible();

    fireEvent.click(
      screen.getByRole("button", { name: domainButtonNames.image }),
    );

    expect(
      screen.queryByRole("heading", { name: "校验封闭文本标签集" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /判定关键点可见性/ }),
    ).toBeEnabled();
  });

  it("renders only the authorized self-authored timing-anchor audio", () => {
    const { container } = render(<App profileStore={createTestStore()} />);
    fireEvent.click(
      screen.getByRole("button", { name: domainButtonNames.audio }),
    );
    openLesson("切割话语并对齐文本时间戳");

    const audio = container.querySelector("audio");
    expect(audio).not.toBeNull();
    expect(audio).toHaveAttribute("controls");
    expect(audio).toHaveAttribute("preload", "metadata");
    expect(audio?.getAttribute("src")).toContain(
      "task4-segmentation-alignment.wav",
    );
    expect(screen.getByText(/自编非语音计时锚点音频/)).toBeVisible();
    expect(screen.getByText(/contains_recorded_speech: false/)).toBeVisible();
    expect(screen.getByText(/允许学生使用/)).toBeVisible();
  });

  it("does not render media that is not authorized for student use", () => {
    const restricted = structuredClone(
      findUnit("TU-AUDIO-SEGMENTATION-ALIGNMENT-001"),
    );
    restricted.exercise.asset_authorization = {
      type: "self-authored",
      student_use_allowed: false,
    };
    const { container } = render(
      <App
        repository={{ listConsumableUnits: () => [restricted] }}
        profileStore={createTestStore()}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "语音课程，1 个可学习单元",
      }),
    );
    openLesson(restricted.title);

    expect(container.querySelector("audio")).toBeNull();
    expect(screen.getByText("未授权学生使用")).toBeVisible();
  });

  it("fails closed when the authorized audio metadata tuple does not match", () => {
    const mismatches: Array<[
      string,
      (unit: TeachingUnit) => void,
    ]> = [
      ["representation", (unit) => {
        unit.exercise.representation = "structured_fixture";
      }],
      ["manifest resolution", (unit) => {
        unit.exercise.manifest_resolution = "unresolved";
      }],
      ["authorization type", (unit) => {
        const authorization = unit.exercise.asset_authorization;
        if (typeof authorization === "object" && authorization !== null) {
          (authorization as Record<string, unknown>).type = "external";
        }
      }],
    ];

    for (const [_label, mutate] of mismatches) {
      const unit = structuredClone(
        findUnit("TU-AUDIO-SEGMENTATION-ALIGNMENT-001"),
      );
      mutate(unit);
      const { container } = render(
        <App
          repository={{ listConsumableUnits: () => [unit] }}
          profileStore={createTestStore()}
        />,
      );
      fireEvent.click(
        screen.getByRole("button", {
          name: "语音课程，1 个可学习单元",
        }),
      );
      openLesson(unit.title);

      expect(container.querySelector("audio")).toBeNull();
      expect(screen.getByText(/结构化练习夹具/)).toBeVisible();
      cleanup();
    }
  });

  it("labels structured fixtures without implying unavailable media", () => {
    const { container } = render(<App profileStore={createTestStore()} />);
    fireEvent.click(
      screen.getByRole("button", { name: domainButtonNames.video }),
    );
    openLesson("用稳定轨迹 ID 连接跨帧目标观察");

    expect(screen.getByText(/结构化练习夹具/)).toBeVisible();
    expect(screen.getByText(/未提供或暗示视频媒体/)).toBeVisible();
    expect(container.querySelector("video")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("keeps evaluation usable but gates last-unit and mastery writes during recovery", () => {
    const setContext = vi.fn();
    const recordExercise = vi.fn();
    const store = createTestStore({
      getLoadError: () => ({
        code: "malformed_profile",
        message: "Stored learning profile is malformed.",
      }),
      setContext,
      recordExercise,
    });
    render(<App profileStore={store} />);
    openLesson("校验封闭文本标签集");

    fireEvent.change(
      screen.getByRole("textbox", { name: "结构化答案" }),
      { target: { value: '{"labels":["negative"]}' } },
    );
    fireEvent.click(screen.getByRole("button", { name: "提交自检" }));

    expect(screen.getByRole("status")).toHaveTextContent("通过");
    expect(setContext).not.toHaveBeenCalled();
    expect(recordExercise).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "本地学习档案无法读取",
    );
  });

  it("retains deterministic feedback when profile persistence fails", () => {
    const store = createTestStore({
      recordExercise: vi.fn(() => {
        throw new Error("storage unavailable");
      }),
    });
    render(<App profileStore={store} />);
    openLesson("校验封闭文本标签集");
    fireEvent.change(
      screen.getByRole("textbox", { name: "结构化答案" }),
      { target: { value: '{"labels":["negative"]}' } },
    );
    fireEvent.click(screen.getByRole("button", { name: "提交自检" }));

    expect(screen.getByRole("status")).toHaveTextContent("通过");
    expect(screen.getByRole("status")).toHaveTextContent("回答正确");
    expect(screen.getByRole("alert")).toHaveTextContent("掌握度保存失败");
  });

  it("records every capability and preserves a partial-persistence warning", () => {
    const recordExercise = vi
      .fn()
      .mockImplementationOnce(() => {
        throw new Error("first capability failed");
      })
      .mockImplementationOnce(() => undefined);
    const store = createTestStore({ recordExercise });
    render(<App profileStore={store} />);
    openLesson("处理意图歧义与允许答案集");
    fireEvent.change(
      screen.getByRole("textbox", { name: "结构化答案" }),
      {
        target: {
          value: JSON.stringify({
            primary_intent: "refund_status",
            candidate_intents: ["refund_status", "order_status"],
            ambiguity: "resolved_by_explicit_refund",
          }),
        },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "提交自检" }));

    expect(recordExercise).toHaveBeenCalledTimes(2);
    expect(recordExercise.mock.calls.map(([input]) => input.capabilityId)).toEqual([
      "CAP-TXT-INTENT-001",
      "CAP-TXT-AMBIGUITY-001",
    ]);
    expect(screen.getByRole("status")).toHaveTextContent("通过");
    expect(screen.getByRole("alert")).toHaveTextContent("掌握度保存失败");
  });
});
