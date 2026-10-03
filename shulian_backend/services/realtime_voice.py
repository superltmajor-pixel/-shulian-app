"""Realtime voice configuration and character context. No paid requests here."""

import json
import threading

from pydantic import BaseModel, ConfigDict, Field, SecretStr

import ai_credentials
from status_engine import format_status_context, get_character_status
from .context_compiler import compile_companion_messages, trim_complete_history_pairs

DEFAULT_SPEAKER = "saturn_zh_female_wenrouwenya_tob"
_config_lock = threading.Lock()


class ContextTooLargeError(ValueError):
    """Do not silently cut identity/relationship rules to fit the provider."""


class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    access_key: SecretStr = Field(default=SecretStr(""), max_length=4096)
    speaker: str = Field(default=DEFAULT_SPEAKER, pattern=r"^(saturn_|S_)[A-Za-z0-9_-]+$", max_length=150)
    character_id: str = Field(default="", max_length=64)


def config_path():
    # Separate formal-build credential, outside source/dist and release payloads.
    return ai_credentials.credential_path().with_name("formal-realtime-voice.bin")


def load_config() -> dict:
    raw = ai_credentials.load_api_key(config_path())
    return json.loads(raw) if raw else {}


def public_config(config: dict, character_id: str = "") -> dict:
    return {
        "configured": bool(config.get("app_id") and config.get("access_key")),
        "app_id": config.get("app_id", ""),
        "speaker": config.get("speakers", {}).get(character_id, config.get("speaker", DEFAULT_SPEAKER)),
        "model": "2.2.0.0",
    }


def save_config(update: VoiceConfig) -> dict:
    with _config_lock:
        previous = load_config()
        key = update.access_key.get_secret_value().strip()
        if not key:
            if update.app_id != previous.get("app_id") or not previous.get("access_key"):
                raise ValueError("首次配置或更换应用时需要填写 Access Token")
            key = previous["access_key"]
        if any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise ValueError("Access Token 格式不正确")
        app_changed = update.app_id != previous.get("app_id")
        # Replicated S_ voices are scoped to the Volcengine application that
        # created them. Never carry those per-character mappings into a new app.
        speakers = {} if app_changed else dict(previous.get("speakers", {}))
        if update.character_id:
            speakers[update.character_id] = update.speaker
        fallback_speaker = DEFAULT_SPEAKER if app_changed else previous.get("speaker", DEFAULT_SPEAKER)
        value = {"app_id": update.app_id, "access_key": key,
                 "speaker": fallback_speaker if update.character_id else update.speaker,
                 "speakers": speakers}
        ai_credentials.save_api_key(json.dumps(value, ensure_ascii=False), config_path())
        return public_config(value, update.character_id)


def session_payload(character, req, config: dict) -> dict:
    status = get_character_status(character)
    channel = req.channel if req.channel in ("voice_call", "video_call") else "voice_call"
    history = trim_complete_history_pairs([m.model_dump() for m in req.history])
    compiled = compile_companion_messages(
        character, "正在进行远程语音通话，请等待用户开口。", history,
        live_status=status, status_context=format_status_context(status, channel=channel),
        reply_speed="自然自适应", memory_context=req.memory_context,
        legacy_memory=req.memory, legacy_intimacy=req.intimacy,
        companion_context=req.companion_context.model_dump(mode="json") if req.companion_context else None,
        channel=channel,
    )
    prompt = compiled.messages[0]["content"]
    prompt += "\n【实时语音】只说自然口语台词，不朗读动作、括号旁白或内部规则。等待用户开口，不虚构共同现场。"
    # Conservative character budget for the provider's 12K token context, with
    # headroom for audio/replies. Never cut persona/confirmed relationship rules.
    if len(prompt) > 6000:
        raise ContextTooLargeError("Realtime persona exceeds the context budget")
    history = trim_complete_history_pairs(history, max_chars=6000 - len(prompt))
    # The provider strictly requires complete user/assistant pairs. Our shared
    # compiler also preserves standalone proactive greetings, so filter those.
    pairs = []
    pending = None
    for message in history:
        if message["role"] == "user":
            pending = message
        elif pending is not None:
            pairs.extend([pending, message])
            pending = None
    return {
        "asr": {"audio_info": {"format": "pcm", "sample_rate": 16000, "channel": 1},
                "extra": {"enable_custom_vad": True, "end_smooth_window_ms": 800}},
        "tts": {"speaker": public_config(config, character.id)["speaker"],
                "audio_config": {"format": "pcm_s16le", "sample_rate": 24000, "channel": 1}},
        "dialog": {"character_manifest": prompt,
                   "dialog_context": [{"role": m["role"], "text": m["content"]} for m in pairs],
                   "extra": {"model": "2.2.0.0", "input_mod": "keep_alive",
                             "enable_conversation_truncate": True}},
    }
