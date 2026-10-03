"""SQLite 状态业务服务。"""

import sqlite3
from collections.abc import Callable
from typing import TypeVar

from state_store import StateStoreError, StateValidationError

from ..domain.errors import InvalidStateDataError, StateUnavailableError
from ..repositories.state_repository import StateRepository


T = TypeVar("T")


class StateService:
    def __init__(self, repository: StateRepository | None = None):
        self._repository = repository or StateRepository()

    @staticmethod
    def _run(operation: Callable[[], T]) -> T:
        try:
            return operation()
        except StateValidationError as exc:
            raise InvalidStateDataError(str(exc)) from exc
        except (StateStoreError, OSError, sqlite3.Error) as exc:
            raise StateUnavailableError("本地数据存储暂不可用") from exc

    def snapshot(self) -> dict:
        return self._run(self._repository.snapshot)

    def mutate(self, items: dict[str, str], deleted_keys: list[str]) -> dict:
        return self._run(lambda: self._repository.mutate(items, deleted_keys))

    def import_legacy(self, data: dict[str, str]) -> dict:
        return self._run(lambda: self._repository.import_legacy(data))

    def replace(self, data: dict[str, str]) -> dict:
        return self._run(lambda: self._repository.replace(data))

    def clear(self) -> dict:
        return self.replace({})

    def export_json(self) -> bytes:
        return self._run(self._repository.export_json)

    def status(self) -> dict:
        return self._run(self._repository.status)


state_service = StateService()
