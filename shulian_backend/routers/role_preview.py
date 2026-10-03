"""Isolated trial chat for a custom-role draft."""

from typing import Literal
import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

import chat as chat_backend
from shulian_backend.security import require_local_write
from shulian_backend.services.custom_role_service import build_custom_character, build_custom_contexts, validate_custom_profile


router = APIRouter()


class TrialTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    speaker: Literal["me", "them"] = Field(alias="from")
    text: str = Field(min_length=1, max_length=4000)


class RoleTrialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: dict
    message: str = Field(min_length=1, max_length=4000)
    history: list[TrialTurn] = Field(default_factory=list, max_length=24)
    memory: str = Field(default="", max_length=8000)


@router.post("/api/role-library/preview-chat")
def preview_role_chat(request: Request, payload: RoleTrialRequest):
    require_local_write(request)
    if not payload.message.strip():
        raise HTTPException(status_code=422, detail="试聊内容不能为空")
    try:
        character = build_custom_character(payload.profile)
        memory_context, companion_context = build_custom_contexts(
            validate_custom_profile(payload.profile), payload.memory, character_id=character.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    history = [
        {"role": "user" if turn.speaker == "me" else "assistant", "content": turn.text.strip()}
        for turn in payload.history
        if turn.text.strip()
    ]
    try:
        reply = chat_backend.get_reply(
            character.id,
            payload.message.strip(),
            history,
            memory=payload.memory,
            memory_context=json.dumps(memory_context, ensure_ascii=False),
            companion_context=companion_context,
            character_override=character,
        )
    except chat_backend.ChatConfigurationError as exc:
        raise HTTPException(status_code=503, detail="请先配置聊天模型，再试聊角色") from exc
    except chat_backend.ChatConsistencyError as exc:
        raise HTTPException(status_code=502, detail="试聊回复未通过一致性检查，请重试") from exc
    except chat_backend.ChatServiceError as exc:
        raise HTTPException(status_code=502, detail="试聊暂时不可用，请稍后重试") from exc
    return {"reply": reply}
