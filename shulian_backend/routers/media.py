"""本地语音文件与 TTS API。"""

import asyncio
import os
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from diagnostics import record_metric

from ..domain import (
    MediaContext,
    TTSConfigurationError,
    TTSServiceError,
)
from ..schemas import TTSRequest
from ..services import tts_service


def _write_voice_file(voice_dir: str, filename: str, payload: bytes) -> None:
    """建目录并落盘。放在工作线程里执行，避免阻塞事件循环。"""

    os.makedirs(voice_dir, exist_ok=True)
    with open(os.path.join(voice_dir, filename), "xb") as voice_file:
        voice_file.write(payload)


def create_media_router(context: MediaContext) -> APIRouter:
    router = APIRouter()

    @router.post("/api/voice")
    async def save_voice(request: Request):
        content_type = (
            request.headers.get("content-type", "")
            .split(";", 1)[0]
            .strip()
            .lower()
        )
        extension = context.content_types.get(content_type)
        if not extension:
            raise HTTPException(status_code=415, detail="不支持的语音格式")

        payload = await request.body()
        if not payload:
            raise HTTPException(status_code=422, detail="语音内容不能为空")
        if len(payload) > context.max_voice_bytes:
            raise HTTPException(status_code=413, detail="语音内容过大")

        filename = f"{uuid.uuid4().hex}.{extension}"
        await asyncio.to_thread(
            _write_voice_file,
            context.voice_dir,
            filename,
            payload,
        )

        return {
            "url": f"/media/{filename}",
            "content_type": content_type,
            "bytes": len(payload),
        }

    @router.post("/api/tts/{character_id}")
    async def tts(character_id: str, req: TTSRequest):
        if character_id not in context.roster:
            raise HTTPException(status_code=404, detail="角色不存在")
        started_at = time.perf_counter()
        try:
            audio, media_type, provider = await tts_service.synthesize_tts(
                character_id,
                req.text,
            )
        except TTSConfigurationError as exc:
            record_metric(
                "tts.synthesis",
                (time.perf_counter() - started_at) * 1000,
                ok=False,
                character_id=character_id,
            )
            raise HTTPException(status_code=503, detail="语音服务配置无效") from exc
        except TTSServiceError as exc:
            record_metric(
                "tts.synthesis",
                (time.perf_counter() - started_at) * 1000,
                ok=False,
                character_id=character_id,
            )
            raise HTTPException(
                status_code=502,
                detail="语音合成服务暂时不可用",
            ) from exc
        record_metric(
            "tts.synthesis",
            (time.perf_counter() - started_at) * 1000,
            character_id=character_id,
            provider=provider,
        )
        return Response(
            content=audio,
            media_type=media_type,
            headers={
                "Cache-Control": "no-store",
                "X-TTS-Provider": provider,
            },
        )

    return router
