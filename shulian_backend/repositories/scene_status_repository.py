"""共同场景状态的 SQLite 状态仓库适配器。"""

from __future__ import annotations

import json
from typing import Any

from state_store import mutate_state, state_snapshot


SCENE_STATE_KEY = "sl_scene_overrides"


class SceneStatusRepository:
    """Persist short-lived shared-scene overrides in the existing state store."""

    def load(self) -> dict[str, Any]:
        raw = state_snapshot()["data"].get(SCENE_STATE_KEY, "")
        if not raw:
            return {}
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return {}
        overrides = payload.get("overrides", {})
        return overrides if isinstance(overrides, dict) else {}

    def save(self, overrides: dict[str, Any]) -> None:
        if overrides:
            value = json.dumps(
                {"version": 1, "overrides": overrides},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            mutate_state({SCENE_STATE_KEY: value}, [])
        else:
            mutate_state({}, [SCENE_STATE_KEY])
