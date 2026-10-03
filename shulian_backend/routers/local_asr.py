"""Local-only websocket gateway for offline streaming speech recognition."""

from __future__ import annotations

import asyncio
import contextlib
import time

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ..security import require_local_write, trusted_local_websocket
from ..services import local_asr as service

router = APIRouter()
_active_session = asyncio.Lock()


@router.get("/api/local-asr/status")
def get_status(request: Request):
    require_local_write(request)
    return service.status()


@router.post("/api/local-asr/download")
async def download_model(request: Request):
    require_local_write(request)
    if not service.runtime_available():
        raise HTTPException(503, "当前客户端未包含本地识别组件，请更新客户端后重试")
    try:
        return await asyncio.to_thread(service.download_model)
    except service.LocalAsrError as exc:
        raise HTTPException(409, str(exc)) from None
    except Exception:
        raise HTTPException(502, "本地语音模型下载失败，请检查网络后重试") from None


@router.websocket("/api/local-asr/stream")
async def stream_asr(ws: WebSocket):
    if not trusted_local_websocket(ws):
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        if not service.runtime_available():
            await ws.send_json({"type": "error", "message": "当前客户端未包含本地识别组件，请更新客户端后重试"})
            return
        if not service.model_installed():
            await ws.send_json({"type": "error", "message": "请先下载本地中文语音模型"})
            return

        async with _active_session:
            recognizer = await asyncio.to_thread(service.get_recognizer)
            stream = recognizer.create_stream()
            await ws.send_json({"type": "ready", "sample_rate": 16000})
            last_partial = ""
            window_start = time.monotonic()
            frame_count = 0
            deadline = window_start + 3600

            while time.monotonic() < deadline:
                message = await asyncio.wait_for(ws.receive(), timeout=max(1, deadline - time.monotonic()))
                if message["type"] == "websocket.disconnect":
                    break
                frame = message.get("bytes")
                if frame is None or len(frame) != 640:
                    raise ValueError("Invalid PCM frame")
                now = time.monotonic()
                if now - window_start >= 1:
                    window_start, frame_count = now, 0
                frame_count += 1
                if frame_count > 60:
                    raise ValueError("Audio frame rate exceeded")

                partial, final = await asyncio.to_thread(service.decode_frame, recognizer, stream, frame)
                if final:
                    await ws.send_json({"type": "final", "text": final})
                    last_partial = ""
                elif partial and partial != last_partial:
                    await ws.send_json({"type": "partial", "text": partial})
                    last_partial = partial
    except WebSocketDisconnect:
        pass
    except TimeoutError:
        pass
    except ValueError:
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "error", "message": "本地语音数据无效，请重新连接"})
    except service.LocalAsrError as exc:
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "error", "message": str(exc)})
    except Exception:
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "error", "message": "本地语音识别处理失败，请重试"})
    finally:
        if ws.client_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await ws.close()
