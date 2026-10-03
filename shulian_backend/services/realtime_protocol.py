"""Volcengine realtime binary framing (v1, event flag), independent of transport."""

import gzip
import io
import json
import struct
from dataclasses import dataclass

MAX_FRAME = 1_048_576


@dataclass(frozen=True)
class Packet:
    event: int
    session_id: str
    payload: dict | bytes


def encode(event: int, payload: dict | bytes, session_id: str = "") -> bytes:
    audio = isinstance(payload, bytes)
    body = payload if audio else json.dumps(payload, ensure_ascii=False).encode()
    frame = bytes((0x11, 0x24 if audio else 0x14, 0 if audio else 0x10, 0))
    frame += struct.pack(">I", event)
    if event >= 100:
        sid = session_id.encode()
        frame += struct.pack(">I", len(sid)) + sid
    return frame + struct.pack(">I", len(body)) + body


def decode(frame: bytes) -> Packet:
    if len(frame) < 8 or len(frame) > MAX_FRAME or frame[0] >> 4 != 1:
        raise ValueError("Invalid realtime frame")
    offset = (frame[0] & 15) * 4
    kind, flags = frame[1] >> 4, frame[1] & 15
    serialization, compression = frame[2] >> 4, frame[2] & 15
    if offset < 4 or kind not in (9, 11, 15) or compression not in (0, 1):
        raise ValueError("Unsupported realtime frame")

    def number():
        nonlocal offset
        if offset + 4 > len(frame):
            raise ValueError("Truncated realtime frame")
        value = struct.unpack_from(">I", frame, offset)[0]
        offset += 4
        return value

    if kind == 15:
        number()  # Upstream error code; never expose its raw payload/credentials.
        raise ValueError("Realtime upstream error")
    if flags & 1:
        number()  # Optional sequence, including negative terminal sequence.
    if not flags & 4:
        raise ValueError("Missing realtime event")
    event = number()
    # Server connection events carry connection ID; session events carry session ID.
    size = number()
    if size > 256 or offset + size > len(frame):
        raise ValueError("Invalid realtime identifier")
    sid = frame[offset:offset + size].decode("utf-8")
    offset += size
    length = number()
    if length != len(frame) - offset:
        raise ValueError("Invalid realtime payload size")
    payload = frame[offset:]
    if compression == 1:
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
            payload = stream.read(MAX_FRAME + 1)
        if len(payload) > MAX_FRAME:
            raise ValueError("Realtime payload too large")
    if serialization == 1:
        payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise ValueError("Expected realtime object")
    elif serialization != 0:
        raise ValueError("Unsupported realtime serialization")
    return Packet(event, sid, payload)
