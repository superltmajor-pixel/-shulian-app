"""Run the complete offline regression suite against disposable app data."""
from __future__ import annotations

import io
import ipaddress
import logging
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="shulian-quality-") as temporary:
        root = Path(temporary)
        paths = {
            "LOCALAPPDATA": root,
            "SHULIAN_STATE_DB": root / "state.sqlite3",
            "SHULIAN_CREDENTIALS_FILE": root / "credentials.bin",
            "SHULIAN_AI_PREFERENCES_FILE": root / "ai-preferences.json",
            "SHULIAN_ROLE_LIBRARY_DIR": root / "role-library",
            "SHULIAN_LOG_DIR": root / "logs",
            "SHULIAN_VOICE_DIR": root / "media",
            "SHULIAN_STORAGE_DIR": root / "webview-data",
        }
        for key, value in paths.items():
            os.environ[key] = str(value)
        os.environ["PYTHON_DOTENV_DISABLED"] = "1"
        for key in list(os.environ):
            if key.endswith("_API_KEY"):
                os.environ.pop(key)

        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex

        def local_connection(original):
            def connect(sock, address):
                # Windows asyncio uses loopback sockets internally. Never
                # connect to the installed app or any upstream paid service.
                try:
                    allowed = ipaddress.ip_address(address[0]).is_loopback and address[1] != 8770
                except (ValueError, TypeError, IndexError):
                    allowed = False
                if not allowed:
                    raise RuntimeError("Offline tests must mock external services")
                return original(sock, address)
            return connect

        try:
            with patch.object(socket.socket, "connect", local_connection(original_connect)), \
                 patch.object(socket.socket, "connect_ex", local_connection(original_connect_ex)):
                suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
                output = io.StringIO()
                result = unittest.TextTestRunner(stream=output, verbosity=0).run(suite)
                if not result.wasSuccessful():
                    if "--verbose" in sys.argv:
                        print(output.getvalue())
                    for test, error in result.failures + result.errors:
                        print(f"FAIL {test.id()}: {error.splitlines()[-1][:260]}")
                print(f"Quality: {result.testsRun} tests; {len(result.failures)} failures; "
                      f"{len(result.errors)} errors; {len(result.skipped)} skipped")
                return 0 if result.wasSuccessful() else 1
        finally:
            logging.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
