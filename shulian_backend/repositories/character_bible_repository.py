"""从随程序发布的 JSON 资源中加载角色圣经。"""

from __future__ import annotations

import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from role_content import content_for, RoleContentMap

from ..domain.character_bible import (
    CharacterBible,
    CharacterBibleEntry,
    CharacterBibleError,
    CharacterBibleSource,
)


_SAFE_CHARACTER_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ALLOWED_STATUSES = {"scaffold", "sample-reviewed", "reviewed"}
_ALLOWED_ENTRY_TYPES = {
    "canon_fact",
    "canon_relation",
    "speech_pattern",
    "decision_pattern",
}
_ALLOWED_EVIDENCE_LEVELS = {"direct", "derived", "provisional"}


def character_bible_root() -> Path:
    override = os.getenv("SHULIAN_CHARACTER_BIBLE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return (Path(getattr(sys, "_MEIPASS")) / "character_bibles").resolve()
    return (Path(__file__).resolve().parents[2] / "character_bibles").resolve()


def _required_text(payload: dict, name: str, *, context: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise CharacterBibleError(f"{context}.{name} must be a non-empty string")
    return value.strip()


def _optional_text(payload: dict, name: str, default: str = "") -> str:
    value = payload.get(name, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise CharacterBibleError(f"{name} must be a string")
    return value.strip()


def _text_tuple(payload: dict, name: str, *, context: str) -> tuple[str, ...]:
    values = payload.get(name, [])
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise CharacterBibleError(f"{context}.{name} must be a string array")
    return tuple(value.strip() for value in values)


def _parse_source(payload: object, *, context: str) -> CharacterBibleSource:
    if not isinstance(payload, dict):
        raise CharacterBibleError(f"{context} must be an object")
    url = _optional_text(payload, "url") or None
    return CharacterBibleSource(
        id=_required_text(payload, "id", context=context),
        source_type=_required_text(payload, "sourceType", context=context),
        title=_required_text(payload, "title", context=context),
        publisher=_required_text(payload, "publisher", context=context),
        authority=_required_text(payload, "authority", context=context),
        locator=_required_text(payload, "locator", context=context),
        url=url,
        language=_optional_text(payload, "language", "zh-CN") or "zh-CN",
    )


def _parse_entry(payload: object, *, context: str) -> CharacterBibleEntry:
    if not isinstance(payload, dict):
        raise CharacterBibleError(f"{context} must be an object")
    entry_type = _required_text(payload, "type", context=context)
    evidence_level = _required_text(payload, "evidenceLevel", context=context)
    if entry_type not in _ALLOWED_ENTRY_TYPES:
        raise CharacterBibleError(f"{context}.type is unsupported: {entry_type}")
    if evidence_level not in _ALLOWED_EVIDENCE_LEVELS:
        raise CharacterBibleError(
            f"{context}.evidenceLevel is unsupported: {evidence_level}"
        )
    priority = payload.get("priority", 50)
    if not isinstance(priority, int) or not 0 <= priority <= 100:
        raise CharacterBibleError(f"{context}.priority must be an integer from 0 to 100")
    always_include = payload.get("alwaysInclude", False)
    if not isinstance(always_include, bool):
        raise CharacterBibleError(f"{context}.alwaysInclude must be a boolean")
    return CharacterBibleEntry(
        id=_required_text(payload, "id", context=context),
        entry_type=entry_type,
        statement=_required_text(payload, "statement", context=context),
        keywords=_text_tuple(payload, "keywords", context=context),
        source_ids=_text_tuple(payload, "sourceIds", context=context),
        evidence_level=evidence_level,
        continuity=_optional_text(payload, "continuity", "main") or "main",
        continuity_triggers=_text_tuple(
            payload, "continuityTriggers", context=context
        ),
        priority=priority,
        always_include=always_include,
    )


def parse_character_bible(payload: object, *, expected_id: str) -> CharacterBible:
    if not isinstance(payload, dict):
        raise CharacterBibleError("character bible root must be an object")
    schema_version = payload.get("schemaVersion")
    if schema_version != 1:
        raise CharacterBibleError(f"unsupported character bible schema: {schema_version}")
    character_id = _required_text(payload, "characterId", context="bible")
    if character_id != expected_id:
        raise CharacterBibleError(
            f"character bible id mismatch: expected {expected_id}, got {character_id}"
        )
    status = _required_text(payload, "status", context="bible")
    if status not in _ALLOWED_STATUSES:
        raise CharacterBibleError(f"unsupported character bible status: {status}")

    raw_sources = payload.get("sources", [])
    raw_entries = payload.get("entries", [])
    if not isinstance(raw_sources, list) or not isinstance(raw_entries, list):
        raise CharacterBibleError("bible.sources and bible.entries must be arrays")
    sources = tuple(
        _parse_source(source, context=f"sources[{index}]")
        for index, source in enumerate(raw_sources)
    )
    entries = tuple(
        _parse_entry(entry, context=f"entries[{index}]")
        for index, entry in enumerate(raw_entries)
    )

    source_ids = [source.id for source in sources]
    entry_ids = [entry.id for entry in entries]
    if len(source_ids) != len(set(source_ids)):
        raise CharacterBibleError(f"{character_id} contains duplicate source ids")
    if len(entry_ids) != len(set(entry_ids)):
        raise CharacterBibleError(f"{character_id} contains duplicate entry ids")
    known_sources = set(source_ids)
    for entry in entries:
        unknown = set(entry.source_ids) - known_sources
        if unknown:
            raise CharacterBibleError(
                f"{character_id}.{entry.id} references unknown sources: {sorted(unknown)}"
            )
        if entry.evidence_level != "provisional" and not entry.source_ids:
            raise CharacterBibleError(
                f"{character_id}.{entry.id} requires at least one source"
            )
        if entry.continuity != (
            _optional_text(payload, "defaultContinuity", "main") or "main"
        ) and not entry.continuity_triggers:
            raise CharacterBibleError(
                f"{character_id}.{entry.id} alternate continuity requires triggers"
            )
    if status == "scaffold" and entries:
        raise CharacterBibleError(
            f"{character_id} scaffold must not contain unreviewed entries"
        )

    return CharacterBible(
        schema_version=schema_version,
        character_id=character_id,
        display_name=_required_text(payload, "displayName", context="bible"),
        work=_required_text(payload, "work", context="bible"),
        status=status,
        default_continuity=_optional_text(payload, "defaultContinuity", "main")
        or "main",
        companion_overlay=_required_text(
            payload, "companionOverlay", context="bible"
        ),
        sources=sources,
        entries=entries,
    )


@lru_cache(maxsize=32)
def _load_cached(root: str, character_id: str) -> CharacterBible:
    path = Path(root) / f"{character_id}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CharacterBibleError(
            f"character bible is missing: {character_id}"
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CharacterBibleError(
            f"cannot read character bible: {character_id}"
        ) from exc
    return parse_character_bible(payload, expected_id=character_id)


class CharacterBibleRepository:
    def __init__(self, root: Path | None = None):
        self.local_roles = root is None and not os.getenv("SHULIAN_CHARACTER_BIBLE_DIR", "").strip()
        self.root = (root or character_bible_root()).resolve()

    def load(self, character_id: str) -> CharacterBible:
        if not _SAFE_CHARACTER_ID.fullmatch(character_id):
            raise CharacterBibleError("invalid character bible id")
        if self.local_roles:
            payload = content_for(character_id).get("bible")
            if payload is None:
                raise CharacterBibleError(f"character bible is missing: {character_id}")
            return parse_character_bible(payload, expected_id=character_id)
        return _load_cached(str(self.root), character_id)

    def load_all(self) -> dict[str, CharacterBible]:
        if self.local_roles:
            return {key: self.load(key) for key in RoleContentMap("bible")}
        if not self.root.is_dir():
            raise CharacterBibleError(
                f"character bible directory is missing: {self.root}"
            )
        result: dict[str, CharacterBible] = {}
        for path in sorted(self.root.glob("*.json")):
            character_id = path.stem
            if _SAFE_CHARACTER_ID.fullmatch(character_id):
                result[character_id] = self.load(character_id)
        return result
