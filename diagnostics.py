"""Local diagnostics for Shulian.

The module intentionally records operational metadata only. It must never write
chat content, memories, API keys, prompts, or generated replies to diagnostics.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from io import BytesIO
from logging import Formatter, INFO, Logger, getLogger
from logging.handlers import RotatingFileHandler
import json
import math
import os
from pathlib import Path
import platform
import re
import sys
import threading
import time
from typing import Any, Iterable
import zipfile


_PROCESS_STARTED_MONOTONIC = time.perf_counter()
_PROCESS_STARTED_AT = datetime.now(timezone.utc)
_LOCK = threading.RLock()
_METRICS: deque[dict[str, Any]] = deque(maxlen=256)
_EVENTS: deque[dict[str, Any]] = deque(maxlen=128)
_LOGGER: Logger | None = None
_LOG_DIRECTORY: Path | None = None
_METRIC_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bsk-[a-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\b(bearer)\s+[a-z0-9._~+/=-]{8,}"),
    re.compile(
        r'(?i)(["\']?(?:api[_-]?key|authorization|access[_-]?token|secret)["\']?\s*[:=]\s*["\']?)[^"\'\s,;}{]{4,}'
    ),
    re.compile(r"(?i)([?&](?:api[_-]?key|token|secret)=)[^&#\s]+"),
)
_MAX_EXPORTED_LOG_BYTES = 512 * 1024


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def redact_text(value: object) -> str:
    """Return text with common credential forms removed."""
    text = str(value)
    text = _SECRET_PATTERNS[0].sub("sk-***REDACTED***", text)
    text = _SECRET_PATTERNS[1].sub(r"\1 ***REDACTED***", text)
    text = _SECRET_PATTERNS[2].sub(r"\1***REDACTED***", text)
    text = _SECRET_PATTERNS[3].sub(r"\1***REDACTED***", text)
    return text


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return redact_text(value)[:2_000]
    if isinstance(value, dict):
        cleaned = {}
        for key, item in list(value.items())[:32]:
            safe_key = redact_text(key)[:80]
            normalized_key = re.sub(r"[^a-z0-9]", "", safe_key.lower())
            if normalized_key in {
                "apikey",
                "authorization",
                "token",
                "accesstoken",
                "refreshtoken",
                "secret",
                "clientsecret",
                "password",
            }:
                cleaned[safe_key] = "***REDACTED***"
            else:
                cleaned[safe_key] = _sanitize(item, depth=depth + 1)
        return cleaned
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item, depth=depth + 1) for item in list(value)[:32]]
    return redact_text(value)[:2_000]


def default_log_directory() -> Path:
    configured = os.getenv("SHULIAN_LOG_DIR", "").strip()
    if configured:
        return Path(configured)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def configure_logging(log_dir: str | os.PathLike[str] | None = None) -> Path:
    """Configure one UTF-8 rotating log and return its path."""
    global _LOGGER, _LOG_DIRECTORY
    directory = Path(log_dir) if log_dir else default_log_directory()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "shulian-debug.log"
    with _LOCK:
        if _LOGGER is not None and _LOG_DIRECTORY == directory:
            return target
        logger = getLogger("shulian")
        logger.setLevel(INFO)
        logger.propagate = False
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
        try:
            max_bytes = int(os.getenv("SHULIAN_LOG_MAX_BYTES", "1048576"))
        except ValueError:
            max_bytes = 1_048_576
        max_bytes = max(262_144, min(max_bytes, 10_485_760))
        try:
            backup_count = int(os.getenv("SHULIAN_LOG_BACKUPS", "3"))
        except ValueError:
            backup_count = 3
        backup_count = max(1, min(backup_count, 8))
        handler = RotatingFileHandler(
            target,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(Formatter("%(message)s"))
        logger.addHandler(handler)
        _LOGGER = logger
        _LOG_DIRECTORY = directory
    return target


def diagnostic_log_path() -> Path:
    return configure_logging()


def log_event(
    level: str,
    code: str,
    message: object,
    **context: Any,
) -> dict[str, Any]:
    """Write a redacted structured event and keep a bounded in-memory tail."""
    severity = str(level or "info").strip().lower()
    if severity not in {"debug", "info", "warning", "error", "critical"}:
        severity = "info"
    event = {
        "at": _utc_now(),
        "level": severity,
        "code": redact_text(code or "runtime")[:96],
        "message": redact_text(message)[:4_000],
        "context": _sanitize(context),
    }
    with _LOCK:
        _EVENTS.append(event)
        logger = _LOGGER or getLogger("shulian")
        if _LOGGER is None:
            configure_logging()
            logger = _LOGGER or logger
        getattr(logger, severity, logger.info)(
            json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        )
    return event


def record_metric(
    name: str,
    duration_ms: float,
    *,
    ok: bool = True,
    **context: Any,
) -> dict[str, Any]:
    """Record a bounded latency sample without request or conversation bodies."""
    normalized = str(name or "").strip().lower()
    if not _METRIC_NAME.fullmatch(normalized):
        raise ValueError("invalid diagnostic metric name")
    duration = float(duration_ms)
    if not math.isfinite(duration) or duration < 0 or duration > 86_400_000:
        raise ValueError("invalid diagnostic duration")
    sample = {
        "at": _utc_now(),
        "name": normalized,
        "duration_ms": round(duration, 2),
        "ok": bool(ok),
        "context": _sanitize(context),
    }
    with _LOCK:
        _METRICS.append(sample)
    return sample


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    index = max(0, min(len(values) - 1, math.ceil(len(values) * ratio) - 1))
    return values[index]


def metrics_snapshot() -> dict[str, Any]:
    with _LOCK:
        samples = [dict(sample) for sample in _METRICS]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        groups[sample["name"]].append(sample)
    summary = {}
    for name, items in sorted(groups.items()):
        values = sorted(float(item["duration_ms"]) for item in items)
        summary[name] = {
            "count": len(values),
            "ok_count": sum(1 for item in items if item["ok"]),
            "average_ms": round(sum(values) / len(values), 2),
            "min_ms": round(values[0], 2),
            "max_ms": round(values[-1], 2),
            "p50_ms": round(_percentile(values, 0.50), 2),
            "p95_ms": round(_percentile(values, 0.95), 2),
            "latest_ms": round(float(items[-1]["duration_ms"]), 2),
        }
    return {
        "summary": summary,
        "recent": samples[-40:],
    }


def recent_events(limit: int = 30) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with _LOCK:
        return [dict(event) for event in list(_EVENTS)[-safe_limit:]]


def cache_usage_summary() -> dict[str, Any]:
    """Token-weighted totals from the bounded recent diagnostic event window."""
    with _LOCK:
        events = list(_EVENTS)
    groups = {}
    for event in events:
        if event.get("code") != "model_usage":
            continue
        ctx = event["context"]
        key = (ctx.get("provider"), ctx.get("model"))
        row = groups.setdefault(key, dict(provider=key[0], model=key[1], requests=0,
            measured_requests=0, hit_tokens=0, miss_tokens=0))
        row["requests"] += 1
        hit, miss = ctx.get("cache_hit_tokens"), ctx.get("cache_miss_tokens")
        if type(hit) is int and type(miss) is int:
            row["measured_requests"] += 1
            row["hit_tokens"] += hit
            row["miss_tokens"] += miss
    for row in groups.values():
        total = row["hit_tokens"] + row["miss_tokens"]
        row["hit_ratio"] = row["hit_tokens"] / total if total else None
    return {"scope": "recent_events_current_process", "models": list(groups.values())}


def runtime_snapshot(
    *,
    build_id: str,
    mode: str,
    health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    uptime_seconds = max(0.0, time.perf_counter() - _PROCESS_STARTED_MONOTONIC)
    log_path = diagnostic_log_path()
    return {
        "schema_version": 1,
        "generated_at": _utc_now(),
        "build_id": str(build_id),
        "runtime": {
            "mode": str(mode),
            "started_at": _PROCESS_STARTED_AT.isoformat(timespec="seconds"),
            "uptime_seconds": round(uptime_seconds, 1),
            "python": platform.python_version(),
            "platform": platform.system(),
            "platform_release": platform.release(),
            "architecture": platform.machine(),
            "frozen": bool(getattr(sys, "frozen", False)),
        },
        "health": _sanitize(health or {}),
        "metrics": metrics_snapshot(),
        "api_cache": cache_usage_summary(),
        "recent_events": recent_events(),
        "logging": {
            "file": log_path.name,
            "rotation": True,
            "max_export_bytes_per_file": _MAX_EXPORTED_LOG_BYTES,
        },
        "privacy": {
            "contains_chat_content": False,
            "contains_api_key": False,
            "contains_memory": False,
            "redaction_enabled": True,
        },
    }


def diagnostic_log_files(
    log_dir: str | os.PathLike[str] | None = None,
) -> list[Path]:
    directory = Path(log_dir) if log_dir else default_log_directory()
    candidates = list(directory.glob("shulian-debug.log*"))
    candidates.extend(directory.glob("gpt-sovits-service.log*"))
    return sorted(
        {
            path.resolve()
            for path in candidates
            if path.is_file()
        },
        key=lambda path: path.name,
    )


def build_diagnostic_archive(
    snapshot: dict[str, Any],
    *,
    log_files: Iterable[str | os.PathLike[str]] | None = None,
) -> bytes:
    """Build an in-memory ZIP containing only redacted operational data."""
    selected = [Path(path) for path in (log_files or diagnostic_log_files())]
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "diagnostics.json",
            json.dumps(_sanitize(snapshot), ensure_ascii=False, indent=2),
        )
        archive.writestr(
            "README.txt",
            (
                "数恋诊断包\n"
                "仅包含构建信息、运行状态、性能指标和脱敏日志。"
                "不包含聊天、长期记忆、角色图片或 API Key。\n"
            ),
        )
        for path in selected:
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            raw = raw[-_MAX_EXPORTED_LOG_BYTES:]
            text = raw.decode("utf-8", errors="replace")
            archive.writestr(f"logs/{path.name}", redact_text(text))
    return output.getvalue()


def reset_diagnostics_for_tests() -> None:
    with _LOCK:
        _METRICS.clear()
        _EVENTS.clear()
