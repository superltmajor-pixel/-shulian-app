"""读取并校验可安全公开的客户端发布身份。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..version import APP_VERSION, BUILD_ID, RELEASE_SCHEMA_VERSION


_SEMVER = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?$"
)
_SAFE_CHANNELS = {"stable", "beta", "dev"}


def _fallback_release(build_id: str) -> dict:
    return {
        "ok": False,
        "schema_version": RELEASE_SCHEMA_VERSION,
        "version": APP_VERSION,
        "build_id": build_id,
        "channel": "dev",
        "platform": "windows-x64",
        "error": "release_metadata_missing",
    }


def release_status(resource_dir: str, build_id: str = BUILD_ID) -> dict:
    """返回自检可公开字段，不包含文件清单、路径或下载地址。"""
    path = Path(resource_dir) / "release.json"
    if not path.is_file():
        return _fallback_release(build_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        result = _fallback_release(build_id)
        result["error"] = "release_metadata_invalid"
        return result

    schema_version = payload.get("schemaVersion")
    version = payload.get("version")
    metadata_build_id = payload.get("buildId")
    channel = payload.get("channel")
    platform = payload.get("platform")
    valid = (
        schema_version == RELEASE_SCHEMA_VERSION
        and isinstance(version, str)
        and _SEMVER.fullmatch(version) is not None
        and version == APP_VERSION
        and metadata_build_id == build_id
        and channel in _SAFE_CHANNELS
        and platform == "windows-x64"
    )
    return {
        "ok": valid,
        "schema_version": schema_version,
        "version": version if isinstance(version, str) else APP_VERSION,
        "build_id": (
            metadata_build_id if isinstance(metadata_build_id, str) else build_id
        ),
        "channel": channel if channel in _SAFE_CHANNELS else "dev",
        "platform": platform if isinstance(platform, str) else "windows-x64",
        "error": None if valid else "release_metadata_mismatch",
    }
