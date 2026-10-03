"""健康检查、AI 凭据与诊断 API。"""

import os
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from diagnostics import build_diagnostic_archive, record_metric, runtime_snapshot

from ..domain import AIConfigServiceError, RuntimeContext, StateServiceError
from ..schemas import AIConfigUpdate, AIModelUpdate, DiagnosticEvent
from ..security import require_local_write
from ..services import ai_config_service, tts_service
from ..services.character_bible_service import character_bible_status
from ..services.model_adapter_service import model_adapter_status
from ..services.personality_service import personality_profile_status
from ..services.release_service import release_status
from ..services.state_service import state_service


def _raise_ai_config_error(payload: dict) -> None:
    error = payload.get("error")
    if error in {"invalid_key", "credential_error"}:
        raise HTTPException(
            status_code=401,
            detail={
                "code": error,
                "message": "API Key 无效、已失效或无法读取，请重新输入",
            },
        )
    if error == "network_error":
        raise HTTPException(
            status_code=503,
            detail={
                "code": "network_error",
                "message": "暂时无法连接 AI 服务，请检查网络后重试",
            },
        )
    if error == "model_unavailable":
        raise HTTPException(
            status_code=503,
            detail={
                "code": "model_unavailable",
                "message": "当前配置的 AI 模型不可用",
            },
        )


def create_system_router(context: RuntimeContext) -> APIRouter:
    router = APIRouter()

    def self_check_payload() -> dict:
        env_exists = bool(context.env_path and os.path.exists(context.env_path))
        web_ok = os.path.exists(os.path.join(context.web_dir, "index.html"))
        ai_config = ai_config_service.resolve_ai_config()
        ai_ready = bool(ai_config["ready"])
        provider = tts_service.tts_provider()
        gpt_sovits_base_url_set = bool(
            (
                os.getenv("SHULIAN_FORMAL_GPT_SOVITS_BASE_URL")
                or os.getenv("GPT_SOVITS_BASE_URL")
                or ""
            ).strip()
        )
        tts_ok = provider == "edge" or gpt_sovits_base_url_set
        try:
            storage = state_service.status()
        except StateServiceError:
            storage = {
                "ok": False,
                "engine": "sqlite",
                "schema_version": 0,
                "target_schema_version": 1,
                "revision": 0,
                "item_count": 0,
            }
        active_character_ids = tuple(context.roster.keys())
        character_bibles = character_bible_status(active_character_ids)
        personality_profiles = personality_profile_status(active_character_ids)
        release = release_status(context.resource_dir, context.build_id)
        ok = (
            web_ok
            and ai_ready
            and tts_ok
            and storage["ok"]
            and character_bibles["ok"]
            and personality_profiles["ok"]
            and release["ok"]
        )
        return {
            "ok": ok,
            "backend": {
                "ok": True,
                "mode": "exe" if context.frozen else "source",
                "build_id": context.build_id,
                "data_dir": context.data_dir,
                "resource_dir": context.resource_dir,
                "version": release["version"],
                "channel": release["channel"],
            },
            "env": {
                "ok": env_exists,
                "path": context.env_path,
            },
            "ai": {
                "ok": ai_ready,
                **ai_config,
                **model_adapter_status(),
            },
            "web": {
                "ok": web_ok,
                "path": context.web_dir,
            },
            "tts": {
                "ok": tts_ok,
                "provider": provider,
                "gpt_sovits_base_url_set": gpt_sovits_base_url_set,
                **tts_service.tts_adapter_status(),
            },
            "storage": storage,
            "character_bibles": character_bibles,
            "personality_profiles": personality_profiles,
            "release": release,
        }

    def diagnostic_snapshot() -> dict:
        check = self_check_payload()
        health = {
            "ok": check["ok"],
            "backend": {
                "ok": check["backend"]["ok"],
                "mode": check["backend"]["mode"],
                "build_id": check["backend"]["build_id"],
            },
            "ai": {
                key: check["ai"].get(key)
                for key in ("ok", "configured", "ready", "provider", "model", "error")
            },
            "web": {"ok": check["web"]["ok"]},
            "tts": check["tts"],
            "storage": check["storage"],
            "character_bibles": check["character_bibles"],
            "personality_profiles": check["personality_profiles"],
            "release": check["release"],
            "role_library": {
                "loaded": len(
                    context.role_library_boot.get("loadedCharacterIds", [])
                ),
                "preserved": len(
                    context.role_library_boot.get("preservedCharacterIds", [])
                ),
                "issues": len(context.role_library_boot.get("issues", [])),
            },
        }
        return runtime_snapshot(
            build_id=context.build_id,
            mode="exe" if context.frozen else "source",
            health=health,
        )

    @router.get("/health")
    def health():
        return {
            "status": "数恋后端运行中 ♡",
            "characters": len(context.roster),
        }

    @router.get("/api/ai-config")
    def get_ai_config():
        payload = ai_config_service.resolve_ai_config()
        _raise_ai_config_error(payload)
        return payload

    @router.put("/api/ai-config")
    def update_ai_config(req: AIConfigUpdate, request: Request):
        require_local_write(request)
        try:
            return ai_config_service.update_ai_config(
                req.api_key.get_secret_value(),
                req.remember,
            )
        except AIConfigServiceError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @router.delete("/api/ai-config")
    def remove_ai_config(request: Request):
        require_local_write(request)
        try:
            return ai_config_service.remove_ai_config()
        except AIConfigServiceError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @router.post("/api/ai-config/logout")
    def logout_ai_config(request: Request):
        """Disconnect the active session without deleting a remembered key."""
        require_local_write(request)
        try:
            return ai_config_service.logout_ai_config()
        except AIConfigServiceError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @router.put("/api/ai-config/model")
    def update_ai_model(req: AIModelUpdate, request: Request):
        require_local_write(request)
        try:
            return ai_config_service.update_ai_model(req.model)
        except AIConfigServiceError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @router.get("/api/self-check")
    def self_check():
        return self_check_payload()

    @router.get("/api/diagnostics")
    def diagnostics_status():
        return diagnostic_snapshot()

    @router.post("/api/diagnostics/events")
    def diagnostics_event(req: DiagnosticEvent, request: Request):
        require_local_write(request)
        record_metric(req.name, req.duration_ms, ok=req.ok)
        return {"ok": True}

    @router.get("/api/diagnostics/export")
    def export_diagnostics():
        archive = build_diagnostic_archive(diagnostic_snapshot())
        filename = f"shulian-diagnostics-{time.strftime('%Y%m%d-%H%M%S')}.zip"
        return Response(
            content=archive,
            media_type="application/zip",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    return router
