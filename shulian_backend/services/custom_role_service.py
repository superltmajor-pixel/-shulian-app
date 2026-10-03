"""Validation and runtime construction for user-created characters."""

from __future__ import annotations

import base64
import binascii
import math
import re
from urllib.parse import urlsplit

from characters import Character, _build_prompt
from role_archive import RoleArchiveError, resolve_role_snapshot_file
from .memory_service import normalize_memory_context
from .companion_context_service import normalize_companion_context, STAGES


_IMAGE = re.compile(
    r"^data:image/(?P<kind>png|jpeg|jpg|webp|gif);base64,(?P<data>[A-Za-z0-9+/=]+)$",
    re.IGNORECASE,
)
_POSITION = re.compile(r"^(\d{1,3})% (\d{1,3})%$")
_PROFILE_FIELDS = {
    "name", "en", "persona", "tags", "cat", "greet", "mood",
    "profileIntro", "personality", "speakingStyle", "relationship",
    "img", "face", "imgPos", "facePos",
    "relationshipLevel",
}
_TEXT_LIMITS = {
    "name": 80, "en": 80, "persona": 20_000, "cat": 40,
    "greet": 2_000, "mood": 500, "profileIntro": 8_000,
    "personality": 8_000, "speakingStyle": 8_000, "relationship": 8_000,
}


def _text_field(profile: dict, key: str) -> str:
    value = profile.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{key} 必须是文本")
    value = value.strip()
    if len(value) > _TEXT_LIMITS[key]:
        raise ValueError(f"{key} 内容过长")
    return value


def _image_field(profile: dict, key: str, character_id: str | None) -> str:
    value = profile.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{key} 必须是图片")
    value = value.strip()
    if not value:
        return ""
    match = _IMAGE.fullmatch(value)
    if match:
        if len(match.group("data")) > 8 * 1024 * 1024 + 4:
            raise ValueError(f"{key} 图片不能超过 6 MiB")
        try:
            data = base64.b64decode(match.group("data"), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError(f"{key} 图片编码无效") from exc
        if not data or len(data) > 6 * 1024 * 1024:
            raise ValueError(f"{key} 图片不能超过 6 MiB")
        kind = match.group("kind").lower()
        signatures = {
            "png": data.startswith(b"\x89PNG\r\n\x1a\n"),
            "jpeg": data.startswith(b"\xff\xd8\xff"),
            "jpg": data.startswith(b"\xff\xd8\xff"),
            "webp": len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP",
            "gif": data.startswith((b"GIF87a", b"GIF89a")),
        }
        if not signatures[kind]:
            raise ValueError(f"{key} 图片内容与格式不匹配")
        return value
    if character_id:
        parsed = urlsplit(value)
        path = parsed.path
        prefix = f"/api/role-library/{character_id}/files/"
        if (value.startswith(prefix) and path.startswith(prefix)
                and not (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment)):
            relative = path[len(prefix):]
            try:
                resolve_role_snapshot_file(character_id, relative)
            except RoleArchiveError as exc:
                raise ValueError(f"{key} 原图片不存在") from exc
            return value
    raise ValueError(f"{key} 仅支持本地上传的图片")


def validate_custom_profile(profile: dict, *, character_id: str | None = None) -> dict:
    """Keep only the documented profile fields and reject prompt/asset injection."""
    if not isinstance(profile, dict):
        raise ValueError("角色资料必须是对象")
    unknown = set(profile) - _PROFILE_FIELDS
    if unknown:
        raise ValueError("角色资料包含不支持的字段")
    cleaned = {key: _text_field(profile, key) for key in _TEXT_LIMITS}
    if not cleaned["name"] or not cleaned["persona"]:
        raise ValueError("角色名称和人设不能为空")
    cleaned["en"] = cleaned["en"] or cleaned["name"]
    cleaned["cat"] = cleaned["cat"] or "自建"
    tags = profile.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 12 or any(
        not isinstance(tag, str) or not tag.strip() or len(tag.strip()) > 50
        for tag in tags
    ):
        raise ValueError("角色标签格式无效")
    cleaned["tags"] = [tag.strip() for tag in tags]
    level = profile.get("relationshipLevel", 0)
    if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 10:
        raise ValueError("初始关系阶段无效")
    cleaned["relationshipLevel"] = level or infer_relationship_level(cleaned["relationship"])
    for key in ("img", "face"):
        cleaned[key] = _image_field(profile, key, character_id)
    for key in ("imgPos", "facePos"):
        value = profile.get(key, "50% 50%")
        if not isinstance(value, str):
            raise ValueError(f"{key} 位置格式无效")
        match = _POSITION.fullmatch(value.strip())
        if not match or any(int(group) > 100 for group in match.groups()):
            raise ValueError(f"{key} 位置格式无效")
        cleaned[key] = value.strip()
    return cleaned


def infer_relationship_level(text: str) -> int:
    # Only affirmative, familiar labels are inferred. The editor offers an
    # explicit stage for relationships that cannot be inferred from prose.
    if re.search(r"未婚|未结婚|没有结婚|尚未|不是|并非|单身|陌生|初识|刚认识", text):
        return 1
    for level, cues in ((10, ("已婚", "已经结婚", "结婚十年", "夫妻", "终身伴侣")),
                        (7, ("恋人", "情侣", "男女朋友", "恋爱关系")),
                        (4, ("挚友", "多年好友", "青梅竹马")),
                        (3, ("朋友", "同学", "同事"))):
        if any(cue in text for cue in cues):
            return level
    return 1


def confirmed_memory_context(text: str) -> dict:
    """Convert reviewed editor text into the same layers used by live chat."""
    facts = [item.strip().lstrip("-• ") for item in re.split(r"\n+|(?<=[。！？.!?])\s*", text) if item.strip()]
    layers = {"stable_facts": [], "relationship_facts": [], "recent_events": []}
    for index, fact in enumerate(facts, 1):
        # This text is authored by the user, whereas the legacy summarizer's
        # first-person text was authored by the character.
        if fact.startswith("我") and not fact.startswith("我们"):
            fact = "用户" + fact[1:]
        candidate = normalize_memory_context({"stable_facts": [fact]})
        if not candidate["stable_facts"] and not candidate["relationship_facts"]:
            candidate = normalize_memory_context({"relationship_facts": [fact]})
        if not candidate["stable_facts"] and not candidate["relationship_facts"]:
            candidate = normalize_memory_context({"recent_events": [{"text": fact}]})
        if not any(candidate[key] for key in layers):
            raise ValueError(f"共同记忆第 {index} 条无法作为有效记忆保存，请精简为完整、明确的事实")
        for key in layers:
            layers[key].extend(candidate[key])
    for key, limit in (("stable_facts", 16), ("relationship_facts", 12), ("recent_events", 8)):
        if len(layers[key]) > limit:
            raise ValueError("共同记忆条目过多，请精简后保存")
    return normalize_memory_context(layers)


def build_custom_contexts(profile: dict, memory: str, *, character_id: str,
                          previous_state: dict | None = None,
                          previous_profile: dict | None = None,
                          previous_memory: str = "") -> tuple[dict, dict]:
    state = previous_state or {}
    current_memory = normalize_memory_context(state.get("memoryContext"))
    companion = normalize_companion_context(character_id, state.get("companionContext"))
    if previous_state is None or memory != previous_memory or not any(
        current_memory[key] for key in ("stable_facts", "relationship_facts", "recent_events")
    ):
        desired = confirmed_memory_context(memory)
        try:
            old = confirmed_memory_context(previous_memory)
        except ValueError:
            old = {"stable_facts": [], "relationship_facts": [], "recent_events": []}
        for key in ("stable_facts", "relationship_facts", "recent_events"):
            text_of = lambda item: item.get("text") if isinstance(item, dict) else item
            old_texts = {text_of(item) for item in old[key]}
            current_memory[key] = desired[key] + [item for item in current_memory[key] if text_of(item) not in old_texts]
        current_memory = normalize_memory_context(current_memory)
        # Migration also copies memory facts into CompanionContext. Remove
        # the replaced manual facts there so live chat cannot revive them.
        old_companion = normalize_companion_context(character_id, {**companion, "stable_facts": old["stable_facts"]})
        old_facts = set(old_companion["stable_facts"])
        companion["stable_facts"] = [fact for fact in companion["stable_facts"] if fact not in old_facts]

    previous = previous_profile or {}
    relation_changed = previous_state is None or any(
        profile.get(key) != previous.get(key) for key in ("relationship", "relationshipLevel")
    )
    if relation_changed:
        level = profile["relationshipLevel"]
        relation = companion["relationship"]
        relation.update(level=level, stage=STAGES[level - 1], title=STAGES[level - 1],
                        dimensions={"familiarity": min(4, (level - 1) // 2),
                                    "trust": min(4, (level - 1) // 2),
                                    "affection": max(0, min(4, level - 4)),
                                    "commitment": max(0, min(4, level - 6))},
                        confirmed_events=["relationship_redefined"], commitments=[])
        companion = normalize_companion_context(character_id, companion)
    return current_memory, companion


def build_custom_character(
    profile: dict, *, character_id: str = "custom_preview"
) -> Character:
    """Build a character for both draft chat and saved roles without persistence."""
    cleaned = validate_custom_profile(profile, character_id=(
        character_id if character_id != "custom_preview" else None
    ))
    details = "\n".join(
        f"【{title}】\n{cleaned[key]}"
        for key, title in (
            ("personality", "性格"),
            ("speakingStyle", "说话方式"),
            ("relationship", "与用户的初始关系"),
        )
        if cleaned[key]
    )
    prompt = _build_prompt(
        cleaned["name"], cleaned["en"], cleaned["persona"],
        cleaned["tags"], cleaned["greet"], cleaned["mood"], [],
        cleaned["relationshipLevel"], extra=details, core_memory=cleaned["profileIntro"],
    )
    return Character(
        id=character_id,
        name=cleaned["name"],
        en=cleaned["en"],
        persona=cleaned["persona"],
        tags=cleaned["tags"],
        cat=cleaned["cat"],
        greet=cleaned["greet"],
        mood=cleaned["mood"],
        replies=[],
        system_prompt=prompt,
        core_memory=cleaned["profileIntro"],
        public_background=tuple(
            part for part in (cleaned["personality"], cleaned["relationship"]) if part
        ),
        intimacy=cleaned["relationshipLevel"],
    )


def validate_imported_sessions(sessions: object) -> list[dict]:
    if not isinstance(sessions, list) or len(sessions) > 500:
        raise ValueError("聊天会话数量超出限制")
    cleaned: list[dict] = []
    total_messages = 0
    for session in sessions:
        if not isinstance(session, dict) or set(session) - {"startTs", "endTs", "messages"}:
            raise ValueError("聊天会话格式无效")
        messages = session.get("messages")
        if not isinstance(messages, list):
            raise ValueError("聊天消息格式无效")
        total_messages += len(messages)
        if total_messages > 50_000:
            raise ValueError("聊天消息数量超出限制")
        prepared = []
        for message in messages:
            if not isinstance(message, dict) or set(message) - {"from", "text", "ts"}:
                raise ValueError("聊天消息格式无效")
            sender = message.get("from")
            text = message.get("text")
            if sender not in {"me", "them"} or not isinstance(text, str) or not text.strip() or len(text) > 8_000:
                raise ValueError("聊天消息角色或文本无效")
            prepared_message = {"from": "me" if sender == "me" else "her", "text": text.strip()}
            if message.get("ts") is not None:
                prepared_message["ts"] = _timestamp(message["ts"])
            prepared.append(prepared_message)
        prepared_session = {"messages": prepared}
        for key in ("startTs", "endTs"):
            if session.get(key) is not None:
                prepared_session[key] = _timestamp(session[key])
        cleaned.append(prepared_session)
    return cleaned


def _timestamp(value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("聊天时间格式无效")
    return value
