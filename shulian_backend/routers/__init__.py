"""FastAPI 路由层。"""

from .characters import router as characters_router
from .chat import router as chat_router
from .media import create_media_router
from .role_library import create_role_library_router
from .state import router as state_router
from .system import create_system_router

__all__ = [
    "characters_router",
    "chat_router",
    "create_media_router",
    "create_role_library_router",
    "create_system_router",
    "state_router",
]
