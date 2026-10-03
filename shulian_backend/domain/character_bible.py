"""角色圣经的只读领域模型。"""

from __future__ import annotations

from dataclasses import dataclass


class CharacterBibleError(RuntimeError):
    """角色圣经缺失、格式错误或引用关系无效。"""


@dataclass(frozen=True)
class CharacterBibleSource:
    id: str
    source_type: str
    title: str
    publisher: str
    authority: str
    locator: str
    url: str | None = None
    language: str = "zh-CN"


@dataclass(frozen=True)
class CharacterBibleEntry:
    id: str
    entry_type: str
    statement: str
    keywords: tuple[str, ...]
    source_ids: tuple[str, ...]
    evidence_level: str
    continuity: str
    continuity_triggers: tuple[str, ...]
    priority: int
    always_include: bool = False


@dataclass(frozen=True)
class CharacterBible:
    schema_version: int
    character_id: str
    display_name: str
    work: str
    status: str
    default_continuity: str
    companion_overlay: str
    sources: tuple[CharacterBibleSource, ...]
    entries: tuple[CharacterBibleEntry, ...]
