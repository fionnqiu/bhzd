export interface ProductMetadataValue {
  readonly value: string;
  readonly sourceRef: string;
}

export interface ProductMetadataSteps {
  readonly values: readonly string[];
  readonly sourceRef: string;
}

export interface ApprovedProductMetadata {
  readonly role: ProductMetadataValue;
  readonly defaultScene: ProductMetadataValue;
  readonly structureSteps: ProductMetadataSteps;
  readonly scenarioDocuments: Readonly<Record<string, string>>;
}

const ROLE = Object.freeze({
  value: "AI数据标注工程师",
  sourceRef: "docs/标航智导.md#4.1-岗位定义",
});

const DEFAULT_SCENE = Object.freeze({
  value: "通用标注规则",
  sourceRef:
    "docs/教学内容与图谱数据规范.md#4-场景扩展规范",
});

const STRUCTURE_STEP_VALUES = Object.freeze([
  "在能力图谱中定位当前能力及其 PRE 前置关系",
  "阅读已发布规则或当前开发态结构节点说明",
  "完成任务卡自检并确认下一学习步骤",
]);

const STRUCTURE_STEPS = Object.freeze({
  values: STRUCTURE_STEP_VALUES,
  sourceRef: "docs/标航智导.md#54-工具二标注任务转化",
});

const SCENARIO_DOCUMENTS: Readonly<Record<string, string>> = Object.freeze({
  "SCN-MEDICAL-001":
    "data/scenarios/medical.json#scenario:SCN-MEDICAL-001",
  "SCN-CUSTOMER-SERVICE-001":
    "data/scenarios/customer-service.json#scenario:SCN-CUSTOMER-SERVICE-001",
  "SCN-IN-VEHICLE-001":
    "data/scenarios/in-vehicle.json#scenario:SCN-IN-VEHICLE-001",
  "SCN-CONTENT-SAFETY-001":
    "data/scenarios/content-safety.json#scenario:SCN-CONTENT-SAFETY-001",
});

export const APPROVED_PRODUCT_METADATA: ApprovedProductMetadata =
  Object.freeze({
    role: ROLE,
    defaultScene: DEFAULT_SCENE,
    structureSteps: STRUCTURE_STEPS,
    scenarioDocuments: SCENARIO_DOCUMENTS,
  });
