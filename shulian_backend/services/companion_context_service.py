"""CompanionContextV1 的规范化、迁移和关系事件校验。

模型或旧聊天只能提供候选证据；本模块负责去重、关系升级规则和隐私收敛。
新上下文只保存结构化结论，不保存私密对话原文。
"""

from __future__ import annotations
from role_content import RoleContentMap, content_for

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from ..domain.character_identity import aliases_for_character
from ..domain.content_cues import EXPLICIT_CONTENT_CUES
from ..domain.relationship_levels import (
    LEVEL_LIFELONG,
    LEVEL_MUTUAL_AFFECTION,
    LEVEL_SHARED_FUTURE,
)
from .memory_service import canonical_stable_fact

from ..schemas.api import CompanionContextV1


CONTEXT_VERSION = 1
STAGES = (
    "初识",
    "认识",
    "熟悉",
    "信赖",
    "亲近",
    "心意相通",
    "关系确认",
    "深度伴侣",
    "灵魂伴侣",
    "终身伴侣",
)

EXPERIENCE_LABELS = {
    "embrace": "拥抱",
    "kiss": "亲吻",
    "shared_sleep": "共同入睡",
    "general_intimacy": "一般亲密",
    "oral_intimacy": "口部亲密",
    "anal_intimacy": "后庭亲密",
    "manual_intimacy": "手部亲密",
    "other_private": "其他私密互动",
}

_ASSISTANT_INITIATED_ORIGINS = frozenset({"proactive", "home-greeting"})

INITIAL_RELATIONSHIPS = RoleContentMap("initialRelationship")

# 露骨/私密词表统一取自 domain.content_cues（与原 memory_service 词表取并集）。
_EXPERIENCE_FACT_CUES = (
    "发生关系", "亲密关系", "亲密互动", "亲密举动", "共同入睡", "相拥入睡", "睡在一起",
    "接吻", "亲吻", "深吻", "拥抱", "抱着睡", "私密互动", "交付身心", "肌肤相亲",
)
_ROLE_TO_USER_ADDRESS_KEYS = (
    "character_to_user_address", "role_to_user_address", "角色对用户称呼",
)
_USER_TO_CHARACTER_ADDRESS_KEYS = (
    "user_to_character_address", "user_to_role_address", "用户对角色称呼",
)
_LEGACY_ADDRESS_KEYS = ("address", "称呼", "legacy_address")
_BOUNDARY_KEYS = ("boundary", "边界")

_DURABLE_COMMITMENT_CUES = (
    "终身", "一辈子", "余生", "白头", "永恒", "契约", "婚约", "结婚", "婚礼",
    "夫妻", "共同未来", "共同走向未来", "以后一直", "关系确认", "终身伴侣",
)
_ONE_OFF_COMMITMENT_CUES = (
    "下次", "下回", "明天", "明日", "今晚", "今夜", "稍后", "待会", "等会",
    "见面时", "回来时", "发消息", "打电话", "做饭", "吃饭", "上工", "工作",
    "文书", "拥抱", "抱抱", "亲吻", "陪着说话", "还想说话",
)

_EXPERIENCE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("oral_intimacy", ("口交", "口部亲密", "含住", "吞吐", "用嘴", "唇舌侍奉")),
    ("anal_intimacy", ("肛交", "后庭", "后穴", "从后面进入")),
    ("manual_intimacy", ("手交", "指交", "用手抚慰", "手部亲密", "手指探入")),
    ("general_intimacy", ("发生关系", "亲密关系", "做爱", "欢爱", "交付身心", "肌肤相亲", "彻夜缠绵", "结合在一起")),
    ("shared_sleep", ("一起睡", "相拥入睡", "抱着你睡", "抱着她睡", "睡在一起", "同床", "共同入睡", "依偎着睡", "在怀里睡")),
    ("kiss", ("亲吻", "吻住", "吻了", "接吻", "唇瓣相贴", "轻啄", "深吻")),
    ("embrace", ("抱住", "抱紧", "拥抱", "相拥", "搂进怀", "搂住", "靠进怀里", "抱在怀里")),
    ("other_private", ("私密互动", "更加亲密", "亲密举动", "身体交付")),
)

_USER_AFFECTION = ("我喜欢你", "我爱你", "喜欢你", "爱你", "对你动心", "心里有你")
_ASSISTANT_AFFECTION = ("我也喜欢你", "我也爱你", "喜欢你", "爱你", "心里也有你", "接受你的心意")
_FUTURE_CUES = ("一起到老", "共度余生", "未来一起", "以后一直", "一辈子", "白头", "共同未来")
_FUTURE_ACCEPTANCE = (
    "我愿意和你一起", "我答应", "说好了", "不会松手", "陪你走下去", "和你走下去",
    "未来一起", "共同未来", "共度余生", "一辈子",
)
_MARRIAGE_CUES = ("结婚", "婚约", "嫁给", "娶你", "婚礼", "夫妻")
_MARRIAGE_ACCEPTANCE = (
    "我愿意", "答应你", "我同意", "说好了", "愿意嫁给你", "愿意娶你", "成为夫妻",
)
_HYPOTHETICAL_RELATIONSHIP = re.compile(r"如果|假如|假设|要是|比如|想象|梦见|假装|打个比方")
_DIRECT_MARRIAGE = re.compile(
    r"(?:我们|咱们|你和我|我和你).{0,12}(?:结婚|婚约|婚礼|夫妻)|"
    r"(?:嫁给我|娶我|娶你|嫁给你)|^\s*(?:结婚|成为夫妻)吧"
)
_BREAKUP_CUES = ("分手", "解除婚约", "撤销承诺", "不再是恋人", "结束我们的关系")
_BREAKUP_ACCEPTANCE = (
    "同意分手", "接受分手", "尊重你的决定", "关系到此结束", "关系到此",
    "解除我们的婚约", "撤销我们的承诺", "不再是恋人", "结束我们的关系",
    "重新定义我们的关系",
)
_DIRECT_BREAKUP_PATTERNS = (
    re.compile(r"(?:我们|咱们|你和我|我和你|我们之间).{0,10}(?:分手|解除婚约|撤销承诺|不再是恋人|结束.{0,4}关系)"),
    re.compile(r"(?:我要|我想|我决定|我要求|我提议|那就).{0,6}(?:和你|跟你)?分手"),
    re.compile(r"(?:和你|跟你).{0,6}(?:分手|解除婚约|结束.{0,4}关系)"),
    re.compile(r"(?:解除|撤销).{0,8}(?:我们的|你我的|我们之间的)(?:婚约|承诺|关系)"),
    re.compile(r"(?:不再|别再).{0,5}(?:做|当|是)(?:恋人|情侣|伴侣|夫妻)"),
    re.compile(r"^\s*分手(?:吧|了|。|！|!|$)"),
)

_NEGATION_PREFIX = re.compile(
    r"(?:不|没|未|无|别|不要|不想|不愿|不会|不能|不可以|拒绝|否认|从未|不再|取消|撤销|解除)"
    r"[^，。！？；\n]{0,8}$"
)
_RELATIONSHIP_REJECTION_CUES = (
    "不喜欢你", "不爱你", "不愿意", "不想", "不同意", "不能答应", "无法答应",
    "不能承诺", "无法承诺", "拒绝", "还需要时间", "需要时间确认", "没有答应",
    "还没想好", "需要考虑", "再考虑", "现在太早", "还太早", "暂时不能决定",
)
_EXPERIENCE_ACCEPTANCE_CUES = (
    "我愿意", "我接受", "回抱", "回吻", "没有躲开", "没有推开",
    "任由你", "依偎", "闭上眼", "陪你睡", "一起睡", "睡吧",
)
_EXPERIENCE_RECOLLECTION_ACCEPTANCE_CUES = (
    "我记得", "记得", "确实", "是的", "没错", "当然", "没有忘", "还记得",
)
_EXPERIENCE_REJECTION_CUES = (
    "不行", "不可以", "不能这样", "不愿意", "不想这样", "拒绝", "别这样",
    "停下", "躲开", "推开", "避开", "挣脱",
)
_PAST_EXPERIENCE_CUES = ("以前", "之前", "上次", "曾经", "已经", "好多次", "多次", "又", "再次")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _utc_now()).astimezone(timezone.utc).isoformat()


def _split_addresses(value: object) -> list[str]:
    """Normalize one UI field into individual, direction-safe nicknames."""

    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = re.split(r"[、,，;；/\n]+", str(value or ""))
    result: list[str] = []
    for raw in raw_values:
        clean = _clean(raw, 40).strip("‘’“”\"'")
        if clean and clean not in result:
            result.append(clean)
    return result[:12]


def _address_fact_direction(
    fact: str,
    *,
    aliases: tuple[str, ...],
) -> str | None:
    compact = re.sub(r"\s+", "", str(fact or ""))
    if not compact:
        return None
    names = tuple(dict.fromkeys((*aliases, "角色")))
    user_to_character = any(
        cue in compact
        for name in names
        for cue in (
            f"用户对{name}的称呼", f"用户对{name}的专属称呼", f"用户称呼{name}", f"用户叫{name}",
            f"用户把{name}叫作", f"用户给{name}的称呼",
        )
    )
    character_to_user = any(
        cue in compact
        for name in names
        for cue in (
            f"{name}对用户的称呼", f"{name}对用户的专属称呼", f"{name}称呼用户", f"{name}叫用户",
            f"{name}把用户叫作", f"{name}给用户的称呼",
        )
    )
    if user_to_character == character_to_user:
        return None
    return "user_to_character" if user_to_character else "character_to_user"


def _quoted_addresses(fact: str) -> list[str]:
    values = re.findall(r"[‘“\"']([^’”\"']{1,40})[’”\"']", str(fact or ""))
    return _split_addresses(values)


def _durable_commitment(value: object, *, character_id: str) -> str:
    """Keep relationship-defining commitments, not next-scene promises."""

    clean = _clean(value, 280)
    if not clean or any(cue in clean for cue in EXPLICIT_CONTENT_CUES):
        return ""
    if content_for(character_id).get("staleMarriage") and (
        any(cue in clean for cue in content_for(character_id)["staleMarriage"]["cues"])
        and any(cue in clean for cue in _MARRIAGE_CUES)
    ):
        return ""
    if not any(cue in clean for cue in _DURABLE_COMMITMENT_CUES):
        return ""
    # A durable relationship commitment may mention a date (for example the
    # confirmed birthday wedding), but a promise whose substance is merely the
    # next hug/message/meal must never become permanent character context.
    if any(cue in clean for cue in _ONE_OFF_COMMITMENT_CUES) and not any(
        cue in clean for cue in ("终身", "余生", "契约", "婚约", "结婚", "夫妻")
    ):
        return ""
    if clean[-1:] not in "。！？.!?；;":
        clean += "。"
    return clean


def _durable_commitments(
    values: Iterable[object],
    *,
    character_id: str,
    limit: int = 16,
) -> list[str]:
    result: list[str] = []
    for value in values:
        clean = _durable_commitment(value, character_id=character_id)
        if clean and clean not in result:
            result.append(clean)
        if len(result) >= limit:
            break
    return result


def _stage(level: int) -> str:
    return STAGES[max(1, min(int(level), 10)) - 1]


def _clean(value: object, limit: int = 280) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lstrip("-• ")[:limit]


def _has_unnegated_cue(text: object, cues: Iterable[str]) -> bool:
    """Return true only when a cue is not locally negated.

    Plain substring checks turn phrases such as ``不想分手`` + ``不同意`` into
    a false mutual breakup because both positive tokens are still present.  A
    conservative false negative is safer than mutating a relationship from an
    ambiguous or explicitly negative sentence.
    """

    clean = _clean(text, 4_000)
    for cue in cues:
        start = 0
        while True:
            index = clean.find(cue, start)
            if index < 0:
                break
            prefix = clean[max(0, index - 18):index]
            if not _NEGATION_PREFIX.search(prefix):
                return True
            start = index + max(1, len(cue))
    return False


def _contains_relationship_rejection(text: object) -> bool:
    return any(cue in _clean(text, 4_000) for cue in _RELATIONSHIP_REJECTION_CUES)


def _is_direct_relationship_redefinition_request(text: object) -> bool:
    """Only accept an explicit request about the user-character relationship.

    Mentions such as ``前对象和我分手了`` or ``朋友正在闹分手`` are biography,
    not permission to downgrade the current companion relationship.
    """

    clean = _clean(text, 4_000)
    return any(pattern.search(clean) for pattern in _DIRECT_BREAKUP_PATTERNS)


def _contains_experience_rejection(text: object) -> bool:
    clean = _clean(text, 4_000)
    # ``没有推开`` and ``没有躲开`` are acceptance, not rejection.
    clean = clean.replace("没有推开", "").replace("没有躲开", "")
    return any(cue in clean for cue in _EXPERIENCE_REJECTION_CUES)


def _unique_texts(values: Iterable[object], *, limit: int) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _clean(value)
        if not text or text in result or any(cue in text for cue in EXPLICIT_CONTENT_CUES):
            continue
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _unique_fact_texts(values: Iterable[object], *, limit: int) -> list[str]:
    return _unique_texts(
        (value for value in values if not any(cue in str(value or "") for cue in _EXPERIENCE_FACT_CUES)),
        limit=limit,
    )


def _unique_stable_facts(values: Iterable[object], *, limit: int) -> list[str]:
    return _unique_fact_texts(
        (fact for value in values if (fact := canonical_stable_fact(value))),
        limit=limit,
    )


def _fingerprint(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def default_companion_context(
    character_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the v21 calibration floor for one character."""

    captured = now or _utc_now()
    calibration = INITIAL_RELATIONSHIPS.get(character_id)
    if calibration:
        familiarity, trust, affection, commitment = calibration["dimensions"]
        level = calibration["level"]
        title = calibration["title"]
        events = list(calibration.get("events", []))
        commitments = list(calibration.get("commitments", []))
        invalidated = list(calibration.get("invalidated", []))
    else:
        familiarity = trust = affection = commitment = 0
        level = 1
        title = _stage(level)
        events = []
        commitments = []
        invalidated = []
    return {
        "version": CONTEXT_VERSION,
        "character_id": character_id,
        "relationship": {
            "level": level,
            "stage": _stage(level),
            "title": title,
            "dimensions": {
                "familiarity": familiarity,
                "trust": trust,
                "affection": affection,
                "commitment": commitment,
            },
            "forms_of_address": [],
            "user_forms_of_address": [],
            "boundaries": ["过去的亲密不代表本轮永久同意；每次都尊重当下表达与边界。"],
            "commitments": commitments,
            "confirmed_events": events,
            "invalidated_facts": invalidated,
            "updated_at": _iso(captured),
        },
        "experience_milestones": [],
        "stable_facts": [],
        "recent_events": [],
        "migration": {
            "source_version": "v21",
            "completed": False,
            "processed_segments": [],
            "migrated_at": "",
        },
        "updated_at": _iso(captured),
    }


def normalize_companion_context(
    character_id: str,
    raw: object,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Normalize untrusted client state and re-apply built-in calibration floors."""

    captured = now or _utc_now()
    base = default_companion_context(character_id, now=captured)
    value: Any = raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = None
    if not isinstance(value, dict) or value.get("version") != CONTEXT_VERSION:
        return base
    if str(value.get("character_id") or "") != character_id:
        return base

    relationship = value.get("relationship") if isinstance(value.get("relationship"), dict) else {}
    dimensions = relationship.get("dimensions") if isinstance(relationship.get("dimensions"), dict) else {}
    confirmed_events = relationship.get("confirmed_events", [])
    explicitly_redefined = isinstance(confirmed_events, list) and "relationship_redefined" in confirmed_events
    base_relationship = base["relationship"]
    base_dimensions = base_relationship["dimensions"]
    level = max(base_relationship["level"], min(10, max(1, int(relationship.get("level") or 1))))
    if character_id not in INITIAL_RELATIONSHIPS or explicitly_redefined:
        level = min(10, max(1, int(relationship.get("level") or 1)))

    title = _clean(relationship.get("title"), 40) or _stage(level)
    if character_id in INITIAL_RELATIONSHIPS and not explicitly_redefined and level == base_relationship["level"]:
        title = base_relationship["title"]
    self_aliases = set(aliases_for_character(character_id))
    forms_of_address = [
        item
        for item in _unique_texts(relationship.get("forms_of_address", []), limit=12)
        if item not in self_aliases
    ]
    user_forms_of_address = _unique_texts(
        relationship.get("user_forms_of_address", []),
        limit=12,
    )
    merged_relationship = {
        "level": level,
        "stage": _stage(level),
        "title": title,
        "dimensions": {
            key: (
                min(4, max(0, int(dimensions.get(key) or 0)))
                if explicitly_redefined
                else max(
                    int(base_dimensions[key]),
                    min(4, max(0, int(dimensions.get(key) or 0))),
                )
            )
            for key in ("familiarity", "trust", "affection", "commitment")
        },
        "forms_of_address": forms_of_address,
        "user_forms_of_address": user_forms_of_address,
        "boundaries": _unique_texts(
            [*base_relationship["boundaries"], *relationship.get("boundaries", [])],
            limit=12,
        ),
        "commitments": _durable_commitments(
            (
                [*relationship.get("commitments", [])]
                if explicitly_redefined
                else [*base_relationship["commitments"], *relationship.get("commitments", [])]
            ),
            character_id=character_id,
            limit=16,
        ),
        "confirmed_events": list(dict.fromkeys(
            ([*relationship.get("confirmed_events", [])] if explicitly_redefined else [
                *base_relationship["confirmed_events"], *relationship.get("confirmed_events", [])
            ])
        ))[:32],
        "invalidated_facts": list(dict.fromkeys(
            [*base_relationship["invalidated_facts"], *relationship.get("invalidated_facts", [])]
        ))[:16],
        "updated_at": _clean(relationship.get("updated_at"), 64) or _iso(captured),
    }

    milestones: list[dict[str, Any]] = []
    seen_categories: set[str] = set()
    raw_milestones = value.get("experience_milestones")
    if isinstance(raw_milestones, list):
        for item in raw_milestones:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or "")
            if category not in EXPERIENCE_LABELS or category in seen_categories:
                continue
            evidence_ids = [
                text for raw_id in item.get("evidence_ids", [])
                if (text := re.sub(r"[^a-fA-F0-9]", "", str(raw_id)))
            ][:64]
            count = len(set(evidence_ids))
            requested_frequency = str(item.get("frequency") or "once")
            frequency = "many" if count >= 5 or requested_frequency == "many" else (
                "several" if count >= 2 or requested_frequency == "several" else "once"
            )
            milestones.append({
                "category": category,
                "first_at": _clean(item.get("first_at"), 64),
                "last_at": _clean(item.get("last_at"), 64),
                "frequency": frequency,
                "evidence_ids": list(dict.fromkeys(evidence_ids)),
            })
            seen_categories.add(category)

    migration = value.get("migration") if isinstance(value.get("migration"), dict) else {}
    result = {
        "version": CONTEXT_VERSION,
        "character_id": character_id,
        "relationship": merged_relationship,
        "experience_milestones": milestones,
        "stable_facts": _unique_stable_facts(value.get("stable_facts", []), limit=24),
        # Recent-event lifetime is owned by MemoryContextV2, where every item
        # has captured_at/expires_at.  Old CompanionContext string events had no
        # clock and could otherwise be replayed forever after a new chat.
        "recent_events": [],
        "migration": {
            "source_version": "v21",
            "completed": bool(migration.get("completed")),
            "processed_segments": list(dict.fromkeys(
                re.sub(r"[^a-fA-F0-9]", "", str(item))
                for item in migration.get("processed_segments", [])
                if str(item).strip()
            ))[-4096:],
            "migrated_at": _clean(migration.get("migrated_at"), 64),
        },
        "updated_at": _clean(value.get("updated_at"), 64) or _iso(captured),
    }
    # Final Pydantic validation is the trust boundary used by every caller.
    return CompanionContextV1.model_validate(result).model_dump(mode="json")


def _message_payload(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    if raw.get("streaming"):
        return None
    from_value = str(raw.get("from") or "")
    role = str(raw.get("role") or "")
    if from_value in {"me", "her"}:
        role = "user" if from_value == "me" else "assistant"
    if role not in {"user", "assistant"}:
        return None
    text = raw.get("content") if "content" in raw else raw.get("text")
    if raw.get("type") == "voice" and raw.get("transcript"):
        text = raw.get("transcript")
    clean = _clean(text, 4_000)
    if not clean:
        return None
    timestamp = raw.get("ts") or raw.get("timestamp") or 0
    try:
        timestamp = float(timestamp)
    except (TypeError, ValueError):
        timestamp = 0
    return {
        "role": role,
        "content": clean,
        "ts": timestamp,
        "origin": _clean(raw.get("origin"), 40),
    }


def _session_messages(raw: object) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        raw = raw.get("messages", [])
    if not isinstance(raw, list):
        return []
    return [message for item in raw if (message := _message_payload(item))]


def _deduplicated_sessions(
    current_messages: list[dict],
    archived_sessions: list[dict],
) -> list[tuple[str, list[dict[str, Any]]]]:
    sessions: list[list[dict[str, Any]]] = []
    for session in archived_sessions or []:
        messages = _session_messages(session)
        if messages:
            sessions.append(messages)
    current = _session_messages(current_messages)
    if current:
        sessions.append(current)
    result: list[tuple[str, list[dict[str, Any]]]] = []
    seen: set[str] = set()
    for messages in sessions:
        canonical = [(item["role"], item["content"]) for item in messages]
        session_id = _fingerprint(canonical)
        if session_id in seen:
            continue
        seen.add(session_id)
        result.append((session_id, messages))
    return result


def _complete_pairs(messages: list[dict[str, Any]]) -> list[tuple[dict, dict]]:
    pairs: list[tuple[dict, dict]] = []
    pending: dict | None = None
    for message in messages:
        if message["role"] == "user":
            pending = message
        elif message.get("origin") in _ASSISTANT_INITIATED_ORIGINS:
            pending = None
        elif pending is not None:
            pairs.append((pending, message))
            pending = None
    return pairs


def complete_conversation_messages(messages: list[dict]) -> list[dict[str, Any]]:
    """Return only genuine user/reply pairs for model-assisted consolidation."""

    result: list[dict[str, Any]] = []
    for user, assistant in _complete_pairs(_session_messages(messages)):
        result.extend((
            {
                "role": "user",
                "content": user["content"],
                "ts": user.get("ts") or 0,
            },
            {
                "role": "assistant",
                "content": assistant["content"],
                "ts": assistant.get("ts") or 0,
            },
        ))
    return result


def _event_time(user: dict, assistant: dict, fallback: datetime) -> str:
    raw = assistant.get("ts") or user.get("ts") or 0
    try:
        value = float(raw)
        if value > 10_000_000_000:
            value /= 1000
        if value > 0:
            return _iso(datetime.fromtimestamp(value, tz=timezone.utc))
    except (ValueError, TypeError, OSError):
        pass
    return _iso(fallback)


def _classify_experiences(user_text: str, assistant_text: str) -> list[str]:
    """Classify only an occurred or mutually acknowledged experience.

    The user mentioning a desired action is only a candidate.  A refusal, a
    negated recollection, or a hypothetical must not become a permanent
    ``not-first-time`` milestone.
    """

    categories: list[str] = []
    for category, cues in _EXPERIENCE_PATTERNS:
        user_hit = _has_unnegated_cue(user_text, cues)
        assistant_hit = _has_unnegated_cue(assistant_text, cues)
        assistant_mentions_category = any(cue in assistant_text for cue in cues)
        assistant_accepts = _has_unnegated_cue(
            assistant_text,
            _EXPERIENCE_ACCEPTANCE_CUES,
        )
        past_recollection = (
            user_hit
            and any(cue in user_text for cue in _PAST_EXPERIENCE_CUES)
            and _has_unnegated_cue(
                assistant_text,
                _EXPERIENCE_RECOLLECTION_ACCEPTANCE_CUES,
            )
        )
        if assistant_mentions_category and not assistant_hit:
            continue
        if _contains_experience_rejection(assistant_text) and not assistant_hit:
            continue
        if assistant_hit or (user_hit and assistant_accepts) or (
            past_recollection and not _contains_relationship_rejection(assistant_text)
        ):
            categories.append(category)
    # A specific private category subsumes the generic fallback in the same turn.
    if "other_private" in categories and len(categories) > 1:
        categories.remove("other_private")
    return categories


def _mutual_event(user_text: str, assistant_text: str) -> str | None:
    # A hypothetical answer or a third party's wedding is not the user's
    # relationship decision, regardless of generic words like “我愿意”.
    if _HYPOTHETICAL_RELATIONSHIP.search(user_text + "\n" + assistant_text):
        return None
    user_breakup = (
        _has_unnegated_cue(user_text, _BREAKUP_CUES)
        and _is_direct_relationship_redefinition_request(user_text)
    )
    if (
        user_breakup
        and not _contains_relationship_rejection(assistant_text)
        and _has_unnegated_cue(assistant_text, _BREAKUP_ACCEPTANCE)
    ):
        return "relationship_redefined"
    if _contains_relationship_rejection(user_text) or _contains_relationship_rejection(assistant_text):
        return None
    marriage = _has_unnegated_cue(user_text, _MARRIAGE_CUES) and bool(_DIRECT_MARRIAGE.search(user_text))
    if marriage and _has_unnegated_cue(assistant_text, _MARRIAGE_ACCEPTANCE):
        return "marriage_commitment"
    future = _has_unnegated_cue(user_text, _FUTURE_CUES)
    if future and _has_unnegated_cue(assistant_text, _FUTURE_ACCEPTANCE):
        return "shared_future"
    affection = _has_unnegated_cue(user_text, _USER_AFFECTION)
    if affection and _has_unnegated_cue(assistant_text, _ASSISTANT_AFFECTION):
        return "mutual_affection"
    return None


def _apply_relationship_event(relationship: dict[str, Any], event: str, character_id: str) -> None:
    dimensions = relationship["dimensions"]
    target_level = relationship["level"]
    if event == "mutual_affection":
        target_level = max(target_level, LEVEL_MUTUAL_AFFECTION)
        dimensions["familiarity"] = max(dimensions["familiarity"], 3)
        dimensions["trust"] = max(dimensions["trust"], 2)
        dimensions["affection"] = max(dimensions["affection"], 2)
        dimensions["commitment"] = max(dimensions["commitment"], 1)
    elif event == "shared_future":
        target_level = max(target_level, LEVEL_SHARED_FUTURE)
        dimensions["familiarity"] = max(dimensions["familiarity"], 3)
        dimensions["trust"] = max(dimensions["trust"], 3)
        dimensions["affection"] = max(dimensions["affection"], 3)
        dimensions["commitment"] = max(dimensions["commitment"], 3)
    elif event in {"marriage_commitment", "eternal_covenant"}:
        target_level = LEVEL_LIFELONG
        for key in dimensions:
            dimensions[key] = 4
        # A later, equally explicit lifelong commitment supersedes a previous
        # mutually confirmed redefinition.  Lesser milestones do not silently
        # restore the built-in calibration floor.
        relationship["confirmed_events"] = [
            item for item in relationship["confirmed_events"]
            if item != "relationship_redefined"
        ]
        if character_id in INITIAL_RELATIONSHIPS:
            relationship["title"] = INITIAL_RELATIONSHIPS[character_id]["title"]
    elif event == "relationship_redefined":
        # Only a mutually acknowledged redefinition is allowed to lower a stage.
        target_level = min(target_level, 4)
        dimensions["affection"] = min(dimensions["affection"], 1)
        dimensions["commitment"] = 0
        relationship["commitments"] = []

    relationship["level"] = target_level
    relationship["stage"] = _stage(target_level)
    if character_id not in INITIAL_RELATIONSHIPS or event == "relationship_redefined":
        relationship["title"] = _stage(target_level)
    if event not in relationship["confirmed_events"]:
        relationship["confirmed_events"].append(event)
    durable_by_event = {
        "shared_future": "双方已经确认共同走向未来的心愿。",
        "marriage_commitment": "双方已经确认婚约或结婚承诺。",
        "eternal_covenant": "双方已经确认彼此的终身契约。",
    }
    if event in durable_by_event:
        relationship["commitments"] = _durable_commitments(
            [*relationship.get("commitments", []), durable_by_event[event]],
            character_id=character_id,
            limit=16,
        )


def _merge_legacy_facts(
    context: dict[str, Any],
    *,
    character_id: str,
    old_memory: str,
    old_memory_context: str,
    old_relationship: dict,
) -> None:
    stable: list[object] = list(context["stable_facts"])
    relationship_facts: list[object] = []
    try:
        parsed = json.loads(old_memory_context or "{}")
    except json.JSONDecodeError:
        parsed = {}
    if isinstance(parsed, dict):
        stable.extend(parsed.get("stable_facts", []))
        relationship_facts.extend(parsed.get("relationship_facts", []))

    # The old free-form memory is retained on disk but is not copied verbatim.
    for line in str(old_memory or "").splitlines():
        clean = _clean(line)
        if not clean or any(cue in clean for cue in EXPLICIT_CONTENT_CUES):
            continue
        if any(cue in clean for cue in ("约定", "承诺", "婚约", "结婚", "关系", "称呼")):
            relationship_facts.append(clean)
        elif clean.startswith(("用户", "- 用户")):
            stable.append(clean)

    rel = context["relationship"]
    aliases = aliases_for_character(character_id)
    self_aliases = set(aliases)
    facts = _unique_texts(relationship_facts, limit=24)

    inferred_role_to_user: list[str] = []
    inferred_user_to_role: list[str] = []
    for fact in facts:
        direction = _address_fact_direction(fact, aliases=aliases)
        if not direction:
            continue
        extracted = _quoted_addresses(fact)
        if direction == "user_to_character":
            inferred_user_to_role.extend(extracted)
        else:
            inferred_role_to_user.extend(extracted)

    explicit_role_to_user: list[str] = []
    explicit_user_to_role: list[str] = []
    if isinstance(old_relationship, dict):
        for key in _ROLE_TO_USER_ADDRESS_KEYS:
            explicit_role_to_user.extend(_split_addresses(old_relationship.get(key)))
        for key in _USER_TO_CHARACTER_ADDRESS_KEYS:
            explicit_user_to_role.extend(_split_addresses(old_relationship.get(key)))

    # Reconcile already-persisted v21 data too.  This repairs generic reversed
    # nicknames such as “宝宝”, not just aliases like “阿萤”.
    existing_role_to_user = _split_addresses(rel.get("forms_of_address", []))
    existing_user_to_role = _split_addresses(rel.get("user_forms_of_address", []))
    for candidate in existing_role_to_user:
        if candidate in self_aliases or (
            candidate in inferred_user_to_role and candidate not in inferred_role_to_user
        ):
            existing_user_to_role.append(candidate)
        else:
            explicit_role_to_user.append(candidate)

    # The pre-v21 UI stored both directions in one "address" field.  Prefer
    # explicit memory evidence; a character's own alias is always user -> role.
    # If no direction can be recovered, retain the historical role -> user
    # interpretation for compatibility instead of silently deleting user data.
    if isinstance(old_relationship, dict):
        for key in _LEGACY_ADDRESS_KEYS:
            for candidate in _split_addresses(old_relationship.get(key)):
                if candidate in self_aliases or (
                    candidate in inferred_user_to_role and candidate not in inferred_role_to_user
                ):
                    explicit_user_to_role.append(candidate)
                else:
                    explicit_role_to_user.append(candidate)

    rel["forms_of_address"] = [
        item for item in _unique_texts(
            [*inferred_role_to_user, *explicit_role_to_user], limit=12
        )
        if item not in self_aliases
        and not (
            item in inferred_user_to_role
            and item not in inferred_role_to_user
            and item not in explicit_role_to_user
        )
    ]
    rel["user_forms_of_address"] = _unique_texts(
        [*existing_user_to_role, *inferred_user_to_role, *explicit_user_to_role],
        limit=12,
    )
    for key in _BOUNDARY_KEYS:
        if isinstance(old_relationship, dict) and old_relationship.get(key):
            rel["boundaries"] = _unique_texts(
                [*rel["boundaries"], old_relationship[key]], limit=12
            )

    for fact in facts:
        if content_for(character_id).get("staleMarriage") and (
            any(cue in fact for cue in content_for(character_id)["staleMarriage"]["cues"])
            and any(cue in fact for cue in _MARRIAGE_CUES)
        ):
            if content_for(character_id)["staleMarriage"]["key"] not in rel["invalidated_facts"]:
                rel["invalidated_facts"].append(content_for(character_id)["staleMarriage"]["key"])
            continue
        if any(cue in fact for cue in ("约定", "承诺", "婚约", "结婚", "契约", "余生")):
            rel["commitments"] = _durable_commitments(
                [*rel["commitments"], fact],
                character_id=character_id,
                limit=16,
            )

    context["stable_facts"] = _unique_stable_facts(stable, limit=24)
    context["recent_events"] = []


def consolidate_companion_context(
    character_id: str,
    current_context: object,
    *,
    old_memory: str = "",
    old_memory_context: str = "",
    old_relationship: dict | None = None,
    old_intimacy: float | None = None,
    current_messages: list[dict] | None = None,
    archived_sessions: list[dict] | None = None,
    reason: str = "periodic",
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate and merge relationship/memory candidates from complete turn pairs."""

    captured = now or _utc_now()
    context = normalize_companion_context(character_id, current_context, now=captured)
    previous_level = int(context["relationship"]["level"])
    _merge_legacy_facts(
        context,
        character_id=character_id,
        old_memory=old_memory,
        old_memory_context=old_memory_context,
        old_relationship=old_relationship or {},
    )

    processed_order = list(context["migration"]["processed_segments"])
    processed = set(processed_order)
    new_processed = 0
    completed_pair_count = 0
    milestones = {item["category"]: item for item in context["experience_milestones"]}

    for session_id, messages in _deduplicated_sessions(
        current_messages or [], archived_sessions or []
    ):
        for index, (user, assistant) in enumerate(_complete_pairs(messages)):
            segment_identity: dict[str, Any] = {
                "user": user["content"],
                "assistant": assistant["content"],
                "user_ts": user.get("ts") or 0,
                "assistant_ts": assistant.get("ts") or 0,
            }
            # Timestamped turns retain the same identity even if an archive
            # copy gains/loses a leading UI-only message.  Timestamp-less
            # fixtures still distinguish genuinely repeated pairs by session.
            if not segment_identity["user_ts"] and not segment_identity["assistant_ts"]:
                segment_identity.update({"session": session_id, "index": index})
            segment_id = _fingerprint(segment_identity)
            if segment_id in processed:
                continue
            processed.add(segment_id)
            processed_order.append(segment_id)
            new_processed += 1
            completed_pair_count += 1
            when = _event_time(user, assistant, captured)

            for category in _classify_experiences(user["content"], assistant["content"]):
                evidence_id = _fingerprint({"segment": segment_id, "category": category})
                item = milestones.get(category)
                if item is None:
                    item = {
                        "category": category,
                        "first_at": when,
                        "last_at": when,
                        "frequency": "once",
                        "evidence_ids": [],
                    }
                    milestones[category] = item
                if evidence_id not in item["evidence_ids"]:
                    item["evidence_ids"].append(evidence_id)
                    item["evidence_ids"] = item["evidence_ids"][-64:]
                    item["last_at"] = when
                    if not item["first_at"]:
                        item["first_at"] = when
                count = len(item["evidence_ids"])
                item["frequency"] = "many" if count >= 5 else "several" if count >= 2 else "once"

            event = _mutual_event(user["content"], assistant["content"])
            if event:
                _apply_relationship_event(context["relationship"], event, character_id)

    # Message quantity can only increase familiarity and can never establish Lv.5+.
    if completed_pair_count:
        total_pair_count = len(processed)
        familiarity_by_volume = 1 if total_pair_count < 4 else 2 if total_pair_count < 13 else 3 if total_pair_count < 31 else 4
        dimensions = context["relationship"]["dimensions"]
        dimensions["familiarity"] = max(dimensions["familiarity"], familiarity_by_volume)
        if context["relationship"]["level"] < 5:
            context["relationship"]["level"] = max(
                context["relationship"]["level"],
                min(4, familiarity_by_volume),
            )
            context["relationship"]["stage"] = _stage(context["relationship"]["level"])
            context["relationship"]["title"] = context["relationship"]["stage"]

    # Old intimacy is deliberately not converted to romance; it only supplies familiarity.
    if old_intimacy is not None:
        familiarity = min(4, max(0, int(float(old_intimacy) // 2.5)))
        context["relationship"]["dimensions"]["familiarity"] = max(
            context["relationship"]["dimensions"]["familiarity"], familiarity
        )
        if character_id not in INITIAL_RELATIONSHIPS and context["relationship"]["level"] < 5:
            context["relationship"]["level"] = max(context["relationship"]["level"], familiarity or 1)
            context["relationship"]["stage"] = _stage(context["relationship"]["level"])
            context["relationship"]["title"] = context["relationship"]["stage"]

    context["experience_milestones"] = [milestones[key] for key in EXPERIENCE_LABELS if key in milestones]
    context["migration"]["processed_segments"] = processed_order[-4096:]
    if reason == "migration":
        context["migration"]["completed"] = True
        context["migration"]["migrated_at"] = _iso(captured)
    context["relationship"]["updated_at"] = _iso(captured)
    context["updated_at"] = _iso(captured)
    context = normalize_companion_context(character_id, context, now=captured)
    result = {
        "previous_level": previous_level,
        "stage_changed": int(context["relationship"]["level"]) != previous_level,
        "processed_segments": new_processed,
    }
    return context, result
