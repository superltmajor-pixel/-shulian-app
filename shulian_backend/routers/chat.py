"""聊天、流式回复、长期记忆摘要与问候 API。"""

import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

import chat as chat_backend
from characters import ROSTER
from diagnostics import log_event, record_metric
from status_engine import get_character_status, get_schedule_status
from shulian_backend.services.scene_status_service import recover_recent_rest_scene
from shulian_backend.services.companion_context_service import (
    complete_conversation_messages,
    consolidate_companion_context,
)
from shulian_backend.services.model_adapter_service import upstream_error_context

from ..schemas import (
    ChatRequest,
    ChatResponse,
    ConsolidateContextRequest,
    ConsolidateContextResponse,
    SummarizeRequest,
    SummarizeResponse,
)


router = APIRouter()


@router.post("/api/chat/{character_id}")
def chat_with_character(character_id: str, req: ChatRequest):
    character = ROSTER.get(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    if req.companion_context is not None and req.companion_context.character_id != character_id:
        raise HTTPException(status_code=422, detail="角色上下文与聊天角色不匹配")

    history = [
        item.model_dump(mode="json", exclude_none=True)
        for item in req.history
    ]
    schedule_status = get_schedule_status(character)
    # Tracking is a post-reply transition check. It must never turn a normal
    # chat entry or small-talk turn into a shared scene by itself.
    recover_recent_rest_scene(character_id)
    live_status = get_character_status(character)

    if req.stream:
        cancellation = chat_backend.CancellationToken()

        def event_stream():
            started_at = time.perf_counter()
            first_chunk_recorded = False
            reply_parts: list[str] = []
            try:
                for chunk in chat_backend.stream_reply(
                    character_id,
                    req.message,
                    history,
                    req.reply_speed,
                    req.memory,
                    req.intimacy,
                    live_status,
                    cancellation,
                    proactive=req.proactive,
                    memory_context=req.memory_context,
                    companion_context=(
                        req.companion_context.model_dump(mode="json")
                        if req.companion_context is not None
                        else None
                    ),
                    channel=req.channel,
                    image_url=req.image_url,
                    image_caption=req.image_caption,
                ):
                    if chunk and not first_chunk_recorded:
                        record_metric(
                            "ai.first_token",
                            (time.perf_counter() - started_at) * 1000,
                            character_id=character_id,
                        )
                        first_chunk_recorded = True
                    if chunk:
                        reply_parts.append(chunk)
                    lines = (
                        chunk.replace("\r\n", "\n")
                        .replace("\r", "\n")
                        .split("\n")
                    )
                    yield "".join(f"data: {line}\n" for line in lines) + "\n"
                if req.track_scene and reply_parts:
                    resolved_status = chat_backend.reconcile_scene_status(
                        character,
                        req.message,
                        "".join(reply_parts),
                        history,
                        schedule_status,
                        channel=req.channel,
                    )
                    payload = json.dumps(
                        resolved_status,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    yield f"event: status\ndata: {payload}\n\n"
                yield "data: [DONE]\n\n"
                record_metric(
                    "ai.stream_total",
                    (time.perf_counter() - started_at) * 1000,
                    ok=first_chunk_recorded,
                    character_id=character_id,
                )
            except chat_backend.ChatConfigurationError:
                record_metric(
                    "ai.stream_total",
                    (time.perf_counter() - started_at) * 1000,
                    ok=False,
                    character_id=character_id,
                )
                log_event(
                    "warning",
                    "ai_not_configured",
                    "AI service is not configured",
                    character_id=character_id,
                )
                yield "event: error\ndata: AI 服务未配置\n\n"
            except chat_backend.ChatConsistencyError:
                record_metric(
                    "ai.stream_total",
                    (time.perf_counter() - started_at) * 1000,
                    ok=False,
                    character_id=character_id,
                )
                log_event(
                    "warning",
                    "ai_reply_rejected",
                    "AI reply was withheld after consistency validation",
                    character_id=character_id,
                )
                yield "event: error\ndata: 这条回复生成异常，已停止发送。请再试一次。\n\n"
            except chat_backend.ChatServiceError:
                record_metric(
                    "ai.stream_total",
                    (time.perf_counter() - started_at) * 1000,
                    ok=False,
                    character_id=character_id,
                )
                log_event(
                    "error",
                    "ai_upstream_unavailable",
                    "AI streaming request failed",
                    character_id=character_id,
                )
                yield "event: error\ndata: AI 服务暂时不可用\n\n"
            finally:
                cancellation.cancel()

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    started_at = time.perf_counter()
    try:
        reply = chat_backend.get_reply(
            character_id,
            req.message,
            history,
            req.reply_speed,
            req.memory,
            req.intimacy,
            live_status,
            proactive=req.proactive,
            memory_context=req.memory_context,
            companion_context=(
                req.companion_context.model_dump(mode="json")
                if req.companion_context is not None
                else None
            ),
            channel=req.channel,
            image_url=req.image_url,
            image_caption=req.image_caption,
        )
    except chat_backend.ChatConfigurationError as exc:
        record_metric(
            "ai.reply",
            (time.perf_counter() - started_at) * 1000,
            ok=False,
            character_id=character_id,
        )
        raise HTTPException(status_code=503, detail="AI 服务未配置") from exc
    except chat_backend.ChatConsistencyError as exc:
        record_metric(
            "ai.reply",
            (time.perf_counter() - started_at) * 1000,
            ok=False,
            character_id=character_id,
        )
        log_event(
            "warning",
            "ai_reply_rejected",
            "AI reply was withheld after consistency validation",
            character_id=character_id,
        )
        raise HTTPException(
            status_code=409,
            detail="这条回复生成异常，已停止发送。请再试一次。",
        ) from exc
    except chat_backend.ChatServiceError as exc:
        record_metric(
            "ai.reply",
            (time.perf_counter() - started_at) * 1000,
            ok=False,
            character_id=character_id,
        )
        log_event(
            "error",
            "ai_upstream_unavailable",
            "AI request failed after bounded retries",
            character_id=character_id,
            provider=chat_backend.get_active_provider_profile().id,
            model=chat_backend.get_active_model(),
            **upstream_error_context(exc),
        )
        raise HTTPException(status_code=502, detail="AI 服务暂时不可用") from exc
    record_metric(
        "ai.reply",
        (time.perf_counter() - started_at) * 1000,
        character_id=character_id,
    )
    resolved_status = (
        chat_backend.reconcile_scene_status(
            character,
            req.message,
            reply,
            history,
            schedule_status,
            channel=req.channel,
        )
        if req.track_scene
        else live_status
    )
    return ChatResponse(
        reply=reply,
        character_id=character_id,
        status=resolved_status,
    )


@router.post("/api/chat/{character_id}/summarize")
def summarize(character_id: str, req: SummarizeRequest):
    if character_id not in ROSTER:
        raise HTTPException(status_code=404, detail="角色不存在")
    messages = [item.model_dump(mode="json", exclude_none=True) for item in req.messages]
    memory_context = chat_backend.summarize_memory_context(
        character_id,
        req.old_memory_context,
        req.old_memory,
        messages,
    )
    return SummarizeResponse(
        memory=memory_context,
        memory_context=memory_context,
        character_id=character_id,
    )


@router.post(
    "/api/context/{character_id}/consolidate",
    response_model=ConsolidateContextResponse,
)
def consolidate_context(character_id: str, req: ConsolidateContextRequest):
    if character_id not in ROSTER:
        raise HTTPException(status_code=404, detail="角色不存在")
    if req.companion_context is not None and req.companion_context.character_id != character_id:
        raise HTTPException(status_code=422, detail="角色上下文与整理角色不匹配")
    consolidated_memory_context = req.old_memory_context
    if req.reason != "migration" and req.current_messages:
        candidates = complete_conversation_messages(req.current_messages[-80:])
        if candidates:
            try:
                consolidated_memory_context = chat_backend.summarize_memory_context(
                    character_id,
                    req.old_memory_context,
                    req.old_memory,
                    candidates,
                )
            except (chat_backend.ChatConfigurationError, chat_backend.ChatServiceError):
                # Memory refinement is an enhancement; deterministic relationship
                # and experience consolidation must still complete offline.
                consolidated_memory_context = req.old_memory_context
    context, result = consolidate_companion_context(
        character_id,
        (
            req.companion_context.model_dump(mode="json")
            if req.companion_context is not None
            else None
        ),
        old_memory=req.old_memory,
        old_memory_context=consolidated_memory_context,
        old_relationship=req.old_relationship,
        old_intimacy=req.old_intimacy,
        current_messages=req.current_messages,
        archived_sessions=req.archived_sessions,
        reason=req.reason,
    )
    return ConsolidateContextResponse(
        companion_context=context,
        memory_context=consolidated_memory_context,
        character_id=character_id,
        previous_level=result["previous_level"],
        stage_changed=result["stage_changed"],
        processed_segments=result["processed_segments"],
    )


@router.get("/api/chat/{character_id}/greet")
def greet(character_id: str):
    if character_id not in ROSTER:
        raise HTTPException(status_code=404, detail="角色不存在")
    raise HTTPException(
        status_code=410,
        detail="固定角色招呼接口已停用；角色发言必须通过聊天生成与一致性校验。",
    )
