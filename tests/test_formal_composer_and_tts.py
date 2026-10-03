import os
import unittest
from pathlib import Path
from unittest.mock import patch

from characters import ROSTER
from shulian_backend.schemas.api import ChatRequest
from shulian_backend.services import tts_service
from shulian_backend.services.context_compiler import compile_companion_messages
from voice_service import VoiceServiceManager


ROOT = Path(__file__).resolve().parents[1]


class FormalComposerAndTtsTests(unittest.TestCase):
    def test_mixed_composer_features_are_built(self):
        chat = (ROOT / "web" / "chat.jsx").read_text(encoding="utf-8")
        app = (ROOT / "web" / "app.jsx").read_text(encoding="utf-8")
        bundle = (ROOT / "web" / "bundle" / "app.bundle.js").read_text(encoding="utf-8")

        for marker in ("pendingImage", "handleComposerPaste", "转成文字", "发送原语音"):
            self.assertIn(marker, chat)
        for marker in (
            "const insertSticker = (emoji) =>",
            "composerInputRef.current",
            "setSelectionRange(nextCursor, nextCursor)",
            "选择后加入输入框，可继续编辑",
            "desktop-chat-actions-inner",
        ):
            self.assertIn(marker, chat)
        self.assertNotIn("onSend?.(`[[sticker:${emoji}]]`)", chat)
        self.assertIn("sendImageMessage = async (id, imageUrl, caption = '')", app)
        self.assertNotIn("origin: 'new-chat-opening'", app)
        self.assertNotIn("channel: 'new_chat'", app)
        for marker in ("图片已加入消息", "转成文字", "发送原语音", "选择后加入输入框"):
            self.assertIn(marker, bundle)

    def test_chat_subflows_and_memoized_messages_follow_the_interface_language(self):
        chat = (ROOT / "web" / "chat.jsx").read_text(encoding="utf-8")
        i18n = (ROOT / "web" / "i18n.jsx").read_text(encoding="utf-8")

        for marker in (
            "uiT('与 {name} 的对话'",
            "uiT('{count} 次会话'",
            "uiT('{count} 条消息'",
            "uiT('正在接通')",
            "uiT('{name} 正在说话'",
            "uiT('切换主画面和小画面')",
            "uiT('已读')",
            "uiT('正在生成回复')",
        ):
            self.assertIn(marker, chat)
        self.assertIn("language={currentUiLanguage()}", chat)
        self.assertIn("a.language !== b.language", chat)
        self.assertIn("currentUiLanguage() === 'en' ? 'en-US' : 'zh-CN'", chat)
        self.assertEqual(i18n.count("'待发送图片':"), 1)

    def test_new_chat_channel_is_valid(self):
        self.assertEqual(ChatRequest(message="开始新对话", channel="new_chat").channel, "new_chat")

    def test_chat_uses_one_adaptive_pacing_rule_while_special_entries_stay_brief(self):
        forbidden = (
            "日常即时消息通常 1—3 句",
            "日常可用 1—4 句",
            "普通问题或短消息优先用 1—3 句",
        )
        prompts = []
        for reply_speed in ("自然自适应", "甜蜜即时", "日常自然", "慢热含蓄"):
            compiled = compile_companion_messages(
                ROSTER["sample_a"],
                "今天想认真聊聊最近的感受。",
                [],
                live_status={
                    "source": "schedule",
                    "scene": "schedule",
                    "label": "日常",
                    "detail": "",
                },
                status_context="",
                reply_speed=reply_speed,
                companion_context={},
                memory_context="",
            )
            system_prompt = compiled.messages[0]["content"]
            self.assertIn("不设固定句数", system_prompt)
            self.assertIn("本轮表达节奏：自然自适应", system_prompt)
            self.assertIn("不由固定的甜蜜、日常或慢热档位强行改变", system_prompt)
            for phrase in forbidden:
                self.assertNotIn(phrase, system_prompt)
            prompts.append(system_prompt)
        self.assertTrue(all(prompt == prompts[0] for prompt in prompts[1:]))

        app = (ROOT / "web" / "app.jsx").read_text(encoding="utf-8")
        self.assertNotIn('"replySpeed"', app)
        self.assertNotIn('label="回复节奏"', app)
        for marker in (
            "1-2句即可",
            "1-2句、40字以内",
            "1-2句，自然口语",
        ):
            self.assertIn(marker, app)

    def test_formal_edge_fallbacks_are_female(self):
        self.assertTrue(tts_service.TTS_VOICES)
        self.assertNotIn("Yunxi", tts_service.TTS_DEFAULT["voice"])
        for config in tts_service.TTS_VOICES.values():
            self.assertNotIn("Yunxi", config["voice"])

    def test_formal_provider_override_has_priority(self):
        with patch.dict(
            os.environ,
            {"TTS_PROVIDER": "gpt_sovits", "SHULIAN_FORMAL_TTS_PROVIDER": "edge"},
            clear=False,
        ):
            self.assertEqual(tts_service.tts_provider(), "edge")

    def test_voice_service_uses_formal_namespace(self):
        manager = VoiceServiceManager(
            lambda *_: None,
            str(ROOT),
            environ={
                "TTS_PROVIDER": "edge",
                "SHULIAN_FORMAL_TTS_PROVIDER": "gpt_sovits",
                "SHULIAN_FORMAL_GPT_SOVITS_AUTO_START": "1",
            },
        )
        self.assertTrue(manager._is_enabled())


from tests.role_fixtures import role_fixture_hooks
setUpModule, tearDownModule = role_fixture_hooks()


if __name__ == "__main__":
    unittest.main()
