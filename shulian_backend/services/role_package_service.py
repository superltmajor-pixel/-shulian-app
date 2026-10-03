"""Portable, bounded packages for user-created roles.

The package is deliberately narrower than a role-library snapshot.  Only the
fields accepted by the custom-role creation API are exported; local paths,
runtime prompts, credentials and unrelated application state stay out.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
import stat
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

from role_archive import (
    RoleArchiveError,
    list_role_library,
    load_role_snapshot,
    resolve_role_snapshot_file,
)


PACKAGE_KIND = "shulian-custom-role"
PACKAGE_SCHEMA_VERSION = 1
MAX_PACKAGE_BYTES = 32 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 48 * 1024 * 1024
MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_SESSIONS_BYTES = 24 * 1024 * 1024
MAX_PROFILE_BYTES = 128 * 1024
MAX_MEMORY_BYTES = 200 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_SESSIONS = 500
MAX_MESSAGES = 50_000
MAX_MESSAGE_TEXT = 8_000
MAX_ENTRIES = 6

_PROFILE_TEXT_LIMITS = {
    "name": 80,
    "en": 80,
    "persona": 20_000,
    "cat": 40,
    "greet": 2_000,
    "mood": 500,
    "profileIntro": 8_000,
    "personality": 8_000,
    "speakingStyle": 8_000,
    "relationship": 8_000,
    "imgPos": 40,
    "facePos": 40,
}
_IMAGE_FIELDS = ("img", "face")
_BASE_FILES = {"profile.json", "sessions.json", "memory.txt"}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DATA_IMAGE = re.compile(
    r"data:image/(?P<kind>png|jpeg|jpg|webp|gif);base64,(?P<data>[A-Za-z0-9+/=]+)\Z",
    re.IGNORECASE,
)
_POSITION = re.compile(r"(?P<x>\d{1,3})% (?P<y>\d{1,3})%\Z")


class RolePackageError(ValueError):
    """The selected role or portable package cannot be used safely."""


def _json_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise RolePackageError("角色包包含无效的文本或数值") from exc


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise RolePackageError("角色包 JSON 包含重复字段")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise RolePackageError(f"角色包 JSON 包含无效数值: {value}")


def _decode_json(data: bytes, label: str, limit: int) -> object:
    if len(data) > limit:
        raise RolePackageError(f"{label} 超过大小限制")
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_reject_constant,
        )
        _json_bytes(value)  # Escaped lone surrogates are not valid role text.
        return value
    except RolePackageError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise RolePackageError(f"{label} 不是有效的 UTF-8 JSON") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _image_kind(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    return None


def _image_bytes_from_source(value: object, character_id: str) -> bytes | None:
    reference = str(value or "").strip()
    if not reference:
        return None
    match = _DATA_IMAGE.fullmatch(reference)
    if match:
        try:
            data = base64.b64decode(match.group("data"), validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise RolePackageError("角色图片编码无效") from exc
    else:
        parsed = urlsplit(reference)
        expected_prefix = f"/api/role-library/{character_id}/files/"
        if parsed.query or parsed.fragment or parsed.scheme or parsed.netloc:
            raise RolePackageError("角色图片不是本地档案资源")
        if parsed.path.startswith(expected_prefix):
            relative = unquote(parsed.path[len(expected_prefix):])
        elif reference.startswith("assets/"):
            relative = reference
        else:
            raise RolePackageError("角色图片不是本地档案资源")
        if not relative.startswith("assets/"):
            raise RolePackageError("角色图片不在档案资源目录")
        try:
            path = resolve_role_snapshot_file(character_id, relative)
            if path.stat().st_size > MAX_IMAGE_BYTES:
                raise RolePackageError("角色图片超过 6 MiB")
            data = path.read_bytes()
        except (OSError, RoleArchiveError) as exc:
            raise RolePackageError("无法读取角色档案图片") from exc
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise RolePackageError("角色图片必须在 6 MiB 以内")
    kind = _image_kind(data)
    if kind is None or (match and match.group("kind").lower().replace("jpg", "jpeg") != kind):
        raise RolePackageError("角色图片的文件内容与格式不匹配")
    return data


def _normalize_profile(raw: object, *, imported: bool) -> dict:
    if not isinstance(raw, dict):
        raise RolePackageError("角色包人设必须是对象")
    allowed = set(_PROFILE_TEXT_LIMITS) | {"tags", "relationshipLevel", *_IMAGE_FIELDS}
    if set(raw) - allowed:
        raise RolePackageError("角色包人设包含不支持的字段")
    profile: dict = {}
    for key, limit in _PROFILE_TEXT_LIMITS.items():
        value = raw.get(key, "50% 50%" if key.endswith("Pos") else "")
        if not isinstance(value, str) or len(value) > limit:
            raise RolePackageError(f"角色包人设字段 {key} 无效")
        if key.endswith("Pos") and value:
            position = _POSITION.fullmatch(value)
            if not position or int(position.group("x")) > 100 or int(position.group("y")) > 100:
                raise RolePackageError(f"角色包图片位置 {key} 无效")
        profile[key] = value.strip()
    if not profile["name"] or not profile["persona"]:
        raise RolePackageError("角色名称和人设不能为空")
    tags = raw.get("tags", [])
    if (
        not isinstance(tags, list)
        or len(tags) > 12
        or any(not isinstance(tag, str) or not tag.strip() or len(tag.strip()) > 50 for tag in tags)
    ):
        raise RolePackageError("角色标签无效")
    profile["tags"] = [tag.strip() for tag in tags]
    level = raw.get("relationshipLevel", 0)
    if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 10:
        raise RolePackageError("角色初始关系阶段无效")
    profile["relationshipLevel"] = level
    for field in _IMAGE_FIELDS:
        value = raw.get(field, "")
        if not isinstance(value, str):
            raise RolePackageError(f"角色图片字段 {field} 无效")
        if imported and value and not re.fullmatch(rf"images/{field}\.(png|jpg|webp|gif)", value):
            raise RolePackageError(f"角色图片引用 {field} 无效")
        profile[field] = value
    return profile


def _timestamp(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RolePackageError(f"{label} 时间戳无效")
    if not math.isfinite(value) or not 0 <= value <= 10**16:
        raise RolePackageError(f"{label} 时间戳超出范围")
    return int(value)


def _normalized_message(raw: object, *, imported: bool) -> dict | None:
    if not isinstance(raw, dict):
        raise RolePackageError("聊天记录必须是对象")
    if imported and set(raw) - {"from", "text", "ts"}:
        raise RolePackageError("聊天记录包含不支持的字段")
    speaker = raw.get("from")
    if speaker == "me":
        speaker = "me"
    elif speaker in ({"them"} if imported else {"her", "them"}):
        speaker = "them"
    else:
        if imported:
            raise RolePackageError("聊天记录发言方无效")
        return None  # Local non-chat UI events are not part of the text archive.
    text = raw.get("text")
    if not imported and not text and isinstance(raw.get("transcript"), str):
        text = raw["transcript"]
    if not isinstance(text, str) or len(text) > MAX_MESSAGE_TEXT:
        raise RolePackageError("聊天消息文本无效或过长")
    if not text.strip():
        if imported:
            raise RolePackageError("聊天消息文本不能为空")
        return None
    message = {"from": speaker, "text": text}
    ts = _timestamp(raw.get("ts"), "聊天消息")
    if ts is not None:
        message["ts"] = ts
    return message


def _normalize_sessions(raw: object, *, imported: bool) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > MAX_SESSIONS:
        raise RolePackageError("聊天会话数量超过限制")
    sessions: list[dict] = []
    total_messages = 0
    for item in raw:
        if not isinstance(item, dict):
            raise RolePackageError("聊天会话必须是对象")
        if imported and set(item) - {"startTs", "endTs", "messages"}:
            raise RolePackageError("聊天会话包含不支持的字段")
        messages = item.get("messages")
        if not isinstance(messages, list):
            raise RolePackageError("聊天会话缺少消息列表")
        total_messages += len(messages)
        if total_messages > MAX_MESSAGES:
            raise RolePackageError("聊天消息总数超过限制")
        normalized = [message for raw_message in messages
                      if (message := _normalized_message(raw_message, imported=imported)) is not None]
        if not normalized:
            continue
        start = _timestamp(item.get("startTs"), "会话开始")
        end = _timestamp(item.get("endTs"), "会话结束")
        if start is not None and end is not None and end < start:
            raise RolePackageError("聊天会话结束时间早于开始时间")
        session = {"messages": normalized}
        if start is not None:
            session["startTs"] = start
        if end is not None:
            session["endTs"] = end
        sessions.append(session)
    return sessions


def _validate_memory(value: object) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_MEMORY_BYTES:
        raise RolePackageError("角色记忆文本超过大小限制")
    return value


def _make_zip(files: dict[str, bytes]) -> bytes:
    hashes = {name: _sha256(data) for name, data in files.items()}
    manifest = {
        "kind": PACKAGE_KIND,
        "schemaVersion": PACKAGE_SCHEMA_VERSION,
        "files": hashes,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("manifest.json", _json_bytes(manifest))
        for name in sorted(files):
            archive.writestr(name, files[name])
    result = output.getvalue()
    if len(result) > MAX_PACKAGE_BYTES:
        raise RolePackageError("角色包超过 32 MiB")
    return result


def export_custom_role_package(character_id: str, *, live_state: dict | None = None) -> bytes:
    """Export only one indexed custom role's current snapshot."""
    index = list_role_library()
    roles = index.get("roles") if isinstance(index, dict) else None
    record = roles.get(character_id) if isinstance(roles, dict) else None
    if not isinstance(record, dict) or record.get("origin") != "custom":
        raise RolePackageError("只有自建角色可以导出角色包")
    try:
        snapshot = load_role_snapshot(character_id, include_state=True)
    except RoleArchiveError as exc:
        raise RolePackageError("无法读取当前角色档案") from exc
    backend = snapshot.get("backend") or {}
    frontend = snapshot.get("frontend") or {}
    state = {**(snapshot.get("state") or {}), **(live_state or {})}
    profile = _normalize_profile({
        "name": backend.get("name") or frontend.get("name") or "",
        "en": backend.get("en") or frontend.get("en") or "",
        "persona": backend.get("persona") or frontend.get("persona") or "",
        "tags": backend.get("tags") or frontend.get("tags") or [],
        "cat": backend.get("cat") or frontend.get("cat") or "",
        "greet": backend.get("greet") or frontend.get("greet") or "",
        "mood": backend.get("mood") or frontend.get("mood") or "",
        "profileIntro": frontend.get("profileIntro") or backend.get("core_memory") or "",
        "personality": frontend.get("personality") or "",
        "speakingStyle": frontend.get("speakingStyle") or "",
        "relationship": frontend.get("relationship") or "",
        "relationshipLevel": frontend.get("relationshipLevel", 0),
        "imgPos": frontend.get("imgPos") or "50% 50%",
        "facePos": frontend.get("facePos") or "50% 50%",
        "img": frontend.get("img") or "",
        "face": frontend.get("face") or "",
    }, imported=False)
    files: dict[str, bytes] = {}
    for field in _IMAGE_FIELDS:
        image = _image_bytes_from_source(profile[field], character_id)
        if image is not None:
            kind = _image_kind(image)
            extension = "jpg" if kind == "jpeg" else kind
            name = f"images/{field}.{extension}"
            files[name] = image
            profile[field] = name
    sessions = list(state.get("importedSessions") or []) + list(state.get("archivedSessions") or [])
    current = state.get("currentMessages") or []
    if current:
        sessions.append({
            "startTs": current[0].get("ts") if isinstance(current[0], dict) else None,
            "endTs": current[-1].get("ts") if isinstance(current[-1], dict) else None,
            "messages": current,
        })
    sessions = _normalize_sessions(sessions, imported=False)
    memory = _validate_memory(state.get("memory") or "")
    files["profile.json"] = _json_bytes(profile)
    files["sessions.json"] = _json_bytes(sessions)
    files["memory.txt"] = memory.encode("utf-8")
    if len(files["profile.json"]) > MAX_PROFILE_BYTES or len(files["sessions.json"]) > MAX_SESSIONS_BYTES:
        raise RolePackageError("角色资料或聊天记录超过角色包限制")
    if sum(map(len, files.values())) > MAX_UNCOMPRESSED_BYTES:
        raise RolePackageError("角色包解压大小超过限制")
    return _make_zip(files)


def _entry_limit(name: str) -> int:
    if name == "manifest.json":
        return MAX_MANIFEST_BYTES
    if name == "profile.json":
        return MAX_PROFILE_BYTES
    if name == "sessions.json":
        return MAX_SESSIONS_BYTES
    if name == "memory.txt":
        return MAX_MEMORY_BYTES
    if re.fullmatch(r"images/(img|face)\.(png|jpg|webp|gif)", name):
        return MAX_IMAGE_BYTES
    raise RolePackageError("角色包包含不允许的文件")


def _read_zip(payload: bytes) -> dict[str, bytes]:
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_PACKAGE_BYTES:
        raise RolePackageError("角色包文件必须在 32 MiB 以内")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            if len(infos) < 4 or len(infos) > MAX_ENTRIES:
                raise RolePackageError("角色包文件数量无效")
            files: dict[str, bytes] = {}
            total_size = 0
            for info in infos:
                name = info.filename
                limit = _entry_limit(name)
                if name in files or name.startswith("/") or "\\" in name or ".." in Path(name).parts:
                    raise RolePackageError("角色包文件路径无效或重复")
                file_type = stat.S_IFMT(info.external_attr >> 16)
                if (
                    info.is_dir()
                    or file_type not in (0, stat.S_IFREG)
                    or info.flag_bits & 0x1
                    or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                ):
                    raise RolePackageError("角色包包含不支持的文件类型")
                if info.file_size > limit:
                    raise RolePackageError(f"角色包文件 {name} 超过大小限制")
                total_size += info.file_size
                if total_size > MAX_UNCOMPRESSED_BYTES:
                    raise RolePackageError("角色包解压大小超过限制")
                with archive.open(info, "r") as stream:
                    data = stream.read(limit + 1)
                if len(data) > limit or len(data) != info.file_size:
                    raise RolePackageError(f"角色包文件 {name} 大小无效")
                files[name] = data
            return files
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, OSError) as exc:
        raise RolePackageError("角色包 ZIP 无效或已损坏") from exc


def import_custom_role_package(payload: bytes) -> dict:
    """Validate a role ZIP and return an editable custom-role POST draft."""
    files = _read_zip(payload)
    if not _BASE_FILES | {"manifest.json"} <= files.keys():
        raise RolePackageError("角色包缺少必需文件")
    manifest = _decode_json(files["manifest.json"], "manifest.json", MAX_MANIFEST_BYTES)
    if not isinstance(manifest, dict) or set(manifest) != {"kind", "schemaVersion", "files"}:
        raise RolePackageError("角色包清单结构无效")
    if (
        manifest["kind"] != PACKAGE_KIND
        or type(manifest["schemaVersion"]) is not int
        or manifest["schemaVersion"] != PACKAGE_SCHEMA_VERSION
    ):
        raise RolePackageError("角色包版本或类型不受支持")
    hashes = manifest["files"]
    if not isinstance(hashes, dict) or set(hashes) != files.keys() - {"manifest.json"}:
        raise RolePackageError("角色包文件清单不匹配")
    for name, digest in hashes.items():
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest) or _sha256(files[name]) != digest:
            raise RolePackageError(f"角色包文件 {name} 校验失败")
    profile = _normalize_profile(_decode_json(files["profile.json"], "profile.json", MAX_PROFILE_BYTES), imported=True)
    expected_images = {profile[field] for field in _IMAGE_FIELDS if profile[field]}
    if files.keys() - _BASE_FILES - {"manifest.json"} != expected_images:
        raise RolePackageError("角色包图片引用与文件不匹配")
    for field in _IMAGE_FIELDS:
        reference = profile[field]
        if not reference:
            continue
        image = files[reference]
        extension = reference.rsplit(".", 1)[-1]
        expected_kind = "jpeg" if extension == "jpg" else extension
        if not image or _image_kind(image) != expected_kind:
            raise RolePackageError("角色包图片内容与格式不匹配")
        profile[field] = f"data:image/{expected_kind};base64,{base64.b64encode(image).decode('ascii')}"
    sessions = _normalize_sessions(
        _decode_json(files["sessions.json"], "sessions.json", MAX_SESSIONS_BYTES),
        imported=True,
    )
    try:
        memory = files["memory.txt"].decode("utf-8")
    except UnicodeError as exc:
        raise RolePackageError("角色记忆不是有效的 UTF-8 文本") from exc
    return {"profile": profile, "archived_sessions": sessions, "memory": _validate_memory(memory)}
