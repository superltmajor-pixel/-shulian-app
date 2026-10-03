"""Export reviewed source files to a fresh local Git repository without history."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from public_source import private_path, public_web_file

# Local workflow instructions and machine diagnostics are deliberately retained
# in the development checkout, never in the public snapshot.
LOCAL_ONLY = {"AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "defender-codex-ab-test.txt"}
ROOT_FILES = {
    ".env.example", ".gitignore", "README.md", "LICENSE", "LICENSING.md",
    "COMMERCIAL_LICENSE.md", "TRADEMARKS.md", "CONTRIBUTING.md", "CLA.md",
    "THIRD_PARTY_NOTICES.md", "package.json", "package-lock.json", "release.json",
    "maintenance-manifest.json", "requirements.txt", "requirements-build.txt", "requirements-release.txt",
    "package-shulian-inplace.ps1", "shulian.spec", "shulian-onedir.spec",
    "shulian.ico", "start.bat", "allow-firewall.bat", "启动数恋后端.bat", "打包EXE.bat",
}
EXACT_FILES = {
    ".githooks/pre-commit", ".github/workflows/public-source.yml",
    ".github/PULL_REQUEST_TEMPLATE.md", "tools/generate_brand_icon.py",
    "tools/brand/approved-hand-heart.png",
}
DIRECTORIES = {
    "shulian_backend": {".py"}, "tests": {".py", ".mjs", ".cjs"},
    "scripts": {".py", ".mjs", ".ps1", ".bat"},
    "packaging": {".ps1", ".bat"}, "docs": {".md"},
}


def allowed(path: str) -> bool:
    p = Path(path)
    if p.is_absolute() or ".." in p.parts or private_path(path):
        return False
    if p.name in LOCAL_ONLY:
        return False
    if path.startswith("web/"):
        return public_web_file(path)
    if path.startswith("packaging/notices/"):
        return p.suffix == ".txt"
    if path in EXACT_FILES or path in ROOT_FILES:
        return True
    if len(p.parts) == 1:
        return p.suffix == ".py"
    return p.suffix in DIRECTORIES.get(p.parts[0], set())


def export(source: Path, destination: Path) -> dict:
    source = source.resolve()
    destination = destination.absolute()
    # Reject existing destinations, including junctions and dangling links.
    if destination.exists() or destination.is_symlink() or destination.is_junction():
        raise ValueError("Destination must not exist; choose a fresh directory")
    destination = destination.resolve()
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("Destination must be separate from the development checkout")
    manifest = destination.with_name(destination.name + ".manifest.json")
    if manifest.exists() or manifest.is_symlink():
        raise ValueError("Export manifest already exists")
    raw = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=source)
    files, excluded = [], []
    for relative in sorted(set(raw.decode("utf-8").split("\0")) - {""}):
        p = source / relative
        for component in (p, *p.parents):
            if component == source:
                break
            if component.is_symlink() or component.is_junction():
                raise ValueError(f"Linked source path cannot be exported: {relative}")
        if not p.is_file():
            continue  # Tracked deletions are not part of the current source.
        if p.name in LOCAL_ONLY:
            excluded.append(relative)
            continue
        if not allowed(relative):
            raise ValueError(f"Unreviewed or private path: {relative}")
        files.append((relative, p))
    if not {"LICENSE", "main.py", "release.json"}.issubset({r for r, _ in files}):
        raise ValueError("Source snapshot is missing required files")

    destination.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for relative, p in files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != hashlib.sha256(p.read_bytes()).hexdigest():
            raise RuntimeError(f"Source changed during export: {relative}; retry to a fresh directory")
        hashes[relative] = digest
    subprocess.run(["git", "init", "--initial-branch=main", str(destination)], check=True,
                   stdout=subprocess.DEVNULL)
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=destination, check=True)
    report = {
        "release": json.loads((destination / "release.json").read_text(encoding="utf-8-sig")),
        "files": hashes, "excludedLocalFiles": excluded,
        "historyCopied": False, "committed": False, "pushed": False,
    }
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True,
                        help="New directory outside the current checkout; never overwritten")
    args = parser.parse_args()
    report = export(ROOT, args.destination)
    print(f"Exported {len(report['files'])} files; no commits, remotes or old history copied")
    print(f"Local-only files excluded: {', '.join(report['excludedLocalFiles'])}")
    print(f"Snapshot: {args.destination.absolute()}")


if __name__ == "__main__":
    main()
