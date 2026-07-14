export interface ProductMetadataValue {
  readonly value: string;
  readonly sourceRef: string;
}

export interface ApprovedProductMetadata {
  readonly role: ProductMetadataValue;
  readonly defaultScene: ProductMetadataValue;
  readonly scenarioDocuments: Readonly<Record<string, string>>;
}

const ROLE = Object.freeze({
  value: "AI数据标注工程师",
  sourceRef: "docs/标航智导.md#4.1-岗位定义",
});

const DEFAULT_SCENE = Object.freeze({
  value: "通用标注规则",
  sourceRef:
    "docs/superpowers/specs/2026-07-14-task6-teaching-application-design.md#6.4-场景切换",
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
    scenarioDocuments: SCENARIO_DOCUMENTS,
  });
