"""Check a portable EXE with synthetic data; never open the installed user's data."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request


def check(app: Path, work: Path, port: int) -> dict:
    if os.name != "nt":
        raise RuntimeError("This acceptance check requires Windows")
    app = app.resolve()
    work = work.absolute()
    if work.exists() or work.is_symlink() or work.is_junction():
        raise ValueError("Work directory must be new")
    if work.resolve().is_relative_to(app) or app.is_relative_to(work.resolve()):
        raise ValueError("Test data must be separate from the built app")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
    if not (app / "Shulian.exe").is_file():
        raise ValueError("App directory must contain Shulian.exe")
    if any((app / name).exists() for name in (".env", "webview-data", "media", "local-data", "role-library")):
        raise ValueError("Test input must be a fresh build with no user data")
    release = json.loads((app / "_internal" / "release.json").read_text(encoding="utf-8-sig"))
    # Desktop mutex is shared even when the test backend uses another port.
    running = subprocess.check_output(["tasklist", "/FI", "IMAGENAME eq Shulian.exe", "/FO", "CSV"],
                                      text=True, errors="replace")
    if '"Shulian.exe"' in running:
        raise RuntimeError("Exit other Shulian windows before testing; they will not be stopped")
    work.mkdir(parents=True)
    old, new = work / "first-install", work / "new-install"
    shutil.copytree(app, old)
    shutil.copytree(app, new)
    local = work / "appdata"
    local.mkdir()
    base = f"http://127.0.0.1:{port}"

    def request(path: str, data=None, method: str = "GET", raw: bool = False):
        headers = {"Origin": base}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, method=method, headers=headers,
                                     data=None if data is None else json.dumps(data).encode("utf-8"))
        with urllib.request.urlopen(req, timeout=10) as response:
            value = response.read()
        return value if raw else json.loads(value)

    def start(folder: Path):
        env = {k: v for k, v in os.environ.items()
               if not k.endswith("_API_KEY") and not k.startswith(("SHULIAN_", "GPT_SOVITS_"))}
        env.update({
            "LOCALAPPDATA": str(local), "PYTHON_DOTENV_DISABLED": "1",
            "SHULIAN_PORT": str(port), "TTS_PROVIDER": "edge",
            "SHULIAN_ROLE_LIBRARY_DIR": str(local / "Shulian" / "role-library"),
            "SHULIAN_STATE_DB": str(local / "Shulian" / "state.sqlite3"),
            "SHULIAN_CREDENTIALS_FILE": str(local / "Shulian" / "credentials.bin"),
            "SHULIAN_AI_PREFERENCES_FILE": str(local / "Shulian" / "ai-preferences.json"),
            "SHULIAN_STORAGE_DIR": str(folder / "webview-data"),
            "SHULIAN_VOICE_DIR": str(folder / "media"),
            "SHULIAN_LOG_DIR": str(folder / "logs"),
        })
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        process = subprocess.Popen([str(folder / "Shulian.exe")], cwd=folder, env=env,
                                   startupinfo=startup, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Test EXE exited with {process.returncode}")
                try:
                    return process, request("/api/self-check")
                except (OSError, urllib.error.URLError):
                    time.sleep(0.3)
            raise RuntimeError("Test EXE startup timed out")
        except BaseException:
            stop(process)
            raise

    def stop(process):
        if process.poll() is None:
            # Stop only this disposable EXE and its descendants while the
            # parent still exists. Killing the parent alone leaves WebView2
            # briefly holding profile files, so it is not a completed exit.
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=True, timeout=20)
            process.wait(timeout=20)

    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jYfQAAAAASUVORK5CYII=")
    process, cold = start(old)
    try:
        assert cold["backend"]["version"] == release["version"], cold
        assert cold["backend"]["build_id"] == release["buildId"], cold
        assert cold["backend"]["mode"] == "exe", cold
        assert request("/api/role-library")["roles"] == {}
        assert b"app.bundle.js" in request("/", raw=True)
        created = request("/api/role-library/roles", {
            "profile": {"name": "便携验收角色", "persona": "用于离线验收的虚构朋友",
                        "personality": "坦率", "speakingStyle": "简短", "relationship": "朋友",
                        "img": "data:image/png;base64," + base64.b64encode(png).decode()},
            "archived_sessions": [{"startTs": 1, "endTs": 2, "messages": [
                {"from": "me", "text": "这是模拟聊天", "ts": 1},
                {"from": "them", "text": "模拟回复", "ts": 2}]}],
            "memory": "仅供验收的合成记忆",
        }, "POST")
        role_id = created["characterId"]
        before = request(f"/api/role-library/roles/{role_id}")
        state = {f"sl_rel_{role_id}": "9", "sl_user_name": "离线测试用户"}
        request("/api/state", {"items": state}, "PUT")
        assert request(before["profile"]["img"], raw=True) == png
    finally:
        stop(process)

    # Follow the documented manual update into a separate fresh directory.
    # Marker files exercise copying app-local folders without any real userdata.
    markers = {"webview-data/acceptance.txt": b"synthetic-ui-state",
               "media/acceptance.txt": b"synthetic-media",
               "local-data/acceptance.txt": b"synthetic-local-data",
               ".env": b"SHULIAN_ACCEPTANCE_ONLY=1\n"}
    for relative, value in markers.items():
        path = old / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    for name in ("webview-data", "media", "local-data"):
        if (new / name).exists():
            raise RuntimeError("Fresh package unexpectedly contains user data")
        deadline = time.monotonic() + 10
        while True:
            try:
                shutil.copytree(old / name, new / name, dirs_exist_ok=True)
                break
            except shutil.Error:
                # WebView2 may remove its transient lock/cache files just after
                # exit. Retry the complete copy; never skip persistent data.
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.3)
    shutil.copyfile(old / ".env", new / ".env")
    database = local / "Shulian" / "state.sqlite3"
    db_hash = hashlib.sha256(database.read_bytes()).hexdigest()
    process, restarted = start(new)
    try:
        after = request(f"/api/role-library/roles/{role_id}")
        assert after == before
        assert request(after["profile"]["img"], raw=True) == png
        persisted = request("/api/state")["data"]
        assert all(persisted[k] == v for k, v in state.items())
        profile = {**after["profile"], "name": "便携验收角色改名"}
        request(f"/api/role-library/roles/{role_id}", {"profile": profile}, "PUT")
        edited = request(f"/api/role-library/roles/{role_id}")
        assert edited["profile"]["name"] == profile["name"]
        assert edited["archived_sessions"] == before["archived_sessions"]
        assert edited["memory"] == before["memory"]
        for relative, value in markers.items():
            assert (new / relative).read_bytes() == value
    finally:
        stop(process)
    result = {
        "version": restarted["backend"]["version"], "buildId": restarted["backend"]["build_id"],
        "coldStart": "pass", "emptyInitialRoles": "pass", "webResources": "pass",
        "createEditRole": "pass", "importedChatAndImages": "pass",
        "directoryChangeDataRetention": "pass", "appLocalCopyMarkers": "pass",
        "stateDatabaseBeforeRestartSha256": db_hash,
        "testData": "synthetic only", "installedClientChanged": False,
        "scope": "EXE API acceptance; no native UI, real AI, microphone or historical-version upgrade exercised",
    }
    (work / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18879)
    args = parser.parse_args()
    print(json.dumps(check(args.app_dir, args.work_dir, args.port), ensure_ascii=False, indent=2))
