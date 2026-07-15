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

  const cocoKeys = ["images", "annotations", "categories"];
  const isCoco = cocoKeys.some((key) => hasOwn(value, key));
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
