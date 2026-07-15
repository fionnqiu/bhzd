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

const SAFE_AUTHORIZATION_FIELDS = [
  "type",
  "representation",
  "student_use_allowed",
  "contains_recorded_speech",
  "source_ref",
] as const;

const SENSITIVE_FIELD_PATTERN =
  /(^|_)(answer|answers|expected|submitted|submission|evaluation|diagnostic|pass_score|score|scoring|precedence|rubric|fault_model|ground_truth|solution|correct_response|feedback|internal|private|hidden|secret|review_payload)(_|$)/u;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const normalizeFieldName = (field: string): string =>
  field
    .replace(/([a-z0-9])([A-Z])/gu, "$1_$2")
    .replace(/[\s-]+/gu, "_")
    .toLowerCase();

const isLearnerSensitiveField = (field: string): boolean =>
  SENSITIVE_FIELD_PATTERN.test(normalizeFieldName(field));

const sanitizeInputValue = (
  value: unknown,
  ancestors: WeakSet<object>,
): unknown | typeof OMIT => {
  if (
    value === null ||
    typeof value === "string" ||
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
        const sanitized = sanitizeInputValue(item, ancestors);
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

      const sanitized = sanitizeInputValue(nested, ancestors);
      if (sanitized !== OMIT) {
        safeEntries.push([field, sanitized]);
      }
    }
    return Object.fromEntries(safeEntries);
  } finally {
    ancestors.delete(value);
  }
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

    const sanitized = sanitizeInputValue(value[field], new WeakSet());
    if (sanitized !== OMIT) {
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

    const sanitized = sanitizeInputValue(value[field], new WeakSet());
    if (sanitized !== OMIT) {
      projection[field] = sanitized;
    }
  }

  return Object.keys(projection).length > 0 ? projection : null;
};

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
