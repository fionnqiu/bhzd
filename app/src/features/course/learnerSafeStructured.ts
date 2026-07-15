const OMIT = Symbol("omit-learner-sensitive-value");

const SAFE_EXAMPLE_FIELDS = [
  "id",
  "asset_ref",
  "representation",
  "manifest_resolution",
  "input",
  "explanation",
  "explanation_evidence_refs",
  "source_ref",
  "source_refs",
  "asset_authorization",
] as const;

const SAFE_PRACTICE_VARIANT_FIELDS = [
  "exercise_id",
  "exercise_type",
  "asset_ref",
  "representation",
  "manifest_resolution",
  "input",
  "student_action",
  "response_space",
  "data_version",
  "capability_refs",
  "asset_authorization",
] as const;

const SAFE_AUTHORIZATION_FIELDS = [
  "type",
  "representation",
  "student_use_allowed",
  "contains_recorded_speech",
  "source_ref",
] as const;

const SAFE_RESPONSE_SPACE_FIELDS = new Set([
  "type",
  "options",
  "values",
  "allowed_values",
  "description",
  "instructions",
  "format",
  "minimum",
  "maximum",
  "min_items",
  "max_items",
  "required_fields",
  "item_shape",
  "shape",
  "schema",
]);

const SENSITIVE_TOKEN_PREFIXES = [
  "answer",
  "expected",
  "submitted",
  "submission",
  "diagnostic",
  "evaluation",
  "grade",
  "grading",
  "precedence",
  "score",
  "rubric",
  "solution",
  "feedback",
  "private",
  "secret",
] as const;

const SENSITIVE_COMPOUND_FIELDS = [
  "pass_score",
  "passscore",
  "pass_condition",
  "passcondition",
  "pass_threshold",
  "fault_model",
  "ground_truth",
  "correct_response",
  "corrected_annotation",
  "candidate_annotation",
  "candidate_response",
  "candidate_result",
  "candidate_output",
  "recognized_submission",
  "unmatched",
  "internal_review",
  "review_payload",
  "error_type",
  "error_code",
] as const;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const normalizeFieldName = (field: string): string =>
  field
    .replace(/([a-z0-9])([A-Z])/gu, "$1_$2")
    .replace(/[^a-zA-Z0-9]+/gu, "_")
    .replace(/^_+|_+$/gu, "")
    .toLowerCase();

const containsCompoundField = (
  normalized: string,
  sensitive: string,
): boolean =>
  [
    normalized,
    normalized.replace(/\d+$/u, ""),
    normalized
      .split("_")
      .map((token) => token.replace(/\d+$/u, ""))
      .join("_"),
  ].some(
    (candidate) =>
      candidate === sensitive ||
      candidate.startsWith(`${sensitive}_`) ||
      candidate.endsWith(`_${sensitive}`) ||
      candidate.includes(`_${sensitive}_`),
  );

const isLearnerSensitiveField = (field: string): boolean => {
  const normalized = normalizeFieldName(field);
  const tokens = normalized.split("_").filter(Boolean);

  if (
    tokens.some((token) =>
      SENSITIVE_TOKEN_PREFIXES.some((prefix) => token.startsWith(prefix)),
    )
  ) {
    return true;
  }

  return SENSITIVE_COMPOUND_FIELDS.some((sensitive) =>
    containsCompoundField(normalized, sensitive),
  );
};

type StringProjector = (value: string) => string;

const preserveString: StringProjector = (value) => value;

const redactInstructionText: StringProjector = (value) =>
  value
    .replace(
      /\b[A-Za-z][A-Za-z0-9_-]*\s*为满分(?:主意图|答案|标签|结果)/gu,
      "主意图需依据题目证据判定",
    )
    .replace(
      /，?固定得\s*\d+(?:\.\d+)?\s*分且进入人工复核/gu,
      "，并进入人工复核",
    )
    .replace(/，?固定得\s*\d+(?:\.\d+)?\s*分/gu, "")
    .replace(
      /校验顺序固定为[^。]*?首个失败项为错误码。?/gu,
      "",
    );

const sanitizeValue = (
  value: unknown,
  ancestors: WeakSet<object>,
  projectString: StringProjector,
): unknown | typeof OMIT => {
  if (typeof value === "string") {
    return projectString(value);
  }
  if (
    value === null ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return value;
  }

  if (typeof value !== "object" || ancestors.has(value)) {
    return OMIT;
  }

  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      return value.flatMap((item) => {
        const sanitized = sanitizeValue(item, ancestors, projectString);
        return sanitized === OMIT ? [] : [sanitized];
      });
    }

    if (!isRecord(value)) {
      return OMIT;
    }

    const safeEntries: Array<[string, unknown]> = [];
    for (const [field, nested] of Object.entries(value)) {
      if (isLearnerSensitiveField(field)) {
        continue;
      }

      const sanitized = sanitizeValue(nested, ancestors, projectString);
      if (sanitized !== OMIT) {
        safeEntries.push([field, sanitized]);
      }
    }
    return Object.fromEntries(safeEntries);
  } finally {
    ancestors.delete(value);
  }
};

const projectValue = (
  value: unknown,
  projectString: StringProjector = preserveString,
): unknown => {
  const projected = sanitizeValue(value, new WeakSet(), projectString);
  return projected === OMIT ? null : projected;
};

const projectAuthorization = (value: unknown): Record<string, unknown> | null => {
  if (!isRecord(value)) {
    return null;
  }

  const projection: Record<string, unknown> = {};
  for (const field of SAFE_AUTHORIZATION_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(value, field)) {
      continue;
    }

    const sanitized = projectValue(value[field]);
    if (sanitized !== null) {
      projection[field] = sanitized;
    }
  }
  return Object.keys(projection).length > 0 ? projection : null;
};

const projectExample = (value: unknown): Record<string, unknown> | null => {
  if (!isRecord(value)) {
    return null;
  }

  const projection: Record<string, unknown> = {};
  for (const field of SAFE_EXAMPLE_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(value, field)) {
      continue;
    }

    if (field === "asset_authorization") {
      const authorization = projectAuthorization(value[field]);
      if (authorization !== null) {
        projection[field] = authorization;
      }
      continue;
    }

    const sanitized =
      field === "explanation"
        ? createLearnerSafeInstructionProjection(value[field])
        : projectValue(value[field]);
    if (sanitized !== null) {
      projection[field] = sanitized;
    }
  }

  return Object.keys(projection).length > 0 ? projection : null;
};

const isSafeResponseSpaceField = (field: string): boolean => {
  const normalized = normalizeFieldName(field);
  if (isLearnerSensitiveField(normalized)) {
    return false;
  }
  return (
    SAFE_RESPONSE_SPACE_FIELDS.has(normalized) ||
    normalized.startsWith("allowed_") ||
    normalized.startsWith("configured_")
  );
};

export const createLearnerSafeStructuredProjection = (
  value: unknown,
): unknown => projectValue(value);

export const createLearnerSafeInstructionProjection = (
  value: unknown,
): unknown => projectValue(value, redactInstructionText);

export const createLearnerSafeExampleProjection = (
  value: unknown,
): unknown => {
  if (Array.isArray(value)) {
    return value.flatMap((example) => {
      const projection = projectExample(example);
      return projection === null ? [] : [projection];
    });
  }

  return projectExample(value);
};

export const createLearnerSafeResponseSpaceProjection = (
  value: unknown,
): unknown => {
  if (!isRecord(value)) {
    return null;
  }

  const projection: Record<string, unknown> = {};
  for (const [field, nested] of Object.entries(value)) {
    if (!isSafeResponseSpaceField(field)) {
      continue;
    }

    const sanitized = projectValue(nested);
    if (sanitized !== null) {
      projection[field] = sanitized;
    }
  }
  return Object.keys(projection).length > 0 ? projection : null;
};

const projectPracticeVariant = (
  value: unknown,
): Record<string, unknown> | null => {
  if (!isRecord(value)) {
    return null;
  }

  const projection: Record<string, unknown> = {};
  for (const field of SAFE_PRACTICE_VARIANT_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(value, field)) {
      continue;
    }

    let sanitized: unknown;
    if (field === "asset_authorization") {
      sanitized = projectAuthorization(value[field]);
    } else if (field === "response_space") {
      sanitized = createLearnerSafeResponseSpaceProjection(value[field]);
    } else if (field === "student_action") {
      sanitized = createLearnerSafeInstructionProjection(value[field]);
    } else {
      sanitized = projectValue(value[field]);
    }

    if (sanitized !== null) {
      projection[field] = sanitized;
    }
  }

  return Object.keys(projection).length > 0 ? projection : null;
};

export const createLearnerSafePracticeVariantProjection = (
  value: unknown,
): unknown => {
  if (Array.isArray(value)) {
    return value.flatMap((variant) => {
      const projection = projectPracticeVariant(variant);
      return projection === null ? [] : [projection];
    });
  }

  return projectPracticeVariant(value);
};
