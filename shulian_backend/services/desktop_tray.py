"""Windows tray lifetime on the existing pywebview WinForms UI thread."""

import sys
from pathlib import Path


def _brand_icon_path() -> Path:
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return resource_root / "shulian.ico"


class DesktopTray:
    def __init__(self, window, exit_callback):
        self.window = window
        self.exit_callback = exit_callback
        self.icon = None
        self.menu = None
        self.brand_icon = None

    def start(self):
        from System import Action
        from System.Drawing import Icon, SystemIcons
        from System.Windows.Forms import ContextMenuStrip, NotifyIcon, ToolStripMenuItem

        def create():
            self.menu = ContextMenuStrip()
            show = ToolStripMenuItem("打开数恋")
            leave = ToolStripMenuItem("退出数恋")
            show.Click += self._show
            leave.Click += self._exit
            self.menu.Items.Add(show)
            self.menu.Items.Add(leave)
            self.icon = NotifyIcon()
            brand_icon = _brand_icon_path()
            if brand_icon.is_file():
                self.brand_icon = Icon(str(brand_icon))
            self.icon.Icon = self.brand_icon or self.window.native.Icon or SystemIcons.Application
            self.icon.Text = "数恋 · 后台运行"
            self.icon.ContextMenuStrip = self.menu
            self.icon.DoubleClick += self._show
            self.icon.Visible = True
            self.window.native.FormClosed += self._closed

        self.window.native.Invoke(Action(create))

    def _show(self, *_):
        self.window.show()
        self.window.restore()
        self.window.native.Activate()

    def _exit(self, *_):
        # destroy marshals to the UI thread; do not block that thread on close events.
        import threading
        threading.Thread(target=self.exit_callback, daemon=True).start()

    def _closed(self, *_):
        self.dispose()

    def dispose(self):
        if self.icon is not None:
            self.icon.Visible = False
            self.icon.Dispose()
            self.icon = None
        if self.brand_icon is not None:
            self.brand_icon.Dispose()
            self.brand_icon = None
        if self.menu is not None:
            self.menu.Dispose()
            self.menu = None
