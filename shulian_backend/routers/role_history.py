"""Paged, read-only access to imported custom-role conversations."""

import json

from fastapi import APIRouter, HTTPException, Query, Request

from role_archive import RoleArchiveError, _current_snapshot_dir, list_role_library
from shulian_backend.security import require_local_write


router = APIRouter()


@router.get("/api/role-library/roles/{character_id}/history")
def custom_role_history(
    character_id: str,
    request: Request,
    cursor: int = Query(default=0, ge=0, le=1_000_000),
    limit: int = Query(default=50, ge=1, le=100),
):
    require_local_write(request)
    try:
        roles = list_role_library().get("roles", {})
        metadata = roles.get(character_id) if isinstance(roles, dict) else None
        if not isinstance(metadata, dict) or metadata.get("origin") != "custom":
            raise HTTPException(status_code=404, detail="自建角色不存在")
        path = _current_snapshot_dir(character_id) / "imported-history.jsonl"
    except RoleArchiveError as exc:
        raise HTTPException(status_code=404, detail="角色聊天记录不存在") from exc

    items = []
    try:
        if path.is_file():
            with path.open("r", encoding="utf-8") as handle:
                position = 0
                for line in handle:
                    if not line.strip():
                        continue
                    if position < cursor:
                        position += 1
                        continue
                    if len(items) > limit:
                        break
                    message = json.loads(line)
                    if not isinstance(message, dict):
                        raise ValueError("Invalid history row")
                    items.append({
                        "from": "me" if message.get("from") == "me" else "them",
                        "text": message.get("text"),
                        "ts": message.get("ts"),
                        "conversationId": message.get("archiveConversationId"),
                        "conversationKind": message.get("archiveConversationKind"),
                    })
                    position += 1
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="角色聊天记录读取失败") from exc

    has_more = len(items) > limit
    return {
        "items": items[:limit],
        "nextCursor": cursor + limit if has_more else None,
    }
