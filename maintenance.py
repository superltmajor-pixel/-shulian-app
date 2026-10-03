"""Local source update and safe uninstall coordination for the desktop shell."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser


_SOURCE_SUFFIXES = {
    ".bat", ".html", ".js", ".json", ".jsx", ".mjs", ".ps1", ".py", ".spec",
}
_SOURCE_EXCLUDED_PARTS = {
    ".frontend-build", ".git", "__pycache__", "dist", "node_modules", "output",
    ".claude", ".codex", ".agents", ".playwright-cli",
    "release", "tests", "venv",
    "role-library", "local-data", "webview-data", "media", "logs",
    "migration-backups", "character_bibles", "personality_profiles", "assets",
}


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _version_key(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"\s*(\d+)\.(\d+)\.(\d+)(?:[-+].*)?\s*", str(value or ""))
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def source_fingerprint(source_root: Path) -> str:
    """Hash maintainable build inputs without runtime/build/cache directories."""
    digest = hashlib.sha256()
    files: list[Path] = []
    for path in source_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        relative = path.relative_to(source_root)
        if any(part in _SOURCE_EXCLUDED_PARTS for part in relative.parts):
            continue
        if relative.as_posix() in {"maintenance-manifest.json", "packager.local.json"}:
            continue
        files.append(path)
    for path in sorted(files, key=lambda item: item.relative_to(source_root).as_posix().lower()):
        relative = path.relative_to(source_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def write_source_manifest(source_root: Path, output_path: Path) -> dict:
    release = _read_json(source_root / "release.json")
    payload = {
        "schemaVersion": 1,
        "productId": "shulian",
        "version": str(release.get("version") or ""),
        "buildId": str(release.get("buildId") or ""),
        "sourceFingerprint": source_fingerprint(source_root),
        "generatedAt": int(time.time()),
    }
    _write_json_atomic(output_path, payload)
    return payload


class MaintenanceCoordinator:
    def __init__(self, current_version: str, current_build_id: str) -> None:
        self.current_version = str(current_version)
        self.current_build_id = str(current_build_id)
        self._lock = threading.RLock()
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_app_data) if local_app_data else Path(tempfile.gettempdir())
        self.maintenance_dir = base / "Shulian" / "maintenance"
        self.job_path = self.maintenance_dir / "update-status.json"
        self.log_path = self.maintenance_dir / "update.log"

    @staticmethod
    def _runtime_app_dir() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent

    @staticmethod
    def _resource_path(relative: str) -> Path:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        return (base / relative).resolve()

    def public_release(self) -> dict:
        release = _read_json(self._resource_path("release.json"))
        url = str(release.get("publicReleaseUrl") or "").strip()
        valid = bool(re.fullmatch(r"https://github\.com/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+/releases", url))
        return {"publicReleaseUrl": url if valid else "",
                "publicReleaseReady": valid and release.get("publicReleaseReady") is True}

    def open_public_releases(self) -> dict:
        release = self.public_release()
        if not release["publicReleaseReady"]:
            return {"ok": False, "error": "release_not_published", "message": "公开下载页尚未开放。"}
        try:
            if webbrowser.open_new_tab(release["publicReleaseUrl"]):
                return {"ok": True}
        except Exception:
            pass
        return {"ok": False, "error": "browser_open_failed", "message": "无法打开浏览器，请稍后重试。"}

    def _discover(self) -> dict:
        runtime_dir = self._runtime_app_dir()
        candidates = []
        configured = os.environ.get("SHULIAN_PACKAGER_PATH", "").strip()
        if configured:
            candidates.append(Path(configured))
        candidates.extend([
            runtime_dir.parent / "package-shulian-inplace.ps1",
            Path(__file__).resolve().parent / "package-shulian-inplace.ps1",
        ])
        packager = next((item.resolve() for item in candidates if item.is_file()), None)
        config = _read_json(packager.parent / "packager.local.json") if packager else {}
        source_text = str(config.get("repo") or "").strip()
        app_text = str(config.get("appDir") or "").strip()
        source_dir = Path(source_text).resolve() if source_text else Path(__file__).resolve().parent
        app_dir = Path(app_text).resolve() if app_text else runtime_dir
        return {
            "runtime_dir": runtime_dir,
            "packager": packager,
            "source_dir": source_dir,
            "app_dir": app_dir,
        }

    def _last_job(self) -> dict | None:
        payload = _read_json(self.job_path)
        return payload or None

    def status(self) -> dict:
        discovered = self._discover()
        source_dir: Path = discovered["source_dir"]
        app_dir: Path = discovered["app_dir"]
        packager: Path | None = discovered["packager"]
        source_release = _read_json(source_dir / "release.json")
        client_release = _read_json(app_dir / "_internal" / "release.json")
        if not client_release:
            client_release = {
                "version": self.current_version,
                "buildId": self.current_build_id,
            }
        source_version = str(source_release.get("version") or "")
        client_version = str(client_release.get("version") or self.current_version)
        source_build = str(source_release.get("buildId") or "")
        client_build = str(client_release.get("buildId") or self.current_build_id)
        source_key = _version_key(source_version)
        client_key = _version_key(client_version)
        source_manifest = _read_json(source_dir / "maintenance-manifest.json")
        installed_manifest = _read_json(app_dir / "_internal" / "maintenance-manifest.json")
        source_fp = ""
        fingerprint_error = ""
        installed_fp = str(installed_manifest.get("sourceFingerprint") or "")
        identity_changed = bool(source_build and source_build != client_build)
        version_newer = bool(source_key and client_key and source_key > client_key)
        same_version = bool(source_key and client_key and source_key == client_key)
        packager_ready = bool(
            packager and source_dir.is_dir() and app_dir.is_dir()
            and (source_dir / "venv" / "Scripts" / "python.exe").is_file()
            and (source_dir / "release.json").is_file()
        )
        if packager_ready:
            try:
                source_fp = source_fingerprint(source_dir)
            except OSError as exc:
                fingerprint_error = str(exc)
        source_changed = bool(source_fp and installed_fp and source_fp != installed_fp)
        public_release = self.public_release()
        reason = ""
        if not packager_ready:
            reason = "请前往下载页查看可用版本。" if public_release["publicReleaseReady"] else "公开下载页尚未开放。"
        elif not source_key or not client_key:
            reason = "源码或客户端版本号格式无效。"
        elif source_key < client_key:
            reason = "源码版本低于当前客户端，已阻止自动降级。"
        elif same_version and (identity_changed or source_changed):
            reason = "检测到源码变动，但版本号尚未递增。"
        elif same_version:
            reason = "当前已经是最新版本。"
        update_available = bool(packager_ready and version_newer and (identity_changed or source_changed or not installed_fp))
        return {
            "ok": True,
            "installed": bool((app_dir / "Shulian.exe").is_file()),
            "packagerReady": packager_ready,
            "updateMode": "source" if packager_ready else "download",
            **public_release,
            "updateAvailable": update_available,
            "sourceChanged": source_changed or identity_changed,
            "clientVersion": client_version,
            "clientBuildId": client_build,
            "sourceVersion": source_version,
            "sourceBuildId": source_build,
            "sourceFingerprint": source_fp,
            "installedFingerprint": installed_fp,
            "fingerprintError": fingerprint_error,
            "reason": reason,
            "sourceDir": str(source_dir),
            "appDir": str(app_dir),
            "lastJob": self._last_job(),
            "sourceManifestVersion": str(source_manifest.get("version") or ""),
        }

    def start_update(self) -> dict:
        with self._lock:
            current = self._last_job()
            if current and current.get("status") in {"queued", "running", "restarting"}:
                if current.get("status") == "restarting" or self._job_is_alive(current):
                    return {"ok": False, "error": "update_in_progress", "job": current}
                _write_json_atomic(
                    self.job_path,
                    {
                        **current,
                        "status": "failed",
                        "percent": 0,
                        "stage": "failed",
                        "message": "上一次更新任务已退出，可以重新开始。",
                        "finishedAt": int(time.time()),
                    },
                )
            status = self.status()
            if not status.get("updateAvailable"):
                return {"ok": False, "error": "update_not_available", "message": status.get("reason", "")}
            discovered = self._discover()
            packager: Path = discovered["packager"]
            self.maintenance_dir.mkdir(parents=True, exist_ok=True)
            job = {
                "schemaVersion": 1,
                "productId": "shulian",
                "status": "queued",
                "percent": 1,
                "stage": "queued",
                "message": "更新任务已进入后台队列。",
                "sourceVersion": status["sourceVersion"],
                "clientVersion": status["clientVersion"],
                "startedAt": int(time.time()),
            }
            _write_json_atomic(self.job_path, job)
            creationflags = 0
            startupinfo = None
            if os.name == "nt":
                creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            command = [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(packager), "-ProgressPath", str(self.job_path), "-LaunchedByApp",
            ]
            with self.log_path.open("ab") as log_stream:
                process = subprocess.Popen(
                    command,
                    cwd=str(packager.parent),
                    stdin=subprocess.DEVNULL,
                    stdout=log_stream,
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                    startupinfo=startupinfo,
                )
            job = {**job, "processId": process.pid}
            _write_json_atomic(self.job_path, job)
            threading.Thread(
                target=self._monitor_update_process,
                args=(process,),
                name="shulian-update-monitor",
                daemon=True,
            ).start()
            return {"ok": True, "job": job}

    @staticmethod
    def _job_is_alive(job: dict) -> bool:
        process_id = job.get("processId")
        try:
            process_id = int(process_id)
        except (TypeError, ValueError):
            process_id = 0
        if process_id > 0:
            try:
                os.kill(process_id, 0)
                return True
            except PermissionError:
                return True
            except (OSError, ProcessLookupError):
                return False
        started_at = job.get("startedAt")
        try:
            return time.time() - float(started_at) < 30
        except (TypeError, ValueError):
            return False

    def _monitor_update_process(self, process: subprocess.Popen) -> None:
        """Surface a launcher/parser failure instead of leaving the UI at 1%."""
        try:
            exit_code = process.wait()
        except Exception:
            return
        with self._lock:
            current = self._last_job() or {}
            if current.get("status") not in {"queued", "running"}:
                return
            if exit_code == 0:
                message = "更新任务提前结束，未收到完成状态。请查看更新日志。"
            else:
                message = (
                    f"更新程序未能启动（退出码 {exit_code}）。"
                    "请查看本机更新日志后重试。"
                )
            _write_json_atomic(
                self.job_path,
                {
                    **current,
                    "status": "failed",
                    "percent": 0,
                    "stage": "failed",
                    "message": message,
                    "finishedAt": int(time.time()),
                },
            )

    def update_job(self) -> dict:
        return {"ok": True, "job": self._last_job()}

    def prepare_uninstall(self, remove_user_data: bool, confirmation: str) -> dict:
        if confirmation != "卸载数恋":
            return {"ok": False, "error": "confirmation_required"}
        if os.name != "nt" or not getattr(sys, "frozen", False):
            return {"ok": False, "error": "not_installed", "message": "源码运行模式不会执行卸载。"}
        app_dir = self._runtime_app_dir()
        app_exe = Path(sys.executable).resolve()
        release = _read_json(app_dir / "_internal" / "release.json")
        if app_exe.name.lower() != "shulian.exe" or release.get("productId") != "shulian":
            return {"ok": False, "error": "installation_unverified"}
        helper_source = self._resource_path("packaging/uninstaller/ShulianUninstaller.ps1")
        if not helper_source.is_file():
            return {"ok": False, "error": "uninstaller_missing"}
        work_dir = Path(tempfile.gettempdir()) / f"Shulian-Uninstall-{uuid.uuid4().hex}"
        work_dir.mkdir(parents=True, exist_ok=False)
        helper = work_dir / "ShulianUninstaller.ps1"
        plan_path = work_dir / "uninstall-plan.json"
        shutil.copy2(helper_source, helper)
        local_app_data = Path(os.environ.get("LOCALAPPDATA", "")).resolve()
        plan = {
            "schemaVersion": 1,
            "productId": "shulian",
            "appDir": str(app_dir),
            "appExe": str(app_exe),
            "processId": os.getpid(),
            "removeUserData": bool(remove_user_data),
            "localDataDir": str(local_app_data / "Shulian"),
            "createdAt": int(time.time()),
        }
        _write_json_atomic(plan_path, plan)
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        process = subprocess.Popen(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(helper), "-PlanPath", str(plan_path),
            ],
            cwd=str(work_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        return {"ok": True, "scheduled": True, "processId": process.pid, "removeUserData": bool(remove_user_data)}
