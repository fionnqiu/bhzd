import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const manifestPath = resolve(process.cwd(), "dist", ".vite", "manifest.json");

const fail = (message) => {
  console.error(`Graph chunk verification failed: ${message}`);
  process.exitCode = 1;
};

let manifest;
try {
  manifest = JSON.parse(await readFile(manifestPath, "utf8"));
} catch (error) {
  fail(`cannot read ${manifestPath}: ${error instanceof Error ? error.message : String(error)}`);
}

if (process.exitCode === 1) {
  process.exit();
}

const entries = Object.entries(manifest);
const indexEntry = manifest["index.html"];
if (indexEntry === undefined || indexEntry.isEntry !== true) {
  fail("index.html is not marked as the application entry");
  process.exit();
}

const graphEntry = entries.find(([key, entry]) =>
  /GraphWorkspace/iu.test(key) || /GraphWorkspace/iu.test(entry.name ?? ""),
);
if (graphEntry === undefined) {
  fail("no GraphWorkspace manifest entry exists");
  process.exit();
}

const [graphKey, graphManifest] = graphEntry;
if (graphManifest.isDynamicEntry !== true) {
  fail(`${graphKey} is not marked as a dynamic entry`);
}

if (!(indexEntry.dynamicImports ?? []).includes(graphKey)) {
  fail(`index.html does not reference ${graphKey} through dynamicImports`);
}

if ((indexEntry.imports ?? []).includes(graphKey)) {
  fail(`index.html statically imports ${graphKey}`);
}

if (process.exitCode !== 1) {
  console.log(
    `GraphWorkspace is dynamically loaded: ${graphKey} -> ${graphManifest.file}`,
  );
}
