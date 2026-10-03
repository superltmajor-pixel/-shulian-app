"""角色档案库 API。"""

import secrets
import json
from dataclasses import replace
from characters import Character

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from state_store import state_snapshot

from role_archive import (
    RoleArchiveError,
    ROLE_WRITE_LOCK,
    archive_role_snapshot,
    get_custom_role_record,
    list_role_library,
    load_role_library_runtime,
    load_role_snapshot,
    resolve_role_snapshot_file,
    role_library_root,
    set_custom_role_disabled,
)

from ..domain import RoleLibraryContext
from ..schemas import RoleArchiveRequest
from ..security import require_local_write
from ..services.custom_role_service import (
    build_custom_character,
    build_custom_contexts,
    validate_custom_profile,
    validate_imported_sessions,
)
from ..services.role_package_service import (
    RolePackageError,
    export_custom_role_package,
    import_custom_role_package,
)


_ROLE_WRITE_LOCK = ROLE_WRITE_LOCK
_MAX_ROLE_REQUEST_BYTES = 64 * 1024 * 1024
_MAX_PACKAGE_BYTES = 32 * 1024 * 1024


def _custom_payload(body: dict, character_id: str | None) -> tuple[dict, list[dict] | None, str | None]:
    if set(body) - {"profile", "archived_sessions", "memory"}:
        raise ValueError("角色资料包含不支持的字段")
    profile = validate_custom_profile(body.get("profile"), character_id=character_id)
    sessions = (
        validate_imported_sessions(body["archived_sessions"])
        if "archived_sessions" in body else None
    )
    memory = body.get("memory")
    if memory is not None and (not isinstance(memory, str) or len(memory) > 200_000):
        raise ValueError("角色记忆格式无效或内容过长")
    return profile, sessions, memory


def _editable_sessions(sessions: list[dict]) -> list[dict]:
    return [
        {
            "startTs": session.get("startTs"),
            "endTs": session.get("endTs"),
            "messages": [
                {
                    "from": "me" if message.get("from") == "me" else "them",
                    "text": message.get("text", ""),
                    **({"ts": message["ts"]} if "ts" in message else {}),
                }
                for message in session.get("messages", [])
                if message.get("from") in {"me", "her"} and message.get("text")
            ],
        }
        for session in sessions
    ]


def _custom_role_or_404(character_id: str) -> dict:
    try:
        return get_custom_role_record(character_id)
    except RoleArchiveError as exc:
        raise HTTPException(status_code=404, detail="自建角色不存在") from exc


def _archive_custom_role(context: RoleLibraryContext, character_id: str, profile: dict,
                         sessions: list[dict], memory: str, *, disabled: bool = False,
                         previous_state: dict | None = None) -> dict:
    state = previous_state or {}
    character = build_custom_character(profile, character_id=character_id)
    previous_profile = (load_role_snapshot(character_id, include_state=False)["frontend"]
                        if previous_state is not None else None)
    if previous_profile is not None:
        previous = load_role_snapshot(character_id, include_state=False)
        if previous.get("extensions"):
            original = Character(**previous["backend"])
            # Preserve the advanced prompt, biography and examples on ordinary
            # image/profile edits. Apply only fields the user actually changed.
            changed = {key: profile[key] for key in (
                "name", "en", "persona", "tags", "cat", "greet", "mood"
            ) if profile.get(key) != previous_profile.get(key)}
            if any(profile.get(key) != previous_profile.get(key, "") for key in (
                "name", "en", "persona", "personality", "speakingStyle", "relationship", "profileIntro"
            )):
                changed["system_prompt"] = character.system_prompt
            if profile.get("profileIntro", "") != previous_profile.get("profileIntro", ""):
                changed["core_memory"] = character.core_memory
            if any(profile.get(key, "") != previous_profile.get(key, "")
                   for key in ("personality", "relationship")):
                changed["public_background"] = character.public_background
            if profile.get("relationshipLevel") != previous_profile.get("relationshipLevel"):
                changed["intimacy"] = character.intimacy
            character = replace(original, **changed)
    memory_context, companion_context = build_custom_contexts(
        profile, memory, character_id=character_id, previous_state=previous_state,
        previous_profile=previous_profile, previous_memory=state.get("memory", ""),
    )
    frontend = {
        "hue": 275,
        "forms": [],
        **(previous_profile or {}),
        **profile,
        "id": character_id,
        "origin": "custom",
    }
    archived = archive_role_snapshot(
        character=character,
        frontend_profile=frontend,
        relationship=state.get("relationship") or {},
        memory=memory,
        memory_context=json.dumps(memory_context, ensure_ascii=False),
        companion_context=companion_context,
        intimacy=companion_context["relationship"]["level"],
        started_at=state.get("startedAt"),
        current_messages=state.get("currentMessages") or [],
        archived_sessions=state.get("archivedSessions") or [],
        imported_sessions=sessions,
        build_id=context.build_id,
        web_dir=context.web_dir,
        voice_dir=context.voice_dir,
        index_metadata={"origin": "custom", "disabled": disabled},
    )
    if not disabled:
        context.roster[character_id] = character
    return {"ok": True, "characterId": character_id, "snapshotId": archived["snapshotId"],
            "memoryContext": memory_context, "companionContext": companion_context}


def create_role_library_router(context: RoleLibraryContext) -> APIRouter:
    router = APIRouter()

    @router.get("/api/role-library")
    def role_library_index():
        return list_role_library()

    @router.get("/api/role-library/runtime")
    def role_library_runtime():
        runtime = load_role_library_runtime(include_state=False)
        return {
            "schemaVersion": runtime["schemaVersion"],
            "roles": [
                {
                    "id": role["id"],
                    "snapshotId": role["snapshotId"],
                    "frontend": role["frontend"],
                }
                for role in runtime["roles"]
            ],
            "issues": runtime["issues"],
        }

    @router.get("/api/role-library/runtime/state")
    def role_library_runtime_state():
        runtime = load_role_library_runtime(include_state=True)
        return {
            "schemaVersion": runtime["schemaVersion"],
            "roles": [
                {
                    "id": role["id"],
                    "snapshotId": role["snapshotId"],
                    "state": role["state"],
                    "origin": role["frontend"].get("origin"),
                }
                for role in runtime["roles"]
            ],
            "issues": runtime["issues"],
        }

    @router.get("/api/role-library/roles")
    def list_custom_roles(request: Request):
        require_local_write(request)
        indexed = list_role_library().get("roles", {})
        roles = []
        if isinstance(indexed, dict):
            for character_id, record in indexed.items():
                if not isinstance(record, dict) or record.get("origin") != "custom":
                    continue
                entry = {
                    "id": character_id,
                    "name": record.get("name", character_id),
                    "disabled": bool(record.get("disabled")),
                    "snapshotId": record.get("currentSnapshotId"),
                }
                try:
                    role = load_role_snapshot(character_id, include_state=False)
                    entry["img"] = role["frontend"].get("img", "")
                    entry["face"] = role["frontend"].get("face", "")
                except RoleArchiveError:
                    entry["error"] = "角色档案读取失败"
                roles.append(entry)
        return {"roles": roles}

    @router.post("/api/role-library/roles")
    async def create_custom_role(request: Request, body: dict):
        require_local_write(request)
        if len(await request.body()) > _MAX_ROLE_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="角色资料过大")
        try:
            profile, sessions, memory = _custom_payload(body, None)
            with _ROLE_WRITE_LOCK:
                indexed = list_role_library().get("roles", {})
                while True:
                    character_id = f"custom_{secrets.token_hex(8)}"
                    if (character_id not in context.roster
                            and character_id not in indexed
                            and not (role_library_root() / "roles" / character_id).exists()):
                        break
                return _archive_custom_role(context, character_id, profile, sessions or [], memory or "")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RoleArchiveError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail="角色保存失败") from exc

    @router.get("/api/role-library/roles/{character_id}")
    def get_custom_role(character_id: str, request: Request, include_history: bool = True):
        require_local_write(request)
        record = _custom_role_or_404(character_id)
        try:
            role = load_role_snapshot(character_id, include_imported=include_history)
        except RoleArchiveError as exc:
            raise HTTPException(status_code=500, detail="角色档案读取失败") from exc
        frontend = role["frontend"]
        return {
            "id": character_id,
            "profile": {key: frontend[key] for key in (
                "name", "en", "persona", "tags", "cat", "greet", "mood",
                "profileIntro", "personality", "speakingStyle", "relationship",
                "img", "face", "imgPos", "facePos",
                "relationshipLevel",
            ) if key in frontend},
            "archived_sessions": _editable_sessions(role["state"]["importedSessions"]),
            "importedMessageCount": role["importedMessageCount"],
            "memory": role["state"]["memory"],
            "disabled": bool(record.get("disabled")),
            "snapshotId": role["snapshotId"],
        }

    @router.put("/api/role-library/roles/{character_id}")
    async def update_custom_role(character_id: str, request: Request, body: dict):
        require_local_write(request)
        if len(await request.body()) > _MAX_ROLE_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="角色资料过大")
        _custom_role_or_404(character_id)
        try:
            profile, sessions, memory = _custom_payload(body, character_id)
            with _ROLE_WRITE_LOCK:
                previous = load_role_snapshot(character_id)
                live = state_snapshot([f"sl_memory_context_{character_id}", f"sl_companion_context_{character_id}"])["data"]
                for prefix, key in (("sl_memory_context_", "memoryContext"), ("sl_companion_context_", "companionContext")):
                    raw = live.get(prefix + character_id)
                    if raw is not None:
                        try:
                            parsed = json.loads(raw)
                        except ValueError:
                            continue
                        if isinstance(parsed, dict):
                            previous["state"][key] = parsed
                if sessions is None:
                    sessions = previous["state"]["importedSessions"]
                if memory is None:
                    memory = previous["state"]["memory"]
                disabled = bool(get_custom_role_record(character_id).get("disabled"))
                result = _archive_custom_role(
                    context, character_id, profile, sessions, memory,
                    disabled=disabled, previous_state=previous["state"],
                )
                return result
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RoleArchiveError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail="角色保存失败") from exc

    @router.post("/api/role-library/roles/{character_id}/disable")
    def disable_custom_role(character_id: str, request: Request):
        require_local_write(request)
        with _ROLE_WRITE_LOCK:
            _custom_role_or_404(character_id)
            try:
                record = set_custom_role_disabled(character_id, True)
            except OSError as exc:
                raise HTTPException(status_code=500, detail="角色状态保存失败") from exc
            context.roster.pop(character_id, None)
        return {"ok": True, "characterId": character_id, "disabled": record["disabled"]}

    @router.post("/api/role-library/roles/{character_id}/restore")
    def restore_custom_role(character_id: str, request: Request):
        require_local_write(request)
        with _ROLE_WRITE_LOCK:
            _custom_role_or_404(character_id)
            try:
                role = load_role_snapshot(character_id, include_state=False)
                character = Character(**role["backend"])
                record = set_custom_role_disabled(character_id, False)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except RoleArchiveError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except OSError as exc:
                raise HTTPException(status_code=500, detail="角色状态保存失败") from exc
            context.roster[character_id] = character
        return {"ok": True, "characterId": character_id, "disabled": record["disabled"]}

    @router.get("/api/role-library/roles/{character_id}/export")
    def export_custom_role(character_id: str, request: Request):
        require_local_write(request)
        _custom_role_or_404(character_id)
        try:
            values = state_snapshot(["sl_threads", "sl_sessions", f"sl_memory_{character_id}"])["data"]
            live_state = {}
            for key, target in (("sl_threads", "currentMessages"), ("sl_sessions", "archivedSessions")):
                if key in values:
                    entries = json.loads(values[key])
                    if isinstance(entries, dict) and character_id in entries:
                        live_state[target] = entries[character_id]
            memory_key = f"sl_memory_{character_id}"
            if memory_key in values:
                live_state["memory"] = values[memory_key]
            package = export_custom_role_package(character_id, live_state=live_state)
        except (RolePackageError, RoleArchiveError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(
            content=package,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{character_id}.zip"'},
        )

    @router.post("/api/role-library/import/inspect")
    async def inspect_custom_role_package(request: Request):
        require_local_write(request)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/zip":
            raise HTTPException(status_code=415, detail="仅支持 ZIP 角色包")
        payload = await request.body()
        if len(payload) > _MAX_PACKAGE_BYTES:
            raise HTTPException(status_code=413, detail="角色包不能超过 32 MiB")
        try:
            return import_custom_role_package(payload)
        except RolePackageError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/api/role-library/{character_id}/files/{relative_path:path}")
    def role_library_file(character_id: str, relative_path: str):
        try:
            path = resolve_role_snapshot_file(character_id, relative_path)
        except RoleArchiveError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path)

    @router.post("/api/role-library/{character_id}/snapshots")
    def create_role_library_snapshot(
        character_id: str,
        req: RoleArchiveRequest,
        request: Request,
    ):
        require_local_write(request)
        character = context.roster.get(character_id)
        if not character:
            raise HTTPException(status_code=404, detail="角色不存在")
        if req.companion_context is not None and req.companion_context.character_id != character_id:
            raise HTTPException(status_code=422, detail="角色上下文与归档角色不匹配")
        try:
            frontend_profile = req.frontend_profile
            record = list_role_library().get("roles", {}).get(character_id, {})
            if record.get("origin") == "custom":
                frontend_profile = load_role_snapshot(character_id, include_state=False)["frontend"]
            return archive_role_snapshot(
                character=character,
                frontend_profile=frontend_profile,
                relationship=req.relationship,
                memory=req.memory,
                memory_context=req.memory_context,
                intimacy=req.intimacy,
                companion_context=(
                    req.companion_context.model_dump(mode="json")
                    if req.companion_context is not None
                    else None
                ),
                started_at=req.started_at,
                current_messages=req.current_messages,
                archived_sessions=req.archived_sessions,
                build_id=context.build_id,
                web_dir=context.web_dir,
                voice_dir=context.voice_dir,
            )
        except RoleArchiveError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail="角色档案写入失败") from exc

    return router
