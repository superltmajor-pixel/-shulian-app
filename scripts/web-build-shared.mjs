import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

export const frontendSourceFiles = [
  "web/tweaks-panel.jsx",
  "web/i18n.jsx",
  "web/glass.jsx",
  "web/data.jsx",
  "web/custom-role.jsx",
  "web/screens.jsx",
  "web/realtime-voice.jsx",
  "web/compatible-voice.jsx",
  "web/chat.jsx",
  "web/app.jsx",
];

// Copy the licenses belonging to the actual packages embedded in our bundle.
// Keeping this derived from node_modules prevents stale notices after upgrades.
export async function frontendNotices() {
  const sections = ['Shulian frontend third-party notices\n'];
  for (const name of ['react', 'react-dom', 'scheduler']) {
    const root = path.join(repositoryRoot, 'node_modules', name);
    const metadata = JSON.parse(await readFile(path.join(root, 'package.json'), 'utf8'));
    const license = await readFile(path.join(root, 'LICENSE'), 'utf8');
    sections.push(`${name} ${metadata.version}\n${'='.repeat(60)}\n${license.trim()}\n`);
  }
  return sections.join('\n');
}

export async function sourceDigest() {
  const hash = createHash("sha256");
  for (const relativePath of [...frontendSourceFiles, "web/realtime-audio-worklet.js"]) {
    hash.update(relativePath);
    hash.update("\0");
    hash.update(await readFile(path.join(repositoryRoot, relativePath)));
    hash.update("\0");
  }
  return hash.digest("hex");
}

export async function releaseIdentity(root = repositoryRoot) {
  const release = JSON.parse(await readFile(path.join(root, "release.json"), "utf8"));
  const checks = [
    ["shulian_backend/version.py", /APP_VERSION\s*=\s*["']([^"']+)["']/, release.version],
    ["shulian_backend/version.py", /BUILD_ID\s*=\s*["']([^"']+)["']/, release.buildId],
    ["web/data.jsx", /SHULIAN_APP_VERSION\s*=\s*["']([^"']+)["']/, release.version],
    ["web/app.jsx", /SHULIAN_BUILD_ID\s*=\s*["']([^"']+)["']/, release.buildId],
    ["web/index.html", /bundle\/app\.bundle\.js\?v=([^"']+)/, release.buildId],
  ];
  for (const [file, pattern, expected] of checks) {
    const source = await readFile(path.join(root, file), "utf8");
    if (!expected || source.match(pattern)?.[1] !== expected) {
      throw new Error(`Release identity mismatch in ${file}; expected ${expected}`);
    }
  }
  return release;
}
