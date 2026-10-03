# -*- mode: python ; coding: utf-8 -*-
import os
import re
import sys
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

ROOT = os.path.abspath(SPECPATH)
sys.path.insert(0, ROOT)
from public_source import public_web_file
from binary_notices import collect_binary_notices
from pathlib import Path

datas = []
binaries = []
hiddenimports = []

datas.append((os.path.join(ROOT, "shulian.ico"), "."))
for notice in ("LICENSE", "LICENSING.md", "COMMERCIAL_LICENSE.md", "TRADEMARKS.md", "THIRD_PARTY_NOTICES.md", "CONTRIBUTING.md", "CLA.md"):
    datas.append((os.path.join(ROOT, notice), "."))
datas.append((os.path.join(ROOT, "release.json"), "."))
maintenance_manifest = os.path.join(ROOT, "maintenance-manifest.json")
if os.path.isfile(maintenance_manifest):
    datas.append((maintenance_manifest, "."))
datas.append((
    os.path.join(ROOT, "packaging", "uninstaller", "ShulianUninstaller.ps1"),
    os.path.join("packaging", "uninstaller"),
))

for pkg in ("uvicorn", "websockets", "aiohttp", "webview", "edge_tts", "clr_loader", "pythonnet", "sherpa_onnx"):
    datas += collect_data_files(pkg, include_py_files=False)
    binaries += collect_dynamic_libs(pkg)
    hiddenimports += collect_submodules(pkg)

web_root = os.path.join(ROOT, "web")

# 备份与临时文件不得进入发布产物：覆盖 .before-XXX、.bak、.bak-XXX、.tmp、.orig 和 ~。
BACKUP_RE = re.compile(r"(\.before-|\.bak\d*|\.bak-|\.tmp|\.orig|~$)", re.IGNORECASE)


def _should_skip(name: str) -> bool:
    return bool(BACKUP_RE.search(name))


for dirpath, dirnames, filenames in os.walk(web_root):
    if "media" in dirpath.split(os.sep):
        dirnames[:] = []
        continue
    dirnames[:] = [dirname for dirname in dirnames if not _should_skip(dirname)]
    for fn in filenames:
        if _should_skip(fn):
            continue
        full = os.path.join(dirpath, fn)
        if not public_web_file(os.path.relpath(full, ROOT).replace(os.sep, "/")):
            continue
        rel = os.path.relpath(os.path.dirname(full), ROOT)
        datas.append((full, rel))

# 收集完成后再次拦截，防止未来修改过滤逻辑时静默把备份文件带入 datas。
_bad = [source for source, _ in datas if _should_skip(os.path.basename(source))]
if _bad:
    raise SystemExit("FATAL: 备份文件进入 datas，已阻止打包: %r" % _bad[:10])

# 安全边界：.env 与用户 API Key 绝不进入 PyInstaller 数据文件。
a = Analysis(
    ["desktop.py"],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["clr"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "PIL",
        "tkinter",
        "torch",
        "matplotlib",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "cefpython3",
        "gtk",
    ],
    noarchive=False,
)
a.datas += collect_binary_notices(a.pure, a.binaries, Path(ROOT), Path(workpath))
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Shulian",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(ROOT, "shulian.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Shulian",
)
