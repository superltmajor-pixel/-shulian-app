from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
from functools import wraps
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit


SCHEMA_VERSION = 1
ROLE_WRITE_LOCK = threading.RLock()


def _serialized_role_write(function):
    @wraps(function)
    def locked(*args, **kwargs):
        with ROLE_WRITE_LOCK:
            return function(*args, **kwargs)
    return locked

_SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_SAFE_SNAPSHOT_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$")
_DATA_IMAGE = re.compile(
    r"^data:image/(?P<kind>png|jpeg|jpg|webp|gif);base64,(?P<data>[A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE,
)


class RoleArchiveError(RuntimeError):
    pass


def _matches_image_signature(kind: str, payload: bytes) -> bool:
    if kind == "png":
        return payload.startswith(b"\x89PNG\r\n\x1a\n")
    if kind in {"jpeg", "jpg"}:
        return payload.startswith(b"\xff\xd8\xff")
    if kind == "webp":
        return (
            len(payload) >= 12
            and payload.startswith(b"RIFF")
            and payload[8:12] == b"WEBP"
        )
    if kind == "gif":
        return payload.startswith((b"GIF87a", b"GIF89a"))
    return False


def role_library_root() -> Path:
    override = os.getenv("SHULIAN_ROLE_LIBRARY_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        base = Path(local_app_data)
    else:
        base = Path.home() / "AppData" / "Local"
    return (base / "Shulian" / "role-library").resolve()


def _safe_character_id(character_id: str) -> str:
    value = str(character_id or "").strip()
    if not _SAFE_ID.fullmatch(value):
        raise RoleArchiveError("Invalid character id")
    return value


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RoleArchiveError(f"Cannot read role library metadata: {path.name}") from exc


def _character_record(character: object) -> dict:
    if is_dataclass(character):
        raw = asdict(character)
    else:
        keys = (
            "id", "name", "en", "persona", "tags", "cat", "greet", "mood",
            "replies", "system_prompt", "core_memory", "public_background",
            "intimacy", "motif",
        )
        raw = {key: getattr(character, key, None) for key in keys}
    raw["public_background"] = list(raw.get("public_background") or [])
    raw["tags"] = list(raw.get("tags") or [])
    raw["replies"] = list(raw.get("replies") or [])
    return raw


def _canonical_asset_reference(value: str) -> str | None:
    normalized = str(value or "").replace("\\", "/").strip()
    direct = normalized.lstrip("./")
    if direct.startswith("assets/"):
        return unquote(direct)

    parsed = urlsplit(normalized)
    match = re.fullmatch(
        r"/api/role-library/[^/]+/files/(?P<asset>assets/.+)",
        parsed.path,
    )
    if match:
        return unquote(match.group("asset"))
    return None


def _canonicalize_profile_assets(value: object) -> object:
    if isinstance(value, str):
        return _canonical_asset_reference(value) or value
    if isinstance(value, dict):
        return {
            key: _canonicalize_profile_assets(nested)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [_canonicalize_profile_assets(nested) for nested in value]
    return value


def _asset_references(value: object):
    if isinstance(value, str):
        reference = _canonical_asset_reference(value)
        if reference:
            yield reference
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _asset_references(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _asset_references(nested)


def _store_embedded_profile_images(
    value: object,
    snapshot_dir: Path,
) -> tuple[object, list[str]]:
    """Move profile data URLs into immutable snapshot assets."""
    copied: list[str] = []

    def transform(item: object) -> object:
        if isinstance(item, str):
            match = _DATA_IMAGE.fullmatch(item.strip())
            if not match:
                return item
            try:
                payload = base64.b64decode(match.group("data"), validate=True)
            except (ValueError, base64.binascii.Error) as exc:
                raise RoleArchiveError("Invalid embedded role image") from exc
            if not payload or len(payload) > 6 * 1024 * 1024:
                raise RoleArchiveError("Embedded role image must be 6 MB or smaller")
            extension = match.group("kind").lower()
            if not _matches_image_signature(extension, payload):
                raise RoleArchiveError("Embedded role image content does not match its type")
            if extension == "jpeg":
                extension = "jpg"
            digest = hashlib.sha256(payload).hexdigest()
            relative = f"assets/imported/{digest[:16]}.{extension}"
            destination = snapshot_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                destination.write_bytes(payload)
            copied.append(relative)
            return relative
        if isinstance(item, dict):
            return {key: transform(nested) for key, nested in item.items()}
        if isinstance(item, list):
            return [transform(nested) for nested in item]
        return item

    return transform(value), sorted(set(copied))


def _copy_profile_assets(
    frontend_profile: dict,
    web_dir: Path,
    snapshot_dir: Path,
    previous_snapshot_dir: Path | None = None,
) -> list[str]:
    copied: list[str] = []
    web_root = web_dir.resolve()
    for reference in sorted(set(_asset_references(frontend_profile))):
        source = (web_root / reference).resolve()
        try:
            source.relative_to(web_root)
        except ValueError:
            continue
        if not source.is_file() and previous_snapshot_dir is not None:
            candidate = (previous_snapshot_dir / reference).resolve()
            try:
                candidate.relative_to(previous_snapshot_dir.resolve())
            except ValueError:
                continue
            source = candidate
        if not source.is_file():
            continue
        destination = snapshot_dir / reference
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(reference)
    return copied


def _copy_voice_attachment(audio_url: str, voice_dir: Path, attachments_dir: Path) -> str | None:
    parsed = urlsplit(str(audio_url or ""))
    if not parsed.path.startswith("/media/"):
        return None
    filename = Path(parsed.path).name
    if not filename or filename in {".", ".."}:
        return None
    source = (voice_dir / filename).resolve()
    try:
        source.relative_to(voice_dir.resolve())
    except ValueError:
        return None
    if not source.is_file():
        return None
    destination = attachments_dir / "audio" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(source, destination)
    return destination.relative_to(attachments_dir.parent).as_posix()


def _extract_image_attachment(
    image_url: str,
    attachments_dir: Path,
    conversation_id: str,
    sequence: int,
) -> str | None:
    match = _DATA_IMAGE.fullmatch(str(image_url or "").strip())
    if not match:
        return None
    try:
        payload = base64.b64decode(match.group("data"), validate=True)
    except (ValueError, base64.binascii.Error):
        return None
    if not payload or len(payload) > 12 * 1024 * 1024:
        return None
    extension = match.group("kind").lower()
    if extension == "jpeg":
        extension = "jpg"
    digest = hashlib.sha256(payload).hexdigest()[:12]
    filename = f"{conversation_id}-{sequence:06d}-{digest}.{extension}"
    destination = attachments_dir / "images" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        destination.write_bytes(payload)
    return destination.relative_to(attachments_dir.parent).as_posix()


def _copy_archived_attachment(url: str, previous: Path | None, destination: Path) -> str | None:
    if previous is None:
        return None
    parsed = urlsplit(str(url or ""))
    character_id = previous.parent.parent.name
    prefix = f"/api/role-library/{character_id}/files/attachments/"
    if parsed.scheme or parsed.netloc or not parsed.path.startswith(prefix):
        return None
    relative = Path("attachments") / unquote(parsed.path[len(prefix):])
    source = (previous / relative).resolve()
    try:
        source.relative_to((previous / "attachments").resolve())
    except ValueError as exc:
        raise RoleArchiveError("Invalid archived attachment path") from exc
    if not source.is_file():
        raise RoleArchiveError("Previous chat attachment is missing")
    target = destination.parent / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return relative.as_posix()


def _normalize_messages(
    messages: list,
    conversation_id: str,
    conversation_kind: str,
    attachments_dir: Path,
    voice_dir: Path,
    previous_snapshot_dir: Path | None = None,
) -> list[dict]:
    normalized: list[dict] = []
    for sequence, raw in enumerate(messages or [], start=1):
        if not isinstance(raw, dict):
            continue
        message = json.loads(json.dumps(raw, ensure_ascii=False))
        message["archiveConversationId"] = conversation_id
        message["archiveConversationKind"] = conversation_kind
        message["archiveSequence"] = sequence
        audio_path = (_copy_archived_attachment(message.get("audioUrl", ""), previous_snapshot_dir, attachments_dir)
                      or _copy_voice_attachment(message.get("audioUrl", ""), voice_dir, attachments_dir))
        if audio_path:
            message["archiveAudioPath"] = audio_path
        image_path = _copy_archived_attachment(message.get("imageUrl", ""), previous_snapshot_dir, attachments_dir) or _extract_image_attachment(
            message.get("imageUrl", ""), attachments_dir, conversation_id, sequence
        )
        if image_path:
            message["archiveImagePath"] = image_path
            message.pop("imageUrl", None)
        normalized.append(message)
    return normalized


def _file_hashes(snapshot_dir: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(snapshot_dir.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            result[path.relative_to(snapshot_dir).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


@_serialized_role_write
def archive_role_snapshot(
    *,
    character: object,
    frontend_profile: dict,
    relationship: dict,
    memory: str,
    intimacy: float | None,
    started_at: int | float | None,
    current_messages: list,
    archived_sessions: list,
    build_id: str,
    web_dir: str | os.PathLike[str],
    voice_dir: str | os.PathLike[str],
    memory_context: str = "",
    companion_context: dict | None = None,
    index_metadata: dict | None = None,
    imported_sessions: list | None = None,
    extensions: dict | None = None,
) -> dict:
    character_record = _character_record(character)
    character_id = _safe_character_id(character_record.get("id", ""))
    root = role_library_root()
    role_dir = root / "roles" / character_id
    snapshots_dir = role_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    previous_snapshot_dir = (
        _current_snapshot_dir(character_id)
        if (role_dir / "current.json").is_file()
        else None
    )

    now = datetime.now(timezone.utc)
    snapshot_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    temp_dir = Path(tempfile.mkdtemp(prefix=".tmp-", dir=snapshots_dir))
    final_dir = snapshots_dir / snapshot_id
    try:
        frontend_copy = _canonicalize_profile_assets(
            json.loads(json.dumps(frontend_profile or {}, ensure_ascii=False))
        )
        frontend_copy, embedded_assets = _store_embedded_profile_images(
            frontend_copy,
            temp_dir,
        )
        backend_profile = {
            key: value
            for key, value in character_record.items()
            if key not in {"core_memory", "system_prompt"}
        }
        _write_json(temp_dir / "profile.json", {
            "schemaVersion": SCHEMA_VERSION,
            "backend": backend_profile,
            "frontend": frontend_copy,
        })
        # Advanced role content is private data, never a bundled resource.
        if extensions is not None:
            _write_json(temp_dir / "extensions.json", extensions)
        elif previous_snapshot_dir is not None:
            previous_extensions = previous_snapshot_dir / "extensions.json"
            if previous_extensions.is_file():
                shutil.copy2(previous_extensions, temp_dir / "extensions.json")
        _write_json(temp_dir / "relationship.json", relationship or {})
        (temp_dir / "core.md").write_text(
            str(character_record.get("core_memory") or "").strip() + "\n",
            encoding="utf-8",
        )
        (temp_dir / "runtime-prompt.md").write_text(
            str(character_record.get("system_prompt") or "").strip() + "\n",
            encoding="utf-8",
        )
        (temp_dir / "memory.md").write_text(str(memory or "").strip() + "\n", encoding="utf-8")
        try:
            context_payload = json.loads(str(memory_context or "{}"))
        except json.JSONDecodeError:
            context_payload = {}
        _write_json(temp_dir / "memory-context.json", context_payload if isinstance(context_payload, dict) else {})
        _write_json(
            temp_dir / "companion-context.json",
            companion_context if isinstance(companion_context, dict) else {},
        )

        attachments_dir = temp_dir / "attachments"
        voice_path = Path(voice_dir)
        conversations: list[dict] = []
        all_messages: list[dict] = []
        for index, session in enumerate(archived_sessions or [], start=1):
            if not isinstance(session, dict):
                continue
            conversation_id = f"archived-{index:04d}"
            messages = _normalize_messages(
                session.get("messages") or [], conversation_id, "archived", attachments_dir, voice_path, previous_snapshot_dir
            )
            conversations.append({
                "id": conversation_id,
                "kind": "archived",
                "startTs": session.get("startTs"),
                "endTs": session.get("endTs"),
                "messageCount": len(messages),
            })
            all_messages.extend(messages)

        current_id = "current"
        current = _normalize_messages(
            current_messages or [], current_id, "current", attachments_dir, voice_path, previous_snapshot_dir
        )
        conversations.append({
            "id": current_id,
            "kind": "current",
            "startTs": current[0].get("ts") if current else started_at,
            "endTs": current[-1].get("ts") if current else None,
            "messageCount": len(current),
        })
        all_messages.extend(current)

        _write_json(temp_dir / "conversations.json", conversations)
        with (temp_dir / "chat-history.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for message in all_messages:
                handle.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")

        # Imported source material is independent of the app's live chat state.
        # A normal archive refresh must preserve it, including on profile edits.
        if imported_sessions is not None:
            _write_json(temp_dir / "imported-sessions.json", imported_sessions)
            with (temp_dir / "imported-history.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
                for index, session in enumerate(imported_sessions):
                    for message in session.get("messages", []):
                        handle.write(json.dumps({**message,
                            "archiveConversationId": f"imported-{index}",
                            "archiveConversationKind": "imported",
                        }, ensure_ascii=False, separators=(",", ":")) + "\n")
        elif previous_snapshot_dir is not None:
            for filename in ("imported-sessions.json", "imported-history.jsonl"):
                previous_file = previous_snapshot_dir / filename
                if previous_file.is_file():
                    shutil.copy2(previous_file, temp_dir / filename)

        copied_assets = sorted(set(
            embedded_assets
            + _copy_profile_assets(frontend_copy, Path(web_dir), temp_dir, previous_snapshot_dir)
        ))
        imported_count = (
            sum(len(session.get("messages", [])) for session in imported_sessions)
            if imported_sessions is not None else
            _read_snapshot_json(previous_snapshot_dir, "manifest.json", {}).get("importedMessageCount", 0)
            if previous_snapshot_dir is not None else 0
        )
        manifest = {
            "schemaVersion": SCHEMA_VERSION,
            "snapshotId": snapshot_id,
            "characterId": character_id,
            "name": str(character_record.get("name") or character_id),
            "createdAt": now.isoformat(),
            "sourceBuildId": str(build_id or "unknown"),
            "startedAt": started_at,
            "intimacy": intimacy,
            "companionContextVersion": (
                companion_context.get("version")
                if isinstance(companion_context, dict)
                else None
            ),
            "conversationCount": len(conversations),
            "messageCount": len(all_messages),
            "importedMessageCount": imported_count,
            "archivedConversationCount": max(0, len(conversations) - 1),
            "copiedAssets": copied_assets,
            "files": _file_hashes(temp_dir),
        }
        _write_json(temp_dir / "manifest.json", manifest)
        os.replace(temp_dir, final_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    index_path = root / "index.json"
    index = _read_json(index_path, {"schemaVersion": SCHEMA_VERSION, "roles": {}})
    if not isinstance(index, dict):
        raise RoleArchiveError("Invalid role library index")
    roles = index.setdefault("roles", {})
    if not isinstance(roles, dict):
        raise RoleArchiveError("Invalid role library role index")
    previous_record = roles.get(character_id)
    roles[character_id] = {
        **(previous_record if isinstance(previous_record, dict) else {}),
        "name": manifest["name"],
        "currentSnapshotId": snapshot_id,
        "updatedAt": now.isoformat(),
        "messageCount": manifest["messageCount"],
        "conversationCount": manifest["conversationCount"],
        **(index_metadata or {}),
    }
    index["schemaVersion"] = SCHEMA_VERSION
    index["updatedAt"] = now.isoformat()
    current_pointer = {
        "schemaVersion": SCHEMA_VERSION,
        "characterId": character_id,
        "snapshotId": snapshot_id,
        "updatedAt": now.isoformat(),
    }
    pointer_path = role_dir / "current.json"
    old_pointer = _read_json(pointer_path, None)
    try:
        _atomic_write_json(pointer_path, current_pointer)
        _atomic_write_json(index_path, index)
    except Exception:
        # A failed index update must not switch a role to an unindexed snapshot.
        try:
            if old_pointer is None:
                pointer_path.unlink(missing_ok=True)
            else:
                _atomic_write_json(pointer_path, old_pointer)
        except OSError:
            pass
        raise

    return {
        "ok": True,
        "characterId": character_id,
        "snapshotId": snapshot_id,
        "path": str(final_dir),
        "messageCount": manifest["messageCount"],
        "conversationCount": manifest["conversationCount"],
        "assetCount": len(manifest["copiedAssets"]),
    }


def repair_current_snapshot_assets(
    character_id: str,
    *,
    web_dir: str | os.PathLike[str],
    build_id: str,
) -> dict:
    """Clone the current snapshot and restore every referenced frontend asset."""
    character_id = _safe_character_id(character_id)
    old_snapshot_dir = _current_snapshot_dir(character_id)
    old_snapshot_id = old_snapshot_dir.name
    profile = _read_snapshot_json(old_snapshot_dir, "profile.json", {})
    manifest = _read_snapshot_json(old_snapshot_dir, "manifest.json", {})
    if not isinstance(profile, dict) or not isinstance(manifest, dict):
        raise RoleArchiveError("Invalid role snapshot metadata")
    frontend = profile.get("frontend")
    if not isinstance(frontend, dict):
        raise RoleArchiveError("Invalid role snapshot profile")

    canonical_frontend = _canonicalize_profile_assets(frontend)
    expected_assets = sorted(set(_asset_references(canonical_frontend)))
    root = role_library_root()
    role_dir = root / "roles" / character_id
    snapshots_dir = role_dir / "snapshots"
    now = datetime.now(timezone.utc)
    snapshot_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    temp_dir = Path(tempfile.mkdtemp(prefix=".tmp-repair-", dir=snapshots_dir))
    final_dir = snapshots_dir / snapshot_id
    try:
        shutil.copytree(old_snapshot_dir, temp_dir, dirs_exist_ok=True)
        repaired_profile = {
            **profile,
            "schemaVersion": SCHEMA_VERSION,
            "frontend": canonical_frontend,
        }
        _write_json(temp_dir / "profile.json", repaired_profile)
        copied_assets = _copy_profile_assets(canonical_frontend, Path(web_dir), temp_dir)
        if copied_assets != expected_assets:
            missing_count = len(set(expected_assets) - set(copied_assets))
            raise RoleArchiveError(
                f"Cannot repair role snapshot assets: {missing_count} source files are missing"
            )
        repaired_manifest = {
            **manifest,
            "schemaVersion": SCHEMA_VERSION,
            "snapshotId": snapshot_id,
            "characterId": character_id,
            "createdAt": now.isoformat(),
            "sourceBuildId": str(build_id or "unknown"),
            "repairedFromSnapshotId": old_snapshot_id,
            "copiedAssets": copied_assets,
        }
        repaired_manifest["files"] = _file_hashes(temp_dir)
        _write_json(temp_dir / "manifest.json", repaired_manifest)
        os.replace(temp_dir, final_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    _atomic_write_json(role_dir / "current.json", {
        "schemaVersion": SCHEMA_VERSION,
        "characterId": character_id,
        "snapshotId": snapshot_id,
        "updatedAt": now.isoformat(),
    })

    index_path = root / "index.json"
    index = _read_json(index_path, {"schemaVersion": SCHEMA_VERSION, "roles": {}})
    if not isinstance(index, dict):
        raise RoleArchiveError("Invalid role library index")
    roles = index.setdefault("roles", {})
    if not isinstance(roles, dict):
        raise RoleArchiveError("Invalid role library role index")
    previous = roles.get(character_id)
    roles[character_id] = {
        **(previous if isinstance(previous, dict) else {}),
        "name": str(repaired_manifest.get("name") or character_id),
        "currentSnapshotId": snapshot_id,
        "updatedAt": now.isoformat(),
        "messageCount": repaired_manifest.get("messageCount", 0),
        "conversationCount": repaired_manifest.get("conversationCount", 0),
    }
    index["schemaVersion"] = SCHEMA_VERSION
    index["updatedAt"] = now.isoformat()
    _atomic_write_json(index_path, index)

    return {
        "ok": True,
        "characterId": character_id,
        "snapshotId": snapshot_id,
        "repairedFromSnapshotId": old_snapshot_id,
        "path": str(final_dir),
        "assetCount": len(copied_assets),
    }


def list_role_library() -> dict:
    root = role_library_root()
    index = _read_json(root / "index.json", {"schemaVersion": SCHEMA_VERSION, "roles": {}})
    return {"root": str(root), **index}


def get_custom_role_record(character_id: str) -> dict:
    """Return metadata only for a role created through the in-app editor."""
    character_id = _safe_character_id(character_id)
    indexed = list_role_library().get("roles")
    record = indexed.get(character_id) if isinstance(indexed, dict) else None
    if not isinstance(record, dict) or record.get("origin") != "custom":
        raise RoleArchiveError("Custom role does not exist")
    return record


@_serialized_role_write
def set_custom_role_disabled(character_id: str, disabled: bool) -> dict:
    character_id = _safe_character_id(character_id)
    root = role_library_root()
    index_path = root / "index.json"
    index = _read_json(index_path, {})
    roles = index.get("roles") if isinstance(index, dict) else None
    record = roles.get(character_id) if isinstance(roles, dict) else None
    if not isinstance(record, dict) or record.get("origin") != "custom":
        raise RoleArchiveError("Custom role does not exist")
    updated = {**record, "disabled": bool(disabled), "updatedAt": datetime.now(timezone.utc).isoformat()}
    roles[character_id] = updated
    index["updatedAt"] = updated["updatedAt"]
    _atomic_write_json(index_path, index)
    return updated


def _current_snapshot_dir(character_id: str) -> Path:
    character_id = _safe_character_id(character_id)
    role_dir = role_library_root() / "roles" / character_id
    pointer = _read_json(role_dir / "current.json", {})
    if not isinstance(pointer, dict):
        raise RoleArchiveError("Invalid current role snapshot pointer")
    snapshot_id = str(pointer.get("snapshotId") or "").strip()
    if not _SAFE_SNAPSHOT_ID.fullmatch(snapshot_id):
        raise RoleArchiveError("Invalid current role snapshot id")
    snapshots_dir = (role_dir / "snapshots").resolve()
    snapshot_dir = (snapshots_dir / snapshot_id).resolve()
    try:
        snapshot_dir.relative_to(snapshots_dir)
    except ValueError as exc:
        raise RoleArchiveError("Invalid current role snapshot path") from exc
    if not snapshot_dir.is_dir():
        raise RoleArchiveError("Current role snapshot is missing")
    return snapshot_dir


def _read_snapshot_json(snapshot_dir: Path, filename: str, default: object) -> object:
    value = _read_json(snapshot_dir / filename, default)
    return value


def _read_snapshot_text(snapshot_dir: Path, filename: str) -> str:
    path = snapshot_dir / filename
    try:
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    except OSError as exc:
        raise RoleArchiveError(f"Cannot read role snapshot file: {filename}") from exc


def _runtime_file_url(character_id: str, relative_path: str) -> str:
    clean = str(relative_path or "").replace("\\", "/").lstrip("/")
    return f"/api/role-library/{character_id}/files/{clean}"


def _rewrite_profile_assets(value: object, character_id: str) -> object:
    if isinstance(value, str):
        normalized = value.replace("\\", "/").lstrip("./")
        if normalized.startswith("assets/"):
            return _runtime_file_url(character_id, normalized)
        return value
    if isinstance(value, list):
        return [_rewrite_profile_assets(item, character_id) for item in value]
    if isinstance(value, dict):
        return {
            key: _rewrite_profile_assets(item, character_id)
            for key, item in value.items()
        }
    return value


def _restore_message(message: dict, character_id: str) -> dict:
    restored = json.loads(json.dumps(message, ensure_ascii=False))
    audio_path = str(restored.get("archiveAudioPath") or "").strip()
    image_path = str(restored.get("archiveImagePath") or "").strip()
    if audio_path:
        restored["audioUrl"] = _runtime_file_url(character_id, audio_path)
    if image_path:
        restored["imageUrl"] = _runtime_file_url(character_id, image_path)
    for key in ("archiveConversationId", "archiveConversationKind", "archiveSequence",
                "archiveAudioPath", "archiveImagePath"):
        restored.pop(key, None)
    return restored


def load_role_snapshot(character_id: str, *, include_state: bool = True, include_imported: bool = True) -> dict:
    """Load one immutable role snapshot into a runtime-safe representation."""
    character_id = _safe_character_id(character_id)
    snapshot_dir = _current_snapshot_dir(character_id)
    manifest = _read_snapshot_json(snapshot_dir, "manifest.json", {})
    profile = _read_snapshot_json(snapshot_dir, "profile.json", {})
    if not isinstance(manifest, dict) or not isinstance(profile, dict):
        raise RoleArchiveError("Invalid role snapshot metadata")
    backend = profile.get("backend")
    frontend = profile.get("frontend")
    if not isinstance(backend, dict) or not isinstance(frontend, dict):
        raise RoleArchiveError("Invalid role snapshot profile")
    if str(backend.get("id") or "") != character_id:
        raise RoleArchiveError("Role snapshot id does not match its folder")

    snapshot_id = str(manifest.get("snapshotId") or snapshot_dir.name)
    result = {
        "id": character_id,
        "snapshotId": snapshot_id,
        "backend": {
            **backend,
            "system_prompt": _read_snapshot_text(snapshot_dir, "runtime-prompt.md"),
            "core_memory": _read_snapshot_text(snapshot_dir, "core.md"),
        },
        "frontend": _rewrite_profile_assets(frontend, character_id),
        "extensions": _read_snapshot_json(snapshot_dir, "extensions.json", {}),
        "importedMessageCount": manifest.get("importedMessageCount", 0),
    }
    if not include_state:
        return result

    relationship = _read_snapshot_json(snapshot_dir, "relationship.json", {})
    conversations = _read_snapshot_json(snapshot_dir, "conversations.json", [])
    messages_by_conversation: dict[str, list[dict]] = {}
    history_path = snapshot_dir / "chat-history.jsonl"
    if history_path.is_file():
        try:
            with history_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    raw = json.loads(line)
                    if not isinstance(raw, dict):
                        continue
                    conversation_id = str(raw.get("archiveConversationId") or "")
                    messages_by_conversation.setdefault(conversation_id, []).append(
                        _restore_message(raw, character_id)
                    )
        except (OSError, json.JSONDecodeError) as exc:
            raise RoleArchiveError("Cannot read role chat history") from exc

    current_messages = messages_by_conversation.get("current", [])
    archived_sessions: list[dict] = []
    if isinstance(conversations, list):
        for conversation in conversations:
            if not isinstance(conversation, dict) or conversation.get("kind") != "archived":
                continue
            conversation_id = str(conversation.get("id") or "")
            archived_sessions.append({
                "startTs": conversation.get("startTs"),
                "endTs": conversation.get("endTs"),
                "messages": messages_by_conversation.get(conversation_id, []),
            })

    result["state"] = {
            "relationship": relationship if isinstance(relationship, dict) else {},
            "memory": _read_snapshot_text(snapshot_dir, "memory.md"),
            "memoryContext": _read_snapshot_json(snapshot_dir, "memory-context.json", {}),
            "companionContext": _read_snapshot_json(snapshot_dir, "companion-context.json", {}),
            "intimacy": manifest.get("intimacy"),
            "startedAt": manifest.get("startedAt"),
            "currentMessages": current_messages,
            "archivedSessions": archived_sessions,
            "importedSessions": (
                _read_snapshot_json(snapshot_dir, "imported-sessions.json", [])
                if include_imported else []
            ),
    }
    return result


def load_role_library_runtime(*, include_state: bool = True) -> dict:
    """Return every readable current role snapshot; one broken role cannot block the app."""
    index = list_role_library()
    indexed_roles = index.get("roles") if isinstance(index, dict) else {}
    roles: list[dict] = []
    issues: list[dict] = []
    if isinstance(indexed_roles, dict):
        for character_id, record in indexed_roles.items():
            if isinstance(record, dict) and record.get("origin") == "custom" and record.get("disabled") is True:
                continue
            try:
                roles.append(load_role_snapshot(character_id, include_state=include_state, include_imported=False))
            except RoleArchiveError as exc:
                issues.append({"characterId": str(character_id), "error": str(exc)})
    return {
        "schemaVersion": SCHEMA_VERSION,
        "root": str(role_library_root()),
        "roles": roles,
        "issues": issues,
    }


def apply_role_library_to_roster(
    roster: dict,
    *,
    preserve_existing: bool = False,
) -> dict:
    """Load archived roles without silently replacing newer built-in definitions.

    ``preserve_existing`` is used by the normal bundled application: built-in
    backend definitions stay code-owned while the frontend still restores
    archived profile assets and relationship state through the runtime APIs.
    Archive-only builds can pass an empty roster (or keep the default
    ``False`` behavior) and continue to reconstruct every character locally.
    """
    from characters import Character

    try:
        runtime = load_role_library_runtime(include_state=False)
    except RoleArchiveError as exc:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "root": str(role_library_root()),
            "roles": [],
            "issues": [{"characterId": None, "error": str(exc)}],
            "loadedCharacterIds": [],
        }
    loaded: list[str] = []
    preserved: list[str] = []
    for role in runtime["roles"]:
        raw = role.get("backend")
        if not isinstance(raw, dict):
            continue
        character_id = str(raw.get("id") or "")
        fallback = roster.get(character_id)
        if fallback is not None and preserve_existing:
            preserved.append(character_id)
            continue

        def pick(name: str, default):
            value = raw.get(name)
            if value is not None:
                return value
            return getattr(fallback, name, default) if fallback is not None else default

        try:
            roster[character_id] = Character(
                id=character_id,
                name=str(pick("name", character_id)),
                en=str(pick("en", character_id)),
                persona=str(pick("persona", "")),
                tags=list(pick("tags", [])),
                cat=str(pick("cat", "自建")),
                greet=str(pick("greet", "")),
                mood=str(pick("mood", "")),
                replies=list(pick("replies", [])),
                system_prompt=str(pick("system_prompt", "")),
                core_memory=str(pick("core_memory", "")),
                public_background=tuple(pick("public_background", [])),
                intimacy=pick("intimacy", 5),
                motif=pick("motif", None),
            )
            loaded.append(character_id)
        except (TypeError, ValueError) as exc:
            runtime["issues"].append({"characterId": character_id, "error": str(exc)})
    runtime["loadedCharacterIds"] = loaded
    runtime["preservedCharacterIds"] = preserved
    return runtime


def resolve_role_snapshot_file(character_id: str, relative_path: str) -> Path:
    """Resolve only copied public assets/attachments from the current snapshot."""
    snapshot_dir = _current_snapshot_dir(character_id)
    normalized = str(relative_path or "").replace("\\", "/").lstrip("/")
    if not (normalized.startswith("assets/") or normalized.startswith("attachments/")):
        raise RoleArchiveError("Role snapshot file is not public")
    target = (snapshot_dir / normalized).resolve()
    try:
        target.relative_to(snapshot_dir.resolve())
    except ValueError as exc:
        raise RoleArchiveError("Invalid role snapshot file path") from exc
    if not target.is_file():
        raise RoleArchiveError("Role snapshot file is missing")
    return target
