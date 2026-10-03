"""路由装配所需的只读运行上下文。"""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RuntimeContext:
    build_id: str
    frozen: bool
    data_dir: str
    resource_dir: str
    env_path: str | None
    web_dir: str
    role_library_boot: Mapping[str, Any]
    roster: Mapping[str, Any]


@dataclass
class MediaContext:
    voice_dir: str
    max_voice_bytes: int
    content_types: Mapping[str, str]
    roster: Mapping[str, Any]


@dataclass(frozen=True)
class RoleLibraryContext:
    build_id: str
    web_dir: str
    voice_dir: str
    roster: Mapping[str, Any]
