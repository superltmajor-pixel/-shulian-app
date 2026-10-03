"""回复一致性检查与高风险草稿修正规则。"""

from __future__ import annotations

import re
from ..domain.message_metadata import has_history_labels
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from diagnostics import log_event
from ..domain.behavior_rails import behavior_rail
from ..domain.character_identity import aliases_for_character
from ..domain.scene_evidence import (
    text_asserts_onsite_action,
    user_permits_onsite_reply,
)
from ..domain.relationship_levels import GUARD_COMMITMENT_LEVEL, GUARD_STAGE_LEVEL
from ..domain.reply_motifs import REPEAT_ENDING_MOTIFS, REPEAT_MOTIFS
from .personality_service import (
    character_output_repair_guidance,
    matching_character_output_rails,
)


@dataclass(frozen=True)
class GuardResult:
    reason_codes: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.reason_codes

    @property
    def hard_reason_codes(self) -> tuple[str, ...]:
        """Rules configured to block delivery until a bounded rewrite succeeds."""

        return tuple(
            code for code in self.reason_codes if behavior_rail(code).blocks_delivery
        )

    @property
    def soft_reason_codes(self) -> tuple[str, ...]:
        """Style-only findings which may request a rewrite but never block delivery."""

        return tuple(
            code for code in self.reason_codes if not behavior_rail(code).blocks_delivery
        )

    @property
    def blocks_delivery(self) -> bool:
        return bool(self.hard_reason_codes)


_FIRST_TIME_CUES = (
    "第一次", "头一回", "从来没有过", "从未有过", "我们还没有过", "以前没有这样",
    "没和你做过", "初次经历",
)
_RELATIONSHIP_RESET_CUES = (
    "我们只是朋友", "我们还不熟", "我不认识你", "第一次见你", "还不算恋人", "和你没有关系",
)
_COMMITMENT_RESET_CUES = ("没有婚约", "没答应过结婚", "不是你的伴侣", "从未承诺过", "没有约定")
_PAST_CALLBACK_CUES = ("昨天", "昨晚", "前天", "上次", "上回", "之前你", "之前我们")
_WORK_CUES = ("批文书", "处理公文", "公务还没", "去开会", "见凝光", "处理事务", "回去工作")
_SCENE_EXIT_CUES = (
    "我先回去了", "我先走了", "我要回去了", "我要走了", "我得回去了", "我得走了",
    "我得离开了", "我先回玉京台", "我回玉京台", "我先回家", "我回去睡",
    "你自己睡", "你先睡，我走了", "你先睡吧，我走了", "等你醒了我再来",
    "等你醒来我再来", "明早我再来", "明天我再来", "明天再来看你",
    "下次再来找你", "等你回来", "等我回来",
)
_USER_WORK_TRANSITION_CUES = (
    "去工作吧", "回去工作吧", "去忙吧", "你先忙", "该工作了", "该上工了",
    "去批文书", "去处理公文", "去处理事务", "去见凝光",
)
_USER_EXIT_TRANSITION_CUES = (
    "你先回去", "你回去吧", "你先走", "你该回去了", "你可以走了", "我先走了",
    "我先回去", "明早见", "一早见", "明天见", "明天再见", "下次见", "下次再见",
)
_AI_CUES = (
    "作为AI", "作为 AI", "我是AI", "我是一个AI", "只是一个AI", "语言模型", "虚拟助手",
    "没有真实感情", "无法真正拥有感情", "无法真正感受到感情",
)
_META_PROCESS_CUES = (
    "系统指令", "提示词", "一致性校验", "一致性规则", "命中规则", "上面的助手草稿",
    "按照我们真实经历过的内容认真回答", "按我们真实经历过的内容认真回答",
    "基于我们真正经历过的事回答", "依据真实上下文认真回应",
)
_IMAGE_CHARACTER_STRONG_CUES = (
    "图里的我", "图片里的我", "照片里的我", "这是我", "这就是我", "这是我的照片",
    "把我画成", "把我做成", "拍的是我", "画的是我", "拍的就是我", "画的就是我",
    "不就是我", "明明是我", "分明是我", "我的样子", "原来我长这样",
)
_IMAGE_CHARACTER_REACTION_CUES = (
    "我什么时候这样过", "我有这么像", "我有长这样", "我怎么会是这个样子",
    "像我", "跟我很像", "和我很像", "跟我一样", "和我一样", "像我的样子", "和我一个样",
)
_IMAGE_USER_IDENTITY_CUES = (
    "图里的你", "图片里的你", "照片里的你", "这是你", "这就是你本人", "这是你的照片",
    "把你画成", "把你做成", "拍的是你", "画的是你", "拍的就是你", "画的就是你",
    "不就是你", "明明是你", "分明是你", "你的样子",
)
_IMAGE_NONASSERTION_PREFIX = re.compile(
    r"(?:并不能说|不能确认|不能断定|无法确认|不能说|不该说|不要说|没有说|"
    r"不是说|并不是|并非|并不|不像|未必|没说|别说|谁说|不是|不)"
    r"(?:这|那|它|图里|图片里|照片里|画面里|画的|拍的|主体)?(?:就|是|很|真|真的)?\s*$"
)
_CLAIM_NEGATION_PREFIX = re.compile(
    r"(?:没有说|没说|并没说|从没说|从未说|谁说|别说|不要说|并非|并不是|不是说|否认|"
    r"难道|怎么会|怎么能|哪有|岂会|该不会|你不会以为).{0,14}$"
)
_SCENE_NONASSERTION_PREFIX = re.compile(
    r"(?:不想|不必|不用|不再|不会|无需|没必要|别|不要|先不|暂时不|已经不|早就不|"
    r"以后再|明天再|稍后再|待会再).{0,8}$"
)
_LEGACY_GUARD_FALLBACK_PATTERNS = (
    re.compile(r"^……让我重新说。你刚才的话，我有认真听见；这一次我不拿套话敷衍你。$"),
    re.compile(r"^等一下，让我把话说准确。你刚才问的事，我会按(?:照)?我们真实经历过的内容认真回答。$"),
    re.compile(r"^……我刚才没有表达清楚。给我一点时间，我会基于我们真正经历过的事回答你。$"),
    re.compile(r"^我方才的话不够准确。你说的事，我记得；我会先弄清你的意思，再认真回应。$"),
    re.compile(r"^抱歉，我刚才把话说乱了。我们已经一起经历过的事，我不会当作从未发生。$"),
    re.compile(r"^让我重新理清一下。你说的事我会依据真实上下文认真回应。$"),
    re.compile(r"^我听着呢。有什么话就直说吧，别让我猜你的心思。$"),
    re.compile(r"^我在听。慢慢说，我会认真回答。$"),
    re.compile(r"^我在听，你慢慢说就好。$"),
    re.compile(r"^我在。你说，我会认真听。$"),
    re.compile(r"^我在听。想说什么，都可以慢慢告诉我。$"),
    re.compile(r"^我在听，你慢慢说。$"),
)

# 重复动作母题表已提取到 domain.reply_motifs，生成前提示与生成后检测共用一份。

_PRESENCE_CHECK_CUES = ("你在吗", "还在吗", "在线吗", "听得到吗", "能听见吗")
_GENERIC_PRESENCE_CLOSURE_RE = re.compile(
    r"(?:^|[。！？\n])[^。！？\n]{0,12}(?:我在[。！？，,]|我(?:就)?在(?:这里|这儿)(?:等|陪|守)?|我就在[。！？，,]|我都在[。！？，,]|我哪儿也不去)"
)
_OWNERSHIP_NOUNS = ("方式", "做法", "习惯", "想法", "计划", "安排", "选择", "口味", "标准", "账本", "东西")
_EXPLICIT_REFERENCE_CORRECTION = (
    "刚才说错",
    "我说反了",
    "应该说",
    "更正一下",
    "准确地说",
    "口误",
    "刚才说得含糊",
    "刚才没说清",
    "我没说清",
    "那句话不准确",
    "不该替你定义",
    "我不该把",
)
_PARENTHETICAL_ACTION = re.compile(r"（[^（）]*）|\([^()]*\)")
_MAX_PARENTHETICAL_ACTION_CHARS = 48
_USER_RECOLLECTION = re.compile(
    r"(?:我(?:还)?记得你(?:之前|以前|上次|曾经)?(?:说过)?|你(?:之前|以前|上次|曾经)说过)"
    r"([^，,。！？!?\n]{2,80})"
)
_USER_ATTRIBUTE_CLAIM = re.compile(
    r"你的(?:方式|做法|习惯|想法|计划|安排|选择|口味|标准)|"
    r"你(?:一向|向来|总是|从来|平时)[^，,。！？!?\n]{1,36}|"
    r"(?:这|那|这种|这个)?(?:方式|做法|习惯)是你(?:教|告诉)我的"
)
_ATTRIBUTE_CORRECTION_PREFIX = re.compile(
    r"(?:不该|不应|不能|不是|并非).{0,16}"
    r"(?:替你定义|说成|当成|归为|算作|把.{0,8}说成)[‘'\"“]?\s*$"
)
_ATTRIBUTE_NONASSERTION_PREFIX = re.compile(
    r"(?:我)?(?:并不|不|还不|并没有|没有|没)(?:知道|清楚|了解|确定|能判断|敢说)"
    r"(?:你|关于你)?(?:究竟|到底|具体)?\s*$|"
    r"(?:还没|没有|没)(?:听你|见你|看你)(?:仔细|明确)?说过\s*$"
)
_FACT_FILLER = re.compile(r"用户|你|我|之前|以前|上次|曾经|说过|喜欢|讨厌|感兴趣|总是|一直|有点|挺|很|对|的|了|是")


def _fact_tokens(value: str) -> set[str]:
    text = _FACT_FILLER.sub("", str(value or ""))
    runs = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", text)
    return {run[i:i+2] for run in runs for i in range(len(run)-1)}


def normalize_action_narration(draft: str, result: GuardResult) -> str:
    """Remove excess parenthetical narration only after content rails pass.

    Never strip a factual/identity contradiction to disguise it as a valid reply,
    or turn an action-only draft into an empty reply.
    """
    if result.hard_reason_codes != ("ACTION_NARRATION_FORMAT",):
        return draft
    if not re.search(r"\w", _PARENTHETICAL_ACTION.sub("", draft)):
        return draft
    kept = False

    def retain_one(match: re.Match) -> str:
        nonlocal kept
        action = match.group(0)
        if not kept and len(re.sub(r"\s+", "", action[1:-1])) <= _MAX_PARENTHETICAL_ACTION_CHARS:
            kept = True
            return action
        return ""

    return _PARENTHETICAL_ACTION.sub(retain_one, draft).strip()


def _contains_asserted_cue(
    text: str,
    cues: tuple[str, ...],
    *,
    nonassertion_prefix: re.Pattern[str] = _CLAIM_NEGATION_PREFIX,
) -> bool:
    for cue in cues:
        start = 0
        while True:
            index = text.find(cue, start)
            if index < 0:
                break
            prefix = text[max(0, index - 24):index]
            if not nonassertion_prefix.search(prefix):
                return True
            start = index + max(1, len(cue))
    return False


def _user_requests_transition(user_message: str, cues: tuple[str, ...]) -> bool:
    text = str(user_message or "").strip()
    return any(cue in text for cue in cues)


def _swaps_reference_ownership(
    draft: str,
    user_message: str,
    history: list[dict],
) -> bool:
    if any(cue in draft for cue in _EXPLICIT_REFERENCE_CORRECTION):
        return False
    previous = next(
        (str(item.get("content") or "") for item in reversed(history) if item.get("role") == "assistant"),
        "",
    )
    if not previous:
        return False
    for noun in _OWNERSHIP_NOUNS:
        if f"你的{noun}" in previous and f"我的{noun}" in user_message:
            preserves_user = any(cue in draft for cue in (f"你的{noun}", "指的是你", "说的是你", "我指你"))
            if not preserves_user:
                return True
        if f"我的{noun}" in previous and f"你的{noun}" in user_message:
            preserves_character = any(cue in draft for cue in (f"我的{noun}", "指的是我", "说的是我"))
            if not preserves_character:
                return True
    return False


def validate_reply(
    *,
    character_id: str,
    draft: str,
    user_message: str,
    history: list[dict],
    live_status: dict[str, Any],
    companion_context: dict[str, Any],
    relevant_experiences: tuple[str, ...] = (),
    channel: str = "text",
    image_grounding: Any | None = None,
    user_fact_sources: tuple[str, ...] | None = None,
    history_dates: tuple[str, ...] | None = None,
) -> GuardResult:
    text = str(draft or "").strip()
    issues: list[str] = []
    if _swaps_reference_ownership(text, user_message, history):
        issues.append("REFERENCE_OWNERSHIP_SWAP")
    if history_dates is not None:
        try:
            today = datetime.strptime(str(live_status.get("date")), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            today = datetime.now().date()
        for cue, days in (("昨天", 1), ("昨晚", 1), ("前天", 2), ("上次", None)):
            claim = re.search(rf"我(?:在|于)?{cue}|{cue}[^，,。！？!?\n]{{0,12}}我", text)
            supported = bool(history_dates) if days is None else (today - timedelta(days=days)).isoformat() in history_dates
            if claim and not supported:
                issues.append("UNGROUNDED_PAST_EPISODE")
                break
    if user_fact_sources is not None:
        evidence_tokens = set().union(*(_fact_tokens(item) for item in user_fact_sources))
        if any(not (_fact_tokens(match.group(1)) & evidence_tokens)
               for match in _USER_RECOLLECTION.finditer(text)):
            issues.append("UNGROUNDED_USER_MEMORY")
        question_echo = ("?" in user_message or "？" in user_message) and any(
            f"我的{noun}" in user_message or f"你的{noun}" in user_message
            for noun in _OWNERSHIP_NOUNS
        )
        attribute_sources = [
            item for item in user_fact_sources
            if not (question_echo and str(item).strip() == str(user_message).strip())
        ]
        attribute_tokens = set().union(*(_fact_tokens(item) for item in attribute_sources))
        unsupported_attribute = False
        for match in _USER_ATTRIBUTE_CLAIM.finditer(text):
            prefix = text[max(0, match.start() - 40):match.start()]
            if (
                _ATTRIBUTE_CORRECTION_PREFIX.search(prefix)
                or _ATTRIBUTE_NONASSERTION_PREFIX.search(prefix)
            ):
                continue
            if not (_fact_tokens(match.group(0)) & attribute_tokens):
                unsupported_attribute = True
                break
        if unsupported_attribute:
            issues.append("UNGROUNDED_USER_MEMORY")

    first_time_claim_text = re.sub(
        r"(?:不|并不|并非|绝不|早已不|当然不)是?(?:我们|两人|彼此)?(?:的)?第一次",
        "",
        text,
    )
    first_time_claim_text = re.sub(
        r"(?:没有|没|从未|从没)说(?:过)?[^。！？!?]{0,24}第一次|(?:怎么|哪|岂|何)会是?(?:我们)?(?:的)?第一次",
        "",
        first_time_claim_text,
    )
    if relevant_experiences and _contains_asserted_cue(first_time_claim_text, _FIRST_TIME_CUES):
        issues.append("EXP_FIRST_TIME")

    relationship = companion_context.get("relationship", {})
    level = int(relationship.get("level") or 1)
    if level >= GUARD_STAGE_LEVEL and _contains_asserted_cue(text, _RELATIONSHIP_RESET_CUES):
        issues.append("REL_STAGE")
    if level >= GUARD_COMMITMENT_LEVEL and _contains_asserted_cue(text, _COMMITMENT_RESET_CUES):
        issues.append("REL_COMMITMENT")

    if any(cue in text for cue in _AI_CUES):
        issues.append("IDENTITY_AI")
    if channel in {"proactive", "home_greeting"} and any(cue in text for cue in _PAST_CALLBACK_CUES):
        issues.append("UNSOLICITED_PAST_CALLBACK")
    if (
        any(cue in text for cue in _META_PROCESS_CUES)
        or has_history_labels(text)
        or any(pattern.fullmatch(text) for pattern in _LEGACY_GUARD_FALLBACK_PATTERNS)
    ):
        issues.append("META_PROCESS_LEAK")

    if channel == "image" and image_grounding is not None:
        relation = str(
            getattr(image_grounding, "subject_relation", "")
            or (
                image_grounding.get("subject_relation", "")
                if isinstance(image_grounding, dict)
                else ""
            )
            or "unknown"
        )
        asserts_character = _contains_asserted_cue(
            text,
            _IMAGE_CHARACTER_STRONG_CUES,
            nonassertion_prefix=_IMAGE_NONASSERTION_PREFIX,
        )
        reacts_as_character = _contains_asserted_cue(
            text,
            _IMAGE_CHARACTER_REACTION_CUES,
            nonassertion_prefix=_IMAGE_NONASSERTION_PREFIX,
        )
        asserts_user = _contains_asserted_cue(
            text,
            _IMAGE_USER_IDENTITY_CUES,
            nonassertion_prefix=_IMAGE_NONASSERTION_PREFIX,
        )
        if relation == "unknown" and (asserts_character or reacts_as_character or asserts_user):
            issues.append("IMAGE_SUBJECT_IDENTITY")
        elif relation == "user_compares_character" and (asserts_character or asserts_user):
            issues.append("IMAGE_SUBJECT_IDENTITY")
        elif relation == "user_claims_character" and asserts_user:
            issues.append("IMAGE_SUBJECT_IDENTITY")
        elif relation == "user_claims_self" and (asserts_character or reacts_as_character):
            issues.append("IMAGE_SUBJECT_IDENTITY")

    if channel in {"text", "image"}:
        parenthetical_actions = _PARENTHETICAL_ACTION.findall(text)
        if len(parenthetical_actions) > 1 or any(
            len(re.sub(r"\s+", "", item[1:-1])) > _MAX_PARENTHETICAL_ACTION_CHARS
            for item in parenthetical_actions
        ):
            issues.append("ACTION_NARRATION_FORMAT")
    role_rail_hits = matching_character_output_rails(character_id, text)
    if any(rail.severity == "hard" for rail in role_rail_hits):
        issues.append("ROLE_FORBIDDEN")
    if any(rail.severity == "soft" for rail in role_rail_hits):
        issues.append("ROLE_STYLE")

    # A model sometimes derives a friendly nickname from the character's own
    # name and accidentally uses it as a vocative for the user (for example
    # Firefly saying "阿萤，下午好").  Only inspect the beginning of a reply so
    # normal self-reference elsewhere is not rejected.
    vocative_text = re.sub(r"^(?:\s*[（(][^）)]{0,80}[）)]\s*)+", "", text)
    relationship = (
        companion_context.get("relationship", {})
        if isinstance(companion_context, dict)
        else {}
    )
    allowed_user_vocatives = {
        str(item).strip()
        for item in relationship.get("forms_of_address", [])
        if str(item).strip()
    }
    character_vocatives = {
        *aliases_for_character(character_id),
        *(
            str(item).strip()
            for item in relationship.get("user_forms_of_address", [])
            if str(item).strip()
        ),
    }
    for alias in character_vocatives - allowed_user_vocatives:
        if re.match(rf"^{re.escape(alias)}(?:[，,、：:！!？?]|\s)", vocative_text):
            issues.append("ADDRESS_SELF_AS_USER")
            break

    status_source = str(live_status.get("source") or "schedule")
    remote_call = channel in {"voice_call", "video_call"}
    claims_onsite_action = text_asserts_onsite_action(
        text,
        excluded_cues=("抬眼看你",) if channel == "video_call" else (),
    )
    if remote_call and claims_onsite_action:
        issues.append("CHANNEL_REMOTE_ACTION")
    elif status_source != "conversation" and not user_permits_onsite_reply(user_message):
        if claims_onsite_action:
            issues.append("CHANNEL_REMOTE_ACTION")

    scene = str(live_status.get("scene") or "")
    tone = str(live_status.get("tone") or "")
    if (
        (status_source == "conversation" or tone == "sleep")
        and not _user_requests_transition(user_message, _USER_WORK_TRANSITION_CUES)
        and _contains_asserted_cue(text, _WORK_CUES, nonassertion_prefix=_SCENE_NONASSERTION_PREFIX)
    ):
        issues.append("SCENE_STATUS")
    if (
        (scene in {"rest", "sleep"} or tone == "sleep")
        and not _user_requests_transition(
            user_message,
            _USER_EXIT_TRANSITION_CUES + _USER_WORK_TRANSITION_CUES,
        )
        and _contains_asserted_cue(
            text,
            _SCENE_EXIT_CUES,
            nonassertion_prefix=_SCENE_NONASSERTION_PREFIX,
        )
    ):
        issues.append("SCENE_STATUS")

    recent_assistant = [
        str(item.get("content") or "")
        for item in history[-10:]
        if item.get("role") == "assistant"
    ][-5:]
    for code, _label, cues in REPEAT_MOTIFS:
        previous_hits = sum(any(cue in old for cue in cues) for old in recent_assistant)
        if previous_hits >= 2 and any(cue in text for cue in cues):
            issues.append(code)
    recent_endings = [old.strip()[-100:] for old in recent_assistant]
    ending = text.strip()[-100:]
    if (
        not any(cue in user_message for cue in _PRESENCE_CHECK_CUES)
        and _GENERIC_PRESENCE_CLOSURE_RE.search(ending)
    ):
        issues.append("GENERIC_PRESENCE_CLOSURE")
    for code, _label, cues in REPEAT_ENDING_MOTIFS:
        previous_hits = sum(any(cue in old for cue in cues) for old in recent_endings)
        if previous_hits >= 1 and any(cue in ending for cue in cues):
            issues.append(code)

    return GuardResult(tuple(dict.fromkeys(issues)))


def build_repair_messages(
    original_messages: list[dict[str, str]],
    draft: str,
    result: GuardResult,
    *,
    character_id: str = "",
) -> list[dict[str, str]]:
    rules, guidance = _guard_guidance(result, character_id=character_id, draft=draft)
    return [
        *original_messages,
        {"role": "assistant", "content": draft},
        {
            "role": "system",
            "content": (
                "上面的助手草稿尚未展示给用户，因一致性规则命中而被拦截。"
                f"命中规则：{rules}。请只重写这一条回复。除非规则明确要求在对话中承认上一句的措辞问题，"
                "否则不要解释后台修正过程。"
                "必须保留对用户问题的直接回应和当前角色语气；纠正首次经历、关系阶段、身份、"
                "远程/现场、地点状态、称呼方向或重复模板矛盾。称呼用户时不得把角色本人的名字或昵称"
                "当成用户称呼。不要新增未经确认的事实、动作、同意或计划。"
                f"{guidance}"
            ),
        },
    ]


def merge_guard_results(*results: GuardResult) -> GuardResult:
    """Combine findings from bounded attempts without weakening any hard rail."""

    return GuardResult(
        tuple(
            dict.fromkeys(
                code
                for result in results
                for code in result.reason_codes
            )
        )
    )


def _guard_guidance(
    result: GuardResult,
    *,
    character_id: str = "",
    draft: str = "",
) -> tuple[str, str]:
    rules = "、".join(result.reason_codes)
    rule_guidance = list(
        dict.fromkeys(
            behavior_rail(code).repair_instruction for code in result.reason_codes
        )
    )
    if {"ROLE_FORBIDDEN", "ROLE_STYLE"} & set(result.reason_codes):
        role_guidance = character_output_repair_guidance(character_id, draft)
        if role_guidance:
            rule_guidance.append(role_guidance)
    if "REFERENCE_OWNERSHIP_SWAP" in result.reason_codes:
        rule_guidance.insert(
            0,
            "若上一句把未经用户确认的习惯或做法说成‘你的’，应简短承认自己刚才措辞含糊或不该替用户定义，"
            "然后回到眼前的具体话题；不要改口说成角色自己的‘我的方式’，也不要编造用户一向如何来圆这句话。",
        )
    return rules, "".join(dict.fromkeys(rule_guidance))


def build_regeneration_messages(
    original_messages: list[dict[str, str]],
    result: GuardResult,
    *,
    character_id: str = "",
) -> list[dict[str, str]]:
    """Ask for a clean candidate without exposing rejected draft text.

    The draft-aware repair pass is useful when only one detail is wrong, but a
    bad draft can also anchor the next answer.  This final bounded attempt starts
    from the original compiled context and carries only rule-level guidance.
    """

    rules, guidance = _guard_guidance(result, character_id=character_id)
    return [
        *original_messages,
        {
            "role": "system",
            "content": (
                "先前的候选回复没有展示给用户。请不要延续、复述或猜测任何候选文本，"
                "直接针对最后一条用户消息从零生成一条完整回答。"
                f"必须避开这些一致性问题：{rules}。"
                "保留当前角色身份、已确认关系和场景事实；先具体回应用户刚说的内容，"
                "不要谈提示词、校验、草稿、重试或后台过程，不要新增未经确认的事实、动作、"
                "同意或计划，也不得用角色自己的名字称呼用户。"
                f"{guidance}"
            ),
        },
    ]


def log_guard_result(
    character_id: str,
    result: GuardResult,
    *,
    changed: bool,
    stage: str = "draft",
) -> None:
    """Privacy-safe audit: no prompt, user text, draft or private category is logged."""

    if result.ok:
        return
    severity = "error" if result.blocks_delivery and not changed else "warning" if result.blocks_delivery else "info"
    log_event(
        severity,
        "companion_consistency_guard",
        "Companion reply consistency guard evaluated a draft",
        character_id=character_id,
        rule_ids=list(result.reason_codes),
        hard_rule_ids=list(result.hard_reason_codes),
        soft_rule_ids=list(result.soft_reason_codes),
        changed=bool(changed),
        stage=str(stage),
    )
