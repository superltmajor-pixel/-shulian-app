"""Local, non-secret AI preferences for Shulian."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


SCHEMA_VERSION = 1
DEFAULT_MODEL = "deepseek-flash"
SUPPORTED_MODELS = (
    DEFAULT_MODEL,
    "doubao-seed-character-260628",
)


def preferences_path() -> Path:
    override = os.getenv("SHULIAN_AI_PREFERENCES_FILE", "").strip()
    if override:
        return Path(override)
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "ShulianArchiveOnly" / "config" / "ai-preferences.json"


def normalize_model(value: object) -> str:
    if isinstance(value, str) and value in SUPPORTED_MODELS:
        return value
    return DEFAULT_MODEL


def load_model(path: Path | None = None) -> str:
    target = path or preferences_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return DEFAULT_MODEL
    if not isinstance(payload, dict):
        return DEFAULT_MODEL
    return normalize_model(payload.get("model"))


def save_model(model: str, path: Path | None = None) -> None:
    if model not in SUPPORTED_MODELS:
        raise ValueError("Unsupported AI model")
    target = path or preferences_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"schemaVersion": SCHEMA_VERSION, "model": model},
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
