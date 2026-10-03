"""按当前话题选择少量角色圣经条目并注入提示词。"""

from __future__ import annotations

from collections.abc import Iterable

from ..domain.character_bible import CharacterBibleEntry, CharacterBibleError
from ..repositories.character_bible_repository import CharacterBibleRepository


_ENTRY_LABELS = {
    "canon_fact": "原作事实",
    "canon_relation": "原作关系",
    "speech_pattern": "语言特征",
    "decision_pattern": "行为推断",
}
_REPOSITORY = CharacterBibleRepository()


def _query_text(user_message: str, history: Iterable[dict]) -> str:
    parts = [user_message]
    recent = list(history)[-6:]
    for item in recent:
        if item.get("role") == "user" and isinstance(item.get("content"), str):
            parts.append(item["content"])
    return "\n".join(parts).casefold()


def _entry_score(entry: CharacterBibleEntry, query: str) -> int | None:
    if entry.evidence_level == "provisional":
        return None
    matches = sum(1 for keyword in entry.keywords if keyword.casefold() in query)
    if not matches and not entry.always_include:
        return None
    return entry.priority + matches * 100 + (20 if entry.always_include else 0)


def select_character_bible_entries(
    character_id: str,
    user_message: str,
    history: Iterable[dict],
    *,
    limit: int = 6,
    repository: CharacterBibleRepository | None = None,
) -> list[CharacterBibleEntry]:
    bible = (repository or _REPOSITORY).load(character_id)
    if bible.status == "scaffold":
        return []
    query = _query_text(user_message, history)
    scored: list[tuple[int, CharacterBibleEntry]] = []
    for entry in bible.entries:
        if entry.continuity != bible.default_continuity and not any(
            trigger.casefold() in query for trigger in entry.continuity_triggers
        ):
            continue
        score = _entry_score(entry, query)
        if score is not None:
            scored.append((score, entry))
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    return [entry for _, entry in scored[: max(0, limit)]]


def build_character_bible_context(
    character_id: str,
    user_message: str,
    history: Iterable[dict],
) -> str:
    try:
        bible = _REPOSITORY.load(character_id)
        entries = select_character_bible_entries(
            character_id,
            user_message,
            history,
            repository=_REPOSITORY,
        )
    except CharacterBibleError:
        # 角色圣经是增强层，损坏时不能阻断基础聊天。
        return ""
    if not entries:
        return ""

    lines = "\n".join(
        (
            f"- [{'分支资料' if entry.continuity != bible.default_continuity else _ENTRY_LABELS[entry.entry_type]}] "
            f"{entry.statement}"
        )
        for entry in entries
    )
    return f"""

【本轮相关原作依据（角色圣经）】
以下内容按当前话题从可追溯资料中选取，只用于校准判断和人物关系，不要求逐条复述。
“行为推断”是基于原作材料的解释，不等同于原作明说；不得把数恋中的用户冒充为原作人物。
{lines}

【数恋关系适配边界】
{bible.companion_overlay}
"""


def character_bible_status(character_ids: object = None) -> dict:
    expected = {str(value) for value in (character_ids or ()) if str(value).strip()}
    try:
        bibles = _REPOSITORY.load_all()
    except CharacterBibleError:
        if not _REPOSITORY.root.exists():
            return {
                "ok": True,
                "configured": False,
                "count": 0,
                "reviewed_count": 0,
                "scaffold_count": 0,
                "missing_character_ids": sorted(expected),
                "error": None,
            }
        return {
            "ok": False,
            "configured": True,
            "count": 0,
            "reviewed_count": 0,
            "scaffold_count": 0,
            "missing_character_ids": sorted(expected),
            "error": "unavailable",
        }
    statuses = [bible.status for bible in bibles.values()]
    return {
        "ok": True,
        "configured": bool(bibles),
        "count": len(bibles),
        "reviewed_count": sum(
            status in {"sample-reviewed", "reviewed"} for status in statuses
        ),
        "scaffold_count": statuses.count("scaffold"),
        "missing_character_ids": sorted(expected - set(bibles)),
        "error": None,
    }
