"""Draft trial chat remains separate from the persistent role roster."""

import unittest
from unittest.mock import patch, sentinel

from fastapi.testclient import TestClient

from characters import Character, ROSTER
import chat
from main import app


class RolePreviewTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.profile = {"name": "测试角色", "persona": "安静而认真"}
        self.character = Character(
            id="custom_preview",
            name="测试角色",
            en="",
            persona="安静而认真",
            tags=[],
            cat="自建",
            greet="你好。",
            mood="",
            replies=[],
            system_prompt="你是测试角色。",
        )

    def test_trial_uses_draft_character_without_registering_it(self):
        payload = {
            "profile": self.profile,
            "message": "继续说",
            "history": [
                {"from": "me", "text": "你好"},
                {"from": "them", "text": "你好。"},
            ],
        }
        with patch(
            "shulian_backend.routers.role_preview.build_custom_character",
            return_value=self.character,
        ), patch(
            "shulian_backend.routers.role_preview.chat_backend.get_reply",
            return_value="我在听。",
        ) as get_reply:
            response = self.client.post("/api/role-library/preview-chat", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"reply": "我在听。"})
        self.assertNotIn("custom_preview", ROSTER)
        args, kwargs = get_reply.call_args
        self.assertEqual(args[2], [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好。"},
        ])
        self.assertIs(kwargs["character_override"], self.character)

    def test_chat_backend_accepts_unregistered_draft_character(self):
        with patch("chat.get_character_status", return_value={"date": "2026-09-25"}), \
             patch("chat._compile_messages", return_value=sentinel.compiled) as compile_messages, \
             patch("chat._guarded_completion", return_value="可以聊。"):
            reply = chat.get_reply(
                self.character.id,
                "你好",
                [],
                character_override=self.character,
            )
        self.assertEqual(reply, "可以聊。")
        self.assertIs(compile_messages.call_args.args[0], self.character)
        self.assertNotIn(self.character.id, ROSTER)

    def test_trial_passes_confirmed_memory_and_relationship_without_persistence(self):
        with patch("shulian_backend.routers.role_preview.chat_backend.get_reply", return_value="好。") as reply:
            result = self.client.post("/api/role-library/preview-chat", json={
                "profile": {"name": "海音", "persona": "画家", "relationship": "我们已经结婚十年"},
                "memory": "我喜欢喝乌龙茶。", "message": "我们是什么关系？"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn("乌龙茶", reply.call_args.kwargs["memory_context"])
        self.assertEqual(reply.call_args.kwargs["companion_context"]["relationship"]["level"], 10)
        self.assertNotIn("custom_preview", ROSTER)

    def test_cross_origin_trial_is_rejected_before_model_call(self):
        with patch("shulian_backend.routers.role_preview.chat_backend.get_reply") as get_reply:
            response = self.client.post(
                "/api/role-library/preview-chat",
                json={"profile": self.profile, "message": "你好"},
                headers={"origin": "https://example.invalid"},
            )
        self.assertEqual(response.status_code, 403)
        get_reply.assert_not_called()

    def test_invalid_draft_does_not_call_model(self):
        with patch(
            "shulian_backend.routers.role_preview.build_custom_character",
            side_effect=ValueError("请填写人设"),
        ), patch("shulian_backend.routers.role_preview.chat_backend.get_reply") as get_reply:
            response = self.client.post(
                "/api/role-library/preview-chat",
                json={"profile": self.profile, "message": "你好"},
            )
        self.assertEqual(response.status_code, 422)
        get_reply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
