"""Lifecycle management for an optional local GPT-SoVITS service."""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import threading
import time
import urllib.request
from urllib.parse import urlsplit


_TRUE_VALUES = {"1", "true", "yes", "on"}


class VoiceServiceConfigurationError(RuntimeError):
    """Raised when automatic voice-service startup is configured unsafely."""


class VoiceServiceManager:
    """Start and stop a local GPT-SoVITS API owned by the desktop client."""

    def __init__(
        self,
        log,
        log_dir: str,
        *,
        environ=None,
        popen_factory=None,
        run_factory=None,
        urlopen=None,
        socket_connect=None,
    ) -> None:
        self._log = log
        self._log_dir = log_dir
        self._environ = environ if environ is not None else os.environ
        self._popen = popen_factory if popen_factory is not None else subprocess.Popen
        self._run = run_factory if run_factory is not None else subprocess.run
        self._urlopen = urlopen if urlopen is not None else urllib.request.urlopen
        self._socket_connect = (
            socket_connect if socket_connect is not None else socket.create_connection
        )
        self._process = None
        self._log_handle = None
        self._lock = threading.RLock()

    def _setting(self, name: str, default: str = "") -> str:
        formal_name = f"SHULIAN_FORMAL_{name}"
        if formal_name in self._environ:
            return self._environ.get(formal_name, default)
        return self._environ.get(name, default)

    def _is_enabled(self) -> bool:
        provider = self._setting("TTS_PROVIDER", "edge").strip().lower()
        enabled = self._setting("GPT_SOVITS_AUTO_START", "").strip().lower()
        return provider == "gpt_sovits" and enabled in _TRUE_VALUES

    def _service_address(self) -> tuple[str, str, int]:
        raw = self._setting("GPT_SOVITS_BASE_URL", "").strip().rstrip("/")
        if not raw:
            raise VoiceServiceConfigurationError("GPT_SOVITS_BASE_URL is missing")
        parsed = urlsplit(raw)
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise VoiceServiceConfigurationError(
                "GPT_SOVITS_BASE_URL must be a plain local HTTP origin"
            )
        host = parsed.hostname
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = host.lower() == "localhost"
        if not is_loopback:
            raise VoiceServiceConfigurationError(
                "automatic GPT-SoVITS startup only supports loopback addresses"
            )
        try:
            port = parsed.port or 80
        except ValueError as exc:
            raise VoiceServiceConfigurationError(
                "GPT_SOVITS_BASE_URL contains an invalid port"
            ) from exc
        return raw, host, port

    def _api_is_ready(self, base_url: str, timeout: float = 0.8) -> bool:
        try:
            with self._urlopen(
                f"{base_url}/openapi.json",
                timeout=timeout,
            ) as response:
                if getattr(response, "status", 200) != 200:
                    return False
                payload = json.loads(response.read().decode("utf-8"))
            return "/tts" in payload.get("paths", {})
        except Exception:
            return False

    def _port_is_open(self, host: str, port: int) -> bool:
        try:
            connection = self._socket_connect((host, port), timeout=0.5)
            connection.close()
            return True
        except OSError:
            return False

    def _resolve_path(self, root: str, name: str, default: str) -> str:
        raw = self._setting(name, "").strip() or default
        expanded = os.path.expanduser(os.path.expandvars(raw))
        if not os.path.isabs(expanded):
            expanded = os.path.join(root, expanded)
        return os.path.abspath(expanded)

    def _build_command(self, host: str, port: int) -> tuple[list[str], str]:
        root_raw = self._setting("GPT_SOVITS_ROOT", "").strip()
        if not root_raw:
            raise VoiceServiceConfigurationError("GPT_SOVITS_ROOT is missing")
        root = os.path.abspath(os.path.expanduser(os.path.expandvars(root_raw)))
        python = self._resolve_path(
            root,
            "GPT_SOVITS_PYTHON",
            os.path.join(".venv", "Scripts", "python.exe"),
        )
        script = self._resolve_path(root, "GPT_SOVITS_SCRIPT", "api_v2.py")
        config = self._resolve_path(
            root,
            "GPT_SOVITS_CONFIG",
            os.path.join("GPT_SoVITS", "configs", "tts_infer.yaml"),
        )
        for label, path in (
            ("GPT_SOVITS_ROOT", root),
            ("GPT_SOVITS_PYTHON", python),
            ("GPT_SOVITS_SCRIPT", script),
            ("GPT_SOVITS_CONFIG", config),
        ):
            if not os.path.exists(path):
                raise VoiceServiceConfigurationError(f"{label} does not exist: {path}")
        return [
            python,
            script,
            "-a",
            host,
            "-p",
            str(port),
            "-c",
            config,
        ], root

    def _close_log_handle(self) -> None:
        with self._lock:
            if self._log_handle is not None:
                try:
                    self._log_handle.close()
                finally:
                    self._log_handle = None

    def _monitor_startup(self, process, base_url: str) -> None:
        raw_timeout = self._setting("GPT_SOVITS_STARTUP_TIMEOUT_SECONDS", "120").strip()
        try:
            timeout = max(5.0, min(float(raw_timeout), 300.0))
        except ValueError:
            timeout = 120.0
        deadline = time.time() + timeout
        while time.time() < deadline:
            exit_code = process.poll()
            if exit_code is not None:
                self._log(f"GPT-SOVITS EXITED DURING STARTUP: code={exit_code}")
                self._close_log_handle()
                return
            if self._api_is_ready(base_url, timeout=1.0):
                self._log(f"GPT-SOVITS READY: {base_url}")
                return
            time.sleep(0.5)
        self._log(f"GPT-SOVITS STARTUP TIMEOUT: {base_url}")

    def _start_monitor(self, process, base_url: str) -> None:
        threading.Thread(
            target=self._monitor_startup,
            args=(process, base_url),
            daemon=True,
            name="gpt-sovits-startup-monitor",
        ).start()

    def start_if_configured(self) -> str:
        """Start GPT-SoVITS when configured, or reuse an existing valid service."""
        if not self._is_enabled():
            return "disabled"
        try:
            base_url, host, port = self._service_address()
            if self._api_is_ready(base_url):
                self._log(f"GPT-SOVITS REUSED: {base_url}")
                return "reused"
            if self._port_is_open(host, port):
                self._log(
                    f"GPT-SOVITS AUTOSTART SKIPPED: unrecognized service owns {host}:{port}"
                )
                return "conflict"
            command, root = self._build_command(host, port)
        except VoiceServiceConfigurationError as exc:
            self._log(f"GPT-SOVITS AUTOSTART CONFIG ERROR: {exc}")
            return "invalid"

        os.makedirs(self._log_dir, exist_ok=True)
        log_path = os.path.join(self._log_dir, "gpt-sovits-service.log")
        try:
            log_handle = open(log_path, "ab", buffering=0)
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = self._popen(
                command,
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                shell=False,
                creationflags=creationflags,
            )
        except Exception as exc:
            try:
                log_handle.close()
            except Exception:
                pass
            self._log(f"GPT-SOVITS AUTOSTART FAILED: {exc!r}")
            return "failed"

        with self._lock:
            self._process = process
            self._log_handle = log_handle
        self._log(f"GPT-SOVITS STARTED: pid={process.pid} url={base_url}")
        self._start_monitor(process, base_url)
        return "started"

    def stop(self) -> None:
        """Stop only the GPT-SoVITS process started by this manager."""
        with self._lock:
            process = self._process
            self._process = None
        if process is None:
            return
        try:
            if process.poll() is None:
                if os.name == "nt":
                    self._run(
                        [
                            "taskkill",
                            "/PID",
                            str(process.pid),
                            "/T",
                            "/F",
                        ],
                        check=False,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                else:
                    process.terminate()
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                self._log("GPT-SOVITS STOPPED WITH SHULIAN")
        except Exception as exc:
            self._log(f"GPT-SOVITS STOP FAILED: {exc!r}")
        finally:
            self._close_log_handle()
