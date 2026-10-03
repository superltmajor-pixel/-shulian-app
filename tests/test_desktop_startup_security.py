import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import desktop


class DesktopStartupSecurityTests(unittest.TestCase):
    def test_health_probe_is_not_trusted_before_our_uvicorn_started(self):
        server = SimpleNamespace(started=False)
        server_thread = MagicMock()
        server_thread.is_alive.return_value = True

        with (
            patch("desktop.time.time", side_effect=[0.0, 0.0, 2.0]),
            patch("desktop.time.sleep"),
            patch("desktop.urllib.request.urlopen") as probe,
        ):
            ready = desktop._wait_until_ready(
                8770,
                server,
                server_thread,
                timeout=1.0,
            )

        self.assertFalse(ready)
        probe.assert_not_called()

    def test_bootstrap_rejects_import_failure_without_health_probe(self):
        bootstrap = desktop._BackendBootstrap()
        bootstrap.error = "import failed"
        bootstrap.loaded.set()
        server_thread = MagicMock()
        server_thread.is_alive.return_value = True

        with patch("desktop._wait_until_ready") as wait_ready:
            ready = desktop._wait_until_bootstrapped(
                8770,
                bootstrap,
                server_thread,
                timeout=1.0,
            )

        self.assertFalse(ready)
        wait_ready.assert_not_called()

    def test_bootstrap_delegates_to_owned_server_after_import(self):
        bootstrap = desktop._BackendBootstrap()
        bootstrap.server = SimpleNamespace(started=True)
        bootstrap.loaded.set()
        server_thread = MagicMock()
        server_thread.is_alive.return_value = True

        with patch("desktop._wait_until_ready", return_value=True) as wait_ready:
            ready = desktop._wait_until_bootstrapped(
                8770,
                bootstrap,
                server_thread,
                timeout=1.0,
            )

        self.assertTrue(ready)
        wait_ready.assert_called_once()


class DesktopWindowSizingTests(unittest.TestCase):
    class FakeWindow:
        def __init__(self, x=200, y=100, width=520, height=640):
            self.x = x
            self.y = y
            self.width = width
            self.height = height
            self.resize_calls = []
            self.move_calls = []
            self.restore_calls = 0
            self.maximize_calls = 0

        def restore(self):
            self.restore_calls += 1

        def maximize(self):
            self.maximize_calls += 1

        def resize(self, width, height):
            self.width = width
            self.height = height
            self.resize_calls.append((width, height))

        def move(self, x, y):
            self.x = x
            self.y = y
            self.move_calls.append((x, y))

    def test_login_and_main_modes_use_compact_wechat_like_sizes(self):
        screen = SimpleNamespace(x=0, y=0, width=1920, height=1080)
        window = self.FakeWindow()
        api = desktop._DesktopWindowApi(lambda: [screen])
        api.attach_window(window)

        main_result = api.set_window_mode("main")
        login_result = api.set_window_mode("login")

        self.assertEqual((main_result["width"], main_result["height"]), (1040, 720))
        self.assertEqual(window.resize_calls, [(1040, 720), (520, 640)])
        self.assertEqual(window.move_calls, [(440, 180), (700, 220)])
        self.assertEqual(window.restore_calls, 2)
        self.assertEqual((login_result["width"], login_result["height"]), (520, 640))

    def test_main_mode_clamps_to_a_small_screen_work_area(self):
        screen = SimpleNamespace(x=0, y=0, width=1366, height=768)
        window = self.FakeWindow()
        api = desktop._DesktopWindowApi(lambda: [screen])
        api.attach_window(window)

        result = api.set_window_mode("main")

        self.assertEqual((result["width"], result["height"]), (1040, 696))
        self.assertEqual(window.move_calls, [(163, 36)])

    def test_repeated_mode_does_not_override_user_position(self):
        screen = SimpleNamespace(x=0, y=0, width=1920, height=1080)
        window = self.FakeWindow()
        api = desktop._DesktopWindowApi(lambda: [screen])
        api.attach_window(window)

        api.set_window_mode("login")
        repeated = api.set_window_mode("login")

        self.assertTrue(repeated["unchanged"])
        self.assertEqual(len(window.resize_calls), 1)
        self.assertEqual(len(window.move_calls), 1)
        self.assertEqual(window.restore_calls, 1)

    def test_invalid_mode_is_rejected_without_resizing(self):
        window = self.FakeWindow()
        api = desktop._DesktopWindowApi(lambda: [])
        api.attach_window(window)

        result = api.set_window_mode("unexpected")

        self.assertFalse(result["ok"])
        self.assertEqual(window.resize_calls, [])

    def test_maximize_toggle_tracks_state_without_native_property(self):
        window = self.FakeWindow()
        api = desktop._DesktopWindowApi(lambda: [])
        api.attach_window(window)

        maximized = api.toggle_maximize_window()
        restored = api.toggle_maximize_window()

        self.assertEqual(maximized, {"ok": True, "maximized": True})
        self.assertEqual(restored, {"ok": True, "maximized": False})
        self.assertEqual(window.maximize_calls, 1)
        self.assertEqual(window.restore_calls, 1)

    def test_maximize_restore_keeps_saved_logical_size_on_scaled_displays(self):
        window = self.FakeWindow(x=220, y=100, width=1040, height=720)
        api = desktop._DesktopWindowApi(lambda: [])
        api.attach_window(window)

        with (
            patch.object(api, "_native_handle", return_value=123),
            patch.object(api, "_monitor_work_area", return_value=(0, 0, 1920, 1040)),
            patch.object(api, "_set_native_bounds") as set_native_bounds,
        ):
            maximized = api.toggle_maximize_window()
            restored = api.toggle_maximize_window()

        self.assertEqual(maximized, {"ok": True, "maximized": True})
        self.assertEqual(restored, {"ok": True, "maximized": False})
        set_native_bounds.assert_called_once_with(123, 0, 0, 1920, 1040)
        self.assertEqual(window.resize_calls, [(1040, 720)])
        self.assertEqual(window.move_calls, [(220, 100)])


class DesktopStartupSecurityContinuationTests(unittest.TestCase):

    def test_dead_server_thread_fails_before_any_health_probe(self):
        server = SimpleNamespace(started=True)
        server_thread = MagicMock()
        server_thread.is_alive.return_value = False

        with (
            patch("desktop.time.time", side_effect=[0.0, 0.0]),
            patch("desktop.urllib.request.urlopen") as probe,
        ):
            ready = desktop._wait_until_ready(
                8770,
                server,
                server_thread,
                timeout=1.0,
            )

        self.assertFalse(ready)
        probe.assert_not_called()

    def test_ready_requires_started_live_server_and_healthy_response(self):
        server = SimpleNamespace(started=True)
        server_thread = MagicMock()
        server_thread.is_alive.return_value = True
        response = MagicMock()
        response.__enter__.return_value.status = 200

        with (
            patch("desktop.time.time", side_effect=[0.0, 0.0]),
            patch("desktop.urllib.request.urlopen", return_value=response),
        ):
            ready = desktop._wait_until_ready(
                8770,
                server,
                server_thread,
                timeout=1.0,
            )

        self.assertTrue(ready)

    def test_health_response_is_rejected_if_our_server_thread_dies(self):
        server = SimpleNamespace(started=True)
        server_thread = MagicMock()
        server_thread.is_alive.side_effect = [True, False]
        response = MagicMock()
        response.__enter__.return_value.status = 200

        with (
            patch("desktop.time.time", side_effect=[0.0, 0.0, 2.0]),
            patch("desktop.urllib.request.urlopen", return_value=response),
        ):
            ready = desktop._wait_until_ready(
                8770,
                server,
                server_thread,
                timeout=1.0,
            )

        self.assertFalse(ready)


if __name__ == "__main__":
    unittest.main()
