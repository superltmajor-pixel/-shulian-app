"""Read optional private character content from immutable local snapshots.

Only JSON data is loaded. Character packages cannot execute Python or JavaScript.
"""
from collections.abc import Mapping
from functools import lru_cache
import json
from pathlib import Path

from role_archive import RoleArchiveError, _current_snapshot_dir, list_role_library


@lru_cache(maxsize=128)
def _load(path: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(value, dict):
        raise RoleArchiveError("Invalid role extensions")
    return value


def content_for(character_id: str) -> dict:
    try:
        path = _current_snapshot_dir(character_id) / "extensions.json"
        return _load(str(path))
    except RoleArchiveError:
        return {}


def content_revision(character_id: str) -> str:
    try:
        return str(_current_snapshot_dir(character_id))
    except RoleArchiveError:
        return ""


class RoleContentMap(Mapping):
    """Snapshot-aware mapping for optional per-character settings."""
    def __init__(self, key: str):
        self.key = key

    def __getitem__(self, character_id):
        content = content_for(character_id)
        if self.key not in content:
            raise KeyError(character_id)
        return content[self.key]

    def __iter__(self):
        for character_id in list_role_library().get("roles", {}):
            if self.key in content_for(character_id):
                yield character_id

    def __len__(self):
        return sum(1 for _ in self)
