import type { DiagnosticIssue, DiagnosticSeverity } from "./types";

export interface TextGridInspection {
  readonly supported: boolean;
  readonly issues: readonly DiagnosticIssue[];
}

interface IndexedHeader {
  readonly lineIndex: number;
  readonly declaredIndex: number;
}

interface DeclaredCount {
  readonly found: boolean;
  readonly value: number | null;
}

interface IntervalFields {
  readonly start: number | null;
  readonly end: number | null;
  readonly hasLabel: boolean;
}

const TIER_HEADER = /^\s*item\s*\[(\d+)\]\s*:\s*$/u;
const INTERVAL_HEADER = /^\s*intervals\s*\[(\d+)\]\s*:\s*$/u;
const LONG_FILE_HEADER = /^\s*File type\s*=\s*"ooTextFile"\s*$/u;
const TEXTGRID_CLASS_HEADER = /^\s*Object class\s*=\s*"TextGrid"\s*$/u;
const GLOBAL_SIZE = /^\s*size\s*=\s*([^\s]+)\s*$/u;
const INTERVAL_SIZE = /^\s*intervals\s*:\s*size\s*=\s*([^\s]+)\s*$/u;

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

const numberFieldInRange = (
  lines: readonly string[],
  start: number,
  end: number,
  field: string,
): number | null => {
  const pattern = new RegExp(`^\\s*${field}\\s*=\\s*([^\\s]+)`, "u");
  for (let index = start; index < end; index += 1) {
    const match = pattern.exec(lines[index] ?? "");
    if (match?.[1] !== undefined) {
      const value = Number(match[1]);
      return Number.isFinite(value) ? value : null;
    }
  }
  return null;
};

const quotedFieldInRange = (
  lines: readonly string[],
  start: number,
  end: number,
  field: string,
): string | null => {
  const pattern = new RegExp(`^\\s*${field}\\s*=\\s*"([\\s\\S]*)"\\s*$`, "u");
  for (let index = start; index < end; index += 1) {
    const match = pattern.exec(lines[index] ?? "");
    if (match?.[1] !== undefined) {
      return match[1];
    }
  }
  return null;
};

const declaredCountInRange = (
  lines: readonly string[],
  start: number,
  end: number,
  pattern: RegExp,
): DeclaredCount => {
  for (let index = start; index < end; index += 1) {
    const match = pattern.exec(lines[index] ?? "");
    if (match?.[1] === undefined) {
      continue;
    }
    const value = Number(match[1]);
    return {
      found: true,
      value: Number.isSafeInteger(value) && value >= 0 ? value : null,
    };
  }
  return { found: false, value: null };
};

const collectHeaders = (
  lines: readonly string[],
  start: number,
  end: number,
  pattern: RegExp,
): IndexedHeader[] => {
  const headers: IndexedHeader[] = [];
  for (let lineIndex = start; lineIndex < end; lineIndex += 1) {
    const match = pattern.exec(lines[lineIndex] ?? "");
    if (match?.[1] !== undefined) {
      headers.push({ lineIndex, declaredIndex: Number(match[1]) });
    }
  }
  return headers;
};

const validateHeaderIndices = (
  headers: readonly IndexedHeader[],
  entity: "tier" | "interval",
  tierPosition: number | null,
  issues: DiagnosticIssue[],
): void => {
  const seen = new Set<number>();
  for (const [position, header] of headers.entries()) {
    const context = tierPosition === null ? "TextGrid" : `TextGrid tier ${tierPosition}`;
    if (!Number.isSafeInteger(header.declaredIndex) || header.declaredIndex <= 0) {
      issues.push(
        issue(
          `invalid_${entity}_index`,
          "severe",
          `${context} has an invalid ${entity} index.`,
        ),
      );
      continue;
    }
    if (seen.has(header.declaredIndex)) {
      issues.push(
        issue(
          `duplicate_${entity}_index`,
          "severe",
          `${context} repeats ${entity} index ${header.declaredIndex}.`,
        ),
      );
    }
    seen.add(header.declaredIndex);
    if (header.declaredIndex !== position + 1) {
      issues.push(
        issue(
          `non_sequential_${entity}_index`,
          "moderate",
          `${context} ${entity} indices must be sequential from 1.`,
        ),
      );
    }
  }
};

const validateDeclaredCount = (
  declared: DeclaredCount,
  observed: number,
  entity: "tier" | "interval",
  tierPosition: number | null,
  issues: DiagnosticIssue[],
): void => {
  const context = tierPosition === null ? "TextGrid" : `TextGrid tier ${tierPosition}`;
  if (!declared.found) {
    issues.push(
      issue(
        `missing_${entity}_count`,
        "moderate",
        `${context} must declare its ${entity} count.`,
      ),
    );
    return;
  }
  if (declared.value === null) {
    issues.push(
      issue(
        `invalid_${entity}_count`,
        "severe",
        `${context} ${entity} count must be a non-negative integer.`,
      ),
    );
    return;
  }
  if (declared.value !== observed) {
    issues.push(
      issue(
        `${entity}_count_mismatch`,
        "severe",
        `${context} declares ${declared.value} ${entity}(s) but contains ${observed}.`,
      ),
    );
  }
};

const parseIntervalFields = (
  lines: readonly string[],
  start: number,
  end: number,
): IntervalFields => {
  let intervalStart: number | null = null;
  let intervalEnd: number | null = null;
  let hasLabel = false;
  for (let index = start; index < end; index += 1) {
    const line = lines[index] ?? "";
    if (intervalStart === null) {
      const match = /^\s*xmin\s*=\s*([^\s]+)/u.exec(line);
      if (match?.[1] !== undefined) {
        const value = Number(match[1]);
        intervalStart = Number.isFinite(value) ? value : null;
        continue;
      }
    }
    if (intervalEnd === null) {
      const match = /^\s*xmax\s*=\s*([^\s]+)/u.exec(line);
      if (match?.[1] !== undefined) {
        const value = Number(match[1]);
        intervalEnd = Number.isFinite(value) ? value : null;
        continue;
      }
    }
    if (/^\s*text\s*=\s*"[\s\S]*"\s*$/u.test(line)) {
      hasLabel = true;
    }
  }
  return { start: intervalStart, end: intervalEnd, hasLabel };
};

const validateIntervals = (
  lines: readonly string[],
  headers: readonly IndexedHeader[],
  tierEndLine: number,
  tierPosition: number,
  tierStart: number | null,
  tierEnd: number | null,
  globalStart: number | null,
  globalEnd: number | null,
  issues: DiagnosticIssue[],
): void => {
  let previous: { readonly start: number; readonly end: number; readonly index: number } | null = null;

  for (const [position, header] of headers.entries()) {
    const blockEnd = headers[position + 1]?.lineIndex ?? tierEndLine;
    const parsed = parseIntervalFields(lines, header.lineIndex + 1, blockEnd);
    if (parsed.start === null || parsed.end === null) {
      issues.push(
        issue(
          "invalid_interval_bounds",
          "severe",
          `TextGrid tier ${tierPosition} interval ${header.declaredIndex} needs finite xmin/xmax.`,
        ),
      );
    } else {
      if (parsed.start > parsed.end) {
        issues.push(
          issue(
            "interval_bounds_reversed",
            "severe",
            `TextGrid tier ${tierPosition} interval ${header.declaredIndex} has xmin greater than xmax.`,
          ),
        );
      }
      if (
        (tierStart !== null && parsed.start < tierStart) ||
        (tierEnd !== null && parsed.end > tierEnd) ||
        (globalStart !== null && parsed.start < globalStart) ||
        (globalEnd !== null && parsed.end > globalEnd)
      ) {
        issues.push(
          issue(
            "interval_out_of_bounds",
            "severe",
            `TextGrid tier ${tierPosition} interval ${header.declaredIndex} lies outside declared bounds.`,
          ),
        );
      }
      if (previous !== null) {
        if (parsed.start < previous.start) {
          issues.push(
            issue(
              "interval_out_of_order",
              "moderate",
              `TextGrid tier ${tierPosition} intervals are not ordered by xmin.`,
            ),
          );
        }
        // Equality is intentionally allowed: adjacent intervals are not overlap.
        if (parsed.start < previous.end) {
          issues.push(
            issue(
              "interval_overlap",
              "severe",
              `TextGrid tier ${tierPosition} intervals ${previous.index} and ${header.declaredIndex} overlap.`,
            ),
          );
        }
      }
      previous = {
        start: parsed.start,
        end: parsed.end,
        index: header.declaredIndex,
      };
    }
    if (!parsed.hasLabel) {
      issues.push(
        issue(
          "missing_interval_label",
          "moderate",
          `TextGrid tier ${tierPosition} interval ${header.declaredIndex} has no text label.`,
        ),
      );
    }
  }
};

/** Validate Praat's long text TextGrid format in time linear to its line count. */
export const inspectTextGrid = (text: string): TextGridInspection => {
  if (text.includes("\u0000")) {
    return {
      supported: false,
      issues: [
        issue(
          "unsupported_textgrid_format",
          "moderate",
          "Binary or short TextGrid formats are not supported; export long text format.",
        ),
      ],
    };
  }

  const lines = text.replace(/^\uFEFF/u, "").split(/\r?\n/u);
  let hasLongHeader = false;
  let hasTextGridClass = false;
  const tierHeaders: IndexedHeader[] = [];
  for (const [lineIndex, line] of lines.entries()) {
    hasLongHeader ||= LONG_FILE_HEADER.test(line);
    hasTextGridClass ||= TEXTGRID_CLASS_HEADER.test(line);
    const match = TIER_HEADER.exec(line);
    if (match?.[1] !== undefined) {
      tierHeaders.push({ lineIndex, declaredIndex: Number(match[1]) });
    }
  }

  if (!hasLongHeader || !hasTextGridClass || tierHeaders.length === 0) {
    return {
      supported: false,
      issues: [
        issue(
          "unsupported_textgrid_format",
          "moderate",
          "Only Praat TextGrid long text interval tiers are supported.",
        ),
      ],
    };
  }

  const issues: DiagnosticIssue[] = [];
  const globalEndLine = tierHeaders[0].lineIndex;
  const globalStart = numberFieldInRange(lines, 0, globalEndLine, "xmin");
  const globalEnd = numberFieldInRange(lines, 0, globalEndLine, "xmax");
  if (globalStart === null || globalEnd === null) {
    issues.push(
      issue(
        "invalid_textgrid_bounds",
        "severe",
        "TextGrid must declare finite global xmin and xmax.",
      ),
    );
  } else if (globalStart > globalEnd) {
    issues.push(
      issue(
        "textgrid_bounds_reversed",
        "severe",
        "TextGrid global xmin must not exceed xmax.",
      ),
    );
  }

  validateDeclaredCount(
    declaredCountInRange(lines, 0, globalEndLine, GLOBAL_SIZE),
    tierHeaders.length,
    "tier",
    null,
    issues,
  );
  validateHeaderIndices(tierHeaders, "tier", null, issues);

  for (const [position, tierHeader] of tierHeaders.entries()) {
    const tierPosition = position + 1;
    const tierEndLine = tierHeaders[position + 1]?.lineIndex ?? lines.length;
    const intervalHeaders = collectHeaders(
      lines,
      tierHeader.lineIndex + 1,
      tierEndLine,
      INTERVAL_HEADER,
    );
    const metadataEnd = intervalHeaders[0]?.lineIndex ?? tierEndLine;
    const className = quotedFieldInRange(
      lines,
      tierHeader.lineIndex + 1,
      metadataEnd,
      "class",
    );
    if (className !== "IntervalTier") {
      issues.push(
        issue(
          "unsupported_textgrid_tier",
          "moderate",
          `TextGrid tier ${tierPosition} is not an IntervalTier.`,
        ),
      );
      continue;
    }

    const tierStart = numberFieldInRange(
      lines,
      tierHeader.lineIndex + 1,
      metadataEnd,
      "xmin",
    );
    const tierEnd = numberFieldInRange(
      lines,
      tierHeader.lineIndex + 1,
      metadataEnd,
      "xmax",
    );
    if (tierStart === null || tierEnd === null) {
      issues.push(
        issue(
          "invalid_tier_bounds",
          "severe",
          `TextGrid tier ${tierPosition} must declare finite xmin/xmax.`,
        ),
      );
    } else {
      if (tierStart > tierEnd) {
        issues.push(
          issue(
            "tier_bounds_reversed",
            "severe",
            `TextGrid tier ${tierPosition} xmin must not exceed xmax.`,
          ),
        );
      }
      if (
        globalStart !== null &&
        globalEnd !== null &&
        (tierStart < globalStart || tierEnd > globalEnd)
      ) {
        issues.push(
          issue(
            "tier_out_of_bounds",
            "severe",
            `TextGrid tier ${tierPosition} lies outside global bounds.`,
          ),
        );
      }
    }

    validateDeclaredCount(
      declaredCountInRange(
        lines,
        tierHeader.lineIndex + 1,
        metadataEnd,
        INTERVAL_SIZE,
      ),
      intervalHeaders.length,
      "interval",
      tierPosition,
      issues,
    );
    validateHeaderIndices(intervalHeaders, "interval", tierPosition, issues);
    validateIntervals(
      lines,
      intervalHeaders,
      tierEndLine,
      tierPosition,
      tierStart,
      tierEnd,
      globalStart,
      globalEnd,
      issues,
    );
  }

  return { supported: true, issues };
};

export const validateTextGrid = (text: string): readonly DiagnosticIssue[] =>
  inspectTextGrid(text).issues;

export const parseTextGrid = inspectTextGrid;
