// @vitest-environment node

import { describe, expect, it } from "vitest";

import { createRepository } from "../../src/data/repository";
import {
  graph,
  scenarios,
  sourceRegistry,
  teachingUnits,
} from "../../src/data/rawData";
import { createGraphEngine } from "../../src/graph/graphEngine";
import { createScenarioEngine } from "../../src/scenarios/scenarioEngine";
import { buildTaskCards } from "../../src/tasks/taskCardBuilder";
import { APPROVED_PRODUCT_METADATA } from "../../src/tasks/productMetadata";
import { createTaskConverter } from "../../src/tasks/taskConverter";
import { getTaskNode } from "../../src/tasks/taskKeywords";

const repositoryInput = { graph, scenarios, sourceRegistry, teachingUnits };
const repository = createRepository(repositoryInput);
const converter = createTaskConverter(repository);

const requireCards = (text: string, scenarioId: string | null = null) => {
  const result = converter.convert(text, scenarioId);
  expect(result.kind).toBe("cards");
  if (result.kind !== "cards") {
    throw new Error("expected cards");
  }
  return result;
};

const isUnknownArray = (value: unknown): value is unknown[] =>
  Array.isArray(value);

const isUnknownRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

describe("task converter", () => {
  it("creates PRE-ordered cards for an explicit audio task", () => {
    const result = converter.convert(
      "对车载语音做唤醒词边界和命令意图标注",
      "SCN-IN-VEHICLE-001",
    );

    expect(result.kind).toBe("cards");
    if (result.kind !== "cards") {
      throw new Error("expected cards");
    }
    expect(result.cards.at(-1)?.capabilityIds).toContain(
      "CAP-AUD-WAKE-COMMAND-001",
    );
    expect(
      result.cards.every(
        (card) => card.steps.length >= 3 && card.steps.length <= 9,
      ),
    ).toBe(true);
  });

  it("asks for the data type instead of guessing", () => {
    expect(converter.convert("帮我做一个标注任务", null)).toMatchObject({
      kind: "clarification",
      missing: ["data_type"],
      matchedDataType: null,
    });
  });

  it("keeps the unique matched data type for scenario compatibility checks", () => {
    expect(converter.convert("请处理音频文件", null)).toMatchObject({
      kind: "clarification",
      matchedDataType: "audio",
    });
    expect(converter.convert("医疗视频行为事件标注", null)).toMatchObject({
      kind: "cards",
      matchedDataType: "video",
    });
  });

  it("suggests but does not switch a detected scene", () => {
    expect(
      converter.convert(
        "医疗文本实体标注",
        "SCN-CUSTOMER-SERVICE-001",
      ),
    ).toMatchObject({
      suggestedScenarioId: "SCN-MEDICAL-001",
      appliedScenarioId: "SCN-CUSTOMER-SERVICE-001",
    });
  });

  it.each([
    ["draft", true],
    ["published", false],
  ] as const)(
    "does not expose an ineligible detected %s scenario in conversion output",
    (reviewStatus, studentVisible) => {
      const input = structuredClone(repositoryInput);
      const medicalScenario = input.scenarios.find(
        (document) => document.scenario.id === "SCN-MEDICAL-001",
      )?.scenario;
      if (medicalScenario === undefined) {
        throw new Error("canonical medical scenario missing");
      }
      medicalScenario.review_status = reviewStatus;
      medicalScenario.student_visible = studentVisible;

      const result = createTaskConverter(createRepository(input)).convert(
        "医疗文本实体标注",
        "SCN-CUSTOMER-SERVICE-001",
      );

      expect(result.suggestedScenarioId).toBeNull();
      expect(result.matchEvidence.join("\n")).not.toContain("SCN-MEDICAL-001");
    },
  );

  it.each([
    ["文本实体边界标注", "text", "CAP-TXT-ENTITY-BOUNDARY-001"],
    ["图像目标框标注", "image", "CAP-IMG-BOX-ANNOTATE-001"],
    ["音频说话人轮次标注", "audio", "CAP-AUD-SPEAKER-001"],
    ["视频目标轨迹标注", "video", "CAP-VID-OBJECT-TRACK-001"],
  ])(
    "recognizes %s as %s and targets its graph capability",
    (text, dataType, capabilityId) => {
      const result = requireCards(text);

      expect(
        result.matchEvidence.some((evidence) =>
          new RegExp(`^data_type:${dataType}:`).test(evidence),
        ),
      ).toBe(true);
      expect(result.cards.at(-1)?.capabilityIds).toContain(capabilityId);
    },
  );

  it.each([
    ["医疗文本实体标注", "SCN-MEDICAL-001"],
    ["客服文本意图标注", "SCN-CUSTOMER-SERVICE-001"],
    ["车载语音唤醒词标注", "SCN-IN-VEHICLE-001"],
    ["内容安全视频行为事件标注", "SCN-CONTENT-SAFETY-001"],
  ])("suggests the detected scene for %s", (text, suggestedScenarioId) => {
    const result = requireCards(text);

    expect(result.appliedScenarioId).toBeNull();
    expect(result.suggestedScenarioId).toBe(suggestedScenarioId);
    expect(result.matchedDataType).not.toBeNull();
  });

  it("returns stable missing fields for empty and ambiguous input", () => {
    expect(converter.convert("", null)).toMatchObject({
      kind: "clarification",
      missing: ["data_type", "goal"],
      appliedScenarioId: null,
      suggestedScenarioId: null,
    });
    expect(converter.convert("   \r\n ", null)).toEqual(
      converter.convert("", null),
    );
    expect(converter.convert("请处理音频文件", null)).toMatchObject({
      kind: "clarification",
      missing: ["goal"],
    });
    expect(converter.convert("请做边界标注", null)).toMatchObject({
      kind: "clarification",
      missing: ["data_type"],
    });
  });

  it("returns auditable candidate IDs and labels when clarification is needed", () => {
    const result = converter.convert("请处理音频文件", null);

    expect(result.kind).toBe("clarification");
    if (result.kind !== "clarification") {
      throw new Error("expected clarification");
    }
    expect(result.candidates).toContain(
      "TSK-AUD-COMMAND-SEGMENT-001|切割唤醒与命令片段",
    );
  });

  it("uses explicit keyword scoring to resolve cross-modality collisions", () => {
    const result = requireCards("请把视频中的音频语音转写并添加标点");

    expect(
      result.matchEvidence.some((evidence) =>
        /^data_type:audio:/.test(evidence),
      ),
    ).toBe(true);
    expect(result.cards.at(-1)?.capabilityIds).toContain(
      "CAP-AUD-TRANSCRIBE-PUNCT-001",
    );
  });

  it.each(["context 标注任务", "audiovisual 标注任务"])(
    "does not treat Latin keyword near-miss %s as a data type",
    (text) => {
      expect(converter.convert(text, null)).toMatchObject({
        kind: "clarification",
        missing: ["data_type"],
      });
    },
  );

  it("normalizes full-width Latin task input with NFKC", () => {
    const result = requireCards("ＶＩＤＥＯ 事件类别标注");

    expect(result.cards.at(-1)?.capabilityIds).toContain(
      "CAP-VID-ACTION-EVENT-001",
    );
    expect(
      result.matchEvidence.some((evidence) =>
        /^data_type:video:video/.test(evidence),
      ),
    ).toBe(true);
  });

  it("clarifies tied data-type scores instead of using rule order", () => {
    const result = converter.convert("音频视频 标注任务", null);

    expect(result).toMatchObject({
      kind: "clarification",
      missing: ["data_type"],
      appliedScenarioId: null,
    });
    if (result.kind !== "clarification") {
      throw new Error("expected clarification");
    }
    expect(result.candidates).toContain(
      "TSK-AUD-COMMAND-SEGMENT-001|切割唤醒与命令片段",
    );
    expect(result.candidates).toContain(
      "TSK-VID-ACTION-EVENT-001|标注视频行为事件",
    );
    if (!("matchEvidence" in result)) {
      throw new Error("expected ambiguity evidence");
    }
    expect(result.matchEvidence).toEqual(
      expect.arrayContaining([
        "data_type_ambiguous:audio:音频",
        "data_type_ambiguous:video:视频",
      ]),
    );
  });

  it("records TSK, CAP, and KNG graph evidence", () => {
    const result = requireCards("语音唤醒词边界与命令意图标注");

    expect(
      result.matchEvidence.some((evidence) =>
        /^task:TSK-AUD-COMMAND-SEGMENT-001:/.test(evidence),
      ),
    ).toBe(true);
    expect(
      result.matchEvidence.some((evidence) =>
        /^capability:CAP-AUD-WAKE-COMMAND-001:/.test(evidence),
      ),
    ).toBe(true);
    expect(
      result.matchEvidence.some((evidence) =>
        /^knowledge:KNG-AUD-/.test(evidence),
      ),
    ).toBe(true);
  });

  it("uses primary_capability_ref to disambiguate multiple incoming SUP edges", () => {
    const input = structuredClone(repositoryInput);
    input.graph.edges.push({
      id: "EDGE-TEST-MULTI-SUP-001",
      source: "CAP-AUD-SPEAKER-001",
      target: "TSK-AUD-COMMAND-SEGMENT-001",
      relation: "SUP",
      label: "支持",
      metadata: {},
    });
    const result = createTaskConverter(createRepository(input)).convert(
      "语音唤醒词与命令意图标注",
      null,
    );

    expect(result.kind).toBe("cards");
    if (result.kind !== "cards") {
      throw new Error("expected cards");
    }
    expect(result.cards.at(-1)?.capabilityIds).toEqual([
      "CAP-AUD-WAKE-COMMAND-001",
    ]);
    expect(result.matchEvidence).toContain(
      "capability_selection:SUP:CAP-AUD-WAKE-COMMAND-001:primary_capability_ref",
    );
  });

  it("clarifies multiple SUP edges without a consistent primary capability", () => {
    const input = structuredClone(repositoryInput);
    const task = input.graph.nodes.find(
      ({ id }) => id === "TSK-AUD-COMMAND-SEGMENT-001",
    );
    if (task === undefined) {
      throw new Error("missing task fixture");
    }
    delete task.primary_capability_ref;
    input.graph.edges.push({
      id: "EDGE-TEST-MULTI-SUP-002",
      source: "CAP-AUD-SPEAKER-001",
      target: task.id,
      relation: "SUP",
      label: "支持",
      metadata: {},
    });

    const result = createTaskConverter(createRepository(input)).convert(
      "语音唤醒词与命令意图标注",
      null,
    );

    expect(result).toMatchObject({
      kind: "clarification",
      missing: ["goal"],
      appliedScenarioId: null,
    });
    if (result.kind !== "clarification") {
      throw new Error("expected clarification");
    }
    expect(result.candidates).toEqual(
      expect.arrayContaining([
        "CAP-AUD-WAKE-COMMAND-001|标注唤醒词与命令词",
        "CAP-AUD-SPEAKER-001|区分说话人",
      ]),
    );
    expect(result.matchEvidence).toContain(
      "capability_selection:ambiguous:CAP-AUD-WAKE-COMMAND-001+CAP-AUD-SPEAKER-001",
    );
  });

  it("labels a no-SUP fallback only as primary_capability_ref", () => {
    const input = structuredClone(repositoryInput);
    input.graph.edges = input.graph.edges.filter(
      ({ relation, target }) =>
        relation !== "SUP" || target !== "TSK-AUD-COMMAND-SEGMENT-001",
    );
    const result = createTaskConverter(createRepository(input)).convert(
      "语音唤醒词与命令意图标注",
      null,
    );

    expect(result.kind).toBe("cards");
    if (result.kind !== "cards") {
      throw new Error("expected cards");
    }
    const capabilityEvidence = result.matchEvidence.filter((evidence) =>
      evidence.startsWith("capability:"),
    );
    expect(capabilityEvidence).toEqual([
      expect.stringContaining(
        "capability:CAP-AUD-WAKE-COMMAND-001:primary_capability_ref:TSK-AUD-COMMAND-SEGMENT-001",
      ),
    ]);
    expect(capabilityEvidence.join("\n")).not.toContain(":SUP:");
  });

  it("builds complete cards only from graph relations and consumable units", () => {
    const result = requireCards(
      "对车载语音做唤醒词边界和命令意图标注",
      "SCN-IN-VEHICLE-001",
    );
    const consumableUnitIds = new Set(
      repository.listConsumableUnits().map(({ id }) => id),
    );

    expect(result.cards.map((card) => card.capabilityIds[0])).toEqual([
      "CAP-CORE-TASK-SCOPE-001",
      "CAP-CORE-ASSET-QUALITY-001",
      "CAP-AUD-CONFIG-VALIDATE-001",
      "CAP-AUD-TRANSCRIBE-PUNCT-001",
      "CAP-AUD-WAKE-COMMAND-001",
    ]);

    for (const card of result.cards) {
      expect(card).toEqual(
        expect.objectContaining({
          name: expect.any(String),
          objectives: expect.any(Array),
          role: APPROVED_PRODUCT_METADATA.role.value,
          scene: "车载语音标注",
          provenance: expect.objectContaining({
            roleSourceRef: APPROVED_PRODUCT_METADATA.role.sourceRef,
            sceneSourceRef:
              "data/scenarios/in-vehicle.json#scenario:SCN-IN-VEHICLE-001",
          }),
          capabilityPath: expect.any(Array),
          capabilityIds: expect.any(Array),
          knowledgeIds: expect.any(Array),
          certificateIds: expect.any(Array),
          steps: expect.any(Array),
          commonErrors: expect.any(Array),
          resourceIds: expect.any(Array),
          selfCheckItems: expect.any(Array),
        }),
      );
      expect(card.steps.length).toBeGreaterThanOrEqual(3);
      expect(card.steps.length).toBeLessThanOrEqual(9);
      expect(
        card.teachingUnitIds.every((unitId) =>
          consumableUnitIds.has(unitId),
        ),
      ).toBe(true);

      for (const capabilityId of card.capabilityIds) {
        expect(repository.getNode(capabilityId)?.type).toBe("CAP");
      }
      for (const knowledgeId of card.knowledgeIds) {
        expect(repository.getNode(knowledgeId)?.type).toBe("KNG");
      }
      for (const certificateId of card.certificateIds) {
        expect(repository.getNode(certificateId)?.type).toBe("CERT");
      }
      for (const resourceId of card.resourceIds) {
        expect(repository.getNode(resourceId)?.type).toBe("RES");
      }
    }
  });

  it("excludes unit KNG refs that are not related to the current capability", () => {
    const input = structuredClone(repositoryInput);
    const unit = input.teachingUnits.units.find(
      ({ id }) => id === "TU-AUDIO-WAKE-COMMAND-WORDS-001",
    );
    if (unit === undefined) {
      throw new Error("missing wake command unit fixture");
    }
    unit.rule_refs.push("KNG-TXT-CLASS-EXCLUSION-001");
    const result = createTaskConverter(createRepository(input)).convert(
      "语音唤醒词与命令意图标注",
      null,
    );

    expect(result.kind).toBe("cards");
    if (result.kind !== "cards") {
      throw new Error("expected cards");
    }
    expect(result.cards.at(-1)?.knowledgeIds).not.toContain(
      "KNG-TXT-CLASS-EXCLUSION-001",
    );
  });

  it("keeps lessonless prerequisites as structure cards", () => {
    const result = requireCards("语音唤醒词与命令意图标注");
    const first = result.cards[0];

    expect(first).toMatchObject({
      contentKind: "structure",
      capabilityIds: ["CAP-CORE-TASK-SCOPE-001"],
      teachingUnitIds: [],
    });
    expect(first?.steps).not.toContain(
      expect.stringContaining("虚构课程"),
    );
    expect(result.cards.at(-1)).toMatchObject({
      contentKind: "lesson",
      teachingUnitIds: ["TU-AUDIO-WAKE-COMMAND-WORDS-001"],
    });
  });

  it("uses approved metadata with provenance for the default scene", () => {
    const result = requireCards("语音唤醒词与命令意图标注");

    expect(
      result.cards.every(
        ({ role, scene, provenance }) =>
          role === APPROVED_PRODUCT_METADATA.role.value &&
          scene === APPROVED_PRODUCT_METADATA.defaultScene.value &&
          provenance.roleSourceRef ===
            APPROVED_PRODUCT_METADATA.role.sourceRef &&
          provenance.sceneSourceRef ===
            APPROVED_PRODUCT_METADATA.defaultScene.sourceRef,
      ),
    ).toBe(true);
  });

  it("uses the controlled default metadata for an unknown scenario", () => {
    const result = requireCards(
      "语音唤醒词与命令意图标注",
      "SCN-UNKNOWN-001",
    );

    expect(result.cards).not.toHaveLength(0);
    expect(
      result.cards.every(({ scene, provenance }) =>
        scene === APPROVED_PRODUCT_METADATA.defaultScene.value &&
        provenance.sceneSourceRef ===
          APPROVED_PRODUCT_METADATA.defaultScene.sourceRef,
      ),
    ).toBe(true);
  });

  it("does not apply a scenario that does not declare the matched data type", () => {
    const result = requireCards(
      "文本实体边界标注",
      "SCN-IN-VEHICLE-001",
    );

    expect(result.appliedScenarioId).toBeNull();
    expect(
      result.cards.every(({ scene, provenance }) =>
        scene === APPROVED_PRODUCT_METADATA.defaultScene.value &&
        provenance.sceneSourceRef ===
          APPROVED_PRODUCT_METADATA.defaultScene.sourceRef,
      ),
    ).toBe(true);
    expect(result.cards.flatMap(({ scenarioRuleIds }) => scenarioRuleIds)).toEqual(
      [],
    );
  });

  it.each([
    ["draft", "review_status"],
    ["hidden", "student_visible"],
  ])("does not expose a %s scenario name", (_caseName, field) => {
    const input = structuredClone(repositoryInput);
    const medical = input.scenarios.find(
      ({ scenario }) => scenario.id === "SCN-MEDICAL-001",
    );
    if (medical === undefined) {
      throw new Error("missing medical scenario fixture");
    }
    if (field === "review_status") {
      medical.scenario.review_status = "draft";
    } else {
      medical.scenario.student_visible = false;
    }
    const result = createTaskConverter(createRepository(input)).convert(
      "文本实体边界标注",
      "SCN-MEDICAL-001",
    );

    expect(result.kind).toBe("cards");
    if (result.kind !== "cards") {
      throw new Error("expected cards");
    }
    expect(result.appliedScenarioId).toBeNull();
    expect(
      result.cards.every(({ scene, provenance }) =>
        scene === APPROVED_PRODUCT_METADATA.defaultScene.value &&
        provenance.sceneSourceRef ===
          APPROVED_PRODUCT_METADATA.defaultScene.sourceRef,
      ),
    ).toBe(true);
  });

  it("propagates eligible scenario evidence into result and cards", () => {
    const result = requireCards(
      "车载语音唤醒词与命令意图标注",
      "SCN-IN-VEHICLE-001",
    );

    expect(result.matchEvidence).toEqual(
      expect.arrayContaining([
        "scenario:SCN-IN-VEHICLE-001:published",
        "scenario:SCN-IN-VEHICLE-001:declares:audio",
        "override:SCNR-IV-AUD-COMMAND-001:published",
      ]),
    );
    expect(
      result.cards.every(({ matchEvidence }) =>
        matchEvidence.includes("scenario:SCN-IN-VEHICLE-001:published"),
      ),
    ).toBe(true);
    expect(result.cards.at(-1)?.matchEvidence).toContain(
      "override:SCNR-IV-AUD-COMMAND-001:published",
    );
  });

  it("is deterministic, trims input, and returns fresh output containers", () => {
    const expected = converter.convert("音频说话人轮次标注", null);
    const padded = converter.convert("  音频说话人轮次标注  ", null);
    expect(padded).toEqual(expected);

    if (padded.kind !== "cards") {
      throw new Error("expected cards");
    }
    padded.cards.pop();
    padded.matchEvidence.push("polluted");

    expect(converter.convert("音频说话人轮次标注", null)).toEqual(expected);
  });

  it("does not mutate canonical repository inputs", () => {
    const before = structuredClone(repositoryInput);

    converter.convert("医疗文本实体标注", "SCN-MEDICAL-001");

    expect(repositoryInput).toEqual(before);
  });

  it("snapshots task catalog nodes before raw graph mutations", () => {
    const rawTask = graph.nodes.find(
      ({ id }) => id === "TSK-AUD-COMMAND-SEGMENT-001",
    );
    if (rawTask === undefined) {
      throw new Error("missing raw task fixture");
    }
    const originalLabel = rawTask.label;

    try {
      rawTask.label = "polluted raw task label";
      const result = requireCards("语音唤醒词与命令意图标注");
      expect(
        result.matchEvidence.some((evidence) =>
          evidence.includes(`label=${originalLabel}`),
        ),
      ).toBe(true);
      expect(result.matchEvidence.join("\n")).not.toContain(
        "polluted raw task label",
      );
    } finally {
      rawTask.label = originalLabel;
    }
  });

  it("deep-freezes task nodes returned from the catalog", () => {
    const task = getTaskNode("TSK-AUD-COMMAND-SEGMENT-001");
    if (task === undefined || !isUnknownArray(task.teaching_unit_links)) {
      throw new Error("missing catalog task fixture");
    }
    const firstLink = task.teaching_unit_links[0];
    if (!isUnknownRecord(firstLink)) {
      throw new Error("missing catalog task link fixture");
    }
    const originalUnitId = firstLink.unit_id;

    expect(() => {
      firstLink.unit_id = "TU-POLLUTED-001";
    }).toThrow();

    const reread = getTaskNode("TSK-AUD-COMMAND-SEGMENT-001");
    if (reread === undefined || !isUnknownArray(reread.teaching_unit_links)) {
      throw new Error("missing reread catalog task fixture");
    }
    const rereadLink = reread.teaching_unit_links[0];
    expect(isUnknownRecord(rereadLink) ? rereadLink.unit_id : undefined).toBe(
      originalUnitId,
    );
  });
});

describe("approved product metadata", () => {
  it("is deeply frozen and carries stable semantic source anchors", () => {
    expect(APPROVED_PRODUCT_METADATA).toEqual(
      expect.objectContaining({
        role: {
          value: "AI数据标注工程师",
          sourceRef: "docs/标航智导.md#4.1-岗位定义",
        },
        defaultScene: {
          value: "通用标注规则",
          sourceRef:
            "docs/superpowers/specs/2026-07-14-task6-teaching-application-design.md#6.4-场景切换",
        },
      }),
    );
    expect(Object.isFrozen(APPROVED_PRODUCT_METADATA)).toBe(true);
    expect(Object.isFrozen(APPROVED_PRODUCT_METADATA.role)).toBe(true);
    expect(Object.isFrozen(APPROVED_PRODUCT_METADATA.defaultScene)).toBe(true);
    expect(Object.isFrozen(APPROVED_PRODUCT_METADATA.scenarioDocuments)).toBe(
      true,
    );
  });

  it("provides approved structural fallback steps with provenance", () => {
    expect(APPROVED_PRODUCT_METADATA.structureSteps).toEqual({
      values: [
        "在能力图谱中定位当前能力及其 PRE 前置关系",
        "阅读已发布规则或当前开发态结构节点说明",
        "完成任务卡自检并确认下一学习步骤",
      ],
      sourceRef: "docs/标航智导.md#5.4-模块二-标注任务转化器",
    });
    expect(Object.isFrozen(APPROVED_PRODUCT_METADATA.structureSteps)).toBe(
      true,
    );
    expect(
      Object.isFrozen(APPROVED_PRODUCT_METADATA.structureSteps.values),
    ).toBe(true);
  });
});

describe("task card step invariants", () => {
  it("fills a sparse structure card from approved structural metadata", () => {
    const input = structuredClone(repositoryInput);
    input.graph.nodes.push({
      id: "CAP-TEST-SPARSE-001",
      label: "same",
      description: "same",
      data_types: ["same"],
      type: "CAP",
      status: "draft",
      source_refs: [],
    });
    const cards = buildTaskCards(
      createRepository(input),
      ["CAP-TEST-SPARSE-001"],
      "text",
      null,
    );

    expect(cards).toHaveLength(1);
    expect(cards[0]).toMatchObject({
      contentKind: "structure",
      steps: APPROVED_PRODUCT_METADATA.structureSteps.values,
      provenance: {
        structureStepsSourceRef:
          APPROVED_PRODUCT_METADATA.structureSteps.sourceRef,
      },
    });
    expect(cards[0]?.steps).toHaveLength(3);
  });

  it("keeps every canonical task path within 3-9 steps with valid refs", () => {
    const graphEngine = createGraphEngine(graph);
    const tasks = graph.nodes.filter(({ type }) => type === "TSK");
    expect(tasks).toHaveLength(20);

    for (const task of tasks) {
      const capabilityId = task.primary_capability_ref;
      const dataType = task.data_types[0];
      if (typeof capabilityId !== "string" || dataType === undefined) {
        throw new Error(`invalid canonical task fixture ${task.id}`);
      }
      const plan = graphEngine.remediationPlan(capabilityId, () => null);
      const cards = buildTaskCards(
        repository,
        plan.steps.map(({ nodeId }) => nodeId),
        dataType,
        null,
      );

      expect(cards.length, task.id).toBeGreaterThan(0);
      for (const card of cards) {
        expect(card.steps.length, `${task.id}:${card.name}`).toBeGreaterThanOrEqual(
          3,
        );
        expect(card.steps.length, `${task.id}:${card.name}`).toBeLessThanOrEqual(
          9,
        );
        expect(
          card.capabilityIds.every(
            (id) => repository.getNode(id)?.type === "CAP",
          ),
          task.id,
        ).toBe(true);
        expect(
          card.knowledgeIds.every(
            (id) => repository.getNode(id)?.type === "KNG",
          ),
          task.id,
        ).toBe(true);
        expect(
          card.resourceIds.every(
            (id) => repository.getNode(id)?.type === "RES",
          ),
          task.id,
        ).toBe(true);
        expect(
          card.certificateIds.every(
            (id) => repository.getNode(id)?.type === "CERT",
          ),
          task.id,
        ).toBe(true);
      }
    }
  });
});

describe("scenario engine", () => {
  const engine = createScenarioEngine(repository);

  it("preserves the base rule for add and replaces only the referenced base", () => {
    const medicalBase = [
      {
        id: "KNG-TXT-ENTITY-TYPE-001",
        content: "base entity rule",
        sourceRefs: [],
      },
    ];
    const medical = engine.applyRules({
      scenarioId: "SCN-MEDICAL-001",
      dataType: "text",
      baseRules: medicalBase,
    });
    expect(medical.rules.map(({ id }) => id)).toEqual([
      "KNG-TXT-ENTITY-TYPE-001",
      "SCNR-MED-TXT-ENTITY-001",
    ]);
    expect(medical.appliedRules[0]).toMatchObject({
      ruleId: "SCNR-MED-TXT-ENTITY-001",
      baseRuleRef: "KNG-TXT-ENTITY-TYPE-001",
      overrideType: "add",
      evidence: expect.arrayContaining([
        "override:SCNR-MED-TXT-ENTITY-001:published",
      ]),
    });

    const safety = engine.applyRules({
      scenarioId: "SCN-CONTENT-SAFETY-001",
      dataType: "text",
      baseRules: [
        {
          id: "KNG-TXT-CLASS-EXCLUSION-001",
          content: "base classification rule",
          sourceRefs: [],
        },
        {
          id: "KNG-TXT-LABEL-VOCAB-001",
          content: "unrelated rule",
          sourceRefs: [],
        },
      ],
    });
    expect(safety.rules.map(({ id }) => id)).toEqual([
      "KNG-TXT-LABEL-VOCAB-001",
      "SCNR-CSAFE-TXT-CLASS-001",
    ]);
  });

  it("does not apply overrides to unsupported data types", () => {
    const result = engine.applyRules({
      scenarioId: "SCN-IN-VEHICLE-001",
      dataType: "text",
      baseRules: [
        {
          id: "KNG-TXT-ENTITY-TYPE-001",
          content: "base entity rule",
          sourceRefs: [],
        },
      ],
    });

    expect(result.appliedRules).toEqual([]);
    expect(result.rules.map(({ id }) => id)).toEqual([
      "KNG-TXT-ENTITY-TYPE-001",
    ]);
  });

  it("excludes draft overrides even when the scenario is published", () => {
    const input = structuredClone(repositoryInput);
    const vehicle = input.scenarios.find(
      ({ scenario }) => scenario.id === "SCN-IN-VEHICLE-001",
    );
    if (vehicle === undefined || !isUnknownArray(vehicle.scenario.overrides)) {
      throw new Error("missing vehicle scenario fixture");
    }
    vehicle.scenario.overrides = [
      ...vehicle.scenario.overrides,
      {
        rule_id: "SCNR-IV-AUD-DRAFT-001",
        data_type: "audio",
        base_rule_ref: "KNG-AUD-COMMAND-INTENT-001",
        override_type: "replace",
        content: "draft content must remain hidden",
        source_refs: [],
        review_status: "draft",
      },
    ];
    const draftEngine = createScenarioEngine(createRepository(input));

    const result = draftEngine.applyRules({
      scenarioId: "SCN-IN-VEHICLE-001",
      dataType: "audio",
      baseRules: [
        {
          id: "KNG-AUD-COMMAND-INTENT-001",
          content: "base command rule",
          sourceRefs: [],
        },
      ],
    });

    expect(result.rules.map(({ id }) => id)).toEqual([
      "KNG-AUD-COMMAND-INTENT-001",
      "SCNR-IV-AUD-COMMAND-001",
    ]);
    expect(result.rules.some(({ content }) => content.includes("draft"))).toBe(
      false,
    );
  });

  it("does not mutate base rules or repository inputs", () => {
    const baseRules = [
      {
        id: "KNG-AUD-COMMAND-INTENT-001",
        content: "base command rule",
        sourceRefs: ["SRC-TEST-001"],
      },
    ];
    const baseBefore = structuredClone(baseRules);
    const inputBefore = structuredClone(repositoryInput);

    engine.applyRules({
      scenarioId: "SCN-IN-VEHICLE-001",
      dataType: "audio",
      baseRules,
    });

    expect(baseRules).toEqual(baseBefore);
    expect(repositoryInput).toEqual(inputBefore);
  });

  it("reports deterministic multiple-replace conflicts without applying them", () => {
    const input = structuredClone(repositoryInput);
    const safety = input.scenarios.find(
      ({ scenario }) => scenario.id === "SCN-CONTENT-SAFETY-001",
    );
    if (safety === undefined || !isUnknownArray(safety.scenario.overrides)) {
      throw new Error("missing content safety overrides fixture");
    }
    safety.scenario.overrides.push({
      rule_id: "SCNR-CSAFE-TXT-CLASS-000",
      data_type: "text",
      base_rule_ref: "KNG-TXT-CLASS-EXCLUSION-001",
      override_type: "replace",
      content: "conflicting published replacement",
      source_refs: ["SRC-POLICY-SCENARIOS-TASK5-001"],
      review_status: "published",
    });
    const conflictEngine = createScenarioEngine(createRepository(input));

    const result = conflictEngine.applyRules({
      scenarioId: "SCN-CONTENT-SAFETY-001",
      dataType: "text",
      baseRules: [
        {
          id: "KNG-TXT-CLASS-EXCLUSION-001",
          content: "base classification rule",
          sourceRefs: [],
        },
      ],
    });

    expect(result.rules.map(({ id }) => id)).toEqual([
      "KNG-TXT-CLASS-EXCLUSION-001",
    ]);
    expect(result.appliedRules).toEqual([]);
    expect(result.evidence).toContain(
      "override_conflict:KNG-TXT-CLASS-EXCLUSION-001:multiple_replace:SCNR-CSAFE-TXT-CLASS-000+SCNR-CSAFE-TXT-CLASS-001",
    );
    if (!("conflicts" in result)) {
      throw new Error("expected structured scenario conflict");
    }
    expect(result.conflicts).toEqual([
      {
        baseRuleRef: "KNG-TXT-CLASS-EXCLUSION-001",
        ruleIds: [
          "SCNR-CSAFE-TXT-CLASS-000",
          "SCNR-CSAFE-TXT-CLASS-001",
        ],
        reason: "multiple_replace",
      },
    ]);
  });
});
