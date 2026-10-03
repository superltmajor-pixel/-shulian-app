"""Edge TTS 与 GPT-SoVITS 的统一语音服务。"""

from role_content import RoleContentMap

import asyncio
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass
from typing import Protocol

from ..domain.errors import TTSConfigurationError, TTSServiceError


class _LazyModule:
    def __init__(self, name: str):
        self._name = name

    def __getattr__(self, attr: str):
        module = __import__(self._name)
        return getattr(module, attr)


edge_tts = _LazyModule("edge_tts")

TTS_VOICES = RoleContentMap("tts")
TTS_DEFAULT = {"voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "pitch": "+4Hz"}

GPT_SOVITS_DEFAULT = {
    "text_lang": "zh",
    "prompt_lang": "zh",
    "prompt_text": "",
    "text_split_method": "cut5",
    "media_type": "wav",
    "top_k": 15,
    "top_p": 1.0,
    "temperature": 1.0,
    "speed_factor": 1.0,
    "repetition_penalty": 1.35,
    "parallel_infer": True,
}
GPT_SOVITS_VOICES = {}


@dataclass(frozen=True)
class TTSResult:
    audio: bytes
    media_type: str
    provider: str
    cache_hit: bool = False


class TTSAdapter(Protocol):
    """语音供应商对数恋暴露的统一能力。"""

    provider: str

    async def synthesize(self, character_id: str, text: str) -> TTSResult: ...


class _TTSCache:
    """有上限、带过期时间的进程内语音缓存。"""

    def __init__(self) -> None:
        self._items: OrderedDict[str, tuple[float, TTSResult]] = OrderedDict()
        self._lock = threading.RLock()

    @staticmethod
    def _max_items() -> int:
        try:
            value = int(os.getenv("TTS_CACHE_MAX_ITEMS", "96"))
        except ValueError:
            value = 96
        return max(0, min(value, 512))

    @staticmethod
    def _ttl_seconds() -> float:
        try:
            value = float(os.getenv("TTS_CACHE_TTL_SECONDS", "900"))
        except ValueError:
            value = 900.0
        return max(0.0, min(value, 86_400.0))

    def get(self, key: str) -> TTSResult | None:
        max_items = self._max_items()
        ttl = self._ttl_seconds()
        if max_items == 0 or ttl == 0:
            return None
        now = time.monotonic()
        with self._lock:
            cached = self._items.get(key)
            if cached is None:
                return None
            created_at, result = cached
            if now - created_at > ttl:
                self._items.pop(key, None)
                return None
            self._items.move_to_end(key)
            return TTSResult(
                audio=result.audio,
                media_type=result.media_type,
                provider=result.provider,
                cache_hit=True,
            )

    def put(self, key: str, result: TTSResult) -> None:
        max_items = self._max_items()
        if max_items == 0 or self._ttl_seconds() == 0:
            return
        with self._lock:
            self._items[key] = (time.monotonic(), result)
            self._items.move_to_end(key)
            while len(self._items) > max_items:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_TTS_CACHE = _TTSCache()


def _formal_env(name: str, default: str = "") -> str:
    """正式版优先读取独立命名空间，同时兼容已有通用配置。"""
    formal_value = os.getenv(f"SHULIAN_FORMAL_{name}")
    if formal_value is not None:
        return formal_value
    return os.getenv(name, default)


def tts_provider() -> str:
    return _formal_env("TTS_PROVIDER", "edge").strip().lower() or "edge"


def _edge_voice_config(character_id: str) -> dict:
    config = dict(TTS_VOICES.get(character_id, TTS_DEFAULT))
    raw = _formal_env("EDGE_TTS_CHARACTER_CONFIG", "").strip()
    if not raw:
        return config
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TTSConfigurationError("EDGE_TTS_CHARACTER_CONFIG is not valid JSON") from exc
    override = payload.get(character_id, {}) if isinstance(payload, dict) else {}
    if not isinstance(override, dict):
        raise TTSConfigurationError(
            f"EDGE_TTS_CHARACTER_CONFIG.{character_id} must be an object"
        )
    for key in ("voice", "rate", "pitch"):
        if override.get(key) is not None:
            config[key] = str(override[key])
    return config


def _tts_gpt_sovits_url() -> str:
    base = _formal_env("GPT_SOVITS_BASE_URL", "").strip().rstrip("/")
    endpoint = _formal_env("GPT_SOVITS_ENDPOINT", "/tts").strip() or "/tts"
    if not base:
        raise TTSConfigurationError("GPT_SOVITS_BASE_URL is missing")
    return f"{base}/{endpoint.lstrip('/')}"


def _tts_gpt_sovits_timeout() -> float:
    raw = _formal_env("GPT_SOVITS_TIMEOUT_SECONDS", "45").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 45.0
    return max(3.0, min(value, 180.0))


def _gpt_sovits_character_config(character_id: str) -> dict:
    config = dict(GPT_SOVITS_VOICES.get(character_id, GPT_SOVITS_DEFAULT))
    raw = _formal_env("GPT_SOVITS_CHARACTER_CONFIG", "").strip()
    if not raw:
        return config
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TTSConfigurationError("GPT_SOVITS_CHARACTER_CONFIG is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise TTSConfigurationError("GPT_SOVITS_CHARACTER_CONFIG must be a JSON object")
    override = payload.get(character_id, {})
    if override is None:
        override = {}
    if not isinstance(override, dict):
        raise TTSConfigurationError(
            f"GPT_SOVITS_CHARACTER_CONFIG.{character_id} must be an object"
        )
    config.update({key: value for key, value in override.items() if value is not None})
    return config


def _build_gpt_sovits_payload(character_id: str, text: str) -> dict:
    config = _gpt_sovits_character_config(character_id)
    ref_audio_path = str(config.get("ref_audio_path", "") or "").strip()
    if not ref_audio_path:
        raise TTSConfigurationError(
            f"GPT-SoVITS ref_audio_path is missing for {character_id}"
        )

    prompt_lang = str(
        config.get("prompt_lang", GPT_SOVITS_DEFAULT["prompt_lang"]) or ""
    ).strip().lower()
    text_lang = str(
        config.get("text_lang", GPT_SOVITS_DEFAULT["text_lang"]) or ""
    ).strip().lower()
    if not prompt_lang or not text_lang:
        raise TTSConfigurationError(
            f"GPT-SoVITS language config is missing for {character_id}"
        )

    payload = {
        "text": text,
        "text_lang": text_lang,
        "ref_audio_path": ref_audio_path,
        "prompt_lang": prompt_lang,
        "prompt_text": str(config.get("prompt_text", "") or ""),
        "text_split_method": str(
            config.get("text_split_method", GPT_SOVITS_DEFAULT["text_split_method"])
        ),
        "media_type": str(config.get("media_type", GPT_SOVITS_DEFAULT["media_type"])),
        "top_k": int(config.get("top_k", GPT_SOVITS_DEFAULT["top_k"])),
        "top_p": float(config.get("top_p", GPT_SOVITS_DEFAULT["top_p"])),
        "temperature": float(
            config.get("temperature", GPT_SOVITS_DEFAULT["temperature"])
        ),
        "speed_factor": float(
            config.get("speed_factor", GPT_SOVITS_DEFAULT["speed_factor"])
        ),
        "repetition_penalty": float(
            config.get("repetition_penalty", GPT_SOVITS_DEFAULT["repetition_penalty"])
        ),
        "parallel_infer": bool(
            config.get("parallel_infer", GPT_SOVITS_DEFAULT["parallel_infer"])
        ),
    }
    aux_refs = config.get("aux_ref_audio_paths")
    if aux_refs:
        if not isinstance(aux_refs, list):
            raise TTSConfigurationError(
                f"GPT-SoVITS aux_ref_audio_paths for {character_id} must be a list"
            )
        payload["aux_ref_audio_paths"] = aux_refs
    return payload


def _post_json_audio_request(
    url: str,
    payload: dict,
    timeout_seconds: float,
) -> tuple[bytes, str]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "audio/*,application/octet-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            audio = response.read()
            media_type = response.headers.get_content_type() or "audio/wav"
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise TTSServiceError(detail or f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise TTSServiceError(str(exc.reason or exc)) from exc
    if not audio:
        raise TTSServiceError("empty audio response")
    return audio, media_type


async def _synthesize_edge_tts(character_id: str, text: str) -> tuple[bytes, str]:
    cfg = _edge_voice_config(character_id)
    try:
        communicate = edge_tts.Communicate(
            text,
            cfg["voice"],
            rate=cfg["rate"],
            pitch=cfg["pitch"],
        )
        audio = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
    except Exception as exc:
        raise TTSServiceError("edge tts failed") from exc
    if not audio:
        raise TTSServiceError("edge tts returned no audio")
    return bytes(audio), "audio/mpeg"


async def _synthesize_gpt_sovits_tts(
    character_id: str,
    text: str,
) -> tuple[bytes, str]:
    return await asyncio.to_thread(
        _post_json_audio_request,
        _tts_gpt_sovits_url(),
        _build_gpt_sovits_payload(character_id, text),
        _tts_gpt_sovits_timeout(),
    )


def gpt_sovits_has_voice(character_id: str) -> bool:
    try:
        cfg = _gpt_sovits_character_config(character_id)
    except TTSConfigurationError:
        return False
    return bool(str(cfg.get("ref_audio_path", "") or "").strip())


class EdgeTTSAdapter:
    provider = "edge"

    async def synthesize(self, character_id: str, text: str) -> TTSResult:
        audio, media_type = await _synthesize_edge_tts(character_id, text)
        return TTSResult(audio, media_type, self.provider)


class GPTSoVITSTTSAdapter:
    provider = "gpt_sovits"

    async def synthesize(self, character_id: str, text: str) -> TTSResult:
        if not gpt_sovits_has_voice(character_id):
            raise TTSConfigurationError(
                f"GPT-SoVITS voice is missing for {character_id}"
            )
        audio, media_type = await _synthesize_gpt_sovits_tts(character_id, text)
        return TTSResult(audio, media_type, self.provider)


class TTSAdapterRegistry:
    """按供应商名解析语音适配器。"""

    def __init__(self, adapters: tuple[TTSAdapter, ...]) -> None:
        self._adapters = {adapter.provider: adapter for adapter in adapters}

    def resolve(self, provider: str) -> TTSAdapter:
        try:
            return self._adapters[provider]
        except KeyError as exc:
            raise TTSConfigurationError(
                f"Unsupported TTS provider: {provider}"
            ) from exc


_TTS_ADAPTERS = TTSAdapterRegistry((EdgeTTSAdapter(), GPTSoVITSTTSAdapter()))


def _tts_retry_count() -> int:
    try:
        retries = int(os.getenv("TTS_ADAPTER_RETRIES", "1"))
    except ValueError:
        retries = 1
    return max(0, min(retries, 3))


def tts_adapter_status() -> dict:
    """返回不含音色路径和用户文本的适配层运行信息。"""
    return {
        "adapter": "unified",
        "retries": _tts_retry_count(),
        "fallback_provider": "edge",
        "cache_max_items": _TTS_CACHE._max_items(),
        "cache_ttl_seconds": _TTS_CACHE._ttl_seconds(),
        "request_cancellation": True,
        "sentence_prefetch": True,
    }


def _tts_cache_key(provider: str, character_id: str, text: str) -> str:
    if provider == "gpt_sovits":
        try:
            character_config: dict | str = _gpt_sovits_character_config(character_id)
        except TTSConfigurationError:
            character_config = _formal_env("GPT_SOVITS_CHARACTER_CONFIG", "")
        config = {
            "base_url": _formal_env("GPT_SOVITS_BASE_URL", ""),
            "endpoint": _formal_env("GPT_SOVITS_ENDPOINT", "/tts"),
            "character": character_config,
        }
    else:
        config = _edge_voice_config(character_id)
    material = json.dumps(
        {
            "provider": provider,
            "character_id": character_id,
            "text": text,
            "config": config,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


async def _synthesize_with_retry(
    adapter: TTSAdapter,
    character_id: str,
    text: str,
) -> TTSResult:
    retries = _tts_retry_count() if adapter.provider == "gpt_sovits" else 0
    for attempt in range(retries + 1):
        try:
            return await adapter.synthesize(character_id, text)
        except TTSConfigurationError:
            raise
        except TTSServiceError:
            if attempt >= retries:
                raise
            await asyncio.sleep(0.15 * (2**attempt))
    raise RuntimeError("unreachable tts retry state")


async def synthesize_tts_result(character_id: str, text: str) -> TTSResult:
    """按当前配置合成语音，并统一处理缓存、重试和降级。"""
    requested_provider = tts_provider()
    primary = _TTS_ADAPTERS.resolve(requested_provider)
    cache_key = _tts_cache_key(requested_provider, character_id, text)
    cached = _TTS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        result = await _synthesize_with_retry(primary, character_id, text)
    except (TTSServiceError, TTSConfigurationError):
        if requested_provider != "gpt_sovits":
            raise
        result = await _synthesize_with_retry(
            _TTS_ADAPTERS.resolve("edge"),
            character_id,
            text,
        )

    _TTS_CACHE.put(cache_key, result)
    return result


async def synthesize_tts(character_id: str, text: str) -> tuple[bytes, str, str]:
    """兼容原 API 的三元组返回值。"""
    result = await synthesize_tts_result(character_id, text)
    return result.audio, result.media_type, result.provider
