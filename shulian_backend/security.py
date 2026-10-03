"""本地桌面 API 的来源校验。"""

import ipaddress
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, WebSocket


_TRUSTED_HTTP_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver", "testclient"}


def is_loopback_request(request: Request) -> bool:
    if request.client is None:
        return False
    host = request.client.host.split("%", 1)[0]
    if host in {"localhost", "testclient"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(mapped and mapped.is_loopback)


def single_request_header(request: Request, name: str) -> str | None:
    """返回唯一的请求头；重复的安全头一律视为不可信。"""
    encoded_name = name.lower().encode("ascii")
    values = [
        value.decode("latin-1")
        for key, value in request.scope.get("headers", [])
        if key.lower() == encoded_name
    ]
    if len(values) != 1:
        return None
    return values[0].strip()


def trusted_authority(authority: str) -> tuple[str, int | None] | None:
    """仅接受数恋桌面端和测试客户端使用的本机 authority。"""
    if not authority or any(ord(char) < 33 or ord(char) == 127 for char in authority):
        return None
    try:
        parsed = urlsplit(f"//{authority}")
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        return None
    hostname = (parsed.hostname or "").lower()
    if hostname not in _TRUSTED_HTTP_HOSTS:
        return None
    return hostname, port


def request_authority(request: Request) -> tuple[str, int | None] | None:
    host = single_request_header(request, "host")
    return trusted_authority(host) if host is not None else None


def origin_matches_request(request: Request, origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
        origin_port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or parsed.scheme.lower() != request.url.scheme.lower()
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return False
    origin_authority = trusted_authority(parsed.netloc)
    current_authority = request_authority(request)
    if origin_authority is None or current_authority is None:
        return False
    origin_host, _ = origin_authority
    request_host, request_port = current_authority
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    return (
        origin_host == request_host
        and (origin_port or default_port) == (request_port or default_port)
    )


def require_local_write(request: Request) -> None:
    if not is_loopback_request(request):
        raise HTTPException(
            status_code=403,
            detail={"code": "local_only", "message": "此操作仅允许在本机完成"},
        )
    fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
    if fetch_site and fetch_site != "same-origin":
        raise HTTPException(
            status_code=403,
            detail={"code": "untrusted_origin", "message": "Untrusted request origin"},
        )
    origin_values = [
        value.decode("latin-1").strip()
        for key, value in request.scope.get("headers", [])
        if key.lower() == b"origin"
    ]
    if len(origin_values) > 1 or (
        origin_values and not origin_matches_request(request, origin_values[0])
    ):
        raise HTTPException(
            status_code=403,
            detail={"code": "untrusted_origin", "message": "Untrusted request origin"},
        )


def trusted_local_websocket(ws: WebSocket) -> bool:
    scope = dict(ws.scope, type="http", scheme="https" if ws.url.scheme == "wss" else "http")
    try:
        require_local_write(Request(scope))
        return len(ws.headers.getlist("origin")) == 1
    except HTTPException:
        return False
