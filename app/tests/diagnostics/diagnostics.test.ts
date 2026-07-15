import { describe, expect, it, vi } from "vitest";
import { diagnoseFile } from "../../src/diagnostics/diagnose";
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
): File => new File([text], name, { type });

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
    const file = new File([body], "sample.json", {
      type: "application/json",
    });
    const result = await diagnoseFile(file, context);
    expect(result.format).toBe("coco");
    expect(result.issues).toContainEqual(
      expect.objectContaining({
        code: "missing_category_reference",
        severity: "severe",
      }),
    );
  });

  it("allows exactly five MiB and reads a file body once", async () => {
    const body = "{}";
    let reads = 0;
    const file = {
      name: "exact.json",
      type: "application/json",
      size: 5 * 1024 * 1024,
      text: async () => {
        reads += 1;
        return body;
      },
    };
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
    storageSet.mockRestore();
    vi.unstubAllGlobals();
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
});
