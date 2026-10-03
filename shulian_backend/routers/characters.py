"""角色资料与状态 API。"""

from fastapi import APIRouter, HTTPException

from characters import ROSTER
from status_engine import get_character_status
from shulian_backend.services.scene_status_service import (
    clear_character_scene,
    recover_recent_rest_scene,
)


router = APIRouter()


def _public_background(character) -> list[str]:
    return list(character.public_background)


@router.get("/api/characters")
def list_characters():
    return [
        {
            "id": character.id,
            "name": character.name,
            "en": character.en,
            "persona": character.persona,
            "tags": character.tags,
            "cat": character.cat,
            "intimacy": character.intimacy,
            "greet": character.greet,
        }
        for character in ROSTER.values()
    ]


@router.get("/api/characters/{character_id}")
def get_character(character_id: str):
    character = ROSTER.get(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    return {
        "id": character.id,
        "name": character.name,
        "en": character.en,
        "persona": character.persona,
        "tags": character.tags,
        "cat": character.cat,
        "intimacy": character.intimacy,
        "greet": character.greet,
        "mood": character.mood,
        "background": _public_background(character),
    }


@router.get("/api/characters/{character_id}/status")
def character_status(character_id: str):
    character = ROSTER.get(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    recover_recent_rest_scene(character_id)
    return get_character_status(character)


@router.delete("/api/characters/{character_id}/status/scene")
def clear_character_scene_status(character_id: str):
    character = ROSTER.get(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    clear_character_scene(character_id)
    return get_character_status(character)
