"""数恋 桌面版启动器。

把 FastAPI 后端跑在进程内固定的本地端口上（对用户隐身），
再开一个 pywebview 桌面窗口（Edge WebView2 / Chromium 内核）指向它。
双击 EXE = 一个桌面窗口，没有黑窗口、没有浏览器标签、不用管端口。

语音：后端 .env 里 TTS_PROVIDER=gpt_sovits 时会优先用本地克隆音色（需另开语音服务），
合成失败自动退回云端 edge-tts 神经音——所以不开语音服务也能正常出声。
"""
import json
import os
import ctypes
from ctypes import wintypes
import socket
import sys
import threading
import time
import urllib.request

# 打包成无控制台窗口的 EXE 时 stdout/stderr 可能为 None，uvicorn 写日志会报错，先兜底
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import traceback

from diagnostics import configure_logging, diagnostic_log_path, log_event, record_metric
from maintenance import MaintenanceCoordinator
from shulian_backend.version import APP_VERSION, BUILD_ID
from voice_service import VoiceServiceManager

# 出错时把异常写到 exe 旁边的轮转日志，方便排查（窗口模式看不到控制台）
_DEFAULT_LOG_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
    else os.path.dirname(os.path.abspath(__file__))
_LOG_DIR = os.environ.get("SHULIAN_LOG_DIR", "").strip() or _DEFAULT_LOG_DIR
os.environ.setdefault("SHULIAN_LOG_DIR", _LOG_DIR)
configure_logging(_LOG_DIR)
_LOG_PATH = str(diagnostic_log_path())
# WebView2 用户数据目录：localStorage（聊天记录/亲密度/记忆）就存这里，放 exe 旁边才能持久保存
_STORAGE_DIR = os.environ.get("SHULIAN_STORAGE_DIR", "").strip() or os.path.join(_LOG_DIR, "webview-data")
# 固定端口：localStorage 按"网址(含端口)"隔离，端口固定每次重启才认得同一份数据
_PORT = int(os.environ.get("SHULIAN_PORT", "8770"))
_BUILD_ID = BUILD_ID
# 打包身份必须以当前 EXE 自身为准。后台更新由旧版进程发起时，子进程会
# 继承旧版的环境变量；若继续使用 setdefault，新版后端会误报旧 Build ID。
os.environ["SHULIAN_BUILD_ID"] = _BUILD_ID
_AUTO_ARCHIVE_ROLE_LIBRARY = os.environ.get("SHULIAN_ARCHIVE_ROLE_LIBRARY_ON_START", "").strip() == "1"
_INSTANCE_MUTEX_NAME = r"Local\ShulianDesktop-8770"
_INSTANCE_MUTEX_HANDLE = None
_ERROR_ALREADY_EXISTS = 183
_LOGIN_WINDOW_SIZE = (520, 640)
_MAIN_WINDOW_SIZE = (1040, 720)
_MIN_WINDOW_SIZE = (420, 560)
_WINDOW_SIZES = {
    "login": _LOGIN_WINDOW_SIZE,
    "main": _MAIN_WINDOW_SIZE,
}
_DESKTOP_STARTED_AT = time.perf_counter()


def _log(msg: str) -> None:
    log_event("info", "desktop", msg)


_VOICE_SERVICE = VoiceServiceManager(_log, _LOG_DIR)
_MAINTENANCE = MaintenanceCoordinator(APP_VERSION, BUILD_ID)


def _archive_role_library_after_start(window) -> None:
    """Run one local-only archive migration when explicitly enabled for maintenance."""
    deadline = time.time() + 180
    try:
        while time.time() < deadline:
            try:
                ready = window.evaluate_js(
                    "typeof window.__shulianArchiveRoleLibrary === 'function'"
                )
            except Exception:
                ready = False
            if ready:
                break
            time.sleep(0.5)
        else:
            _log("ROLE ARCHIVE MIGRATION FAILED: frontend migration function did not become ready")
            return

        window.evaluate_js(
            """
            window.__shulianArchiveMigrationResult = { status: 'running' };
            Promise.resolve(window.__shulianArchiveRoleLibrary())
              .then(result => { window.__shulianArchiveMigrationResult = { status: 'ok', result }; })
              .catch(error => {
                window.__shulianArchiveMigrationResult = {
                  status: 'error',
                  message: String((error && error.message) || error || 'unknown error')
                };
              });
            """
        )
        while time.time() < deadline:
            raw = window.evaluate_js(
                "JSON.stringify(window.__shulianArchiveMigrationResult || null)"
            )
            result = json.loads(raw) if isinstance(raw, str) and raw else raw
            if isinstance(result, dict) and result.get("status") in {"ok", "error"}:
                _log("ROLE ARCHIVE MIGRATION RESULT: " + json.dumps(result, ensure_ascii=False))
                return
            time.sleep(0.5)
        _log("ROLE ARCHIVE MIGRATION FAILED: migration timed out")
    except Exception:
        _log("ROLE ARCHIVE MIGRATION FAILED:\n" + traceback.format_exc())


try:
    import uvicorn
except Exception:
    _log("IMPORT FAILED:\n" + traceback.format_exc())
    raise


def _load_webview():
    try:
        import webview
        return webview
    except Exception:
        _log("WEBVIEW IMPORT FAILED:\n" + traceback.format_exc())
        raise


def _show_startup_error(message: str) -> None:
    """在无控制台的桌面包中向用户显示可操作的安全退出原因。"""
    _log(message)
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "数恋无法启动", 0x10)
    except Exception:
        _log("MESSAGE BOX FAILED:\n" + traceback.format_exc())


def _startup_html(message: str = "正在唤醒你的数字恋人…") -> str:
    safe_message = (
        str(message)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="color-scheme" content="dark">
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ width: 100%; height: 100%; margin: 0; }}
    body {{
      display: grid;
      place-items: center;
      overflow: hidden;
      color: rgba(255,255,255,.88);
      background:
        radial-gradient(circle at 20% 20%, rgba(128,82,170,.24), transparent 38%),
        radial-gradient(circle at 80% 75%, rgba(211,91,143,.18), transparent 42%),
        #08090b;
      font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
      -webkit-app-region: drag;
    }}
    main {{ text-align: center; }}
    .mark {{
      width: 42px; height: 42px; margin: 0 auto 18px;
      border: 2px solid rgba(255,255,255,.16);
      border-top-color: #d99af2;
      border-radius: 50%;
      animation: spin .9s linear infinite;
    }}
    p {{ margin: 0; font-size: 14px; letter-spacing: .04em; }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    @media (prefers-reduced-motion: reduce) {{ .mark {{ animation: none; }} }}
  </style>
</head>
<body><main><div class="mark"></div><p>{safe_message}</p></main></body>
</html>"""


class _DesktopWindowApi:
    """Resize the native shell when the web app crosses the login boundary."""

    def __init__(self, screens_provider) -> None:
        self._screens_provider = screens_provider
        self._window = None
        self._mode = None
        self._maximized = False
        self._restore_bounds = None
        self._lock = threading.RLock()
        self._tray = None
        self._exiting = False

    def start_tray(self) -> None:
        from shulian_backend.services.desktop_tray import DesktopTray
        try:
            tray = DesktopTray(self._window, self._exit_app)
            tray.start()
            self._tray = tray
        except Exception:
            if 'tray' in locals():
                tray.dispose()
            _log("TRAY START FAILED:\n" + traceback.format_exc())

    def _on_closing(self):
        if self._exiting:
            return True
        # The updater closes this window after persisting its restarting status.
        try:
            job = _MAINTENANCE.update_job().get("job") or {}
        except Exception:
            job = {}
        if job.get("status") == "restarting" and job.get("sourceVersion") != APP_VERSION:
            return True
        if self._tray is not None:
            self._window.hide()
            return False
        return True

    def _exit_app(self):
        self._exiting = True
        if self._window is not None:
            self._window.destroy()

    def attach_window(self, window, initial_mode: str | None = None) -> None:
        if initial_mode is not None and initial_mode not in _WINDOW_SIZES:
            raise ValueError(f"invalid initial window mode: {initial_mode}")
        with self._lock:
            self._window = window
            self._mode = initial_mode

    @staticmethod
    def _screen_for_window(screens, window):
        if not screens:
            return None
        try:
            center_x = window.x + window.width / 2
            center_y = window.y + window.height / 2
            for screen in screens:
                if (
                    screen.x <= center_x < screen.x + screen.width
                    and screen.y <= center_y < screen.y + screen.height
                ):
                    return screen
        except Exception:
            pass
        return screens[0]

    @staticmethod
    def _native_handle(window):
        if os.name != "nt":
            return None
        try:
            return int(window.native.Handle.ToInt64())
        except Exception:
            return None

    @staticmethod
    def _monitor_work_area(hwnd):
        """Return the nearest monitor's taskbar-safe work area in native pixels."""
        if os.name != "nt" or hwnd is None:
            return None

        class Rect(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class MonitorInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", Rect),
                ("rcWork", Rect),
                ("dwFlags", wintypes.DWORD),
            ]

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(MonitorInfo),
        ]
        user32.GetMonitorInfoW.restype = wintypes.BOOL

        monitor = user32.MonitorFromWindow(hwnd, 0x00000002)
        if not monitor:
            return None
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        work = info.rcWork
        width = int(work.right - work.left)
        height = int(work.bottom - work.top)
        if width <= 0 or height <= 0:
            return None
        return int(work.left), int(work.top), width, height

    @staticmethod
    def _set_native_bounds(hwnd, left, top, width, height):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        flags = 0x0004 | 0x0010 | 0x0200  # NOZORDER | NOACTIVATE | NOOWNERZORDER
        if not user32.SetWindowPos(hwnd, None, left, top, width, height, flags):
            raise ctypes.WinError(ctypes.get_last_error())

    def _apply_final_bounds(self, left, top, width, height, hwnd=None):
        if hwnd is not None and left is not None and top is not None:
            self._set_native_bounds(hwnd, left, top, width, height)
            return
        self._window.resize(width, height)
        if left is not None and top is not None:
            self._window.move(left, top)

    def set_window_mode(self, mode: str, animate: bool = False) -> dict:
        if mode not in _WINDOW_SIZES:
            return {"ok": False, "error": "invalid_mode"}

        with self._lock:
            if self._window is None:
                return {"ok": False, "error": "window_unavailable"}
            if self._mode == mode:
                return {"ok": True, "mode": mode, "unchanged": True}

            try:
                screens = list(self._screens_provider() or [])
                screen = self._screen_for_window(screens, self._window)
                desired_width, desired_height = _WINDOW_SIZES[mode]
                if screen is None:
                    width, height = desired_width, desired_height
                    left = top = None
                else:
                    available_width = max(_MIN_WINDOW_SIZE[0], int(screen.width) - 48)
                    available_height = max(_MIN_WINDOW_SIZE[1], int(screen.height) - 72)
                    width = min(desired_width, available_width)
                    height = min(desired_height, available_height)
                    left = int(screen.x + max(0, (screen.width - width) / 2))
                    top = int(screen.y + max(0, (screen.height - height) / 2))

                self._window.restore()
                self._maximized = False
                self._restore_bounds = None
                # pywebview's size API uses logical pixels and performs the Windows
                # DPI conversion itself. Raw SetWindowPos here interpreted 1040 as
                # physical pixels, leaving the main view at roughly login width on
                # high-DPI displays.
                self._apply_final_bounds(left, top, width, height)
                can_animate = False
            except Exception:
                _log("WINDOW MODE CHANGE FAILED:\n" + traceback.format_exc())
                return {"ok": False, "error": "resize_failed"}

            self._mode = mode
            _log(f"window mode={mode} size={width}x{height} animated={can_animate}")
            return {
                "ok": True,
                "mode": mode,
                "width": width,
                "height": height,
                "animated": can_animate,
            }

    def minimize_window(self) -> dict:
        with self._lock:
            if self._window is None:
                return {"ok": False, "error": "window_unavailable"}
            try:
                self._window.minimize()
                return {"ok": True}
            except Exception:
                _log("WINDOW MINIMIZE FAILED:\n" + traceback.format_exc())
                return {"ok": False, "error": "minimize_failed"}

    def drag_window(self) -> dict:
        """Begin a native caption drag from the custom HTML title bar."""
        with self._lock:
            if self._window is None:
                return {"ok": False, "error": "window_unavailable"}
            try:
                hwnd = int(self._window.native.Handle.ToInt64())
                user32 = ctypes.windll.user32
                user32.ReleaseCapture()
                user32.SendMessageW(hwnd, 0x00A1, 0x0002, 0)
                return {"ok": True}
            except Exception:
                _log("WINDOW DRAG FAILED:\n" + traceback.format_exc())
                return {"ok": False, "error": "drag_failed"}

    def toggle_maximize_window(self) -> dict:
        with self._lock:
            if self._window is None:
                return {"ok": False, "error": "window_unavailable"}
            try:
                if self._maximized:
                    restore_bounds = self._restore_bounds
                    self._window.restore()
                    if restore_bounds is not None:
                        left, top, width, height = restore_bounds
                        # ``window.x/y/width/height`` are pywebview logical pixels.
                        # Sending those values to Win32 SetWindowPos treats them as
                        # physical pixels and shrinks the window after every
                        # maximize/restore cycle on scaled displays (for example,
                        # 1040px becomes 832px at 125% DPI). Let pywebview perform
                        # the DPI conversion when restoring the saved bounds.
                        self._apply_final_bounds(
                            left,
                            top,
                            width,
                            height,
                        )
                    self._restore_bounds = None
                    maximized = False
                else:
                    self._restore_bounds = (
                        int(self._window.x),
                        int(self._window.y),
                        int(self._window.width),
                        int(self._window.height),
                    )
                    hwnd = self._native_handle(self._window)
                    work_area = self._monitor_work_area(hwnd)
                    if work_area is None:
                        self._window.maximize()
                    else:
                        left, top, width, height = work_area
                        self._window.restore()
                        self._apply_final_bounds(left, top, width, height, hwnd)
                    maximized = True
                self._maximized = maximized
                return {"ok": True, "maximized": maximized}
            except Exception:
                _log("WINDOW MAXIMIZE FAILED:\n" + traceback.format_exc())
                return {"ok": False, "error": "maximize_failed"}

    def close_window(self) -> dict:
        with self._lock:
            if self._window is None:
                return {"ok": False, "error": "window_unavailable"}
            try:
                if self._tray is not None:
                    self._window.hide()
                else:
                    self._window.minimize()
                return {"ok": True}
            except Exception:
                _log("WINDOW CLOSE FAILED:\n" + traceback.format_exc())
                return {"ok": False, "error": "close_failed"}

    def get_maintenance_status(self) -> dict:
        try:
            return _MAINTENANCE.status()
        except Exception:
            _log("MAINTENANCE STATUS FAILED:\n" + traceback.format_exc())
            return {"ok": False, "error": "maintenance_status_failed"}

    def open_public_releases(self) -> dict:
        return _MAINTENANCE.open_public_releases()

    def start_source_update(self) -> dict:
        try:
            result = _MAINTENANCE.start_update()
            if result.get("ok"):
                _log("SOURCE UPDATE STARTED")
            return result
        except Exception:
            _log("SOURCE UPDATE START FAILED:\n" + traceback.format_exc())
            return {"ok": False, "error": "update_start_failed"}

    def get_update_job(self) -> dict:
        try:
            return _MAINTENANCE.update_job()
        except Exception:
            _log("UPDATE JOB READ FAILED:\n" + traceback.format_exc())
            return {"ok": False, "error": "update_job_read_failed"}

    def uninstall_app(self, remove_user_data: bool = False, confirmation: str = "") -> dict:
        try:
            result = _MAINTENANCE.prepare_uninstall(bool(remove_user_data), str(confirmation))
            if result.get("ok"):
                _log(f"UNINSTALL SCHEDULED remove_user_data={bool(remove_user_data)}")
                # Return to JavaScript before closing; the external helper waits for this PID.
                threading.Timer(0.8, self._destroy_for_uninstall).start()
            return result
        except Exception:
            _log("UNINSTALL START FAILED:\n" + traceback.format_exc())
            return {"ok": False, "error": "uninstall_start_failed"}

    def _destroy_for_uninstall(self) -> None:
        with self._lock:
            try:
                if self._window is not None:
                    self._exit_app()
            except Exception:
                _log("UNINSTALL WINDOW CLOSE FAILED:\n" + traceback.format_exc())


def _acquire_instance_mutex() -> bool:
    """每个 Windows 登录会话只允许一个数恋桌面进程持有固定端口。"""
    global _INSTANCE_MUTEX_HANDLE
    if os.name != "nt":
        return True

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, _INSTANCE_MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _INSTANCE_MUTEX_HANDLE = handle
    return True


def _release_instance_mutex() -> None:
    global _INSTANCE_MUTEX_HANDLE
    if os.name != "nt" or not _INSTANCE_MUTEX_HANDLE:
        return
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(_INSTANCE_MUTEX_HANDLE)
    finally:
        _INSTANCE_MUTEX_HANDLE = None


def _reserve_local_port(port: int) -> socket.socket:
    """独占绑定固定回环端口，绝不连接或复用来源不明的已有 HTTP 服务。"""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", port))
        return listener
    except Exception:
        listener.close()
        raise


class _ThreadedServer(uvicorn.Server):
    """uvicorn 默认在 run() 里注册信号处理器，但信号只能在主线程注册。
    桌面版把后端跑在子线程，必须禁掉，否则子线程一启动就抛异常、服务起不来。"""

    def install_signal_handlers(self) -> None:  # noqa: D401
        pass


def _build_server(app, port: int) -> _ThreadedServer:
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    return _ThreadedServer(config)


def _run_server(server: _ThreadedServer, listener: socket.socket) -> None:
    try:
        server.run(sockets=[listener])
    except BaseException:
        _log("SERVER THREAD FAILED:\n" + traceback.format_exc())
    finally:
        listener.close()


class _BackendBootstrap:
    def __init__(self) -> None:
        self.loaded = threading.Event()
        self.server = None
        self.error = None


def _bootstrap_backend(
    bootstrap: _BackendBootstrap,
    listener: socket.socket,
    port: int,
) -> None:
    started_at = time.perf_counter()
    try:
        from main import app

        record_metric(
            "startup.backend_import",
            (time.perf_counter() - started_at) * 1000,
        )
        _VOICE_SERVICE.start_if_configured()
        bootstrap.server = _build_server(app, port)
        bootstrap.loaded.set()
        _run_server(bootstrap.server, listener)
    except BaseException:
        bootstrap.error = traceback.format_exc()
        bootstrap.loaded.set()
        try:
            listener.close()
        except Exception:
            pass
        _log("APP IMPORT OR SERVER START FAILED:\n" + bootstrap.error)


def _wait_until_ready(
    port: int,
    server: _ThreadedServer,
    server_thread: threading.Thread,
    timeout: float = 20.0,
) -> bool:
    """轮询 /health，等后端起来。"""
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not server_thread.is_alive():
            return False
        if not server.started:
            time.sleep(0.05)
            continue
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200 and server.started and server_thread.is_alive():
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def _wait_until_bootstrapped(
    port: int,
    bootstrap: _BackendBootstrap,
    server_thread: threading.Thread,
    timeout: float = 20.0,
) -> bool:
    started_at = time.time()
    if not bootstrap.loaded.wait(timeout):
        return False
    if bootstrap.error or bootstrap.server is None or not server_thread.is_alive():
        return False
    remaining = max(0.1, timeout - (time.time() - started_at))
    return _wait_until_ready(
        port,
        bootstrap.server,
        server_thread,
        timeout=remaining,
    )


def _finish_window_startup(
    window,
    port: int,
    bootstrap: _BackendBootstrap,
    server_thread: threading.Thread,
) -> None:
    ready = _wait_until_bootstrapped(port, bootstrap, server_thread)
    record_metric(
        "startup.backend_ready",
        (time.perf_counter() - _DESKTOP_STARTED_AT) * 1000,
        ok=ready,
    )
    _log(f"backend on 127.0.0.1:{port} ready={ready}")
    if not ready:
        message = "数恋本地服务启动失败，请关闭窗口后重试。"
        try:
            window.load_html(_startup_html(message))
        except Exception:
            _show_startup_error(message + " 请查看程序目录中的 shulian-debug.log。")
        return

    migration_query = "&archive-role-library=1" if _AUTO_ARCHIVE_ROLE_LIBRARY else ""
    window.load_url(f"http://127.0.0.1:{port}/?build={_BUILD_ID}{migration_query}")
    record_metric(
        "startup.frontend_navigation",
        (time.perf_counter() - _DESKTOP_STARTED_AT) * 1000,
    )
    if _AUTO_ARCHIVE_ROLE_LIBRARY:
        _archive_role_library_after_start(window)


def _native_titlebar_attributes(windows_build: int) -> dict[str, tuple[int, int]]:
    """Return only DWM attributes supported by the current Windows build."""
    # Windows 10 should skip these attributes entirely. Windows 11 exposes
    # dark mode and caption-color attributes starting with build 22000.
    attributes = {}
    if windows_build >= 22000:
        attributes.update(
            {
                "dark": (20, 1),
                "border": (34, 0x002C2625),
                "caption": (35, 0x000B0908),
                "text": (36, 0x00FFFFFF),
            }
        )
    return attributes


def _apply_native_window_theme(window) -> None:
    """让 Windows 原生标题栏跟随数恋的深色外观；旧版 Windows 不支持时静默回退。"""
    if os.name != "nt" or not window.events.shown.wait(10):
        return
    try:
        hwnd = int(window.native.Handle.ToInt64())
        dwm = ctypes.windll.dwmapi

        def set_attr(attribute: int, value: int) -> int:
            data = ctypes.c_int(value)
            return int(dwm.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd),
                ctypes.c_uint(attribute),
                ctypes.byref(data),
                ctypes.sizeof(data),
            ))

        windows_build = int(getattr(sys.getwindowsversion(), "build", 0))
        attributes = _native_titlebar_attributes(windows_build)
        results = {
            name: set_attr(attribute, value)
            for name, (attribute, value) in attributes.items()
        }
        _log(
            f"native title bar theme build={windows_build} "
            f"attributes={attributes} results={results}"
        )
    except Exception:
        _log("NATIVE TITLE BAR THEME FAILED:\n" + traceback.format_exc())


def main() -> None:
    port = _PORT
    try:
        log_event(
            "info",
            "desktop.start",
            "Shulian desktop process started",
            build_id=_BUILD_ID,
            frozen=bool(getattr(sys, "frozen", False)),
        )
        if not _acquire_instance_mutex():
            _show_startup_error("数恋已经在运行，请从系统托盘打开数恋；如需重启，请先在托盘菜单选择退出数恋。")
            return

        try:
            listener = _reserve_local_port(port)
        except OSError as exc:
            _show_startup_error(
                f"本机端口 {port} 已被其他程序占用，数恋已安全退出。\n\n"
                "为保护你的 API Key，数恋不会连接或复用这个未知服务。"
                "请关闭占用端口的程序后重试。"
            )
            _log(f"exclusive bind failed on 127.0.0.1:{port}: {exc!r}")
            return

        bootstrap = _BackendBootstrap()
        server_thread = threading.Thread(
            target=_bootstrap_backend,
            args=(bootstrap, listener, port),
            daemon=True,
        )
        server_thread.start()

        webview = _load_webview()
        os.makedirs(_STORAGE_DIR, exist_ok=True)
        window_api = _DesktopWindowApi(lambda: webview.screens)
        initial_screen = next(iter(webview.screens or []), None)
        window = webview.create_window(
            "数恋 · 数字恋人",
            html=_startup_html(),
            width=_LOGIN_WINDOW_SIZE[0],
            height=_LOGIN_WINDOW_SIZE[1],
            min_size=_MIN_WINDOW_SIZE,
            resizable=True,
            frameless=True,
            easy_drag=False,
            shadow=True,
            background_color="#08090b",
            js_api=window_api,
            screen=initial_screen,
        )
        # create_window 已按目标显示器居中；登记初始模式后，React 加载完成时
        # 再次请求 login 模式会直接返回 unchanged，不再把同一窗口横向移动一次。
        window_api.attach_window(window, initial_mode="login")
        window.events.shown += window_api.start_tray
        window.events.closing += window_api._on_closing
        record_metric(
            "startup.window_created",
            (time.perf_counter() - _DESKTOP_STARTED_AT) * 1000,
        )
        # private_mode=False + storage_path：localStorage 持久化到 _STORAGE_DIR，关窗不丢
        # 普通关闭收进托盘；托盘退出、更新与卸载才结束窗口和后端。
        webview.start(
            func=_finish_window_startup,
            args=(window, port, bootstrap, server_thread),
            private_mode=False,
            storage_path=_STORAGE_DIR,
        )
    finally:
        record_metric(
            "desktop.session",
            (time.perf_counter() - _DESKTOP_STARTED_AT) * 1000,
        )
        _VOICE_SERVICE.stop()
        _release_instance_mutex()


if __name__ == "__main__":
    main()
