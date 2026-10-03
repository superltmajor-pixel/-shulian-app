"""Load and validate source-backed personality profiles from JSON resources."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from pathlib import Path
from role_content import content_for, content_revision, RoleContentMap

from ..domain.personality import (
    BehaviorAnchor,
    CharacterOutputRail,
    DialogueExample,
    DynamicPersonalityState,
    PersonalityProfile,
    PersonalityProfileError,
    SourcedPersonalityStatement,
)
from .character_bible_repository import CharacterBibleRepository


_SAFE_CHARACTER_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ALLOWED_STATUSES = {"draft", "reviewed"}
_ALLOWED_SCHEMA_VERSIONS = {3, 4}
_ALLOWED_SEVERITIES = {"hard", "soft"}
_ALLOWED_PERSONALITY_ORIGINS = {
    "canonical_evidence",
    "interpretive_extension",
    "relationship_learned",
}
_ALLOWED_DYNAMIC_MODES = {
    "daily", "relaxed", "vulnerable", "intimate", "repair", "reintegrating", "boundary",
}
_ALLOWED_EXAMPLE_SCENARIOS = {
    "daily",
    "intimacy",
    "support",
    "conflict",
    "boundary",
    "decision",
    "interest",
    "future",
    "social",
    "media",
    "closeness",
    "reintegrating",
}
_ALLOWED_EXAMPLE_ORIGINS = {"official_adaptation", "interpretive_extension"}
_ALLOWED_EXAMPLE_CHANNELS = {
    "text",
    "image",
    "voice_message",
    "voice_call",
    "video_call",
    "proactive",
    "home_greeting",
    "new_chat",
    "gift",
}
_ALLOWED_SUBJECT_RELATIONS = {
    "unknown",
    "user_claims_character",
    "user_compares_character",
    "user_claims_self",
}
_ALLOWED_OFFICIAL_AUTHORITIES = {
    "official",
    "official_adaptation",
    "official_publisher",
    "primary_in_game",
    "primary_published_text",
}


def personality_profile_root() -> Path:
    override = os.getenv("SHULIAN_PERSONALITY_PROFILE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return (Path(getattr(sys, "_MEIPASS")) / "personality_profiles").resolve()
    return (Path(__file__).resolve().parents[2] / "personality_profiles").resolve()


def _required_text(payload: dict, name: str, *, context: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise PersonalityProfileError(f"{context}.{name} must be a non-empty string")
    return value.strip()


def _text_tuple(payload: dict, name: str, *, context: str, required: bool = False) -> tuple[str, ...]:
    values = payload.get(name, [])
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise PersonalityProfileError(f"{context}.{name} must be a string array")
    result = tuple(value.strip() for value in values)
    if required and not result:
        raise PersonalityProfileError(f"{context}.{name} must not be empty")
    return result


def _priority(payload: dict, *, context: str) -> int:
    value = payload.get("priority", 50)
    if not isinstance(value, int) or not 0 <= value <= 100:
        raise PersonalityProfileError(f"{context}.priority must be an integer from 0 to 100")
    return value


def _optional_bool(payload: dict, name: str, *, context: str) -> bool:
    value = payload.get(name, False)
    if not isinstance(value, bool):
        raise PersonalityProfileError(f"{context}.{name} must be a boolean")
    return value


def _statement(payload: object, *, context: str) -> SourcedPersonalityStatement:
    if not isinstance(payload, dict):
        raise PersonalityProfileError(f"{context} must be an object")
    origin = str(payload.get("origin") or "canonical_evidence").strip()
    if origin not in _ALLOWED_PERSONALITY_ORIGINS:
        raise PersonalityProfileError(f"{context}.origin is unsupported: {origin}")
    return SourcedPersonalityStatement(
        id=_required_text(payload, "id", context=context),
        text=_required_text(payload, "text", context=context),
        source_entry_ids=_text_tuple(
            payload, "sourceEntryIds", context=context, required=True
        ),
        origin=origin,
    )


def _bounded_int(payload: dict, name: str, *, context: str, default: int, minimum: int, maximum: int) -> int:
    value = payload.get(name, default)
    if not isinstance(value, int) or not minimum <= value <= maximum:
        raise PersonalityProfileError(
            f"{context}.{name} must be an integer from {minimum} to {maximum}"
        )
    return value


def _dynamic_state(payload: object, *, context: str) -> DynamicPersonalityState:
    if not isinstance(payload, dict):
        raise PersonalityProfileError(f"{context} must be an object")
    mode = _required_text(payload, "mode", context=context)
    if mode not in _ALLOWED_DYNAMIC_MODES:
        raise PersonalityProfileError(f"{context}.mode is unsupported: {mode}")
    origin = _required_text(payload, "origin", context=context)
    if origin not in _ALLOWED_PERSONALITY_ORIGINS:
        raise PersonalityProfileError(f"{context}.origin is unsupported: {origin}")
    return DynamicPersonalityState(
        id=_required_text(payload, "id", context=context),
        mode=mode,
        instruction=_required_text(payload, "instruction", context=context),
        relationship_floor=_bounded_int(
            payload, "relationshipFloor", context=context, default=1, minimum=1, maximum=10
        ),
        activation_floor=_bounded_int(
            payload, "activationFloor", context=context, default=0, minimum=0, maximum=4
        ),
        priority=_priority(payload, context=context),
        origin=origin,
        source_entry_ids=_text_tuple(payload, "sourceEntryIds", context=context, required=True),
    )


def _anchor(payload: object, *, context: str) -> BehaviorAnchor:
    if not isinstance(payload, dict):
        raise PersonalityProfileError(f"{context} must be an object")
    return BehaviorAnchor(
        id=_required_text(payload, "id", context=context),
        instruction=_required_text(payload, "instruction", context=context),
        triggers=_text_tuple(payload, "triggers", context=context),
        priority=_priority(payload, context=context),
        source_entry_ids=_text_tuple(
            payload, "sourceEntryIds", context=context, required=True
        ),
    )


def _example(payload: object, *, context: str) -> DialogueExample:
    if not isinstance(payload, dict):
        raise PersonalityProfileError(f"{context} must be an object")
    scenario = _required_text(payload, "scenario", context=context)
    if scenario not in _ALLOWED_EXAMPLE_SCENARIOS:
        raise PersonalityProfileError(f"{context}.scenario is unsupported: {scenario}")
    origin = _required_text(payload, "origin", context=context)
    if origin not in _ALLOWED_EXAMPLE_ORIGINS:
        raise PersonalityProfileError(f"{context}.origin is unsupported: {origin}")
    channels = _text_tuple(payload, "channels", context=context)
    unsupported_channels = set(channels) - _ALLOWED_EXAMPLE_CHANNELS
    if unsupported_channels:
        raise PersonalityProfileError(
            f"{context}.channels contains unsupported values: {sorted(unsupported_channels)}"
        )
    subject_relations = _text_tuple(payload, "subjectRelations", context=context)
    unsupported_relations = set(subject_relations) - _ALLOWED_SUBJECT_RELATIONS
    if unsupported_relations:
        raise PersonalityProfileError(
            f"{context}.subjectRelations contains unsupported values: {sorted(unsupported_relations)}"
        )
    requires_explicit_comparison = _optional_bool(
        payload, "requiresExplicitComparison", context=context
    )
    if requires_explicit_comparison and scenario != "media":
        raise PersonalityProfileError(
            f"{context}.requiresExplicitComparison is only valid for media examples"
        )
    if requires_explicit_comparison and "user_compares_character" not in subject_relations:
        raise PersonalityProfileError(
            f"{context}.requiresExplicitComparison requires user_compares_character"
        )
    if scenario == "media" and (
        "image" not in channels
        or subject_relations != ("user_compares_character",)
        or not requires_explicit_comparison
    ):
        raise PersonalityProfileError(
            f"{context} media examples must be image-enabled and restricted to an explicit character comparison"
        )
    return DialogueExample(
        id=_required_text(payload, "id", context=context),
        scenario=scenario,
        origin=origin,
        user=_required_text(payload, "user", context=context),
        assistant=_required_text(payload, "assistant", context=context),
        rationale=_required_text(payload, "rationale", context=context),
        official_source_ids=_text_tuple(
            payload, "officialSourceIds", context=context, required=True
        ),
        source_context=_required_text(payload, "sourceContext", context=context),
        adaptation_note=_required_text(payload, "adaptationNote", context=context),
        channels=channels,
        subject_relations=subject_relations,
        requires_explicit_comparison=requires_explicit_comparison,
        triggers=_text_tuple(payload, "triggers", context=context),
        priority=_priority(payload, context=context),
        source_entry_ids=_text_tuple(
            payload, "sourceEntryIds", context=context, required=True
        ),
    )


def _output_rail(payload: object, *, context: str) -> CharacterOutputRail:
    if not isinstance(payload, dict):
        raise PersonalityProfileError(f"{context} must be an object")
    severity = _required_text(payload, "severity", context=context)
    if severity not in _ALLOWED_SEVERITIES:
        raise PersonalityProfileError(f"{context}.severity is unsupported: {severity}")
    return CharacterOutputRail(
        id=_required_text(payload, "id", context=context),
        phrases=_text_tuple(payload, "phrases", context=context, required=True),
        severity=severity,
        repair_instruction=_required_text(payload, "repairInstruction", context=context),
        source_entry_ids=_text_tuple(
            payload, "sourceEntryIds", context=context, required=True
        ),
    )


def _object_array(payload: dict, name: str, *, context: str) -> list[object]:
    value = payload.get(name)
    if not isinstance(value, list) or not value:
        raise PersonalityProfileError(f"{context}.{name} must be a non-empty array")
    return value


def parse_personality_profile(
    payload: object,
    *,
    expected_id: str,
    known_source_entry_ids: set[str] | None = None,
    source_authorities: dict[str, str] | None = None,
    source_ids_by_entry: dict[str, set[str]] | None = None,
) -> PersonalityProfile:
    if not isinstance(payload, dict):
        raise PersonalityProfileError("personality profile root must be an object")
    schema_version = payload.get("schemaVersion")
    if schema_version not in _ALLOWED_SCHEMA_VERSIONS:
        raise PersonalityProfileError(
            f"unsupported personality profile schema: {schema_version}"
        )
    character_id = _required_text(payload, "characterId", context="profile")
    if character_id != expected_id:
        raise PersonalityProfileError(
            f"personality profile id mismatch: expected {expected_id}, got {character_id}"
        )
    status = _required_text(payload, "status", context="profile")
    if status not in _ALLOWED_STATUSES:
        raise PersonalityProfileError(f"unsupported personality profile status: {status}")

    profile = PersonalityProfile(
        schema_version=schema_version,
        character_id=character_id,
        display_name=_required_text(payload, "displayName", context="profile"),
        status=status,
        core_traits=tuple(
            _statement(item, context=f"coreTraits[{index}]")
            for index, item in enumerate(_object_array(payload, "coreTraits", context="profile"))
        ),
        values=tuple(
            _statement(item, context=f"values[{index}]")
            for index, item in enumerate(_object_array(payload, "values", context="profile"))
        ),
        voice=tuple(
            _statement(item, context=f"voice[{index}]")
            for index, item in enumerate(_object_array(payload, "voice", context="profile"))
        ),
        inner_dynamics=tuple(
            _statement(item, context=f"innerDynamics[{index}]")
            for index, item in enumerate(
                _object_array(payload, "innerDynamics", context="profile")
                if schema_version >= 4 else []
            )
        ),
        dynamic_states=tuple(
            _dynamic_state(item, context=f"dynamicStates[{index}]")
            for index, item in enumerate(
                _object_array(payload, "dynamicStates", context="profile")
                if schema_version >= 4 else []
            )
        ),
        closing_styles=tuple(
            _statement(item, context=f"closingStyles[{index}]")
            for index, item in enumerate(
                _object_array(payload, "closingStyles", context="profile")
                if schema_version >= 4 else []
            )
        ),
        behavior_anchors=tuple(
            _anchor(item, context=f"behaviorAnchors[{index}]")
            for index, item in enumerate(_object_array(payload, "behaviorAnchors", context="profile"))
        ),
        dialogue_examples=tuple(
            _example(item, context=f"dialogueExamples[{index}]")
            for index, item in enumerate(_object_array(payload, "dialogueExamples", context="profile"))
        ),
        output_rails=tuple(
            _output_rail(item, context=f"outputRails[{index}]")
            for index, item in enumerate(_object_array(payload, "outputRails", context="profile"))
        ),
    )

    all_items = (
        *profile.core_traits,
        *profile.values,
        *profile.voice,
        *profile.inner_dynamics,
        *profile.dynamic_states,
        *profile.closing_styles,
        *profile.behavior_anchors,
        *profile.dialogue_examples,
        *profile.output_rails,
    )
    item_ids = [item.id for item in all_items]
    if len(item_ids) != len(set(item_ids)):
        raise PersonalityProfileError(f"{character_id} contains duplicate profile item ids")
    if known_source_entry_ids is not None:
        for item in all_items:
            unknown = set(item.source_entry_ids) - known_source_entry_ids
            if unknown:
                raise PersonalityProfileError(
                    f"{character_id}.{item.id} references unknown character bible entries: {sorted(unknown)}"
                )
    if source_authorities is not None:
        for example in profile.dialogue_examples:
            unknown_sources = set(example.official_source_ids) - set(source_authorities)
            if unknown_sources:
                raise PersonalityProfileError(
                    f"{character_id}.{example.id} references unknown official sources: {sorted(unknown_sources)}"
                )
            disallowed = {
                source_id: source_authorities[source_id]
                for source_id in example.official_source_ids
                if source_authorities[source_id] not in _ALLOWED_OFFICIAL_AUTHORITIES
            }
            if disallowed:
                raise PersonalityProfileError(
                    f"{character_id}.{example.id} uses non-official sources: {sorted(disallowed)}"
                )
            if source_ids_by_entry is not None:
                supported_sources = {
                    source_id
                    for entry_id in example.source_entry_ids
                    for source_id in source_ids_by_entry.get(entry_id, set())
                }
                ungrounded = set(example.official_source_ids) - supported_sources
                if ungrounded:
                    raise PersonalityProfileError(
                        f"{character_id}.{example.id} official sources are not grounded by its bible entries: {sorted(ungrounded)}"
                    )
    return profile


class PersonalityProfileRepository:
    def __init__(
        self,
        root: Path | None = None,
        bible_repository: CharacterBibleRepository | None = None,
    ):
        self.local_roles = root is None and not os.getenv("SHULIAN_PERSONALITY_PROFILE_DIR", "").strip()
        self.root = (root or personality_profile_root()).resolve()
        self.bible_repository = bible_repository or CharacterBibleRepository()
        self._cache: dict[str, PersonalityProfile] = {}
        self._revisions: dict[str, str] = {}
        # 缓存会被多个请求线程并发读取，也可能被 clear_cache 清空。用可重入锁
        # 把「查缺失 → 解析 → 回填」收敛成原子步骤，顺带消除重复解析。
        self._cache_lock = threading.RLock()

    def load(self, character_id: str) -> PersonalityProfile:
        if not _SAFE_CHARACTER_ID.fullmatch(character_id):
            raise PersonalityProfileError("invalid personality profile id")
        with self._cache_lock:
            if self.local_roles:
                revision = content_revision(character_id)
                if self._revisions.get(character_id) != revision:
                    self._cache.pop(character_id, None)
                    self._revisions[character_id] = revision
            cached = self._cache.get(character_id)
            if cached is not None:
                return cached
            return self._load_uncached(character_id)

    def _load_uncached(self, character_id: str) -> PersonalityProfile:
        path = self.root / f"{character_id}.json"
        try:
            if self.local_roles:
                payload = content_for(character_id).get("personality")
                if payload is None:
                    raise FileNotFoundError(character_id)
            else:
                payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise PersonalityProfileError(
                f"personality profile is missing: {character_id}"
            ) from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PersonalityProfileError(
                f"cannot read personality profile: {character_id}"
            ) from exc
        bible = self.bible_repository.load(character_id)
        profile = parse_personality_profile(
            payload,
            expected_id=character_id,
            known_source_entry_ids={entry.id for entry in bible.entries},
            source_authorities={source.id: source.authority for source in bible.sources},
            source_ids_by_entry={
                entry.id: set(entry.source_ids) for entry in bible.entries
            },
        )
        self._cache[character_id] = profile
        return profile

    def load_all(self) -> dict[str, PersonalityProfile]:
        if self.local_roles:
            return {key: self.load(key) for key in RoleContentMap("personality")}
        if not self.root.is_dir():
            raise PersonalityProfileError(
                f"personality profile directory is missing: {self.root}"
            )
        result: dict[str, PersonalityProfile] = {}
        for path in sorted(self.root.glob("*.json")):
            if _SAFE_CHARACTER_ID.fullmatch(path.stem):
                result[path.stem] = self.load(path.stem)
        return result

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()
