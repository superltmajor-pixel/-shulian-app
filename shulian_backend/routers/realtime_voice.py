"""Same-origin local WebSocket gateway. Credentials never enter browser events."""

import asyncio
import contextlib
import json
import time
import uuid

import aiohttp
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ai_credentials import CredentialError
from characters import ROSTER
from ..schemas.api import ChatRequest
from ..security import require_local_write, trusted_local_websocket
from ..services import realtime_voice as service
from ..services.realtime_protocol import decode, encode

router = APIRouter()
UPSTREAM_URL = "wss://openspeech.bytedance.com/api/v3/realtime/dialogue"


@router.get("/api/realtime-voice/config")
def get_config(request: Request, character_id: str = ""):
    require_local_write(request)
    try:
        return service.public_config(service.load_config(), character_id)
    except (CredentialError, ValueError):
        raise HTTPException(503, "实时语音配置读取失败") from None


@router.put("/api/realtime-voice/config")
def put_config(request: Request, config: service.VoiceConfig):
    require_local_write(request)
    if config.character_id and config.character_id not in ROSTER:
        raise HTTPException(404, "角色不存在")
    try:
        return service.save_config(config)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except CredentialError:
        raise HTTPException(503, "实时语音配置保存失败") from None


async def relay(ws: WebSocket, config: dict, payload: dict):
    session_id = str(uuid.uuid4())
    upstream = None
    started = False
    send_lock = asyncio.Lock()

    async def send(event, body, sid=session_id):
        async with send_lock:
            await asyncio.wait_for(upstream.send_bytes(encode(event, body, sid)), 5)

    async def receive_packet():
        message = await upstream.receive()
        if message.type != aiohttp.WSMsgType.BINARY:
            raise ConnectionError("Realtime connection closed")
        return decode(message.data)

    async def provider():
        nonlocal upstream, started
        headers = {"X-Api-App-ID": config["app_id"], "X-Api-Access-Key": config["access_key"],
                   "X-Api-Resource-Id": "volc.speech.dialog", "X-Api-App-Key": "PlgvMymc7f3tQnJ6",
                   "X-Api-Connect-Id": str(uuid.uuid4())}
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=10)
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.ws_connect(UPSTREAM_URL, headers=headers, heartbeat=20, max_msg_size=1_048_576) as connection:
                upstream = connection
                try:
                    await send(1, {}, "")
                    packet = await asyncio.wait_for(receive_packet(), 10)
                    if packet.event != 50:
                        raise ConnectionError("Realtime connection rejected")
                    await send(100, payload)
                    packet = await asyncio.wait_for(receive_packet(), 15)
                    if packet.event != 150:
                        raise ConnectionError("Realtime session rejected")
                    started = True
                    await ws.send_json({"type": "ready", "sample_rate": 24000})
                    while True:
                        packet = await receive_packet()  # Heartbeat detects transport loss; silence is valid.
                        if packet.session_id and packet.session_id != session_id:
                            continue
                        if packet.event in (51, 52, 152, 153, 599):
                            raise ConnectionError("Realtime session ended")
                        if packet.event == 352:
                            if not isinstance(packet.payload, bytes) or len(packet.payload) % 2:
                                raise ValueError("Invalid PCM audio")
                            await asyncio.wait_for(ws.send_bytes(packet.payload), 5)
                        elif packet.event in (350, 351, 359, 450, 451, 459, 550, 553, 559):
                            if not isinstance(packet.payload, dict):
                                raise ValueError("Invalid realtime event")
                            await asyncio.wait_for(ws.send_json({"type": "event", "event": packet.event, "data": packet.payload}), 5)
                finally:
                    if started and not connection.closed:
                        with contextlib.suppress(Exception):
                            await send(102, {})
                            async with asyncio.timeout(2):
                                while (await receive_packet()).event != 152:
                                    pass
                            await send(2, {}, "")

    async def browser():
        window, audio_bytes, controls = time.monotonic(), 0, 0
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            if time.monotonic() - window >= 1:
                window, audio_bytes, controls = time.monotonic(), 0, 0
            audio = message.get("bytes")
            if audio is not None:
                audio_bytes += len(audio)
                if not started or not audio or len(audio) > 6400 or len(audio) % 2 or audio_bytes > 96000:
                    raise ValueError("Invalid microphone frame")
                await send(200, audio)
                continue
            raw = message.get("text", "")
            controls += 1
            if len(raw) > 8192 or controls > 20:
                raise ValueError("Invalid realtime control")
            command = json.loads(raw)
            if command.get("type") == "end":
                return
            if not started:
                raise ValueError("Session is not ready")
            if command.get("type") == "text":
                content = str(command.get("text", "")).strip()
                if not content or len(content) > 4000:
                    raise ValueError("Invalid realtime text")
                await send(501, {"content": content})
            elif command.get("type") == "truncate":
                item_id = command.get("reply_id")
                end_ms = command.get("audio_end_ms")
                if not isinstance(item_id, str) or len(item_id) > 256 or not isinstance(end_ms, int) or not 0 <= end_ms <= 600000:
                    raise ValueError("Invalid playback position")
                await send(513, {"item_id": item_id, "audio_end_ms": end_ms})
            else:
                raise ValueError("Unknown realtime command")

    tasks = [asyncio.create_task(provider()), asyncio.create_task(browser())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED, timeout=3600)
        if not done:
            raise TimeoutError("Call duration limit")
        for task in done:
            task.result()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@router.websocket("/api/realtime-voice/{character_id}")
async def realtime_call(ws: WebSocket, character_id: str):
    if not trusted_local_websocket(ws) or character_id not in ROSTER:
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        config = await asyncio.to_thread(service.load_config)
        if not service.public_config(config)["configured"]:
            await ws.send_json({"type": "error", "message": "请先配置豆包实时语音服务"})
            return
        raw = await asyncio.wait_for(ws.receive_text(), 10)
        if len(raw.encode()) > 131072:
            raise ValueError("Context too large")
        data = json.loads(raw)
        if data.pop("type", None) != "start":
            raise ValueError("Expected start")
        req = ChatRequest.model_validate(data)
        if req.companion_context and req.companion_context.character_id != character_id:
            raise ValueError("Character mismatch")
        payload = await asyncio.to_thread(service.session_payload, ROSTER[character_id], req, config)
        await relay(ws, config, payload)
    except WebSocketDisconnect:
        pass
    except service.ContextTooLargeError:
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "error", "message": "角色上下文过长，请精简角色设定或记忆后重试"})
    except (ValueError, ValidationError):
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "error", "message": "实时语音数据或配置无效"})
    except Exception:
        # Never echo upstream exceptions: authentication headers may be present.
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "error", "message": "实时语音连接失败，请检查服务开通、凭据和网络"})
    finally:
        with contextlib.suppress(Exception):
            await ws.close()
