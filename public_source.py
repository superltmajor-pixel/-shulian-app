"""Shared source-publication and web-package boundaries (no private role data)."""
import re
from pathlib import PurePosixPath

_PRIVATE_PARTS = {"role-library", "local-data", "webview-data", "media", "logs",
                  "migration-backups", "character_bibles", "personality_profiles"}
_TEMPORARY = re.compile(r"(?:\.before-|\.bak\d*|\.tmp|\.orig|~$)", re.I)
_BRAND_IMAGES = {"web/shulian-brand-icon.png"}


def private_path(value: str) -> bool:
    path = PurePosixPath(value.replace("\\", "/"))
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    return bool(parts & _PRIVATE_PARTS or "assets" in parts
                or (name.startswith(".env") and name != ".env.example")
                or path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".log"}
                or _TEMPORARY.search(name))


def public_web_file(value: str) -> bool:
    path = PurePosixPath(value.replace("\\", "/"))
    if private_path(value) or not value.startswith("web/"):
        return False
    if value in _BRAND_IMAGES:
        return True
    return path.suffix.lower() in {".jsx", ".js", ".css", ".html", ".svg", ".json", ".woff2", ".otf", ".ttf", ".txt"}
