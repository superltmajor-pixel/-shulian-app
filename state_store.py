from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
MAX_STATE_ITEMS = 4096
MAX_KEY_LENGTH = 160
MAX_VALUE_BYTES = 8 * 1024 * 1024
MAX_BATCH_BYTES = 32 * 1024 * 1024

_SAFE_KEY = re.compile(r"^sl_[A-Za-z0-9_.:-]{1,156}$")
_INTERNAL_PREFIX = "sl_sqlite_"
_INIT_LOCK = threading.RLock()

# 进程内初始化缓存：一次状态快照原先要 3 次开连接 + 2 次 quick_check + 1 个写事务，
# 即使数据库已是目标版本、没有任何迁移要做。quick_check 的耗时随库大小线性增长，
# 而 /api/state 是高频路径，所以只在这里缓存“这个库文件已经初始化过”。
_initialized_path: str | None = None


class StateStoreError(RuntimeError):
    pass


class StateValidationError(StateStoreError):
    pass


def state_database_path() -> Path:
    override = os.getenv("SHULIAN_STATE_DB", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        base = Path(local_app_data)
    else:
        base = Path.home() / "AppData" / "Local"
    return (base / "Shulian" / "data" / "shulian.sqlite3").resolve()


def _connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or state_database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, timeout=8.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 8000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = FULL")
    return connection


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _database_has_user_objects(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
          AND type IN ('table', 'index', 'trigger', 'view')
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def _backup_before_migration(connection: sqlite3.Connection, from_version: int) -> Path:
    database = state_database_path()
    backup_dir = database.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    final_path = backup_dir / f"shulian-v{from_version}-{stamp}.sqlite3"
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{final_path.name}.",
        dir=backup_dir,
    )
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        with closing(sqlite3.connect(temp_path)) as backup:
            connection.backup(backup)
            backup.execute("PRAGMA integrity_check")
        os.replace(temp_path, final_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return final_path


def _migrate_to_v1(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS state_items (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            revision INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS state_metadata (
            name TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO state_metadata(name, value)
        VALUES ('revision', '0')
        """
    )
    if _table_exists(connection, "state"):
        legacy_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(state)").fetchall()
        }
        if {"key", "value"}.issubset(legacy_columns):
            now = _utc_now()
            connection.execute(
                """
                INSERT OR IGNORE INTO state_items(key, value, revision, updated_at)
                SELECT key, value, 1, ?
                FROM state
                WHERE key LIKE 'sl_%'
                """,
                (now,),
            )
            connection.execute(
                """
                UPDATE state_metadata
                SET value = CASE
                    WHEN EXISTS(SELECT 1 FROM state_items) THEN '1'
                    ELSE value
                END
                WHERE name = 'revision'
                """
            )


_MIGRATIONS = {
    1: _migrate_to_v1,
}


def initialize_state_store() -> dict:
    global _initialized_path
    with _INIT_LOCK:
        database = state_database_path()
        with closing(_connect(database)) as connection:
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > SCHEMA_VERSION:
                raise StateStoreError(
                    f"State database schema {current} is newer than supported {SCHEMA_VERSION}"
                )
            backup_path: Path | None = None
            if current < SCHEMA_VERSION and _database_has_user_objects(connection):
                backup_path = _backup_before_migration(connection, current)
            try:
                connection.execute("BEGIN IMMEDIATE")
                for target in range(current + 1, SCHEMA_VERSION + 1):
                    migration = _MIGRATIONS.get(target)
                    if migration is None:
                        raise StateStoreError(f"Missing state migration {target}")
                    migration(connection)
                    connection.execute(f"PRAGMA user_version = {target}")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                raise StateStoreError(f"State database integrity check failed: {integrity}")
        # 上面这个连接刚做完 quick_check，这里不要再让 storage_status 重开连接、
        # 再扫一遍同一个库。
        status = storage_status(check_integrity=False)
        status["migration_backup"] = str(backup_path) if backup_path else None
        # 任何一次成功初始化都顺便给热路径缓存「这个库文件已经初始化过」。
        _initialized_path = str(database)
        return status


def _reset_initialization_cache() -> None:
    """清空进程内初始化缓存。

    仅供测试或明确知道库文件被外部替换/删除时使用；正常读写路径不要调用。
    """
    global _initialized_path
    with _INIT_LOCK:
        _initialized_path = None


def _ensure_state_store() -> None:
    """热路径闸门：同一个库文件在进程内只做一次完整初始化。

    首次调用等价于 ``initialize_state_store()``；之后直接返回，跳过迁移、
    quick_check 和额外的连接。库文件若被外部删除，会重新初始化。
    """
    global _initialized_path
    target = state_database_path()
    key = str(target)
    if _initialized_path == key and target.exists():
        return
    with _INIT_LOCK:
        if _initialized_path == key and target.exists():
            return
        initialize_state_store()
        _initialized_path = key


def _validate_key(key: object) -> str:
    value = str(key or "")
    if (
        len(value) > MAX_KEY_LENGTH
        or not _SAFE_KEY.fullmatch(value)
        or value.startswith(_INTERNAL_PREFIX)
    ):
        raise StateValidationError("Invalid state key")
    return value


def _validate_items(items: object) -> dict[str, str]:
    if not isinstance(items, dict):
        raise StateValidationError("State items must be an object")
    if len(items) > MAX_STATE_ITEMS:
        raise StateValidationError("Too many state items")
    clean: dict[str, str] = {}
    total = 0
    for raw_key, raw_value in items.items():
        key = _validate_key(raw_key)
        if not isinstance(raw_value, str):
            raise StateValidationError(f"State value for {key} must be a string")
        size = len(raw_value.encode("utf-8"))
        if size > MAX_VALUE_BYTES:
            raise StateValidationError(f"State value for {key} is too large")
        total += len(key.encode("utf-8")) + size
        if total > MAX_BATCH_BYTES:
            raise StateValidationError("State batch is too large")
        clean[key] = raw_value
    return clean


def _validate_deleted_keys(keys: object) -> list[str]:
    if not isinstance(keys, list):
        raise StateValidationError("Deleted keys must be a list")
    if len(keys) > MAX_STATE_ITEMS:
        raise StateValidationError("Too many deleted state keys")
    return list(dict.fromkeys(_validate_key(key) for key in keys))


def _current_revision(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT value FROM state_metadata WHERE name = 'revision'"
    ).fetchone()
    return int(row["value"]) if row else 0


def _advance_revision(connection: sqlite3.Connection) -> int:
    revision = _current_revision(connection) + 1
    connection.execute(
        """
        INSERT INTO state_metadata(name, value) VALUES ('revision', ?)
        ON CONFLICT(name) DO UPDATE SET value = excluded.value
        """,
        (str(revision),),
    )
    return revision


def state_snapshot(keys: list[str] | None = None) -> dict:
    _ensure_state_store()
    with closing(_connect()) as connection:
        if keys is None:
            rows = connection.execute("SELECT key, value FROM state_items ORDER BY key").fetchall()
        else:
            selected = [_validate_key(key) for key in keys]
            placeholders = ",".join("?" for _ in selected)
            rows = connection.execute(
                f"SELECT key, value FROM state_items WHERE key IN ({placeholders}) ORDER BY key",
                selected,
            ).fetchall() if selected else []
        revision = _current_revision(connection)
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": revision,
        "item_count": len(rows),
        "data": {row["key"]: row["value"] for row in rows},
    }


def mutate_state(items: object, deleted_keys: object) -> dict:
    clean_items = _validate_items(items)
    clean_deleted = _validate_deleted_keys(deleted_keys)
    deleted = [key for key in clean_deleted if key not in clean_items]
    _ensure_state_store()
    with closing(_connect()) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            revision = _advance_revision(connection)
            now = _utc_now()
            connection.executemany(
                """
                INSERT INTO state_items(key, value, revision, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    revision = excluded.revision,
                    updated_at = excluded.updated_at
                """,
                [
                    (key, value, revision, now)
                    for key, value in clean_items.items()
                ],
            )
            if deleted:
                connection.executemany(
                    "DELETE FROM state_items WHERE key = ?",
                    [(key,) for key in deleted],
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        count = int(connection.execute("SELECT COUNT(*) FROM state_items").fetchone()[0])
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "revision": revision,
        "item_count": count,
        "updated": len(clean_items),
        "deleted": len(deleted),
    }


def import_legacy_state(items: object) -> dict:
    clean = _validate_items(items)
    _ensure_state_store()
    with closing(_connect()) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = int(connection.execute("SELECT COUNT(*) FROM state_items").fetchone()[0])
            if existing:
                connection.rollback()
                return {
                    "ok": True,
                    "schema_version": SCHEMA_VERSION,
                    "revision": _current_revision(connection),
                    "item_count": existing,
                    "imported": 0,
                    "skipped": len(clean),
                }
            revision = _advance_revision(connection) if clean else _current_revision(connection)
            now = _utc_now()
            connection.executemany(
                """
                INSERT INTO state_items(key, value, revision, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                [(key, value, revision, now) for key, value in clean.items()],
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "revision": revision,
        "item_count": len(clean),
        "imported": len(clean),
        "skipped": 0,
    }


def replace_state(items: object) -> dict:
    clean = _validate_items(items)
    _ensure_state_store()
    with closing(_connect()) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            revision = _advance_revision(connection)
            now = _utc_now()
            connection.execute("DELETE FROM state_items")
            connection.executemany(
                """
                INSERT INTO state_items(key, value, revision, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                [(key, value, revision, now) for key, value in clean.items()],
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "revision": revision,
        "item_count": len(clean),
    }


def export_state_json() -> bytes:
    snapshot = state_snapshot()
    payload = {
        "_app": "shulian",
        "_ver": 2,
        "_at": int(datetime.now(timezone.utc).timestamp() * 1000),
        "_storage": {
            "engine": "sqlite",
            "schema_version": snapshot["schema_version"],
            "revision": snapshot["revision"],
        },
        "data": snapshot["data"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def storage_status(*, check_integrity: bool = True) -> dict:
    """返回存储状态。

    ``check_integrity=False`` 供刚做过 quick_check 的调用方复用结果，
    避免在同一次初始化里对同一个库扫描两遍。
    """
    database = state_database_path()
    if not database.exists():
        return {
            "ok": True,
            "engine": "sqlite",
            "schema_version": 0,
            "target_schema_version": SCHEMA_VERSION,
            "revision": 0,
            "item_count": 0,
        }
    try:
        with closing(_connect(database)) as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if _table_exists(connection, "state_items"):
                count = int(connection.execute("SELECT COUNT(*) FROM state_items").fetchone()[0])
            else:
                count = 0
            if _table_exists(connection, "state_metadata"):
                revision = _current_revision(connection)
            else:
                revision = 0
            integrity = "ok"
            if check_integrity:
                integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        return {
            "ok": integrity == "ok" and version == SCHEMA_VERSION,
            "engine": "sqlite",
            "schema_version": version,
            "target_schema_version": SCHEMA_VERSION,
            "revision": revision,
            "item_count": count,
        }
    except (OSError, sqlite3.Error, ValueError) as exc:
        return {
            "ok": False,
            "engine": "sqlite",
            "schema_version": None,
            "target_schema_version": SCHEMA_VERSION,
            "revision": None,
            "item_count": None,
            "error": type(exc).__name__,
        }
