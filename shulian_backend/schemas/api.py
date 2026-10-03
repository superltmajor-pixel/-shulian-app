"""数恋 HTTP API 的 Pydantic 模型。"""

import base64
import binascii
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


_IMAGE_DATA_URL_RE = re.compile(
    r"^data:image/(?P<format>jpeg|png|gif|webp);base64,(?P<payload>[A-Za-z0-9+/]*={0,2})$",
    re.IGNORECASE,
)
_MAX_IMAGE_BYTES = 6 * 1024 * 1024


def _valid_image_signature(image_format: str, payload: bytes) -> bool:
    image_format = image_format.lower()
    if image_format == "jpeg":
        return payload.startswith(b"\xff\xd8\xff")
    if image_format == "png":
        return payload.startswith(b"\x89PNG\r\n\x1a\n")
    if image_format == "gif":
        return payload.startswith((b"GIF87a", b"GIF89a"))
    return (
        image_format == "webp"
        and len(payload) >= 12
        and payload.startswith(b"RIFF")
        and payload[8:12] == b"WEBP"
    )


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4_000)
    # Chat history is rendered with its original time so the model can keep
    # separate days and assistant-initiated messages apart.  Older clients do
    # not send these fields, so both remain optional for wire compatibility.
    ts: int | float | None = Field(default=None, ge=0)
    origin: str | None = Field(default=None, max_length=40)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("消息内容不能为空")
        return value


RelationshipStage = Literal[
    "初识",
    "认识",
    "熟悉",
    "信赖",
    "亲近",
    "心意相通",
    "关系确认",
    "深度伴侣",
    "灵魂伴侣",
    "终身伴侣",
]
ExperienceCategory = Literal[
    "embrace",
    "kiss",
    "shared_sleep",
    "general_intimacy",
    "oral_intimacy",
    "anal_intimacy",
    "manual_intimacy",
    "other_private",
]


class RelationshipDimensions(BaseModel):
    """四维关系状态；每一维使用 0—4 的离散分级。"""

    model_config = ConfigDict(extra="forbid")

    familiarity: int = Field(default=0, ge=0, le=4)
    trust: int = Field(default=0, ge=0, le=4)
    affection: int = Field(default=0, ge=0, le=4)
    commitment: int = Field(default=0, ge=0, le=4)


class RelationshipState(BaseModel):
    """由双方确认事件驱动的关系状态，而不是消息计数器。"""

    model_config = ConfigDict(extra="forbid")

    level: int = Field(default=1, ge=1, le=10)
    stage: RelationshipStage = "初识"
    title: str = Field(default="初识", min_length=1, max_length=40)
    dimensions: RelationshipDimensions = Field(default_factory=RelationshipDimensions)
    # Direction is intentional: forms_of_address is character -> user, while
    # user_forms_of_address is user -> character.  Keeping both prevents an
    # old, ambiguous "称呼" field from teaching a character its own nickname
    # as the user's name.
    forms_of_address: list[str] = Field(default_factory=list, max_length=12)
    user_forms_of_address: list[str] = Field(default_factory=list, max_length=12)
    boundaries: list[str] = Field(default_factory=list, max_length=12)
    commitments: list[str] = Field(default_factory=list, max_length=16)
    confirmed_events: list[str] = Field(default_factory=list, max_length=32)
    invalidated_facts: list[str] = Field(default_factory=list, max_length=16)
    updated_at: str = Field(default="", max_length=64)


class ExperienceMilestone(BaseModel):
    """只保存非露骨类别与频次，不保存私密对话原文。"""

    model_config = ConfigDict(extra="forbid")

    category: ExperienceCategory
    first_at: str = Field(default="", max_length=64)
    last_at: str = Field(default="", max_length=64)
    frequency: Literal["once", "several", "many"] = "once"
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)


class CompanionMigrationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_version: str = Field(default="v21", max_length=32)
    completed: bool = False
    processed_segments: list[str] = Field(default_factory=list, max_length=4_096)
    migrated_at: str = Field(default="", max_length=64)


class CompanionContextV1(BaseModel):
    """所有聊天入口共享的角色上下文。"""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    character_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    relationship: RelationshipState
    experience_milestones: list[ExperienceMilestone] = Field(
        default_factory=list,
        max_length=8,
    )
    stable_facts: list[str] = Field(default_factory=list, max_length=24)
    recent_events: list[str] = Field(default_factory=list, max_length=16)
    migration: CompanionMigrationState = Field(default_factory=CompanionMigrationState)
    updated_at: str = Field(default="", max_length=64)


class AIConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr = Field(repr=False)
    remember: bool = True


class AIModelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The pure build can target any configured OpenAI-compatible model.
    model: str = Field(min_length=1, max_length=200)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4_000)
    image_url: str | None = Field(default=None, max_length=8_388_608)
    image_caption: str = Field(default="", max_length=1_000)
    history: list[Message] = Field(default_factory=list, max_length=40)
    # 旧三档仅保留请求兼容；上下文编译器统一采用自然自适应节奏。
    reply_speed: Literal["自然自适应", "甜蜜即时", "日常自然", "慢热含蓄"] = "自然自适应"
    stream: bool = False
    track_scene: bool = False
    proactive: bool = False
    channel: Literal[
        "text",
        "voice_message",
        "image",
        "voice_call",
        "video_call",
        "proactive",
        "home_greeting",
        "new_chat",
        "gift",
    ] = "text"
    memory: str = Field(default="", max_length=8_000)
    memory_context: str = Field(default="", max_length=24_000)
    intimacy: float | None = Field(default=None, ge=1, le=10)
    companion_context: CompanionContextV1 | None = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("消息内容不能为空")
        return value

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        match = _IMAGE_DATA_URL_RE.fullmatch(value.strip())
        if match is None:
            raise ValueError("图片必须是 JPEG、PNG、GIF 或 WebP 的 Base64 数据")
        try:
            payload = base64.b64decode(match.group("payload"), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("图片 Base64 数据无效") from exc
        if not payload or len(payload) > _MAX_IMAGE_BYTES:
            raise ValueError("图片大小必须在 6 MiB 以内")
        if not _valid_image_signature(match.group("format"), payload):
            raise ValueError("图片内容与声明格式不匹配")
        return value.strip()

    @field_validator("image_caption")
    @classmethod
    def validate_image_caption(cls, value: str) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def validate_image_caption_pair(self):
        if self.image_caption and not self.image_url:
            raise ValueError("图片说明必须与图片一起发送")
        if self.image_url:
            # Older clients did not always mark a multimedia request with the
            # image channel.  Normalize it here so personality routing and
            # output rails cannot be bypassed by stale request metadata.
            self.channel = "image"
        return self


class ChatResponse(BaseModel):
    reply: str
    character_id: str
    status: dict | None = None


class SummarizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    old_memory: str = Field(default="", max_length=8_000)
    old_memory_context: str = Field(default="", max_length=24_000)
    messages: list[Message] = Field(default_factory=list, max_length=80)


class SummarizeResponse(BaseModel):
    memory: str
    memory_context: str
    character_id: str


class ConsolidateContextRequest(BaseModel):
    """把旧状态和一段完整对话整理进 CompanionContextV1。"""

    model_config = ConfigDict(extra="forbid")

    companion_context: CompanionContextV1 | None = None
    old_memory: str = Field(default="", max_length=200_000)
    old_memory_context: str = Field(default="", max_length=24_000)
    old_relationship: dict = Field(default_factory=dict)
    old_intimacy: float | None = Field(default=None, ge=1, le=10)
    current_messages: list[dict] = Field(default_factory=list, max_length=100_000)
    archived_sessions: list[dict] = Field(default_factory=list, max_length=10_000)
    reason: Literal["migration", "periodic", "new_chat", "call_end", "manual"] = "periodic"


class ConsolidateContextResponse(BaseModel):
    companion_context: CompanionContextV1
    memory_context: str = Field(default="", max_length=24_000)
    character_id: str
    previous_level: int = Field(ge=1, le=10)
    stage_changed: bool = False
    processed_segments: int = Field(default=0, ge=0)


class TTSRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=600)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("朗读内容不能为空")
        return value


class RoleArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frontend_profile: dict = Field(default_factory=dict)
    relationship: dict = Field(default_factory=dict)
    memory: str = Field(default="", max_length=200_000)
    memory_context: str = Field(default="", max_length=24_000)
    intimacy: float | None = Field(default=None, ge=1, le=10)
    companion_context: CompanionContextV1 | None = None
    started_at: int | float | None = None
    current_messages: list[dict] = Field(default_factory=list, max_length=100_000)
    archived_sessions: list[dict] = Field(default_factory=list, max_length=10_000)


class DiagnosticEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal[
        "startup.frontend_ready",
        "ui.diagnostics_open",
    ]
    duration_ms: float = Field(ge=0, le=120_000)
    ok: bool = True


class StateMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: dict[str, str] = Field(default_factory=dict)
    deleted_keys: list[str] = Field(default_factory=list)


class StateReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: dict[str, str] = Field(default_factory=dict)
