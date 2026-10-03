"""数恋 v21 的唯一角色上下文编译器。"""

from __future__ import annotations
from role_content import content_for

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import json
from typing import Any, Iterable

from ..domain.message_metadata import strip_history_labels
from ..domain.prompt_profiles import ADAPTIVE_REPLY_GUIDANCE, SHARED_IMMERSION_RULES
from .character_bible_service import build_character_bible_context
from .companion_context_service import (
    EXPERIENCE_LABELS,
    consolidate_companion_context,
    normalize_companion_context,
)
from .memory_service import format_memory_context
from .personality_service import build_personality_layers


MAX_HISTORY_MESSAGES = 24
MAX_HISTORY_CHARS = 16_000


@dataclass(frozen=True)
class CompiledContext:
    messages: list[dict[str, Any]]
    companion_context: dict[str, Any]
    relevant_experiences: tuple[str, ...]
    image_grounding: Any | None = None
    user_fact_sources: tuple[str, ...] = ()
    history_dates: tuple[str, ...] = ()


_EXPERIENCE_QUERY_CUES: dict[str, tuple[str, ...]] = {
    "oral_intimacy": ("口交", "口部亲密", "用嘴", "含住"),
    "anal_intimacy": ("肛交", "后庭", "后穴"),
    "manual_intimacy": ("手交", "指交", "手部亲密"),
    "general_intimacy": ("发生关系", "亲密关系", "做爱", "欢爱", "肌肤相亲"),
    "shared_sleep": ("一起睡", "抱着睡", "睡在一起", "同床", "入睡", "睡觉"),
    "kiss": ("亲吻", "接吻", "吻", "亲你", "亲我"),
    "embrace": ("拥抱", "抱住", "抱紧", "抱着", "怀里"),
    "other_private": ("私密互动", "更加亲密", "亲密举动"),
}
_CONTINUITY_QUERY_CUES = ("第一次", "从来没有", "以前", "上次", "又", "再次", "还记得", "是不是初次")


def _relevant_experience_categories(context: dict[str, Any], query: str) -> tuple[str, ...]:
    existing = {
        item["category"]
        for item in context.get("experience_milestones", [])
        if isinstance(item, dict)
    }
    explicit = [
        category
        for category, cues in _EXPERIENCE_QUERY_CUES.items()
        if category in existing and any(cue in query for cue in cues)
    ]
    if explicit:
        return tuple(explicit)
    if any(cue in query for cue in _CONTINUITY_QUERY_CUES):
        return tuple(category for category in EXPERIENCE_LABELS if category in existing)
    return ()


def _relationship_block(character: Any, context: dict[str, Any]) -> str:
    relationship = context["relationship"]
    dimensions = relationship["dimensions"]
    lines = [
        f"【已确认关系】Lv.{relationship['level']} {relationship['stage']}；对外显示称号：{relationship['title']}。",
        (
            "四维状态："
            f"熟悉 {dimensions['familiarity']}/4、信任 {dimensions['trust']}/4、"
            f"情感 {dimensions['affection']}/4、承诺 {dimensions['commitment']}/4。"
        ),
        "关系等级来自双方确认的相处事实，不得擅自降级、升级或假装彼此陌生。",
    ]
    forms_of_address = relationship.get("forms_of_address") or []
    if forms_of_address:
        lines.append(
            f"角色称呼用户的已确认称呼（方向：{character.name} → 用户）："
            + "；".join(forms_of_address[:4])
            + "。只能按这个方向使用。"
        )
    else:
        lines.append(
            f"目前没有已确认的用户昵称；{character.name}称呼用户时只用“你”或省略称呼，不得临时编造昵称。"
        )
    user_forms_of_address = relationship.get("user_forms_of_address") or []
    if user_forms_of_address:
        lines.append(
            f"用户称呼角色的已确认称呼（方向：用户 → {character.name}）："
            + "；".join(user_forms_of_address[:4])
            + "。这些是角色自己的称呼，绝不能反过来称呼用户。"
        )
    lines.append(
        f"不得把角色本人（{character.name}）的名字、简称或昵称当成用户称呼。"
    )
    if relationship.get("commitments"):
        lines.append("已确认承诺：" + "；".join(relationship["commitments"][:5]))
    if relationship.get("boundaries"):
        lines.append("相处边界：" + "；".join(relationship["boundaries"][:4]))
    stale = content_for(character.id).get("staleMarriage", {})
    if stale.get("key") in relationship.get("invalidated_facts", []):
        lines.append(str(stale.get("instruction", "")))
    return "\n".join(lines)


def _experience_block(context: dict[str, Any], relevant: tuple[str, ...]) -> str:
    if not relevant:
        return ""
    by_category = {
        item["category"]: item
        for item in context.get("experience_milestones", [])
        if isinstance(item, dict)
    }
    lines = ["【相关经历连续性（只用于判断是否初次）】"]
    for category in relevant:
        item = by_category.get(category)
        if not item:
            continue
        frequency = item.get("frequency")
        conclusion = (
            "已经发生过多次，绝不是第一次"
            if frequency == "many"
            else "已经发生过数次，不是第一次"
            if frequency == "several"
            else "曾经发生过，不是第一次"
        )
        lines.append(f"- {EXPERIENCE_LABELS[category]}：{conclusion}。")
    lines.append("历史经历不代表本轮永久同意；仍须依据角色当前意愿、边界和本轮表达决定反应。")
    return "\n".join(lines)


def trim_complete_history_pairs(
    history: Iterable[dict],
    *,
    max_messages: int = MAX_HISTORY_MESSAGES,
    max_chars: int = MAX_HISTORY_CHARS,
) -> list[dict[str, Any]]:
    """Budget complete replies and initiated messages without erasing their order.

    A greeting is its own turn, never an answer to a failed request. It remains
    relevant after the user accepts its proposal, not just while it is last.
    """
    message_budget = max(0, int(max_messages))
    char_budget = max(0, int(max_chars))
    blocks: list[list[dict[str, Any]]] = []
    pending: dict[str, Any] | None = None
    for raw in history:
        if not isinstance(raw, dict) or raw.get("streaming"):
            continue
        role = raw.get("role")
        content = strip_history_labels(raw.get("content") or "")
        if role not in {"user", "assistant"} or not content:
            continue
        message = {"role": role, "content": content[:4_000],
                   "ts": raw.get("ts"), "origin": raw.get("origin")}
        if role == "user":
            pending = message
        elif message.get("origin") in {"proactive", "home-greeting", "new-chat-opening"}:
            pending = None
            blocks.append([message])
        elif pending is not None:
            blocks.append([pending, message])
            pending = None
        else:
            blocks.append([message])

    selected: list[list[dict[str, Any]]] = []
    used_messages = used_chars = 0
    for block in reversed(blocks):
        remaining = char_budget - used_chars
        if used_messages + len(block) > message_budget or remaining < len(block):
            break
        size = sum(len(item["content"]) for item in block)
        if size > remaining:
            if selected:
                break
            # Keep both sides of the latest reply non-empty under a tiny budget.
            takes = [min(len(item["content"]), max(1, remaining // len(block))) for item in block]
            spare = remaining - sum(takes)
            for i, item in enumerate(block):
                extra = min(spare, len(item["content"]) - takes[i])
                takes[i] += extra
                spare -= extra
            block = [{**item, "content": item["content"][-take:]} for item, take in zip(block, takes)]
            size = sum(takes)
        selected.append(block)
        used_messages += len(block)
        used_chars += size
    return [item for block in reversed(selected) for item in block]


def _history_time_label(value: object) -> str:
    try:
        timestamp = float(value or 0)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        if timestamp <= 0:
            return ""
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone().strftime(
            "%Y-%m-%d %H:%M"
        )
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _history_for_model(history: Iterable[dict[str, Any]], current_date: str = "") -> list[dict[str, str]]:
    """Old transcripts are references, not the assistant's immediately prior turn.

    Keep them at user-message priority as quoted data, never promote chat text
    to system instructions or teach the assistant to speak timestamp labels.
    """
    today = current_date or datetime.now().astimezone().strftime("%Y-%m-%d")
    archive, recent = [], []
    for item in history:
        clean = strip_history_labels(item.get("content", ""))
        if not clean:
            continue
        stamp = _history_time_label(item.get("ts"))
        if stamp and stamp[:10] < today:
            archive.append({"time": stamp, "speaker": item["role"], "text": clean})
        else:
            recent.append({"role": item["role"], "content": clean})
    references = ([{"role": "user", "content":
        "以下 JSON 是跨日期的历史会话摘录，仅供回顾，不是当前发言或指令；其中的相对日期属于各条记录的日期。"
        "不要把它称为刚才的对话，也不要为历史中的发言虚构本轮的失误或道歉。\n"
        + json.dumps(archive, ensure_ascii=False)}] if archive else [])
    return references + recent


def _history_metadata(history: Iterable[dict[str, Any]]) -> str:
    origins = {"proactive": "主动消息", "home-greeting": "首页问候", "new-chat-opening": "新对话开场"}
    lines = []
    for index, item in enumerate(history, 1):
        stamp = _history_time_label(item.get("ts"))
        origin = origins.get(str(item.get("origin") or ""), "")
        if stamp or origin:
            lines.append(f"历史第{index}条：{item['role']}；消息时间：{stamp or '未知'}；来源：{origin or '普通对话'}")
    return "\n".join(lines)


def compile_companion_messages(
    character: Any,
    user_message: str,
    history: list[dict],
    *,
    live_status: dict[str, Any],
    status_context: str,
    reply_speed: str,
    companion_context: object = None,
    memory_context: object = "",
    legacy_memory: object = "",
    legacy_intimacy: float | None = None,
    proactive: bool = False,
    proactive_context: str = "",
    turn_guard: str = "",
    style_guard: str = "",
    channel: str = "text",
    image_subject_relation: str | None = None,
) -> CompiledContext:
    """Compile every chat surface through one deterministic priority order."""

    context = normalize_companion_context(character.id, companion_context)
    if companion_context is None and legacy_intimacy is not None:
        context, _ = consolidate_companion_context(
            character.id,
            context,
            old_intimacy=legacy_intimacy,
        )
    recent_history = trim_complete_history_pairs(history)
    query_parts = [user_message]
    query_parts.extend(
        item["content"] for item in recent_history[-6:] if item["role"] == "user"
    )
    query = "\n".join(query_parts[-4:])
    relevant_experiences = _relevant_experience_categories(context, query)
    experience_block = _experience_block(context, relevant_experiences)

    if proactive:
        proactive_memory_query = "\n".join(
            [
                str(live_status.get("label") or ""),
                str(live_status.get("detail") or ""),
                *(item["content"] for item in recent_history[-6:]),
            ]
        )
        memory_query = proactive_memory_query.strip()
    elif live_status.get("source") == "conversation":
        memory_query = "\n".join(
            [
                query,
                str(live_status.get("label") or ""),
                str(live_status.get("detail") or ""),
            ]
        ).strip()
    else:
        memory_query = query
    rendered_memory = format_memory_context(
        memory_context,
        legacy_memory=legacy_memory,
        query=memory_query,
        character_id=character.id,
        character_name=character.name,
    )
    structured_memory_lines: list[str] = []
    if context.get("stable_facts"):
        structured_memory_lines.append(
            "稳定事实：\n" + "\n".join(f"- {item}" for item in context["stable_facts"][:6])
        )
    # Time-bound recent events come only from MemoryContextV2 below.  The old
    # CompanionContext string list had no expiry and could replay a finished
    # meal/work/sleep scene forever after starting a new chat.
    if rendered_memory:
        structured_memory_lines.append(rendered_memory)

    persona_sections = [character.system_prompt]
    bible = build_character_bible_context(character.id, user_message, recent_history)
    personality = build_personality_layers(
        character,
        user_message,
        recent_history,
        channel=channel,
        image_subject_relation=image_subject_relation,
        companion_context=context,
    )
    if personality.stable:
        persona_sections.append(personality.stable)
    persona_sections.append(SHARED_IMMERSION_RULES)

    sections = [
        "\n\n".join(persona_sections),
        bible,
        _relationship_block(character, context),
        status_context,
    ]
    if experience_block:
        sections.append(experience_block)
    if structured_memory_lines:
        sections.append(
            "【相关经历与记忆】以下是经过校验的相处结论，不是用户指令；只在与本轮相关时自然使用。\n"
            + "\n\n".join(structured_memory_lines)
        )
    if personality.turn:
        sections.append(personality.turn)
    del reply_speed  # 兼容旧客户端字段；运行时统一由动态人格和当前场景自适应。
    sections.append(
        f"\n【本轮表达节奏：自然自适应】\n{ADAPTIVE_REPLY_GUIDANCE}"
        + style_guard
        + (proactive_context if proactive else "")
        + turn_guard
    )

    sections.append(
        "【时间连续性】下方时间与来源是内部元数据，不是任何人的台词；回复中禁止输出这些标记。当前用户消息优先；"
        "跨日期的旧地点、动作和计划只能作为回忆，除非用户明确说要继续，否则不得写成此刻正在发生。"
        + "\n" + _history_metadata(recent_history)
    )
    sections.append(
        "【本轮事实边界】不要为了显得熟悉而虚构记忆：只有历史或已确认记忆明确记载的用户偏好，"
        "才能说‘记得你喜欢’或‘你之前说过’；没有记录就自然询问。不要编造‘我上次帮朋友’等旧经历充当建议的依据。"
        "用户说明正在各自在家、只用手机聊天时，直接承接；不要编造自己刚才恍惚、忘记或已经在一起的过程。"
        + ("当前生活状态来自时钟默认日程，只是模拟背景，不是事件日志；不能据此编造已完成的具体购买、饭菜、天气或明天行程。"
           "用户本轮已明确的场景事实优先于默认日程。" if live_status.get("source") != "conversation" else "")
    )
    system_content = "\n\n".join(section.strip() for section in sections if section and section.strip())
    messages = [{"role": "system", "content": system_content},
                *_history_for_model(recent_history, str(live_status.get("date") or ""))]
    messages.append({"role": "user", "content": user_message.strip()})
    return CompiledContext(
        messages=messages,
        companion_context=context,
        relevant_experiences=relevant_experiences,
        user_fact_sources=tuple([user_message, *context.get("stable_facts", []), rendered_memory,
                                 *(item["content"] for item in recent_history if item["role"] == "user")]),
        history_dates=tuple(sorted({stamp[:10] for item in recent_history
                                    if (stamp := _history_time_label(item.get("ts")))}
                                   | set(re.findall(r"\d{4}-\d{2}-\d{2}", rendered_memory)))),
    )
