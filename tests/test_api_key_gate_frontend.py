import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


class ApiKeyGateFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (WEB / "app.jsx").read_text(encoding="utf-8")
        cls.glass = (WEB / "glass.jsx").read_text(encoding="utf-8")
        cls.screens = (WEB / "screens.jsx").read_text(encoding="utf-8")
        cls.i18n = (WEB / "i18n.jsx").read_text(encoding="utf-8")
        cls.markup = (WEB / "index.html").read_text(encoding="utf-8")
        cls.styles = (WEB / "app.css").read_text(encoding="utf-8")
        cls.tray = (ROOT / "shulian_backend" / "services" / "desktop_tray.py").read_text(
            encoding="utf-8"
        )
        # 样式已从 index.html 抽到 app.css。CSS 断言沿用统一的「标记 + 样式」视图，
        # 免得为一次搬家改几十处断言；只针对文档结构的断言请用 self.markup。
        cls.index = cls.markup + "\n" + cls.styles

    def test_build_and_cache_versions_identify_the_gate_release(self):
        build_id = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))["buildId"]
        self.assertIn(f"const SHULIAN_BUILD_ID = '{build_id}'", self.app)
        self.assertIn(f'bundle/app.bundle.js?v={build_id}', self.markup)
        self.assertNotRegex(self.markup, r'<script[^>]+src=["\'][^"\']+\.jsx')

    def test_webview_native_password_reveal_is_hidden_when_custom_toggle_exists(self):
        for selector in (
            ".api-key-input-wrap input::-ms-reveal",
            ".api-key-input-wrap input::-ms-clear",
            ".ai-service-key-wrap input::-ms-reveal",
            ".ai-service-key-wrap input::-ms-clear",
        ):
            self.assertIn(selector, self.index)
        self.assertIn("display: none;", self.index)

    def test_approved_brand_icon_is_used_inside_and_desktop(self):
        self.assertTrue((ROOT / "shulian.ico").is_file())
        self.assertTrue((WEB / "shulian-brand-icon.png").is_file())
        self.assertGreater((WEB / "shulian-brand-icon.png").stat().st_size, 10_000)
        self.assertIn("const BrandIcon", self.glass)
        self.assertEqual(self.app.count("<BrandIcon"), 2)
        self.assertIn('rel="icon" type="image/png"', self.markup)
        for spec_name in ("shulian.spec", "shulian-onedir.spec"):
            spec = (ROOT / spec_name).read_text(encoding="utf-8")
            self.assertIn('icon=os.path.join(ROOT, "shulian.ico")', spec)
            self.assertIn('datas.append((os.path.join(ROOT, "shulian.ico"), "."))', spec)
        self.assertIn('return resource_root / "shulian.ico"', self.tray)
        self.assertIn("self.icon.Icon = self.brand_icon", self.tray)

    def test_noto_sans_sc_is_bundled_and_inherited_by_controls(self):
        fonts = WEB / "fonts"
        for name in (
            "NotoSansSC-Regular.otf",
            "NotoSansSC-Medium.otf",
            "LICENSE-NotoCJK.txt",
        ):
            self.assertTrue((fonts / name).is_file(), name)
        self.assertIn('@font-face', self.styles)
        self.assertIn('--font: "Noto Sans SC"', self.styles)
        self.assertIn('font-family: var(--font);', self.styles)
        self.assertIn('button, input, textarea, select { font-family: inherit; }', self.styles)

    def test_native_shell_has_themeable_titlebar_and_content_offset(self):
        self.assertIn("desktop-window-chrome${compact ? ' is-compact' : ''}", self.app)
        self.assertIn('pywebview-drag-region', self.app)
        self.assertIn("invoke('drag_window')", self.app)
        self.assertIn('window.pywebview?.api?.minimize_window', self.app)
        self.assertIn('const method = window.pywebview?.api?.set_window_mode', self.app)
        self.assertIn('requestNativeWindowMode(desiredWindowMode.current, false)', self.app)
        self.assertIn('.desktop-window-chrome { display: none; }', self.index)
        self.assertIn('html[data-native-shell="true"] #stage { inset: 38px 0 0; }', self.index)
        self.assertIn('.desktop-window-actions button.is-close:hover', self.index)
        titlebar = self.app.split('className={`desktop-window-chrome', 1)[1].split('</header>', 1)[0]
        self.assertNotIn('<BrandIcon', titlebar)
        self.assertNotIn('数恋 · 数字恋人', titlebar)
        self.assertIn("{!compact && (", titlebar)
        self.assertEqual(self.app.count("<DesktopWindowChrome compact />"), 2)

    def test_top_level_app_gates_main_app_before_local_initialization(self):
        self.assertIn("function MainApp({ aiConfig, onAiConfigChange, onAiModelChange, onAiRemoved, onAiLoggedOut, maintenance })", self.app)
        top_app = self.app.split("function App()", 1)[1].split(
            "let pendingRoleArchiveRoles", 1
        )[0]
        self.assertIn("status: 'checking'", top_app)
        self.assertIn("if (gate.status === 'ready')", top_app)
        self.assertIn("<MainApp", top_app)
        self.assertIn("<ApiKeyGate", top_app)
        self.assertNotIn("localStorage", top_app)
        self.assertIn("desiredWindowMode.current = 'main'", top_app)
        self.assertIn("desiredWindowMode.current = 'login'", top_app)
        self.assertIn("requestNativeWindowMode('main', !reduceMotion)", top_app)
        self.assertIn("pywebviewready", top_app)
        self.assertLess(top_app.index("if (gate.status === 'ready')"), top_app.index("<MainApp"))

    def test_gate_uses_only_the_backend_config_contract(self):
        top_app = self.app.split("function App()", 1)[1].split(
            "let pendingRoleArchiveRoles", 1
        )[0]
        self.assertGreaterEqual(top_app.count("/api/ai-config"), 3)
        self.assertIn("method: 'GET'", top_app)
        self.assertIn("method: 'PUT'", top_app)
        self.assertIn("method: 'DELETE'", top_app)
        self.assertIn("/api/ai-config/logout", top_app)
        self.assertIn("method: 'POST'", top_app)
        self.assertIn("JSON.stringify({ api_key: apiKey, remember })", top_app)
        self.assertIn("config: { ...payload, ready: true }", top_app)
        self.assertNotIn("configured: true, ready: true", top_app)
        self.assertIn("payload.configured === false", top_app)
        self.assertIn("payload.ready === true", top_app)
        self.assertIn("response.status === 401 ? 'missing' : 'error'", top_app)
        self.assertIn("response.status === 503", self.app)
        self.assertIn("payload?.detail?.message", self.app)

    def test_gate_form_auto_detects_provider_without_a_remember_toggle(self):
        gate = self.app.split("function ApiKeyGate", 1)[1].split(
            "function MainApp", 1
        )[0]
        self.assertIn("type={visible ? 'text' : 'password'}", gate)
        self.assertIn('autoComplete="off"', gate)
        self.assertIn("显示 API Key", gate)
        self.assertIn("隐藏 API Key", gate)
        self.assertIn("<I.eye size={19} />", gate)
        self.assertIn("placeholder={uiT('输入 API Key')}", gate)
        self.assertIn("aria-label={uiT('AI 服务 API Key')}", gate)
        self.assertNotIn('placeholder="sk-..."', gate)
        self.assertNotIn("setRemember", gate)
        self.assertNotIn("在此设备保存 API Key", gate)
        self.assertIn("onValidate(candidate)", gate)
        self.assertIn("const [providerLabel, setProviderLabel] = useS(uiT('自动识别'))", gate)
        self.assertIn("setProviderLabel(result.config?.provider_label || uiT('AI 服务'))", gate)
        self.assertIn("当前 AI 服务", gate)
        self.assertIn("providerState", gate)
        self.assertNotIn("安全连接", gate)
        self.assertNotIn("tabIndex={-1}", gate)
        self.assertNotIn("localStorage", gate)
        self.assertIn("正在验证", gate)
        self.assertIn("${providerLabel} 已连接，正在进入数恋", gate)
        self.assertIn("onConnected(result.config || {})", gate)
        self.assertIn("切换账号", gate)
        self.assertIn("清除已保存 Key", gate)
        self.assertIn("onRemove", gate)
        self.assertIn("window.confirm", gate)

    def test_settings_exposes_a_separate_ai_service_screen(self):
        settings = self.screens.split("function SettingsScreen", 1)[1].split(
            "function MePanel", 1
        )[0]
        ai_service = self.screens.split("function AiServiceScreen", 1)[1].split(
            "function SettingsScreen", 1
        )[0]
        self.assertIn("AI 服务", settings)
        self.assertIn('entry="ai-service"', settings)
        self.assertIn("onOpenAiService", settings)
        self.assertIn("切换账号", ai_service)
        self.assertIn("退出登录", ai_service)
        self.assertIn("失败时当前账号仍可继续使用", ai_service)
        self.assertIn("聊天、记忆和个人资料都会保留", ai_service)
        self.assertIn("不会写入浏览器存储、聊天记录或数恋备份", ai_service)
        self.assertNotIn("localStorage", ai_service)
        self.assertIn("kind === 'ai-service'", self.screens)
        self.assertIn("仅当前会话，关闭后需重新验证", self.screens)

    def test_ai_service_and_transport_failures_follow_the_interface_language(self):
        ai_service = self.screens.split("function AiServiceScreen", 1)[1].split(
            "function SettingsScreen", 1
        )[0]
        for marker in (
            "title={uiT('AI 服务')}",
            "uiT('连接管理')",
            "uiT('回复模型')",
            "uiT('切换账号')",
            "uiT(removing ? '正在退出…' : '退出登录')",
            "uiT('API Key 不会写入浏览器存储",
        ):
            self.assertIn(marker, ai_service)
        top_app = self.app.split("function App()", 1)[1].split(
            "let pendingRoleArchiveRoles", 1
        )[0]
        self.assertNotIn("message: '无法连接本机服务", top_app)
        self.assertGreaterEqual(
            top_app.count("uiT('无法连接本机服务，请确认数恋仍在运行。')"),
            5,
        )
        self.assertIn("'连接管理': 'Connection management'", self.i18n)
        self.assertIn("'回复模型': 'Reply model'", self.i18n)

    def test_failed_replacement_does_not_replace_the_ready_config(self):
        replace = self.app.split("const replaceApiKey", 1)[1].split(
            "const removeApiKey", 1
        )[0]
        self.assertIn("const result = await validateApiKey(apiKey)", replace)
        self.assertIn("if (result.ok) setGate", replace)
        self.assertNotIn("setGate", replace.split("if (result.ok)", 1)[0])

    def test_removing_key_returns_to_gate_without_touching_local_data(self):
        remove = self.app.split("const removeApiKey", 1)[1].split(
            "if (gate.status === 'ready')", 1
        )[0]
        self.assertIn("method: 'DELETE'", remove)
        self.assertIn("await transitionToLogin(", remove)
        self.assertIn("聊天、记忆和个人资料均已保留", remove)
        self.assertNotIn("localStorage", remove)
        self.assertNotIn("location.reload", remove)

    def test_logout_preserves_saved_key_and_is_separate_from_forgetting_it(self):
        logout = self.app.split("const logoutApiKey", 1)[1].split(
            "const removeApiKey", 1
        )[0]
        self.assertIn("/api/ai-config/logout", logout)
        self.assertIn("method: 'POST'", logout)
        self.assertIn("已保存的 API Key 会在下次启动时自动连接", logout)
        forget = self.app.split("const removeApiKey", 1)[1].split(
            "if (gate.status === 'ready')", 1
        )[0]
        self.assertIn("method: 'DELETE'", forget)
        self.assertIn("已清除保存的 API Key", forget)

    def test_gate_and_ai_service_share_existing_flat_visual_language(self):
        for selector in (
            ".api-gate-shell {",
            ".api-gate-card {",
            ".api-key-input-wrap input {",
            ".api-gate-recovery {",
            ".settings-row.is-link {",
            ".ai-service-summary {",
            ".ai-service-editor {",
        ):
            self.assertIn(selector, self.index)
        self.assertIn("background: #15161b", self.index)
        self.assertIn("border: 1px solid #2d2f36", self.index)
        self.assertIn('html[data-reduce-motion="true"] .api-gate-spinner,', self.index)
        self.assertIn(".fade-rise, .bubble-pop, .api-gate-spinner,", self.index)

    def test_gate_matches_the_approved_standalone_dark_window_hierarchy(self):
        gate = self.app.split("function ApiKeyGate", 1)[1].split(
            "function MainApp", 1
        )[0]
        self.assertIn('className="api-gate-brand-copy"', gate)
        self.assertIn('className="api-gate-provider"', gate)
        self.assertNotIn('className="api-gate-eyebrow"', gate)
        self.assertNotIn('className="api-gate-card-head"', gate)
        self.assertNotIn("你的数字恋人", gate)
        self.assertNotIn("输入你的 API Key，验证后即可进入数恋。", gate)
        self.assertNotIn('<label htmlFor="api-gate-key-input">', gate)
        self.assertNotIn('api-gate-remember', gate)
        self.assertIn("messageTone === 'error'", gate)
        self.assertIn("AI 服务 API Key", gate)
        for expected in (
            '--font: "Noto Sans SC"',
            'html[data-theme-resolved="light"] .api-gate-brand { color: #fff; }',
            '.api-gate-provider {',
            '.api-gate-provider-state.is-connected {',
            'width: min(100%, 410px)',
            'min-height: 100%',
            'justify-content: center',
            'padding: clamp(52px, 8vh, 72px) 44px 26px',
            'width: 58px;',
            'height: 58px;',
            '.desktop-window-chrome.is-compact',
        ):
            self.assertIn(expected, self.index)
        self.assertIn('.api-gate-feedback:empty { display: block; }', self.index)
        self.assertIn('html[data-theme-resolved="light"] .api-gate-brand {', self.index)
        self.assertIn('linear-gradient(180deg, #0d0d13 0%, #08090d 100%) !important;', self.index)
        self.assertEqual(self.styles.count("{"), self.styles.count("}"))

    def test_styles_live_in_app_css_and_index_only_links_them(self):
        self.assertIn('<link rel="stylesheet" href="app.css" />', self.markup)
        self.assertNotIn("<style>", self.markup)
        self.assertLess(len(self.markup), 12_000, "index.html 不应再内联样式")
        self.assertGreater(len(self.styles), 80_000)
        self.assertEqual(self.styles.count("{"), self.styles.count("}"))


from tests.role_fixtures import role_fixture_hooks
setUpModule, tearDownModule = role_fixture_hooks()


if __name__ == "__main__":
    unittest.main()
