"""Collect installed dependency notices for the modules selected by PyInstaller."""
from __future__ import annotations

import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import sys


def collect_binary_notices(pure, binaries, root: Path, work: Path) -> list[tuple[str, str, str]]:
    """Return DATA entries without copying app data or absolute paths to the report.

    This records package notices, not a claim that every native dependency's
    redistribution terms have been reviewed. The report retains that boundary.
    """
    package_map = metadata.packages_distributions()
    names = {"pyinstaller"}  # Its bootloader is present even without a Python module.
    for module, _, _ in pure:
        names.update(package_map.get(module.split(".", 1)[0], []))
    paths = {Path(source).resolve() for _, source, _ in binaries}
    for dist in metadata.distributions():
        if any(Path(dist.locate_file(file)).resolve() in paths for file in dist.files or []):
            names.add(dist.metadata["Name"])

    output = work / "third-party-notices"
    output.mkdir(parents=True, exist_ok=True)
    entries, packages, missing = [], [], []
    seen = set()

    def include(source: Path, target: str) -> dict:
        if target in seen:
            raise ValueError(f"Duplicate notice destination: {target}")
        seen.add(target)
        entries.append((target, str(source), "DATA"))
        return {"path": target, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}

    for name in sorted(names, key=str.casefold):
        dist = metadata.distribution(name)
        canonical = re.sub(r"[-_.]+", "-", dist.metadata["Name"]).lower()
        base = f"third-party/{canonical}-{dist.version}"
        notices = []
        for file in sorted(dist.files or [], key=str):
            parts = Path(str(file)).parts
            if ".." in parts or Path(str(file)).is_absolute():
                continue
            filename = parts[-1].lower()
            if not any(word in filename for word in ("license", "licence", "copying", "copyright", "notice")):
                continue
            source = Path(dist.locate_file(file))
            if source.is_file():
                notices.append(include(source, f"{base}/{'/'.join(parts)}"))
        supplement = root / "packaging" / "notices" / f"{canonical}.txt"
        if supplement.is_file():
            notices.append(include(supplement, f"{base}/UPSTREAM-LICENSE.txt"))
        if not notices:
            missing.append(f"{canonical}=={dist.version}")
        packages.append({
            "name": dist.metadata["Name"], "version": dist.version,
            "licenseExpression": dist.metadata.get("License-Expression"),
            "notices": notices,
        })

        # Keep unmodified library sources accessible for LGPL edge-tts and MPL
        # certifi. Matching app source and rebuild instructions must accompany
        # a public binary release as well.
        if canonical in {"edge-tts", "certifi"}:
            for file in sorted(dist.files or [], key=str):
                relative = Path(str(file))
                if relative.is_absolute() or ".." in relative.parts:
                    continue
                if relative.suffix not in {".py", ".pem"} and relative.name != "METADATA":
                    continue
                source = Path(dist.locate_file(file))
                if source.is_file():
                    include(source, f"{base}/source/{relative.as_posix()}")

    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError("Python runtime LICENSE.txt is required for distribution")
    include(python_license, "third-party/python/LICENSE.txt")
    for source in sorted((root / "packaging" / "notices").glob("*.txt")):
        include(source, f"third-party/supplemental/{source.name}")

    report = {
        "schemaVersion": 1, "pythonVersion": sys.version.split()[0],
        "packages": packages, "missingPackageNotices": missing,
        "reviewRequired": [
            "Native DLLs and embedded components need distribution review before public release.",
            "Publish matching application source, library source archives and rebuild instructions together.",
        ],
    }
    manifest = output / "manifest.json"
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    entries.append(("third-party/manifest.json", str(manifest), "DATA"))
    return entries
