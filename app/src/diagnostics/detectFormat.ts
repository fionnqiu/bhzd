import type {
  DetectedFormat,
  DiagnosticFileLike,
  DiagnosticFormat,
} from "./types";

type RecognizedSource = DiagnosticFormat | null;

const extensionFormat = (name: string): RecognizedSource => {
  const basename = name.split(/[\\/]/u).at(-1)?.toLowerCase() ?? "";
  if (basename.endsWith(".json")) {
    return "json";
  }
  if (basename.endsWith(".textgrid")) {
    return "textgrid";
  }
  if (basename.endsWith(".xml")) {
    return "voc";
  }
  if (basename.endsWith(".png") || basename.endsWith(".jpg") || basename.endsWith(".jpeg")) {
    return "image";
  }
  return null;
};

const mimeFormat = (mime: string): RecognizedSource => {
  const normalized = mime.trim().toLowerCase().split(";", 1)[0] ?? "";
  if (
    normalized === "application/json" ||
    normalized === "text/json" ||
    normalized === "application/ld+json"
  ) {
    return "json";
  }
  if (
    normalized === "text/x-textgrid" ||
    normalized === "application/x-textgrid" ||
    normalized === "text/textgrid"
  ) {
    return "textgrid";
  }
  if (normalized === "application/xml" || normalized === "text/xml") {
    return "voc";
  }
  if (normalized === "image/png" || normalized === "image/jpg" || normalized === "image/jpeg") {
    return "image";
  }
  return null;
};

/**
 * Detect only from metadata.  The body is deliberately not read here so a
 * caller can enforce the size limit before any potentially expensive read.
 * A specific extension/MIME disagreement is rejected conservatively.
 */
export const detectFormat = (file: DiagnosticFileLike): DetectedFormat => {
  const name = file.name;
  const rawMime = file.type ?? "";
  const byExtension = extensionFormat(name ?? "");
  const byMime = mimeFormat(rawMime);

  if (byExtension !== null && byMime !== null && byExtension !== byMime) {
    return {
      format: "unknown",
      conflict: true,
      code: "mime_extension_conflict",
    };
  }

  if (byExtension !== null) {
    return { format: byExtension, conflict: false };
  }

  if (byMime !== null) {
    // A MIME type is sufficient when no recognized extension is present. An
    // explicit conflict is reserved for two recognized, disagreeing signals.
    return { format: byMime, conflict: false };
  }

  const hasExtension = /\.[^./\\]+$/u.test(name ?? "");
  return hasExtension
    ? { format: "unknown", conflict: false, code: "unsupported_extension" }
    : { format: "unknown", conflict: false };
};

/** Convenience projection for callers that only need the conservative format. */
export const detectFormatName = (file: DiagnosticFileLike): DiagnosticFormat =>
  detectFormat(file).format;
