import type { DiagnosticIssue, DiagnosticSeverity } from "./types";

export interface TextGridInspection {
  readonly supported: boolean;
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

const numberField = (lines: readonly string[], field: string): number | null => {
  const pattern = new RegExp(`^\\s*${field}\\s*=\\s*([^\\s]+)`, "u");
  for (const line of lines) {
    const match = pattern.exec(line);
    if (match?.[1] !== undefined) {
      const value = Number(match[1]);
      return Number.isFinite(value) ? value : null;
    }
  }
  return null;
};

const quotedField = (lines: readonly string[], field: string): string | null => {
  const pattern = new RegExp(`^\\s*${field}\\s*=\\s*"([\\s\\S]*)"\\s*$`, "u");
  for (const line of lines) {
    const match = pattern.exec(line);
    if (match?.[1] !== undefined) {
      return match[1];
    }
  }
  return null;
};

const parseIntervalBlock = (
  lines: readonly string[],
  start: number,
  end: number,
  tierIndex: number,
  issues: DiagnosticIssue[],
): void => {
  const intervals: { start: number; end: number; index: number }[] = [];
  for (let index = start; index < end; index += 1) {
    const header = /^\s*intervals\s*\[(\d+)\]\s*:\s*$/u.exec(lines[index] ?? "");
    if (header === null) {
      continue;
    }
    const nextHeader = lines.findIndex((line, candidateIndex) =>
      candidateIndex > index &&
      candidateIndex < end &&
      /^\s*intervals\s*\[\d+\]\s*:\s*$/u.test(line),
    );
    const blockEnd = nextHeader === -1 ? end : nextHeader;
    const block = lines.slice(index + 1, blockEnd);
    const startValue = numberField(block, "xmin");
    const endValue = numberField(block, "xmax");
    if (startValue === null || endValue === null) {
      issues.push(
        issue(
          "invalid_interval_bounds",
          "severe",
          `TextGrid tier ${tierIndex} has an interval without finite xmin/xmax.`,
        ),
      );
    } else {
      intervals.push({ start: startValue, end: endValue, index: Number(header[1]) });
      if (startValue > endValue) {
        issues.push(
          issue(
            "interval_bounds_reversed",
            "severe",
            `TextGrid tier ${tierIndex} interval ${header[1]} has xmin greater than xmax.`,
          ),
        );
      }
    }
    if (quotedField(block, "text") === null) {
      issues.push(
        issue(
          "missing_interval_label",
          "moderate",
          `TextGrid tier ${tierIndex} interval ${header[1]} has no text label.`,
        ),
      );
    }
    index = blockEnd - 1;
  }

  for (let index = 1; index < intervals.length; index += 1) {
    const previous = intervals[index - 1];
    const current = intervals[index];
    if (current.start < previous.start) {
      issues.push(
        issue(
          "interval_out_of_order",
          "moderate",
          `TextGrid tier ${tierIndex} intervals are not ordered by xmin.`,
        ),
      );
    }
    // Equality is intentionally allowed: adjacent intervals are not overlap.
    if (current.start < previous.end) {
      issues.push(
        issue(
          "interval_overlap",
          "severe",
          `TextGrid tier ${tierIndex} intervals ${previous.index} and ${current.index} overlap.`,
        ),
      );
    }
  }
};

/** Validate Praat's long text TextGrid format without evaluating label meaning. */
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
  const hasLongHeader =
    lines.some((line) => /^\s*File type\s*=\s*"ooTextFile"/u.test(line)) &&
    lines.some((line) => /^\s*Object class\s*=\s*"TextGrid"/u.test(line));
  const tierStarts = lines
    .map((line, index) => ({ line, index }))
    .filter(({ line }) => /^\s*item\s*\[\d+\]\s*:\s*$/u.test(line));
  const hasIntervals = lines.some((line) => /^\s*intervals\s*\[\d+\]\s*:\s*$/u.test(line));

  if (!hasLongHeader || tierStarts.length === 0 || !hasIntervals) {
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
  const globalStart = numberField(lines.slice(0, tierStarts[0].index), "xmin");
  const globalEnd = numberField(lines.slice(0, tierStarts[0].index), "xmax");
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

  for (let tierIndex = 0; tierIndex < tierStarts.length; tierIndex += 1) {
    const tierStart = tierStarts[tierIndex].index;
    const tierEnd = tierStarts[tierIndex + 1]?.index ?? lines.length;
    const tierLines = lines.slice(tierStart, tierEnd);
    const className = quotedField(tierLines, "class");
    if (className !== "IntervalTier") {
      issues.push(
        issue(
          "unsupported_textgrid_tier",
          "moderate",
          `TextGrid tier ${tierIndex + 1} is not an IntervalTier.`,
        ),
      );
      continue;
    }
    const tierStartValue = numberField(tierLines, "xmin");
    const tierEndValue = numberField(tierLines, "xmax");
    if (tierStartValue === null || tierEndValue === null) {
      issues.push(
        issue(
          "invalid_tier_bounds",
          "severe",
          `TextGrid tier ${tierIndex + 1} must declare finite xmin/xmax.`,
        ),
      );
    } else {
      if (tierStartValue > tierEndValue) {
        issues.push(
          issue(
            "tier_bounds_reversed",
            "severe",
            `TextGrid tier ${tierIndex + 1} xmin must not exceed xmax.`,
          ),
        );
      }
      if (
        globalStart !== null &&
        globalEnd !== null &&
        (tierStartValue < globalStart || tierEndValue > globalEnd)
      ) {
        issues.push(
          issue(
            "tier_out_of_bounds",
            "severe",
            `TextGrid tier ${tierIndex + 1} lies outside global bounds.`,
          ),
        );
      }
    }
    const intervalStart = tierLines.findIndex((line) =>
      /^\s*intervals\s*\[\d+\]\s*:\s*$/u.test(line),
    );
    if (intervalStart === -1) {
      issues.push(
        issue(
          "missing_intervals",
          "moderate",
          `TextGrid tier ${tierIndex + 1} has no intervals.`,
        ),
      );
      continue;
    }
    parseIntervalBlock(
      tierLines,
      intervalStart,
      tierLines.length,
      tierIndex + 1,
      issues,
    );

    // Check each interval against both tier and global bounds.
    const intervalHeaders = tierLines
      .map((line, index) => ({ line, index }))
      .filter(({ line }) => /^\s*intervals\s*\[\d+\]\s*:\s*$/u.test(line));
    for (const [intervalIndex, header] of intervalHeaders.entries()) {
      const end = intervalHeaders[intervalIndex + 1]?.index ?? tierLines.length;
      const bounds = tierLines.slice(header.index + 1, end);
      const startValue = numberField(bounds, "xmin");
      const endValue = numberField(bounds, "xmax");
      if (startValue === null || endValue === null) {
        continue;
      }
      if (
        (tierStartValue !== null && startValue < tierStartValue) ||
        (tierEndValue !== null && endValue > tierEndValue) ||
        (globalStart !== null && startValue < globalStart) ||
        (globalEnd !== null && endValue > globalEnd)
      ) {
        issues.push(
          issue(
            "interval_out_of_bounds",
            "severe",
            `TextGrid tier ${tierIndex + 1} interval lies outside declared bounds.`,
          ),
        );
      }
    }
  }

  return { supported: true, issues };
};

export const validateTextGrid = (text: string): readonly DiagnosticIssue[] =>
  inspectTextGrid(text).issues;

export const parseTextGrid = inspectTextGrid;
