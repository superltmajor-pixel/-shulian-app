"""Conversation-aware character scene status.

The clock-based schedule remains the fallback. A confirmed shared scene is a
short-lived persisted override, so opening a chat does not change a character's
independent activity while an explicit shared event can remain continuous.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from shulian_backend.domain.live_status_tones import tone_color
from shulian_backend.domain.scene_evidence import (
    current_scene_text,
    text_asserts_onsite_action,
    user_asserts_shared_presence,
    user_permits_onsite_reply,
)
from shulian_backend.repositories.scene_status_repository import (
    SceneStatusRepository,
)
from state_store import state_snapshot


_LOCK = threading.RLock()
_OVERRIDES: dict[str, dict[str, Any]] = {}
_RECENT_RECOVERY_ATTEMPTED: set[str] = set()
_REPOSITORY = SceneStatusRepository()
_LOGGER = logging.getLogger(__name__)

_SCENES = {
    "chat": {
        "label": "和你聊天中",
        "detail": "正在认真听你说话",
        "tone": "warm",
        "minutes": 15,
    },
    "meal": {
        "label": "和你吃饭中",
        "detail": "正在陪你一起吃饭",
        "tone": "meal",
        "minutes": 90,
    },
    "walk": {
        "label": "和你散步中",
        "detail": "正在陪你慢慢走走",
        "tone": "walk",
        "minutes": 90,
    },
    "shopping": {
        "label": "和你逛街中",
        "detail": "正在陪你四处看看",
        "tone": "walk",
        "minutes": 120,
    },
    "movie": {
        "label": "和你看电影中",
        "detail": "正在和你共享电影时光",
        "tone": "warm",
        "minutes": 180,
    },
    "date": {
        "label": "和你约会中",
        "detail": "正在认真享受与你的约会",
        "tone": "warm",
        "minutes": 180,
    },
    "travel": {
        "label": "和你在路上",
        "detail": "正在陪你一起前往目的地",
        "tone": "walk",
        "minutes": 120,
    },
    "home": {
        "label": "和你回家中",
        "detail": "正在陪你一起回去",
        "tone": "walk",
        "minutes": 60,
    },
    "rest": {
        "label": "陪你休息中",
        "detail": "正在安静陪你放松一会儿",
        "tone": "idle",
        "minutes": 60,
    },
    "sleep": {
        "label": "陪你睡觉中",
        "detail": "已经安静睡下，和你一起进入夜晚",
        "tone": "sleep",
        "minutes": 480,
    },
    "study": {
        "label": "陪你学习中",
        "detail": "正在和你一起专心学习",
        "tone": "study",
        "minutes": 120,
    },
    "game": {
        "label": "和你玩游戏中",
        "detail": "正在和你一起玩游戏",
        "tone": "warm",
        "minutes": 120,
    },
}

# 色调→颜色统一取自 domain.live_status_tones，与 status_engine 共用一份。

_SCENE_CUE = re.compile(
    r"吃饭|吃东西|餐厅|饭店|火锅|午饭|晚饭|早餐|散步|走走|逛街|购物|"
    r"电影|影院|约会|出门|出发|在路上|回家|到家|休息|睡觉|躺一会|"
    r"入睡|睡着|睡梦|哄睡|哄着|一起睡|同床|上床|躺下|躺着|被窝|安眠|晚安|睡吧|"
    r"学习|写作业|复习|看书|打游戏|玩游戏|开黑|吃完|结束|不去了|先走"
)

_REST_CUE = re.compile(
    r"休息|睡觉|睡着|入睡|睡梦|哄睡|哄着|一起睡|同床|上床|躺下|躺着|被窝|安眠|晚安|睡吧"
)
_SHARED_REST_USER_CUE = re.compile(
    r"抱(?:着|住)|哄(?:着|你|她|他)?|陪(?:你|我|她|他)?(?:睡|休息)|"
    r"一起(?:睡|休息)|我们(?:睡|休息)|同床|上床|躺(?:下|着)|被窝|回房|"
    r"结束(?:了)?(?:今天|一天|这一天)(?:的)?(?:行程|安排)|"
    r"哄.*?(?:入睡|睡着)|抱.*?(?:入睡|睡着)"
)
_SHARED_REST_REPLY_CUE = re.compile(
    r"睡着|入睡|睡梦|呼吸.*?(?:平稳|绵长|安稳)|安静下来|靠在|在你怀里|怀里|"
    r"闭上眼|合上眼|沉沉|晚安|睡吧|陪你|一起睡|好.*?(?:睡|休息)|嗯.*?(?:睡|休息)"
)
_SHARED_SLEEP_CUE = re.compile(
    r"睡觉|睡着|入睡|睡梦|哄睡|哄着|一起睡|同床|上床|被窝|安眠|晚安|睡吧"
)
_REST_REFUSAL_CUE = re.compile(
    r"(?:不想|不愿|不肯|不能|不要|不打算|还不能)(?:睡|休息|躺下|上床|入睡)|"
    r"拒绝(?:睡|休息|躺下|上床)|别(?:让我)?(?:睡|休息)|我不睡"
)
_SHARED_SCENE_CUE = re.compile(
    r"我们|咱们|一起|一块|陪(?:你|我|她|他)|跟(?:你|我)|和(?:你|我)|与(?:你|我)|"
    r"同(?:你|我)|带(?:你|我|她|他)|牵着(?:你|我|她|他)|抱着(?:你|我|她|他)"
)
_SCENE_REFUSAL_CUE = re.compile(
    r"不去|不想|不要|不行|不能|拒绝|改天|下次再|以后再|先不|暂时不"
)
_FUTURE_OR_HYPOTHETICAL_CUE = re.compile(
    r"明天|明日|以后|下次|改天|如果|假如|要不要|想不想|计划|打算"
)
_IMMEDIATE_SCENE_CUE = re.compile(
    r"现在|这就|走吧|来吧|出发|已经|正在|开始|坐下|到了|过来|进来"
)
_USER_ACCEPTANCE_CUE = re.compile(r"^(?:[（(][^）)]{0,80}[）)]\s*)*(?:好|好啊|可以|嗯|当然|走吧|来吧|我愿意)")
_INTERACTION_END_CUE = re.compile(
    r"再见|先走了|我走了|你走吧|挂了|晚点聊|回头聊|下次聊|不聊了|结束聊天|离开了"
)
_SCENE_EVIDENCE_CUES: dict[str, tuple[str, ...]] = {
    "meal": ("吃饭", "用餐", "早餐", "午饭", "晚饭", "夜宵", "餐厅", "饭店"),
    "walk": ("散步", "走走"),
    "shopping": ("逛街", "购物"),
    "movie": ("电影", "影院"),
    "date": ("约会",),
    "travel": ("出发", "在路上", "旅行", "目的地"),
    "home": ("回家", "到家"),
    "rest": ("休息", "躺一会", "放松"),
    "sleep": ("睡觉", "入睡", "睡着", "晚安", "被窝"),
    "study": ("学习", "写作业", "复习", "看书"),
    "game": ("打游戏", "玩游戏", "开黑"),
}
_RECENT_SCENE_MAX_AGE = timedelta(minutes=180)
_RECENT_SLEEP_MAX_AGE = timedelta(hours=12)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _serialize_overrides(
    overrides: dict[str, dict[str, Any]],
) -> dict[str, dict[str, str]]:
    serialized: dict[str, dict[str, str]] = {}
    for character_id, override in overrides.items():
        scene = str(override.get("scene") or "")
        started_at = override.get("started_at")
        expires_at = override.get("expires_at")
        if (
            scene not in _SCENES
            or not isinstance(started_at, datetime)
            or not isinstance(expires_at, datetime)
        ):
            continue
        serialized[character_id] = {
            "scene": scene,
            "started_at": started_at.isoformat(timespec="seconds"),
            "expires_at": expires_at.isoformat(timespec="seconds"),
        }
    return serialized


def _load_persisted_overrides() -> dict[str, dict[str, Any]]:
    try:
        raw_overrides = _REPOSITORY.load()
    except Exception:
        _LOGGER.warning("Unable to load persisted scene status", exc_info=True)
        return {}

    now = _utc_now()
    loaded: dict[str, dict[str, Any]] = {}
    for character_id, raw in raw_overrides.items():
        if not isinstance(raw, dict):
            continue
        scene = str(raw.get("scene") or "")
        started_at = _parse_datetime(raw.get("started_at"))
        expires_at = _parse_datetime(raw.get("expires_at"))
        if (
            scene not in _SCENES
            or not started_at
            or not expires_at
            or expires_at <= now
        ):
            continue
        loaded[str(character_id)] = {
            "scene": scene,
            "started_at": started_at,
            "expires_at": expires_at,
        }
    return loaded


def _persist_overrides() -> None:
    with _LOCK:
        payload = _serialize_overrides(_OVERRIDES)
        try:
            _REPOSITORY.save(payload)
        except Exception:
            # The in-memory status remains usable if local storage is temporarily unavailable.
            _LOGGER.warning("Unable to persist scene status", exc_info=True)


def reload_persisted_scenes() -> None:
    """Reload scene overrides after a state restore or an external state write."""

    loaded = _load_persisted_overrides()
    with _LOCK:
        _OVERRIDES.clear()
        _OVERRIDES.update(loaded)


def scene_transition_candidate(*texts: str) -> bool:
    """Return whether a turn is worth a small scene-classification request."""

    joined = "\n".join(str(text or "") for text in texts)
    return bool(_SCENE_CUE.search(joined)) or any(
        user_permits_onsite_reply(text) for text in texts[:1]
    )


def explicit_shared_presence_scene(user_message: str, reply: str) -> str | None:
    """Recognize a user-grounded, currently co-present interaction.

    A user's asserted stage direction already proves co-presence.  A request
    only does so after the reply actually performs an on-site action.  This
    deterministic bridge lets the guard accept the first turn and persists a
    short ``chat`` scene for the following turn without treating ordinary text
    messaging as physical co-presence.
    """

    user_message = current_scene_text(user_message)
    reply = current_scene_text(reply)
    if user_asserts_shared_presence(user_message):
        return "chat"
    if user_permits_onsite_reply(user_message) and text_asserts_onsite_action(reply):
        return "chat"
    return None


def explicit_shared_rest_scene(user_message: str, reply: str) -> str | None:
    """Return the explicit shared sleep/rest scene confirmed by a turn.

    Sleep is easy for a general classifier to mistake for the end of a
    conversation.  When the user describes staying together, holding,
    accompanying, or coaxing the character to sleep and the reply confirms
    that she has settled down, this is a continuing shared ``rest`` scene.
    """

    user_text = current_scene_text(user_message)
    reply_text = current_scene_text(reply)
    if not _REST_CUE.search(user_text + "\n" + reply_text):
        return None
    if _REST_REFUSAL_CUE.search(reply_text):
        return None
    if not (
        _SHARED_REST_USER_CUE.search(user_text)
        and _SHARED_REST_REPLY_CUE.search(reply_text)
    ):
        return None
    return "sleep" if _SHARED_SLEEP_CUE.search(user_text + "\n" + reply_text) else "rest"


def _strip_json_fence(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    return match.group(0) if match else text


def parse_scene_decision(value: str) -> dict[str, Any] | None:
    """Parse and validate the model's fixed-schema scene decision."""

    try:
        raw = json.loads(_strip_json_fence(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    action = str(raw.get("action") or "").strip().lower()
    scene = str(raw.get("scene") or "").strip().lower()
    try:
        confidence = float(raw.get("confidence", 0))
    except (TypeError, ValueError):
        return None
    if action not in {"keep", "set", "clear"}:
        return None
    if action == "set" and scene not in _SCENES:
        return None
    return {
        "action": action,
        "scene": scene if action == "set" else "",
        "confidence": max(0.0, min(confidence, 1.0)),
    }


def validate_scene_decision_evidence(
    decision: dict[str, Any] | None,
    *,
    current_status: dict[str, Any],
    user_message: str,
    reply: str,
) -> dict[str, Any] | None:
    """Reject model scene changes that have no deterministic conversation evidence."""

    if not decision or decision.get("action") == "keep":
        return decision
    action = str(decision.get("action") or "")
    current_is_shared = current_status.get("source") == "conversation"
    user_message = current_scene_text(user_message)
    reply = current_scene_text(reply)
    if not user_message:
        return {"action": "keep", "scene": "", "confidence": 1.0}
    combined = f"{user_message}\n{reply}"
    if action == "clear":
        return decision if current_is_shared and _INTERACTION_END_CUE.search(combined) else {
            "action": "keep", "scene": "", "confidence": 1.0,
        }

    scene = str(decision.get("scene") or "")
    if scene == "chat":
        # Ordinary messaging must never create “和你聊天中”; chat is only a
        # safe downgrade after another confirmed shared activity has ended, or
        # a new scene backed by an explicit co-present user action.
        return decision if current_is_shared or explicit_shared_presence_scene(user_message, reply) else {
            "action": "keep", "scene": "", "confidence": 1.0,
        }
    cues = _SCENE_EVIDENCE_CUES.get(scene, ())
    if not cues or not any(cue in combined for cue in cues):
        return {"action": "keep", "scene": "", "confidence": 1.0}
    if _SCENE_REFUSAL_CUE.search(combined):
        return {"action": "keep", "scene": "", "confidence": 1.0}
    user_text = str(user_message or "").strip()
    reply_text = str(reply or "").strip()
    shared_now = bool(_SHARED_SCENE_CUE.search(user_text))
    accepted_role_proposal = bool(
        _USER_ACCEPTANCE_CUE.search(user_text)
        and _SHARED_SCENE_CUE.search(reply_text)
    )
    if not (shared_now or accepted_role_proposal):
        return {"action": "keep", "scene": "", "confidence": 1.0}
    if _FUTURE_OR_HYPOTHETICAL_CUE.search(combined) and not _IMMEDIATE_SCENE_CUE.search(combined):
        return {"action": "keep", "scene": "", "confidence": 1.0}
    return decision


def _set_override(character_id: str, scene: str, now: datetime | None = None) -> None:
    spec = _SCENES.get(str(scene or ""))
    if spec is None:
        _LOGGER.warning("Ignored invalid shared scene", extra={"character_id": character_id})
        return
    started_at = now or _utc_now()
    with _LOCK:
        _OVERRIDES[character_id] = {
            "scene": scene,
            "started_at": started_at,
            "expires_at": started_at + timedelta(minutes=spec["minutes"]),
        }
    _persist_overrides()


def clear_character_scene(character_id: str) -> None:
    changed = False
    character_id = str(character_id or "")
    with _LOCK:
        _RECENT_RECOVERY_ATTEMPTED.add(character_id)
        changed = _OVERRIDES.pop(character_id, None) is not None
    if changed:
        _persist_overrides()


def clear_all_scenes() -> None:
    """Clear all shared scenes and their persisted state."""

    with _LOCK:
        changed = bool(_OVERRIDES)
        _OVERRIDES.clear()
    if changed:
        _persist_overrides()


def _active_override(character_id: str, now: datetime | None = None) -> dict[str, Any] | None:
    current = now or _utc_now()
    removed = False
    with _LOCK:
        override = _OVERRIDES.get(character_id)
        scene = str(override.get("scene") or "") if isinstance(override, dict) else ""
        expires_at = override.get("expires_at") if isinstance(override, dict) else None
        invalid = bool(override) and (
            scene not in _SCENES or not isinstance(expires_at, datetime)
        )
        if override and (invalid or expires_at <= current):
            _OVERRIDES.pop(character_id, None)
            removed = True
            result = None
        else:
            result = dict(override) if override else None
    if removed:
        _persist_overrides()
    return result


def _thread_text(item: object) -> str:
    if not isinstance(item, dict):
        return ""
    text = item.get("text") or item.get("transcript") or ""
    return str(text).strip()


def _thread_datetime(item: object) -> datetime | None:
    if not isinstance(item, dict):
        return None
    try:
        timestamp = float(item.get("ts")) / 1000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def recover_recent_rest_scene(
    character_id: str,
    now: datetime | None = None,
) -> bool:
    """Recover a missed explicit sleep scene from the persisted recent thread.

    This runs at most once per character per process and only considers a very
    recent user/character pair.  It repairs a missed post-reply transition
    without turning an old conversation or an arbitrary status refresh into a
    new scene.
    """

    character_id = str(character_id or "").strip()
    if not character_id:
        return False
    current = now or _utc_now()
    try:
        raw_threads = state_snapshot()["data"].get("sl_threads", "")
        threads = json.loads(raw_threads) if raw_threads else {}
    except Exception:
        _LOGGER.warning("Unable to recover recent rest scene", exc_info=True)
        return False
    if not isinstance(threads, dict) or not isinstance(threads.get(character_id), list):
        return False
    with _LOCK:
        if character_id in _RECENT_RECOVERY_ATTEMPTED:
            return False
        _RECENT_RECOVERY_ATTEMPTED.add(character_id)

    thread = threads[character_id]
    # Recovery is only allowed from the final complete user/character pair.
    # Searching farther back can resurrect last night's sleep after a newer
    # morning conversation has already established that the scene moved on.
    role_items = [
        item for item in thread
        if isinstance(item, dict)
        and item.get("from") in {"me", "her"}
        and _thread_text(item)
    ]
    if not role_items or role_items[-1].get("from") != "her":
        return False
    reply_item = role_items[-1]
    user_index = next(
        (index for index in range(len(role_items) - 2, -1, -1) if role_items[index].get("from") == "me"),
        None,
    )
    if user_index is None:
        return False
    user_item = role_items[user_index]
    # An assistant-only greeting/proactive message after an already completed
    # pair must not be paired retroactively with that old user message.
    if any(item.get("from") == "her" for item in role_items[user_index + 1:-1]):
        return False

    user = _thread_text(user_item)
    reply = _thread_text(reply_item)
    user_at = _thread_datetime(user_item)
    reply_at = _thread_datetime(reply_item)
    timestamps = [value for value in (reply_at, user_at) if value is not None]
    latest_at = max(timestamps) if timestamps else None
    recovered_scene = explicit_shared_rest_scene(user, reply)
    if recovered_scene is None:
        return False
    max_age = _RECENT_SLEEP_MAX_AGE if recovered_scene == "sleep" else _RECENT_SCENE_MAX_AGE
    if latest_at is None or current - latest_at > max_age:
        return False
    if current - latest_at < timedelta(minutes=-5):
        return False

    active = _active_override(character_id, current)
    if active:
        if active["scene"] != "rest" or recovered_scene != "sleep":
            return False
    _set_override(character_id, recovered_scene, current)
    return True


def resolve_effective_status(
    schedule_status: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Overlay an unexpired conversation scene on a scheduled status."""

    base = {**schedule_status, "source": "schedule", "scene": None}
    override = _active_override(str(base.get("character_id") or ""), now)
    if not override:
        return base
    scene = str(override.get("scene") or "")
    spec = _SCENES.get(scene)
    if spec is None:
        clear_character_scene(str(base.get("character_id") or ""))
        return base
    return {
        **base,
        "label": spec["label"],
        "detail": spec["detail"],
        "tone": spec["tone"],
        "color": tone_color(spec["tone"]),
        "next": "场景结束后恢复原有安排",
        "source": "conversation",
        "scene": scene,
        "expires_at": override["expires_at"].isoformat(timespec="seconds"),
    }


def apply_scene_decision(
    schedule_status: dict[str, Any],
    decision: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply only high-confidence, fixed-enum decisions from the classifier."""

    if not decision or decision.get("confidence", 0) < 0.75:
        return resolve_effective_status(schedule_status)
    character_id = str(schedule_status.get("character_id") or "")
    if decision["action"] == "clear":
        clear_character_scene(character_id)
    elif decision["action"] == "set":
        _set_override(character_id, str(decision["scene"]))
    return resolve_effective_status(schedule_status)


reload_persisted_scenes()
