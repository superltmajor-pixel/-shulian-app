"""Select and render stable personality material for the current turn."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Iterable

from ..domain.personality import (
    BehaviorAnchor,
    CharacterOutputRail,
    DialogueExample,
    DynamicPersonalityState,
    PersonalityProfile,
    PersonalityProfileError,
)
from ..repositories.personality_profile_repository import PersonalityProfileRepository


_REPOSITORY = PersonalityProfileRepository()
_EXPLICIT_CHARACTER_COMPARISON_CUES = (
    "像你",
    "好像你",
    "有点像你",
    "让我想到你",
    "让我想起你",
)
_RELATIONSHIP_TRIGGER_CUES = {
    "喜欢": (
        "喜欢你",
        "喜欢我",
        "喜欢上你",
        "喜欢上我",
        "对你有好感",
        "对我有好感",
    ),
    "爱": (
        "爱你",
        "爱我",
        "爱上你",
        "爱上我",
        "爱着你",
        "爱着我",
        "相爱",
        "爱情",
        "恋爱",
    ),
    "陪": (
        "陪你",
        "陪我",
        "陪着你",
        "陪着我",
        "陪伴你",
        "陪伴我",
        "陪在你",
        "陪在我",
    ),
    "抱": (
        "抱你",
        "抱我",
        "抱抱",
        "拥抱你",
        "拥抱我",
        "想抱你",
        "想抱我",
        "抱一下",
        "抱一抱",
    ),
    "吻": (
        "吻你",
        "吻我",
        "亲吻你",
        "亲吻我",
        "接吻",
        "吻一下",
    ),
    "亲": (
        "亲你",
        "亲我",
        "亲亲",
        "亲一下",
        "亲一口",
        "亲吻",
    ),
}


@dataclass(frozen=True)
class PersonalitySelection:
    profile: PersonalityProfile | None
    anchors: tuple[BehaviorAnchor, ...]
    examples: tuple[DialogueExample, ...]
    dynamic_states: tuple[DynamicPersonalityState, ...] = ()
    affect: "PersonalityAffectState | None" = None


@dataclass(frozen=True)
class PersonalityPromptLayers:
    stable: str
    turn: str
    affect: "PersonalityAffectState | None" = None


@dataclass(frozen=True)
class PersonalityAffectState:
    mode: str
    relationship_level: int
    felt_safety: int
    activation: int
    self_control: int
    vulnerability: int
    initiative: int


_AFFECT_WINDOW_SECONDS = 45 * 60
_BOUNDARY_CUES = ("停下", "不要这样", "别碰", "不愿意", "我拒绝", "让我不舒服", "越界了")
_REPAIR_CUES = ("对不起", "抱歉", "和好", "原谅", "重新说", "重新来", "说清楚")
_CONFLICT_CUES = ("生气", "吵架", "伤到我", "难受", "误会", "不舒服", "越界")
_VULNERABLE_CUES = ("撑不住", "害怕", "想哭", "很累", "难过", "低落", "需要你", "不想一个人")
_INTIMATE_CUES = (
    "喜欢你", "爱你", "想你", "需要我", "需要你", "抱抱我", "抱住我", "抱紧我", "吻我", "亲我",
    "靠近我", "靠近一点", "靠过来", "想要你", "亲密", "接吻", "在一起", "不想你离开",
)
_HIGH_ACTIVATION_CUES = ("忍不住", "控制不住", "心跳", "呼吸", "颤", "失控", "迫不及待", "想要你")
_RELAXED_CUES = ("散步", "休息", "靠一会", "安静待着", "吃饭", "看电影", "睡前", "放松")
_REINTEGRATING_CUES = (
    "缓一会", "缓过来", "平静下来", "情绪缓", "抱一会", "还好吗", "刚才的你", "安静一下", "歇一会",
)


def _message_timestamp_seconds(item: dict) -> float:
    try:
        value = float(item.get("ts") or 0)
        return value / 1000 if value > 10_000_000_000 else value
    except (TypeError, ValueError):
        return 0


def _recent_user_text(user_message: str, history: Iterable[dict]) -> str:
    now = datetime.now(timezone.utc).timestamp()
    recent: list[str] = []
    for item in list(history)[-10:]:
        if item.get("role") != "user":
            continue
        stamp = _message_timestamp_seconds(item)
        if stamp and (stamp > now + 60 or now - stamp > _AFFECT_WINDOW_SECONDS):
            continue
        text = str(item.get("content") or "").strip()
        if text:
            recent.append(text)
    return "\n".join([*recent[-4:], str(user_message or "").strip()])


def _relationship_values(companion_context: object) -> tuple[int, int, int]:
    relationship = (
        companion_context.get("relationship", {})
        if isinstance(companion_context, dict) else {}
    )
    dimensions = relationship.get("dimensions", {}) if isinstance(relationship, dict) else {}
    try:
        level = min(10, max(1, int(relationship.get("level") or 1)))
    except (TypeError, ValueError):
        level = 1
    def bounded(name: str) -> int:
        try:
            return min(4, max(0, int(dimensions.get(name) or 0)))
        except (TypeError, ValueError):
            return 0
    return level, bounded("trust"), bounded("affection")


def infer_personality_affect(
    user_message: str,
    history: Iterable[dict],
    companion_context: object = None,
) -> PersonalityAffectState:
    """Infer a small, decaying turn state without converting emotion into relationship fact."""

    text = _recent_user_text(user_message, history)
    current = str(user_message or "")
    level, trust, affection = _relationship_values(companion_context)
    boundary = any(cue in current for cue in _BOUNDARY_CUES)
    repair = any(cue in text for cue in _REPAIR_CUES)
    conflict = any(cue in text for cue in _CONFLICT_CUES)
    intimate = sum(cue in text for cue in _INTIMATE_CUES)
    vulnerable = sum(cue in text for cue in _VULNERABLE_CUES)
    high = sum(cue in text for cue in _HIGH_ACTIVATION_CUES)
    relaxed = any(cue in text for cue in _RELAXED_CUES)
    reintegrating = any(cue in current for cue in _REINTEGRATING_CUES)

    activation = min(4, intimate + vulnerable + high * 2 + int(conflict))
    felt_safety = min(4, trust + int(affection >= 3) + int(intimate > 0))
    if boundary:
        felt_safety = max(0, felt_safety - 2)
    exposed = min(4, vulnerable + intimate + max(0, felt_safety - 2))
    initiative = min(4, affection + int("想要" in text or "靠近" in text))
    self_control = min(4, max(0, 4 - activation + int(felt_safety < 2)))

    if boundary:
        mode = "boundary"
    elif repair or conflict:
        mode = "repair"
    elif reintegrating:
        mode = "reintegrating"
    elif intimate and level >= 5:
        mode = "intimate"
    elif vulnerable:
        mode = "vulnerable"
    elif relaxed:
        mode = "relaxed"
    else:
        mode = "daily"
    return PersonalityAffectState(
        mode=mode,
        relationship_level=level,
        felt_safety=felt_safety,
        activation=activation,
        self_control=self_control,
        vulnerability=exposed,
        initiative=initiative,
    )


def _weighted_segments(user_message: str, history: Iterable[dict]) -> list[tuple[int, str]]:
    segments: list[tuple[int, str]] = [(6, str(user_message or "").casefold())]
    recent = [
        str(item.get("content") or "").casefold()
        for item in history
        if item.get("role") == "user"
    ][-8:]
    for age, text in enumerate(reversed(recent), start=1):
        segments.append((max(1, 4 - age // 2), text))
    return segments


def _trigger_matches(trigger: str, text: str) -> bool:
    normalized_trigger = str(trigger or "").strip().casefold()
    normalized_text = str(text or "").casefold()
    if not normalized_trigger:
        return False
    cues = _RELATIONSHIP_TRIGGER_CUES.get(normalized_trigger)
    if cues is None:
        return normalized_trigger in normalized_text
    return any(cue in normalized_text for cue in cues)


def _relevance_score(triggers: tuple[str, ...], segments: list[tuple[int, str]]) -> int:
    if not triggers:
        return 0
    return sum(
        weight
        for trigger in triggers
        for weight, text in segments
        if _trigger_matches(trigger, text)
    )


def _select_ranked(
    items: Iterable[Any],
    segments: list[tuple[int, str]],
    *,
    limit: int,
) -> tuple[Any, ...]:
    ranked: list[tuple[int, int, str, Any]] = []
    defaults: list[tuple[int, str, Any]] = []
    for item in items:
        relevance = _relevance_score(item.triggers, segments)
        if relevance:
            ranked.append((relevance, item.priority, item.id, item))
        elif not item.triggers:
            defaults.append((item.priority, item.id, item))
    ranked.sort(key=lambda value: (-value[0], -value[1], value[2]))
    defaults.sort(key=lambda value: (-value[0], value[1]))
    selected = [item for _, _, _, item in ranked[:limit]]
    if len(selected) < limit:
        selected.extend(item for _, _, item in defaults[: limit - len(selected)])
    return tuple(selected)


def _example_similarity_penalty(example: DialogueExample, history: Iterable[dict]) -> int:
    recent = [
        str(item.get("content") or "").strip()
        for item in list(history)[-10:]
        if item.get("role") == "assistant" and str(item.get("content") or "").strip()
    ][-5:]
    if not recent:
        return 0
    similarity = max(
        SequenceMatcher(None, example.assistant, text[:600]).ratio()
        for text in recent
    )
    return 35 if similarity >= 0.62 else 18 if similarity >= 0.46 else 0


def _select_examples(
    items: Iterable[DialogueExample],
    segments: list[tuple[int, str]],
    history: Iterable[dict],
    *,
    user_message: str,
    channel: str,
    image_subject_relation: str | None,
    limit: int = 2,
) -> tuple[DialogueExample, ...]:
    ranked: list[tuple[int, int, int, str, DialogueExample]] = []
    current_message = str(user_message or "").casefold()
    resolved_relation = str(image_subject_relation or "unknown")
    for item in items:
        if item.channels and channel not in item.channels:
            continue
        # An image turn may only use examples authored for media.  A generic
        # default dialogue can otherwise bias an uncaptioned image just as much
        # as an incorrectly selected media comparison.
        if channel == "image" and item.scenario != "media":
            continue
        if (
            channel == "image"
            and item.subject_relations
            and resolved_relation not in item.subject_relations
        ):
            continue
        if item.requires_explicit_comparison and not (
            resolved_relation == "user_compares_character"
            or any(cue in current_message for cue in _EXPLICIT_CHARACTER_COMPARISON_CUES)
        ):
            continue
        relevance = _relevance_score(item.triggers, segments)
        if not relevance and item.triggers:
            continue
        score = relevance * 20 + item.priority - _example_similarity_penalty(item, history)
        ranked.append((score, relevance, item.priority, item.id, item))
    ranked.sort(key=lambda value: (-value[0], -value[1], -value[2], value[3]))
    selected: list[DialogueExample] = []
    scenarios: set[str] = set()
    for _, _, _, _, item in ranked:
        if item.scenario in scenarios:
            continue
        selected.append(item)
        scenarios.add(item.scenario)
        if len(selected) >= limit:
            break
    return tuple(selected)


def _select_dynamic_states(
    items: Iterable[DynamicPersonalityState],
    affect: PersonalityAffectState,
) -> tuple[DynamicPersonalityState, ...]:
    eligible = [
        item for item in items
        if item.mode == affect.mode
        and item.relationship_floor <= affect.relationship_level
        and item.activation_floor <= affect.activation
    ]
    eligible.sort(key=lambda item: (-item.priority, item.id))
    return tuple(eligible[:1])


def select_personality_material(
    character_id: str,
    user_message: str,
    history: Iterable[dict],
    *,
    repository: PersonalityProfileRepository | None = None,
    channel: str = "text",
    image_subject_relation: str | None = None,
    companion_context: object = None,
) -> PersonalitySelection:
    affect = infer_personality_affect(user_message, history, companion_context)
    try:
        profile = (repository or _REPOSITORY).load(character_id)
    except PersonalityProfileError:
        return PersonalitySelection(profile=None, anchors=(), examples=(), affect=affect)
    segments = _weighted_segments(user_message, history)
    anchors = _select_ranked(profile.behavior_anchors, segments, limit=2)
    examples = _select_examples(
        profile.dialogue_examples,
        segments,
        history,
        user_message=user_message,
        channel=channel,
        image_subject_relation=image_subject_relation,
        limit=2,
    )
    return PersonalitySelection(
        profile=profile,
        anchors=anchors,
        examples=examples,
        dynamic_states=_select_dynamic_states(profile.dynamic_states, affect),
        affect=affect,
    )


def build_personality_layers(
    character: Any,
    user_message: str,
    history: Iterable[dict],
    *,
    channel: str = "text",
    image_subject_relation: str | None = None,
    companion_context: object = None,
) -> PersonalityPromptLayers:
    selection = select_personality_material(
        character.id,
        user_message,
        history,
        channel=channel,
        image_subject_relation=image_subject_relation,
        companion_context=companion_context,
    )
    profile = selection.profile
    if profile is None:
        tags = "、".join(str(item) for item in getattr(character, "tags", []) if str(item))
        fallback = (
            "【结构化人格档案（自定义角色回退）】\n"
            f"- 核心设定：{getattr(character, 'persona', character.name)}。\n"
            + (f"- 性格标签：{tags}。\n" if tags else "")
            + "- 只按角色档案、当前场景和用户真实表达作出选择；不知道的事实不补写。"
        )
        return PersonalityPromptLayers(stable=fallback, turn="", affect=selection.affect)

    stable_sections = [
        "【稳定人格层】以下条目来自经校验的官方角色资料，只规定稳定人格，不替代当前场景。",
        "核心特质：\n" + "\n".join(f"- {item.text}" for item in profile.core_traits),
        "价值与动机：\n" + "\n".join(f"- {item.text}" for item in profile.values),
        "表达原则：\n" + "\n".join(f"- {item.text}" for item in profile.voice),
    ]
    if profile.inner_dynamics:
        stable_sections.append(
            "内在动力（包含有来源标记的合理角色推演，不是原作事件）：\n"
            + "\n".join(f"- {item.text}" for item in profile.inner_dynamics)
        )
    turn_sections: list[str] = []
    if selection.anchors:
        turn_sections.append(
            "【本轮人格锚点】只用于决定这一轮的立场与表达，不改变稳定身份。\n"
            + "\n".join(f"- {item.instruction}" for item in selection.anchors)
        )
    if selection.examples:
        examples = []
        for item in selection.examples:
            examples.append(
                f"用户：{item.user}\n{profile.display_name}：{item.assistant}"
            )
        rendered_examples = "\n\n".join(examples)
        turn_sections.append(
            "【官方素材驱动的表达示例】只学习语气、节奏和决策方式；"
            "不是当前历史事实，不得照抄或把示例情节带入本轮。\n"
            + rendered_examples[:1_200]
        )
    if selection.dynamic_states and selection.affect is not None:
        affect = selection.affect
        turn_sections.append(
            "【本轮动态人格】这是短时表达状态，不是永久关系事实，也不能替用户决定感受或同意。\n"
            f"- 状态：{affect.mode}；安全感 {affect.felt_safety}/4；情绪唤醒 {affect.activation}/4；"
            f"自我控制 {affect.self_control}/4；脆弱外显 {affect.vulnerability}/4；主动性 {affect.initiative}/4。\n"
            + "\n".join(f"- {item.instruction}" for item in selection.dynamic_states)
        )
    if profile.closing_styles:
        turn_sections.append(
            "【角色化收尾】不要机械逐条执行；根据本轮内容任选合适方式，也允许回应完成后直接停住。"
            "结尾应保留这个角色的具体判断、选择、细节或节奏，避免只换一种说法宣布‘我在这里’。\n"
            + "\n".join(f"- {item.text}" for item in profile.closing_styles)
        )
    return PersonalityPromptLayers(
        stable="\n\n".join(stable_sections),
        turn="\n\n".join(turn_sections),
        affect=selection.affect,
    )


def build_personality_context(
    character: Any,
    user_message: str,
    history: Iterable[dict],
    *,
    channel: str = "text",
    image_subject_relation: str | None = None,
    companion_context: object = None,
) -> str:
    """Compatibility renderer for prompt previews and existing callers."""

    layers = build_personality_layers(
        character,
        user_message,
        history,
        channel=channel,
        image_subject_relation=image_subject_relation,
        companion_context=companion_context,
    )
    return "\n\n".join(part for part in (layers.stable, layers.turn) if part)


def character_output_rails(character_id: str) -> tuple[CharacterOutputRail, ...]:
    try:
        return _REPOSITORY.load(character_id).output_rails
    except PersonalityProfileError:
        return ()


def matching_character_output_rails(
    character_id: str,
    text: str,
) -> tuple[CharacterOutputRail, ...]:
    candidate = str(text or "")
    return tuple(
        rail
        for rail in character_output_rails(character_id)
        if any(phrase in candidate for phrase in rail.phrases)
    )


def character_output_repair_guidance(character_id: str, text: str = "") -> str:
    rails = (
        matching_character_output_rails(character_id, text)
        if text
        else character_output_rails(character_id)
    )
    instructions = dict.fromkeys(
        rail.repair_instruction for rail in rails
    )
    return "".join(instructions)


def personality_profile_status(character_ids: object = None) -> dict:
    expected = {str(value) for value in (character_ids or ()) if str(value).strip()}
    try:
        profiles = _REPOSITORY.load_all()
    except PersonalityProfileError:
        if not _REPOSITORY.root.exists():
            return {
                "ok": True,
                "configured": False,
                "count": 0,
                "reviewed_count": 0,
                "missing_character_ids": sorted(expected),
                "error": None,
            }
        return {
            "ok": False,
            "configured": True,
            "count": 0,
            "reviewed_count": 0,
            "missing_character_ids": sorted(expected),
            "error": "unavailable",
        }
    statuses = [profile.status for profile in profiles.values()]
    valid = all(
        profile.status == "reviewed"
        and profile.output_rails
        and profile.dialogue_examples
        and (
            profile.schema_version < 4
            or (profile.inner_dynamics and profile.dynamic_states and profile.closing_styles)
        )
        for profile in profiles.values()
    )
    return {
        "ok": valid,
        "configured": bool(profiles),
        "count": len(profiles),
        "reviewed_count": statuses.count("reviewed"),
        "missing_character_ids": sorted(expected - set(profiles)),
        "error": None,
    }
