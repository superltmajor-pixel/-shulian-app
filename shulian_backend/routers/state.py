"""SQLite 状态 API。"""

import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from ..domain.errors import InvalidStateDataError, StateServiceError
from ..schemas import StateMutationRequest, StateReplaceRequest
from ..security import require_local_write
from ..services.scene_status_service import clear_all_scenes, reload_persisted_scenes
from ..services.state_service import state_service


router = APIRouter()


def _state_service_http_error(exc: StateServiceError) -> HTTPException:
    if isinstance(exc, InvalidStateDataError):
        return HTTPException(
            status_code=400,
            detail={"code": "invalid_state", "message": str(exc)},
        )
    return HTTPException(
        status_code=503,
        detail={"code": "state_store_unavailable", "message": "本地数据存储暂不可用"},
    )


@router.get("/api/state")
def get_state():
    """返回 SQLite 主存储，用于恢复浏览器缓存。"""
    try:
        return state_service.snapshot()
    except StateServiceError as exc:
        raise _state_service_http_error(exc) from exc


@router.put("/api/state")
def update_state(req: StateMutationRequest, request: Request):
    """原子写入和删除一批本地状态。"""
    require_local_write(request)
    try:
        result = state_service.mutate(req.items, req.deleted_keys)
        if "sl_scene_overrides" in req.items or "sl_scene_overrides" in req.deleted_keys:
            reload_persisted_scenes()
        return result
    except StateServiceError as exc:
        raise _state_service_http_error(exc) from exc


@router.post("/api/state/import")
def import_state(req: StateReplaceRequest, request: Request):
    """仅在 SQLite 为空时导入旧 localStorage。"""
    require_local_write(request)
    try:
        result = state_service.import_legacy(req.data)
        reload_persisted_scenes()
        return result
    except StateServiceError as exc:
        raise _state_service_http_error(exc) from exc


@router.post("/api/state/replace")
def replace_all_state(req: StateReplaceRequest, request: Request):
    """恢复备份时原子替换全部应用状态。"""
    require_local_write(request)
    try:
        result = state_service.replace(req.data)
        reload_persisted_scenes()
        return result
    except StateServiceError as exc:
        raise _state_service_http_error(exc) from exc


@router.delete("/api/state")
def clear_state(request: Request):
    """原子清空 SQLite 应用状态。"""
    require_local_write(request)
    try:
        result = state_service.clear()
        clear_all_scenes()
        return result
    except StateServiceError as exc:
        raise _state_service_http_error(exc) from exc


@router.get("/api/state/export")
def export_state():
    """用现有 JSON 备份格式导出 SQLite 主存储。"""
    try:
        payload = state_service.export_json()
    except StateServiceError as exc:
        raise _state_service_http_error(exc) from exc
    filename = f"shulian-backup-{time.strftime('%Y%m%d-%H%M%S')}.json"
    return Response(
        content=payload,
        media_type="application/json",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
