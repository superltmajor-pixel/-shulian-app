"""Structured, source-backed personality profile models.

The runtime keeps immutable character identity, dynamic scene state, memories,
and output rails in separate layers.  Personality profiles only describe the
stable values, voice, decision tendencies, examples and character-specific
output constraints that belong to one character.
"""

from __future__ import annotations

from dataclasses import dataclass


class PersonalityProfileError(RuntimeError):
    """A personality profile is missing, malformed or has invalid provenance."""


@dataclass(frozen=True)
class SourcedPersonalityStatement:
    id: str
    text: str
    source_entry_ids: tuple[str, ...]
    origin: str = "canonical_evidence"


@dataclass(frozen=True)
class BehaviorAnchor:
    id: str
    instruction: str
    triggers: tuple[str, ...]
    priority: int
    source_entry_ids: tuple[str, ...]


@dataclass(frozen=True)
class DialogueExample:
    id: str
    scenario: str
    origin: str
    user: str
    assistant: str
    rationale: str
    official_source_ids: tuple[str, ...]
    source_context: str
    adaptation_note: str
    channels: tuple[str, ...]
    subject_relations: tuple[str, ...]
    requires_explicit_comparison: bool
    triggers: tuple[str, ...]
    priority: int
    source_entry_ids: tuple[str, ...]


@dataclass(frozen=True)
class CharacterOutputRail:
    id: str
    phrases: tuple[str, ...]
    severity: str
    repair_instruction: str
    source_entry_ids: tuple[str, ...]


@dataclass(frozen=True)
class DynamicPersonalityState:
    id: str
    mode: str
    instruction: str
    relationship_floor: int
    activation_floor: int
    priority: int
    origin: str
    source_entry_ids: tuple[str, ...]


@dataclass(frozen=True)
class PersonalityProfile:
    schema_version: int
    character_id: str
    display_name: str
    status: str
    core_traits: tuple[SourcedPersonalityStatement, ...]
    values: tuple[SourcedPersonalityStatement, ...]
    voice: tuple[SourcedPersonalityStatement, ...]
    inner_dynamics: tuple[SourcedPersonalityStatement, ...]
    dynamic_states: tuple[DynamicPersonalityState, ...]
    closing_styles: tuple[SourcedPersonalityStatement, ...]
    behavior_anchors: tuple[BehaviorAnchor, ...]
    dialogue_examples: tuple[DialogueExample, ...]
    output_rails: tuple[CharacterOutputRail, ...]
