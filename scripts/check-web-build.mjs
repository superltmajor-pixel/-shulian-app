import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

import {
  releaseIdentity,
  frontendNotices,
  repositoryRoot,
  sourceDigest,
} from "./web-build-shared.mjs";

const outputRoot = path.join(repositoryRoot, "web", "bundle");
const manifest = JSON.parse(
  await readFile(path.join(outputRoot, "manifest.json"), "utf8"),
);
const release = await releaseIdentity();
const notices = await readFile(path.join(outputRoot, 'THIRD-PARTY-NOTICES.txt'), 'utf8');
if (notices !== await frontendNotices()
    || createHash('sha256').update(notices).digest('hex') !== manifest.noticesSha256) {
  throw new Error('Frontend third-party notices missing or stale; run npm run build:web');
}
const expectedSourceDigest = await sourceDigest();
if (manifest.schemaVersion !== 1 || manifest.tool !== "vite") {
  throw new Error("Invalid frontend build manifest");
}
if (manifest.buildId !== release.buildId) {
  throw new Error(
    `Frontend build id is stale: ${manifest.buildId} != ${release.buildId}`,
  );
}
if (manifest.sourceSha256 !== expectedSourceDigest) {
  throw new Error("Frontend bundle is stale; run npm run build:web");
}
const bundleBytes = await readFile(path.join(outputRoot, manifest.bundle));
const bundleDigest = createHash("sha256").update(bundleBytes).digest("hex");
if (
  bundleBytes.length !== manifest.bundleBytes
  || bundleDigest !== manifest.bundleSha256
) {
  throw new Error("Frontend bundle integrity check failed");
}
process.stdout.write(
  `frontend bundle ok: ${manifest.bundle} (${bundleBytes.length} bytes)\n`,
);
