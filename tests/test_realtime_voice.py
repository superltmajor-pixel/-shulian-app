"""Offline realtime protocol, configuration and WebSocket lifecycle coverage."""

import asyncio
import gzip
import json
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import aiohttp
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from shulian_backend.routers import local_asr as local_asr_route
from shulian_backend.routers import realtime_voice as route
from shulian_backend.services import local_asr
from shulian_backend.services import realtime_voice as service
from shulian_backend.services.realtime_protocol import decode, encode
from shulian_backend.schemas.api import ChatRequest


def server_frame(event, payload=None, sid="test-session", compressed=False):
    audio = isinstance(payload, bytes)
    data = payload if audio else json.dumps(payload or {}).encode()
    if compressed:
        data = gzip.compress(data)
    identifier = sid.encode()
    return (bytes([0x11, 0xB4 if audio else 0x94, (0 if audio else 0x10) | int(compressed), 0])
            + struct.pack(">II", event, len(identifier)) + identifier
            + struct.pack(">I", len(data)) + data)


class ProtocolTests(unittest.TestCase):
    def test_official_start_connection_fixture(self):
        self.assertEqual(list(encode(1, {})), [17, 20, 16, 0, 0, 0, 0, 1, 0, 0, 0, 2, 123, 125])

    def test_pcm_request_is_raw_and_has_session_id(self):
        frame = encode(200, b"\x00\x80\xff\x7f", "s")
        self.assertEqual(frame[:4], b"\x11\x24\x00\x00")
        self.assertEqual(frame[4:], struct.pack(">II", 200, 1) + b"s" + struct.pack(">I", 4) + b"\x00\x80\xff\x7f")

    def test_decode_connection_and_compressed_json_and_audio(self):
        self.assertEqual(decode(server_frame(50, sid="connection")).event, 50)
        self.assertEqual(decode(server_frame(451, {"results": [{"text": "你好"}]}, compressed=True)).payload["results"][0]["text"], "你好")
        self.assertEqual(decode(server_frame(352, b"\xff\x7f")).payload, b"\xff\x7f")

    def test_rejects_truncated_and_oversize_compressed_frames(self):
        frame = server_frame(451, {"content": "hello"})
        for short in (frame[:3], frame[:8], frame[:-1], frame + b"x"):
            with self.assertRaises(ValueError):
                decode(short)
        with self.assertRaises(ValueError):
            decode(server_frame(352, b"x" * 1_048_577, compressed=True))


class LocalAsrFrameTests(unittest.TestCase):
    def test_first_pcm_frame_accepts_string_and_text_results(self):
        for result in (" 你好 ", SimpleNamespace(text=" 你好 ")):
            with self.subTest(result_type=type(result).__name__):
                stream = SimpleNamespace(accept_waveform=Mock())
                recognizer = SimpleNamespace(
                    is_ready=Mock(side_effect=[True, False]),
                    decode_stream=Mock(),
                    get_result=Mock(return_value=result),
                    is_endpoint=Mock(return_value=False),
                )
                self.assertEqual(local_asr.decode_frame(recognizer, stream, bytes(640)), ("你好", None))
                self.assertEqual(stream.accept_waveform.call_args.args[0], 16000)
                self.assertEqual(len(stream.accept_waveform.call_args.args[1]), 320)
                recognizer.decode_stream.assert_called_once_with(stream)

    def test_socket_accepts_only_same_origin_local_clients(self):
        app = FastAPI()
        app.include_router(local_asr_route.router)
        client = TestClient(app)
        for headers in ({}, {"origin": "https://evil.example"}):
            with self.subTest(headers=headers), self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect("/api/local-asr/stream", headers=headers):
                    pass
        with patch.object(local_asr_route.service, "runtime_available", return_value=False):
            with client.websocket_connect(
                "/api/local-asr/stream", headers={"origin": "http://testserver"}
            ) as ws:
                self.assertEqual(ws.receive_json()["type"], "error")


class FrontendAudioTests(unittest.TestCase):
    def test_microphone_playback_interrupt_and_cleanup(self):
        result = subprocess.run(["node", "--test", "tests/realtime-voice.test.mjs"],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_compatible_voice_turn_taking_and_cleanup(self):
        result = subprocess.run(["node", "--test", "tests/compatible-voice.test.mjs"],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_calls_default_to_compatible_mode_and_keep_realtime_selectable(self):
        root = Path(__file__).resolve().parents[1]
        compatible = (root / "web" / "compatible-voice.jsx").read_text(encoding="utf-8")
        chat = (root / "web" / "chat.jsx").read_text(encoding="utf-8")
        app = (root / "web" / "app.jsx").read_text(encoding="utf-8")
        build = (root / "scripts" / "web-build-shared.mjs").read_text(encoding="utf-8")
        self.assertIn("React.useState('compatible')", compatible)
        self.assertIn("mode === 'realtime' ? realtimeEngine : compatibleEngine", compatible)
        self.assertIn("useVoiceCallEngine(c, onContext, onSend)", chat)
        self.assertIn("onSend={(text, callTurns) => callSend", app)
        self.assertIn('"web/compatible-voice.jsx"', build)


class ConfigurationTests(unittest.TestCase):
    def test_encrypted_roundtrip_preserves_other_roles_and_never_returns_token(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(service, "config_path", return_value=Path(directory) / "voice.bin"):
            result = service.save_config(service.VoiceConfig(app_id="123", access_key="test-secret-token", character_id="sample_a", speaker="S_sample_a"))
            self.assertTrue(result["configured"])
            self.assertNotIn("access_key", result)
            self.assertNotIn(b"test-secret-token", service.config_path().read_bytes())
            service.save_config(service.VoiceConfig(app_id="123", character_id="sample_c", speaker="S_sample_c"))
            self.assertEqual(service.public_config(service.load_config(), "sample_a")["speaker"], "S_sample_a")
            self.assertEqual(service.load_config()["access_key"], "test-secret-token")
            with self.assertRaises(ValueError):
                service.save_config(service.VoiceConfig(app_id="456"))

            changed = service.save_config(service.VoiceConfig(
                app_id="456", access_key="replacement-token",
                character_id="sample_a", speaker="S_new_sample_a",
            ))
            stored = service.load_config()
            self.assertEqual(changed["speaker"], "S_new_sample_a")
            self.assertEqual(service.public_config(stored, "sample_c")["speaker"], service.DEFAULT_SPEAKER)
            self.assertNotIn("sample_c", stored["speakers"])

    def test_start_payload_preserves_context_and_only_complete_pairs(self):
        character = SimpleNamespace(id="sample_a")
        req = ChatRequest(message="call", memory_context="记忆", history=[
            {"role": "assistant", "content": "主动问候", "origin": "proactive"},
            {"role": "user", "content": "早安"}, {"role": "assistant", "content": "早上好"},
            {"role": "user", "content": "未答"},
        ])
        with patch.object(service, "get_character_status", return_value={}), \
             patch.object(service, "format_status_context", return_value="状态"), \
             patch.object(service, "compile_companion_messages", return_value=SimpleNamespace(messages=[{"content": "角色人格和关系"}])) as compile_context:
            payload = service.session_payload(character, req, {"speakers": {"sample_a": "S_sample_a"}})
        self.assertEqual([m["role"] for m in payload["dialog"]["dialog_context"]], ["user", "assistant"])
        self.assertIn("角色人格和关系", payload["dialog"]["character_manifest"])
        self.assertEqual(compile_context.call_args.kwargs["memory_context"], "记忆")
        self.assertEqual(payload["dialog"]["extra"]["model"], "2.2.0.0")
        self.assertEqual(payload["dialog"]["extra"]["input_mod"], "keep_alive")
        self.assertEqual(payload["tts"]["speaker"], "S_sample_a")

    def test_context_budget_keeps_identity_and_trims_complete_history(self):
        character = SimpleNamespace(id="sample_a")
        req = ChatRequest(message="call", history=[
            {"role": "user", "content": "问" * 4000},
            {"role": "assistant", "content": "答" * 4000},
        ])
        with patch.object(service, "get_character_status", return_value={}), \
             patch.object(service, "format_status_context", return_value=""), \
             patch.object(service, "compile_companion_messages", return_value=SimpleNamespace(messages=[{"content": "人格" * 1500}])) as compiler:
            payload = service.session_payload(character, req, {})
            dialog = payload["dialog"]
            self.assertLessEqual(len(dialog["character_manifest"]) + sum(len(item["text"]) for item in dialog["dialog_context"]), 6000)
            self.assertEqual([item["role"] for item in dialog["dialog_context"]], ["user", "assistant"])
            compiler.return_value = SimpleNamespace(messages=[{"content": "人格" * 4000}])
            with self.assertRaises(service.ContextTooLargeError):
                service.session_payload(character, req, {})


class FakeUpstream:
    def __init__(self, fail_start=False):
        self.queue = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.fail_start = fail_start
        self.sid = ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def send_bytes(self, frame):
        event = struct.unpack_from(">I", frame, 4)[0]
        offset = 8
        if event >= 100:
            length = struct.unpack_from(">I", frame, offset)[0]
            self.sid = frame[offset + 4:offset + 4 + length].decode()
            offset += 4 + length
        body = frame[offset + 4:]
        self.sent.append((event, body))
        if event == 1:
            await self.queue.put(server_frame(50, sid="connect"))
        elif event == 100:
            await self.queue.put(server_frame(153 if self.fail_start else 150, sid=self.sid))
        elif event == 200:
            for item in [server_frame(450, {"question_id": "q1"}, self.sid),
                         server_frame(350, {"text": "你好", "reply_id": "r1"}, self.sid),
                         server_frame(352, b"\x01\x00" * 320, self.sid),
                         server_frame(359, {"reply_id": "r1"}, self.sid)]:
                await self.queue.put(item)
        elif event == 501:
            await self.queue.put(server_frame(553, {"question_id": "text-q"}, self.sid))
        elif event == 102:
            await self.queue.put(server_frame(152, sid=self.sid))

    async def receive(self):
        return SimpleNamespace(type=aiohttp.WSMsgType.BINARY, data=await self.queue.get())


class FakeClient:
    def __init__(self, upstream):
        self.upstream = upstream
        self.headers = None
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    def ws_connect(self, url, **kwargs):
        self.headers = kwargs["headers"]
        return self.upstream


class GatewayTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(route.router)
        self.client = TestClient(app)
        self.config = {"app_id": "123", "access_key": "secret-token"}

    def test_rejects_cross_origin_and_missing_origin(self):
        for headers in ({}, {"origin": "https://evil.example"}, {"origin": "http://testserver:9999"}):
            with self.assertRaises(WebSocketDisconnect), self.client.websocket_connect("/api/realtime-voice/sample_a", headers=headers):
                pass

    def test_unconfigured_does_not_connect_upstream(self):
        with patch.object(service, "load_config", return_value={}), patch.object(route.aiohttp, "ClientSession") as external:
            with self.client.websocket_connect("/api/realtime-voice/sample_a", headers={"origin": "http://testserver"}) as ws:
                self.assertEqual(ws.receive_json()["type"], "error")
            external.assert_not_called()

    def test_handshake_audio_interrupt_events_text_and_graceful_close(self):
        upstream = FakeUpstream()
        client = FakeClient(upstream)
        with patch.object(service, "load_config", return_value=self.config), \
             patch.object(service, "session_payload", return_value={"dialog": {}}), \
             patch.object(route.aiohttp, "ClientSession", return_value=client):
            with self.client.websocket_connect("/api/realtime-voice/sample_a", headers={"origin": "http://testserver"}) as ws:
                ws.send_json({"type": "start", "message": "call"})
                ready = ws.receive_json()
                self.assertEqual(ready["type"], "ready")
                self.assertNotIn("secret-token", json.dumps(ready))
                ws.send_bytes(b"\x00\x00" * 320)
                self.assertEqual(ws.receive_json()["event"], 450)
                self.assertEqual(ws.receive_json()["event"], 350)
                self.assertEqual(ws.receive_bytes(), b"\x01\x00" * 320)
                self.assertEqual(ws.receive_json()["event"], 359)
                ws.send_json({"type": "text", "text": "hello"})
                self.assertEqual(ws.receive_json()["event"], 553)
                ws.send_json({"type": "truncate", "reply_id": "r1", "audio_end_ms": 12})
                ws.send_json({"type": "end"})
                with self.assertRaises(WebSocketDisconnect):
                    ws.receive_json()
        self.assertTrue(upstream.closed)
        self.assertEqual([event for event, _ in upstream.sent], [1, 100, 200, 501, 513, 102, 2])
        self.assertEqual(client.headers["X-Api-Access-Key"], "secret-token")

    def test_failure_is_sanitized_and_stops_upstream(self):
        upstream = FakeUpstream(fail_start=True)
        with patch.object(service, "load_config", return_value=self.config), \
             patch.object(service, "session_payload", return_value={}), \
             patch.object(route.aiohttp, "ClientSession", return_value=FakeClient(upstream)):
            with self.client.websocket_connect("/api/realtime-voice/sample_a", headers={"origin": "http://testserver"}) as ws:
                ws.send_json({"type": "start", "message": "call"})
                result = ws.receive_json()
                self.assertEqual(result["type"], "error")
                self.assertNotIn("secret-token", str(result))
        self.assertTrue(upstream.closed)

    def test_invalid_audio_closes_session(self):
        upstream = FakeUpstream()
        with patch.object(service, "load_config", return_value=self.config), \
             patch.object(service, "session_payload", return_value={}), \
             patch.object(route.aiohttp, "ClientSession", return_value=FakeClient(upstream)):
            with self.client.websocket_connect("/api/realtime-voice/sample_a", headers={"origin": "http://testserver"}) as ws:
                ws.send_json({"type": "start", "message": "call"})
                ws.receive_json()
                ws.send_bytes(b"odd")
                self.assertEqual(ws.receive_json()["type"], "error")
        self.assertTrue(upstream.closed)
        self.assertNotIn(200, [event for event, _ in upstream.sent])

    def test_browser_disconnect_releases_upstream_without_end_command(self):
        upstream = FakeUpstream()
        with patch.object(service, "load_config", return_value=self.config), \
             patch.object(service, "session_payload", return_value={}), \
             patch.object(route.aiohttp, "ClientSession", return_value=FakeClient(upstream)):
            with self.client.websocket_connect("/api/realtime-voice/sample_a", headers={"origin": "http://testserver"}) as ws:
                ws.send_json({"type": "start", "message": "call"})
                self.assertEqual(ws.receive_json()["type"], "ready")
                ws.close()
        self.assertTrue(upstream.closed)


from tests.role_fixtures import role_fixture_hooks
setUpModule, tearDownModule = role_fixture_hooks()


if __name__ == "__main__":
    unittest.main()
