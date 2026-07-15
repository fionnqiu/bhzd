import type { DiagnosticIssue, DiagnosticSeverity } from "./types";

export interface VocInspection {
  readonly parsed: boolean;
  readonly rejectedCode?: "xml_doctype_forbidden" | "corrupted_xml";
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

const elementName = (element: Element): string =>
  (element.localName || element.nodeName).toLowerCase();

const directChildren = (element: Element, localName: string): Element[] =>
  Array.from(element.children).filter(
    (child) => elementName(child) === localName.toLowerCase(),
  );

const directChild = (element: Element, localName: string): Element | null =>
  directChildren(element, localName)[0] ?? null;

const childText = (element: Element, localName: string): string | null => {
  const child = directChild(element, localName);
  return child === null ? null : (child.textContent ?? "").trim();
};

const integerText = (value: string | null): number | null => {
  if (value === null || !/^[+-]?\d+$/u.test(value)) {
    return null;
  }
  const number = Number(value);
  return Number.isSafeInteger(number) ? number : null;
};

interface ImageSize {
  readonly width: number;
  readonly height: number;
}

const parseImageSize = (
  annotation: Element,
  issues: DiagnosticIssue[],
): ImageSize | null => {
  const size = directChild(annotation, "size");
  if (size === null) {
    return null;
  }
  const width = integerText(childText(size, "width"));
  const height = integerText(childText(size, "height"));
  if (width === null || height === null || width <= 0 || height <= 0) {
    issues.push(
      issue(
        "invalid_image_size",
        "severe",
        "VOC size width and height must be positive finite integers.",
      ),
    );
    return null;
  }
  return { width, height };
};

/** Parse and validate a Pascal VOC annotation with browser DOMParser only. */
export const inspectVocXml = (text: string): VocInspection => {
  if (/<!DOCTYPE\b/iu.test(text)) {
    return {
      parsed: false,
      rejectedCode: "xml_doctype_forbidden",
      issues: [
        issue(
          "xml_doctype_forbidden",
          "severe",
          "DOCTYPE declarations are not accepted in local VOC diagnostics.",
        ),
      ],
    };
  }

  let document: Document;
  try {
    document = new DOMParser().parseFromString(text, "application/xml");
  } catch {
    return {
      parsed: false,
      rejectedCode: "corrupted_xml",
      issues: [issue("corrupted_xml", "severe", "The XML document could not be parsed.")],
    };
  }

  const root = document.documentElement;
  if (root === null) {
    return {
      parsed: false,
      rejectedCode: "corrupted_xml",
      issues: [issue("corrupted_xml", "severe", "The XML document is empty.")],
    };
  }
  const parserError =
    elementName(root) === "parsererror" ||
    document.getElementsByTagName("parsererror").length > 0;
  if (parserError) {
    return {
      parsed: false,
      rejectedCode: "corrupted_xml",
      issues: [issue("corrupted_xml", "severe", "The XML document is malformed.")],
    };
  }

  const issues: DiagnosticIssue[] = [];
  if (elementName(root) !== "annotation") {
    issues.push(
      issue(
        "invalid_voc_root",
        "severe",
        "VOC XML root must be annotation.",
      ),
    );
    return { parsed: true, issues };
  }

  const imageSize = parseImageSize(root, issues);
  const objects = directChildren(root, "object");
  if (objects.length === 0) {
    issues.push(
      issue(
        "missing_voc_object",
        "severe",
        "VOC annotation must contain at least one object.",
      ),
    );
  }

  for (const [index, object] of objects.entries()) {
    const name = childText(object, "name");
    if (name === null || name.length === 0) {
      issues.push(
        issue(
          "missing_object_name",
          "moderate",
          `VOC object ${index + 1} must have a non-empty name.`,
        ),
      );
    }
    const box = directChild(object, "bndbox");
    if (box === null) {
      issues.push(
        issue(
          "missing_bndbox",
          "severe",
          `VOC object ${index + 1} must contain bndbox.`,
        ),
      );
      continue;
    }

    const xmin = integerText(childText(box, "xmin"));
    const ymin = integerText(childText(box, "ymin"));
    const xmax = integerText(childText(box, "xmax"));
    const ymax = integerText(childText(box, "ymax"));
    if (xmin === null || ymin === null || xmax === null || ymax === null) {
      issues.push(
        issue(
          "invalid_bndbox_coordinate",
          "severe",
          `VOC object ${index + 1} coordinates must be finite integers.`,
        ),
      );
      continue;
    }
    if (xmin >= xmax || ymin >= ymax) {
      issues.push(
        issue(
          "invalid_bndbox_order",
          "severe",
          `VOC object ${index + 1} must satisfy xmin < xmax and ymin < ymax.`,
        ),
      );
    }
    if (xmin < 0 || ymin < 0) {
      issues.push(
        issue(
          "negative_bndbox_coordinate",
          "severe",
          `VOC object ${index + 1} coordinates cannot be negative.`,
        ),
      );
    }
    if (
      imageSize !== null &&
      (xmin > imageSize.width || xmax > imageSize.width ||
        ymin > imageSize.height || ymax > imageSize.height)
    ) {
      issues.push(
        issue(
          "bndbox_out_of_bounds",
          "severe",
          `VOC object ${index + 1} bndbox exceeds image bounds.`,
        ),
      );
    }
  }

  return { parsed: true, issues };
};

export const validateVocXml = (text: string): readonly DiagnosticIssue[] =>
  inspectVocXml(text).issues;

export const parseVocXml = inspectVocXml;
