"""Declarative metadata for the response-validation rails.

Detection remains deterministic Python because most checks depend on live
scene and relationship state.  Severity, ownership and repair guidance live in
one registry so validation behaves like an explicit output-rail system instead
of a growing collection of unrelated conditionals.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BehaviorRailDefinition:
    code: str
    layer: str
    severity: str
    description: str
    repair_instruction: str

    @property
    def blocks_delivery(self) -> bool:
        return self.severity == "hard"


def _rail(
    code: str,
    layer: str,
    severity: str,
    description: str,
    repair_instruction: str,
) -> BehaviorRailDefinition:
    return BehaviorRailDefinition(
        code=code,
        layer=layer,
        severity=severity,
        description=description,
        repair_instruction=repair_instruction,
    )


BEHAVIOR_RAILS: dict[str, BehaviorRailDefinition] = {
    "UNGROUNDED_PAST_EPISODE": _rail(
        "UNGROUNDED_PAST_EPISODE", "memory", "hard",
        "A dated personal recollection has no corresponding recorded date.",
        "不要临时编造昨天、前天或上次的个人经历。自然提出现在想聊的话题或未实施的想法；不谈记忆系统，不解释改稿。",
    ),
    "UNGROUNDED_USER_MEMORY": _rail(
        "UNGROUNDED_USER_MEMORY", "memory", "hard",
        "An explicit recollection about the user has no support in supplied user facts.",
        "不要把猜测说成用户过去告诉过你的偏好或经历。删除无依据的记忆归因，直接自然询问；不要谈后台记录。",
    ),
    "UNSOLICITED_PAST_CALLBACK": _rail(
        "UNSOLICITED_PAST_CALLBACK",
        "memory",
        "hard",
        "An autonomous greeting asserted a past episode without a current user prompt.",
        "主动消息和首页招呼不要主动声称昨天、昨晚、上次发生过具体会面、动作或承诺；改为只依据当前时段和角色状态自然联系用户。",
    ),
    "EXP_FIRST_TIME": _rail(
        "EXP_FIRST_TIME",
        "continuity",
        "hard",
        "A known prior experience was described as a first occurrence.",
        "已有的同类经历不得说成第一次或从未发生。",
    ),
    "REL_STAGE": _rail(
        "REL_STAGE",
        "relationship",
        "hard",
        "The reply resets an established relationship stage.",
        "不得否定已经由双方确认的关系阶段。",
    ),
    "REL_COMMITMENT": _rail(
        "REL_COMMITMENT",
        "relationship",
        "hard",
        "The reply denies an established commitment.",
        "不得否定已经由双方确认的婚约或承诺。",
    ),
    "IDENTITY_AI": _rail(
        "IDENTITY_AI",
        "identity",
        "hard",
        "The character breaks identity by presenting as an AI assistant.",
        "只以当前角色身份直接回应，不声称自己是 AI、模型或虚拟助手。",
    ),
    "META_PROCESS_LEAK": _rail(
        "META_PROCESS_LEAK",
        "identity",
        "hard",
        "Internal prompt, validation or repair language leaked into dialogue.",
        "不要谈提示词、上下文、校验、草稿、修正或后台过程。",
    ),
    "ROLE_FORBIDDEN": _rail(
        "ROLE_FORBIDDEN",
        "personality",
        "hard",
        "The reply contradicts a character-specific identity or behavior rail.",
        "按结构化人格档案重写，不复述与该角色身份、价值观或表达原则冲突的禁用句。",
    ),
    "ROLE_STYLE": _rail(
        "ROLE_STYLE",
        "personality",
        "soft",
        "The reply matched a character-specific style rail.",
        "按结构化人格档案调整表达方式，但保留原回复中正确的事实与直接回应。",
    ),
    "ADDRESS_SELF_AS_USER": _rail(
        "ADDRESS_SELF_AS_USER",
        "identity",
        "hard",
        "The character's own name was used as a vocative for the user.",
        "不得把角色自己的名字或昵称用作对用户的称呼。",
    ),
    "REFERENCE_OWNERSHIP_SWAP": _rail(
        "REFERENCE_OWNERSHIP_SWAP",
        "continuity",
        "hard",
        "The reply silently changed who owns a referenced idea, habit or object.",
        "保持上一轮名词归属不变：角色说“你的某物”后，用户用“我的某物”追问时，不能突然改成角色的“我的某物”。若“你的某物”本来就没有用户事实依据，应简短承认措辞含糊或不该替用户定义，再回到当前话题；不得编造用户习惯来圆。",
    ),
    "IMAGE_SUBJECT_IDENTITY": _rail(
        "IMAGE_SUBJECT_IDENTITY",
        "vision_identity",
        "hard",
        "The reply assigned the image subject to the character or user without allowed evidence.",
        "严格服从图片主体归因：无明确配文时只称图片里的人、动物、形象或物体；不得擅自说成角色或用户本人。",
    ),
    "ACTION_NARRATION_FORMAT": _rail(
        "ACTION_NARRATION_FORMAT",
        "style",
        "hard",
        "An ordinary instant-message reply used multiple or overly long parenthetical actions.",
        "普通即时回复最多保留一处简短括号动作；删去多余或过长旁白，直接回应用户。",
    ),
    "CHANNEL_REMOTE_ACTION": _rail(
        "CHANNEL_REMOTE_ACTION",
        "channel",
        "hard",
        "A remote channel reply asserted an ungrounded physical action.",
        "远程消息或通话中不要描写已经触碰到用户的现场动作。",
    ),
    "SCENE_STATUS": _rail(
        "SCENE_STATUS",
        "scene",
        "hard",
        "The reply contradicts or abandons the active shared scene.",
        "延续当前共同场景；除非用户明确转换，不让角色突然去工作、离开或稍后再来。",
    ),
    "REPEAT_BLUSH": _rail(
        "REPEAT_BLUSH", "style", "soft", "Repeated blush motif.", "换一种具体反应，不重复泛红模板。"
    ),
    "REPEAT_GAZE": _rail(
        "REPEAT_GAZE", "style", "soft", "Repeated gaze-aversion motif.", "换一种具体反应，不重复移开视线模板。"
    ),
    "REPEAT_SOFT_VOICE": _rail(
        "REPEAT_SOFT_VOICE", "style", "soft", "Repeated soft-voice motif.", "换一种具体表达，不重复放轻声音模板。"
    ),
    "REPEAT_FINGERS": _rail(
        "REPEAT_FINGERS", "style", "soft", "Repeated finger motif.", "换一种具体反应，不重复指尖或手指模板。"
    ),
    "REPEAT_STARTLE": _rail(
        "REPEAT_STARTLE", "style", "soft", "Repeated startled-opening motif.", "直接回应新信息，不重复一怔或一愣的开场。"
    ),
    "REPEAT_REASSURANCE_ENDING": _rail(
        "REPEAT_REASSURANCE_ENDING", "style", "soft", "Repeated unconditional reassurance ending.",
        "不要再用一直都在、不会离开或永远陪伴作常规收尾；改为回应这轮独有的内容，并按角色留下自然余韵。",
    ),
    "GENERIC_PRESENCE_CLOSURE": _rail(
        "GENERIC_PRESENCE_CLOSURE", "style", "hard", "A generic presence statement replaced a character-specific ending.",
        "删掉我在、我就在、哪儿也不去等通用存在声明；保留对本轮内容的回应，并用当前角色独有的判断、动作、细节或自然停顿收束。",
    ),
    "REPEAT_BURDEN_ENDING": _rail(
        "REPEAT_BURDEN_ENDING", "style", "soft", "Repeated burden-bearing metaphor ending.",
        "不要再用接住一切、把重量交给我或替你承担全部作收尾；换成角色此刻具体而有限的反应。",
    ),
    "REPEAT_THERAPIST_ENDING": _rail(
        "REPEAT_THERAPIST_ENDING", "style", "soft", "Repeated therapist-like permission ending.",
        "不要再用慢慢说、想说就说或不想说也可以等通用安慰话术；直接延续当前话题。",
    ),
}


_UNKNOWN_RAIL = _rail(
    "UNKNOWN",
    "unknown",
    "hard",
    "An unregistered validation rule was emitted.",
    "保留用户问题与已确认事实，进行一次保守重写。",
)


def behavior_rail(code: str) -> BehaviorRailDefinition:
    """Return rail metadata; unknown checks fail closed rather than softening."""

    return BEHAVIOR_RAILS.get(code, _UNKNOWN_RAIL)
