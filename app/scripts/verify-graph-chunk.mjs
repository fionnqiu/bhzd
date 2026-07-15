import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { relative, resolve } from "node:path";

const HEAVY_GRAPH_MARKER = /vis-network|stabilizationIterationsDone/u;
const STATIC_VIS_IMPORT =
  /(?:^|\n)\s*(?:import\s+(?!type\b)(?:[^;\n]*?\s+from\s+)?|export\s+(?!type\b)[^;\n]*?\s+from\s+)["'](?:vis-network|vis-data|vis-util)(?:\/[^"']*)?["']/gu;

const normalizedPath = (value) => value.replaceAll("\\", "/");

const graphEntryFor = (manifest) =>
  Object.entries(manifest).find(
    ([key, entry]) =>
      /GraphWorkspace/iu.test(key) ||
      /GraphWorkspace/iu.test(entry?.name ?? ""),
  );

const staticClosureFor = (manifest, entryKey) => {
  const visited = new Set();
  const pending = [entryKey];

  while (pending.length > 0) {
    const key = pending.pop();
    if (typeof key !== "string" || visited.has(key)) {
      continue;
    }
    visited.add(key);
    const entry = manifest[key];
    for (const importedKey of entry?.imports ?? []) {
      pending.push(importedKey);
    }
  }

  return visited;
};

/**
 * Verify both the Rollup manifest relationship and the heavy dependency
 * boundary. Returning errors keeps the contract directly regression-testable
 * while the executable wrapper below turns them into a failing build.
 */
export const verifyGraphChunkBoundary = ({
  manifest,
  sourceFiles,
  outputFiles,
}) => {
  const errors = [];
  const indexEntry = manifest["index.html"];
  if (indexEntry === undefined || indexEntry.isEntry !== true) {
    return ["index.html is not marked as the application entry"];
  }

  const graphEntry = graphEntryFor(manifest);
  if (graphEntry === undefined) {
    return ["no GraphWorkspace manifest entry exists"];
  }

  const [graphKey, graphManifest] = graphEntry;
  if (graphManifest.isDynamicEntry !== true) {
    errors.push(`${graphKey} is not marked as a dynamic entry`);
  }
  if (!(indexEntry.dynamicImports ?? []).includes(graphKey)) {
    errors.push(`index.html does not reference ${graphKey} through dynamicImports`);
  }

  const staticClosure = staticClosureFor(manifest, "index.html");
  if (staticClosure.has(graphKey)) {
    errors.push(`${graphKey} is statically reachable from the index entry`);
  }

  for (const [sourcePath, source] of sourceFiles) {
    const normalized = normalizedPath(sourcePath);
    if (
      normalized.startsWith("features/graph/") ||
      normalized.includes("/features/graph/")
    ) {
      continue;
    }
    STATIC_VIS_IMPORT.lastIndex = 0;
    if (STATIC_VIS_IMPORT.test(source)) {
      errors.push(`static vis dependency found outside lazy graph subtree: ${normalized}`);
    }
  }

  const staticOutput = [...staticClosure]
    .map((key) => manifest[key]?.file)
    .filter((file) => typeof file === "string")
    .map((file) => outputFiles.get(file) ?? "")
    .join("\n");
  if (HEAVY_GRAPH_MARKER.test(staticOutput)) {
    errors.push("heavy graph dependency leaked into the index entry static closure");
  }

  const graphOutput = outputFiles.get(graphManifest.file) ?? "";
  if (!HEAVY_GRAPH_MARKER.test(graphOutput)) {
    errors.push("dynamic GraphWorkspace chunk does not contain the expected graph dependency marker");
  }

  return errors;
};

const collectSourceFiles = async (root) => {
  const files = new Map();
  const visit = async (directory) => {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = resolve(directory, entry.name);
      if (entry.isDirectory()) {
        await visit(path);
      } else if (/\.(?:[cm]?[jt]sx?)$/u.test(entry.name)) {
        files.set(normalizedPath(relative(root, path)), await readFile(path, "utf8"));
      }
    }
  };
  await visit(root);
  return files;
};

const run = async () => {
  const appRoot = process.cwd();
  const manifestPath = resolve(appRoot, "dist", ".vite", "manifest.json");
  let manifest;
  try {
    manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  } catch (error) {
    throw new Error(
      `cannot read ${manifestPath}: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
  }

  const outputFiles = new Map();
  for (const entry of Object.values(manifest)) {
    if (typeof entry?.file !== "string" || !entry.file.endsWith(".js")) {
      continue;
    }
    outputFiles.set(
      entry.file,
      await readFile(resolve(appRoot, "dist", entry.file), "utf8"),
    );
  }

  const errors = verifyGraphChunkBoundary({
    manifest,
    sourceFiles: await collectSourceFiles(resolve(appRoot, "src")),
    outputFiles,
  });
  if (errors.length > 0) {
    throw new Error(errors.join("\n"));
  }

  const [graphKey, graphManifest] = graphEntryFor(manifest);
  console.log(
    `GraphWorkspace and vis-network are isolated behind a dynamic boundary: ${graphKey} -> ${graphManifest.file}`,
  );
};

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : null;
if (invokedPath === fileURLToPath(import.meta.url)) {
  run().catch((error) => {
    console.error(
      `Graph chunk verification failed: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
    process.exitCode = 1;
  });
}
