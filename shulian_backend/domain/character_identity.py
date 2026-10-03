"""Stable identity aliases used by prompt and memory safety checks."""

from __future__ import annotations
from role_content import RoleContentMap


CHARACTER_SELF_ALIASES = RoleContentMap("aliases")


def aliases_for_character(character_id: str, character_name: str = "") -> tuple[str, ...]:
    aliases = CHARACTER_SELF_ALIASES.get(str(character_id or "").strip(), ())
    clean_name = str(character_name or "").strip()
    if aliases:
        return aliases
    if clean_name:
        for known_aliases in CHARACTER_SELF_ALIASES.values():
            if clean_name in known_aliases:
                return known_aliases
        return (clean_name,)
    return ()
