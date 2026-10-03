# -*- mode: python ; coding: utf-8 -*-
import os
import re
import sys
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(SPECPATH)
sys.path.insert(0, ROOT)
from public_source import public_web_file
from binary_notices import collect_binary_notices
from pathlib import Path

datas = []
binaries = []
hiddenimports = []

# One application brand icon is shared by the EXE, tray and shortcuts.
datas.append((os.path.join(ROOT, "shulian.ico"), "."))
for notice in ("LICENSE", "LICENSING.md", "COMMERCIAL_LICENSE.md", "TRADEMARKS.md", "THIRD_PARTY_NOTICES.md", "CONTRIBUTING.md", "CLA.md"):
    datas.append((os.path.join(ROOT, notice), "."))

# 动态导入较多的依赖，整包收集：
#   uvicorn  -> loop/protocol 子模块是运行时按名加载的
#   webview  -> 各平台后端 + JS 桥接资源文件
#   edge_tts -> 云端神经语音
#   pythonnet/clr_loader -> Windows 上 pywebview 用 .NET 互操作驱动 WebView2
for pkg in ("uvicorn", "websockets", "aiohttp", "webview", "edge_tts", "clr_loader", "pythonnet", "sherpa_onnx"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# 前端 web 资源全部打入，但排除用户录音目录 web/media（运行时写到 exe 旁边）
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
        rel = os.path.relpath(os.path.dirname(full), ROOT)  # web 或 web\assets ...
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
    excludes=["tkinter", "torch", "matplotlib"],
    noarchive=False,
)
a.datas += collect_binary_notices(a.pure, a.binaries, Path(ROOT), Path(workpath))
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Shulian",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(ROOT, "shulian.ico"),
)
