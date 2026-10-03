"""数恋 FastAPI 应用装配入口。

本文件只负责：
1. 解析源码/打包运行目录并加载非敏感环境配置；
2. 创建 FastAPI 应用、异常处理器和跨路由中间件；
3. 装配模块化 routers / services / repositories / schemas / domain；
4. 最后挂载本地语音目录和前端静态资源。
"""

import os
import sys
import time
import traceback
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from diagnostics import log_event, record_metric
from shulian_backend.version import APP_VERSION, BUILD_ID


_FROZEN = getattr(sys, "frozen", False)
_DEFAULT_BUILD_ID = BUILD_ID
_BUILD_ID = (
    _DEFAULT_BUILD_ID
    if _FROZEN
    else os.getenv("SHULIAN_BUILD_ID", "").strip() or _DEFAULT_BUILD_ID
)


def _resource_dir() -> str:
    """打包后返回 PyInstaller 资源目录，源码运行时返回仓库根目录。"""
    if _FROZEN:
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _data_dir() -> str:
    """打包后返回 EXE 目录，源码运行时返回仓库根目录。"""
    if _FROZEN:
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


_HERE = _resource_dir()
_DATA = _data_dir()
_ENV_PATH = None

# .env 只承载模型、超时与 TTS 等非敏感配置；API Key 走加密凭据门禁。
_env_candidates = []
_external_env_path = os.getenv("SHULIAN_ENV_FILE", "").strip()
if _external_env_path:
    _env_candidates.append(_external_env_path)
_env_candidates.extend([os.path.join(_DATA, ".env"), os.path.join(_HERE, ".env")])
for _env_path in _env_candidates:
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
        _ENV_PATH = _env_path
        break

# 永远不允许环境变量绕过 API Key 连接页。
os.environ.pop("DEEPSEEK_API_KEY", None)

# 依赖环境配置的应用模块必须在 load_dotenv 之后导入。
from characters import ROSTER
from role_archive import apply_role_library_to_roster
from shulian_backend.domain import (
    MediaContext,
    RoleLibraryContext,
    RuntimeContext,
    TTSConfigurationError,
    TTSServiceError,
)
from shulian_backend.routers import (
    characters_router,
    chat_router,
    create_media_router,
    create_role_library_router,
    create_system_router,
    state_router,
)
from shulian_backend.security import request_authority
from shulian_backend.routers.local_asr import router as local_asr_router
from shulian_backend.routers.realtime_voice import router as realtime_voice_router
from shulian_backend.routers.role_preview import router as role_preview_router
from shulian_backend.routers.role_history import router as role_history_router
from shulian_backend.routers.role_suggest import router as role_suggest_router


_ROLE_LIBRARY_BOOT = apply_role_library_to_roster(
    ROSTER,
    preserve_existing=True,
)

app = FastAPI(title="数恋 API", version=APP_VERSION)


# ── 统一错误与观测 ────────────────────────────────────────────────

def _request_id(request: Request) -> str:
    current = getattr(request.state, "request_id", "")
    if current:
        return current
    current = uuid.uuid4().hex[:12]
    request.state.request_id = current
    return current


def _diagnostic_route(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", "")
    if template:
        return str(template)[:200]
    path = request.url.path
    if path.startswith("/api/"):
        return "/api/unknown"
    return path[:80]


def _error_identity(
    request: Request,
    status_code: int,
    detail: object,
) -> dict[str, str]:
    if isinstance(detail, dict):
        code = str(detail.get("code") or "").strip()
        message = str(detail.get("message") or "").strip()
    else:
        code = ""
        message = str(detail or "").strip()
    if not code:
        code = {
            400: "invalid_request",
            401: "authentication_failed",
            403: "forbidden",
            404: "not_found",
            413: "request_too_large",
            415: "unsupported_media_type",
            422: "invalid_request",
            500: "internal_error",
            502: "upstream_unavailable",
            503: "service_unavailable",
        }.get(status_code, f"http_{status_code}")
    if not message:
        message = "请求处理失败"
    return {
        "code": code,
        "message": message,
        "request_id": _request_id(request),
    }


def _json_error_response(
    request: Request,
    status_code: int,
    detail: object,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": detail,
            "error": _error_identity(request, status_code, detail),
        },
    )


@app.exception_handler(StarletteHTTPException)
async def structured_http_error(request: Request, exc: StarletteHTTPException):
    error = _error_identity(request, exc.status_code, exc.detail)
    log_event(
        "warning" if exc.status_code < 500 else "error",
        error["code"],
        error["message"],
        request_id=error["request_id"],
        method=request.method,
        path=_diagnostic_route(request),
        status=exc.status_code,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "error": error},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def structured_validation_error(
    request: Request,
    exc: RequestValidationError,
):
    error = _error_identity(
        request,
        422,
        {"code": "invalid_request", "message": "请求内容格式不正确"},
    )
    safe_details = [
        {key: value for key, value in item.items() if key not in {"input", "ctx"}}
        for item in exc.errors()
    ]
    log_event(
        "warning",
        error["code"],
        error["message"],
        request_id=error["request_id"],
        method=request.method,
        path=_diagnostic_route(request),
        status=422,
    )
    return JSONResponse(
        status_code=422,
        content={"detail": safe_details, "error": error},
    )


def _error_traceback(exc: Exception) -> str:
    """返回脱敏且只保留尾部的 traceback —— 抛错现场通常在最后几帧。

    log_event 会再走一次 redact/截断；这里先裁尾部，避免 _sanitize 从头截断
    把真正有用的帧丢掉。
    """
    try:
        rendered = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
    except Exception:  # traceback 渲染本身失败时不能影响 500 响应
        return ""
    return rendered[-1_800:]


@app.exception_handler(Exception)
async def structured_internal_error(request: Request, exc: Exception):
    error = _error_identity(
        request,
        500,
        {"code": "internal_error", "message": "数恋内部服务发生错误"},
    )
    log_event(
        "error",
        error["code"],
        error["message"],
        request_id=error["request_id"],
        method=request.method,
        path=_diagnostic_route(request),
        exception=type(exc).__name__,
        detail=str(exc)[:500],
        traceback=_error_traceback(exc),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": error["message"], "error": error},
    )


@app.middleware("http")
async def diagnostic_request_context(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex[:12]
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        record_metric(
            "http.request",
            (time.perf_counter() - started_at) * 1000,
            ok=False,
            method=request.method,
            path=_diagnostic_route(request),
            status=500,
        )
        raise
    duration_ms = (time.perf_counter() - started_at) * 1000
    if request.url.path.startswith("/api/"):
        record_metric(
            "http.request",
            duration_ms,
            ok=response.status_code < 500,
            method=request.method,
            path=_diagnostic_route(request),
            status=response.status_code,
        )
    response.headers.setdefault("X-Request-ID", request.state.request_id)
    response.headers.setdefault("Server-Timing", f"app;dur={duration_ms:.2f}")
    return response


@app.middleware("http")
async def disable_frontend_cache(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path.lower()
    if (
        path in {"/", "/api/ai-config", "/api/self-check"}
        or path.endswith((".html", ".jsx", ".css", ".js"))
    ):
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ── 跨路由安全与容量限制 ──────────────────────────────────────────

def _csv_env(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


cors_origins = _csv_env("CORS_ORIGINS")
if "*" in cors_origins:
    raise RuntimeError("CORS_ORIGINS must list trusted origins; wildcard '*' is not allowed")
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(os.getenv(name, str(default))), maximum))
    except ValueError:
        return default


MAX_REQUEST_BYTES = _bounded_int_env(
    "MAX_REQUEST_BYTES",
    131_072,
    16_384,
    1_048_576,
)
MAX_CHAT_REQUEST_BYTES = _bounded_int_env(
    "MAX_CHAT_REQUEST_BYTES",
    10_485_760,
    1_048_576,
    16_777_216,
)
MAX_VOICE_BYTES = _bounded_int_env(
    "MAX_VOICE_BYTES",
    4_194_304,
    262_144,
    10_485_760,
)
ROLE_ARCHIVE_MAX_BYTES = _bounded_int_env(
    "ROLE_ARCHIVE_MAX_BYTES",
    67_108_864,
    1_048_576,
    134_217_728,
)
STATE_REQUEST_MAX_BYTES = _bounded_int_env(
    "STATE_REQUEST_MAX_BYTES",
    16_777_216,
    1_048_576,
    33_554_432,
)

VOICE_CONTENT_TYPES = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}
VOICE_DIR = os.getenv("SHULIAN_VOICE_DIR", "").strip() or (
    os.path.join(_DATA, "media")
    if _FROZEN
    else os.path.join(_HERE, "web", "media")
)


def _web_dir() -> str:
    """优先使用 EXE 旁可替换的 web，缺失时回退到打包内置资源。"""
    external = os.path.join(_DATA, "web")
    if os.path.exists(os.path.join(external, "index.html")):
        return external
    return os.path.join(_HERE, "web")


WEB_DIR = _web_dir()


@app.middleware("http")
async def security_headers_and_request_limit(request: Request, call_next):
    if request.url.path.startswith("/api/role-library/") and request.method in {"POST", "PUT"}:
        request_limit = ROLE_ARCHIVE_MAX_BYTES
    elif request.url.path.startswith("/api/state") and request.method in {"POST", "PUT"}:
        request_limit = STATE_REQUEST_MAX_BYTES
    elif request.url.path.startswith("/api/chat/") and request.method == "POST":
        request_limit = MAX_CHAT_REQUEST_BYTES
    else:
        request_limit = (
            MAX_VOICE_BYTES if request.url.path == "/api/voice" else MAX_REQUEST_BYTES
        )
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > request_limit:
                response = _json_error_response(request, 413, "请求内容过大")
            else:
                response = await call_next(request)
        except ValueError:
            response = _json_error_response(request, 400, "Content-Length 无效")
    else:
        response = await call_next(request)

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(self), microphone=(self), geolocation=()",
    )
    return response


@app.middleware("http")
async def trusted_local_host_boundary(request: Request, call_next):
    """在进入路由前拒绝 DNS rebinding 和伪造 Host。"""
    if request_authority(request) is None:
        response = _json_error_response(
            request,
            400,
            {
                "code": "invalid_host",
                "message": "Untrusted request host",
            },
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(self), microphone=(self), geolocation=()"
        )
        return response
    return await call_next(request)


# ── 路由装配 ──────────────────────────────────────────────────────

_RUNTIME_CONTEXT = RuntimeContext(
    build_id=_BUILD_ID,
    frozen=_FROZEN,
    data_dir=_DATA,
    resource_dir=_HERE,
    env_path=_ENV_PATH,
    web_dir=WEB_DIR,
    role_library_boot=_ROLE_LIBRARY_BOOT,
    roster=ROSTER,
)
_ROLE_LIBRARY_CONTEXT = RoleLibraryContext(
    build_id=_BUILD_ID,
    web_dir=WEB_DIR,
    voice_dir=VOICE_DIR,
    roster=ROSTER,
)
_MEDIA_CONTEXT = MediaContext(
    voice_dir=VOICE_DIR,
    max_voice_bytes=MAX_VOICE_BYTES,
    content_types=VOICE_CONTENT_TYPES,
    roster=ROSTER,
)

app.include_router(create_system_router(_RUNTIME_CONTEXT))
app.include_router(state_router)
app.include_router(characters_router)
app.include_router(create_role_library_router(_ROLE_LIBRARY_CONTEXT))
app.include_router(role_preview_router)
app.include_router(role_history_router)
app.include_router(role_suggest_router)
app.include_router(chat_router)
app.include_router(realtime_voice_router)
app.include_router(local_asr_router)
app.include_router(create_media_router(_MEDIA_CONTEXT))


# 静态资源必须在全部 API 路由之后挂载。
os.makedirs(VOICE_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=VOICE_DIR), name="media")
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
