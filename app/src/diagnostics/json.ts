import type {
  DiagnosticIssue,
  DiagnosticSeverity,
} from "./types";

export interface JsonInspection {
  readonly value: unknown;
  readonly isCoco: boolean;
  readonly issues: readonly DiagnosticIssue[];
}

const issue = (
  code: string,
  severity: DiagnosticSeverity,
  message: string,
): DiagnosticIssue => ({
  code,
  severity,
  message,
  ruleRefs: [],
  capabilityRefs: [],
  remediation: [],
});

const hasOwn = (record: Record<string, unknown>, key: string): boolean =>
  Object.prototype.hasOwnProperty.call(record, key);

export const isPlainObject = (value: unknown): value is Record<string, unknown> => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
};

const isFiniteNumber = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

type Identifier = string | number;

const singular = (key: "images" | "annotations" | "categories"): string => {
  if (key === "categories") {
    return "category";
  }
  return key.slice(0, -1);
};

const identifier = (value: unknown): Identifier | null => {
  if (typeof value === "string" && value.trim().length > 0) {
    return value;
  }
  if (typeof value === "number" && Number.isSafeInteger(value)) {
    return value;
  }
  return null;
};

const idKey = (value: Identifier): string =>
  `${typeof value}:${String(value)}`;

const hasCocoAnnotationShape = (value: unknown): boolean => {
  if (!Array.isArray(value)) {
    return false;
  }
  return value.some(
    (candidate) =>
      isPlainObject(candidate) &&
      ["image_id", "category_id", "bbox"].some((field) => hasOwn(candidate, field)),
  );
};

/** Infer COCO intent conservatively so generic annotations-only responses stay JSON. */
export const hasCocoIntent = (value: Record<string, unknown>): boolean => {
  const collectionKeys = ["images", "annotations", "categories"] as const;
  const present = collectionKeys.filter((key) => hasOwn(value, key));
  if (present.length >= 2) {
    return true;
  }
  return present.length === 1 && present[0] === "annotations"
    ? hasCocoAnnotationShape(value.annotations)
    : false;
};

interface IndexedCollection {
  readonly values: readonly Record<string, unknown>[];
  readonly ids: ReadonlyMap<string, Identifier>;
}

const collection = (
  root: Record<string, unknown>,
  key: "images" | "annotations" | "categories",
  issues: DiagnosticIssue[],
): IndexedCollection => {
  const raw = root[key];
  if (!Array.isArray(raw)) {
    issues.push(
      issue(
        `missing_${key}_array`,
        "severe",
        `COCO root must contain a ${key} array.`,
      ),
    );
    return { values: [], ids: new Map<string, Identifier>() };
  }

  const values: Record<string, unknown>[] = [];
  const ids = new Map<string, Identifier>();
  for (const [index, candidate] of raw.entries()) {
    if (!isPlainObject(candidate)) {
      issues.push(
        issue(
          `invalid_${singular(key)}_entry`,
          "severe",
          `${key}[${index}] must be an object.`,
        ),
      );
      continue;
    }
    values.push(candidate);
    const candidateId = identifier(candidate.id);
    if (candidateId === null) {
      issues.push(
        issue(
          `missing_${singular(key)}_id`,
          "severe",
          `${key}[${index}].id must be a non-empty string or safe integer.`,
        ),
      );
      continue;
    }
    const keyValue = idKey(candidateId);
    if (ids.has(keyValue)) {
      issues.push(
        issue(
          `duplicate_${singular(key)}_id`,
          "severe",
          `${key}[${index}] duplicates id ${String(candidateId)}.`,
        ),
      );
      continue;
    }
    ids.set(keyValue, candidateId);
  }
  return { values, ids };
};

const findId = (ids: ReadonlyMap<string, Identifier>, value: unknown): boolean => {
  const candidate = identifier(value);
  return candidate !== null && ids.has(idKey(candidate));
};

const validateCocoObject = (root: Record<string, unknown>): DiagnosticIssue[] => {
  const issues: DiagnosticIssue[] = [];
  const images = collection(root, "images", issues);
  const annotations = collection(root, "annotations", issues);
  const categories = collection(root, "categories", issues);

  for (const [index, image] of images.values.entries()) {
    for (const field of ["width", "height"] as const) {
      const value = image[field];
      if (!isFiniteNumber(value) || value <= 0) {
        issues.push(
          issue(
            `invalid_image_${field}`,
            "severe",
            `images[${index}].${field} must be a positive finite number.`,
          ),
        );
      }
    }
  }

  for (const [index, category] of categories.values.entries()) {
    if (typeof category.name !== "string" || category.name.trim().length === 0) {
      issues.push(
        issue(
          "missing_category_name",
          "moderate",
          `categories[${index}].name must be a non-empty string.`,
        ),
      );
    }
  }

  const imageById = new Map<string, Record<string, unknown>>();
  for (const image of images.values) {
    const imageId = identifier(image.id);
    if (imageId !== null) {
      imageById.set(idKey(imageId), image);
    }
  }

  for (const [index, annotation] of annotations.values.entries()) {
    if (!findId(images.ids, annotation.image_id)) {
      issues.push(
        issue(
          "missing_image_reference",
          "severe",
          `annotations[${index}].image_id does not reference an image.`,
        ),
      );
    }
    if (!findId(categories.ids, annotation.category_id)) {
      issues.push(
        issue(
          "missing_category_reference",
          "severe",
          `annotations[${index}].category_id does not reference a category.`,
        ),
      );
    }

    const bbox = annotation.bbox;
    if (!Array.isArray(bbox) || bbox.length !== 4 || !bbox.every(isFiniteNumber)) {
      issues.push(
        issue(
          "invalid_bbox",
          "severe",
          `annotations[${index}].bbox must contain four finite numbers.`,
        ),
      );
      continue;
    }
    const [x, y, width, height] = bbox;
    if (width <= 0 || height <= 0) {
      issues.push(
        issue(
          "non_positive_bbox",
          "severe",
          `annotations[${index}].bbox width and height must be positive.`,
        ),
      );
    }
    if (x < 0 || y < 0) {
      issues.push(
        issue(
          "negative_bbox_origin",
          "severe",
          `annotations[${index}].bbox origin cannot be negative.`,
        ),
      );
    }

    const imageId = identifier(annotation.image_id);
    const image = imageId === null ? undefined : imageById.get(idKey(imageId));
    if (image !== undefined && isFiniteNumber(image.width) && isFiniteNumber(image.height)) {
      if (x + width > image.width || y + height > image.height) {
        issues.push(
          issue(
            "bbox_out_of_bounds",
            "severe",
            `annotations[${index}].bbox exceeds its image bounds.`,
          ),
        );
      }
    }
  }

  return issues;
};

/** Parse JSON once and perform COCO structural checks when its root advertises COCO fields. */
export const inspectJsonText = (text: string): JsonInspection => {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return {
      value: undefined,
      isCoco: false,
      issues: [issue("corrupted_json", "severe", "The JSON document could not be parsed.")],
    };
  }

  if (!isPlainObject(value)) {
    return {
      value,
      isCoco: false,
      issues: [
        issue(
          "json_root_not_object",
          "severe",
          "The JSON root must be a plain object.",
        ),
      ],
    };
  }

  const isCoco = hasCocoIntent(value);
  return {
    value,
    isCoco,
    issues: isCoco ? validateCocoObject(value) : [],
  };
};

export const validateCoco = (value: unknown): readonly DiagnosticIssue[] =>
  isPlainObject(value)
    ? validateCocoObject(value)
    : [issue("json_root_not_object", "severe", "The COCO root must be an object.")];

export const parseJson = inspectJsonText;

type JsonShape =
  | { readonly kind: "null" }
  | { readonly kind: "boolean" }
  | { readonly kind: "number" }
  | { readonly kind: "string" }
  | { readonly kind: "array"; readonly items: readonly JsonShape[] }
  | { readonly kind: "object"; readonly fields: ReadonlyMap<string, JsonShape> };

export const MAX_JSON_RESPONSE_DEPTH = 128;
export const MAX_JSON_RESPONSE_NODES = 100_000;

interface JsonTraversalFrame {
  readonly value: unknown;
  readonly depth: number;
}

/** Bound untrusted JSON before any recursive response-shape comparison. */
export const validateJsonResponseComplexity = (
  value: unknown,
): readonly DiagnosticIssue[] => {
  const stack: JsonTraversalFrame[] = [{ value, depth: 0 }];
  const seen = new WeakSet<object>();
  let visited = 0;

  while (stack.length > 0) {
    const frame = stack.pop();
    if (frame === undefined) {
      break;
    }
    visited += 1;
    if (visited > MAX_JSON_RESPONSE_NODES) {
      return [
        issue(
          "response_structure_too_large",
          "moderate",
          "The JSON response contains too many nested values for local diagnosis.",
        ),
      ];
    }
    if (frame.depth > MAX_JSON_RESPONSE_DEPTH) {
      return [
        issue(
          "response_structure_too_deep",
          "moderate",
          "The JSON response nesting depth exceeds the local diagnosis limit.",
        ),
      ];
    }

    const candidate = frame.value;
    if (
      candidate === null ||
      typeof candidate === "string" ||
      typeof candidate === "boolean" ||
      (typeof candidate === "number" && Number.isFinite(candidate))
    ) {
      continue;
    }
    if (typeof candidate !== "object") {
      return [
        issue(
          "response_structure_not_json",
          "moderate",
          "The response structure contains a non-JSON value.",
        ),
      ];
    }
    if (seen.has(candidate)) {
      return [
        issue(
          "response_structure_not_json",
          "moderate",
          "The response structure contains a repeated object reference.",
        ),
      ];
    }
    seen.add(candidate);
    const children = Array.isArray(candidate)
      ? candidate
      : isPlainObject(candidate)
        ? Object.values(candidate)
        : null;
    if (children === null) {
      return [
        issue(
          "response_structure_not_json",
          "moderate",
          "The response structure contains a non-plain object.",
        ),
      ];
    }
    if (visited + stack.length + children.length > MAX_JSON_RESPONSE_NODES) {
      return [
        issue(
          "response_structure_too_large",
          "moderate",
          "The JSON response contains too many nested values for local diagnosis.",
        ),
      ];
    }
    for (let index = children.length - 1; index >= 0; index -= 1) {
      stack.push({ value: children[index], depth: frame.depth + 1 });
    }
  }

  return [];
};

const shapeOf = (value: unknown, ancestors = new WeakSet<object>()): JsonShape | null => {
  if (value === null) {
    return { kind: "null" };
  }
  if (typeof value === "string") {
    return { kind: "string" };
  }
  if (typeof value === "boolean") {
    return { kind: "boolean" };
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? { kind: "number" } : null;
  }
  if (typeof value !== "object" || ancestors.has(value)) {
    return null;
  }
  ancestors.add(value);
  if (Array.isArray(value)) {
    const items: JsonShape[] = [];
    for (const item of value) {
      const shape = shapeOf(item, ancestors);
      if (shape === null) {
        ancestors.delete(value);
        return null;
      }
      items.push(shape);
    }
    ancestors.delete(value);
    return { kind: "array", items };
  }
  if (!isPlainObject(value)) {
    ancestors.delete(value);
    return null;
  }
  const fields = new Map<string, JsonShape>();
  for (const [key, nested] of Object.entries(value)) {
    const shape = shapeOf(nested, ancestors);
    if (shape === null) {
      ancestors.delete(value);
      return null;
    }
    fields.set(key, shape);
  }
  ancestors.delete(value);
  return { kind: "object", fields };
};

const shapeKind = (shape: JsonShape): string => shape.kind;

const responseIssue = (
  code: string,
  message: string,
  path: string,
): DiagnosticIssue =>
  issue(code, "moderate", `${path} ${message}`);

const validateShape = (
  expected: JsonShape,
  actual: unknown,
  path: string,
): DiagnosticIssue[] => {
  const actualShape = shapeOf(actual);
  if (actualShape === null || actualShape.kind !== expected.kind) {
    return [
      responseIssue(
        "response_type_mismatch",
        `must have type ${shapeKind(expected)}.`,
        path,
      ),
    ];
  }

  if (expected.kind === "object" && actualShape.kind === "object") {
    if (!isPlainObject(actual)) {
      return [
        responseIssue(
          "response_type_mismatch",
          "must have type object.",
          path,
        ),
      ];
    }
    const actualObject = actual;
    const issues: DiagnosticIssue[] = [];
    for (const key of expected.fields.keys()) {
      if (!Object.prototype.hasOwnProperty.call(actualObject, key)) {
        issues.push(
          responseIssue(
            "missing_response_field",
            "is missing a required field.",
            `${path}.${key}`,
          ),
        );
      }
    }
    for (const key of Object.keys(actualObject)) {
      if (!expected.fields.has(key)) {
        issues.push(
          responseIssue(
            "unexpected_response_field",
            "is not declared by the selected exercise response structure.",
            `${path}.${key}`,
          ),
        );
      }
    }
    for (const [key, nestedShape] of expected.fields.entries()) {
      if (Object.prototype.hasOwnProperty.call(actualObject, key)) {
        issues.push(...validateShape(nestedShape, actualObject[key], `${path}.${key}`));
      }
    }
    return issues;
  }

  if (expected.kind === "array" && actualShape.kind === "array") {
    if (!Array.isArray(actual)) {
      return [
        responseIssue(
          "response_type_mismatch",
          "must have type array.",
          path,
        ),
      ];
    }
    const actualArray = actual;
    if (expected.items.length > 0 && actualArray.length !== expected.items.length) {
      return [
        responseIssue(
          "response_array_length_mismatch",
          `must contain ${expected.items.length} item(s).`,
          path,
        ),
      ];
    }
    const issues: DiagnosticIssue[] = [];
    for (const [index, value] of actualArray.entries()) {
      const expectedShape = expected.items[index] ?? expected.items[0];
      if (expectedShape !== undefined) {
        issues.push(...validateShape(expectedShape, value, `${path}[${index}]`));
      }
    }
    return issues;
  }
  return [];
};

const responseCandidates = (unit: unknown): unknown[] => {
  if (!isPlainObject(unit) || !isPlainObject(unit.exercise)) {
    return [];
  }
  const exercise = unit.exercise;
  const candidates: unknown[] = [];
  if (Object.prototype.hasOwnProperty.call(exercise, "answer")) {
    candidates.push(exercise.answer);
  }
  if (!isPlainObject(exercise.evaluation)) {
    return candidates;
  }
  const evaluation = exercise.evaluation;
  if (Array.isArray(evaluation.allowed_answers)) {
    for (const candidate of evaluation.allowed_answers) {
      if (isPlainObject(candidate) && Object.prototype.hasOwnProperty.call(candidate, "answer")) {
        candidates.push(candidate.answer);
      }
    }
  }
  if (Array.isArray(evaluation.diagnostic_rules)) {
    for (const candidate of evaluation.diagnostic_rules) {
      if (isPlainObject(candidate) && Object.prototype.hasOwnProperty.call(candidate, "submission")) {
        candidates.push(candidate.submission);
      }
    }
  }
  return candidates;
};

/** Validate keys and JSON value shapes without comparing or exposing answer values. */
export const validateJsonResponseShape = (
  unit: unknown,
  submission: unknown,
): readonly DiagnosticIssue[] => {
  const complexityIssues = validateJsonResponseComplexity(submission);
  if (complexityIssues.length > 0) {
    return complexityIssues;
  }
  const shapes = responseCandidates(unit)
    .map((candidate) => shapeOf(candidate))
    .filter((shape): shape is JsonShape => shape !== null);
  if (shapes.length === 0) {
    return [
      issue(
        "response_structure_unavailable",
        "moderate",
        "The selected exercise does not declare a usable JSON response structure.",
      ),
    ];
  }
  const attempts = shapes.map((shape) => validateShape(shape, submission, "$response"));
  const best = attempts.reduce((current, candidate) =>
    candidate.length < current.length ? candidate : current,
  );
  return best;
};
