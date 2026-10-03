import { createHash } from "node:crypto";
import {
  mkdir,
  readFile,
  readdir,
  rm,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { build } from "vite";

import {
  frontendSourceFiles,
  frontendNotices,
  releaseIdentity,
  repositoryRoot,
  sourceDigest,
} from "./web-build-shared.mjs";

const generatedRoot = path.join(repositoryRoot, ".frontend-build");
const generatedEntry = path.join(generatedRoot, "shulian-entry.jsx");
const outputRoot = path.join(repositoryRoot, "web", "bundle");
const release = await releaseIdentity();

await rm(generatedRoot, { recursive: true, force: true });
await mkdir(generatedRoot, { recursive: true });

const prelude = [
  'import React from "react";',
  'import { createRoot } from "react-dom/client";',
  "const ReactDOM = { createRoot };",
  "",
].join("\n");
const sources = [];
for (const relativePath of frontendSourceFiles) {
  sources.push(`\n/* source: ${relativePath} */\n`);
  sources.push(await readFile(path.join(repositoryRoot, relativePath), "utf8"));
  sources.push("\n");
}
await writeFile(generatedEntry, prelude + sources.join(""), "utf8");

try {
  await build({
    configFile: false,
    root: repositoryRoot,
    define: {
      "process.env.NODE_ENV": JSON.stringify("production"),
    },
    build: {
      target: "chrome109",
      outDir: outputRoot,
      emptyOutDir: true,
      minify: true,
      sourcemap: false,
      lib: {
        entry: generatedEntry,
        name: "ShulianFrontend",
        formats: ["iife"],
        fileName: () => "app.bundle.js",
      },
    },
  });

  const outputFiles = await readdir(outputRoot);
  const bundleName = outputFiles.find(
    (name) => name === "app.bundle.js" || name.endsWith(".js"),
  );
  if (!bundleName) throw new Error("Vite did not produce a JavaScript bundle");
  const bundlePath = path.join(outputRoot, bundleName);
  const bundleBytes = await readFile(bundlePath);
  const notices = await frontendNotices();
  await writeFile(path.join(outputRoot, 'THIRD-PARTY-NOTICES.txt'), notices, 'utf8');
  const manifest = {
    schemaVersion: 1,
    tool: "vite",
    viteVersion: "8.1.5",
    reactVersion: "18.3.1",
    format: "iife",
    buildId: release.buildId,
    sourceSha256: await sourceDigest(),
    bundle: bundleName,
    bundleBytes: bundleBytes.length,
    bundleSha256: createHash("sha256").update(bundleBytes).digest("hex"),
    noticesSha256: createHash("sha256").update(notices).digest("hex"),
  };
  await writeFile(
    path.join(outputRoot, "manifest.json"),
    `${JSON.stringify(manifest, null, 2)}\n`,
    "utf8",
  );
} finally {
  await rm(generatedRoot, { recursive: true, force: true });
}
