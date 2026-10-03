import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


class CharacterAccentThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (WEB / "app.jsx").read_text(encoding="utf-8")
        cls.chat = (WEB / "chat.jsx").read_text(encoding="utf-8")
        cls.screens = (WEB / "screens.jsx").read_text(encoding="utf-8")
        cls.data = (WEB / "data.jsx").read_text(encoding="utf-8")
        cls.glass = (WEB / "glass.jsx").read_text(encoding="utf-8")
        cls.markup = (WEB / "index.html").read_text(encoding="utf-8")
        cls.styles = (WEB / "app.css").read_text(encoding="utf-8")
        # 样式已从 index.html 抽到 app.css。CSS 断言沿用统一的「标记 + 样式」视图，
        # 免得为一次搬家改几十处断言；只针对文档结构的断言请用 self.markup。
        cls.index = cls.markup + "\n" + cls.styles
        cls.desktop = (ROOT / "desktop.py").read_text(encoding="utf-8")
        cls.packager = (ROOT / "package-shulian-inplace.ps1").read_text(encoding="utf-8")

    def test_local_roles_restore_their_own_palettes(self):
        from tests.role_fixtures import frontend_profiles, load_frontend_roles
        profiles = frontend_profiles()
        actual = load_frontend_roles(profiles)
        self.assertEqual(actual['palettes'], {p['id']: p['accent'] for p in profiles})
        self.assertEqual(load_frontend_roles([])['palettes'], {})

    def test_visible_character_drives_all_accent_tokens(self):
        self.assertIn("const accentCharacterId =", self.app)
        for source in (
            "viewingSession?.charId",
            "profileCharId",
            "historyCharId",
            "videoId",
            "voiceId",
            "chatId",
            "loverArchive?.charId",
            "currentId",
        ):
            self.assertIn(source, self.app)
        self.assertIn("const palette = CHARACTER_ACCENTS[accentCharacterId] || {", self.app)
        for token, value in (
            ("--accent", "palette.accent"),
            ("--accent-2", "palette.accent2"),
            ("--accent-3", "palette.accent3"),
            ("--accent-ink", "palette.ink"),
        ):
            self.assertIn(f"root.setProperty('{token}', {value})", self.app)
        self.assertIn("[accentCharacterId, t.glassIntensity, t.aurora]", self.app)

    def test_manual_accent_picker_no_longer_competes_with_character(self):
        self.assertNotIn('<TweakSection label="主题色" />', self.app)
        self.assertNotIn('<TweakColor label="强调色"', self.app)
        self.assertNotIn('"accent":', self.app.split("}/*EDITMODE-END*/", 1)[0])

    def test_message_list_selected_row_tracks_open_chat_and_uses_accent(self):
        block = self.screens.split("function MessagesScreen", 1)[1].split(
            "function CharacterProfilePanel", 1
        )[0]
        self.assertEqual(self.app.count("activeChatId={chatId}"), 2)
        self.assertIn("activeChatId = null", block.split(")", 1)[0])
        self.assertIn("const selected = c.id === activeChatId", block)
        self.assertIn("message-list-item${selected ? ' is-selected' : ''}", block)
        self.assertIn("aria-current={selected ? 'page' : undefined}", block)
        for selector in (
            ".message-list-item:hover",
            ".message-list-item:active",
            ".message-list-item.is-selected",
            ".message-list-item:focus-visible",
        ):
            self.assertIn(selector, self.index)
        self.assertIn("inset 3px 0 0 var(--accent)", self.index)
        self.assertIn("var(--accent-2)", self.index.split(".message-list-item.is-selected", 1)[1])

    def test_desktop_messages_remove_duplicate_heading_and_restore_a_real_conversation(self):
        block = self.screens.split("function MessagesScreen", 1)[1].split(
            "function CharacterProfilePanel", 1
        )[0]
        self.assertNotIn('className="messages-panel-heading"', block)
        self.assertIn("hasConversationMessages", block)
        self.assertIn("没有找到相关会话", block)
        self.assertNotIn("'暂无消息'", block)
        self.assertIn("pickDesktopConversationId", self.screens)
        self.assertIn("localStorage.setItem('sl_last_chat', id)", self.app)
        self.assertIn("tab !== 'messages'", self.app)
        self.assertNotIn("选择一个会话", self.app)
        self.assertNotIn("从左侧选择一位恋人", self.app)

    def test_primary_interactions_use_theme_variables(self):
        themed = self.chat + self.screens
        self.assertGreaterEqual(themed.count("linear-gradient(135deg, var(--accent), var(--accent-2))"), 8)
        switch_css = self.index.split(".settings-switch.is-on", 1)[1].split("}", 1)[0]
        self.assertIn("linear-gradient(90deg, var(--accent), var(--accent-2))", switch_css)
        for stale in (
            "linear-gradient(135deg, oklch(0.78 0.15 350), oklch(0.72 0.15 320))",
            "linear-gradient(135deg, oklch(0.74 0.15 350), oklch(0.68 0.15 320))",
            "linear-gradient(90deg, oklch(0.82 0.13 350), oklch(0.78 0.13 295))",
        ):
            self.assertNotIn(stale, themed)

    def test_home_character_window_and_sidebar_account_entry_are_wired(self):
        home = self.screens.split("function HomeScreen", 1)[1].split("function btn", 1)[0]
        for class_name in (
            'home-hero-copy',
            'home-hero-meta',
            'home-hero-info',
            'home-hero-mood',
            'home-hero-actions',
            'home-form-dots',
            'home-form-dot',
        ):
            self.assertIn(class_name, home)
        self.assertNotIn("<Ring value={c.intimacy / 10}", home)
        self.assertNotIn('home-form-switcher', home)
        self.assertIn('aria-label={`切换至${f.label}`}', home)
        self.assertIn('aria-pressed={on}', home)
        self.assertIn('onClick={() => setForm(i)}', home)
        self.assertIn('className="glass bubble-pop greet-bubble home-greeting-bubble"', home)
        self.assertIn("aria-label={uiT('回复{name}的消息', { name: c.name })}", home)
        self.assertEqual(home.count('openMessagesChat(c.id)'), 1)
        self.assertNotIn('openChat(c.id)', home)
        self.assertNotIn('title="点一下，回她一句"', home)
        self.assertNotIn('找 TA 聊天', home)
        self.assertIn('className="home-voice-action"', home)
        self.assertIn("aria-label={uiT('和{name}语音', { name: c.name })}", home)
        greeting_css = self.index.split('.home-greeting-bubble {', 1)[1].split('}', 1)[0]
        self.assertIn('border-radius: 18px', greeting_css)
        self.assertIn('border-top-left-radius: 6px', greeting_css)
        greet_button_css = self.index.split('.greet-bubble {', 1)[1].split('}', 1)[0]
        self.assertIn('cursor: pointer', greet_button_css)
        self.assertIn('.greet-bubble:focus-visible', self.index)
        self.assertIn('.home-hero-actions .home-voice-action', self.index)
        self.assertIn('.home-form-dot.is-active', self.index)
        self.assertNotIn("left: 40%", self.index)
        self.assertIn("left: 0", self.index)
        self.assertIn("width: 100%", self.index)
        self.assertIn("hero-media-button${isContained ? ' is-contain' : ''}", self.screens)
        self.assertIn('function sampleHeroPalette(image)', self.screens)
        self.assertIn('onPalette?.(sampleHeroPalette(event.currentTarget))', self.screens)
        self.assertIn('mixRgb(tone, [12, 14, 18], .56)', self.screens)
        self.assertIn("'--hero-tone': heroPalette.tone", home)
        self.assertIn('.hero-media-button.is-contain', self.index)
        self.assertIn('mix-blend-mode: multiply', self.index)
        self.assertIn('width: 66%', self.index)
        self.assertIn('right: 22px', self.index)
        self.assertNotIn("desktop-account-button", self.glass)
        self.assertIn("desktop-settings-button", self.glass)
        self.assertIn("desktop-sidebar-profile", self.glass)
        self.assertIn("desktop-sidebar-toggle", self.glass)
        self.assertIn("I.panelLeft", self.glass)
        self.assertIn("desktop-sidebar-collapsed-profile", self.glass)
        self.assertIn("desktop-account-dock", self.glass)
        self.assertIn("desktop-account-menu", self.glass)
        self.assertIn('aria-haspopup="menu"', self.glass)
        self.assertIn("<BrandIcon size={30}", self.glass)
        self.assertIn("sl_sidebar_collapsed", self.glass)
        self.assertIn("width: collapsed ? 56 : 196", self.glass)
        sidebar = self.glass.split("function SideBar", 1)[1].split("const Aurora", 1)[0]
        phone = self.glass.split("function Phone", 1)[1].split("function TabBar", 1)[0]
        tabbar = self.glass.split("function TabBar", 1)[1].split("Object.assign(window", 1)[0]

        self.assertNotIn("label: '我的'", sidebar)
        self.assertNotIn("label: '我的'", tabbar)
        self.assertIn('className="mobile-account-entry"', tabbar)
        self.assertIn("aria-label={uiT('打开账户菜单')}", tabbar)
        self.assertIn('onOpenAccount', tabbar)
        self.assertIn('onOpenSettings', tabbar)
        self.assertIn('<UserProfileAvatar profile={userProfile}', tabbar)
        self.assertIn('onOpenAccount={onOpenAccount}', phone)
        self.assertIn('onOpenSettings={onOpenSettings}', phone)
        self.assertIn(".desktop-sidebar.is-collapsed { width: 56px !important; }", self.index)
        self.assertIn("!collapsed && <span", self.glass)
        self.assertIn("userProfile={userProfile}", self.app)
        self.assertIn("<UserProfileAvatar profile={userProfile}", self.glass)
        self.assertIn("onOpenAccount", self.glass)
        self.assertIn("onOpenSettings", self.glass)
        self.assertEqual(self.glass.count("<UserProfileAvatar profile={userProfile}"), 3)
        self.assertIn("userProfile?.name", sidebar)
        self.assertNotIn("偏好与本机数据", sidebar)
        self.assertNotIn("数恋 v1.0 · 记忆与陪伴", sidebar)
        self.assertIn("aria-current={on ? 'page' : undefined}", self.glass)
        self.assertIn("setMeSub('profile')", self.app)
        self.assertIn("setMeSub('settings')", self.app)
        self.assertIn("function SettingsScreen", self.screens)
        self.assertIn("function ProfileScreen", self.screens)
        self.assertIn("def _native_titlebar_attributes(windows_build", self.desktop)

    def test_local_role_forms_preserve_banner_crop_and_separate_gallery(self):
        from tests.role_fixtures import frontend_profiles, load_frontend_roles
        profiles = frontend_profiles()
        actual = load_frontend_roles(profiles)
        for profile, role, forms in zip(profiles, actual['roster'], actual['forms']):
            self.assertEqual(role['gallery'], profile['gallery'])
            self.assertTrue(role['isCustomRole'])
            for expected, form in zip(profile['forms'], forms):
                for key in ('img', 'imgPos', 'imgFit'):
                    self.assertEqual(form[key], expected[key])
                self.assertNotIn(form['img'], role['gallery'])

    def test_desktop_layout_rechecks_width_after_login_and_native_resize(self):
        responsive_store = self.glass.split("const desktopLayoutStore", 1)[1].split("function UserProfileAvatar", 1)[0]
        phone = self.glass.split("function Phone", 1)[1].split("function TabBar", 1)[0]
        self.assertIn("React.useSyncExternalStore", responsive_store)
        self.assertIn("window.matchMedia(DESKTOP_LAYOUT_MEDIA_QUERY)", responsive_store)
        self.assertIn("window.addEventListener('resize', schedule)", responsive_store)
        self.assertIn("window.addEventListener('orientationchange', schedule)", responsive_store)
        self.assertIn("window.addEventListener('pageshow', schedule)", responsive_store)
        self.assertIn("document.addEventListener('visibilitychange', schedule)", responsive_store)
        self.assertIn("visualViewport?.addEventListener('resize', schedule)", responsive_store)
        self.assertIn("new ResizeObserver(schedule)", responsive_store)
        self.assertIn("[100, 300, 1000]", responsive_store)
        self.assertIn("resizeObserver?.disconnect()", responsive_store)
        self.assertIn("const wide = useWideLayout();", phone)

        main_app = self.app.split("function MainApp(", 1)[1].split("// ── screen routing ──", 1)[0]
        self.assertIn("const wide = useWideLayout();", main_app)
        self.assertNotIn("matchMedia('(min-width: 769px)')", self.app)
        self.assertEqual(self.glass.count("window.matchMedia(DESKTOP_LAYOUT_MEDIA_QUERY)"), 1)
        self.assertIn("const isDesktopMsg = wide && tab === 'messages'", self.app)
        self.assertIn("transition?.source === 'message-list'", self.app)
        self.assertIn("source: 'message-list'", self.app)

    def test_default_css_matches_sample_a_and_assets_are_cache_busted(self):
        for value in (
            "--accent:   oklch(0.72 0.18 305)",
            "--accent-2: oklch(0.68 0.20 350)",
            "--accent-3: oklch(0.80 0.11 290)",
            "--accent-ink: oklch(0.42 0.16 320)",
        ):
            self.assertIn(value, self.index)
        release = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        manifest = json.loads((WEB / "bundle/manifest.json").read_text(encoding="utf-8"))
        build_id = release["buildId"]
        self.assertIn(f"const SHULIAN_BUILD_ID = '{build_id}'", self.app)
        self.assertIn(f'bundle/app.bundle.js?v={build_id}', self.markup)
        self.assertNotRegex(self.markup, r'<script[^>]+src=["\'][^"\']*\.jsx')
        self.assertEqual(manifest["buildId"], build_id)
        bundle = (WEB / "bundle" / manifest["bundle"]).read_bytes()
        self.assertEqual(hashlib.sha256(bundle).hexdigest(), manifest["bundleSha256"])
        self.assertEqual(len(bundle), manifest["bundleBytes"])

    def test_home_voice_action_uses_visible_character_gradient(self):
        voice_css = self.index.split('.home-voice-action {', 1)[1].split('}', 1)[0]
        self.assertIn('linear-gradient(135deg, var(--accent), var(--accent-2))', voice_css)
        self.assertIn('color: #fff !important', voice_css)
        self.assertIn('.home-voice-action:hover', self.index)
        self.assertIn('.home-voice-action:focus-visible', self.index)
        self.assertIn("root.setProperty('--accent', palette.accent)", self.app)

    def test_voice_transcript_is_opt_in_and_toggled_by_context_menu(self):
        voice = self.chat.split("function VoiceBubble", 1)[1].split("function Bubble", 1)[0]
        self.assertIn("const [showTranscript, setShowTranscript] = useStateC(false)", voice)
        self.assertIn("event.preventDefault()", voice)
        self.assertIn("setShowTranscript(open => !open)", voice)
        self.assertEqual(voice.count("onContextMenu={toggleTranscript}"), 2)
        self.assertEqual(voice.count("showTranscript && message.transcript &&"), 2)
        self.assertNotIn("{message.transcript && (", voice)
        self.assertIn("onClick={togglePlayback}", voice)
        self.assertIn("左键播放 · 右键显示或收起文字", voice)

    def test_desktop_glass_is_flat_and_opaque(self):
        self.assertIn('Desktop uses opaque, flat surfaces instead of liquid glass.', self.index)
        self.assertIn('backdrop-filter: none !important', self.index)
        self.assertIn('.glass::after { content: none; display: none; }', self.index)
        self.assertIn('className={`desktop-sidebar', (WEB / "glass.jsx").read_text(encoding="utf-8"))

    def test_conversation_uses_narrow_rail_without_recommended_replies(self):
        for class_name in (
            'desktop-chat-rail',
            'desktop-chat-message-rail',
            'desktop-chat-message-row is-me',
            'desktop-chat-message-row is-her',
            'desktop-chat-turn-body',
        ):
            self.assertIn(class_name, self.chat)
        self.assertIn('.desktop-chat-rail { width: min(100%, 760px); }', self.index)
        self.assertIn('width: min(100%, 560px)', self.index)
        self.assertIn('width: min(100%, 420px)', self.index)
        self.assertNotIn('desktop-chat-suggestion', self.chat)
        self.assertNotIn('suggestions.map', self.chat)
        self.assertNotIn("label: '换一批'", self.chat)

    def test_selected_message_card_injects_character_color_into_chat_frame(self):
        for class_name in (
            'desktop-chat-frame',
            'desktop-chat-frame-injection',
            'desktop-chat-bridge',
        ):
            self.assertIn(class_name, self.chat)
        self.assertIn('@keyframes chatFrameInject', self.index)
        self.assertNotIn('.message-list-item.is-selected::after', self.index)
        self.assertIn('originOffsetY', self.screens)
        self.assertIn("--chat-stage-inset-top: 0px", self.index)
        bridge_css = self.index.split('.desktop-chat-bridge {', 1)[1].split('}', 1)[0]
        self.assertIn("display: none", bridge_css)
        bridge_keyframes = self.index.split('@keyframes chatBridgeInject', 1)[1].split('@keyframes', 1)[0]
        self.assertIn('100% { opacity: 0;', bridge_keyframes)
        self.assertIn("source: 'message-list'", self.screens)
        self.assertIn('originY', self.app)

    def test_chat_frame_injection_is_limited_to_message_list_entry(self):
        open_chat = self.app.split("const openChat", 1)[1].split("const openLoverArchive", 1)[0]
        self.assertIn("const shouldInject = transition?.source === 'message-list'", open_chat)
        self.assertIn("setChatInjection(null)", open_chat)
        self.assertIn("source: 'message-list'", open_chat)
        self.assertIn("const showChatFrameInjection = injection?.source === 'message-list'", self.chat)
        self.assertIn("{showChatFrameInjection && <>", self.chat)

    def test_text_chat_buffers_sse_before_revealing_verified_reply(self):
        self.assertIn('async function readChatStream(res, onStatus)', self.app)
        self.assertIn("Accept: 'text/event-stream'", self.app)
        self.assertIn('stream: true', self.app)
        self.assertIn("streaming: true", self.app)
        self.assertIn("streaming: false", self.app)
        self.assertIn('desktop-chat-stream-caret', self.chat)
        stream = self.app.split('async function readChatStream', 1)[1].split('async function revealVerifiedReply', 1)[0]
        self.assertIn("reply += payload", stream)
        self.assertIn("return reply", stream)
        self.assertIn("onStatus?.(status)", stream)
        self.assertIn("eventName === 'error'", stream)
        self.assertNotIn("onText", stream)
        self.assertIn('await new Promise(resolve => setTimeout(resolve, delay))', self.app)
        self.assertIn('await readChatStream(res, status => applyLiveStatus(id, status))', self.app)
        self.assertIn('await revealVerifiedReply(', self.app)
        self.assertIn('const queueStreamPaint = (partial) =>', self.app)
        self.assertIn('window.setTimeout(flushQueuedStream, 48)', self.app)
        self.assertIn('window.clearTimeout(streamFlushTimer)', self.app)
        self.assertIn('requestAnimationFrame(() =>', self.chat)
        self.assertIn('onScroll={trackScrollPosition}', self.chat)
        self.assertIn('overflow-anchor: none', self.index)
        # Execute the actual parser with byte-split UTF-8/SSE frames, without a server.
        parser = "async function readChatStream" + stream
        probe = r"""
const assert = require('node:assert/strict');
function response(text) {
  const bytes = new TextEncoder().encode(text);
  let offset = 0;
  return { body: { getReader: () => ({ read: async () =>
    offset < bytes.length
      ? { value: bytes.slice(offset, ++offset), done: false }
      : { done: true }
  }) } };
}
(async () => {
  const statuses = [];
  const result = await readChatStream(response(
    'event: status\r\ndata: {"scene":"rest"}\r\n\r\n' +
    'data: 你好\n\ndata: 世界\n\ndata: [DONE]\n\ndata: ignored\n\n'
  ), status => statuses.push(status));
  assert.equal(result, '你好世界');
  assert.deepEqual(statuses, [{scene: 'rest'}]);
  assert.equal(await readChatStream(response('data: tail')), 'tail');
  await assert.rejects(readChatStream(response('event: error\ndata: unavailable\n\n')), /unavailable/);
  await assert.rejects(readChatStream({}), /不支持流式回复/);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run(
            ["node", "-"], input=parser + probe, text=True, encoding="utf-8",
            capture_output=True, timeout=15, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


    def test_lover_cards_open_archive_instead_of_mounting_chat(self):
        gallery = self.screens.split("function GalleryScreen", 1)[1].split(
            "function fmtTime", 1
        )[0]
        self.assertIn("onOpenArchive(c.id, 'known')", gallery)
        self.assertNotIn("openChat(c.id)", gallery)
        self.assertIn("const [loverArchive, setLoverArchive]", self.app)
        self.assertIn("archiveId ? (", self.app)
        self.assertIn("<LoverArchiveScreen", self.app)
        self.assertIn("onBack={() => setLoverArchive(null)}", self.app)
        self.assertIn("setTab('messages')", self.app)
        self.assertIn("if (loverArchive?.charId) openMessagesChat(id)", self.app)

    def test_notification_entries_open_the_canonical_messages_route(self):
        route = self.app.split("const openMessagesChat", 1)[1].split("const openVoice", 1)[0]
        notification_handler = self.app.split("{notifOpen &&", 1)[1].split("onClose={() =>", 1)[0]
        home_route = self.app.split("if (tab === 'home' && ROSTER.length)", 1)[1].split("else if", 1)[0]
        self.assertIn("setTab('messages')", route)
        self.assertIn("openChat(id)", route)
        self.assertIn("openMessagesChat(charId)", notification_handler)
        self.assertNotIn("openChat(charId)", notification_handler)
        self.assertIn("openMessagesChat={openMessagesChat}", home_route)
        self.assertNotIn("openChat={openChat}", home_route)
        home = self.screens.split("function HomeScreen", 1)[1].split("function btn", 1)[0]
        greeting_click = home.split("onClick={() => {", 1)[1].split("}}", 1)[0]
        self.assertIn("onGreetingShown?.(greetingKey, greetText)", greeting_click)
        self.assertIn("openMessagesChat(c.id)", greeting_click)
        self.assertNotIn("onClick={() => openChat(c.id)}", home)

    def test_lover_archive_has_four_distinct_sections_without_home_or_chat_ui(self):
        archive = self.screens.split("function LoverArchiveScreen", 1)[1].split(
            "// ══════════════════ 恋人画廊", 1
        )[0]
        for label in ("她记得的你", "共同经历", "关系约定", "收藏记忆"):
            self.assertIn(label, archive)
        self.assertIn("aria-pressed={active}", archive)
        self.assertIn("聊天与通话统一留在“消息”", archive)
        for duplicate in ("home-hero-card", "home-stats-grid", "home-voice-action", "ChatThread", "openVoice"):
            self.assertNotIn(duplicate, archive)

    def test_lover_archive_directory_stays_visible_while_scrolling(self):
        directory_css = self.index.split('.lover-archive-index {', 1)[1].split('}', 1)[0]
        self.assertIn('position: sticky', directory_css)
        self.assertIn('top: 18px', directory_css)

    def test_home_heart_value_routes_to_archive_history(self):
        home = self.screens.split("function HomeScreen", 1)[1].split("function btn", 1)[0]
        self.assertIn("openArchive(c.id, 'history')", home)
        self.assertNotIn("trajOpen", home)
        self.assertNotIn("心动轨迹", home)

    def test_home_and_gallery_use_the_approved_compact_headers(self):
        home = self.screens.split("function HomeScreen", 1)[1].split("function btn", 1)[0]
        gallery = self.screens.split("function GalleryScreen", 1)[1].split(
            "function fmtTime", 1
        )[0]
        self.assertIn('className="fade-rise home-greeting-row"', home)
        self.assertIn('className="home-notification-button"', home)
        self.assertNotIn("now.getMonth()+1", home)
        self.assertNotIn("DISCOVER", gallery)
        self.assertNotIn("遇见 TA", gallery)
        self.assertNotIn("选择想陪伴的 TA", gallery)
        self.assertNotIn("搜索心动的 TA", gallery)
        self.assertIn('className="gallery-toolbar"', gallery)
        self.assertIn('className="gallery-search-trigger"', gallery)
        self.assertIn("aria-label={uiT('搜索恋人')}", gallery)

    def test_relationship_agreements_are_persisted_and_injected_into_ai_requests(self):
        self.assertIn("sl_relationship_${c.id}", self.app)
        self.assertIn("const memoryForRequest = (id) =>", self.app)
        self.assertGreaterEqual(self.app.count("memory_context: memoryForRequest(id)"), 7)
        memory = self.app.split("const memoryForRequest = (id) =>", 1)[1].split("// ── 对话历史", 1)[0]
        for marker in ("sanitizeRelationshipAgreement(", "relationshipAgreementsRef.current[id]",
                       "agreement.character_to_user_address", "agreement.user_to_character_address",
                       "agreement.boundary", "agreement.contact", "serializeMemoryContext({",
                       "relationship_facts: [...context.relationship_facts, ...rules]"):
            self.assertIn(marker, memory)
        self.assertIn("old_memory: memoriesRef.current[id] || ''", self.app)
        self.assertIn("onSaveAgreements", self.screens)
        self.assertIn("关系约定已保存，将影响之后的互动", self.app)

    def test_account_hub_only_routes_to_profile_and_settings(self):
        account = self.screens.split("function MeScreen", 1)[1].split(
            "function SettingsSwitch", 1
        )[0]
        self.assertIn("账户与应用", account)
        self.assertIn("我的资料", account)
        self.assertIn("设置", account)
        self.assertIn("本机账户", account)
        for duplicate in (
            "openVoice",
            "openHistory",
            "openProfile(c.id)",
            "亲密关系",
            "记忆中心",
            "数恋 Plus",
            "查看对话记录",
        ):
            self.assertNotIn(duplicate, account)
        self.assertIn("openProfile={() => openAccountPanel('profile'", self.app)
        self.assertIn("openSettings={() => openAccountPanel('settings'", self.app)
        for legacy in ("LegacyMeScreen", "LegacyMePanel", "function Toggle", "function SettingRow"):
            self.assertNotIn(legacy, self.screens)

    def test_profile_screen_is_a_focused_accessible_editor(self):
        profile = self.screens.split("function ProfileScreen", 1)[1].split(
            "const ACCOUNT_SETTINGS_DEFAULT", 1
        )[0]
        self.assertIn("title={uiT('我的资料')}", profile)
        self.assertIn('className="visually-hidden"', profile)
        self.assertIn("<UserAvatar profile={profileDraft}", profile)
        self.assertIn("avatarImg", profile)
        self.assertIn("onDirtyChange(dirty)", profile)
        self.assertIn("beforeunload", profile)
        self.assertIn("role={saveError ? 'alert' : 'status'}", profile)
        self.assertIn("保存失败，请检查本机存储空间后重试", profile)
        self.assertIn("file.size > 8 * 1024 * 1024", self.screens)
        self.assertIn("fr.onerror", self.screens)
        self.assertIn("img.onerror", self.screens)
        self.assertIn('className="profile-avatar-error" role="alert"', profile)
        self.assertIn("titleRef.current.focus", self.screens)
        self.assertIn("tabIndex={-1}", self.screens)
        self.assertIn("accountPanelTriggerRef", self.app)
        self.assertIn("data-account-entry", self.screens)
        self.assertIn("disabled={!dirty}", profile)
        self.assertIn("navigateFromProfile", self.app)
        self.assertIn("资料还没有保存，确定离开吗", self.app)
        self.assertIn("onProfileDirtyChange", self.app)
        for duplicate in ("快捷设置", "通知与提醒", "陪伴与隐私", "onOpenSub", "默认头像颜色", "colorOptions", "avatarHue", "profile-color"):
            self.assertNotIn(duplicate, profile)
        self.assertNotIn("avatarHue", self.app)
        self.assertNotIn("avatarHue", self.glass)
        self.assertNotIn(".profile-color-", self.index)

    def test_settings_screen_only_exposes_real_controls_and_data_actions(self):
        switch = self.screens.split("function SettingsSwitch", 1)[1].split(
            "function AccountPanelShell", 1
        )[0]
        settings = self.screens.split("function SettingsScreen", 1)[1].split(
            "function MePanel", 1
        )[0]
        self.assertIn('role="switch"', switch)
        self.assertIn("aria-checked={on}", switch)
        self.assertIn("主动消息", settings)
        self.assertIn("减少动态效果", settings)
        self.assertIn("导出备份", settings)
        self.assertIn("恢复备份", settings)
        self.assertNotIn("偏好与数据", settings)
        self.assertNotIn("AI、外观与陪伴", settings)
        self.assertNotIn('className="settings-content-head"', settings)
        self.assertNotIn("完整替换当前数恋数据", settings)
        self.assertNotIn("管理用于生成回复和长期记忆的个人 API Key", settings)
        self.assertNotIn("后台打包阶段会显示进度", settings)
        self.assertIn("readShulianStorage", settings)
        self.assertIn("已还原原数据", settings)
        self.assertIn("写入后的数据校验未通过", settings)
        self.assertIn("设置未保存，请检查本机存储空间后重试", settings)
        self.assertIn("清除所有数据", settings)
        self.assertIn("ACCOUNT_SETTINGS_DEFAULT = { nudge: true, reduceMotion: false, performanceMode: true, themeMode: 'system', language: 'zh-CN' }", self.screens)
        self.assertIn("dataset.performanceMode", self.app)
        self.assertIn("dataset.windowActive", self.app)
        self.assertIn('html[data-performance-mode="true"]', self.index)
        self.assertIn("function normalizeSettingBoolean", self.screens)
        for fake_toggle in ("dailyHi", "anniv", "sound", "nightMode"):
            self.assertNotIn(fake_toggle, settings)
        self.assertIn('html[data-reduce-motion="true"] *', self.index)

    def test_theme_mode_supports_light_dark_and_live_system_following(self):
        settings = self.screens.split("function SettingsScreen", 1)[1].split(
            "function MePanel", 1
        )[0]
        self.assertIn("themeMode: 'system'", self.screens)
        self.assertIn("function normalizeThemeMode", self.screens)
        self.assertIn('role="radiogroup"', settings)
        self.assertIn("['light', '浅色']", settings)
        self.assertIn("['dark', '深色']", settings)
        self.assertIn("['system', '跟随系统']", settings)
        self.assertIn("window.applyShulianTheme(next.themeMode)", settings)
        self.assertIn("prefers-color-scheme: dark", self.markup)
        self.assertIn("dataset.themeMode", self.markup)
        self.assertIn("dataset.themeResolved", self.markup)
        self.assertIn("shulianThemeMedia.addEventListener('change', syncSystemTheme)", self.markup)
        self.assertIn('html[data-theme-resolved="light"]', self.index)
        self.assertIn(".settings-theme-option.is-selected", self.index)

    def test_light_theme_keeps_text_visible_and_character_selection_tinted(self):
        gallery = self.screens.split("function GalleryScreen", 1)[1].split(
            "function fmtTime", 1
        )[0]
        messages = self.screens.split("function MessagesScreen", 1)[1].split(
            "function CharacterProfilePanel", 1
        )[0]
        self.assertIn("color: 'var(--ink)' }}>{c.name}", gallery)
        self.assertIn("background: 'var(--surface-secondary)'", gallery)
        self.assertIn('className="message-search-button"', messages)
        self.assertIn("aria-label={uiT('搜索会话')}", messages)

        search_css = self.index.split('html[data-theme-resolved="light"] .message-search-button {', 1)[1].split('}', 1)[0]
        self.assertIn('color: var(--ink-soft)', search_css)
        self.assertIn('background: #fff', search_css)
        self.assertIn("var(--hairline-color)", messages)
        self.assertIn("border: '2.5px solid var(--surface-primary)'", messages)
        self.assertIn('html[data-theme-resolved="light"] .home-hero-card .glass-strong', self.index)
        self.assertIn('html[data-theme-resolved="light"] .home-hero-mood', self.index)
        self.assertIn('html[data-theme-resolved="light"] .message-list-item.is-selected', self.index)
        light_selected = self.index.split('html[data-theme-resolved="light"] .message-list-item.is-selected {', 1)[1].split('}', 1)[0]
        self.assertIn("color-mix(in oklch, var(--accent) 13%, #fff)", light_selected)
        self.assertNotIn("#17181d", light_selected)
        self.assertIn('className="fade-rise app-toast"', self.app)
        self.assertIn("color: 'var(--ink)'", self.app.split('className="fade-rise app-toast"', 1)[1].split('</Glass>', 1)[0])
        self.assertIn("background: 'var(--surface-primary)'", self.screens)
        self.assertIn("let bg = 'var(--surface-secondary)'", self.screens)
        self.assertIn('className="msg-panel-list"', self.app)
        list_css = self.index.split('.msg-panel-list {', 1)[1].split('}', 1)[0]
        self.assertIn('border-right: 1px solid var(--hairline-color)', list_css)
        self.assertIn("background: isDesktopMsg ? 'var(--app-background)'", self.app)
        for selector in (
            'html[data-theme-resolved="light"] .account-panel-head {',
            'html[data-theme-resolved="light"] .profile-avatar-copy h2,',
            'html[data-theme-resolved="light"] .account-button-secondary {',
            'html[data-theme-resolved="light"] .settings-data-grid {',
            'html[data-theme-resolved="light"] .settings-data-grid > div {',
        ):
            self.assertIn(selector, self.index)
        self.assertIn('height: 352px', self.index)
        self.assertIn('right: 22px', self.index)
        self.assertIn('filter: blur(30px) saturate(1.12) brightness(.66)', self.index)
        self.assertIn('html[data-theme-resolved="light"] .settings-row.is-link:hover,', self.index)
        self.assertIn('html[data-theme-resolved="light"] .settings-row.is-link:hover .settings-row-icon {', self.index)
        self.assertNotIn('html[data-theme-resolved="light"] .settings-row-button:hover,', self.index)

    def test_interface_language_switch_is_persisted_and_applied_globally(self):
        i18n = (ROOT / "web" / "i18n.jsx").read_text(encoding="utf-8")
        build = (ROOT / "scripts" / "web-build-shared.mjs").read_text(encoding="utf-8")
        settings = self.screens.split("function SettingsScreen", 1)[1].split(
            "function MePanel", 1
        )[0]

        self.assertIn('"web/i18n.jsx"', build)
        self.assertIn("const UI_LANGUAGE_DEFAULT = 'zh-CN'", i18n)
        self.assertIn("value === 'en' ? 'en' : UI_LANGUAGE_DEFAULT", i18n)
        self.assertIn("window.applyShulianLanguage?.(next.language)", settings)
        self.assertIn("['zh-CN', '简体中文']", settings)
        self.assertIn("['en', 'English']", settings)
        self.assertIn("language: normalizeUiLanguage(raw?.language)", self.screens)
        self.assertIn("useUiLanguage()", self.app)
        self.assertIn("window.applyShulianLanguage", self.markup)
        self.assertIn("document.documentElement.lang", self.markup)
        self.assertIn("'数恋': 'Digital Companion'", i18n)
        self.assertIn("<span>{uiT('数恋')}</span>", self.glass)
        self.assertIn("uiT('后台更新到 v{version}'", settings)
        self.assertIn("uiT('由外部卸载助手在数恋退出后移除程序文件。默认保留聊天、记忆、媒体和 API 配置。')", settings)
        self.assertIn("uninstallText !== uninstallConfirmationText", settings)
        self.assertIn(".maintenance-uninstall > .account-button-danger", self.index)
        self.assertIn("window.confirm(uiT(\n      '后台构建并更新到数恋 v{version}？", self.app)
        self.assertIn("window.confirm(uiT('确定清除所有数恋本机数据吗？", self.app)
        self.assertIn("window.confirm(uiT('清空所有通知记录？'))", self.app)
        for label in ('关闭通知', '通知', '全部已读', '清空', '暂无通知'):
            self.assertIn(f"uiT('{label}')", self.screens)
        self.assertIn("'Clear all notification history?'", i18n)
        self.assertIn("uiT('当前仅渲染最近 {count} 条，完整记录仍保存在本机'", self.chat)
        self.assertIn("{uiT(cat.cat)}", self.chat)
        self.assertIn("{ id: 'known', label: uiT('她记得的你')", self.screens)
        self.assertIn("<h1>{c.name} · {uiT('二人档案')}</h1>", self.screens)
        self.assertIn("uiT('聊天与通话统一留在“消息”。')", self.screens)
        self.assertNotIn("<div><h2>她记得的你</h2>", self.screens)

    def test_account_surfaces_share_flat_layout_and_focus_states(self):
        for selector in (
            ".account-page {",
            ".account-profile-summary,",
            ".account-panel-shell {",
            ".settings-row {",
            ".settings-switch {",
            ".danger-zone {",
            ".account-nav-row:focus-visible,",
        ):
            self.assertIn(selector, self.index)
        self.assertIn("background: #15161b", self.index)
        self.assertIn("border: 1px solid #2d2f36", self.index)

    def test_packager_validates_archive_account_screens_and_cache_entry(self):
        self.assertIn("$builtScreens", self.packager)
        self.assertIn("$targetScreens", self.packager)
        self.assertIn("function LoverArchiveScreen", self.packager)
        self.assertIn("function ProfileScreen", self.packager)
        self.assertIn("function SettingsScreen", self.packager)
        self.assertIn("bundle/app.bundle.js?v=$expectedBuildId", self.packager)
        self.assertIn("$servedScreens.Contains('function LoverArchiveScreen')", self.packager)
        self.assertIn('$servedIndex.Contains("bundle/app.bundle.js?v=$expectedBuildId")', self.packager)
        self.assertIn('Select-String -LiteralPath $targetIndex -SimpleMatch "bundle/app.bundle.js?v=$expectedBuildId"', self.packager)
        self.assertIn("-not $servedScreens.Contains('默认头像颜色')", self.packager)
        self.assertIn("-not $servedIndex.Contains('.profile-color-')", self.packager)


from tests.role_fixtures import role_fixture_hooks
setUpModule, tearDownModule = role_fixture_hooks()


if __name__ == "__main__":
    unittest.main()
