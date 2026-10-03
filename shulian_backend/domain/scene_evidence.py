"""Deterministic evidence for whether a chat turn is physically co-present.

The model sees free-form roleplay text, while the status engine stores a small
fixed scene enum.  These helpers are shared by both the response guard and the
scene-status service so a user action cannot be accepted by one layer and
rejected by the other.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


ONSITE_ACTION_CUES = (
    "抱起你", "抱住你", "抱紧你", "抱着你", "拥住你", "拥抱你", "搂住你", "搂紧你", "搂着你",
    "牵住你的手", "牵着你的手", "握住你的手", "拉住你的手", "吻住你", "吻了吻你",
    "吻上你", "亲了亲你", "亲吻你", "亲上你",
    "抚上你的脸", "摸了摸你的头", "揉了揉你的头发", "抬眼看你", "贴近", "凑到",
    "靠进你怀里", "靠在你怀里", "靠在你肩上", "走到你身边", "来到你身边",
    "坐到你身旁", "坐到你身边", "躺在你身边", "依偎着你",
)

_USER_STAGE_ACTION_CUES = (
    "抱起", "抱住", "抱紧", "抱着", "拥住", "拥抱", "搂住", "搂紧", "搂着",
    "牵住", "牵着", "握住", "拉住", "吻住", "吻了吻", "吻上", "亲了亲", "亲吻", "亲上",
    "抚上", "摸了摸", "揉了揉", "贴近", "凑到", "靠进", "靠在", "走到", "来到",
    "坐到", "躺在", "依偎",
)
_USER_NARRATED_ACTION_CUES = (
    "我抱起", "我抱住", "我抱紧", "我抱着", "我拥抱", "我搂住", "我牵住", "我握住",
    "我拉住", "我吻", "我亲", "我贴近", "我靠近", "把你抱", "把她抱", "把他抱",
)

_USER_PRESENCE_CUES = (
    "我来找你", "我到你这里", "我在你身边", "来到你身边", "走到你身边",
    "坐到你身旁", "坐到你身边", "躺在你身边", "睡在一起",
)
_USER_DIRECT_REQUEST_CUES = (
    "抱抱我", "抱住我", "抱紧我", "搂住我", "牵我的手", "吻我", "亲我",
    "来我身边", "到我身边", "过来",
)
_NONCURRENT_ACTION_PREFIX = re.compile(
    r"(?:不|没|没有|无法|不能|没法|别|不要|想不想|想要|想|真想|好想|希望|如果|假如|要是|"
    r"下次|明天|以后|等见面|见面时|会不会|会|准备|打算|计划|梦见|幻想|"
    r"昨天|昨日|昨晚|前天|上次|曾经|以前|当时|记得|回忆).{0,14}$"
)
_STAGE_DIRECTION = re.compile(r"[（(]([^（）()\r\n]{1,180})[）)]")
_NONCURRENT_SCENE = re.compile(
    r"昨天|昨日|昨晚|前天|上次|曾经|以前|当时|记得|回忆|那天|"
    r"明天|明日|以后|下次|改天|将来|如果|假如|要是|梦见|幻想|想象"
)
_CURRENT_SCENE = re.compile(r"现在|此刻|这会儿|这就|今天|今日|今晚")
_CONDITIONAL_SCENE = re.compile(r"如果|假如|要是|梦见|幻想|想象")


def current_scene_text(value: str) -> str:
    """Extract current clauses; a recollection stays past until explicitly reset.

    Keep temporal scope across commas so a long remembered action cannot evade
    the short cue-prefix checks. An explicit present clause can start a new
    scene in the same message (昨天很忙，今天我们一起吃饭).
    """
    result: list[str] = []
    noncurrent = False
    for clause in re.split(r"[，,。！？!?；;\n]", str(value or "")):
        past = list(_NONCURRENT_SCENE.finditer(clause))
        present = list(_CURRENT_SCENE.finditer(clause))
        if past:
            noncurrent = True
        if present and not _CONDITIONAL_SCENE.search(clause):
            if not past or present[-1].start() > past[-1].start():
                noncurrent = False
                clause = clause[present[-1].start():]
        if not noncurrent and clause.strip():
            result.append(clause.strip())
    return "，".join(result)


def _contains_asserted_cue(text: str, cues: Iterable[str]) -> bool:
    for cue in cues:
        if not cue:
            continue
        start = 0
        while True:
            index = text.find(cue, start)
            if index < 0:
                break
            prefix = text[max(0, index - 32):index]
            if not _NONCURRENT_ACTION_PREFIX.search(prefix):
                return True
            start = index + len(cue)
    return False


def text_asserts_onsite_action(
    value: str,
    *,
    excluded_cues: Iterable[str] = (),
) -> bool:
    """Return whether text asserts a current physical action, not a wish or hypothetical."""

    text = str(value or "").strip()
    excluded = {str(cue) for cue in excluded_cues}
    cues = (cue for cue in ONSITE_ACTION_CUES if cue not in excluded)
    return bool(text) and _contains_asserted_cue(text, cues)


def user_asserts_shared_presence(user_message: str) -> bool:
    """Return whether the user explicitly places both participants together now."""

    text = str(user_message or "").strip()
    if not text:
        return False
    if _contains_asserted_cue(text, _USER_PRESENCE_CUES):
        return True
    if _contains_asserted_cue(text, _USER_NARRATED_ACTION_CUES):
        return True
    return any(
        not _NONCURRENT_ACTION_PREFIX.search(text[max(0, match.start() - 32):match.start()])
        and _contains_asserted_cue(match.group(1), _USER_STAGE_ACTION_CUES)
        for match in _STAGE_DIRECTION.finditer(text)
    )


def user_permits_onsite_reply(user_message: str) -> bool:
    """Return whether an immediate on-site response is grounded by this user turn.

    An asserted roleplay action remains valid even when followed by a question,
    e.g. ``（抱起阿晴）今天累不累？``.  Desire questions such as
    ``你想抱我吗？`` and future plans remain non-current because their prefix is
    rejected by ``_NONCURRENT_ACTION_PREFIX``.
    """

    text = str(user_message or "").strip()
    if not text:
        return False
    return user_asserts_shared_presence(text) or _contains_asserted_cue(
        text,
        _USER_DIRECT_REQUEST_CUES,
    )
