// @vitest-environment node

import { describe, expect, it } from "vitest";

// The production verifier is an executable ESM module with a deliberately
// small public pure function for regression tests.
// @ts-expect-error The executable .mjs module has no generated declaration.
import { verifyGraphChunkBoundary } from "../../scripts/verify-graph-chunk.mjs";

const manifest = {
  "index.html": {
    file: "assets/index.js",
    isEntry: true,
    dynamicImports: ["src/features/graph/GraphWorkspace.tsx"],
  },
  "src/features/graph/GraphWorkspace.tsx": {
    file: "assets/graph.js",
    name: "GraphWorkspace",
    isDynamicEntry: true,
    imports: ["index.html"],
  },
};

const validInputs = {
  manifest,
  sourceFiles: new Map([
    [
      "src/app/App.tsx",
      'const GraphWorkspace = lazy(() => import("../features/graph/GraphWorkspace"));',
    ],
    [
      "features/graph/GraphCanvas.tsx",
      'import { Network } from "vis-network";',
    ],
  ]),
  outputFiles: new Map([
    ["assets/index.js", "console.log('application entry')"],
    ["assets/graph.js", "/* vis-network */ stabilizationIterationsDone"],
  ]),
};

describe("graph chunk boundary verifier", () => {
  it("accepts a graph dependency isolated behind the dynamic workspace", () => {
    expect(verifyGraphChunkBoundary(validInputs)).toEqual([]);
  });

  it("rejects a static vis dependency even when a dynamic GraphWorkspace entry still exists", () => {
    const sourceFiles = new Map(validInputs.sourceFiles);
    sourceFiles.set(
      "src/app/App.tsx",
      'import { Network } from "vis-network";\nconst GraphWorkspace = lazy(() => import("../features/graph/GraphWorkspace"));',
    );

    expect(
      verifyGraphChunkBoundary({ ...validInputs, sourceFiles }),
    ).toEqual(expect.arrayContaining([expect.stringMatching(/static vis dependency/iu)]));
  });

  it("rejects heavy graph code in the entry static-import closure", () => {
    const closureManifest = {
      ...manifest,
      "index.html": {
        ...manifest["index.html"],
        imports: ["src/vendor.ts"],
      },
      "src/vendor.ts": {
        file: "assets/vendor.js",
      },
    };
    const outputFiles = new Map(validInputs.outputFiles);
    outputFiles.set("assets/vendor.js", "/* vis-network */");

    expect(
      verifyGraphChunkBoundary({
        ...validInputs,
        manifest: closureManifest,
        outputFiles,
      }),
    ).toEqual(expect.arrayContaining([expect.stringMatching(/entry static closure/iu)]));
  });

  it("rejects GraphWorkspace when it becomes statically reachable through an intermediate chunk", () => {
    const staticManifest = {
      ...manifest,
      "index.html": {
        ...manifest["index.html"],
        imports: ["src/vendor.ts"],
      },
      "src/vendor.ts": {
        file: "assets/vendor.js",
        imports: ["src/features/graph/GraphWorkspace.tsx"],
      },
    };

    expect(
      verifyGraphChunkBoundary({ ...validInputs, manifest: staticManifest }),
    ).toEqual(expect.arrayContaining([expect.stringMatching(/statically reachable/iu)]));
  });
});
