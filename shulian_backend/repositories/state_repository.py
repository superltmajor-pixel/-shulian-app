"""SQLite 状态仓库适配器。

底层迁移和事务仍由稳定的 ``state_store.py`` 实现；应用层只依赖此接口。
"""

from state_store import (
    export_state_json,
    import_legacy_state,
    mutate_state,
    replace_state,
    state_snapshot,
    storage_status,
)


class StateRepository:
    def snapshot(self) -> dict:
        return state_snapshot()

    def mutate(self, items: dict[str, str], deleted_keys: list[str]) -> dict:
        return mutate_state(items, deleted_keys)

    def import_legacy(self, data: dict[str, str]) -> dict:
        return import_legacy_state(data)

    def replace(self, data: dict[str, str]) -> dict:
        return replace_state(data)

    def export_json(self) -> bytes:
        return export_state_json()

    def status(self) -> dict:
        return storage_status()
