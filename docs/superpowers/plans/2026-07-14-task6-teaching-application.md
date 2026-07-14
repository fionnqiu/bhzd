# Task 6 教学应用与诊断系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个在 Windows Chrome/Edge 中本地运行、消费已发布教学数据并贯通课程、图谱、练习、任务转化、诊断和 PRE 补强计划的 Web 应用。

**Architecture:** React 单页应用只负责交互，数据门槛、图谱查询、确定性判定、掌握度、任务转化和格式诊断实现为无 React 依赖的纯 TypeScript 模块。Vite 在构建期打包仓库权威 JSON 与授权音频，浏览器只在本地解析文件并用版本化 `localStorage` 保存匿名学习档案。

**Tech Stack:** React 19、TypeScript 5、Vite 7、vis-network、Vitest、React Testing Library、Playwright、现有 Python 3.11 校验脚本。

---

## File map

```text
app/
├── package.json                         # 前端命令与依赖
├── vite.config.ts                       # 外部权威数据导入、Vitest 配置
├── playwright.config.ts                 # tests/e2e 与本地 Web 服务
├── src/
│   ├── app/App.tsx                      # 工作模式与统一外壳
│   ├── app/app.css                      # 设计令牌、三栏布局、响应式与动效降级
│   ├── data/contracts.ts                # JSON 输入的 TypeScript 契约
│   ├── data/rawData.ts                  # 唯一权威静态导入入口
│   ├── data/repository.ts               # 发布门槛、索引与引用查询
│   ├── graph/graphEngine.ts             # 邻接索引、局部子图和 PRE 计划
│   ├── evaluation/evaluate.ts           # Python 判定语义的 TypeScript 实现
│   ├── evaluation/mastery.ts            # 掌握度公式与分级
│   ├── state/profileStore.ts            # 版本化 localStorage 档案
│   ├── scenarios/scenarioEngine.ts      # add/replace 覆盖与场景建议
│   ├── tasks/taskConverter.ts            # 确定性任务匹配和任务卡
│   ├── diagnostics/types.ts             # 诊断结果契约
│   ├── diagnostics/detectFormat.ts      # 类型、大小和截图模式
│   ├── diagnostics/json.ts              # 通用 JSON 与 COCO 检查
│   ├── diagnostics/textGrid.ts          # TextGrid long text format
│   ├── diagnostics/vocXml.ts            # VOC XML 检查
│   ├── features/dashboard/*             # 四类课程入口
│   ├── features/course/*                # 内容、练习和反馈
│   ├── features/graph/*                 # vis-network 与节点详情
│   ├── features/tasks/*                 # 任务转化器
│   └── features/diagnostics/*           # 文件诊断与报告
│
├── tests/                               # Vitest 领域、组件和 Python 对照测试
└── public/                              # 图标等非权威静态资源

tests/e2e/                               # Playwright 全流程与夹具
evidence/user-trials/                    # 真实试用协议、空表和后续证据
```

## Task 1: Scaffold the application and lock canonical data contracts

**Files:**
- Create: `app/package.json`
- Create: `app/index.html`
- Create: `app/tsconfig.json`
- Create: `app/vite.config.ts`
- Create: `app/src/main.tsx`
- Create: `app/src/data/contracts.ts`
- Create: `app/src/data/rawData.ts`
- Create: `app/tests/data/rawData.test.ts`
- Modify: `.gitignore`

- [ ] **Step 1: Write the failing canonical-data smoke test**

```ts
// app/tests/data/rawData.test.ts
import { describe, expect, it } from "vitest";
import { graph, teachingUnits } from "../../src/data/rawData";

describe("canonical project data", () => {
  it("loads the reviewed Task 1-5 baseline", () => {
    expect(teachingUnits.units).toHaveLength(19);
    expect(teachingUnits.student_visible_unit_ids).toHaveLength(19);
    expect(graph.nodes).toHaveLength(166);
    expect(graph.edges).toHaveLength(240);
  });
});
```

- [ ] **Step 2: Run the test and confirm the application does not exist yet**

Run: `npm --prefix app test -- --run tests/data/rawData.test.ts`

Expected: FAIL because `app/package.json` or `src/data/rawData.ts` does not exist.

- [ ] **Step 3: Add the Vite/TypeScript scaffold and explicit data contracts**

Use these scripts in `app/package.json`:

```json
{
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "build": "tsc --noEmit && vite build",
    "test": "vitest",
    "test:run": "vitest run",
    "test:e2e": "playwright test"
  }
}
```

Define `TeachingUnit`, `Exercise`, `GraphNode`, `GraphEdge`, `ScenarioDocument`, `SourceRegistry`, and their collection roots in `contracts.ts`. `rawData.ts` must import the four canonical roots with paths relative to `app/src/data/`:

```ts
import graphJson from "../../../data/graph/annotation-capability-graph.json";
import teachingUnitsJson from "../../../data/curriculum/teaching-units.json";
import sourceRegistryJson from "../../../data/sources/source-registry.json";
import medicalJson from "../../../data/scenarios/medical.json";
import customerServiceJson from "../../../data/scenarios/customer-service.json";
import inVehicleJson from "../../../data/scenarios/in-vehicle.json";
import contentSafetyJson from "../../../data/scenarios/content-safety.json";

export const graph = graphJson as GraphDocument;
export const teachingUnits = teachingUnitsJson as TeachingUnitDocument;
export const sourceRegistry = sourceRegistryJson as SourceRegistryDocument;
export const scenarios = [medicalJson, customerServiceJson, inVehicleJson, contentSafetyJson] as ScenarioDocument[];
```

Configure Vitest with `environment: "jsdom"` and allow Vite to read the repository parent. Add `app/node_modules/`, `app/dist/`, `test-results/`, and `playwright-report/` to `.gitignore`.

- [ ] **Step 4: Install dependencies and run the smoke test**

Run:

```powershell
Set-Location app
npm install react@^19 react-dom@^19 vis-network@^9
npm install -D typescript@^5 vite@^7 @vitejs/plugin-react@^4 vitest@^3 jsdom@^26 @testing-library/react@^16 @testing-library/jest-dom@^6 @types/react@^19 @types/react-dom@^19 @playwright/test@^1
npm test -- --run tests/data/rawData.test.ts
```

Expected: 1 test passes and `package-lock.json` is created.

- [ ] **Step 5: Commit the scaffold**

```powershell
git add .gitignore app
git commit -m "feat(task6): scaffold teaching web application"
```

## Task 2: Enforce the published teaching-unit gate

**Files:**
- Create: `app/src/data/repository.ts`
- Create: `app/tests/data/repository.test.ts`

- [ ] **Step 1: Write failing tests for visibility and references**

```ts
import { describe, expect, it } from "vitest";
import { createRepository } from "../../src/data/repository";
import { graph, scenarios, sourceRegistry, teachingUnits } from "../../src/data/rawData";

const repo = createRepository({ graph, scenarios, sourceRegistry, teachingUnits });

describe("published teaching repository", () => {
  it("exposes only indexed published student-visible units", () => {
    expect(repo.listConsumableUnits()).toHaveLength(19);
    expect(repo.listConsumableUnits().every((unit) =>
      unit.review_status === "published" && unit.student_visible
    )).toBe(true);
  });

  it("does not turn draft graph nodes into published lessons", () => {
    const draft = graph.nodes.find((node) => node.status === "draft")!;
    expect(repo.getNode(draft.id)?.status).toBe("draft");
    expect(repo.getConsumableUnitsForNode(draft.id).every((unit) =>
      teachingUnits.student_visible_unit_ids.includes(unit.id)
    )).toBe(true);
  });

  it("resolves every visible rule and source reference", () => {
    expect(repo.validate().errors).toEqual([]);
  });
});
```

- [ ] **Step 2: Run the repository test and verify RED**

Run: `npm --prefix app test -- --run tests/data/repository.test.ts`

Expected: FAIL with missing `createRepository`.

- [ ] **Step 3: Implement immutable indexes and validation**

`createRepository()` must construct maps for unit ID, node ID, source ID, scenario ID, outgoing edges, incoming edges, and `teaching_unit_refs`. Define the consumable predicate exactly once:

```ts
const visibleIds = new Set(teachingUnits.student_visible_unit_ids);
const isConsumable = (unit: TeachingUnit) =>
  unit.review_status === "published" &&
  unit.student_visible === true &&
  visibleIds.has(unit.id);
```

`validate()` must report duplicate IDs, missing source/rule/node refs, graph edge endpoints, scenario `base_rule_ref` failures, and visible-index mismatches. Return data, never mutate imported JSON.

- [ ] **Step 4: Run tests and build**

Run:

```powershell
npm --prefix app test -- --run tests/data
npm --prefix app run build
```

Expected: repository tests pass and Vite build exits 0.

- [ ] **Step 5: Commit the publication gate**

```powershell
git add app/src/data app/tests/data
git commit -m "feat(task6): enforce published lesson data gate"
```

## Task 3: Build graph navigation and PRE remediation planning

**Files:**
- Create: `app/src/graph/graphEngine.ts`
- Create: `app/tests/graph/graphEngine.test.ts`

- [ ] **Step 1: Write failing graph-engine tests**

```ts
import { describe, expect, it } from "vitest";
import { createGraphEngine } from "../../src/graph/graphEngine";
import { graph } from "../../src/data/rawData";

const engine = createGraphEngine(graph);

describe("graph engine", () => {
  it("returns typed one-hop relations for a capability", () => {
    const view = engine.neighborhood("CAP-AUD-TRANSCRIBE-PUNCT-001", 1);
    expect(view.nodes.some((node) => node.id === "CAP-AUD-TRANSCRIBE-PUNCT-001")).toBe(true);
    expect(view.edges.every((edge) => view.nodeIds.has(edge.source) && view.nodeIds.has(edge.target))).toBe(true);
  });

  it("orders unmet prerequisites topologically", () => {
    const plan = engine.remediationPlan("CAP-AUD-WAKE-COMMAND-001", () => 0);
    expect(plan.cycleDetected).toBe(false);
    expect(plan.steps.at(-1)?.nodeId).toBe("CAP-AUD-WAKE-COMMAND-001");
    expect(plan.steps.every((step, index) =>
      step.prerequisiteIds.every((id) => plan.steps.findIndex((item) => item.nodeId === id) < index)
    )).toBe(true);
  });
});
```

- [ ] **Step 2: Run the graph tests and verify RED**

Run: `npm --prefix app test -- --run tests/graph/graphEngine.test.ts`

Expected: FAIL with missing `createGraphEngine`.

- [ ] **Step 3: Implement indexed neighborhoods and stable topological planning**

Expose these interfaces:

```ts
export interface GraphView {
  nodes: GraphNode[];
  edges: GraphEdge[];
  nodeIds: Set<string>;
}

export interface RemediationStep {
  nodeId: string;
  prerequisiteIds: string[];
  mastery: number | null;
  skipPractice: boolean;
}

export interface RemediationPlan {
  targetNodeId: string;
  steps: RemediationStep[];
  cycleDetected: boolean;
}
```

Follow incoming `PRE` edges recursively from the target, keep nodes with mastery `< 0.8` or `null`, retain mastered nodes as `skipPractice: true`, and use original graph-node order as the stable tie breaker. If a cycle is detected, return `cycleDetected: true` and no executable steps.

- [ ] **Step 4: Run TypeScript and existing Python graph checks**

Run:

```powershell
npm --prefix app test -- --run tests/graph
python scripts/validate_graph.py data/graph/annotation-capability-graph.json
python -m pytest tests/graph/test_graph_integrity.py -q
```

Expected: TypeScript tests pass; graph validator reports 166 nodes and 240 edges; Python graph tests pass.

- [ ] **Step 5: Commit the graph engine**

```powershell
git add app/src/graph app/tests/graph
git commit -m "feat(task6): add graph navigation and remediation plans"
```

## Task 4: Port deterministic exercise evaluation with Python parity

**Files:**
- Create: `app/src/evaluation/evaluate.ts`
- Create: `app/tests/evaluation/evaluate.test.ts`
- Create: `app/tests/evaluation/pythonParity.test.ts`

- [ ] **Step 1: Write failing evaluator contract tests**

```ts
import { describe, expect, it } from "vitest";
import { teachingUnits } from "../../src/data/rawData";
import { evaluateExercise } from "../../src/evaluation/evaluate";

describe("deterministic exercise evaluator", () => {
  for (const unit of teachingUnits.units) {
    it(`accepts the declared answer for ${unit.id}`, () => {
      const result = evaluateExercise(unit, unit.exercise.answer);
      expect(result.passed).toBe(true);
      expect(result.score).toBeGreaterThanOrEqual(unit.exercise.evaluation.pass_score ?? 1);
      expect(result.ruleRefs).toEqual(unit.rule_refs);
      expect(result.capabilityRefs).toEqual(unit.exercise.capability_refs);
    });
  }
});
```

Add a Node-environment parity test that uses `spawnSync("python", [...])` for each unit, passes its declared answer to `scripts/evaluate_exercise.py`, parses stdout JSON, and compares score, pass state, rule refs, capability refs, and evaluation version.

- [ ] **Step 2: Run evaluator tests and verify RED**

Run: `npm --prefix app test -- --run tests/evaluation`

Expected: FAIL with missing `evaluateExercise`.

- [ ] **Step 3: Implement the evaluator in declared precedence order**

Use this public result:

```ts
export interface EvaluationResult {
  score: number;
  passed: boolean;
  matched: "diagnostic_rule" | "allowed_answer" | "answer" | "unclassified";
  errorType: string | null;
  feedback: string;
  remediation: string[];
  ruleRefs: string[];
  capabilityRefs: string[];
  evaluationVersion: string;
  manualReviewRequired: boolean;
}
```

Implement structural deep equality with unordered object keys and ordered arrays. Match `diagnostic_rules` in array order, then `allowed_answers`, then `answer`; unmatched submissions use declared incorrect feedback and `manual_review_on_unmatched`. Never normalize strings beyond the unit declaration.

- [ ] **Step 4: Run all evaluator and Python parity tests**

Run:

```powershell
npm --prefix app test -- --run tests/evaluation
python -m pytest tests/content -q
```

Expected: all 19 declared answers pass in TypeScript, parity assertions pass, and existing content tests pass.

- [ ] **Step 5: Commit the evaluator**

```powershell
git add app/src/evaluation app/tests/evaluation
git commit -m "feat(task6): port deterministic exercise evaluation"
```

## Task 5: Add mastery and versioned local learning state

**Files:**
- Create: `app/src/evaluation/mastery.ts`
- Create: `app/src/state/profileStore.ts`
- Create: `app/tests/state/profileStore.test.ts`

- [ ] **Step 1: Write failing mastery and persistence tests**

```ts
import { beforeEach, describe, expect, it } from "vitest";
import { applyExerciseScore, applyDiagnosticPenalty, masteryBand } from "../../src/evaluation/mastery";
import { createProfileStore } from "../../src/state/profileStore";

describe("learning profile", () => {
  beforeEach(() => localStorage.clear());

  it("uses the approved mastery formula and severity penalties", () => {
    expect(applyExerciseScore(0.4, 1)).toBeCloseTo(0.61);
    expect(applyDiagnosticPenalty(0.61, "severe")).toBeCloseTo(0.46);
    expect(masteryBand(0.8)).toBe("mastered");
  });

  it("isolates general and scenario mastery", () => {
    const store = createProfileStore(localStorage);
    store.recordExercise({ capabilityId: "CAP-AUD-TRANSCRIBE-PUNCT-001", score: 1, scenarioId: null, evaluationVersion: "1.1.0" });
    store.recordExercise({ capabilityId: "CAP-AUD-TRANSCRIBE-PUNCT-001", score: 0, scenarioId: "SCN-CUSTOMER-SERVICE-001", evaluationVersion: "1.1.0" });
    expect(store.snapshot().generalMastery["CAP-AUD-TRANSCRIBE-PUNCT-001"]).not.toBe(
      store.snapshot().scenarioMastery["CAP-AUD-TRANSCRIBE-PUNCT-001::SCN-CUSTOMER-SERVICE-001"]
    );
  });
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm --prefix app test -- --run tests/state`

Expected: FAIL with missing mastery and profile modules.

- [ ] **Step 3: Implement profile schema version 1**

Persist under `bhzd.learning-profile.v1`. Store general mastery, scenario mastery, attempts, last mode, last scenario, last unit, and last node. Invalid JSON resets only after returning a recoverable `loadError`; valid version-1 data loads unchanged. `reset()` removes only this application key.

Implement thresholds `[0,0.4) beginner`, `[0.4,0.6) needs_work`, `[0.6,0.8) consolidating`, `[0.8,1] mastered`, score update `clamp(old + 0.35 * (score - old))`, and penalties 0.03/0.08/0.15.

- [ ] **Step 4: Run state tests**

Run: `npm --prefix app test -- --run tests/state tests/evaluation`

Expected: all tests pass, including persistence after a new store instance.

- [ ] **Step 5: Commit learning state**

```powershell
git add app/src/evaluation/mastery.ts app/src/state app/tests/state
git commit -m "feat(task6): persist general and scenario mastery"
```

## Task 6: Implement scene overrides and deterministic task conversion

**Files:**
- Create: `app/src/scenarios/scenarioEngine.ts`
- Create: `app/src/tasks/taskConverter.ts`
- Create: `app/tests/tasks/taskConverter.test.ts`

- [ ] **Step 1: Write failing scenario and task-card tests**

```ts
import { describe, expect, it } from "vitest";
import { createRepository } from "../../src/data/repository";
import { graph, scenarios, sourceRegistry, teachingUnits } from "../../src/data/rawData";
import { createTaskConverter } from "../../src/tasks/taskConverter";

const converter = createTaskConverter(createRepository({ graph, scenarios, sourceRegistry, teachingUnits }));

describe("task converter", () => {
  it("creates PRE-ordered cards for an explicit audio task", () => {
    const result = converter.convert("对车载语音做唤醒词边界和命令意图标注", "SCN-IN-VEHICLE-001");
    expect(result.kind).toBe("cards");
    if (result.kind !== "cards") throw new Error("expected cards");
    expect(result.cards.at(-1)?.capabilityIds).toContain("CAP-AUD-WAKE-COMMAND-001");
    expect(result.cards.every((card) => card.steps.length >= 3 && card.steps.length <= 9)).toBe(true);
  });

  it("asks for the data type instead of guessing", () => {
    expect(converter.convert("帮我做一个标注任务", null)).toMatchObject({ kind: "clarification", missing: ["data_type"] });
  });

  it("suggests but does not switch a detected scene", () => {
    expect(converter.convert("医疗文本实体标注", "SCN-CUSTOMER-SERVICE-001")).toMatchObject({
      suggestedScenarioId: "SCN-MEDICAL-001",
      appliedScenarioId: "SCN-CUSTOMER-SERVICE-001"
    });
  });
});
```

- [ ] **Step 2: Run task tests and verify RED**

Run: `npm --prefix app test -- --run tests/tasks`

Expected: FAIL with missing `createTaskConverter`.

- [ ] **Step 3: Implement explicit keyword evidence and add/replace rules**

Define auditable keyword sets for the four data types, four scenarios, and graph labels. Return either:

```ts
type ConversionResult =
  | { kind: "clarification"; missing: Array<"data_type" | "goal">; candidates: string[]; appliedScenarioId: string | null; suggestedScenarioId: string | null }
  | { kind: "cards"; cards: TaskCard[]; matchEvidence: string[]; appliedScenarioId: string | null; suggestedScenarioId: string | null };
```

Task cards must include name, objectives, role, scene, capability path, knowledge IDs, certificate IDs, steps, common errors, resource IDs, and self-check items. Apply only published scenario overrides whose declared `data_types` include the matched type; preserve base rules for `add` and replace only the referenced rule for `replace`.

- [ ] **Step 4: Run task and scenario validation**

Run:

```powershell
npm --prefix app test -- --run tests/tasks
python scripts/validate_scenarios.py
```

Expected: task tests pass and scenario validation reports 4 scenarios, 9 overrides, and 9 examples.

- [ ] **Step 5: Commit task conversion**

```powershell
git add app/src/scenarios app/src/tasks app/tests/tasks
git commit -m "feat(task6): convert enterprise tasks into learning cards"
```

## Task 7: Add safe four-format diagnostics and screenshot-only mode

**Files:**
- Create: `app/src/diagnostics/types.ts`
- Create: `app/src/diagnostics/detectFormat.ts`
- Create: `app/src/diagnostics/json.ts`
- Create: `app/src/diagnostics/textGrid.ts`
- Create: `app/src/diagnostics/vocXml.ts`
- Create: `app/src/diagnostics/diagnose.ts`
- Create: `app/tests/diagnostics/diagnostics.test.ts`
- Create: `tests/e2e/fixtures/coco-valid.json`
- Create: `tests/e2e/fixtures/coco-broken.json`
- Create: `tests/e2e/fixtures/sample.TextGrid`
- Create: `tests/e2e/fixtures/voc-invalid.xml`
- Create: `tests/e2e/fixtures/explanation.png`

- [ ] **Step 1: Write failing parser and safety tests**

```ts
import { describe, expect, it } from "vitest";
import { diagnoseFile } from "../../src/diagnostics/diagnose";

describe("local diagnostics", () => {
  it("rejects files larger than five MiB", async () => {
    const file = new File([new Uint8Array(5 * 1024 * 1024 + 1)], "large.json", { type: "application/json" });
    expect(await diagnoseFile(file, { dataType: "text", targetUnitId: null })).toMatchObject({ status: "rejected", code: "file_too_large" });
  });

  it("keeps screenshots out of scoring", async () => {
    const file = new File([new Uint8Array([137, 80, 78, 71])], "explanation.png", { type: "image/png" });
    expect(await diagnoseFile(file, { dataType: "image", targetUnitId: null })).toMatchObject({
      status: "explanation_only", masteryImpact: false, score: null
    });
  });

  it("finds invalid COCO category references", async () => {
    const body = JSON.stringify({ images: [{ id: 1, width: 100, height: 100 }], categories: [{ id: 1, name: "person" }], annotations: [{ id: 1, image_id: 1, category_id: 99, bbox: [0, 0, 10, 10] }] });
    const result = await diagnoseFile(new File([body], "sample.json", { type: "application/json" }), { dataType: "image", targetUnitId: null });
    expect(result.issues).toContainEqual(expect.objectContaining({ code: "missing_category_reference", severity: "severe" }));
  });
});
```

- [ ] **Step 2: Run diagnostic tests and verify RED**

Run: `npm --prefix app test -- --run tests/diagnostics`

Expected: FAIL with missing `diagnoseFile`.

- [ ] **Step 3: Implement bounded local parsers**

Use `File.text()`, `JSON.parse()`, and browser `DOMParser`; never use `fetch` or persist file bodies. Return:

```ts
export interface DiagnosticIssue {
  code: string;
  severity: "minor" | "moderate" | "severe";
  message: string;
  ruleRefs: string[];
  capabilityRefs: string[];
  remediation: string[];
}

export interface DiagnosticReport {
  status: "complete" | "manual_review" | "explanation_only" | "rejected";
  format: "json" | "coco" | "textgrid" | "voc" | "image" | "unknown";
  issues: DiagnosticIssue[];
  masteryImpact: boolean;
  score: number | null;
  code?: string;
}
```

COCO checks ID uniqueness/references and positive bbox dimensions; VOC checks required elements and `xmin < xmax`, `ymin < ymax`, within optional image size; TextGrid long format checks ordered non-overlapping intervals and `xmin <= xmax`; generic JSON validates the selected exercise structure. Unknown semantic correctness returns `manual_review`.

- [ ] **Step 4: Run diagnostic tests and ensure no file bytes persist**

Run: `npm --prefix app test -- --run tests/diagnostics`

Expected: parser tests pass; localStorage assertions contain no fixture text or binary data.

- [ ] **Step 5: Commit diagnostics**

```powershell
git add app/src/diagnostics app/tests/diagnostics tests/e2e/fixtures
git commit -m "feat(task6): diagnose structured annotation exports locally"
```

## Task 8: Build the accessible application shell and visual system

**Files:**
- Create: `app/src/app/App.tsx`
- Create: `app/src/app/app.css`
- Create: `app/src/app/AppContext.tsx`
- Create: `app/src/components/Button.tsx`
- Create: `app/src/components/Panel.tsx`
- Create: `app/src/features/dashboard/Dashboard.tsx`
- Create: `app/tests/app/App.test.tsx`
- Modify: `app/src/main.tsx`

- [ ] **Step 1: Write a failing shell accessibility test**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "../../src/app/App";

it("opens all four course domains from the keyboard", async () => {
  render(<App />);
  expect(screen.getByRole("banner")).toHaveTextContent("标航智导");
  for (const name of ["文本", "图像", "语音", "视频"]) {
    expect(screen.getByRole("button", { name: new RegExp(name) })).toBeEnabled();
  }
  await userEvent.setup().click(screen.getByRole("button", { name: /语音/ }));
  expect(screen.getByRole("main")).toHaveTextContent("语音");
});
```

- [ ] **Step 2: Run the shell test and verify RED**

Run: `npm --prefix app test -- --run tests/app/App.test.tsx`

Expected: FAIL because `App` does not exist.

- [ ] **Step 3: Implement the shell and approved design tokens**

Use a skip link, semantic `header/nav/main/aside`, roving work-mode buttons, visible focus, and a confirmation dialog for reset. Define CSS variables:

```css
:root {
  --space-blue: #0b1f3a;
  --star-cyan: #00c6ff;
  --navigation-orange: #ff8a3d;
  --mastery-green: #2ec27e;
  --error-red: #e5484d;
  --paper-white: #f7f8fa;
  --ink: #10233f;
}

.workspace { display: grid; grid-template-columns: minmax(18rem, 0.85fr) minmax(30rem, 1.5fr) minmax(18rem, 0.85fr); min-height: calc(100vh - 4.5rem); }
@media (max-width: 960px) { .workspace { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { scroll-behavior: auto !important; animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; } }
```

Dashboard cards show the current consumable counts 5/5/6/3 from repository data rather than hard-coded totals.

- [ ] **Step 4: Run component tests and production build**

Run:

```powershell
npm --prefix app test -- --run tests/app
npm --prefix app run build
```

Expected: shell test passes; type check and build exit 0.

- [ ] **Step 5: Commit the application shell**

```powershell
git add app/src/app app/src/components app/src/features/dashboard app/src/main.tsx app/tests/app
git commit -m "feat(task6): add accessible star-map learning shell"
```

## Task 9: Connect lessons, structured practice, feedback, and mastery

**Files:**
- Create: `app/src/features/course/CourseBrowser.tsx`
- Create: `app/src/features/course/LessonView.tsx`
- Create: `app/src/features/course/StructuredResponseEditor.tsx`
- Create: `app/src/features/course/FeedbackPanel.tsx`
- Create: `app/src/features/course/AudioAsset.tsx`
- Create: `app/tests/course/learningLoop.test.tsx`
- Modify: `app/src/app/App.tsx`

- [ ] **Step 1: Write a failing full learning-loop component test**

```tsx
it("completes a text lesson and records rule-backed feedback", async () => {
  render(<App />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /文本/ }));
  await user.click(screen.getByRole("button", { name: /校验封闭文本标签集/ }));
  await user.clear(screen.getByLabelText("结构化答案"));
  await user.type(screen.getByLabelText("结构化答案"), '{"labels":["negative"]}');
  await user.click(screen.getByRole("button", { name: "提交自检" }));
  expect(screen.getByRole("status")).toHaveTextContent("通过");
  expect(screen.getByText(/规则依据/)).toBeVisible();
  expect(screen.getByText(/掌握度/)).toBeVisible();
});
```

- [ ] **Step 2: Run the learning-loop test and verify RED**

Run: `npm --prefix app test -- --run tests/course/learningLoop.test.tsx`

Expected: FAIL because course components are missing.

- [ ] **Step 3: Implement published content and response editing**

Render every declared field without `dangerouslySetInnerHTML`. Use select/radio controls when the response space exposes a finite scalar set; otherwise use a JSON textarea initialized with a type-shaped empty object, never the answer values. Catch JSON syntax errors before evaluation. `AudioAsset` maps the authorized segmentation asset ref to a Vite `?url` import and shows structured-fixture notices for non-media exercises.

On classified deterministic results, update the correct general or scene profile. On `manualReviewRequired`, render feedback and remediation but do not update mastery.

- [ ] **Step 4: Run all component and evaluator tests**

Run: `npm --prefix app test -- --run tests/course tests/evaluation tests/state`

Expected: learning loop and domain tests pass.

- [ ] **Step 5: Commit the learning loop**

```powershell
git add app/src/features/course app/src/app/App.tsx app/tests/course
git commit -m "feat(task6): connect lessons practice and mastery feedback"
```

## Task 10: Add vis-network graph exploration and progress panel

**Files:**
- Create: `app/src/features/graph/GraphCanvas.tsx`
- Create: `app/src/features/graph/graphVisuals.ts`
- Create: `app/src/features/graph/NodeDetails.tsx`
- Create: `app/src/features/graph/ProgressPanel.tsx`
- Create: `app/tests/graph/GraphCanvas.test.tsx`
- Modify: `app/src/app/App.tsx`

- [ ] **Step 1: Write a failing graph interaction test using a network adapter mock**

```tsx
it("opens node relations and a consumable linked lesson", async () => {
  render(<GraphCanvas networkFactory={fakeNetworkFactory} />);
  fakeNetworkFactory.emitSelect("CAP-AUD-TRANSCRIBE-PUNCT-001");
  expect(await screen.findByRole("heading", { name: /转写/ })).toBeVisible();
  expect(screen.getByText(/前置能力/)).toBeVisible();
  expect(screen.getByRole("button", { name: /开始课程/ })).toBeEnabled();
});
```

- [ ] **Step 2: Run graph component tests and verify RED**

Run: `npm --prefix app test -- --run tests/graph/GraphCanvas.test.tsx`

Expected: FAIL because `GraphCanvas` does not exist.

- [ ] **Step 3: Implement the vis-network adapter and status-safe details**

Map shapes as CAP circle, KNG diamond, TSK hexagon, SCN box, RES dot, CERT star. Map mastery to fill/border without hiding real node status. Initial view uses all nodes; selection replaces it with a two-hop neighborhood and offers “返回总览”. NodeDetails lists typed incoming/outgoing relations and enables lesson launch only for repository-consumable links.

Destroy the Network instance on unmount. Disable physics after stabilization and disable animations under reduced motion. Provide a searchable text list mirroring graph nodes so keyboard-only users can select any node.

- [ ] **Step 4: Run graph tests and build**

Run: `npm --prefix app test -- --run tests/graph && npm --prefix app run build`

Expected: graph engine and component tests pass; build exits 0.

- [ ] **Step 5: Commit graph UI**

```powershell
git add app/src/features/graph app/src/app/App.tsx app/tests/graph
git commit -m "feat(task6): visualize graph-driven learning progress"
```

## Task 11: Connect task conversion, scenarios, diagnostics, and remediation UI

**Files:**
- Create: `app/src/features/tasks/TaskConverterView.tsx`
- Create: `app/src/features/tasks/TaskCardView.tsx`
- Create: `app/src/features/diagnostics/DiagnosticView.tsx`
- Create: `app/src/features/diagnostics/DiagnosticReportView.tsx`
- Create: `app/src/features/scenarios/ScenarioSwitcher.tsx`
- Create: `app/tests/features/taskAndDiagnosis.test.tsx`
- Modify: `app/src/app/App.tsx`

- [ ] **Step 1: Write failing scenario, task, and screenshot tests**

```tsx
it("requires confirmation before applying a suggested scenario", async () => {
  render(<App />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("tab", { name: "任务转化" }));
  await user.type(screen.getByLabelText("企业任务描述"), "医疗文本实体标注");
  await user.click(screen.getByRole("button", { name: "生成学习任务卡" }));
  expect(screen.getByText(/建议切换到医疗场景/)).toBeVisible();
  expect(screen.getByLabelText("当前场景")).toHaveValue("通用规则");
});

it("keeps screenshots in explanation-only mode", async () => {
  render(<App />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("tab", { name: "标注诊断" }));
  await user.upload(screen.getByLabelText("上传标注导出文件"), pngFixture);
  expect(await screen.findByText(/辅助讲解模式/)).toBeVisible();
  expect(screen.queryByText(/掌握度已更新/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the feature test and verify RED**

Run: `npm --prefix app test -- --run tests/features`

Expected: FAIL because the views are missing.

- [ ] **Step 3: Implement the three workspaces**

TaskConverterView renders clarification choices, match evidence, scene suggestion, and PRE-ordered cards. ScenarioSwitcher exposes common plus four scenes, disables scenes unsupported by the current data type, and requires confirmation for suggestions. DiagnosticView requires data type/target context, accepts only `.json`, `.TextGrid`, `.xml`, `.png`, `.jpg`, `.jpeg`, renders format errors without clearing state, and applies mastery only when `masteryImpact` is true.

DiagnosticReportView groups issues by severity and shows rule refs, capability links, remediation resources, and the graph engine's PRE plan. All displayed “paths” use the label “按前置关系排序的补强计划”.

- [ ] **Step 4: Run feature and domain tests**

Run: `npm --prefix app test -- --run tests/features tests/tasks tests/diagnostics tests/graph tests/state`

Expected: all workspaces and deterministic domain tests pass.

- [ ] **Step 5: Commit the remaining product workspaces**

```powershell
git add app/src/features app/src/app/App.tsx app/tests/features
git commit -m "feat(task6): connect task conversion and diagnosis workspaces"
```

## Task 12: Add end-to-end, browser, accessibility, and regression verification

**Files:**
- Create: `app/playwright.config.ts`
- Create: `tests/e2e/learning-domains.spec.ts`
- Create: `tests/e2e/graph-and-scenario.spec.ts`
- Create: `tests/e2e/task-conversion.spec.ts`
- Create: `tests/e2e/diagnostics.spec.ts`
- Create: `tests/e2e/accessibility-and-state.spec.ts`
- Create: `tests/e2e/helpers.ts`
- Modify: `app/package.json`

- [ ] **Step 1: Write the E2E tests before configuring the server**

```ts
// tests/e2e/learning-domains.spec.ts
import { expect, test } from "@playwright/test";

for (const domain of ["文本", "图像", "语音", "视频"]) {
  test(`${domain} completes a representative learning loop`, async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: new RegExp(domain) }).click();
    await page.getByTestId("lesson-card").first().click();
    await page.getByRole("button", { name: "载入标准结构示例" }).click();
    await page.getByRole("button", { name: "提交自检" }).click();
    await expect(page.getByRole("status")).toContainText("反馈");
    await expect(page.getByTestId("mastery-summary")).toBeVisible();
  });
}
```

Add separate E2E assertions for node navigation, two-scene comparison, task clarification, valid/invalid diagnostic files, screenshot no-score behavior, persistence after reload, reset, keyboard focus, 390px mobile viewport, and reduced-motion media emulation.

- [ ] **Step 2: Run Playwright and verify RED**

Run: `npm --prefix app run test:e2e`

Expected: FAIL because Playwright configuration and/or E2E-only helpers are missing.

- [ ] **Step 3: Configure deterministic E2E helpers without exposing answers in production**

Set `testDir: "../tests/e2e"`, `baseURL: "http://127.0.0.1:4173"`, and a web server command `npm run dev -- --port 4173`. Configure Chromium by default and a second project with `channel: "msedge"` when Edge is installed. The “载入标准结构示例” control must be enabled only when `import.meta.env.MODE === "test"`; production builds must not render it.

- [ ] **Step 4: Run the complete automated verification matrix**

Run:

```powershell
python -m pytest -q
python scripts/validate_graph.py data/graph/annotation-capability-graph.json
python scripts/validate_scenarios.py
npm --prefix app run test:run
npm --prefix app run build
npm --prefix app run test:e2e
```

Expected: 0 failures; graph is 166/240; scenarios are 4/9/9; Vite build succeeds; Chromium and available Edge projects pass.

- [ ] **Step 5: Perform visual inspection in real browser sizes**

Start: `npm --prefix app run dev -- --port 4173`

Inspect 1440×900 and 390×844: dashboard, graph total/local view, lesson, correct/incorrect feedback, task cards, structured diagnostic report, screenshot auxiliary mode, keyboard focus, and reduced motion. Record only observed issues; fix product code and rerun affected tests before continuing.

- [ ] **Step 6: Commit E2E coverage**

```powershell
git add app/playwright.config.ts app/package.json app/package-lock.json tests/e2e
git commit -m "test(task6): cover complete teaching and diagnosis flows"
```

## Task 13: Prepare real-trial evidence, update governing documents, and close only verified steps

**Files:**
- Create: `evidence/user-trials/README.md`
- Create: `evidence/user-trials/trial-protocol.md`
- Create: `evidence/user-trials/trial-record-template.md`
- Create: `evidence/user-trials/session-summary.schema.json`
- Modify: `docs/superpowers/plans/2026-07-12-annotation-teaching-agent.md`
- Modify: `docs/superpowers/specs/2026-07-14-task6-teaching-application-design.md`
- Modify: `docs/logs/document-changelog.md`
- Modify: `E:\ObsidianWorkSpace\codex\Work Log 2026-07-14.md`

- [ ] **Step 1: Create trial files that cannot be mistaken for completed evidence**

`README.md` must state `status: awaiting_human_domain_release_and_participants`. The protocol uses the same representative sequence for each participant: one text, image, audio, and video task; one scenario comparison; one enterprise-task conversion; one structured diagnosis; and one remediation plan. The record template requires participant role, consent/authorization reference, start/end time, completion status, errors, feedback, revision decision, retest result, and recorder identity.

The JSON schema must require `participant_role`, `tasks`, `started_at`, `finished_at`, `observations`, `revision_decisions`, `retest`, and `release_approval_ref`; it must not permit a default participant or generated approval.

- [ ] **Step 2: Verify trial templates contain no fabricated outcomes**

Run:

```powershell
rg -n "通过试用|全部满意|教师已批准|学生已完成" evidence/user-trials
```

Expected: no matches. Any instructional example must be removed rather than presented as a result.

- [ ] **Step 3: Mark only Task 6 Steps 1-2 after fresh engineering verification**

Change Task 6 Step 1 and Step 2 checkboxes to `[x]` only if Task 12's full command matrix passed in the current run. Keep Step 3 `[ ]` and state the exact human release/participant blocker until genuine records exist. Change the Task 6 design status to `工程实现已验证；等待真实试用` under the same condition.

- [ ] **Step 4: Append required document and external work logs**

The repository document changelog entry must list every changed project document, implementation reason, exact commands/results, browser inspection evidence, and remaining human verification. Append one external work-log entry using the mandated `What was done / Key decisions / Results` structure and the actual completion time.

- [ ] **Step 5: Run final clean verification and inspect the diff**

Run:

```powershell
git diff --check
python -m pytest -q
npm --prefix app run test:run
npm --prefix app run build
npm --prefix app run test:e2e
git status --short
```

Expected: no whitespace errors and no test/build/E2E failures. Status may contain only the intended Task 6 implementation, evidence templates, and documentation/log changes.

- [ ] **Step 6: Commit verified engineering completion**

```powershell
git add app tests/e2e evidence/user-trials docs .gitignore
git commit -m "feat(task6): deliver verified teaching application"
```

- [ ] **Step 7: Stop at the real-human gate when evidence is absent**

If human domain release and 2-3 genuine participant records are unavailable, report Task 6 as “Steps 1-2 complete; Step 3 awaiting real trial” and do not mark the task complete. When genuine evidence is later supplied, validate required fields, apply justified revisions, rerun the full matrix, record retest outcomes, mark Step 3 `[x]`, append both logs, and create a separate completion commit.

---

## Final definition of done

- The application opens in current Windows Chrome/Edge and exposes four content domains.
- Only consumable lessons open; draft graph structure is labeled truthfully.
- All 19 current lessons render and their declared answers pass TypeScript/Python parity.
- Graph, scenarios, task cards, mastery, diagnostics, screenshot restriction, and PRE remediation are deterministic and tested.
- Python suite, graph/scenario validators, Vitest, build, Playwright, accessibility checks, and visual inspection have fresh evidence.
- Real human-domain release and 2-3 genuine teacher/student trial records exist; otherwise Task 6 remains explicitly incomplete at Step 3.
