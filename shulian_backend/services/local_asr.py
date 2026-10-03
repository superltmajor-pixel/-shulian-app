"""Offline Chinese streaming ASR backed by sherpa-onnx."""

from __future__ import annotations

import importlib.util
import os
import shutil
import tarfile
import tempfile
import threading
import urllib.request
from pathlib import Path, PurePosixPath

import ai_credentials

MODEL_ID = "sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    f"{MODEL_ID}.tar.bz2"
)
MODEL_FILES = {
    "tokens.txt": 1_000,
    "encoder-epoch-99-avg-1.int8.onnx": 1_000_000,
    "decoder-epoch-99-avg-1.onnx": 500_000,
    "joiner-epoch-99-avg-1.int8.onnx": 500_000,
}
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_MODEL_BYTES = 80 * 1024 * 1024

_recognizer = None
_recognizer_lock = threading.Lock()
_download_lock = threading.Lock()


class LocalAsrError(RuntimeError):
    """A safe, user-facing local-recognition failure."""


def model_dir() -> Path:
    # Keep downloaded model weights beside the protected user credentials, not
    # in the source tree, the replaceable EXE directory, or the release payload.
    return ai_credentials.credential_path().parent / "models" / MODEL_ID


def runtime_available() -> bool:
    try:
        if importlib.util.find_spec("sherpa_onnx") is None:
            return False
        import sherpa_onnx

        return hasattr(sherpa_onnx, "OnlineRecognizer")
    except (ImportError, OSError, ValueError):
        return False


def _valid_file(path: Path, minimum: int) -> bool:
    try:
        return not path.is_symlink() and path.is_file() and path.stat().st_size >= minimum
    except OSError:
        return False


def model_installed() -> bool:
    root = model_dir()
    return all(_valid_file(root / name, minimum) for name, minimum in MODEL_FILES.items())


def status() -> dict:
    installed = model_installed()
    available = runtime_available()
    return {
        "runtime_available": available,
        "model_installed": installed,
        "ready": available and installed,
        "model_id": MODEL_ID,
    }


def _download_model() -> dict:
    target = model_dir()
    if model_installed():
        return status()
    if target.exists() or target.is_symlink():
        raise LocalAsrError("本地语音模型目录已存在但不完整；为保护本机文件，没有覆盖它")

    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix=".shulian-asr-", dir=parent))
    archive_path = temp_root / "model.tar.bz2"
    staged = temp_root / MODEL_ID
    staged.mkdir()
    try:
        request = urllib.request.Request(
            MODEL_URL,
            headers={"User-Agent": "Shulian-local-speech/1.0"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_ARCHIVE_BYTES:
                raise LocalAsrError("语音模型下载体积异常，已停止")
            total = 0
            with archive_path.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise LocalAsrError("语音模型下载超过安全上限，已停止")
                    output.write(chunk)
        if not archive_path.is_file() or archive_path.stat().st_size < 1024:
            raise LocalAsrError("语音模型下载不完整，请检查网络后重试")

        found: set[str] = set()
        unpacked = 0
        try:
            with tarfile.open(archive_path, mode="r:bz2") as bundle:
                for member in bundle:
                    parts = PurePosixPath(member.name).parts
                    if len(parts) != 2 or parts[0] != MODEL_ID:
                        continue
                    name = parts[1]
                    if name not in MODEL_FILES:
                        continue
                    if not member.isfile() or member.issym() or member.islnk() or name in found:
                        raise LocalAsrError("语音模型文件结构无效，已停止安装")
                    if member.size < MODEL_FILES[name] or member.size > MAX_MODEL_BYTES:
                        raise LocalAsrError("语音模型文件大小异常，已停止安装")
                    unpacked += member.size
                    if unpacked > MAX_MODEL_BYTES:
                        raise LocalAsrError("语音模型解压体积超过安全上限，已停止")
                    source = bundle.extractfile(member)
                    if source is None:
                        raise LocalAsrError("语音模型文件读取失败")
                    destination = staged / name
                    with source, destination.open("xb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                    if destination.stat().st_size != member.size:
                        raise LocalAsrError("语音模型文件不完整，请重新下载")
                    found.add(name)
        except (tarfile.TarError, OSError, EOFError) as exc:
            raise LocalAsrError("语音模型解压失败，请重试") from exc

        if found != set(MODEL_FILES):
            raise LocalAsrError("语音模型缺少必要文件，请重试")
        if not all(_valid_file(staged / name, minimum) for name, minimum in MODEL_FILES.items()):
            raise LocalAsrError("语音模型校验失败，请重试")
        os.replace(staged, target)
        return status()
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def download_model() -> dict:
    with _download_lock:
        return _download_model()


def get_recognizer():
    global _recognizer
    if not runtime_available():
        raise LocalAsrError("当前客户端未包含本地识别组件，请更新客户端后重试")
    if not model_installed():
        raise LocalAsrError("请先下载本地中文语音模型")
    with _recognizer_lock:
        if _recognizer is None:
            try:
                import sherpa_onnx

                root = model_dir()
                _recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                    tokens=str(root / "tokens.txt"),
                    encoder=str(root / "encoder-epoch-99-avg-1.int8.onnx"),
                    decoder=str(root / "decoder-epoch-99-avg-1.onnx"),
                    joiner=str(root / "joiner-epoch-99-avg-1.int8.onnx"),
                    num_threads=max(1, min(4, os.cpu_count() or 1)),
                    sample_rate=16000,
                    feature_dim=80,
                    enable_endpoint_detection=True,
                    rule1_min_trailing_silence=2.4,
                    rule2_min_trailing_silence=1.2,
                    decoding_method="greedy_search",
                    provider="cpu",
                )
            except Exception as exc:
                _recognizer = None
                raise LocalAsrError("本地语音识别初始化失败，请重新下载语音模型") from exc
    return _recognizer


def decode_frame(recognizer, stream, frame: bytes) -> tuple[str, str | None]:
    """Decode one signed-16 little-endian 20ms frame; return interim/final text."""
    import numpy as np

    samples = np.frombuffer(frame, dtype="<i2").astype(np.float32) / 32768.0
    stream.accept_waveform(16000, samples)
    while recognizer.is_ready(stream):
        recognizer.decode_stream(stream)
    result = recognizer.get_result(stream)
    text = str(getattr(result, "text", result) or "").strip()
    if recognizer.is_endpoint(stream):
        recognizer.reset(stream)
        return text, text or None
    return text, None
