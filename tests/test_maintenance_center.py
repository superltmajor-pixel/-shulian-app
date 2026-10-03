import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from maintenance import MaintenanceCoordinator, source_fingerprint


ROOT = Path(__file__).resolve().parents[1]


class MaintenanceCoordinatorTests(unittest.TestCase):
    def test_public_install_uses_download_mode_without_scanning_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            coordinator = MaintenanceCoordinator("0.26.0", "public-test")
            coordinator.job_path = root / "job.json"
            with mock.patch.object(coordinator, "_discover", return_value={
                "source_dir": root, "app_dir": root, "packager": None,
            }), mock.patch.object(coordinator, "public_release", return_value={
                "publicReleaseUrl": "https://github.com/example/app/releases", "publicReleaseReady": True,
            }), mock.patch("maintenance.source_fingerprint") as fingerprint, mock.patch("maintenance.subprocess.Popen") as launch:
                status = coordinator.status()
                self.assertEqual(status["updateMode"], "download")
                self.assertFalse(status["updateAvailable"])
                self.assertEqual(status["clientVersion"], "0.26.0")
                self.assertIn("下载页", status["reason"])
                self.assertFalse(coordinator.start_update()["ok"])
                fingerprint.assert_not_called()
                launch.assert_not_called()

    def test_download_link_requires_published_metadata_and_safe_url(self):
        with tempfile.TemporaryDirectory() as temp:
            metadata = Path(temp) / "release.json"
            coordinator = MaintenanceCoordinator("0.26.0", "test")
            with mock.patch.object(coordinator, "_resource_path", return_value=metadata), mock.patch("maintenance.webbrowser.open_new_tab", return_value=True) as browser:
                for url, ready in [("https://github.com/example/app/releases", False),
                                   ("file:///C:/test.exe", True),
                                   ("https://github.com.evil.invalid/example/app/releases", True),
                                   ("https://github.com/example/app/releases", "true")]:
                    metadata.write_text(json.dumps({"publicReleaseUrl": url, "publicReleaseReady": ready}))
                    self.assertFalse(coordinator.open_public_releases()["ok"])
                browser.assert_not_called()
                url = "https://github.com/example/app/releases"
                metadata.write_text(json.dumps({"publicReleaseUrl": url, "publicReleaseReady": True}))
                self.assertTrue(coordinator.open_public_releases()["ok"])
                browser.assert_called_once_with(url)
                browser.return_value = False
                self.assertEqual(coordinator.open_public_releases()["error"], "browser_open_failed")

    def make_layout(self, root: Path, source_version: str, client_version: str):
        source = root / "source"
        app_dir = root / "dist"
        source.mkdir()
        (source / "venv" / "Scripts").mkdir(parents=True)
        (source / "venv" / "Scripts" / "python.exe").write_bytes(b"")
        (source / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
        source_build = f"build-{source_version}"
        client_build = f"build-{client_version}"
        (source / "release.json").write_text(json.dumps({
            "productId": "shulian", "version": source_version, "buildId": source_build,
        }), encoding="utf-8")
        (app_dir / "_internal").mkdir(parents=True)
        (app_dir / "Shulian.exe").write_bytes(b"")
        (app_dir / "_internal" / "release.json").write_text(json.dumps({
            "productId": "shulian", "version": client_version, "buildId": client_build,
        }), encoding="utf-8")
        packager = root / "package-shulian-inplace.ps1"
        packager.write_text("# test\n", encoding="utf-8")
        (root / "packager.local.json").write_text(json.dumps({
            "repo": str(source), "appDir": str(app_dir),
        }), encoding="utf-8")
        return source, app_dir, packager

    def test_source_fingerprint_ignores_machine_agent_and_packager_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            feature = source / "feature.py"
            feature.write_text("VALUE = 1\n", encoding="utf-8")
            original = source_fingerprint(source)
            for relative in (".claude/launch.json", ".codex/page.html", ".agents/state.json",
                             ".playwright-cli/session.json", "packager.local.json"):
                local = source / relative
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_text("machine-specific configuration", encoding="utf-8")
            self.assertEqual(source_fingerprint(source), original)
            feature.write_text("VALUE = 2\n", encoding="utf-8")
            self.assertNotEqual(source_fingerprint(source), original)

    def test_newer_source_version_is_offered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, _, packager = self.make_layout(root, "0.24.6", "0.24.4")
            with mock.patch.dict(os.environ, {
                "SHULIAN_PACKAGER_PATH": str(packager), "LOCALAPPDATA": str(root / "local"),
            }, clear=False):
                status = MaintenanceCoordinator("0.24.4", "build-0.24.4").status()
            self.assertTrue(status["packagerReady"])
            self.assertEqual(status["updateMode"], "source")
            self.assertTrue(status["updateAvailable"])
            self.assertEqual(status["sourceVersion"], "0.24.6")

    def test_source_change_without_version_bump_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, app_dir, packager = self.make_layout(root, "0.24.6", "0.24.6")
            installed = {
                "schemaVersion": 1,
                "productId": "shulian",
                "version": "0.24.6",
                "buildId": "build-0.24.6",
                "sourceFingerprint": "0" * 64,
            }
            (app_dir / "_internal" / "maintenance-manifest.json").write_text(
                json.dumps(installed), encoding="utf-8",
            )
            self.assertNotEqual(source_fingerprint(source), installed["sourceFingerprint"])
            with mock.patch.dict(os.environ, {
                "SHULIAN_PACKAGER_PATH": str(packager), "LOCALAPPDATA": str(root / "local"),
            }, clear=False):
                status = MaintenanceCoordinator("0.24.6", "build-0.24.6").status()
            self.assertTrue(status["sourceChanged"])
            self.assertFalse(status["updateAvailable"])
            self.assertIn("版本号尚未递增", status["reason"])

    def test_source_mode_never_executes_uninstall(self):
        coordinator = MaintenanceCoordinator("0.24.6", "build")
        result = coordinator.prepare_uninstall(False, "卸载数恋")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "not_installed")

    def test_launcher_failure_does_not_leave_job_queued_at_one_percent(self):
        coordinator = MaintenanceCoordinator("0.25.4", "build")
        with tempfile.TemporaryDirectory() as temp:
            coordinator.job_path = Path(temp) / "update-status.json"
            coordinator.job_path.write_text(json.dumps({
                "status": "queued", "percent": 1, "stage": "queued",
            }), encoding="utf-8")

            class FailedProcess:
                def wait(self):
                    return 1

            coordinator._monitor_update_process(FailedProcess())
            job = json.loads(coordinator.job_path.read_text(encoding="utf-8"))
            self.assertEqual(job["status"], "failed")
            self.assertEqual(job["percent"], 0)
            self.assertIn("未能启动", job["message"])

    def test_old_queued_job_without_process_id_is_retryable(self):
        stale = {"status": "queued", "percent": 1, "startedAt": 1}
        self.assertFalse(MaintenanceCoordinator._job_is_alive(stale))
        self.assertTrue(MaintenanceCoordinator._job_is_alive({
            "status": "queued", "startedAt": time.time(),
        }))


class MaintenanceSurfaceTests(unittest.TestCase):
    def test_windows_power_shell_scripts_keep_utf8_bom(self):
        paths = [
            ROOT / "package-shulian-inplace.ps1",
            ROOT / "packaging" / "uninstaller" / "ShulianUninstaller.ps1",
        ]
        deployment_copy = ROOT.parent / "package-shulian-inplace.ps1"
        if deployment_copy.exists():
            paths.append(deployment_copy)
        for path in paths:
            self.assertEqual(path.read_bytes()[:3], b"\xef\xbb\xbf", path.as_posix())

    def test_frontend_exposes_progress_and_explicit_uninstall_confirmation(self):
        app = (ROOT / "web" / "app.jsx").read_text(encoding="utf-8")
        screens = (ROOT / "web" / "screens.jsx").read_text(encoding="utf-8")
        self.assertIn("get_maintenance_status", app)
        self.assertIn("start_source_update", app)
        self.assertIn("后台更新中", app)
        self.assertIn("uiT('输入“{text}”确认'", screens)
        self.assertIn("uninstallConfirmationText", screens)
        self.assertIn("同时删除全部本机数据", screens)

    def test_packager_reports_machine_readable_progress(self):
        packager = (ROOT / "package-shulian-inplace.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("Write-UpdateProgress 22 'packaging'", packager)
        self.assertIn("Write-UpdateProgress 100 'completed'", packager)
        self.assertIn("scripts\\write-maintenance-manifest.py", packager)

    def test_update_process_control_is_path_scoped_and_waits_for_exit(self):
        packager = (ROOT / "package-shulian-inplace.ps1").read_text(encoding="utf-8-sig")
        updater = (ROOT / "packaging" / "updater" / "ShulianUpdater.ps1").read_text(
            encoding="utf-8-sig",
        )

        self.assertIn("function Get-TargetClientProcesses", packager)
        self.assertIn("[StringComparison]::OrdinalIgnoreCase", packager)
        self.assertIn("Wait-TargetClientExit 8", packager)
        self.assertNotIn("if (Get-Process -Name 'Shulian'", packager)

        self.assertIn("function Get-ShulianProcesses([string]$TargetAppDir)", updater)
        self.assertIn("[StringComparison]::OrdinalIgnoreCase", updater)
        self.assertIn("Wait-ShulianExit $TargetAppDir 8", updater)
        self.assertIn("Stop-Shulian $AppDir", updater)
        self.assertIn("Remove-Item Env:\\SHULIAN_BUILD_ID", updater)
        self.assertIn("servedBuild=$servedBuildId", updater)

    def test_updater_rebuilds_desktop_shortcut_with_brand_icon(self):
        updater = (ROOT / "packaging" / "updater" / "ShulianUpdater.ps1").read_text(
            encoding="utf-8-sig",
        )
        self.assertIn("function Refresh-ShulianDesktopShortcut", updater)
        self.assertIn("_internal\\shulian.ico", updater)
        self.assertIn("数字恋人.lnk", updater)
        self.assertIn("$shortcut.IconLocation = \"$icon,0\"", updater)
        self.assertGreaterEqual(updater.count("Refresh-ShulianDesktopShortcut $AppDir"), 2)
        self.assertIn("SHChangeNotify", updater)
        shortcut_helper = updater.split(
            "function Refresh-ShulianDesktopShortcut", 1,
        )[1].split("$AppDir = Resolve-FullPath", 1)[0]
        self.assertIn("Write-Warning", shortcut_helper)
        self.assertIn("return $false", shortcut_helper)
        self.assertGreaterEqual(shortcut_helper.count("catch"), 4)

    def test_frozen_client_owns_its_release_build_identity(self):
        desktop = (ROOT / "desktop.py").read_text(encoding="utf-8")
        main = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn('os.environ["SHULIAN_BUILD_ID"] = _BUILD_ID', desktop)
        self.assertNotIn('os.environ.setdefault("SHULIAN_BUILD_ID", _BUILD_ID)', desktop)
        self.assertIn("_DEFAULT_BUILD_ID\n    if _FROZEN", main)


from tests.role_fixtures import role_fixture_hooks
setUpModule, tearDownModule = role_fixture_hooks()


if __name__ == "__main__":
    unittest.main()
