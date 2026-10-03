import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ApiKeyPackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.desktop = (ROOT / "desktop.py").read_text(encoding="utf-8")
        cls.packager = (ROOT / "package-shulian-inplace.ps1").read_text(encoding="utf-8")
        cls.specs = {
            name: (ROOT / name).read_text(encoding="utf-8")
            for name in ("shulian.spec", "shulian-onedir.spec")
        }

    def test_pyinstaller_specs_never_bundle_dotenv(self):
        for name, source in self.specs.items():
            with self.subTest(spec=name):
                self.assertNotIn("env_file", source)
                self.assertNotIn("datas.append((env_file", source)
                self.assertNotIn("内置一份 .env", source)
                self.assertNotIn("含 DeepSeek key", source)
                self.assertIn("API Key 绝不进入 PyInstaller", source)

    def test_desktop_owns_fixed_origin_instead_of_reusing_http_service(self):
        self.assertIn('_PORT = int(os.environ.get("SHULIAN_PORT", "8770"))', self.desktop)
        self.assertIn('os.path.join(_LOG_DIR, "webview-data")', self.desktop)
        self.assertIn('_INSTANCE_MUTEX_NAME = r"Local\\ShulianDesktop-8770"', self.desktop)
        self.assertIn("CreateMutexW", self.desktop)
        self.assertIn("_ERROR_ALREADY_EXISTS = 183", self.desktop)
        self.assertIn("wintypes.BOOL", self.desktop)
        self.assertIn("wintypes.HANDLE", self.desktop)
        self.assertNotIn("ctypes.c_bool", self.desktop)
        self.assertIn("SO_EXCLUSIVEADDRUSE", self.desktop)
        self.assertIn("_LOGIN_WINDOW_SIZE = (520, 640)", self.desktop)
        self.assertIn("_MAIN_WINDOW_SIZE = (1040, 720)", self.desktop)
        self.assertIn("js_api=window_api", self.desktop)
        self.assertIn('listener.bind(("127.0.0.1", port))', self.desktop)
        self.assertIn("MessageBoxW", self.desktop)
        self.assertIn("数恋不会连接或复用这个未知服务", self.desktop)
        self.assertNotIn("def _port_is_ours", self.desktop)
        self.assertNotIn("reuse existing backend", self.desktop)
        self.assertNotIn("SO_REUSEADDR", self.desktop)

    def test_desktop_and_packager_share_api_key_gate_build(self):
        build_id = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))["buildId"]
        self.assertIn("from shulian_backend.version import APP_VERSION, BUILD_ID", self.desktop)
        self.assertIn("_BUILD_ID = BUILD_ID", self.desktop)
        self.assertIn(f"$expectedBuildId = '{build_id}'", self.packager)
        self.assertIn('bundle/app.bundle.js?v=$expectedBuildId', self.packager)

    def test_native_titlebar_uses_windows_build_supported_dwm_attributes(self):
        self.assertIn("def _native_titlebar_attributes(windows_build", self.desktop)
        self.assertIn("if windows_build >= 22000:", self.desktop)
        self.assertIn('"dark": (20, 1)', self.desktop)
        self.assertIn("attributes = _native_titlebar_attributes(windows_build)", self.desktop)
        self.assertNotIn('"border": set_attr(34', self.desktop)

    def test_desktop_uses_a_themeable_frameless_shell_instead_of_native_blue_chrome(self):
        self.assertIn("frameless=True", self.desktop)
        self.assertIn("easy_drag=False", self.desktop)
        self.assertIn("shadow=True", self.desktop)
        self.assertIn("private_mode=False", self.desktop)
        self.assertIn("storage_path=_STORAGE_DIR", self.desktop)
        self.assertIn("html=_startup_html()", self.desktop)
        self.assertIn("func=_finish_window_startup", self.desktop)
        self.assertIn("target=_bootstrap_backend", self.desktop)
        self.assertIn("window.load_url(", self.desktop)
        self.assertNotIn("webview.start(_apply_native_window_theme", self.desktop)
        for method in ("minimize_window", "drag_window", "toggle_maximize_window", "close_window"):
            self.assertIn(f"def {method}(self)", self.desktop)

    def test_packager_validates_gate_in_build_target_and_live_service(self):
        for marker in (
            "function ApiKeyGate",
            "function MainApp",
            "function AiServiceScreen",
            "/api/ai-config",
        ):
            self.assertGreaterEqual(self.packager.count(marker), 3, marker)
        self.assertIn("http://127.0.0.1:8770/openapi.json", self.packager)
        self.assertIn("$servedSchema.paths.'/api/ai-config'", self.packager)
        for method in ("get", "put", "delete"):
            self.assertIn(f"$aiConfigMethods -contains '{method}'", self.packager)
        self.assertNotIn("Create('http://127.0.0.1:8770/api/ai-config')", self.packager)

    def test_packager_rejects_bundled_env_and_migrates_only_legacy_key(self):
        self.assertIn("$builtBundledEnv = Join-Path $builtDir '_internal\\.env'", self.packager)
        self.assertIn("$builtRootEnv = Join-Path $builtDir '.env'", self.packager)
        self.assertIn("$targetBundledEnv = Join-Path $appDir '_internal\\.env'", self.packager)
        self.assertIn("Move-LegacyEnvironmentSettings $targetBundledEnv $targetRootEnv", self.packager)

        function = self.packager.split("function Remove-LegacyDeepSeekKey", 1)[1].split(
            "\ntry {", 1
        )[0]
        self.assertIn("[System.IO.File]::ReadAllLines($Path)", function)
        self.assertIn("DEEPSEEK_API_KEY", function)
        self.assertIn("Write-EnvironmentFileAtomic $Path $safeLines", function)
        self.assertNotIn("TTS_PROVIDER", function)
        self.assertNotIn("GPT_SOVITS", function)

        atomic_writer = self.packager.split("function Write-EnvironmentFileAtomic", 1)[1].split(
            "\nfunction Remove-LegacyDeepSeekKey", 1
        )[0]
        self.assertIn("[System.IO.File]::WriteAllLines", atomic_writer)
        self.assertIn("[System.IO.File]::Replace", atomic_writer)
        self.assertIn("[System.IO.File]::Move", atomic_writer)
        self.assertIn("$backup", atomic_writer)
        self.assertIn("Remove-Item -LiteralPath $backup -Force", atomic_writer)
        self.assertNotIn("::Replace($temporary, $Path, $null", atomic_writer)

        migration = self.packager.split("function Move-LegacyEnvironmentSettings", 1)[1].split(
            "\ntry {", 1
        )[0]
        self.assertIn("$safeBundledLines", migration)
        self.assertIn("DEEPSEEK_API_KEY", migration)
        self.assertIn("$knownNames", migration)
        self.assertIn("Write-EnvironmentFileAtomic $RootPath", migration)
        self.assertIn("Remove-Item -LiteralPath $BundledPath -Force", migration)

    def test_plaintext_cleanup_runs_after_copy_validation_before_launch(self):
        copy_at = self.packager.index("Copy-Item -LiteralPath $builtExe")
        hash_at = self.packager.index("$sourceHash =")
        target_gate_at = self.packager.index(
            "Select-String -LiteralPath $targetApp -SimpleMatch 'function ApiKeyGate'"
        )
        root_key_at = self.packager.index("Remove-LegacyDeepSeekKey $targetRootEnv", copy_at)
        cleanup_at = self.packager.index("Move-LegacyEnvironmentSettings $targetBundledEnv $targetRootEnv")
        launch_at = self.packager.index("Start-Process -FilePath $targetExe")
        self.assertLess(copy_at, hash_at)
        self.assertLess(hash_at, target_gate_at)
        self.assertLess(target_gate_at, root_key_at)
        self.assertLess(root_key_at, cleanup_at)
        self.assertLess(root_key_at, launch_at)

    def test_packager_keeps_only_the_internal_web_bundle(self):
        self.assertNotIn(
            "Copy-Item -Path (Join-Path $builtDir '_internal\\web\\*')",
            self.packager,
        )
        self.assertIn("$targetApp = Join-Path $appDir '_internal\\web\\app.jsx'", self.packager)
        self.assertIn("$legacyWeb = Join-Path $appDir 'web'", self.packager)
        self.assertIn("拒绝清理未验证的旧资源目录", self.packager)

    def test_desktop_python_syntax_is_valid(self):
        compile(self.desktop, str(ROOT / "desktop.py"), "exec")


if __name__ == "__main__":
    unittest.main()
