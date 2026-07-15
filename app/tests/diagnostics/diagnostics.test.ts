import { afterEach, describe, expect, it, vi } from "vitest";
import {
  diagnoseFile,
  MAX_DIAGNOSTIC_FILE_BYTES,
} from "../../src/diagnostics/diagnose";
import { detectFormat } from "../../src/diagnostics/detectFormat";
import { inspectJsonText } from "../../src/diagnostics/json";
import { inspectTextGrid } from "../../src/diagnostics/textGrid";
import { inspectVocXml } from "../../src/diagnostics/vocXml";
import { teachingUnits } from "../../src/data/rawData";

const context = { dataType: "image", targetUnitId: null } as const;

const fileFromText = (
  text: string,
  name: string,
  type = "",
): {
  readonly name: string;
  readonly type: string;
  readonly size: number;
  text(): Promise<string>;
} => ({
  name,
  type,
  size: new TextEncoder().encode(text).byteLength,
  text: async () => text,
});

const passEvaluator = () => ({
  score: 1,
  passed: true,
  matched: "answer" as const,
  errorType: null,
  feedback: "ok",
  remediation: [],
  ruleRefs: [],
  capabilityRefs: [],
  dataVersion: "1.0.0",
  evaluationVersion: "1.0.0",
  manualReviewRequired: false,
});

const intervalTier = (
  tierIndex: number,
  intervalIndices: readonly number[],
  declaredIntervalCount = intervalIndices.length,
): string => {
  const intervals = intervalIndices.map((intervalIndex, position) => `
        intervals [${intervalIndex}]:
            xmin = ${position}
            xmax = ${position + 1}
            text = "segment-${position + 1}"`).join("");
  return `    item [${tierIndex}]:
        class = "IntervalTier"
        name = "tier-${tierIndex}"
        xmin = 0
        xmax = ${Math.max(1, intervalIndices.length)}
        intervals: size = ${declaredIntervalCount}${intervals}`;
};

const textGridDocument = (
  tiers: readonly string[],
  declaredTierCount = tiers.length,
  xmax = 10,
): string => `File type = "ooTextFile"
Object class = "TextGrid"
xmin = 0
xmax = ${xmax}
tiers? <exists>
size = ${declaredTierCount}
item []:
${tiers.join("\n")}`;

const largeTextGrid = (intervalCount: number): string =>
  textGridDocument(
    [intervalTier(1, Array.from({ length: intervalCount }, (_, index) => index + 1))],
    1,
    intervalCount,
  );

const textGridStructureCases = [
  {
    name: "declared tier count",
    text: textGridDocument([intervalTier(1, [1])], 2),
    code: "tier_count_mismatch",
  },
  {
    name: "declared interval count",
    text: textGridDocument([intervalTier(1, [1], 2)]),
    code: "interval_count_mismatch",
  },
  {
    name: "duplicate tier index",
    text: textGridDocument([intervalTier(1, [1]), intervalTier(1, [1])]),
    code: "duplicate_tier_index",
  },
  {
    name: "skipped tier index",
    text: textGridDocument([intervalTier(1, [1]), intervalTier(3, [1])]),
    code: "non_sequential_tier_index",
  },
  {
    name: "duplicate interval index",
    text: textGridDocument([intervalTier(1, [1, 1])]),
    code: "duplicate_interval_index",
  },
  {
    name: "skipped interval index",
    text: textGridDocument([intervalTier(1, [1, 3])]),
    code: "non_sequential_interval_index",
  },
] as const;

const invalidEvaluationCases: readonly {
  readonly name: string;
  readonly fields: Readonly<Record<string, unknown>>;
}[] = [
  { name: "out-of-range score", fields: { score: 2 } },
  { name: "non-boolean passed", fields: { passed: "yes" } },
  { name: "unknown match", fields: { matched: "bogus" } },
  { name: "non-string error type", fields: { errorType: 7 } },
  { name: "non-string feedback", fields: { feedback: null } },
  { name: "invalid remediation list", fields: { remediation: [1] } },
  { name: "invalid rule refs", fields: { ruleRefs: "RULE" } },
  { name: "invalid capability refs", fields: { capabilityRefs: [null] } },
  { name: "invalid data version", fields: { dataVersion: 1 } },
  { name: "invalid evaluation version", fields: { evaluationVersion: null } },
  {
    name: "non-boolean manual review flag",
    fields: { manualReviewRequired: "false" },
  },
  {
    name: "passed unclassified result",
    fields: { matched: "unclassified", passed: true },
  },
  {
    name: "passed diagnostic rule",
    fields: { matched: "diagnostic_rule", passed: true },
  },
];

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("local diagnostics", () => {
  it("rejects files larger than five MiB before reading", async () => {
    const file = new File(
      [new Uint8Array(5 * 1024 * 1024 + 1)],
      "large.json",
      { type: "application/json" },
    );
    expect(await diagnoseFile(file, context)).toMatchObject({
      status: "rejected",
      code: "file_too_large",
    });
  });

  it("keeps screenshots out of scoring", async () => {
    const file = new File(
      [new Uint8Array([137, 80, 78, 71])],
      "explanation.png",
      { type: "image/png" },
    );
    expect(await diagnoseFile(file, context)).toMatchObject({
      status: "explanation_only",
      masteryImpact: false,
      score: null,
      format: "image",
    });
  });

  it("finds invalid COCO category references", async () => {
    const body = JSON.stringify({
      images: [{ id: 1, width: 100, height: 100 }],
      categories: [{ id: 1, name: "person" }],
      annotations: [
        { id: 1, image_id: 1, category_id: 99, bbox: [0, 0, 10, 10] },
      ],
    });
    const file = fileFromText(body, "sample.json", "application/json");
    const result = await diagnoseFile(file, context);
    expect(result.format).toBe("coco");
    expect(result.issues).toContainEqual(
      expect.objectContaining({
        code: "missing_category_reference",
        severity: "severe",
      }),
    );
  });

  it("allows an actual JSON body of exactly five MiB and reads it once", async () => {
    const prefix = '{"payload":"';
    const suffix = '"}';
    const body = `${prefix}${"x".repeat(
      MAX_DIAGNOSTIC_FILE_BYTES - prefix.length - suffix.length,
    )}${suffix}`;
    let reads = 0;
    const base = fileFromText(body, "exact.json", "application/json");
    const file = {
      ...base,
      text: async () => {
        reads += 1;
        return body;
      },
    };
    expect(file.size).toBe(MAX_DIAGNOSTIC_FILE_BYTES);
    const result = await diagnoseFile(file, { dataType: "text", targetUnitId: null });
    expect(result.status).toBe("manual_review");
    expect(reads).toBe(1);
  });

  it("rejects a MIME and extension conflict without reading", async () => {
    let reads = 0;
    const file = {
      name: "annotation.json",
      type: "image/png",
      size: 1,
      text: async () => {
        reads += 1;
        return "{}";
      },
    };
    const result = await diagnoseFile(file, context);
    expect(result).toMatchObject({ status: "rejected", code: "mime_extension_conflict" });
    expect(reads).toBe(0);
  });

  it("rejects malformed JSON and unknown formats", async () => {
    const malformed = await diagnoseFile(
      fileFromText("{not-json", "broken.json", "application/json"),
      context,
    );
    expect(malformed).toMatchObject({ status: "rejected", code: "corrupted_json" });
    const unknown = await diagnoseFile(fileFromText("hello", "notes.csv", "text/csv"), context);
    expect(unknown).toMatchObject({ status: "rejected", code: "unsupported_extension" });
  });

  it("validates COCO duplicate IDs, missing references, bbox dimensions, and bounds", () => {
    const inspection = inspectJsonText(
      JSON.stringify({
        images: [
          { id: 1, width: 100, height: 100 },
          { id: 1, width: 100, height: 100 },
        ],
        categories: [{ id: 1, name: "person" }],
        annotations: [
          { id: 1, image_id: 1, category_id: 1, bbox: [90, 90, 20, 20] },
          { id: 1, image_id: 2, category_id: 99, bbox: [0, 0, 0, 2] },
        ],
      }),
    );
    const codes = inspection.issues.map((candidate) => candidate.code);
    expect(inspection.isCoco).toBe(true);
    expect(codes).toEqual(expect.arrayContaining([
      "duplicate_image_id",
      "duplicate_annotation_id",
      "missing_image_reference",
      "missing_category_reference",
      "bbox_out_of_bounds",
      "non_positive_bbox",
    ]));
  });

  it("keeps generic JSON semantic scoring behind a selected published unit", async () => {
    const unit = teachingUnits.units.find((candidate) => candidate.id === "TU-TEXT-LABEL-VOCAB-001");
    if (unit === undefined) throw new Error("canonical unit missing");
    const answer = JSON.stringify(unit.exercise.answer);
    const target = { dataType: "text", targetUnitId: unit.id } as const;
    const complete = await diagnoseFile(fileFromText(answer, "response.json", "application/json"), target);
    expect(complete).toMatchObject({ status: "complete", score: 1, masteryImpact: true, format: "json" });
    const unmatched = await diagnoseFile(fileFromText(JSON.stringify({ labels: ["unknown"] }), "response.json", "application/json"), target);
    expect(unmatched.status).toBe("manual_review");
    expect(unmatched.masteryImpact).toBe(false);
    const noTarget = await diagnoseFile(fileFromText(answer, "response.json", "application/json"), { dataType: "text", targetUnitId: null });
    expect(noTarget.status).toBe("manual_review");
    expect(noTarget.masteryImpact).toBe(false);
  });

  it("does not turn structural findings into mastery without deterministic ground truth", async () => {
    const coco = JSON.stringify({
      images: [{ id: 1, width: 100, height: 100 }],
      categories: [{ id: 1, name: "person" }],
      annotations: [{ id: 1, image_id: 1, category_id: 99, bbox: [0, 0, 10, 10] }],
    });
    const result = await diagnoseFile(
      fileFromText(coco, "broken.json", "application/json"),
      { dataType: "image", targetUnitId: "TU-IMAGE-RECT-BOUNDS-001" },
      {
        evaluator: () => ({
          score: 0,
          passed: false,
          matched: "unclassified",
          errorType: null,
          feedback: "manual",
          remediation: [],
          ruleRefs: [],
          capabilityRefs: [],
          dataVersion: "1.0.0",
          evaluationVersion: "1.0.0",
          manualReviewRequired: true,
        }),
      },
    );
    expect(result.status).toBe("manual_review");
    expect(result.masteryImpact).toBe(false);
    expect(result.score).toBeNull();
  });

  it("never applies mastery when a permissive evaluator meets broken COCO, VOC, or TextGrid data", async () => {
    const permissive = { evaluator: passEvaluator };
    const coco = await diagnoseFile(
      fileFromText(
        JSON.stringify({
          images: [{ id: 1, width: 100, height: 100 }],
          categories: [{ id: 1, name: "person" }],
          annotations: [{ id: 1, image_id: 1, category_id: 99, bbox: [0, 0, 10, 10] }],
        }),
        "broken.json",
        "application/json",
      ),
      { dataType: "image", targetUnitId: "TU-IMAGE-RECT-BOUNDS-001" },
      permissive,
    );
    const voc = await diagnoseFile(
      fileFromText(
        `<annotation><object><name>person</name><bndbox><xmin>10</xmin><ymin>10</ymin><xmax>2</xmax><ymax>2</ymax></bndbox></object></annotation>`,
        "broken.xml",
        "application/xml",
      ),
      { dataType: "image", targetUnitId: "TU-IMAGE-RECT-BOUNDS-001" },
      permissive,
    );
    const textGrid = await diagnoseFile(
      fileFromText(
        `File type = "ooTextFile"\nObject class = "TextGrid"\nxmin = 0\nxmax = 2\ntiers? <exists>\nsize = 1\nitem []:\n    item [1]:\n        class = "IntervalTier"\n        name = "speech"\n        xmin = 0\n        xmax = 2\n        intervals: size = 2\n        intervals [1]:\n            xmin = 0\n            xmax = 1.5\n            text = "a"\n        intervals [2]:\n            xmin = 1\n            xmax = 2\n            text = "b"`,
        "broken.TextGrid",
        "text/x-textgrid",
      ),
      { dataType: "audio", targetUnitId: "TU-AUDIO-TRANSCRIPTION-PUNCTUATION-001" },
      permissive,
    );
    for (const report of [coco, voc, textGrid]) {
      expect(report.status).toBe("manual_review");
      expect(report.masteryImpact).toBe(false);
      expect(report.score).toBeNull();
    }
  });

  it("keeps unsupported mixed TextGrid in manual review even with a pass evaluator", async () => {
    const report = await diagnoseFile(
      fileFromText(
        `File type = "ooTextFile short"\nObject class = "TextGrid"\n0 2`,
        "short.TextGrid",
        "text/x-textgrid",
      ),
      { dataType: "audio", targetUnitId: "TU-AUDIO-TRANSCRIPTION-PUNCTUATION-001" },
      { evaluator: passEvaluator },
    );
    expect(report.status).toBe("manual_review");
    expect(report.masteryImpact).toBe(false);
    expect(report.score).toBeNull();
  });

  it("validates generic JSON response shape before an injected evaluator", async () => {
    const target = { dataType: "text", targetUnitId: "TU-TEXT-LABEL-VOCAB-001" } as const;
    const missing = await diagnoseFile(fileFromText("{}", "response.json", "application/json"), target, { evaluator: passEvaluator });
    const wrongType = await diagnoseFile(fileFromText(JSON.stringify({ labels: "negative" }), "response.json", "application/json"), target, { evaluator: passEvaluator });
    const wrongKey = await diagnoseFile(fileFromText(JSON.stringify({ wrong: ["negative"] }), "response.json", "application/json"), target, { evaluator: passEvaluator });
    const valid = await diagnoseFile(fileFromText(JSON.stringify({ labels: ["negative"] }), "response.json", "application/json"), target, { evaluator: passEvaluator });
    for (const report of [missing, wrongType, wrongKey]) {
      expect(report.status).toBe("manual_review");
      expect(report.masteryImpact).toBe(false);
      expect(report.score).toBeNull();
    }
    expect(valid.status).toBe("complete");
    expect(valid.masteryImpact).toBe(true);
    expect(valid.score).toBe(1);
    expect(missing.issues.every((candidate) => !candidate.message.includes("negative"))).toBe(true);
  });

  it("bounds deeply nested generic JSON without throwing or affecting mastery", async () => {
    const depth = 10_000;
    const body = `{"labels":${"[".repeat(depth)}"negative"${"]".repeat(depth)}}`;
    expect(new TextEncoder().encode(body).byteLength).toBeLessThan(40 * 1024);
    const report = await diagnoseFile(
      fileFromText(body, "deep.json", "application/json"),
      { dataType: "text", targetUnitId: "TU-TEXT-LABEL-VOCAB-001" },
      { evaluator: passEvaluator },
    );
    expect(["manual_review", "rejected"]).toContain(report.status);
    expect(report.score).toBeNull();
    expect(report.masteryImpact).toBe(false);
    expect(report.issues).toContainEqual(
      expect.objectContaining({ code: "response_structure_too_deep" }),
    );
  });

  it.each(invalidEvaluationCases)(
    "rejects evaluator contract violation: $name",
    async ({ fields }) => {
      const evaluator = () => {
        const result = passEvaluator();
        for (const [field, value] of Object.entries(fields)) {
          Object.defineProperty(result, field, { value, enumerable: true });
        }
        return result;
      };
      const report = await diagnoseFile(
        fileFromText(
          JSON.stringify({ labels: ["negative"] }),
          "response.json",
          "application/json",
        ),
        { dataType: "text", targetUnitId: "TU-TEXT-LABEL-VOCAB-001" },
        { evaluator },
      );
      expect(report.status).toBe("manual_review");
      expect(report.score).toBeNull();
      expect(report.masteryImpact).toBe(false);
      expect(report.issues).toContainEqual(
        expect.objectContaining({ code: "evaluation_failed" }),
      );
    },
  );

  it("preserves a valid deterministic diagnostic-rule result", async () => {
    const report = await diagnoseFile(
      fileFromText(
        JSON.stringify({ labels: ["wrong"] }),
        "response.json",
        "application/json",
      ),
      { dataType: "text", targetUnitId: "TU-TEXT-LABEL-VOCAB-001" },
      {
        evaluator: () => ({
          score: 0,
          passed: false,
          matched: "diagnostic_rule",
          errorType: "label_error",
          feedback: "Review the label rule.",
          remediation: ["Retry the exercise."],
          ruleRefs: ["RULE-1"],
          capabilityRefs: ["CAP-1"],
          dataVersion: "1.0.0",
          evaluationVersion: "1.0.0",
          manualReviewRequired: false,
        }),
      },
    );
    expect(report).toMatchObject({
      status: "complete",
      score: 0,
      masteryImpact: true,
    });
    expect(report.issues).toContainEqual(
      expect.objectContaining({ code: "label_error", severity: "severe" }),
    );
  });

  it("keeps an annotations-only generic image answer as JSON and scores its published unit", async () => {
    const unit = teachingUnits.units.find(
      (candidate) => candidate.id === "TU-IMAGE-KEYPOINT-VISIBILITY-001",
    );
    if (unit === undefined) throw new Error("canonical keypoint unit missing");
    const report = await diagnoseFile(
      fileFromText(
        JSON.stringify(unit.exercise.answer),
        "keypoints.json",
        "application/json",
      ),
      { dataType: "image", targetUnitId: unit.id },
    );
    expect(report.format).toBe("json");
    expect(report.status).toBe("complete");
    expect(report.score).toBe(1);
    expect(report.masteryImpact).toBe(true);
  });

  it("distinguishes generic annotations from partial COCO intent", () => {
    const generic = inspectJsonText(
      JSON.stringify({ annotations: [{ case_id: "KP-VISIBLE", visibility: "visible" }] }),
    );
    expect(generic.isCoco).toBe(false);
    const partialCoco = inspectJsonText(
      JSON.stringify({ images: [{ id: 1 }], categories: [] }),
    );
    expect(partialCoco.isCoco).toBe(true);
    const annotationIntent = inspectJsonText(
      JSON.stringify({ annotations: [{ id: 1, image_id: 1, category_id: 1, bbox: [0, 0, 2, 2] }] }),
    );
    expect(annotationIntent.isCoco).toBe(true);
  });

  it("handles VOC malformed XML, forbidden DOCTYPE, and coordinate order", () => {
    const invalid = inspectVocXml(
      `<annotation><size><width>100</width><height>80</height></size><object><name>x</name><bndbox><xmin>50</xmin><ymin>2</ymin><xmax>10</xmax><ymax>1</ymax></bndbox></object></annotation>`,
    );
    expect(invalid.issues.map((candidate) => candidate.code)).toContain("invalid_bndbox_order");
    const doctype = inspectVocXml(`<!DOCTYPE annotation><annotation />`);
    expect(doctype).toMatchObject({ parsed: false, rejectedCode: "xml_doctype_forbidden" });
    const malformed = inspectVocXml("<annotation><object>");
    expect(malformed).toMatchObject({ parsed: false, rejectedCode: "corrupted_xml" });
  });

  it("checks TextGrid overlap while allowing adjacent intervals", () => {
    const adjacentText = `File type = "ooTextFile"
Object class = "TextGrid"
xmin = 0
xmax = 2
tiers? <exists>
size = 1
item []:
    item [1]:
        class = "IntervalTier"
        name = "speech"
        xmin = 0
        xmax = 2
        intervals: size = 2
        intervals [1]:
            xmin = 0
            xmax = 1
            text = "a"
        intervals [2]:
            xmin = 1
            xmax = 2
            text = "b"`;
    const adjacent = inspectTextGrid(adjacentText);
    expect(adjacent.issues.map((candidate) => candidate.code)).not.toContain("interval_overlap");
    const overlap = adjacentText.replace("xmin = 1\n            xmax = 2", "xmin = 0.5\n            xmax = 2");
    expect(inspectTextGrid(overlap).issues.map((candidate) => candidate.code)).toContain("interval_overlap");
    expect(inspectTextGrid("File type = \\\"ooTextFile\\\"\\nObject class = \\\"TextGrid\\\"\\n1 2").supported).toBe(false);
  });

  it.each(textGridStructureCases)(
    "keeps TextGrid $name failures out of mastery",
    async ({ text, code }) => {
      const report = await diagnoseFile(
        fileFromText(text, "structure.TextGrid", "text/x-textgrid"),
        {
          dataType: "audio",
          targetUnitId: "TU-AUDIO-TRANSCRIPTION-PUNCTUATION-001",
        },
        { evaluator: passEvaluator },
      );
      expect(report.status).toBe("manual_review");
      expect(report.score).toBeNull();
      expect(report.masteryImpact).toBe(false);
      expect(report.issues).toContainEqual(expect.objectContaining({ code }));
    },
  );

  it("parses a large valid TextGrid without structural findings", () => {
    const intervalCount = 4_000;
    const text = largeTextGrid(intervalCount);
    expect(new TextEncoder().encode(text).byteLength).toBeLessThan(
      MAX_DIAGNOSTIC_FILE_BYTES,
    );
    const result = inspectTextGrid(text);
    expect(result.supported).toBe(true);
    expect(result.issues).toEqual([]);
  }, 30_000);

  it("reports screenshots as explanation-only for PNG and JPEG and calls no storage/network API", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const storageSet = vi.spyOn(Storage.prototype, "setItem");
    const png = await diagnoseFile(new File([new Uint8Array([137, 80, 78, 71])], "shot.png", { type: "image/png" }), context);
    const jpg = await diagnoseFile(new File([new Uint8Array([255, 216, 255])], "shot.jpg", { type: "image/jpeg" }), context);
    expect(png).toMatchObject({ format: "image", status: "explanation_only", score: null, masteryImpact: false });
    expect(jpg).toMatchObject({ format: "image", status: "explanation_only", score: null, masteryImpact: false });
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(storageSet).not.toHaveBeenCalled();
  });

  it("keeps context and parser output isolated", async () => {
    const contextObject = { dataType: "image", targetUnitId: null as string | null };
    const source = JSON.stringify({ images: [], annotations: [], categories: [] });
    const report = await diagnoseFile(fileFromText(source, "empty.json", "application/json"), contextObject);
    expect(contextObject).toEqual({ dataType: "image", targetUnitId: null });
    expect(source).not.toContain("diagnostic");
    const firstIssue = report.issues[0];
    expect(firstIssue).toBeDefined();
    expect(() => {
      Object.defineProperty(firstIssue, "code", { value: "mutated" });
    }).toThrow();
    expect(firstIssue?.code).not.toBe("mutated");
  });

  it("detects metadata formats without reading bodies", () => {
    let reads = 0;
    const file = {
      name: "sample.TextGrid",
      type: "text/x-textgrid",
      size: 0,
      text: async () => {
        reads += 1;
        return "";
      },
    };
    expect(detectFormat(file)).toMatchObject({ format: "textgrid", conflict: false });
    expect(reads).toBe(0);
  });

  it("accepts a recognized MIME when the filename has no extension", () => {
    const detected = detectFormat({
      name: "annotation-export",
      type: "application/json",
      size: 2,
      text: async () => "{}",
    });
    expect(detected).toMatchObject({ format: "json", conflict: false });
  });

  it("does not let a supported MIME override an explicit unsupported extension", () => {
    const detected = detectFormat({
      name: "annotation-export.csv",
      type: "application/json",
      size: 2,
      text: async () => "{}",
    });
    expect(detected).toMatchObject({
      format: "unknown",
      conflict: false,
      code: "unsupported_extension",
    });
  });
});
